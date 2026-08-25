from __future__ import annotations

import ast
import inspect
import threading
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

from domains.campaign_finance.jurisdictions.states.PA.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.PA.scraper import load as pa_load_module
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    bulk_fixture_row_counts,
    cleanup_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper import pa_load_test_support as pa_support
from domains.campaign_finance.jurisdictions.states.PA.scraper import test_load as pa_load_tests
from domains.campaign_finance.jurisdictions.states.PA.scraper.load import LoadResult, _resolve_pa_filings_path


_TEST_FILE_LINE_HARD_LIMIT = 800
_TEST_FUNCTION_LINE_HARD_LIMIT = 100
_PA_TEST_MODULES = (Path(__file__).with_name("test_load.py"), Path(__file__))
_SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"


def test_load_pa_with_filings_commits_data_source_then_rolls_back_on_phase2_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()
    load_result = LoadResult(
        inserted=2,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )
    ensure_transaction_open = MagicMock()

    def _ensure_data_source(connection: object, **_kwargs: object) -> str:
        connection.execute("SELECT ensure data source")
        return "pa-source-id"

    monkeypatch.setattr(pa_load_module, "ensure_transaction_open", ensure_transaction_open)
    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", _ensure_data_source)
    monkeypatch.setattr(pa_load_module, "_load_pa_file", lambda *_args, **_kwargs: load_result)
    monkeypatch.setattr(pa_load_module, "parse_filings", lambda _path, _year: iter(()))
    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda _path, _year: iter(()))
    monkeypatch.setattr(
        pa_load_module,
        "_load_pa_relational_transactions",
        MagicMock(side_effect=RuntimeError("relational failed")),
    )

    with pytest.raises(RuntimeError, match="relational failed"):
        pa_load_module._load_pa_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025)

    ensure_transaction_open.assert_not_called()
    assert conn.calls.count("commit") == 1
    assert conn.calls.count("rollback") == 1
    assert conn.calls.index("commit") < conn.calls.index("rollback")


def test_load_pa_with_filings_reports_superseded_rows_from_filer_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    load_result = LoadResult(
        inserted=2,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )
    campaignfinance_id_column = _load_column_for_semantic_path("filings", "pa.campaignfinance_id")
    amend_column = _load_column_for_semantic_path("filings", "pa.amend_flag")
    terminate_column = _load_column_for_semantic_path("filings", "pa.terminate_flag")
    detail_campaign_id_column = _load_column_for_semantic_path("contributions", "pa.campaign_finance_id")

    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", lambda *_args, **_kwargs: "pa-source-id")
    monkeypatch.setattr(pa_load_module, "_load_pa_file", lambda *_args, **_kwargs: load_result)
    monkeypatch.setattr(
        pa_load_module,
        "parse_filings",
        lambda _path, _year: iter([{campaignfinance_id_column: "1001", amend_column: "N", terminate_column: "Y"}]),
    )
    monkeypatch.setitem(
        pa_load_module._PA_PARSER_FN,
        "contributions",
        lambda _path, _year: iter([{detail_campaign_id_column: "1001"}]),
    )
    monkeypatch.setattr(pa_load_module, "_load_pa_relational_transactions", MagicMock(return_value=1))

    result = pa_load_module._load_pa_with_filings(
        conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025
    )
    assert result.superseded == 1


def test_load_pa_with_filings_reports_complete_two_phase_elapsed_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()
    lifecycle_events: list[str] = []
    timing_samples = iter((("timer_start", 100.0), ("timer_end", 105.5)))

    def _record_perf_counter() -> float:
        event, timestamp = next(timing_samples)
        lifecycle_events.append(event)
        return timestamp

    load_result = LoadResult(
        inserted=2,
        skipped=1,
        quarantined=3,
        superseded=0,
        errors=1,
        elapsed_seconds=0.1,
    )
    monkeypatch.setattr(pa_load_module.time, "perf_counter", _record_perf_counter)
    monkeypatch.setattr(
        pa_load_module,
        "commit_managed_transaction",
        lambda *_args: lifecycle_events.append("commit"),
    )
    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", lambda *_args, **_kwargs: "pa-source-id")
    monkeypatch.setattr(pa_load_module, "_load_pa_file", lambda *_args, **_kwargs: load_result)
    monkeypatch.setattr(pa_load_module, "parse_filings", lambda *_args: iter(()))
    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda *_args: iter(()))
    monkeypatch.setattr(pa_load_module, "_load_pa_relational_transactions", MagicMock(return_value=4))

    result = pa_load_module._load_pa_with_filings(
        conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025
    )

    assert result.elapsed_seconds == pytest.approx(5.5)
    assert (result.inserted, result.skipped, result.quarantined, result.errors, result.superseded) == (2, 1, 3, 1, 4)
    assert lifecycle_events == ["timer_start", "commit", "commit", "timer_end"]

    def _fail_data_source_setup(connection: object, **_kwargs: object) -> str:
        connection.execute("SELECT ensure data source")
        raise RuntimeError("data-source setup failed")

    monkeypatch.undo()
    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", _fail_data_source_setup)

    with pytest.raises(RuntimeError, match="data-source setup failed"):
        pa_load_module._load_pa_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025)

    assert conn.calls == ["execute", "rollback"]
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_resolve_pa_filings_path_returns_zip_path_unchanged(tmp_path: Path) -> None:
    zip_path = tmp_path / "pa-2025.zip"
    zip_path.touch()
    assert _resolve_pa_filings_path(zip_path, data_type="contributions") == zip_path


def test_resolve_pa_filings_path_derives_sibling_filings_csv(tmp_path: Path) -> None:
    detail = tmp_path / "sample_contributions.csv"
    filings = tmp_path / "sample_filings.csv"
    detail.touch()
    filings.touch()
    assert _resolve_pa_filings_path(detail, data_type="contributions") == filings


def test_resolve_pa_filings_path_raises_when_no_sibling_found(tmp_path: Path) -> None:
    detail = tmp_path / "sample_contributions.csv"
    detail.touch()
    with pytest.raises(FileNotFoundError, match="Cannot locate PA filings CSV"):
        _resolve_pa_filings_path(detail, data_type="contributions")


def test_relational_loader_helpers_stay_within_parameter_hard_limit() -> None:
    helper_functions = (
        pa_load_module._upsert_pa_filing,
        pa_load_module._upsert_pa_transaction_with_filing,
        pa_load_module._load_pa_relational_transactions,
    )
    parameter_counts = {helper.__name__: len(inspect.signature(helper).parameters) for helper in helper_functions}
    violations = {name: count for name, count in parameter_counts.items() if count > 6}
    assert not violations, f"PA relational loader helpers must stay at or below six parameters: {violations}"


def test_load_pa_rows_errored_row_rolls_back_only_its_savepoint_and_batch_still_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()

    def _load_row(_conn: object, row: dict[str, str | None], *_args: object, **_kwargs: object) -> bool:
        if row["CampaignFinanceID"] == "3":
            raise RuntimeError("single-row failure")
        return True

    monkeypatch.setattr(pa_load_module, "_load_pa_row", _load_row)
    rows = [{"CampaignFinanceID": str(index)} for index in range(pa_load_module._COMMIT_BATCH_ROWS)]
    counts = pa_load_module._load_pa_rows(
        conn,
        rows,
        data_source_id=uuid4(),
        data_type="contributions",
        limit=None,
    )

    assert counts.errors == 1
    assert counts.inserted == pa_load_module._COMMIT_BATCH_ROWS - 1
    assert conn.commit_count == 1
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    assert conn.calls.count("savepoint_rollback") == 1
    assert "rollback" not in conn.calls


def test_wait_until_raises_on_timeout_never_defaults_healthy() -> None:
    calls: list[int] = []

    def _never_true() -> bool:
        calls.append(1)
        return False

    with pytest.raises(TimeoutError, match="Timed out"):
        pa_support.wait_until(
            _never_true,
            timeout_seconds=0.05,
            poll_interval_seconds=0.01,
            description="a condition that never holds",
        )
    assert calls


def test_wait_until_raises_on_indeterminate_non_bool() -> None:
    with pytest.raises(TypeError, match="indeterminate"):
        pa_support.wait_until(
            lambda: None,
            timeout_seconds=0.05,
            description="an indeterminate probe",
        )


@pytest.mark.parametrize("test_module_path", _PA_TEST_MODULES, ids=lambda path: path.name)
def test_pa_loader_test_modules_stay_within_line_hard_limit(test_module_path: Path) -> None:
    line_count = len(test_module_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= _TEST_FILE_LINE_HARD_LIMIT, (
        f"{test_module_path.name} has {line_count} lines; split it below "
        f"the {_TEST_FILE_LINE_HARD_LIMIT}-line hard limit"
    )


@pytest.mark.parametrize("test_module_path", _PA_TEST_MODULES, ids=lambda path: path.name)
def test_pa_loader_test_functions_stay_within_line_hard_limit(test_module_path: Path) -> None:
    module = ast.parse(test_module_path.read_text(encoding="utf-8"))
    violations = {
        node.name: node.end_lineno - node.lineno + 1
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.end_lineno is not None
        and node.end_lineno - node.lineno + 1 > _TEST_FUNCTION_LINE_HARD_LIMIT
    }
    assert not violations, (
        f"{test_module_path.name} functions exceed the {_TEST_FUNCTION_LINE_HARD_LIMIT}-line hard limit: {violations}"
    )


@pytest.mark.parametrize(
    ("commit_batch_rows", "expected_gate"),
    [(pa_load_module._COMMIT_BATCH_ROWS, "GATE 1"), (0, "GATE 2")],
)
def test_stage2_gated_row_loader_reports_unreleased_gate(
    monkeypatch: pytest.MonkeyPatch,
    commit_batch_rows: int,
    expected_gate: str,
) -> None:
    job_a = pa_support.PAFixture(Path("unused.csv"), "job-a", "filer-a", [])
    gates = tuple(threading.Event() for _ in range(4))
    monkeypatch.setattr(pa_load_module, "_COMMIT_BATCH_ROWS", commit_batch_rows)
    monkeypatch.setattr(pa_load_module, "_load_pa_row", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(pa_load_tests, "_GATE_TIMEOUT_SECONDS", 0.0)
    gated_loader = pa_load_tests._stage2_gated_row_loader(job_a, gates)

    with pytest.raises(TimeoutError, match=expected_gate):
        gated_loader(
            object(),
            {"CampaignFinanceID": job_a.campaign_finance_id},
            object(),
            data_type="contributions",
        )


def test_lock_release_specimen_gate1_failure_preserves_error_and_cleans_resources(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_fixtures: list[pa_support.PAFixture] = []
    captured_connections: list[psycopg.Connection] = []
    captured_backend_pids: list[int] = []
    event_calls = 0
    real_event_factory = threading.Event
    real_fixture_writer = pa_support.write_pa_fixture_pair
    real_get_connection = pa_load_tests.get_connection

    class _NeverReachedEvent:
        def set(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> bool:
            return False

        def is_set(self) -> bool:
            return False

    def _event_factory():
        nonlocal event_calls
        event_calls += 1
        return _NeverReachedEvent() if event_calls == 1 else real_event_factory()

    def _write_fixture(*args, **kwargs):
        fixture = real_fixture_writer(*args, **kwargs)
        captured_fixtures.append(fixture)
        return fixture

    def _get_connection(*args, **kwargs):
        connection = real_get_connection(*args, **kwargs)
        captured_connections.append(connection)
        captured_backend_pids.append(connection.info.backend_pid)
        return connection

    monkeypatch.setattr(threading, "Event", _event_factory)
    monkeypatch.setattr(pa_support, "write_pa_fixture_pair", _write_fixture)
    monkeypatch.setattr(pa_load_tests, "get_connection", _get_connection)

    try:
        with pytest.raises(AssertionError, match="Job A never reached GATE 1"):
            pa_load_tests.test_load_pa_with_filings_releases_shared_dimension_lock_at_batch_commit(
                db_conn, tmp_path, monkeypatch
            )

        assert len(captured_fixtures) == 2
        assert len(captured_connections) == 2
        assert all(connection.closed for connection in captured_connections)
        assert [bulk_fixture_row_counts(fixture) for fixture in captured_fixtures] == [(0, 0), (0, 0)]
        for backend_pid in captured_backend_pids:
            pa_support.wait_until(
                lambda pid=backend_pid: pa_support.observe_backend_activity(pid) is None,
                timeout_seconds=5.0,
                description=f"test backend pid {backend_pid} to leave pg_stat_activity",
            )
    finally:
        for connection in captured_connections:
            if not connection.closed:
                connection.close()
        for fixture in captured_fixtures:
            cleanup_bulk_fixture(fixture)
