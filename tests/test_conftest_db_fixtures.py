from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import api.conftest as api_conftest
import conftest as root_conftest

pytestmark = pytest.mark.unit
_POSTGRES_UNAVAILABLE = "Unable to connect to PostgreSQL at localhost:5433/civibus"


def _raise_runtime_error(message: str):
    def _raiser(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(message)

    return _raiser


def _mock_canonical_contest_result_preflight(connection: MagicMock) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (True,),
        (True, True, False),
    ]
    connection.cursor.return_value.__enter__.return_value = cursor
    return cursor


def _assert_fixture_skips_when_postgres_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    fixture_func: object,
) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        root_conftest,
        "get_connection",
        _raise_runtime_error(_POSTGRES_UNAVAILABLE),
    )
    monkeypatch.setattr(root_conftest.time, "sleep", sleep_calls.append)

    wrapped_fixture = fixture_func.__wrapped__
    with pytest.raises(pytest.skip.Exception, match=_POSTGRES_UNAVAILABLE):
        next(wrapped_fixture())
    assert sleep_calls == [root_conftest._DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS] * (
        root_conftest._DB_CONNECTION_STARTUP_RETRY_ATTEMPTS - 1
    )


def test_db_conn_fixture_skips_when_postgres_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_fixture_skips_when_postgres_is_unavailable(monkeypatch, root_conftest.db_conn)


def test_graph_conn_fixture_skips_when_postgres_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_fixture_skips_when_postgres_is_unavailable(monkeypatch, root_conftest.graph_conn)


def test_db_conn_fixture_retries_transient_startup_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_connection = MagicMock()
    _mock_canonical_contest_result_preflight(mocked_connection)
    sleep_calls: list[float] = []
    attempt_count = 0

    def _get_connection_after_retries(*_args: object, **_kwargs: object) -> object:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise RuntimeError(_POSTGRES_UNAVAILABLE)
        return mocked_connection

    monkeypatch.setattr(root_conftest, "get_connection", _get_connection_after_retries)
    monkeypatch.setattr(root_conftest.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(root_conftest, "_collect_missing_stage1_canaries", lambda _connection: [])

    wrapped_fixture = root_conftest.db_conn.__wrapped__
    fixture_generator = wrapped_fixture()

    connection = next(fixture_generator)

    assert connection is mocked_connection
    assert attempt_count == 3
    assert sleep_calls == [root_conftest._DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS] * 2

    fixture_generator.close()
    assert mocked_connection.rollback.call_count == 2
    mocked_connection.execute.assert_called_once_with("BEGIN")
    mocked_connection.close.assert_called_once()


def test_db_conn_fixture_fails_fast_when_stage1_canaries_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_connection = MagicMock()
    mocked_cursor = _mock_canonical_contest_result_preflight(mocked_connection)
    mocked_cursor.fetchone.side_effect = [
        (True,),
        (True, True, False),
        (False,),
    ]
    monkeypatch.setattr(root_conftest, "get_connection", lambda *_args, **_kwargs: mocked_connection)
    monkeypatch.setattr(
        root_conftest,
        "_collect_missing_stage1_canaries",
        lambda _connection: ["core.person_er_view", "core.match_decision"],
    )

    with pytest.raises(pytest.fail.Exception) as excinfo:
        next(root_conftest.db_conn.__wrapped__())

    message = str(excinfo.value)
    assert "Stage 1 bootstrap contract drift detected" in message
    assert "core.person_er_view" in message
    assert "core.match_decision" in message
    mocked_connection.close.assert_called_once()
    mocked_connection.execute.assert_not_called()


def test_graph_conn_fixture_preflights_before_ensure_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    drifted_connection = MagicMock()
    _mock_canonical_contest_result_preflight(drifted_connection)
    ensure_graph_calls: list[MagicMock] = []
    monkeypatch.setattr(root_conftest, "get_connection", lambda *_args, **_kwargs: drifted_connection)
    monkeypatch.setattr(
        root_conftest,
        "_collect_missing_stage1_canaries",
        lambda _connection: ["ag_catalog.ag_graph.civibus"],
    )
    monkeypatch.setattr(root_conftest, "ensure_graph", lambda connection: ensure_graph_calls.append(connection))

    with pytest.raises(pytest.fail.Exception) as excinfo:
        next(root_conftest.graph_conn.__wrapped__())

    message = str(excinfo.value)
    assert "Stage 1 bootstrap contract drift detected" in message
    assert "ag_catalog.ag_graph.civibus" in message
    assert ensure_graph_calls == []
    drifted_connection.rollback.assert_called_once()
    drifted_connection.close.assert_called_once()

    healthy_connection = MagicMock()
    _mock_canonical_contest_result_preflight(healthy_connection)
    call_order: list[str] = []

    monkeypatch.setattr(root_conftest, "get_connection", lambda *_args, **_kwargs: healthy_connection)
    monkeypatch.setattr(
        root_conftest,
        "_collect_missing_stage1_canaries",
        lambda _connection: call_order.append("preflight") or [],
    )
    monkeypatch.setattr(
        root_conftest,
        "ensure_graph",
        lambda connection: call_order.append("ensure_graph") or ensure_graph_calls.append(connection),
    )

    fixture_generator = root_conftest.graph_conn.__wrapped__()
    connection = next(fixture_generator)

    assert connection is healthy_connection
    assert call_order == ["preflight", "ensure_graph"]
    assert ensure_graph_calls == [healthy_connection]

    fixture_generator.close()
    assert healthy_connection.commit.call_count == 2
    healthy_connection.execute.assert_called_once_with("BEGIN")
    healthy_connection.rollback.assert_called_once_with()
    healthy_connection.close.assert_called_once_with()


def test_api_client_chain_fails_fast_from_db_conn_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_connection = MagicMock()
    _mock_canonical_contest_result_preflight(mocked_connection)
    build_calls: list[MagicMock] = []
    monkeypatch.setattr(root_conftest, "get_connection", lambda *_args, **_kwargs: mocked_connection)
    monkeypatch.setattr(
        root_conftest,
        "_collect_missing_stage1_canaries",
        lambda _connection: ["core.organization_er_view"],
    )

    def _build_client(connection: MagicMock) -> SimpleNamespace:
        build_calls.append(connection)
        return SimpleNamespace(app=SimpleNamespace(dependency_overrides={}))

    monkeypatch.setattr(api_conftest, "_build_api_test_client", _build_client)

    with pytest.raises(pytest.fail.Exception, match="core.organization_er_view"):
        db_generator = root_conftest.db_conn.__wrapped__()
        db_conn = next(db_generator)
        next(api_conftest.api_client.__wrapped__(db_conn))

    assert build_calls == []


def test_graph_api_client_chain_fails_fast_from_graph_conn_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_connection = MagicMock()
    _mock_canonical_contest_result_preflight(mocked_connection)
    build_calls: list[MagicMock] = []
    monkeypatch.setattr(root_conftest, "get_connection", lambda *_args, **_kwargs: mocked_connection)
    monkeypatch.setattr(
        root_conftest,
        "_collect_missing_stage1_canaries",
        lambda _connection: ["ag_catalog.ag_graph.civibus"],
    )

    def _build_client(connection: MagicMock) -> SimpleNamespace:
        build_calls.append(connection)
        return SimpleNamespace(app=SimpleNamespace(dependency_overrides={}))

    monkeypatch.setattr(api_conftest, "_build_api_test_client", _build_client)

    with pytest.raises(pytest.fail.Exception, match="ag_catalog.ag_graph.civibus"):
        graph_generator = root_conftest.graph_conn.__wrapped__()
        graph_conn = next(graph_generator)
        next(api_conftest.graph_api_client.__wrapped__(graph_conn))

    assert build_calls == []


def test_contest_result_bootstrap_sql_uses_canonical_constraint_contract() -> None:
    bootstrap_sql = root_conftest._contest_result_bootstrap_sql()

    assert "CONSTRAINT uq_contest_result_canonical UNIQUE" in bootstrap_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_contest_result_canonical" not in bootstrap_sql


def test_contest_result_bootstrap_sql_creates_civic_schema_before_table() -> None:
    bootstrap_sql = root_conftest._contest_result_bootstrap_sql()

    assert "CREATE SCHEMA IF NOT EXISTS civic;" in bootstrap_sql
    assert bootstrap_sql.index("CREATE SCHEMA IF NOT EXISTS civic;") < bootstrap_sql.index(
        "CREATE TABLE civic.contest_result"
    )


def test_stage1_preflight_does_not_mutate_existing_contest_result_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked_connection = MagicMock()
    mocked_cursor = MagicMock()
    mocked_cursor.fetchone.side_effect = [
        (True,),
        (True, True, False),
    ]
    mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
    monkeypatch.setattr(root_conftest, "_collect_missing_stage1_canaries", lambda _connection: [])

    root_conftest._fail_if_stage1_bootstrap_drift_detected(mocked_connection)

    executed_sql = [str(call.args[0]) for call in mocked_cursor.execute.call_args_list]
    forbidden_snippets = (
        "ALTER TABLE civic.contest_result",
        "UPDATE civic.contest_result",
        "ADD CONSTRAINT uq_contest_result_canonical",
        "DROP TRIGGER IF EXISTS trg_contest_result_updated_at",
        "CREATE TRIGGER trg_contest_result_updated_at",
    )
    for forbidden_snippet in forbidden_snippets:
        assert forbidden_snippet not in "\n".join(executed_sql)


def test_stage1_preflight_bootstraps_missing_stage1_canaries_before_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked_connection = MagicMock()
    mocked_cursor = MagicMock()
    mocked_cursor.fetchone.side_effect = [
        (True,),   # to_regclass('civic.contest_result')
        (True, True, False),  # canonical contest_result contract checks
        (False,),  # to_regclass('core.match_decision') in helper
    ]
    mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor

    missing_then_healthy = iter(
        [
            [
                "civic.officeholding.date_precision",
                "core.person_er_view",
                "core.organization_er_view",
                "core.match_decision",
            ],
            [],
        ]
    )
    monkeypatch.setattr(
        root_conftest,
        "_collect_missing_stage1_canaries",
        lambda _connection: next(missing_then_healthy),
    )

    root_conftest._fail_if_stage1_bootstrap_drift_detected(mocked_connection)

    executed_sql = [str(call.args[0]) for call in mocked_cursor.execute.call_args_list]
    assert any("ALTER TABLE civic.officeholding" in sql for sql in executed_sql)
    assert any("CREATE OR REPLACE VIEW core.person_er_view" in sql for sql in executed_sql)
    assert any("CREATE TABLE core.match_decision" in sql for sql in executed_sql)


def test_stage1_canary_bootstrap_repairs_only_match_decision_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked_connection = MagicMock()
    mocked_cursor = MagicMock()
    mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor
    monkeypatch.setattr(root_conftest, "_relation_exists", lambda *_args, **_kwargs: False)

    root_conftest._bootstrap_missing_stage1_canaries(
        mocked_connection,
        missing_canaries=["core.match_decision"],
    )

    executed_sql = "\n".join(str(call.args[0]) for call in mocked_cursor.execute.call_args_list)
    assert "CREATE TABLE core.match_decision" in executed_sql
    assert "CREATE TABLE core.entity_cluster" not in executed_sql
    assert "CREATE TABLE core.cluster_member" not in executed_sql


def test_stage1_canary_bootstrap_repairs_missing_contest_result_columns() -> None:
    mocked_connection = MagicMock()
    mocked_cursor = MagicMock()
    mocked_connection.cursor.return_value.__enter__.return_value = mocked_cursor

    root_conftest._bootstrap_missing_stage1_canaries(
        mocked_connection,
        missing_canaries=[
            "civic.contest_result.candidate_name",
            "civic.contest_result.votes",
            "civic.contest_result.vote_pct",
            "civic.contest_result.is_certified",
        ],
    )

    executed_sql = "\n".join(str(call.args[0]) for call in mocked_cursor.execute.call_args_list)
    assert "ALTER TABLE civic.contest_result" in executed_sql
    assert "ADD COLUMN IF NOT EXISTS candidate_name" in executed_sql
    assert "ADD COLUMN IF NOT EXISTS votes" in executed_sql
    assert "ADD COLUMN IF NOT EXISTS vote_pct" in executed_sql
    assert "ADD COLUMN IF NOT EXISTS is_certified" in executed_sql
