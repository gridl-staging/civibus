"""Unit contract for the shared ``core.refresh_run`` integration-test fixtures.

These helpers commit real rows and delete real rows outside any fixture transaction, so
their guards are the only thing standing between a mistyped date and a wiped day of dev
refresh history. Cover them here rather than only through their DB-backed call sites.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from core.refresh import gate_l5
from test_support.refresh_run_fixtures import (
    SENTINEL_DATE_FLOOR,
    assert_single_in_flight_row,
    delete_refresh_runs_completed_on,
    refresh_job_for_tests,
)


def test_refresh_job_for_tests_defaults_to_a_synthetic_data_source_name() -> None:
    job = refresh_job_for_tests("fixture-job")

    assert job.data_source_names == ("Synthetic refresh-run fixture source",)


def test_delete_refresh_runs_completed_on_refuses_a_real_evidence_date() -> None:
    connection = MagicMock()

    with pytest.raises(ValueError, match="sentinel"):
        delete_refresh_runs_completed_on(connection, date(2026, 8, 23))

    # The refusal must precede every mutation: no rollback, no DELETE, no commit.
    connection.rollback.assert_not_called()
    connection.execute.assert_not_called()
    connection.commit.assert_not_called()


def test_delete_refresh_runs_completed_on_refuses_the_day_below_the_floor() -> None:
    connection = MagicMock()
    day_below_floor = date.fromordinal(SENTINEL_DATE_FLOOR.toordinal() - 1)

    with pytest.raises(ValueError, match="sentinel"):
        delete_refresh_runs_completed_on(connection, day_below_floor)

    connection.execute.assert_not_called()


def test_delete_refresh_runs_completed_on_clears_the_sentinel_window() -> None:
    connection = MagicMock()

    delete_refresh_runs_completed_on(connection, SENTINEL_DATE_FLOOR)

    connection.rollback.assert_called_once_with()
    sql, parameters = connection.execute.call_args.args
    assert "DELETE FROM core.refresh_run" in sql
    # Bounds come from the reader itself, so the clear and the aggregate cannot drift.
    assert parameters == gate_l5._utc_window(SENTINEL_DATE_FLOOR)
    connection.commit.assert_called_once_with()


def test_assert_single_in_flight_row_passes_for_one_committed_running_row() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("running", None)]

    assert_single_in_flight_row(connection, "some-job-key")

    sql, parameters = cursor.execute.call_args.args
    assert "completed_at IS NULL" in sql
    assert parameters == ("some-job-key",)


def test_assert_single_in_flight_row_fails_when_no_running_row_was_committed() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []

    with pytest.raises(AssertionError):
        assert_single_in_flight_row(connection, "some-job-key")


def test_assert_single_in_flight_row_fails_on_a_terminal_row_under_the_same_key() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("success", datetime(2099, 1, 1, tzinfo=timezone.utc))]

    with pytest.raises(AssertionError):
        assert_single_in_flight_row(connection, "some-job-key")
