from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

from domains.campaign_finance.ingest import cli


def _build_connection() -> MagicMock:
    connection = MagicMock()
    connection.transaction.side_effect = lambda: nullcontext()
    return connection


class _TrackingTransactionConnection:
    def __init__(self, *, initial_transaction_depth: int = 0) -> None:
        self.transaction_depth = initial_transaction_depth
        self.commit = MagicMock(side_effect=self._commit)
        self.close = MagicMock()

    def _commit(self) -> None:
        self.transaction_depth = 0

    def transaction(self):
        connection = self

        class _TransactionContext:
            def __enter__(self) -> None:
                connection.transaction_depth += 1

            def __exit__(self, exc_type, exc, tb) -> None:
                connection.transaction_depth -= 1

        return _TransactionContext()


def test_main_reports_loaded_and_skipped_counts(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    connection = _build_connection()
    contribution_records = [{"sub_id": "one"}, {"sub_id": "two"}]
    fetch_client = MagicMock()
    fetch_client.fetch_contributions.return_value = contribution_records

    monkeypatch.setattr(cli, "FecClient", MagicMock(return_value=fetch_client))
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_fec_data_source", MagicMock(return_value=uuid4()))
    load_contribution = MagicMock(side_effect=[True, False])
    monkeypatch.setattr(cli, "load_contribution", load_contribution)

    exit_code = cli.main(["--state", "NC", "--cycle", "2024", "--limit", "2"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "loaded=1 skipped=1 errors=0 fetched=2" in captured.out
    assert captured.err == ""
    assert load_contribution.call_count == 2
    assert connection.transaction.call_count == 3
    connection.close.assert_called_once()


def test_main_isolates_record_failures_with_savepoints(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = _build_connection()
    contribution_records = [{"sub_id": "one"}, {"sub_id": "two"}, {"sub_id": "three"}]
    fetch_client = MagicMock()
    fetch_client.fetch_contributions.return_value = contribution_records

    monkeypatch.setattr(cli, "FecClient", MagicMock(return_value=fetch_client))
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_fec_data_source", MagicMock(return_value=uuid4()))
    load_contribution = MagicMock(side_effect=[True, psycopg.Error("boom"), False])
    monkeypatch.setattr(cli, "load_contribution", load_contribution)

    exit_code = cli.main(["--state", "NC", "--cycle", "2024", "--limit", "3"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "loaded=1 skipped=1 errors=1 fetched=3" in captured.out
    assert "sub_id=two" in captured.err
    assert load_contribution.call_count == 3
    assert connection.transaction.call_count == 4
    connection.close.assert_called_once()


def test_main_initializes_graph_inside_outer_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _TrackingTransactionConnection(initial_transaction_depth=1)
    fetch_client = MagicMock()
    fetch_client.fetch_contributions.return_value = [{"sub_id": "one"}]
    ensure_graph_depths: list[int] = []

    def _capture_ensure_graph(conn: object) -> None:
        assert isinstance(conn, _TrackingTransactionConnection)
        ensure_graph_depths.append(conn.transaction_depth)

    monkeypatch.setattr(cli, "FecClient", MagicMock(return_value=fetch_client))
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_graph", _capture_ensure_graph)
    monkeypatch.setattr(cli, "ensure_fec_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(cli, "load_contribution", MagicMock(return_value=True))

    exit_code = cli.main(["--state", "NC", "--cycle", "2024", "--limit", "1"])

    assert exit_code == 0
    assert ensure_graph_depths == [1]
    assert connection.commit.call_count == 2
    connection.close.assert_called_once()


def test_main_reports_connection_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    fetch_client = MagicMock()
    fetch_client.fetch_contributions.return_value = [{"sub_id": "one"}]

    monkeypatch.setattr(cli, "FecClient", MagicMock(return_value=fetch_client))
    monkeypatch.setattr(cli, "get_connection", MagicMock(side_effect=RuntimeError("database unavailable")))
    ensure_fec_data_source = MagicMock()
    monkeypatch.setattr(cli, "ensure_fec_data_source", ensure_fec_data_source)
    load_contribution = MagicMock()
    monkeypatch.setattr(cli, "load_contribution", load_contribution)

    exit_code = cli.main(["--state", "NC", "--cycle", "2024", "--limit", "1"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FEC ingest failed: database unavailable" in captured.err
    ensure_fec_data_source.assert_not_called()
    load_contribution.assert_not_called()


def test_run_fec_refresh_returns_typed_summary_without_argparse(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _build_connection()
    contribution_records = [{"sub_id": "one"}, {"sub_id": "two"}]
    fetch_client = MagicMock()
    fetch_client.fetch_contributions.return_value = contribution_records

    monkeypatch.setattr(cli, "FecClient", MagicMock(return_value=fetch_client))
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_fec_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(cli, "load_contribution", MagicMock(side_effect=[True, False]))

    summary = cli.run_fec_refresh(state="NC", cycle=2024, limit=2)

    fetch_client.fetch_contributions.assert_called_once_with(state="NC", cycle=2024, limit=2)
    assert summary.loaded_count == 1
    assert summary.skipped_count == 1
    assert summary.error_count == 0
    assert summary.fetched_count == 2
    connection.close.assert_called_once_with()
