"""Shared fixtures for integration tests that commit real ``core.refresh_run`` rows.

Tests that prove the committed-start attempt lifecycle write real rows and commit them,
so they escape the ``db_conn`` fixture rollback. This module is the single owner of the
shapes those tests share: the campaign-finance ``RefreshJob`` under test, the terminal-row
seed, the in-flight-row vacuity guard, and the scoped cleanups every such test must run in
a ``finally``.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock

import psycopg

from core.refresh import gate_l5, runner

SYNTHETIC_DATA_SOURCE_NAME = "Synthetic refresh-run fixture source"

# Every fixture in this module dates its rows far past any real refresh history, so a
# window-scoped clear can never reach production or dev data. ``delete_refresh_runs_completed_on``
# enforces the floor because it is the one helper that deletes by date instead of by job key.
SENTINEL_DATE_FLOOR = date(2099, 1, 1)

_DEFAULT_TERMINAL_COUNTS = {"inserted": 1, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0}


def refresh_job_for_tests(
    key: str,
    *,
    jurisdiction: str = "state/CO",
    data_source_names: tuple[str, ...] = (SYNTHETIC_DATA_SOURCE_NAME,),
    run_callable: MagicMock | None = None,
    refresh_history_key: str | None = None,
    activity_denominator_result_field: str | None = None,
) -> runner.RefreshJob:
    """Build the daily campaign-finance ``RefreshJob`` shape the refresh suites share.

    The default source name is synthetic because lifecycle tests may commit metadata
    updates. Tests that exercise a production source identity must pass it explicitly.
    """
    return runner.RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        cadence="daily",
        data_source_names=data_source_names,
        run_callable=run_callable or MagicMock(),
        refresh_history_key=refresh_history_key,
        activity_denominator_result_field=activity_denominator_result_field,
    )


def record_terminal_refresh_run(
    connection: psycopg.Connection,
    job: runner.RefreshJob,
    *,
    pull_status: str,
    completed_at: datetime,
    counts: dict[str, int] | None = None,
    error: str | None = None,
) -> None:
    """Seed one terminal attempt row whose ``started_at`` equals its ``completed_at``."""
    runner._record_refresh_run(
        connection,
        job,
        pull_status=pull_status,
        counts=dict(counts if counts is not None else _DEFAULT_TERMINAL_COUNTS),
        started_at=completed_at,
        completed_at=completed_at,
        metadata_updates=0,
        message=f"{pull_status} run",
        error=error,
    )


def delete_refresh_runs_for_job(connection: psycopg.Connection, job_key: str) -> None:
    """Drop the committed attempt rows a lifecycle test left outside the fixture transaction.

    Call this before seeding as well as in the ``finally``: a run killed mid-test leaks
    committed rows that would otherwise wedge the next run's vacuity and count assertions.
    """
    connection.rollback()
    connection.execute("DELETE FROM core.refresh_run WHERE job_key = %s", (job_key,))
    connection.commit()


def assert_single_in_flight_row(connection: psycopg.Connection, job_key: str) -> None:
    """Assert exactly one committed in-flight attempt exists under ``job_key``.

    Every before/after equality in the in-flight exclusion suites is vacuous unless the
    running row it is supposed to exclude was really committed. This is that guard: one
    row, ``pull_status`` ``running``, ``completed_at`` NULL — asserted under the same key
    the reader under test reads, which is what catches a job-key mismatch.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pull_status, completed_at FROM core.refresh_run WHERE job_key = %s AND completed_at IS NULL",
            (job_key,),
        )
        assert cursor.fetchall() == [("running", None)]


def delete_refresh_runs_completed_on(connection: psycopg.Connection, evidence_date: date) -> None:
    """Clear every attempt row completed inside one L5 evidence window.

    ``gate_l5.summarize_refresh_runs`` aggregates the whole window with no ``job_key``
    filter, so a test asserting exact window counts must own the window outright — a
    job-key-scoped pre-clear cannot reach a row another test leaked under a different key.
    The window bound comes from the reader itself so the two can never drift.

    Owning a whole UTC day is only safe on a sentinel date no real refresh run can occupy,
    so dates below :data:`SENTINEL_DATE_FLOOR` are refused rather than committed away —
    the caller has no restore path once the delete lands.
    """
    if evidence_date < SENTINEL_DATE_FLOOR:
        raise ValueError(
            f"delete_refresh_runs_completed_on owns a whole UTC day of core.refresh_run and is "
            f"restricted to sentinel dates on or after {SENTINEL_DATE_FLOOR.isoformat()}; "
            f"refusing {evidence_date.isoformat()}"
        )

    window_start, window_end = gate_l5._utc_window(evidence_date)
    connection.rollback()
    connection.execute(
        "DELETE FROM core.refresh_run WHERE completed_at >= %s AND completed_at < %s",
        (window_start, window_end),
    )
    connection.commit()
