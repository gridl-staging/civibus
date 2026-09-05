from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping
import errno
import fcntl
import os
import re
import signal
import statistics
import sys
import tempfile
import threading
import time
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol, get_args
from uuid import UUID, uuid4

import psycopg

from core.refresh.authority_execution_plan import (
    AuthorityExecutionPlan,
    ExecutionPlanMode,
    load_authority_execution_plan,
    select_execution_plan_jobs,
)
from core.db import (
    APPLICATION_NAME_LIMIT_BYTES,
    build_connection_parameters,
    connection_identity,
    get_connection,
    insert_refresh_run,
    select_refresh_run,
    update_refresh_run,
)
from core.types.python.models import REFRESH_PULL_STATUS_RUNNING, RefreshExecutionOrigin, RefreshRun
from domains.campaign_finance.ingest.bulk_loader import sync_data_source_metadata

_RUNNER_LOCK_PATH = Path("/var/lock/civibus-refresh-runner.lock")
_DATABASE_RUNNER_LOCK_NAMESPACE = "civibus-refresh-runner"
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
_PLANNED_EXECUTION_OPTION_NAMES = Counter({"--authority-plan-json": 1, "--execution-mode": 1, "--execution-origin": 1})
_EXECUTION_ORIGINS = frozenset(get_args(RefreshExecutionOrigin))
_HISTORICAL_RECOVERY_MESSAGE = "Historical orphaned refresh attempt interrupted by operator recovery"
_HISTORICAL_RECOVERY_ERROR = (
    "operator recovery adopted the exact historical attempt after zero-backend quiescence proof"
)
_HISTORICAL_RECOVERY_OPTION_NAMES = frozenset(
    {
        "--recover-app",
        "--recover-authority",
        "--recover-data-source-name",
        "--recover-database-host",
        "--recover-database-name",
        "--recover-database-port",
        "--recover-domain",
        "--recover-execution-origin",
        "--recover-execution-plan",
        "--recover-filing-authority-code",
        "--recover-filing-authority-type",
        "--recover-job-key",
        "--recover-jurisdiction",
        "--recover-machine-id",
        "--recover-postcondition-json",
        "--recover-refresh-run-id",
        "--recover-started-at",
    }
)


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


@dataclass(frozen=True, slots=True)
class HistoricalRefreshRecoveryIdentity:
    """Complete operator-supplied identity for one historical refresh attempt."""

    refresh_run_id: UUID
    job_key: str
    domain: str
    jurisdiction: str
    filing_authority_type: str
    filing_authority_code: str
    data_source_names: tuple[str, ...]
    execution_origin: RefreshExecutionOrigin
    started_at: datetime
    app: str
    machine_id: str
    authority: str
    execution_plan: str
    database_host: str
    database_port: int
    database_name: str


@dataclass(frozen=True, slots=True)
class HistoricalRefreshRecoveryOutcome:
    """Terminal recovery result plus whether an earlier exact invocation owned it."""

    postcondition: dict[str, object]
    already_terminal: bool


@dataclass(frozen=True, slots=True)
class _HistoricalRecoveryQuiescence:
    exact_job_backends: int
    active_refresh_backends: int
    running_refresh_rows: int
    long_idle_transactions: int
    ungranted_locks: int


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
            SELECT completed_at, pull_status, execution_origin, inserted_count, skipped_count,
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
        execution_origin,
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
        "execution_origin": execution_origin,
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
        sync_data_source_metadata(connection, data_source_id, pull_status=pull_status, commit=False)
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

    if counts["errors"] > 0:
        return (
            "degraded",
            counts,
            _format_loader_counts("Refresh job completed with loader errors: ", counts),
        )

    wa_contributions_complete_proof = (
        job.key == "state-wa-contributions"
        and job.domain == "campaign_finance"
        and job.jurisdiction == "state/WA"
        and getattr(execution_result, "source_complete", False) is True
    )
    if wa_contributions_complete_proof:
        source_row_count = getattr(execution_result, "source_row_count", None)
        if type(source_row_count) is not int or source_row_count < 0:
            raise ValueError("complete source proof requires a non-negative integer source_row_count")
        return (
            "success",
            counts,
            f"Refresh job proved complete source rows={source_row_count}: {_format_loader_counts('', counts)}",
        )

    if (
        counts["inserted"] == 0
        and counts["skipped"] == 0
        and counts["quarantined"] == 0
        and counts["superseded"] == 0
        and counts["errors"] == 0
    ):
        return "empty", counts, "Refresh job completed with no inserted rows"

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
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
    run_id: UUID | None = None,
) -> RefreshRun:
    """Map a job and one attempt outcome onto the core.refresh_run row shape.

    An attempt is written twice — once as `running` and once when it finishes —
    so `run_id` lets the finishing write reuse the identity of the started row.
    """
    _validate_execution_origin(execution_origin)
    return RefreshRun(
        id=run_id if run_id is not None else uuid4(),
        job_key=job.key,
        domain=job.domain,
        jurisdiction=job.jurisdiction,
        data_source_names=list(job.data_source_names),
        execution_origin=execution_origin,
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
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
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
            execution_origin=execution_origin,
        ),
    )


def _start_refresh_run(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    started_at: datetime,
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
) -> UUID:
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
        execution_origin=execution_origin,
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
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
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
            execution_origin=execution_origin,
            run_id=refresh_run_id,
        ),
    )


def _rollback_quietly(connection: psycopg.Connection) -> None:
    """Discard an aborted transaction without letting cleanup mask the original failure."""
    try:
        connection.rollback()
    except Exception:  # noqa: BLE001
        pass


def _select_started_attempt_for_update(
    connection: psycopg.Connection,
    refresh_run_id: UUID,
) -> RefreshRun | None:
    """Lock and load the one attempt row before a terminal transition."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM core.refresh_run WHERE id = %s FOR UPDATE",
            (refresh_run_id,),
        )
        if cursor.fetchone() is None:
            return None
    return select_refresh_run(connection, refresh_run_id)


def _require_exact_started_attempt(
    stored: RefreshRun | None,
    *,
    refresh_run_id: UUID,
    job: RefreshJob,
    started_at: datetime,
    execution_origin: RefreshExecutionOrigin,
) -> None:
    """Refuse a missing, foreign, or already-terminal attempt before updating it."""
    if stored is None or stored.id != refresh_run_id:
        raise RuntimeError("exact started refresh attempt is missing")
    if (
        stored.job_key != job.key
        or stored.domain != job.domain
        or stored.jurisdiction != job.jurisdiction
        or tuple(stored.data_source_names) != job.data_source_names
        or stored.started_at != started_at
    ):
        raise RuntimeError("started refresh attempt job identity mismatch")
    if stored.execution_origin != execution_origin:
        raise RuntimeError("started refresh attempt execution origin mismatch")
    if stored.pull_status != REFRESH_PULL_STATUS_RUNNING or stored.completed_at is not None:
        raise RuntimeError("started refresh attempt is already terminal")


def _validate_historical_recovery_identity(identity: HistoricalRefreshRecoveryIdentity) -> None:
    text_fields = {
        "job key": identity.job_key,
        "domain": identity.domain,
        "jurisdiction": identity.jurisdiction,
        "filing authority type": identity.filing_authority_type,
        "filing authority code": identity.filing_authority_code,
        "app": identity.app,
        "machine id": identity.machine_id,
        "authority": identity.authority,
        "execution plan": identity.execution_plan,
        "database host": identity.database_host,
        "database name": identity.database_name,
    }
    for field_name, value in text_fields.items():
        if not value or value != value.strip():
            raise ValueError(f"historical recovery {field_name} must be nonblank and trimmed")
    if not identity.data_source_names or any(
        not value or value != value.strip() for value in identity.data_source_names
    ):
        raise ValueError("historical recovery requires nonblank trimmed data-source names")
    if len(set(identity.data_source_names)) != len(identity.data_source_names):
        raise ValueError("historical recovery data-source names must be unique")
    if identity.execution_origin != "operator_attended":
        raise ValueError("historical recovery requires execution_origin='operator_attended'")
    if identity.started_at.tzinfo is None or identity.started_at.utcoffset() is None:
        raise ValueError("historical recovery started_at must be timezone-aware")
    expected_authority = f"{identity.filing_authority_type}/{identity.filing_authority_code}"
    if identity.authority != expected_authority or identity.jurisdiction != expected_authority:
        raise ValueError("historical recovery authority and jurisdiction identity mismatch")
    if re.fullmatch(r"[0-9a-f]+", identity.machine_id) is None:
        raise ValueError("historical recovery machine id must be lowercase hexadecimal")
    if (
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            str(identity.refresh_run_id),
        )
        is None
    ):
        raise ValueError("historical recovery refresh-run id is not lifecycle-consumable")
    if identity.database_port < 1 or identity.database_port > 65535:
        raise ValueError("historical recovery database port is invalid")


def _classify_historical_recovery_attempt(
    stored: RefreshRun | None,
    identity: HistoricalRefreshRecoveryIdentity,
) -> Literal["running", "already_recovered"]:
    """Accept only the exact running orphan or this owner's exact terminal result."""
    _validate_historical_recovery_identity(identity)
    if stored is None:
        raise RuntimeError("exact historical refresh attempt is missing")
    if stored.id != identity.refresh_run_id:
        raise RuntimeError("historical refresh attempt identity mismatch")
    if (
        stored.job_key != identity.job_key
        or stored.domain != identity.domain
        or stored.jurisdiction != identity.jurisdiction
        or tuple(stored.data_source_names) != identity.data_source_names
    ):
        raise RuntimeError("historical refresh attempt job identity mismatch")
    if stored.execution_origin != identity.execution_origin:
        raise RuntimeError("historical refresh attempt execution origin mismatch")
    if _normalize_datetime(stored.started_at) != _normalize_datetime(identity.started_at):
        raise RuntimeError("historical refresh attempt started_at mismatch")

    zero_outcome = (
        stored.inserted_count == 0
        and stored.skipped_count == 0
        and stored.quarantined_count == 0
        and stored.superseded_count == 0
        and stored.error_count == 0
        and stored.metadata_updates == 0
    )
    if stored.pull_status == REFRESH_PULL_STATUS_RUNNING and stored.completed_at is None:
        if not zero_outcome or stored.message != "Refresh job started" or stored.error is not None:
            raise RuntimeError("historical running refresh attempt outcome identity mismatch")
        return "running"
    if (
        stored.pull_status == "failed"
        and stored.completed_at is not None
        and zero_outcome
        and stored.message == _HISTORICAL_RECOVERY_MESSAGE
        and stored.error == _HISTORICAL_RECOVERY_ERROR
    ):
        return "already_recovered"
    raise RuntimeError("historical refresh attempt is already terminal under another owner")


def _select_historical_recovery_data_source_rows(
    connection: psycopg.Connection,
    identity: HistoricalRefreshRecoveryIdentity,
) -> list[tuple[str, str | None, str | None]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT name, filing_authority_type, filing_authority_code
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = ANY(%s)
            ORDER BY name, id
            """,
            (identity.domain, identity.jurisdiction, list(identity.data_source_names)),
        )
        return list(cursor.fetchall())


def _require_historical_recovery_data_source_identity(
    rows: list[tuple[str, str | None, str | None]],
    identity: HistoricalRefreshRecoveryIdentity,
) -> None:
    if not rows:
        raise RuntimeError("historical recovery data-source identity is missing")
    names = [row[0] for row in rows]
    if len(names) != len(set(names)) or len(rows) > len(identity.data_source_names):
        raise RuntimeError("historical recovery data-source identity is ambiguous")
    if set(names) != set(identity.data_source_names) or len(rows) != len(identity.data_source_names):
        raise RuntimeError("historical recovery data-source identity mismatch")
    if any(
        authority_type != identity.filing_authority_type or authority_code != identity.filing_authority_code
        for _, authority_type, authority_code in rows
    ):
        raise RuntimeError("historical recovery filing authority identity mismatch")


def _read_historical_recovery_quiescence(
    connection: psycopg.Connection,
    identity: HistoricalRefreshRecoveryIdentity,
) -> _HistoricalRecoveryQuiescence:
    exact_application_name = _scoped_connection_identity(identity.job_key)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              (SELECT count(*)::integer
               FROM pg_stat_activity
               WHERE pid <> pg_backend_pid()
                 AND datname = current_database()
                 AND backend_type = 'client backend'
                 AND application_name = %s),
              (SELECT count(*)::integer
               FROM pg_stat_activity
               WHERE pid <> pg_backend_pid()
                 AND datname = current_database()
                 AND backend_type = 'client backend'
                 AND application_name LIKE 'refresh:%%'),
              (SELECT count(*)::integer
               FROM core.refresh_run
               WHERE pull_status = 'running'),
              (SELECT count(*)::integer
               FROM pg_stat_activity
               WHERE pid <> pg_backend_pid()
                 AND datname = current_database()
                 AND state LIKE 'idle in transaction%%'
                 AND xact_start < now() - interval '30 minutes'),
              (SELECT count(*)::integer
               FROM pg_locks
               WHERE NOT granted
                 AND pid <> pg_backend_pid()
                 AND (database = 0 OR database = (SELECT oid FROM pg_database WHERE datname = current_database())))
            """,
            (exact_application_name,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("historical recovery quiescence proof returned no row")
    return _HistoricalRecoveryQuiescence(*row)


def _require_historical_recovery_quiescence(
    proof: _HistoricalRecoveryQuiescence,
    *,
    expected_running_refresh_rows: int,
) -> None:
    if proof.exact_job_backends != 0:
        raise RuntimeError("exact historical refresh job still has an active backend")
    if proof.active_refresh_backends != 0:
        raise RuntimeError("conflicting refresh backend remains active")
    if proof.running_refresh_rows != expected_running_refresh_rows:
        raise RuntimeError(
            "historical recovery running-row quiescence mismatch; "
            f"expected {expected_running_refresh_rows}, found {proof.running_refresh_rows}"
        )
    if proof.long_idle_transactions != 0:
        raise RuntimeError("long-idle database transactions block historical recovery")
    if proof.ungranted_locks != 0:
        raise RuntimeError("ungranted database locks block historical recovery")


def _require_historical_recovery_database_identity(
    connection: psycopg.Connection,
    identity: HistoricalRefreshRecoveryIdentity,
) -> None:
    parameters = build_connection_parameters()
    configured = (
        str(parameters["host"]),
        int(parameters["port"]),
        str(parameters["dbname"]),
    )
    expected = (identity.database_host, identity.database_port, identity.database_name)
    if configured != expected:
        raise RuntimeError(
            "historical recovery database connection identity mismatch; "
            f"expected {expected!r}, configured {configured!r}"
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if row != (identity.database_name,):
        raise RuntimeError("historical recovery connected database identity mismatch")


def _try_acquire_historical_recovery_advisory_lock(
    connection: psycopg.Connection,
    identity: HistoricalRefreshRecoveryIdentity,
) -> bool:
    lock_name = f"{_DATABASE_RUNNER_LOCK_NAMESPACE}:{identity.job_key}"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
            (lock_name,),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _select_historical_recovery_attempt_for_update(
    connection: psycopg.Connection,
    refresh_run_id: UUID,
) -> RefreshRun | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM core.refresh_run WHERE id = %s FOR UPDATE NOWAIT",
            (refresh_run_id,),
        )
        if cursor.fetchone() is None:
            return None
    return select_refresh_run(connection, refresh_run_id)


def _serialize_refresh_postcondition(postcondition: Mapping[str, object]) -> str:
    return json.dumps(postcondition, sort_keys=True) + "\n"


def build_historical_recovery_postcondition(
    identity: HistoricalRefreshRecoveryIdentity,
    attempt: RefreshRun,
    *,
    running_refresh_rows: int,
    active_refresh_backends: int,
    long_idle_transactions: int,
    ungranted_locks: int,
) -> dict[str, object]:
    if _classify_historical_recovery_attempt(attempt, identity) != "already_recovered":
        raise RuntimeError("historical recovery postcondition requires the exact recovered terminal attempt")
    assert attempt.completed_at is not None
    completed_at = _normalize_datetime(attempt.completed_at).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "app": identity.app,
        "machine_id": identity.machine_id,
        "authority": identity.authority,
        "execution_plan": identity.execution_plan,
        "refresh_run_id": str(identity.refresh_run_id),
        "job_key": identity.job_key,
        "execution_origin": identity.execution_origin,
        "pull_status": attempt.pull_status,
        "completed_at": completed_at,
        "metadata_updates": attempt.metadata_updates,
        "running_refresh_rows": running_refresh_rows,
        "active_refresh_backends": active_refresh_backends,
        "long_idle_transactions": long_idle_transactions,
        "ungranted_locks": ungranted_locks,
        "database": {
            "host": identity.database_host,
            "port": identity.database_port,
            "name": identity.database_name,
        },
    }


def recover_historical_refresh_attempt(
    connection: psycopg.Connection,
    identity: HistoricalRefreshRecoveryIdentity,
    *,
    completed_at: datetime | None = None,
) -> HistoricalRefreshRecoveryOutcome:
    """Adopt one exact orphan only after preflight and in-lock quiescence reproof."""
    _validate_historical_recovery_identity(identity)
    try:
        _require_historical_recovery_database_identity(connection, identity)
        preflight_attempt = select_refresh_run(connection, identity.refresh_run_id)
        preflight_state = _classify_historical_recovery_attempt(preflight_attempt, identity)
        data_source_rows = _select_historical_recovery_data_source_rows(connection, identity)
        _require_historical_recovery_data_source_identity(data_source_rows, identity)
        expected_running_rows = 1 if preflight_state == "running" else 0
        preflight_quiescence = _read_historical_recovery_quiescence(connection, identity)
        _require_historical_recovery_quiescence(
            preflight_quiescence,
            expected_running_refresh_rows=expected_running_rows,
        )

        if not _try_acquire_historical_recovery_advisory_lock(connection, identity):
            raise RuntimeError("historical recovery advisory lock is held by another refresh owner")
        try:
            locked_attempt = _select_historical_recovery_attempt_for_update(
                connection,
                identity.refresh_run_id,
            )
        except psycopg.errors.LockNotAvailable as error:
            raise RuntimeError("historical recovery row lock is held by another owner") from error
        locked_state = _classify_historical_recovery_attempt(locked_attempt, identity)
        if locked_attempt != preflight_attempt or locked_state != preflight_state:
            raise RuntimeError("historical refresh attempt changed after preflight")
        locked_data_source_rows = _select_historical_recovery_data_source_rows(connection, identity)
        if locked_data_source_rows != data_source_rows:
            raise RuntimeError("historical recovery data-source identity changed after preflight")
        _require_historical_recovery_data_source_identity(locked_data_source_rows, identity)
        locked_quiescence = _read_historical_recovery_quiescence(connection, identity)
        _require_historical_recovery_quiescence(
            locked_quiescence,
            expected_running_refresh_rows=expected_running_rows,
        )

        already_terminal = locked_state == "already_recovered"
        if not already_terminal:
            job = RefreshJob(
                key=identity.job_key,
                domain=identity.domain,
                jurisdiction=identity.jurisdiction,
                cadence="continuous",
                data_source_names=identity.data_source_names,
                run_callable=lambda: None,
            )
            _finish_refresh_run(
                connection,
                identity.refresh_run_id,
                job,
                pull_status="failed",
                counts=_zero_loader_counts(),
                started_at=_normalize_datetime(identity.started_at),
                completed_at=_normalize_datetime(completed_at) if completed_at is not None else _utc_now(),
                metadata_updates=0,
                message=_HISTORICAL_RECOVERY_MESSAGE,
                error=_HISTORICAL_RECOVERY_ERROR,
                execution_origin=identity.execution_origin,
            )
        connection.commit()

        terminal_attempt = select_refresh_run(connection, identity.refresh_run_id)
        if _classify_historical_recovery_attempt(terminal_attempt, identity) != "already_recovered":
            raise RuntimeError("historical recovery terminal postcondition identity mismatch")
        final_data_source_rows = _select_historical_recovery_data_source_rows(connection, identity)
        _require_historical_recovery_data_source_identity(final_data_source_rows, identity)
        final_quiescence = _read_historical_recovery_quiescence(connection, identity)
        _require_historical_recovery_quiescence(final_quiescence, expected_running_refresh_rows=0)
        assert terminal_attempt is not None
        postcondition = build_historical_recovery_postcondition(
            identity,
            terminal_attempt,
            running_refresh_rows=final_quiescence.running_refresh_rows,
            active_refresh_backends=final_quiescence.active_refresh_backends,
            long_idle_transactions=final_quiescence.long_idle_transactions,
            ungranted_locks=final_quiescence.ungranted_locks,
        )
        connection.rollback()
        return HistoricalRefreshRecoveryOutcome(
            postcondition=postcondition,
            already_terminal=already_terminal,
        )
    except Exception:
        _rollback_quietly(connection)
        raise


def persist_historical_recovery_postcondition(
    path: Path,
    postcondition: Mapping[str, object],
) -> None:
    """Atomically create the lifecycle-owned byte-exact postcondition without overwrite."""
    if not path.is_absolute():
        raise RuntimeError("historical recovery postcondition path must be absolute")
    serialized = _serialize_refresh_postcondition(postcondition)
    if path.exists() or path.is_symlink():
        if path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") == serialized:
            return
        raise RuntimeError("historical recovery postcondition path already exists with different content")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise RuntimeError("historical recovery postcondition parent must be an existing regular directory")

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".historical-refresh-recovery-",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", closefd=True) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.link(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


class _ControlledRefreshSignal(BaseException):
    """Internal non-Exception escape so job error classification cannot consume a stop."""

    def __init__(self, signal_number: int) -> None:
        self.signal_number = signal_number
        super().__init__(signal.Signals(signal_number).name)


@dataclass(slots=True)
class _StartedAttemptSignalState:
    signal_number: int | None = None


@contextmanager
def _started_attempt_signal_scope() -> Iterator[_StartedAttemptSignalState]:
    """Install controlled stop handlers only while a committed attempt is active.

    Python delivers signals on the main thread. Direct ``run_job`` callers on a worker
    thread therefore retain the process's handlers and cannot pretend to own a signal.
    A repeated controlled signal is a no-op while the first one is unwinding and closing
    the exact attempt, which keeps terminal finalization one-shot.
    """
    if threading.current_thread() is not threading.main_thread():
        yield _StartedAttemptSignalState()
        return

    state = _StartedAttemptSignalState()
    previous_handlers = {
        signal_number: signal.getsignal(signal_number) for signal_number in (signal.SIGTERM, signal.SIGINT)
    }

    def _interrupt(signal_number: int, _frame: object) -> None:
        if state.signal_number is not None:
            return
        state.signal_number = signal_number
        raise _ControlledRefreshSignal(signal_number)

    try:
        for signal_number in previous_handlers:
            signal.signal(signal_number, _interrupt)
        yield state
    finally:
        for signal_number, previous_handler in previous_handlers.items():
            signal.signal(signal_number, previous_handler)


def _fail_started_attempt(
    connection: psycopg.Connection,
    refresh_run_id: UUID,
    job: RefreshJob,
    *,
    started_at: datetime,
    message: str,
    error: str,
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
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
        stored_attempt = _select_started_attempt_for_update(connection, refresh_run_id)
        _require_exact_started_attempt(
            stored_attempt,
            refresh_run_id=refresh_run_id,
            job=job,
            started_at=started_at,
            execution_origin=execution_origin,
        )
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
            execution_origin=execution_origin,
        )
        connection.commit()
    except Exception as finalization_error:  # noqa: BLE001
        _rollback_quietly(connection)
        return _build_result(
            key=job.key,
            status="failed",
            message=message,
            error=f"{error}; terminal finalization refused: {finalization_error}",
        )
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
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
    execution_plan: AuthorityExecutionPlan | None = None,
    execution_mode: ExecutionPlanMode | None = None,
    on_heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> RefreshRunResult:
    if not should_run_job(job, last_pull_at=last_pull_at, now=now):
        return _build_result(key=job.key, status="skipped", message="Skipped by cadence gate")

    planned_kwargs = (
        {"execution_plan": execution_plan, "execution_mode": execution_mode} if execution_plan is not None else {}
    )
    return run_job(
        connection,
        job,
        dry_run=False,
        execution_origin=execution_origin,
        on_heartbeat=on_heartbeat,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        **planned_kwargs,
    )


def _record_repair_pair_alarm(
    connection: psycopg.Connection,
    disturbing_job: RefreshJob,
    repair_job: RefreshJob,
    *,
    last_pull_at_by_key: Mapping[str, datetime | None],
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
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
            execution_origin=execution_origin,
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
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
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
            execution_origin=execution_origin,
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
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
    execution_plan: AuthorityExecutionPlan | None = None,
    execution_mode: ExecutionPlanMode | None = None,
    on_heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> RefreshRunResult:
    """Run one job as a single attempt row: committed as running, then finished in place.

    Only the ``running`` row is committed here. The finishing update rides the caller's
    transaction — ``run_all_jobs`` commits it through ``_finalize_job_transaction`` — so a
    direct caller that never commits leaves the attempt visibly in flight. A dry run writes
    no row at all.
    """
    _validate_execution_origin_for_jobs(
        execution_origin,
        [job],
        dry_run=dry_run,
        execution_plan=execution_plan,
        execution_mode=execution_mode,
    )
    if dry_run:
        return _dry_run_result(job.key)

    started_at = _utc_now()
    try:
        refresh_run_id = _start_refresh_run(
            connection,
            job,
            started_at=started_at,
            execution_origin=execution_origin,
        )
    except Exception as start_error:  # noqa: BLE001
        _rollback_quietly(connection)
        return _build_result(
            key=job.key,
            status="failed",
            message="Refresh-run start recording failed",
            error=str(start_error),
        )

    with _started_attempt_signal_scope():
        try:
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
                    execution_origin=execution_origin,
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
                        execution_origin=execution_origin,
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
                    execution_origin=execution_origin,
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
        except _ControlledRefreshSignal as interrupted:
            signal_name = signal.Signals(interrupted.signal_number).name
            return _fail_started_attempt(
                connection,
                refresh_run_id,
                job,
                started_at=started_at,
                message=f"Refresh attempt interrupted by {signal_name}",
                error=f"controlled {signal_name} interrupted the active refresh attempt",
                execution_origin=execution_origin,
            )


def run_all_jobs(
    connection: psycopg.Connection | None,
    jobs: list[RefreshJob],
    *,
    dry_run: bool = False,
    force: bool = False,
    execution_origin: RefreshExecutionOrigin = "legacy_unknown",
    execution_plan: AuthorityExecutionPlan | None = None,
    execution_mode: ExecutionPlanMode | None = None,
    now: datetime | None = None,
    on_result: Callable[[RefreshRunResult], None] | None = None,
    stop_on_failure: bool = False,
    on_heartbeat: Callable[[str], None] | None = None,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> list[RefreshRunResult]:
    _validate_execution_origin_for_jobs(
        execution_origin,
        jobs,
        dry_run=dry_run,
        force=force,
        execution_plan=execution_plan,
        execution_mode=execution_mode,
        require_complete_mode_plan=True,
    )
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
                execution_origin=execution_origin,
                execution_plan=execution_plan,
                execution_mode=execution_mode,
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
            execution_origin=execution_origin,
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

    def aware_datetime(raw_value: str) -> datetime:
        try:
            value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError as error:
            raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from error
        if value.tzinfo is None or value.utcoffset() is None:
            raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
        return value.astimezone(timezone.utc)

    parser = argparse.ArgumentParser(description="Run campaign-finance refresh jobs from config-driven cadence")
    parser.add_argument(
        "--scope", choices=["all", "priority", "federal"], default="all", help="Refresh scope to execute"
    )
    parser.add_argument(
        "--execution-origin",
        choices=["scheduled", "operator_attended"],
        default="legacy_unknown",
        help="Explicit invocation lineage; omission remains legacy_unknown",
    )
    parser.add_argument(
        "--job-key-prefix",
        dest="job_key_prefixes",
        action="append",
        default=[],
        help="Optional canonical refresh-job key prefix filter; may be repeated",
    )
    parser.add_argument(
        "--authority-plan-json",
        type=Path,
        help="Authority-scoped operations profile containing the exact typed execution plan",
    )
    parser.add_argument(
        "--execution-mode",
        choices=["scheduled", "canary"],
        help="Exact execution-plan mode; requires --authority-plan-json",
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
    recovery_group = parser.add_argument_group("historical refresh recovery")
    recovery_group.add_argument("--recover-refresh-run-id", type=UUID)
    recovery_group.add_argument("--recover-job-key")
    recovery_group.add_argument("--recover-domain")
    recovery_group.add_argument("--recover-jurisdiction")
    recovery_group.add_argument("--recover-filing-authority-type")
    recovery_group.add_argument("--recover-filing-authority-code")
    recovery_group.add_argument("--recover-data-source-name", action="append", default=[])
    recovery_group.add_argument(
        "--recover-execution-origin",
        choices=["operator_attended"],
    )
    recovery_group.add_argument("--recover-started-at", type=aware_datetime)
    recovery_group.add_argument("--recover-app")
    recovery_group.add_argument("--recover-machine-id")
    recovery_group.add_argument("--recover-authority")
    recovery_group.add_argument("--recover-execution-plan")
    recovery_group.add_argument("--recover-database-host")
    recovery_group.add_argument("--recover-database-port", type=int)
    recovery_group.add_argument("--recover-database-name")
    recovery_group.add_argument("--recover-postcondition-json", type=Path)
    return parser


def _historical_recovery_identity_from_cli(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    raw_argv: list[str],
) -> tuple[HistoricalRefreshRecoveryIdentity, Path] | None:
    option_names = [token.split("=", 1)[0] for token in raw_argv if token.startswith("--")]
    recovery_requested = any(option_name in _HISTORICAL_RECOVERY_OPTION_NAMES for option_name in option_names)
    if not recovery_requested:
        return None
    unexpected = sorted(set(option_names) - _HISTORICAL_RECOVERY_OPTION_NAMES)
    if unexpected:
        parser.error(f"historical refresh recovery accepts only recovery options; found {unexpected!r}")
    missing = sorted(_HISTORICAL_RECOVERY_OPTION_NAMES - set(option_names))
    if missing:
        parser.error(f"historical refresh recovery requires the complete option set; missing {missing!r}")
    duplicate_singletons = sorted(
        option_name
        for option_name in _HISTORICAL_RECOVERY_OPTION_NAMES - {"--recover-data-source-name"}
        if option_names.count(option_name) != 1
    )
    if duplicate_singletons:
        parser.error(f"historical refresh recovery options must appear exactly once: {duplicate_singletons!r}")
    if option_names.count("--recover-data-source-name") < 1:
        parser.error("historical refresh recovery requires at least one data-source name")

    assert args.recover_refresh_run_id is not None
    assert args.recover_started_at is not None
    assert args.recover_database_port is not None
    assert args.recover_postcondition_json is not None
    identity = HistoricalRefreshRecoveryIdentity(
        refresh_run_id=args.recover_refresh_run_id,
        job_key=args.recover_job_key,
        domain=args.recover_domain,
        jurisdiction=args.recover_jurisdiction,
        filing_authority_type=args.recover_filing_authority_type,
        filing_authority_code=args.recover_filing_authority_code,
        data_source_names=tuple(args.recover_data_source_name),
        execution_origin=args.recover_execution_origin,
        started_at=args.recover_started_at,
        app=args.recover_app,
        machine_id=args.recover_machine_id,
        authority=args.recover_authority,
        execution_plan=args.recover_execution_plan,
        database_host=args.recover_database_host,
        database_port=args.recover_database_port,
        database_name=args.recover_database_name,
    )
    try:
        _validate_historical_recovery_identity(identity)
    except ValueError as error:
        parser.error(str(error))
    return identity, args.recover_postcondition_json


def _run_historical_recovery_cli(
    identity: HistoricalRefreshRecoveryIdentity,
    postcondition_path: Path,
) -> int:
    connection: psycopg.Connection | None = None
    try:
        connection = get_connection(
            application_name=_scoped_connection_identity(f"recovery-{identity.job_key}"),
        )
        outcome = recover_historical_refresh_attempt(connection, identity)
        persist_historical_recovery_postcondition(postcondition_path, outcome.postcondition)
        disposition = "already_terminal" if outcome.already_terminal else "recovered"
        _emit_stdout_line(
            f"{identity.job_key}: status=failed metadata_updates=0 "
            f"message=Historical refresh attempt {disposition} "
            f"refresh_run_id={identity.refresh_run_id} postcondition={postcondition_path}"
        )
        return 0
    except Exception as error:  # noqa: BLE001
        print(f"Historical refresh recovery refused: {error}", file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()


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


def _runner_lock_keys_for_jobs(
    jobs: list[RefreshJob],
    *,
    authority_ownership_lock_key: str | None = None,
) -> tuple[str, ...]:
    lock_keys = {job.key for job in jobs}
    if authority_ownership_lock_key is not None:
        lock_keys.add(authority_ownership_lock_key)
    return tuple(sorted(lock_keys))


def _acquire_runner_locks_for_jobs(
    jobs: list[RefreshJob],
    *,
    wait_seconds: float = 0.0,
    authority_ownership_lock_key: str | None = None,
) -> list[int] | None:
    """Take one lock per distinct job key, waiting up to ``wait_seconds`` on each.

    The wait is per key rather than a single deadline across the whole set: each key
    is an independent contender, and a run that queued behind one holder should still
    be allowed to queue behind the next rather than be dropped by the elapsed budget.
    """
    job_keys = _runner_lock_keys_for_jobs(
        jobs,
        authority_ownership_lock_key=authority_ownership_lock_key,
    )
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


def _try_acquire_database_runner_locks(
    connection: psycopg.Connection,
    jobs: list[RefreshJob],
    *,
    authority_ownership_lock_key: str | None = None,
) -> bool:
    """Take nonblocking session locks for the exact selected job keys.

    The local ``flock`` guard prevents same-host overlap. These PostgreSQL locks
    close the cross-host gap while retaining per-job isolation. They must be
    session-scoped because the runner commits its visible ``running`` receipt
    before executing the job; transaction-scoped locks would be released then.
    Closing ``connection`` releases every acquired lock, including earlier keys
    when a later key is contended.
    """
    job_keys = _runner_lock_keys_for_jobs(
        jobs,
        authority_ownership_lock_key=authority_ownership_lock_key,
    )
    with connection.cursor() as cursor:
        for job_key in job_keys:
            lock_name = f"{_DATABASE_RUNNER_LOCK_NAMESPACE}:{job_key}"
            cursor.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                (lock_name,),
            )
            row = cursor.fetchone()
            if not row or not bool(row[0]):
                print(
                    "Another refresh runner is already active "
                    f"(database lock: {job_key}). Exiting to avoid concurrent same-job writes.",
                    file=sys.stderr,
                )
                return False
    return True


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


def _validate_execution_origin(execution_origin: str) -> None:
    if execution_origin not in _EXECUTION_ORIGINS:
        raise ValueError(f"Unsupported execution origin: {execution_origin!r}")


def _validate_execution_origin_for_jobs(
    execution_origin: str,
    jobs: list[RefreshJob],
    *,
    dry_run: bool = False,
    force: bool = False,
    execution_plan: AuthorityExecutionPlan | None = None,
    execution_mode: ExecutionPlanMode | None = None,
    require_complete_mode_plan: bool = False,
) -> None:
    _validate_execution_origin(execution_origin)
    if execution_plan is None:
        if execution_mode is not None:
            raise ValueError("execution mode requires an authority execution plan")
        if execution_origin == "scheduled":
            raise ValueError("scheduled execution origin requires an authority execution plan")
        return
    if execution_mode is None:
        raise ValueError("authority execution plan requires an execution mode")

    mode_plan = execution_plan.mode(execution_mode)
    actual_job_keys = tuple(job.key for job in jobs)
    expected_job_keys = mode_plan.job_keys
    job_set_matches = (
        actual_job_keys == expected_job_keys
        if require_complete_mode_plan
        else len(actual_job_keys) == 1 and actual_job_keys[0] in expected_job_keys
    )
    if not job_set_matches:
        raise ValueError(
            f"{execution_mode} execution origin requires the plan's exact ordered job set; "
            f"expected {expected_job_keys!r}, found {actual_job_keys!r}"
        )
    if execution_origin != mode_plan.execution_origin:
        raise ValueError(
            f"{execution_mode} execution origin mismatch; "
            f"expected {mode_plan.execution_origin!r}, found {execution_origin!r}"
        )
    if dry_run or force:
        raise ValueError("planned execution does not allow dry-run or forced execution")


def _validate_planned_cli_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    raw_argv: list[str],
) -> None:
    plan_requested = args.authority_plan_json is not None or args.execution_mode is not None
    if not plan_requested and args.execution_origin != "scheduled":
        return

    option_names = Counter(token.split("=", 1)[0] for token in raw_argv if token.startswith("--"))
    if (
        option_names != _PLANNED_EXECUTION_OPTION_NAMES
        or args.authority_plan_json is None
        or args.execution_mode is None
    ):
        parser.error("planned execution requires only --authority-plan-json, --execution-mode, and --execution-origin")


def _require_canary_result(jobs: list[RefreshJob], results: list[RefreshRunResult]) -> None:
    if (
        len(jobs) != 1
        or len(results) != 1
        or results[0].key != jobs[0].key
        or results[0].status != "success"
        or results[0].metadata_updates != len(jobs[0].data_source_names)
    ):
        raise ValueError("authority canary requires one fresh successful exact-source ledger result")


def main(argv: list[str] | None = None) -> int:
    from core.refresh.job_builders import build_refresh_plan

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_argument_parser()
    args = parser.parse_args(raw_argv)
    historical_recovery = _historical_recovery_identity_from_cli(parser, args, raw_argv)
    if historical_recovery is not None:
        identity, postcondition_path = historical_recovery
        return _run_historical_recovery_cli(identity, postcondition_path)
    _validate_planned_cli_args(parser, args, raw_argv)

    execution_plan: AuthorityExecutionPlan | None = None
    if args.authority_plan_json is not None:
        try:
            execution_plan = load_authority_execution_plan(args.authority_plan_json)
        except (ValueError, OSError) as error:
            parser.error(str(error))

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
    if execution_plan is not None:
        try:
            jobs = list(
                select_execution_plan_jobs(
                    jobs,
                    execution_plan,
                    mode=args.execution_mode,
                )
            )
            _validate_execution_origin_for_jobs(
                args.execution_origin,
                jobs,
                execution_plan=execution_plan,
                execution_mode=args.execution_mode,
                require_complete_mode_plan=True,
            )
        except ValueError as error:
            parser.error(str(error))

    lock_fds: list[int] = []
    try:
        if jobs and not args.dry_run and not args.no_lock:
            if execution_plan is None:
                acquired_fds = _acquire_runner_locks_for_jobs(
                    jobs,
                    wait_seconds=args.lock_wait_seconds,
                )
            else:
                acquired_fds = _acquire_runner_locks_for_jobs(
                    jobs,
                    wait_seconds=args.lock_wait_seconds,
                    authority_ownership_lock_key=execution_plan.ownership_lock_key,
                )
            if acquired_fds is None:
                return 2
            lock_fds = acquired_fds

        def _stream_result(result: RefreshRunResult) -> None:
            _emit_stdout_line(_format_result_line(result))

        if args.dry_run:
            results = run_all_jobs(
                None,
                jobs,
                dry_run=True,
                force=args.force,
                execution_origin=args.execution_origin,
                on_result=_stream_result,
            )
        else:
            connection: psycopg.Connection | None = None
            try:
                connection = get_connection(application_name=f"{_CONNECTION_IDENTITY_PREFIX}runner")
                if jobs and not args.no_lock:
                    if execution_plan is None:
                        database_locks_acquired = _try_acquire_database_runner_locks(connection, jobs)
                    else:
                        database_locks_acquired = _try_acquire_database_runner_locks(
                            connection,
                            jobs,
                            authority_ownership_lock_key=execution_plan.ownership_lock_key,
                        )
                    if not database_locks_acquired:
                        return 2
                planned_kwargs = (
                    {"execution_plan": execution_plan, "execution_mode": args.execution_mode}
                    if execution_plan is not None
                    else {}
                )
                results = run_all_jobs(
                    connection,
                    jobs,
                    dry_run=False,
                    force=args.force,
                    execution_origin=args.execution_origin,
                    on_result=_stream_result,
                    stop_on_failure=(
                        execution_plan.mode(args.execution_mode).stop_on_failure
                        if execution_plan is not None
                        else args.scope == "federal"
                    ),
                    on_heartbeat=_emit_stdout_line,
                    **planned_kwargs,
                )
            except Exception as error:  # noqa: BLE001
                print(f"Refresh runner failed: {error}", file=sys.stderr)
                return 1
            finally:
                if connection is not None:
                    connection.close()

        if execution_plan is not None and args.execution_mode == "canary":
            try:
                _require_canary_result(jobs, results)
            except ValueError as error:
                print(f"Refresh runner failed: {error}", file=sys.stderr)
                return 1
        return int(any(result.status in _FAILING_STATUSES for result in results))
    finally:
        _release_runner_locks(lock_fds)


if __name__ == "__main__":
    raise SystemExit(main())
