from __future__ import annotations

import argparse
import hashlib
from collections.abc import Mapping
import errno
import fcntl
import os
import re
import statistics
import sys
import tempfile
import threading
import time
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol
from uuid import UUID, uuid4

import psycopg

from core.db import (
    APPLICATION_NAME_LIMIT_BYTES,
    connection_identity,
    get_connection,
    insert_refresh_run,
    update_refresh_run,
)
from core.types.python.models import REFRESH_PULL_STATUS_RUNNING, RefreshRun
from domains.campaign_finance.ingest.bulk_loader import sync_data_source_metadata

_RUNNER_LOCK_PATH = Path("/var/lock/civibus-refresh-runner.lock")
# Namespace every PostgreSQL session this module opens or scopes, so `pg_stat_activity`
# separates refresh traffic from the rest of the platform's connections.
_CONNECTION_IDENTITY_PREFIX = "refresh:"
# Bytes of blake2b digest appended when a job key is too long to fit verbatim; 4 bytes
# (8 hex chars) keeps collisions negligible while staying inside the byte budget.
_IDENTITY_DIGEST_BYTES = 4
# How often a bounded lock wait re-tries the non-blocking flock.
_RUNNER_LOCK_POLL_SECONDS = 1.0
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _scoped_connection_identity(job_key: str) -> str:
    """Return the job's session identity, bounded to PostgreSQL's application_name limit.

    Job keys are data-driven from source ids, so a long id could push
    ``refresh:<key>`` past the 63-byte ceiling and surface as a spurious ``crashed``
    outcome when the job opens its first connection. When that happens, truncate the
    key and append a short stable digest so distinct over-long keys stay
    distinguishable in ``pg_stat_activity``.
    """
    identity = f"{_CONNECTION_IDENTITY_PREFIX}{job_key}"
    if len(identity.encode("utf-8")) <= APPLICATION_NAME_LIMIT_BYTES:
        return identity

    suffix = f"-{hashlib.blake2b(job_key.encode('utf-8'), digest_size=_IDENTITY_DIGEST_BYTES).hexdigest()}"
    key_byte_budget = APPLICATION_NAME_LIMIT_BYTES - len(_CONNECTION_IDENTITY_PREFIX.encode("utf-8")) - len(suffix)
    truncated_key = job_key.encode("utf-8")[:key_byte_budget].decode("utf-8", errors="ignore")
    return f"{_CONNECTION_IDENTITY_PREFIX}{truncated_key}{suffix}"


_DEGRADED_VOLUME_RATIO_THRESHOLD = 0.5
_DEGRADED_LOOKBACK_DAYS = 30
_SUPPORTED_STATE_CODES = (
    "AL",
    "CA",
    "CO",
    "FL",
    "GA",
    "IL",
    "IN",
    "KY",
    "LA",
    "MA",
    "MN",
    "NC",
    "NE",
    "NJ",
    "NY",
    "OR",
    "PA",
    "TX",
    "VA",
    "WA",
    "WI",
)

_SUPPORTED_CITY_CODES = ("LA", "NYC", "PHL", "SF")

_CITY_JURISDICTION_TYPE = "municipality"

_CADENCE_INTERVALS = {
    "continuous": timedelta(0),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
    "quarterly": timedelta(days=90),
    "annual": timedelta(days=365),
}
_REFRESH_HISTORY_CADENCE_PULL_STATUSES = ("success",)
# main() exits non-zero when any emitted result uses one of these process statuses.
_FAILING_STATUSES = frozenset({"crashed", "degraded", "empty", "failed"})
# How often an in-flight job reports liveness on stdout. Operator aid only: the durable
# in-flight truth is the committed ``running`` row in ``core.refresh_run``.
_HEARTBEAT_INTERVAL_SECONDS = 300.0
_LOCK_KEY_DIGEST_LENGTH = 12
_LOCK_FILENAME_LIMIT = 255
_LOCK_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True, slots=True)
class RunnerParameters:
    fec_cycle: int = 2026
    fec_limit: int = 100
    co_year: int | None = None
    pa_year: int | None = None
    ga_candidate: str = ""
    ga_date_start: str | None = None
    ga_date_end: str | None = None
    nc_committee_docs_path: Path | None = None
    nc_ie_document_index_path: Path | None = None
    nc_date_from: str | None = None
    nc_date_to: str | None = None
    nc_committee_id: str | None = None
    nc_committee_name: str | None = None
    nc_trans_type: str | None = None
    va_year_month: str | None = None
    tx_year_from: int | None = None
    ca_year_from: int | None = None
    year_from: int | None = None
    candidate_listing_path: Path | None = None


@dataclass(frozen=True, slots=True)
class RefreshJob:
    key: str
    domain: str
    jurisdiction: str
    cadence: str
    data_source_names: tuple[str, ...]
    run_callable: Callable[[], object]
    refresh_history_key: str | None = None
    activity_denominator_result_field: str | None = None
    side_effects_repaired_by_job_key: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshRunResult:
    key: str
    status: str
    metadata_updates: int
    message: str
    error: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_now(now: datetime | None) -> datetime:
    return _normalize_datetime(now) if now is not None else _utc_now()


# ---------------------------------------------------------------------------
# Execution engine
# ---------------------------------------------------------------------------


def _build_result(
    *,
    key: str,
    status: str,
    message: str,
    metadata_updates: int = 0,
    error: str | None = None,
) -> RefreshRunResult:
    return RefreshRunResult(
        key=key,
        status=status,
        metadata_updates=metadata_updates,
        message=message,
        error=error,
    )


def should_run_job(job: RefreshJob, *, last_pull_at: datetime | None, now: datetime | None = None) -> bool:
    interval = _CADENCE_INTERVALS.get(job.cadence)
    if interval is None:
        raise ValueError(f"Unsupported cadence: {job.cadence!r}")

    if last_pull_at is None:
        return True

    if interval == timedelta(0):
        return True

    resolved_now = _resolve_now(now)
    resolved_last_pull_at = _normalize_datetime(last_pull_at)
    return resolved_now - resolved_last_pull_at >= interval


def cadence_last_pull_owner(job: RefreshJob) -> Literal["refresh_history", "data_source"]:
    return "refresh_history" if job.refresh_history_key is not None else "data_source"


def _select_data_source_id(
    connection: psycopg.Connection,
    *,
    domain: str,
    jurisdiction: str,
    name: str,
) -> UUID | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (domain, jurisdiction, name),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _select_latest_pull_at(connection: psycopg.Connection, job: RefreshJob) -> datetime | None:
    if cadence_last_pull_owner(job) == "refresh_history":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT MAX(completed_at)
                FROM core.refresh_run
                WHERE job_key = %s
                  AND pull_status = ANY(%s)
                """,
                (job.refresh_history_key, list(_REFRESH_HISTORY_CADENCE_PULL_STATUSES)),
            )
            row = cursor.fetchone()

        if row is None:
            return None
        return row[0]

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT MAX(last_pull_at)
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = ANY(%s)
            """,
            (job.domain, job.jurisdiction, list(job.data_source_names)),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def select_latest_pull_at(connection: psycopg.Connection, job: RefreshJob) -> datetime | None:
    """Return the runner cadence clock for ``job`` using the existing branch selector."""

    return _select_latest_pull_at(connection, job)


def select_latest_completed_run(connection: psycopg.Connection, job: RefreshJob) -> dict[str, object] | None:
    """Return the newest completed refresh-run attempt for ``job`` regardless of status."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT completed_at, pull_status, inserted_count, skipped_count,
                   quarantined_count, superseded_count, error_count, error
            FROM core.refresh_run
            WHERE job_key = %s
              AND completed_at IS NOT NULL
            ORDER BY completed_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (job.key,),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    (
        completed_at,
        pull_status,
        inserted_count,
        skipped_count,
        quarantined_count,
        superseded_count,
        error_count,
        error,
    ) = row
    return {
        "completed_at": completed_at,
        "pull_status": pull_status,
        "inserted_count": inserted_count,
        "skipped_count": skipped_count,
        "quarantined_count": quarantined_count,
        "superseded_count": superseded_count,
        "error_count": error_count,
        "error": error,
    }


def _sync_job_metadata(connection: psycopg.Connection, job: RefreshJob, *, pull_status: str) -> int:
    metadata_updates = 0
    for source_name in job.data_source_names:
        data_source_id = _select_data_source_id(
            connection,
            domain=job.domain,
            jurisdiction=job.jurisdiction,
            name=source_name,
        )
        if data_source_id is None:
            continue
        sync_data_source_metadata(connection, data_source_id, pull_status=pull_status)
        metadata_updates += 1
    return metadata_updates


def _legacy_data_source_pull_status(pull_status: str) -> str:
    if pull_status == "success":
        return "success"
    if pull_status == "crashed":
        return "failed"
    return "partial"


def _dry_run_result(job_key: str) -> RefreshRunResult:
    return _build_result(key=job_key, status="dry_run", message="Dry-run: job not executed")


_LOADER_COUNT_FIELDS = ("inserted", "skipped", "quarantined", "superseded", "errors")
_ACTIVITY_COUNT_FIELDS = ("inserted", "skipped", "quarantined", "superseded")


def _zero_loader_counts() -> dict[str, int]:
    return {field_name: 0 for field_name in _LOADER_COUNT_FIELDS}


def _activity_count(counts: Mapping[str, int]) -> int:
    return sum(counts[field_name] for field_name in _ACTIVITY_COUNT_FIELDS)


def _single_loader_counts(execution_result: object) -> dict[str, int] | None:
    if isinstance(execution_result, Mapping) and all(
        field_name in execution_result for field_name in _LOADER_COUNT_FIELDS
    ):
        return {field_name: int(execution_result[field_name]) for field_name in _LOADER_COUNT_FIELDS}

    if all(hasattr(execution_result, field_name) for field_name in _LOADER_COUNT_FIELDS):
        count_values = {field_name: getattr(execution_result, field_name) for field_name in _LOADER_COUNT_FIELDS}
        if all(isinstance(value, int) for value in count_values.values()):
            return count_values

    if hasattr(execution_result, "result_row_count"):
        result_row_count = getattr(execution_result, "result_row_count")
        if isinstance(result_row_count, int):
            return {
                "inserted": result_row_count,
                "skipped": 0,
                "quarantined": 0,
                "superseded": 0,
                "errors": 0,
            }
    return None


def _loader_counts(execution_result: object | None) -> dict[str, int] | None:
    """Extract loader activity counters from single-file or multi-file loader results."""
    if execution_result is None:
        return None

    if isinstance(execution_result, list):
        aggregate_counts = _zero_loader_counts()
        for item in execution_result:
            item_counts = _single_loader_counts(item)
            if item_counts is None:
                return None
            for field_name in _LOADER_COUNT_FIELDS:
                aggregate_counts[field_name] += item_counts[field_name]
        return aggregate_counts

    return _single_loader_counts(execution_result)


def _result_field_value(execution_result: object, field_name: str) -> object | None:
    if isinstance(execution_result, Mapping):
        return execution_result.get(field_name)
    return getattr(execution_result, field_name, None)


def _nonnegative_int_result_field(execution_result: object, field_name: str) -> int | None:
    value = _result_field_value(execution_result, field_name)
    if type(value) is not int or value < 0:
        return None
    return value


def _format_loader_counts(prefix: str, counts: Mapping[str, int]) -> str:
    return prefix + " ".join(
        f"{field_name}={counts[field_name]}"
        for field_name in ("inserted", "skipped", "quarantined", "superseded", "errors")
    )


def _derive_configured_denominator_pull_status(
    job: RefreshJob,
    execution_result: object | None,
    counts: dict[str, int] | None,
) -> tuple[str, dict[str, int], str] | None:
    denominator_field = job.activity_denominator_result_field
    if denominator_field is None:
        return None

    if counts is None:
        return (
            "degraded",
            _zero_loader_counts(),
            f"Refresh job configured activity denominator but loader counts are unavailable: field={denominator_field}",
        )

    activity_denominator = _nonnegative_int_result_field(execution_result, denominator_field)
    if activity_denominator is None:
        return (
            "degraded",
            counts,
            f"Refresh job configured invalid activity denominator: field={denominator_field}",
        )

    activity_count = _activity_count(counts)
    if counts["errors"] > 0:
        return (
            "degraded",
            counts,
            _format_loader_counts("Refresh job with configured denominator completed with loader errors: ", counts),
        )

    if denominator_field == "due":
        selected_count = _nonnegative_int_result_field(execution_result, "selected")
        processed_count = _nonnegative_int_result_field(execution_result, "processed")
        completed_count = _nonnegative_int_result_field(execution_result, "completed")
        if selected_count is None or processed_count is None or completed_count is None:
            return "degraded", counts, "Refresh job configured invalid enrichment progress summary"
        if selected_count == 0:
            return "degraded", counts, "Refresh job configured empty selected roster"
        if activity_denominator > selected_count or completed_count > activity_denominator:
            return "degraded", counts, "Refresh job configured inconsistent enrichment progress summary"
        if processed_count != selected_count:
            return (
                "degraded",
                counts,
                f"Refresh job did not process selected roster: processed={processed_count} selected={selected_count}",
            )
        # Due and completed are both people counts; loader activity counts individual writes.
        activity_count = completed_count

    if activity_denominator == 0:
        if denominator_field == "due" and activity_count == 0:
            return (
                "success",
                counts,
                _format_loader_counts("Refresh job succeeded: ", counts)
                + f" activity={activity_count} denominator={activity_denominator}",
            )
        return "degraded", counts, f"Refresh job configured invalid activity denominator: field={denominator_field}"
    if activity_count < max(1, int(activity_denominator * _DEGRADED_VOLUME_RATIO_THRESHOLD)):
        return (
            "degraded",
            counts,
            f"Refresh job completed below configured volume threshold: "
            f"activity={activity_count} denominator={activity_denominator}",
        )
    return (
        "success",
        counts,
        _format_loader_counts("Refresh job succeeded: ", counts)
        + f" activity={activity_count} denominator={activity_denominator}",
    )


def _recent_nonempty_activity_counts(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    completed_after: datetime,
) -> list[int]:
    """Return recent processed-row volumes for the job's degraded-volume guard."""
    activity_expression = " + ".join(f"{field_name}_count" for field_name in _ACTIVITY_COUNT_FIELDS)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {activity_expression}
            FROM core.refresh_run
            WHERE job_key = %s
              AND completed_at >= %s
              AND {activity_expression} > 0
              AND pull_status IN ('success', 'degraded')
            ORDER BY completed_at DESC
            """,
            (job.key, completed_after),
        )
        return [row[0] for row in cursor.fetchall()]


def _derive_pull_status(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    execution_error: Exception | None,
    execution_result: object | None,
    completed_at: datetime,
) -> tuple[str, dict[str, int], str]:
    if execution_error is not None:
        return (
            "crashed",
            {"inserted": 0, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 1},
            str(execution_error),
        )

    counts = _loader_counts(execution_result)
    configured_denominator_status = _derive_configured_denominator_pull_status(job, execution_result, counts)
    if configured_denominator_status is not None:
        return configured_denominator_status

    if counts is None:
        return (
            "success",
            {"inserted": 0, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0},
            ("Refresh job succeeded"),
        )

    if (
        counts["inserted"] == 0
        and counts["skipped"] == 0
        and counts["quarantined"] == 0
        and counts["superseded"] == 0
        and counts["errors"] == 0
    ):
        return "empty", counts, "Refresh job completed with no inserted rows"

    if counts["errors"] > 0:
        return (
            "degraded",
            counts,
            _format_loader_counts("Refresh job completed with loader errors: ", counts),
        )

    lookback_floor = completed_at - timedelta(days=_DEGRADED_LOOKBACK_DAYS)
    prior_activity_counts = _recent_nonempty_activity_counts(connection, job, completed_after=lookback_floor)
    activity_count = _activity_count(counts)
    if counts["inserted"] > 0 and prior_activity_counts:
        median_activity_count = int(statistics.median(prior_activity_counts))
        if activity_count < max(1, int(median_activity_count * _DEGRADED_VOLUME_RATIO_THRESHOLD)):
            return (
                "degraded",
                counts,
                f"Refresh job completed below historical volume threshold: activity={activity_count} "
                f"median={median_activity_count}",
            )

    return (
        "success",
        counts,
        _format_loader_counts("Refresh job succeeded: ", counts),
    )


def _build_refresh_run(
    job: RefreshJob,
    *,
    pull_status: str,
    counts: dict[str, int],
    started_at: datetime,
    completed_at: datetime | None,
    metadata_updates: int,
    message: str,
    error: str | None,
    run_id: UUID | None = None,
) -> RefreshRun:
    """Map a job and one attempt outcome onto the core.refresh_run row shape.

    An attempt is written twice — once as `running` and once when it finishes —
    so `run_id` lets the finishing write reuse the identity of the started row.
    """
    return RefreshRun(
        id=run_id if run_id is not None else uuid4(),
        job_key=job.key,
        domain=job.domain,
        jurisdiction=job.jurisdiction,
        data_source_names=list(job.data_source_names),
        pull_status=pull_status,
        started_at=started_at,
        completed_at=completed_at,
        inserted_count=counts["inserted"],
        skipped_count=counts["skipped"],
        quarantined_count=counts["quarantined"],
        superseded_count=counts["superseded"],
        error_count=counts["errors"],
        metadata_updates=metadata_updates,
        message=message,
        error=error,
    )


def _record_refresh_run(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    pull_status: str,
    counts: dict[str, int],
    started_at: datetime,
    completed_at: datetime,
    metadata_updates: int,
    message: str,
    error: str | None,
) -> None:
    """Insert a single-shot terminal refresh-run row that was never in flight."""
    insert_refresh_run(
        connection,
        _build_refresh_run(
            job,
            pull_status=pull_status,
            counts=counts,
            started_at=started_at,
            completed_at=completed_at,
            metadata_updates=metadata_updates,
            message=message,
            error=error,
        ),
    )


def _start_refresh_run(connection: psycopg.Connection, job: RefreshJob, *, started_at: datetime) -> UUID:
    """Commit an in-flight attempt row so the run is visible while the job executes.

    The commit is deliberate and sits outside the per-job transaction boundary: an
    attempt that later fails and rolls back must still leave evidence it was tried.
    """
    refresh_run = _build_refresh_run(
        job,
        pull_status=REFRESH_PULL_STATUS_RUNNING,
        counts=_zero_loader_counts(),
        started_at=started_at,
        completed_at=None,
        metadata_updates=0,
        message="Refresh job started",
        error=None,
    )
    insert_refresh_run(connection, refresh_run)
    connection.commit()
    return refresh_run.id


def _finish_refresh_run(
    connection: psycopg.Connection,
    refresh_run_id: UUID,
    job: RefreshJob,
    *,
    pull_status: str,
    counts: dict[str, int],
    started_at: datetime,
    completed_at: datetime,
    metadata_updates: int,
    message: str,
    error: str | None,
) -> None:
    """Complete the in-flight attempt row in place; the caller owns the commit."""
    update_refresh_run(
        connection,
        _build_refresh_run(
            job,
            pull_status=pull_status,
            counts=counts,
            started_at=started_at,
            completed_at=completed_at,
            metadata_updates=metadata_updates,
            message=message,
            error=error,
            run_id=refresh_run_id,
        ),
    )


def _rollback_quietly(connection: psycopg.Connection) -> None:
    """Discard an aborted transaction without letting cleanup mask the original failure."""
    try:
        connection.rollback()
    except Exception:  # noqa: BLE001
        pass


def _fail_started_attempt(
    connection: psycopg.Connection,
    refresh_run_id: UUID,
    job: RefreshJob,
    *,
    started_at: datetime,
    message: str,
    error: str,
) -> RefreshRunResult:
    """Close an in-flight attempt as failed after orchestration broke, and report it.

    The failure aborted the runner's transaction, so the rollback has to precede the
    UPDATE or Postgres rejects it as InFailedSqlTransaction; that rollback also
    discards the partial writes a failed result is expected to drop. The commit then
    makes the terminal row durable, because the failed result returned here is one
    _finalize_job_transaction would otherwise roll back. Closing the row is
    best-effort: a second failure here must not hide the one being reported.
    """
    try:
        connection.rollback()
        _finish_refresh_run(
            connection,
            refresh_run_id,
            job,
            pull_status="failed",
            counts=_zero_loader_counts(),
            started_at=started_at,
            completed_at=_utc_now(),
            metadata_updates=0,
            message=message,
            error=error,
        )
        connection.commit()
    except Exception:  # noqa: BLE001
        pass
    return _build_result(key=job.key, status="failed", message=message, error=error)


def _format_result_line(result: RefreshRunResult) -> str:
    line = f"{result.key}: status={result.status} metadata_updates={result.metadata_updates} message={result.message}"
    if result.error:
        return f"{line} error={result.error}"
    return line


class _HeartbeatStopEvent(Protocol):
    """The ``threading.Event`` surface a heartbeat worker needs: wait for a tick, or stop."""

    def wait(self, timeout: float) -> bool: ...

    def set(self) -> None: ...


def _new_heartbeat_stop_event() -> _HeartbeatStopEvent:
    """Build the production stop event; a module-level seam so tests can script waits."""
    return threading.Event()


@dataclass(frozen=True, slots=True)
class _HeartbeatAttempt:
    """The immutable in-flight attempt a heartbeat line reports, as the ledger row records it."""

    job_key: str
    refresh_run_id: UUID
    started_at: datetime


def _format_heartbeat_line(attempt: _HeartbeatAttempt, *, elapsed_seconds: int) -> str:
    return (
        f"{attempt.job_key}: heartbeat elapsed_s={elapsed_seconds} "
        f"refresh_run_id={attempt.refresh_run_id} message=Refresh job in flight"
    )


class _JobHeartbeat:
    """Emit periodic liveness lines on a worker thread while a job executes.

    The worker runs alongside a job-owned psycopg transaction, so it reads nothing but
    its injected clock: psycopg connections are not safe to share across threads, and
    the durable in-flight truth is the committed ``running`` ledger row. These lines are
    operator aid and never become results.
    """

    def __init__(
        self,
        attempt: _HeartbeatAttempt,
        *,
        interval_seconds: float,
        now_fn: Callable[[], datetime],
        emit: Callable[[str], None],
        event_factory: Callable[[], _HeartbeatStopEvent],
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError(f"heartbeat interval_seconds must be positive, got {interval_seconds!r}")
        self._attempt = attempt
        self._interval_seconds = interval_seconds
        self._now_fn = now_fn
        self._emit = emit
        self._stop_event = event_factory()
        self._worker = threading.Thread(
            target=self._emit_until_stopped,
            name=f"refresh-heartbeat-{attempt.job_key}",
            daemon=True,
        )

    def __enter__(self) -> _JobHeartbeat:
        self._worker.start()
        return self

    def __exit__(self, *exception_details: object) -> Literal[False]:
        self._stop_event.set()
        self._worker.join()
        return False

    def _emit_until_stopped(self) -> None:
        # ``wait`` returns True only once stop was requested, so every False is one elapsed interval.
        while not self._stop_event.wait(self._interval_seconds):
            self._emit(_format_heartbeat_line(self._attempt, elapsed_seconds=self._elapsed_seconds()))

    def _elapsed_seconds(self) -> int:
        # Anchored on the attempt row's own ``started_at`` so ``elapsed_s`` means the same thing
        # here and in ``core.refresh_run``, rather than drifting by the start-row commit's cost.
        return int((self._now_fn() - self._attempt.started_at).total_seconds())


def _job_heartbeat_context(
    attempt: _HeartbeatAttempt,
    *,
    on_heartbeat: Callable[[str], None] | None,
    interval_seconds: float,
) -> AbstractContextManager[object]:
    """Heartbeat only when an operator surface asked for it; otherwise start no thread."""
    if on_heartbeat is None:
        return nullcontext()
    return _JobHeartbeat(
        attempt,
        interval_seconds=interval_seconds,
        now_fn=_utc_now,
        emit=on_heartbeat,
        event_factory=_new_heartbeat_stop_event,
    )


def _record_result(
    results: list[RefreshRunResult],
    result: RefreshRunResult,
    *,
    on_result: Callable[[RefreshRunResult], None] | None,
) -> None:
    results.append(result)
    if on_result is not None:
        on_result(result)


def _finalize_job_transaction(connection: psycopg.Connection, result: RefreshRunResult) -> None:
    """Persist successful/crashed/degraded runs and roll back failed orchestration writes."""
    if result.status == "failed":
        connection.rollback()
    else:
        connection.commit()


def _run_gated_job(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    last_pull_at: datetime | None,
    now: datetime,
    on_heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> RefreshRunResult:
    if not should_run_job(job, last_pull_at=last_pull_at, now=now):
        return _build_result(key=job.key, status="skipped", message="Skipped by cadence gate")

    return run_job(
        connection,
        job,
        dry_run=False,
        on_heartbeat=on_heartbeat,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )


def _record_repair_pair_alarm(
    connection: psycopg.Connection,
    disturbing_job: RefreshJob,
    repair_job: RefreshJob,
    *,
    last_pull_at_by_key: Mapping[str, datetime | None],
) -> RefreshRunResult:
    disturbing_last_pull_at = last_pull_at_by_key[disturbing_job.key]
    repair_last_pull_at = last_pull_at_by_key[repair_job.key]
    message = (
        f"Repair-pair partial run: disturbing_job={disturbing_job.key} "
        f"last_pull_at={disturbing_last_pull_at.isoformat() if disturbing_last_pull_at else None}; "
        f"repair_job={repair_job.key} "
        f"last_pull_at={repair_last_pull_at.isoformat() if repair_last_pull_at else None}"
    )
    recorded_at = _utc_now()
    try:
        _record_refresh_run(
            connection,
            disturbing_job,
            pull_status="failed",
            counts=_zero_loader_counts(),
            started_at=recorded_at,
            completed_at=recorded_at,
            metadata_updates=0,
            message=message,
            error=message,
        )
        connection.commit()
    except Exception as error:  # noqa: BLE001
        _rollback_quietly(connection)
        return _build_result(
            key=disturbing_job.key,
            status="failed",
            message=message,
            error=f"{message}; alarm ledger recording failed: {error}",
        )
    return _build_result(
        key=disturbing_job.key,
        status="failed",  # Repair-pair alarms must fail the process instead of silently succeeding.
        message=message,
        error=message,
    )


def _append_repair_pair_alarms(
    connection: psycopg.Connection,
    jobs: list[RefreshJob],
    results: list[RefreshRunResult],
    *,
    last_pull_at_by_key: Mapping[str, datetime | None],
    on_result: Callable[[RefreshRunResult], None] | None,
) -> None:
    jobs_by_key = {job.key: job for job in jobs}
    results_by_key = {result.key: result for result in results}
    for disturbing_job in jobs:
        repair_job_key = disturbing_job.side_effects_repaired_by_job_key
        repair_job = jobs_by_key.get(repair_job_key) if repair_job_key is not None else None
        disturbing_result = results_by_key.get(disturbing_job.key)
        repair_result = results_by_key.get(repair_job_key) if repair_job_key is not None else None
        if (
            repair_job is None
            or disturbing_result is None
            or repair_result is None
            or disturbing_result.status != "success"
            or repair_result.status != "skipped"
        ):
            continue

        # A weekly trigger can run the clobbering job while manual recovery keeps
        # its repair job inside the cadence freshness window.
        alarm = _record_repair_pair_alarm(
            connection,
            disturbing_job,
            repair_job,
            last_pull_at_by_key=last_pull_at_by_key,
        )
        _record_result(results, alarm, on_result=on_result)


@dataclass(frozen=True)
class _JobOutcome:
    """What one execution of a job produced, before it is written to the ledger."""

    pull_status: str
    counts: dict[str, int]
    message: str
    completed_at: datetime
    error: Exception | None


def _execute_job(connection: psycopg.Connection, job: RefreshJob) -> _JobOutcome:
    """Run the job's callable and classify what it produced."""
    execution_error: Exception | None = None
    execution_result: object | None = None
    try:
        # Only the callable is scoped: connections it opens are the job's own work. The
        # shared orchestration connection was opened before this scope and keeps its identity.
        with connection_identity(_scoped_connection_identity(job.key)):
            execution_result = job.run_callable()
    except Exception as error:  # noqa: BLE001
        execution_error = error

    completed_at = _utc_now()
    pull_status, counts, message = _derive_pull_status(
        connection,
        job,
        execution_error=execution_error,
        execution_result=execution_result,
        completed_at=completed_at,
    )
    return _JobOutcome(
        pull_status=pull_status,
        counts=counts,
        message=message,
        completed_at=completed_at,
        error=execution_error,
    )


def run_job(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    dry_run: bool = False,
    on_heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> RefreshRunResult:
    """Run one job as a single attempt row: committed as running, then finished in place.

    Only the ``running`` row is committed here. The finishing update rides the caller's
    transaction — ``run_all_jobs`` commits it through ``_finalize_job_transaction`` — so a
    direct caller that never commits leaves the attempt visibly in flight. A dry run writes
    no row at all.
    """
    if dry_run:
        return _dry_run_result(job.key)

    started_at = _utc_now()
    try:
        refresh_run_id = _start_refresh_run(connection, job, started_at=started_at)
    except Exception as start_error:  # noqa: BLE001
        _rollback_quietly(connection)
        return _build_result(
            key=job.key,
            status="failed",
            message="Refresh-run start recording failed",
            error=str(start_error),
        )

    try:
        with _job_heartbeat_context(
            _HeartbeatAttempt(job_key=job.key, refresh_run_id=refresh_run_id, started_at=started_at),
            on_heartbeat=on_heartbeat,
            interval_seconds=heartbeat_interval_seconds,
        ):
            outcome = _execute_job(connection, job)
    except Exception as orchestration_error:  # noqa: BLE001
        return _fail_started_attempt(
            connection,
            refresh_run_id,
            job,
            started_at=started_at,
            message="Refresh execution orchestration failed",
            error=str(orchestration_error),
        )

    metadata_updates = 0
    if outcome.pull_status == "success":
        try:
            metadata_updates = _sync_job_metadata(
                connection,
                job,
                pull_status=_legacy_data_source_pull_status(outcome.pull_status),
            )
        except Exception as metadata_error:  # noqa: BLE001
            return _fail_started_attempt(
                connection,
                refresh_run_id,
                job,
                started_at=started_at,
                message="Metadata sync failed",
                error=str(metadata_error),
            )

    execution_error_text = str(outcome.error) if outcome.error is not None else None
    try:
        _finish_refresh_run(
            connection,
            refresh_run_id,
            job,
            pull_status=outcome.pull_status,
            counts=outcome.counts,
            started_at=started_at,
            completed_at=outcome.completed_at,
            metadata_updates=metadata_updates,
            message=outcome.message,
            error=execution_error_text,
        )
    except Exception as refresh_run_error:  # noqa: BLE001
        return _build_result(
            key=job.key,
            status="failed",
            message="Refresh-run recording failed",
            metadata_updates=metadata_updates,
            error=str(refresh_run_error),
        )

    return _build_result(
        key=job.key,
        status=outcome.pull_status,
        metadata_updates=metadata_updates,
        message=outcome.message,
        error=execution_error_text,
    )


def run_all_jobs(
    connection: psycopg.Connection | None,
    jobs: list[RefreshJob],
    *,
    dry_run: bool = False,
    force: bool = False,
    now: datetime | None = None,
    on_result: Callable[[RefreshRunResult], None] | None = None,
    stop_on_failure: bool = False,
    on_heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> list[RefreshRunResult]:
    if not dry_run and connection is None:
        raise ValueError("run_all_jobs requires a database connection when dry_run=False")

    results: list[RefreshRunResult] = []
    last_pull_at_by_key: dict[str, datetime | None] = {}
    resolved_now = _resolve_now(now)
    for job in jobs:
        if dry_run:
            _record_result(results, _dry_run_result(job.key), on_result=on_result)
            continue

        assert connection is not None  # guarded above
        try:
            last_pull_at = None if force else _select_latest_pull_at(connection, job)
            last_pull_at_by_key[job.key] = last_pull_at
            result = _run_gated_job(
                connection,
                job,
                last_pull_at=last_pull_at,
                now=resolved_now,
                on_heartbeat=on_heartbeat,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
            )
            _finalize_job_transaction(connection, result)
        except Exception as error:  # noqa: BLE001
            try:
                connection.rollback()
            except Exception:
                pass
            result = _build_result(
                key=job.key,
                status="failed",
                message="Refresh orchestration failed",
                error=str(error),
            )
        _record_result(results, result, on_result=on_result)
        if stop_on_failure and result.status in _FAILING_STATUSES:
            break

    if not dry_run:
        assert connection is not None  # guarded above
        _append_repair_pair_alarms(
            connection,
            jobs,
            results,
            last_pull_at_by_key=last_pull_at_by_key,
            on_result=on_result,
        )

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_argument_parser() -> argparse.ArgumentParser:

    def finite_float(raw_value: str) -> float:
        value = float(raw_value)
        if value != value or value in (float("inf"), float("-inf")):
            raise argparse.ArgumentTypeError("--lock-wait-seconds must be a finite number")
        return value

    parser = argparse.ArgumentParser(description="Run campaign-finance refresh jobs from config-driven cadence")
    parser.add_argument(
        "--scope", choices=["all", "priority", "federal"], default="all", help="Refresh scope to execute"
    )
    parser.add_argument(
        "--job-key-prefix",
        dest="job_key_prefixes",
        action="append",
        default=[],
        help="Optional canonical refresh-job key prefix filter; may be repeated",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan and report without executing jobs")
    parser.add_argument("--force", action="store_true", help="Ignore cadence gating and execute all scoped jobs")
    parser.add_argument("--fec-cycle", default=2026, type=int, help="Default FEC cycle")
    parser.add_argument("--fec-limit", default=100, type=int, help="Default FEC row limit")
    parser.add_argument("--co-year", type=int, help="CO year override (defaults to current year)")
    parser.add_argument("--pa-year", type=int, help="PA year override (defaults to current year)")
    parser.add_argument(
        "--tx-year-from",
        type=int,
        help="TX year filter: only load rows from this year onwards (default: current_year - 4)",
    )
    parser.add_argument(
        "--ca-year-from",
        type=int,
        help="CA year filter: only load rows from this year onwards (default: current_year - 4)",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        help="Civics year filter: only load rows from this year onwards (default: current_year - 4)",
    )
    parser.add_argument(
        "--candidate-listing-path",
        type=Path,
        help="Optional NC candidate-listing fixture path override for civics refresh job",
    )
    parser.add_argument("--ga-candidate", default="", help="GA candidate name filter (empty = all candidates)")
    parser.add_argument("--ga-date-start", help="GA date-start filter (MM/DD/YYYY)")
    parser.add_argument("--ga-date-end", help="GA date-end filter (MM/DD/YYYY)")
    parser.add_argument(
        "--nc-committee-docs-path",
        type=Path,
        help="Path to an NC committee-document export required for filing-aware NC refresh jobs",
    )
    parser.add_argument(
        "--nc-ie-document-index-path",
        type=Path,
        help="Path to an NC IE document-index CSV export for the standalone NC IE refresh job",
    )
    parser.add_argument("--nc-date-from", help="NC transaction date-from filter (MM/DD/YYYY)")
    parser.add_argument("--nc-date-to", help="NC transaction date-to filter (MM/DD/YYYY)")
    parser.add_argument("--nc-committee-id", help="NC committee id filter for committee-scoped runner execution")
    parser.add_argument(
        "--nc-committee-name",
        help="NC visible committee name filter for committee-scoped runner execution",
    )
    parser.add_argument("--nc-trans-type", choices=["all", "rec", "exp"], help="NC transaction type filter")
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Skip the global flock guard (only for dry-run or debugging)",
    )
    parser.add_argument(
        "--lock-wait-seconds",
        type=finite_float,
        default=0.0,
        help=(
            "Wait up to this many seconds for the global runner lock before giving up "
            "(default 0: exit immediately when another runner holds it)"
        ),
    )
    return parser


def _acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int | None:
    """Try to acquire the global flock, retrying until ``wait_seconds`` elapses.

    Returns the fd on success, or None when the lock stayed held for the whole
    wait. A zero wait keeps the historical fail-fast behavior; a positive wait
    lets a narrowly scoped run queue behind an unrelated full-scope run on the
    same host instead of being dropped by it.
    """
    if wait_seconds != wait_seconds or wait_seconds in (float("inf"), float("-inf")):
        raise ValueError("wait_seconds must be finite")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN}:
                os.close(fd)
                raise
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            os.close(fd)
            return None
        time.sleep(min(_RUNNER_LOCK_POLL_SECONDS, remaining_seconds))


def _fallback_runner_lock_path() -> Path:
    """Return a same-host lock path for environments where /var/lock is unavailable."""
    return Path(tempfile.gettempdir()) / f"civibus-refresh-runner-{os.getuid()}.lock"


def _runner_lock_path_for_job_key(base_path: Path, job_key: str) -> Path:
    safe_key = _LOCK_SAFE_FILENAME_PATTERN.sub("_", job_key)
    digest = hashlib.sha256(job_key.encode("utf-8")).hexdigest()[:_LOCK_KEY_DIGEST_LENGTH]
    key_component = safe_key if safe_key == job_key else f"{safe_key}-{digest}"
    filename = f"{base_path.stem}-{key_component}{base_path.suffix}"
    if len(filename) <= _LOCK_FILENAME_LIMIT:
        return base_path.with_name(filename)

    digest_suffix = f"-{digest}"
    available_key_length = _LOCK_FILENAME_LIMIT - len(base_path.stem) - len(base_path.suffix) - len(digest_suffix) - 1
    truncated_key = safe_key[: max(0, available_key_length)]
    return base_path.with_name(f"{base_path.stem}-{truncated_key}{digest_suffix}{base_path.suffix}")


def _release_runner_locks(held: list[int]) -> None:
    for fd in held:
        try:
            os.close(fd)
        except OSError:
            pass


def _try_acquire_runner_locks(
    base_path: Path,
    job_keys: tuple[str, ...],
    *,
    wait_seconds: float = 0.0,
) -> list[int] | None:
    held: list[int] = []
    try:
        for job_key in job_keys:
            lock_path = _runner_lock_path_for_job_key(base_path, job_key)
            fd = _acquire_runner_lock(lock_path, wait_seconds=wait_seconds)
            if fd is None:
                print(
                    f"Another refresh runner is already active (lock: {lock_path}). Exiting to avoid VM saturation.",
                    file=sys.stderr,
                )
                _release_runner_locks(held)
                return None
            held.append(fd)
    except OSError:
        _release_runner_locks(held)
        raise
    return held


def _acquire_runner_locks_for_jobs(jobs: list[RefreshJob], *, wait_seconds: float = 0.0) -> list[int] | None:
    """Take one lock per distinct job key, waiting up to ``wait_seconds`` on each.

    The wait is per key rather than a single deadline across the whole set: each key
    is an independent contender, and a run that queued behind one holder should still
    be allowed to queue behind the next rather than be dropped by the elapsed budget.
    """
    job_keys = tuple(sorted({job.key for job in jobs}))
    primary_lock_path = _RUNNER_LOCK_PATH
    try:
        return _try_acquire_runner_locks(primary_lock_path, job_keys, wait_seconds=wait_seconds)
    except OSError as primary_lock_error:
        try:
            fallback_lock_path = _fallback_runner_lock_path()
            fallback_fds = _try_acquire_runner_locks(fallback_lock_path, job_keys, wait_seconds=wait_seconds)
        except OSError as fallback_lock_error:
            print(
                "Refresh runner lock setup failed "
                f"(primary: {primary_lock_path}: {primary_lock_error}; "
                f"fallback: {locals().get('fallback_lock_path', '<unavailable>')}: {fallback_lock_error}).",
                file=sys.stderr,
            )
            return None

        if fallback_fds is not None:
            print(
                "Refresh runner using fallback lock "
                f"(primary: {primary_lock_path}: {primary_lock_error}; "
                f"fallback: {fallback_lock_path}).",
                file=sys.stderr,
            )
        return fallback_fds


def _emit_stdout_line(line: str) -> None:
    """Single owner of runner stdout: escape non-printable characters, then flush one line.

    The heartbeat worker writes here while the job's own thread may also be printing, so the
    line and its terminator go out as one write rather than ``print``'s two — a heartbeat can
    then never split a concurrent line down the middle.
    """
    safe_line = "".join(
        character if character.isprintable() else character.encode("unicode_escape").decode("ascii")
        for character in line
    )
    sys.stdout.write(safe_line + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    from core.refresh.job_builders import build_refresh_plan

    args = build_argument_parser().parse_args(argv)

    parameters = RunnerParameters(
        fec_cycle=args.fec_cycle,
        fec_limit=args.fec_limit,
        co_year=args.co_year,
        pa_year=args.pa_year,
        ga_candidate=args.ga_candidate,
        ga_date_start=args.ga_date_start,
        ga_date_end=args.ga_date_end,
        nc_committee_docs_path=args.nc_committee_docs_path,
        nc_ie_document_index_path=args.nc_ie_document_index_path,
        nc_date_from=args.nc_date_from,
        nc_date_to=args.nc_date_to,
        nc_committee_id=args.nc_committee_id,
        nc_committee_name=args.nc_committee_name,
        nc_trans_type=args.nc_trans_type,
        tx_year_from=args.tx_year_from,
        ca_year_from=args.ca_year_from,
        year_from=args.year_from,
        candidate_listing_path=args.candidate_listing_path,
    )

    jobs = build_refresh_plan(
        scope=args.scope,
        parameters=parameters,
        job_key_prefixes=tuple(args.job_key_prefixes),
    )

    lock_fds: list[int] = []
    try:
        if jobs and not args.dry_run and not args.no_lock:
            acquired_fds = _acquire_runner_locks_for_jobs(jobs, wait_seconds=args.lock_wait_seconds)
            if acquired_fds is None:
                return 2
            lock_fds = acquired_fds

        def _stream_result(result: RefreshRunResult) -> None:
            _emit_stdout_line(_format_result_line(result))

        if args.dry_run:
            results = run_all_jobs(None, jobs, dry_run=True, force=args.force, on_result=_stream_result)
        else:
            connection: psycopg.Connection | None = None
            try:
                connection = get_connection(application_name=f"{_CONNECTION_IDENTITY_PREFIX}runner")
                results = run_all_jobs(
                    connection,
                    jobs,
                    dry_run=False,
                    force=args.force,
                    on_result=_stream_result,
                    stop_on_failure=args.scope == "federal",
                    on_heartbeat=_emit_stdout_line,
                )
            except Exception as error:  # noqa: BLE001
                print(f"Refresh runner failed: {error}", file=sys.stderr)
                return 1
            finally:
                if connection is not None:
                    connection.close()

        return int(any(result.status in _FAILING_STATUSES for result in results))
    finally:
        _release_runner_locks(lock_fds)


if __name__ == "__main__":
    raise SystemExit(main())
