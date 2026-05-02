"""NC orchestrator progress repository.

Single owner of per-committee, per-window download progress for statewide
NC committee orchestration. Backed by cf.nc_orchestrator_progress.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _registry_table_exists(conn: psycopg.Connection) -> bool:
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'cf' AND table_name = 'nc_committee_registry'
        )
        """
    ).fetchone()
    return row is not None and row[0] is True


def _build_allowlist_scope(
    allowlist_sboe_ids: list[str] | None,
) -> tuple[str, dict[str, Any]]:
    """Return reusable SQL predicate fragment and params for allowlist scoping."""
    if allowlist_sboe_ids is None:
        return "", {}
    return (
        " AND sboe_id = ANY(%(allowlist_sboe_ids)s::text[])",
        {"allowlist_sboe_ids": allowlist_sboe_ids},
    )


def seed_progress_from_registry(
    conn: psycopg.Connection,
    window_start: date,
    window_end: date,
    allowlist_sboe_ids: list[str] | None = None,
) -> int:
    """Seed pending progress rows from cf.nc_committee_registry for the given window.

    Returns the number of newly inserted rows. Idempotent per (sboe_id, window_start, window_end).
    Raises RuntimeError if cf.nc_committee_registry is absent.
    """
    if not _registry_table_exists(conn):
        raise RuntimeError(
            "cf.nc_committee_registry does not exist. "
            "Cannot seed orchestrator progress without upstream committee registry."
        )

    with conn.cursor() as cur:
        params: dict[str, Any] = {
            "window_start": window_start,
            "window_end": window_end,
        }
        where_allowlist, allowlist_params = _build_allowlist_scope(allowlist_sboe_ids)
        params.update(allowlist_params)

        # Filter out empty sboe_id values: 232+ active NC committees in production
        # have sboe_id='' (registered with NCSBE but never assigned an SBoE ID, or a
        # discovery data-quality issue). Without this filter the seed query violates
        # nc_orchestrator_progress_pkey on (sboe_id, window_start, window_end). The
        # downloader path (_download_committee_exports) cannot drive the portal
        # without a real sboe_id anyway, so dropping these rows costs no coverage.
        # SELECT DISTINCT defends against the same logical-duplicate path collapsing
        # to multiple rows in the registry, which would also break the PK.
        cur.execute(
            """
            INSERT INTO cf.nc_orchestrator_progress (sboe_id, window_start, window_end)
            SELECT DISTINCT sboe_id, %(window_start)s, %(window_end)s
            FROM cf.nc_committee_registry
            WHERE (is_active OR last_filing_date >= %(window_start)s)
                AND NULLIF(BTRIM(sboe_id), '') IS NOT NULL
                {where_allowlist}
                AND NOT EXISTS (
                SELECT 1 FROM cf.nc_orchestrator_progress p
                WHERE p.sboe_id = cf.nc_committee_registry.sboe_id
                    AND p.window_start = %(window_start)s
                    AND p.window_end = %(window_end)s
            )
            ORDER BY sboe_id ASC
            """.format(where_allowlist=where_allowlist),
            params,
        )
        return cur.rowcount


def mark_retryable_failure(
    conn: psycopg.Connection,
    sboe_id: str,
    window_start: date,
    window_end: date,
    *,
    error: str,
) -> None:
    """Return an in-progress row back to pending for retryable failures."""
    conn.execute(
        """
        UPDATE cf.nc_orchestrator_progress
        SET status = 'pending',
            claimed_at = NULL,
            last_error = %(error)s,
            attempt_count = attempt_count + 1,
            updated_at = now()
        WHERE sboe_id = %(sboe_id)s
            AND window_start = %(window_start)s
            AND window_end = %(window_end)s
        """,
        {
            "sboe_id": sboe_id,
            "window_start": window_start,
            "window_end": window_end,
            "error": error,
        },
    )


def claim_next_committee(
    conn: psycopg.Connection,
    window_start: date,
    window_end: date,
    allowlist_sboe_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """Claim the next pending committee (deterministic sboe_id ASC order).

    Returns a dict with the claimed row's columns, or None if no pending work remains.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        params: dict[str, Any] = {
            "window_start": window_start,
            "window_end": window_end,
        }
        where_allowlist, allowlist_params = _build_allowlist_scope(allowlist_sboe_ids)
        params.update(allowlist_params)
        cur.execute(
            """
            UPDATE cf.nc_orchestrator_progress
            SET status = 'in_progress',
                claimed_at = now(),
                updated_at = now()
            WHERE (sboe_id, window_start, window_end) = (
                SELECT sboe_id, window_start, window_end
                FROM cf.nc_orchestrator_progress
                WHERE window_start = %(window_start)s
                    AND window_end = %(window_end)s
                    AND status = 'pending'
                    {where_allowlist}
                ORDER BY sboe_id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """.format(where_allowlist=where_allowlist),
            params,
        )
        return cur.fetchone()


def mark_completed(
    conn: psycopg.Connection,
    sboe_id: str,
    window_start: date,
    window_end: date,
) -> None:
    """Transition a committee's progress to completed."""
    conn.execute(
        """
        UPDATE cf.nc_orchestrator_progress
        SET status = 'completed',
            updated_at = now()
        WHERE sboe_id = %(sboe_id)s
            AND window_start = %(window_start)s
            AND window_end = %(window_end)s
        """,
        {"sboe_id": sboe_id, "window_start": window_start, "window_end": window_end},
    )


def mark_failed(
    conn: psycopg.Connection,
    sboe_id: str,
    window_start: date,
    window_end: date,
    *,
    error: str,
) -> None:
    """Transition a committee's progress to failed, recording the error text."""
    conn.execute(
        """
        UPDATE cf.nc_orchestrator_progress
        SET status = 'failed',
            last_error = %(error)s,
            attempt_count = attempt_count + 1,
            updated_at = now()
        WHERE sboe_id = %(sboe_id)s
            AND window_start = %(window_start)s
            AND window_end = %(window_end)s
        """,
        {
            "sboe_id": sboe_id,
            "window_start": window_start,
            "window_end": window_end,
            "error": error,
        },
    )


def reclaim_stale_in_progress(
    conn: psycopg.Connection,
    window_start: date,
    window_end: date,
    *,
    stale_after_minutes: int,
    allowlist_sboe_ids: list[str] | None = None,
) -> int:
    """Reset stale in_progress rows back to pending for re-claiming.

    Returns the number of rows reclaimed.
    """
    with conn.cursor() as cur:
        params: dict[str, Any] = {
            "window_start": window_start,
            "window_end": window_end,
            "stale_after_minutes": stale_after_minutes,
        }
        where_allowlist, allowlist_params = _build_allowlist_scope(allowlist_sboe_ids)
        params.update(allowlist_params)
        cur.execute(
            """
            UPDATE cf.nc_orchestrator_progress
            SET status = 'pending',
                claimed_at = NULL,
                updated_at = now()
            WHERE window_start = %(window_start)s
                AND window_end = %(window_end)s
                AND status = 'in_progress'
                AND claimed_at < now() - make_interval(mins => %(stale_after_minutes)s)
                {where_allowlist}
            """.format(where_allowlist=where_allowlist),
            params,
        )
        return cur.rowcount
