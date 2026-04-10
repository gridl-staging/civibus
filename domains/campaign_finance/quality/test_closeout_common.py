"""Unit tests for shared closeout metadata helpers.

Tests DataSourceSnapshot, fetch_data_source_snapshot, and
derive_pull_status_from_counts without assuming FEC-specific
table structures or LoadStepSummary types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.reconciliation import (
    DataSourceSnapshot,
    derive_pull_status_from_counts,
    fetch_data_source_snapshot,
)


def _mock_conn(rows: list[tuple], *, fetchone: bool = False) -> MagicMock:
    """Build a mock psycopg connection returning the given rows."""
    mock_cursor = MagicMock()
    if fetchone:
        mock_cursor.fetchone.return_value = rows[0] if rows else None
    else:
        mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


class TestDataSourceSnapshot:
    def test_fields_are_accessible(self) -> None:
        ts = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        snap = DataSourceSnapshot(record_count=42, last_pull_status="success", last_pull_at=ts)
        assert snap.record_count == 42
        assert snap.last_pull_status == "success"
        assert snap.last_pull_at == ts

    def test_allows_all_none_fields(self) -> None:
        snap = DataSourceSnapshot(record_count=None, last_pull_status=None, last_pull_at=None)
        assert snap.record_count is None
        assert snap.last_pull_status is None
        assert snap.last_pull_at is None

    def test_is_frozen(self) -> None:
        snap = DataSourceSnapshot(record_count=10, last_pull_status="success", last_pull_at=None)
        with pytest.raises(AttributeError):
            snap.record_count = 99  # type: ignore[misc]


class TestFetchDataSourceSnapshot:
    def test_returns_snapshot_with_all_fields(self) -> None:
        ds_id = uuid4()
        ts = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        conn = _mock_conn([(100, "success", ts)], fetchone=True)
        snap = fetch_data_source_snapshot(conn, ds_id)
        assert snap.record_count == 100
        assert snap.last_pull_status == "success"
        assert snap.last_pull_at == ts

    def test_returns_all_none_when_data_source_missing(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        snap = fetch_data_source_snapshot(conn, ds_id)
        assert snap.record_count is None
        assert snap.last_pull_status is None
        assert snap.last_pull_at is None

    def test_queries_correct_columns(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(None, None, None)], fetchone=True)
        fetch_data_source_snapshot(conn, ds_id)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "record_count" in sql
        assert "last_pull_status" in sql
        assert "last_pull_at" in sql
        assert "core.data_source" in sql

    def test_passes_data_source_id_as_parameter(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(None, None, None)], fetchone=True)
        fetch_data_source_snapshot(conn, ds_id)
        params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
        assert params == (ds_id,)


class TestDerivePullStatusFromCounts:
    def test_success_when_no_errors(self) -> None:
        assert derive_pull_status_from_counts(100, 0, 0) == "success"

    def test_success_when_all_skipped_zero_errors(self) -> None:
        assert derive_pull_status_from_counts(0, 50, 0) == "success"

    def test_success_when_inserted_and_skipped_no_errors(self) -> None:
        assert derive_pull_status_from_counts(80, 20, 0) == "success"

    def test_partial_when_errors_and_successes(self) -> None:
        assert derive_pull_status_from_counts(90, 5, 5) == "partial"

    def test_partial_when_errors_and_skipped_only(self) -> None:
        assert derive_pull_status_from_counts(0, 10, 5) == "partial"

    def test_failed_when_only_errors(self) -> None:
        assert derive_pull_status_from_counts(0, 0, 10) == "failed"

    def test_success_when_all_zero(self) -> None:
        """Empty run with no rows at all is success (not an error)."""
        assert derive_pull_status_from_counts(0, 0, 0) == "success"
