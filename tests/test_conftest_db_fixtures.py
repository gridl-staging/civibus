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
    healthy_connection.commit.assert_called_once_with()
    healthy_connection.execute.assert_called_once_with("BEGIN")
    healthy_connection.rollback.assert_called_once_with()
    healthy_connection.close.assert_called_once_with()


def test_api_client_chain_fails_fast_from_db_conn_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    mocked_connection = MagicMock()
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
