from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi import HTTPException

from api.deps import get_db


def _build_request_with_pool(pool: MagicMock, *, path: str = "/v1/committees") -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)), url=SimpleNamespace(path=path))


class _PoolConnectionContext:
    def __init__(self, connection: MagicMock) -> None:
        self._connection = connection
        self.exit_calls: list[tuple[object, object, object]] = []

    def __enter__(self) -> MagicMock:
        return self._connection

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        self.exit_calls.append((exc_type, exc_value, traceback))
        return False


def test_get_db_yields_connection_and_returns_to_pool_on_normal_exit() -> None:
    connection = MagicMock()
    pool_context_manager = _PoolConnectionContext(connection)
    pool = MagicMock()
    pool.connection.return_value = pool_context_manager

    dependency = get_db(_build_request_with_pool(pool))

    yielded_connection = next(dependency)

    assert yielded_connection is connection
    with pytest.raises(StopIteration):
        next(dependency)

    pool.connection.assert_called_once_with()
    connection.execute.assert_called_once_with("SET LOCAL statement_timeout = 10000")
    assert pool_context_manager.exit_calls == [(None, None, None)]
    connection.close.assert_not_called()


def test_get_db_returns_connection_to_pool_when_consumer_raises() -> None:
    connection = MagicMock()
    pool_context_manager = _PoolConnectionContext(connection)
    pool = MagicMock()
    pool.connection.return_value = pool_context_manager

    dependency = get_db(_build_request_with_pool(pool))

    yielded_connection = next(dependency)

    assert yielded_connection is connection

    with pytest.raises(RuntimeError, match="consumer failed"):
        dependency.throw(RuntimeError("consumer failed"))

    pool.connection.assert_called_once_with()
    connection.execute.assert_called_once_with("SET LOCAL statement_timeout = 10000")
    exit_type, exit_error, exit_traceback = pool_context_manager.exit_calls[0]
    assert exit_type is RuntimeError
    assert isinstance(exit_error, RuntimeError)
    assert str(exit_error) == "consumer failed"
    assert exit_traceback is not None
    connection.close.assert_not_called()


def test_get_db_raises_503_when_pool_checkout_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePoolTimeout(Exception):
        pass

    monkeypatch.setattr("api.deps.PoolTimeout", FakePoolTimeout, raising=False)
    pool = MagicMock()
    pool.connection.side_effect = FakePoolTimeout("database is unavailable")

    dependency = get_db(_build_request_with_pool(pool))

    with pytest.raises(HTTPException) as exc_info:
        next(dependency)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database unavailable"


@pytest.mark.parametrize(
    ("path", "expected_timeout_ms"),
    [
        ("/v1/donors/search", 10_000),
        ("/public/v1/federal/export.json", 30_000),
        ("/public/v1/federal/export.csv", 30_000),
    ],
)
def test_get_db_sets_path_specific_statement_timeout(path: str, expected_timeout_ms: int) -> None:
    connection = MagicMock()
    pool_context_manager = _PoolConnectionContext(connection)
    pool = MagicMock()
    pool.connection.return_value = pool_context_manager

    dependency = get_db(_build_request_with_pool(pool, path=path))

    assert next(dependency) is connection
    with pytest.raises(StopIteration):
        next(dependency)

    connection.execute.assert_called_once_with(f"SET LOCAL statement_timeout = {expected_timeout_ms}")


def test_get_db_statement_timeout_env_overrides_are_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVIBUS_API_STATEMENT_TIMEOUT_MS", "12000")
    monkeypatch.setenv("CIVIBUS_API_EXPORT_STATEMENT_TIMEOUT_MS", "45000")
    connection = MagicMock()
    pool_context_manager = _PoolConnectionContext(connection)
    pool = MagicMock()
    pool.connection.return_value = pool_context_manager

    dependency = get_db(_build_request_with_pool(pool, path="/public/v1/federal/export.json"))

    assert next(dependency) is connection
    with pytest.raises(StopIteration):
        next(dependency)

    connection.execute.assert_called_once_with("SET LOCAL statement_timeout = 45000")

    monkeypatch.setenv("CIVIBUS_API_STATEMENT_TIMEOUT_MS", "0")
    failing_dependency = get_db(_build_request_with_pool(pool, path="/v1/donors/search"))
    with pytest.raises(RuntimeError, match="CIVIBUS_API_STATEMENT_TIMEOUT_MS"):
        next(failing_dependency)


def test_get_db_maps_query_cancellation_to_504() -> None:
    connection = MagicMock()
    pool_context_manager = _PoolConnectionContext(connection)
    pool = MagicMock()
    pool.connection.return_value = pool_context_manager

    dependency = get_db(_build_request_with_pool(pool))

    assert next(dependency) is connection

    with pytest.raises(HTTPException) as exc_info:
        dependency.throw(psycopg.errors.QueryCanceled("statement timeout"))

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "Database query exceeded the request time limit"
    exit_type, exit_error, exit_traceback = pool_context_manager.exit_calls[0]
    assert exit_type is HTTPException
    assert isinstance(exit_error, HTTPException)
    assert exit_traceback is not None
