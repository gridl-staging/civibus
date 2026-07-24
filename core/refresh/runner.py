
from __future__ import annotations

import argparse
from collections.abc import Mapping
import errno
import fcntl
import os
import statistics
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID

import psycopg

from core.db import get_connection, insert_refresh_run
from core.types.python.models import RefreshRun
from domains.campaign_finance.ingest.bulk_loader import sync_data_source_metadata

_RUNNER_LOCK_PATH = Path("/var/lock/civibus-refresh-runner.lock")
_REPO_ROOT = Path(__file__).resolve().parents[2]
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
_FAILING_STATUSES = frozenset({"crashed", "degraded", "empty", "failed"})


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
    if job.refresh_history_key is not None:
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
        return {field_name: int(getattr(execution_result, field_name)) for field_name in _LOADER_COUNT_FIELDS}

    if hasattr(execution_result, "result_row_count"):
        return {
            "inserted": int(getattr(execution_result, "result_row_count")),
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
        "Refresh job succeeded: "
        + " ".join(
            f"{field_name}={counts[field_name]}"
            for field_name in ("inserted", "skipped", "quarantined", "superseded", "errors")
        ),
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
    insert_refresh_run(
        connection,
        RefreshRun(
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
        ),
    )


def _format_result_line(result: RefreshRunResult) -> str:
    line = f"{result.key}: status={result.status} metadata_updates={result.metadata_updates} message={result.message}"
    if result.error:
        return f"{line} error={result.error}"
    return line


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
    force: bool,
    now: datetime,
) -> RefreshRunResult:
    if not force:
        latest_pull_at = _select_latest_pull_at(connection, job)
        if not should_run_job(job, last_pull_at=latest_pull_at, now=now):
            return _build_result(key=job.key, status="skipped", message="Skipped by cadence gate")

    return run_job(connection, job, dry_run=False)


def run_job(
    connection: psycopg.Connection,
    job: RefreshJob,
    *,
    dry_run: bool = False,
) -> RefreshRunResult:
    if dry_run:
        return _dry_run_result(job.key)

    metadata_updates = 0
    execution_error: Exception | None = None
    execution_result: object | None = None
    started_at = _utc_now()

    try:
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

    if pull_status == "success":
        try:
            metadata_updates = _sync_job_metadata(
                connection,
                job,
                pull_status=_legacy_data_source_pull_status(pull_status),
            )
        except Exception as metadata_error:  # noqa: BLE001
            return _build_result(
                key=job.key,
                status="failed",
                message="Metadata sync failed",
                metadata_updates=metadata_updates,
                error=str(metadata_error),
            )

    try:
        _record_refresh_run(
            connection,
            job,
            pull_status=pull_status,
            counts=counts,
            started_at=started_at,
            completed_at=completed_at,
            metadata_updates=metadata_updates,
            message=message,
            error=str(execution_error) if execution_error is not None else None,
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
        status=pull_status,
        metadata_updates=metadata_updates,
        message=message,
        error=str(execution_error) if execution_error is not None else None,
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
) -> list[RefreshRunResult]:
    if not dry_run and connection is None:
        raise ValueError("run_all_jobs requires a database connection when dry_run=False")

    results: list[RefreshRunResult] = []
    resolved_now = _resolve_now(now)
    for job in jobs:
        if dry_run:
            _record_result(results, _dry_run_result(job.key), on_result=on_result)
            continue

        assert connection is not None  # guarded above
        try:
            result = _run_gated_job(connection, job, force=force, now=resolved_now)
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

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_argument_parser() -> argparse.ArgumentParser:
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
    return parser


def _acquire_runner_lock(lock_path: Path) -> int | None:
    """Try to acquire a global flock. Returns the fd on success, None on contention."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError as error:
        os.close(fd)
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            return None
        raise


def _fallback_runner_lock_path() -> Path:
    """Return a same-host lock path for environments where /var/lock is unavailable."""
    return Path(tempfile.gettempdir()) / f"civibus-refresh-runner-{os.getuid()}.lock"


def main(argv: list[str] | None = None) -> int:
    from core.refresh.job_builders import build_refresh_plan

    args = build_argument_parser().parse_args(argv)

    lock_fd: int | None = None
    if not args.dry_run and not args.no_lock:
        try:
            lock_fd = _acquire_runner_lock(_RUNNER_LOCK_PATH)
        except OSError as primary_lock_error:
            fallback_lock_path = _fallback_runner_lock_path()
            try:
                lock_fd = _acquire_runner_lock(fallback_lock_path)
            except OSError as fallback_lock_error:
                print(
                    "Refresh runner lock setup failed "
                    f"(primary: {_RUNNER_LOCK_PATH}: {primary_lock_error}; "
                    f"fallback: {fallback_lock_path}: {fallback_lock_error}).",
                    file=sys.stderr,
                )
                return 2
            print(
                "Refresh runner using fallback lock "
                f"(primary: {_RUNNER_LOCK_PATH}: {primary_lock_error}; "
                f"fallback: {fallback_lock_path}).",
                file=sys.stderr,
            )
        if lock_fd is None:
            print(
                "Another refresh runner is already active "
                f"(lock: {_RUNNER_LOCK_PATH}). Exiting to avoid VM saturation.",
                file=sys.stderr,
            )
            return 2

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

    def _stream_result(result: RefreshRunResult) -> None:
        print(_format_result_line(result), flush=True)

    if args.dry_run:
        results = run_all_jobs(None, jobs, dry_run=True, force=args.force, on_result=_stream_result)
    else:
        connection: psycopg.Connection | None = None
        try:
            connection = get_connection()
            results = run_all_jobs(
                connection,
                jobs,
                dry_run=False,
                force=args.force,
                on_result=_stream_result,
                stop_on_failure=args.scope == "federal",
            )
        except Exception as error:  # noqa: BLE001
            print(f"Refresh runner failed: {error}", file=sys.stderr)
            return 1
        finally:
            if connection is not None:
                connection.close()

    return 1 if any(result.status in _FAILING_STATUSES for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
