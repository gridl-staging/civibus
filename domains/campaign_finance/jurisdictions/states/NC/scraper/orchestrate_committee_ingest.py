
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Iterator

import psycopg

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    NCNoTransactionsForCriteriaError,
    TransactionSearchCriteria,
    download_committee_document_export,
    download_transaction_export_playwright,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    load_nc_transactions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrator_progress import (
    claim_next_committee,
    mark_completed,
    mark_failed,
    mark_retryable_failure,
    reclaim_stale_in_progress,
    seed_progress_from_registry,
)


def _log_outcome(sboe_id: str, outcome: str, **details: object) -> None:
    """Emit a per-committee terminal-outcome log line to stdout.

    Operators tail the orchestrator's log file to know forward progress.
    Without per-committee lines, a long-running stuck orchestrator looks
    identical to a healthy one (live incident 2026-04-26: 1h45m run
    stuck at 198/3,668 committees produced a 0-byte log file).

    Format: ISO-8601 timestamp + sboe_id + outcome + key=value details.
    Flushes immediately so the line is visible in tailed log files
    without waiting for buffer flush.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    detail_str = " ".join(f"{k}={v}" for k, v in details.items()) if details else ""
    print(f"{ts} sboe_id={sboe_id} outcome={outcome} {detail_str}".rstrip(), flush=True)


@dataclass(slots=True)
class CommitteeIngestRunResult:
    seeded: int = 0
    reclaimed: int = 0
    claimed: int = 0
    completed: int = 0
    year_filtered: int = 0
    retryable_failures: int = 0
    permanent_failures: int = 0


def _format_portal_date(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def _normalize_non_negative_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    if limit < 0:
        raise ValueError("limit must be greater than or equal to 0")
    return limit


def _validate_orchestrator_window(window_start: date, window_end: date) -> None:
    if window_end < window_start:
        raise ValueError("window_end must be greater than or equal to window_start")


def _validate_orchestrator_controls(stale_after_minutes: int, politeness_delay_seconds: float) -> None:
    if stale_after_minutes < 0:
        raise ValueError("stale_after_minutes must be greater than or equal to 0")
    if politeness_delay_seconds < 0:
        raise ValueError("politeness_delay_seconds must be greater than or equal to 0")


@contextmanager
def _resolve_work_dir(work_dir: Path | None) -> Iterator[Path]:
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        yield work_dir
        return

    with TemporaryDirectory(prefix="nc-committee-orchestrator-") as temp_dir:
        resolved = Path(temp_dir)
        resolved.mkdir(parents=True, exist_ok=True)
        yield resolved


def _registry_committee_name(conn: psycopg.Connection, sboe_id: str) -> str:
    row = conn.execute(
        """
        SELECT committee_name
        FROM cf.nc_committee_registry
        WHERE sboe_id = %s
        LIMIT 1
        """,
        (sboe_id,),
    ).fetchone()
    if row is None or row[0] is None or not str(row[0]).strip():
        raise ValueError(f"Committee registry row missing committee_name for sboe_id={sboe_id!r}")
    return str(row[0]).strip()


def _registry_org_group_id(conn: psycopg.Connection, sboe_id: str) -> str:
    """Return the CFOrgLkup OGID (org_group_id) for the given sboe_id.

    Why: download_committee_document_export needs OGID, not sboe_id, in the
    CFOrgLkup/ExportSearchResults URL. Passing sboe_id where OGID is expected
    returns an HTML 404 page (the portal cannot resolve sboe_id as OGID), which
    surfaces downstream as `Committee export returned HTML instead of CSV`.
    Live evidence: 2026-04-25 production prod-proof attempt for sboe_id
    `001-085N21-C-001` failed with that exact symptom.

    Production live data has sboe_id duplicates (verified 2026-04-25:
    FED-C4753N-C-001 and STA-C1873N-C-002 each appear on two distinct
    org_group_id rows — both currently CLOSED so neither hits the active
    filter, but the duplication pattern is real). The unique key is
    org_group_id (uq_nc_committee_registry_org_group_id), not sboe_id.
    Pick the largest org_group_id deterministically — the registry's
    upsert path uses higher org_group_ids for newer NC SBoE assignments,
    so MAX prefers the most recent committee registration when sboe_id
    collides. Both rows in the known live duplicates have the same
    committee_name (or near-identical), so committee identity is
    preserved either way; the ordering just makes the choice stable
    across runs.
    """
    row = conn.execute(
        """
        SELECT MAX(org_group_id)
        FROM cf.nc_committee_registry
        WHERE sboe_id = %s
        """,
        (sboe_id,),
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"Committee registry row missing org_group_id for sboe_id={sboe_id!r}")
    return str(row[0])


def _sleep_for_politeness(politeness_delay_seconds: float) -> None:
    if politeness_delay_seconds <= 0:
        return
    time.sleep(politeness_delay_seconds)


def _download_committee_exports(
    *,
    org_group_id: str,
    committee_name: str,
    window_start: date,
    window_end: date,
    committee_docs_path: Path,
    transaction_path: Path,
    politeness_delay_seconds: float,
) -> None:
    _sleep_for_politeness(politeness_delay_seconds)
    download_committee_document_export(org_group_id, committee_name, committee_docs_path)

    _sleep_for_politeness(politeness_delay_seconds)
    download_transaction_export_playwright(
        TransactionSearchCriteria(
            committee_name=committee_name,
            date_from=_format_portal_date(window_start),
            date_to=_format_portal_date(window_end),
        ),
        transaction_path,
    )


def _retryable_failure_message(error: Exception) -> str:
    message = str(error).strip()
    if message:
        return message
    return error.__class__.__name__


def _permanent_failure_message(error: Exception) -> str:
    message = str(error).strip()
    if message:
        return message
    return error.__class__.__name__


# Consecutive retryable failures usually mean the portal is down or the
# politeness threshold is too tight for this Hetzner-side rate. Break the
# run on a small streak so the unbounded crawl doesn't hammer a wedged
# portal forever, but tolerate isolated per-committee transient failures
# (e.g. one Playwright timeout) without aborting the whole run.
_CONSECUTIVE_RETRYABLE_FAILURE_BUDGET = 3

# Per-committee retry budget: after this many failed attempts, demote the
# row from retryable -> permanent so the orchestrator stops re-claiming
# the same persistent-failure committee. Without this cap, the claim
# loop keeps picking the same sboe_id (sboe_id ASC ordering) and a single
# bad committee can starve the entire crawl. Live evidence 2026-04-26:
# committee 079-7SE7OZ-C-001 was retried 4 times (Committee export
# returned empty CSV) and consumed the consecutive-retry budget on every
# fresh dispatch. Demoting after N attempts unblocks the rest of the queue.
_PER_COMMITTEE_MAX_ATTEMPTS = 3


def orchestrate_committee_ingest(
    conn: psycopg.Connection,
    *,
    window_start: date,
    window_end: date,
    stale_after_minutes: int,
    politeness_delay_seconds: float,
    limit: int | None = None,
    allowlist_sboe_ids: list[str] | None = None,
    year_from: int | None = None,
    work_dir: Path | None = None,
    consecutive_retryable_budget: int = _CONSECUTIVE_RETRYABLE_FAILURE_BUDGET,
    per_committee_max_attempts: int = _PER_COMMITTEE_MAX_ATTEMPTS,
    commit_per_committee: bool = False,
) -> CommitteeIngestRunResult:
    """Run sequential statewide NC committee ingest for one date window.

    ``commit_per_committee=True`` makes each terminal per-committee outcome
    (completed, retryable failure, permanent failure, no-results, demoted)
    commit immediately so progress is visible to other DB sessions and
    crash-resilient mid-crawl. Production callers (``run_nc_committee_orchestrator``)
    pass True; unit tests using BEGIN/ROLLBACK isolation default to False so
    fixture-scoped data does not leak across tests.
    """
    _validate_orchestrator_window(window_start, window_end)
    _validate_orchestrator_controls(stale_after_minutes, politeness_delay_seconds)
    committee_limit = _normalize_non_negative_limit(limit)
    result = CommitteeIngestRunResult()

    result.reclaimed = reclaim_stale_in_progress(
        conn,
        window_start,
        window_end,
        stale_after_minutes=stale_after_minutes,
        allowlist_sboe_ids=allowlist_sboe_ids,
    )
    result.seeded = seed_progress_from_registry(
        conn,
        window_start,
        window_end,
        allowlist_sboe_ids=allowlist_sboe_ids,
    )
    consecutive_retryable_failures = 0

    with _resolve_work_dir(work_dir) as resolved_work_dir:
        while committee_limit is None or result.claimed < committee_limit:
            claimed_row = claim_next_committee(
                conn,
                window_start,
                window_end,
                allowlist_sboe_ids=allowlist_sboe_ids,
            )
            if claimed_row is None:
                break

            result.claimed += 1
            sboe_id = str(claimed_row["sboe_id"])
            log_sboe_id = "".join(
                character if character.isascii() and (character.isalnum() or character in {"-", "_"}) else "_"
                for character in sboe_id
            ).strip("_")
            try:
                safe_sboe_id = log_sboe_id
                if not safe_sboe_id:
                    raise ValueError(f"Cannot derive safe work filename from sboe_id={sboe_id!r}")
                committee_docs_path = (
                    resolved_work_dir
                    / f"{safe_sboe_id}_committee_docs_{window_start.isoformat()}_{window_end.isoformat()}.csv"
                )
                transaction_path = (
                    resolved_work_dir
                    / f"{safe_sboe_id}_transactions_{window_start.isoformat()}_{window_end.isoformat()}.csv"
                )
                resolved_work_dir_real = resolved_work_dir.resolve()
                if (
                    resolved_work_dir_real not in committee_docs_path.resolve().parents
                    or resolved_work_dir_real not in transaction_path.resolve().parents
                ):
                    raise ValueError(f"Refusing to write outside orchestrator work_dir for sboe_id={sboe_id!r}")
                committee_name = _registry_committee_name(conn, sboe_id)
                org_group_id = _registry_org_group_id(conn, sboe_id)
            except Exception as error:  # noqa: BLE001
                mark_failed(
                    conn,
                    sboe_id,
                    window_start,
                    window_end,
                    error=_permanent_failure_message(error),
                )
                result.permanent_failures += 1
                if commit_per_committee:
                    conn.commit()
                _log_outcome(
                    log_sboe_id or "invalid_sboe_id",
                    "permanent_failure",
                    stage="registry_lookup",
                    error_class=type(error).__name__,
                )
                continue

            try:
                _download_committee_exports(
                    org_group_id=org_group_id,
                    committee_name=committee_name,
                    window_start=window_start,
                    window_end=window_end,
                    committee_docs_path=committee_docs_path,
                    transaction_path=transaction_path,
                    politeness_delay_seconds=politeness_delay_seconds,
                )
            except NCNoTransactionsForCriteriaError:
                # Legitimate empty result: the committee has no transactions in
                # the requested window. Mark the row completed with zero rows
                # and continue to the next committee instead of breaking the
                # loop on a "retryable failure" that would never actually
                # change on retry.
                mark_completed(conn, sboe_id, window_start, window_end)
                result.completed += 1
                consecutive_retryable_failures = 0
                if commit_per_committee:
                    conn.commit()
                _log_outcome(log_sboe_id or "invalid_sboe_id", "completed", reason="no_results")
                continue
            except Exception as error:  # noqa: BLE001
                # Stage 1 gate: browser/download/politeness failures are retryable.
                # Tolerate isolated per-committee failures so the unbounded
                # crawl doesn't abort on a single Playwright timeout, but
                # break the run if N consecutive retryable failures pile up
                # (signals systemic portal issue or politeness too tight).
                #
                # Per-committee retry cap: a row that has already failed
                # `per_committee_max_attempts` times gets demoted from
                # retryable -> permanent so the claim loop stops re-picking
                # the same persistent-failure committee. attempt_count from
                # the orchestrator_progress row reflects the count BEFORE
                # this attempt; +1 captures the just-failed attempt.
                prior_attempts = int(claimed_row.get("attempt_count") or 0)
                if prior_attempts + 1 >= per_committee_max_attempts:
                    # Permanent demotion is a SUCCESSFUL queue-state advance:
                    # the failing committee is taken out of contention so the
                    # crawl can move on. Demotions therefore reset the
                    # consecutive-retryable streak — they're not a portal-down
                    # signal, they're a backpressure signal we already handled.
                    mark_failed(
                        conn,
                        sboe_id,
                        window_start,
                        window_end,
                        error=(
                            f"Demoted to permanent after {prior_attempts + 1} retryable "
                            f"attempts; last error: {_retryable_failure_message(error)}"
                        ),
                    )
                    result.permanent_failures += 1
                    consecutive_retryable_failures = 0
                    if commit_per_committee:
                        conn.commit()
                    _log_outcome(
                        log_sboe_id or "invalid_sboe_id",
                        "permanent_failure",
                        stage="download_demoted",
                        attempts=prior_attempts + 1,
                        error_class=type(error).__name__,
                    )
                    continue
                # Genuine retryable failure: counts toward the streak.
                mark_retryable_failure(
                    conn,
                    sboe_id,
                    window_start,
                    window_end,
                    error=_retryable_failure_message(error),
                )
                result.retryable_failures += 1
                consecutive_retryable_failures += 1
                if commit_per_committee:
                    conn.commit()
                _log_outcome(
                    log_sboe_id or "invalid_sboe_id",
                    "retryable_failure",
                    stage="download",
                    streak=consecutive_retryable_failures,
                    error_class=type(error).__name__,
                )
                if consecutive_retryable_failures >= consecutive_retryable_budget:
                    break
                continue

            try:
                load_result = load_nc_transactions_with_filings(
                    conn,
                    transaction_path,
                    committee_docs_path,
                    year_from=year_from,
                )
                result.year_filtered += int(getattr(load_result, "year_filtered", 0))
            except Exception as error:  # noqa: BLE001
                # Stage 1 gate: deterministic stitched-load contract failures are permanent.
                mark_failed(
                    conn,
                    sboe_id,
                    window_start,
                    window_end,
                    error=_permanent_failure_message(error),
                )
                result.permanent_failures += 1
                if commit_per_committee:
                    conn.commit()
                _log_outcome(
                    log_sboe_id or "invalid_sboe_id",
                    "permanent_failure",
                    stage="load",
                    error_class=type(error).__name__,
                )
                continue

            mark_completed(conn, sboe_id, window_start, window_end)
            result.completed += 1
            consecutive_retryable_failures = 0
            if commit_per_committee:
                conn.commit()
            _log_outcome(log_sboe_id or "invalid_sboe_id", "completed")

    return result


def run_nc_committee_orchestrator(
    *,
    window_start: date,
    window_end: date,
    stale_after_minutes: int,
    politeness_delay_seconds: float,
    limit: int | None = None,
    allowlist_sboe_ids: list[str] | None = None,
    year_from: int | None = None,
) -> CommitteeIngestRunResult:
    """CLI-friendly wrapper that owns DB connection lifecycle."""
    conn: psycopg.Connection | None = None
    try:
        conn = get_connection()
        result = orchestrate_committee_ingest(
            conn,
            window_start=window_start,
            window_end=window_end,
            stale_after_minutes=stale_after_minutes,
            politeness_delay_seconds=politeness_delay_seconds,
            limit=limit,
            allowlist_sboe_ids=allowlist_sboe_ids,
            year_from=year_from,
            # Production crawls take many hours; per-committee commits make
            # progress visible to monitoring SQL sessions and survive crashes.
            commit_per_committee=True,
        )
        # Final commit covers anything outside terminal-per-committee paths
        # (e.g. reclaim_stale_in_progress / seed_progress_from_registry rows
        # written before the loop began under autocommit=False).
        conn.commit()
        return result
    finally:
        if conn is not None:
            conn.close()
