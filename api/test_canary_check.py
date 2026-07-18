"""Tests for the API container startup canary.

The canary is the mechanical guard against the Apr 30 incident class:
bringing up an API process against an empty/wrong DB. It must:

* exit 0 only when ``evaluate_content_health`` returns no failures
* exit 1 when failures are present (don't let the container start)
* exit 1 when the DB is unreachable past the configured deadline
* exit 0 when explicitly skipped via env (dev / fresh-DB bootstrap / CI)

These tests stub out ``get_connection`` and ``evaluate_content_health``
so the canary's flow can be exercised without a live Postgres.
"""

from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from api._federal_first_test_support import (
    FEDERAL_FIRST_COUNTS,
    FEDERAL_FIRST_FLOORS,
    FakeConnection,
    set_federal_floor_env,
)


REQUIRED_SCHEMA_COLUMNS = (
    ("civic", "zcta_district", "boundary_year"),
    ("cf", "candidate", "candidate_contrib"),
    ("cf", "candidate", "candidate_loans"),
    ("cf", "candidate", "candidate_loan_repay"),
)


class FakeCanaryCursor:
    def __init__(self, present_columns: set[tuple[str, str, str]]) -> None:
        self.present_columns = present_columns
        self.executed: list[tuple[object, object]] = []
        self._rows: list[tuple[str, str, str]] = []

    def __enter__(self) -> "FakeCanaryCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> None:
        self.executed.append((query, params))
        required_columns = {(params[index], params[index + 1], params[index + 2]) for index in range(0, len(params), 3)}
        self._rows = sorted(required_columns - self.present_columns)

    def fetchall(self) -> list[tuple[str, str, str]]:
        return self._rows


class FakeCanaryConnection:
    def __init__(self, present_columns: set[tuple[str, str, str]]) -> None:
        self.cursor_instance = FakeCanaryCursor(present_columns)
        self.closed = False
        self.close_count = 0

    def cursor(self) -> FakeCanaryCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.close_count += 1
        self.closed = True


class RecordingLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _fresh_canary_module() -> ModuleType:
    sys.modules.pop("api.canary_check", None)
    return importlib.import_module("api.canary_check")


def test_canary_exits_zero_when_skip_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_STARTUP_CANARY", "skip")
    canary = _fresh_canary_module()

    # If skip is honoured, get_connection MUST NOT be called — that's the
    # point of skip (e.g. fresh DB bootstrap before there's data to check).
    sentinel_called = MagicMock()
    monkeypatch.setattr(canary, "get_connection", sentinel_called)

    assert canary.main() == 0
    sentinel_called.assert_not_called()


def test_canary_exits_zero_when_health_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    canary = _fresh_canary_module()

    fake_connection = FakeCanaryConnection(set(REQUIRED_SCHEMA_COLUMNS))
    evaluate_content_health = MagicMock(return_value=[])
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)
    monkeypatch.setattr(canary, "evaluate_content_health", evaluate_content_health)

    assert canary.main() == 0
    evaluate_content_health.assert_called_once()
    assert evaluate_content_health.call_args.args[0] is fake_connection
    assert fake_connection.close_count == 1


def test_canary_exits_one_when_health_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    canary = _fresh_canary_module()
    from api.health_content import ContentHealthFailure

    fake_connection = FakeCanaryConnection(set(REQUIRED_SCHEMA_COLUMNS))
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)
    monkeypatch.setattr(
        canary,
        "evaluate_content_health",
        lambda *a, **k: [ContentHealthFailure(check="cf_transaction_total", actual=0, floor=1_000_000)],
    )

    assert canary.main() == 1
    # Even on failure the connection must close, otherwise repeated boot
    # attempts leak DB connections.
    assert fake_connection.closed is True


@pytest.mark.parametrize("missing_column", REQUIRED_SCHEMA_COLUMNS)
def test_canary_exits_one_when_required_schema_column_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    missing_column: tuple[str, str, str],
) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    canary = _fresh_canary_module()
    present_columns = set(REQUIRED_SCHEMA_COLUMNS) - {missing_column}
    fake_connection = FakeCanaryConnection(present_columns)
    evaluate_content_health = MagicMock(return_value=[])
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)
    monkeypatch.setattr(canary, "evaluate_content_health", evaluate_content_health)
    log_handler = RecordingLogHandler()
    logger = logging.getLogger("civibus.api.canary")
    logger.addHandler(log_handler)
    try:
        assert canary.main() == 1
    finally:
        logger.removeHandler(log_handler)

    executed = fake_connection.cursor_instance.executed
    assert len(executed) == 1
    query, params = executed[0]
    assert "information_schema.columns" in str(query)
    assert {(params[index], params[index + 1], params[index + 2]) for index in range(0, len(params), 3)} == set(
        REQUIRED_SCHEMA_COLUMNS
    )
    schema, table, column = missing_column
    assert f"schema_column:{schema}.{table}.{column}" in "\n".join(log_handler.messages)
    evaluate_content_health.assert_not_called()
    assert fake_connection.close_count == 1


def test_canary_exits_zero_with_federal_first_floors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    set_federal_floor_env(monkeypatch, FEDERAL_FIRST_FLOORS)
    canary = _fresh_canary_module()

    fake_connection = FakeConnection(list(FEDERAL_FIRST_COUNTS.values()))
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)

    assert canary.main() == 0
    assert fake_connection.closed is True


@pytest.mark.parametrize("check_name", FEDERAL_FIRST_COUNTS.keys())
def test_canary_exits_one_when_any_federal_floor_exceeds_actual(
    monkeypatch: pytest.MonkeyPatch,
    check_name: str,
) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    floors = dict(FEDERAL_FIRST_FLOORS)
    floors[check_name] = FEDERAL_FIRST_COUNTS[check_name] + 1
    set_federal_floor_env(monkeypatch, floors)
    canary = _fresh_canary_module()

    fake_connection = FakeConnection(list(FEDERAL_FIRST_COUNTS.values()))
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)

    assert canary.main() == 1
    assert fake_connection.closed is True


def test_canary_exits_one_when_db_unreachable_past_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    # Tight deadline keeps the test fast.
    monkeypatch.setenv("CIVIBUS_STARTUP_CANARY_TIMEOUT_SECONDS", "0.5")
    canary = _fresh_canary_module()

    def _boom() -> None:
        raise RuntimeError("simulated db outage")

    monkeypatch.setattr(canary, "get_connection", _boom)
    missing_required_schema_checks = MagicMock(return_value=[])
    evaluate_content_health = MagicMock(return_value=[])
    monkeypatch.setattr(canary, "_missing_required_schema_checks", missing_required_schema_checks)
    monkeypatch.setattr(canary, "evaluate_content_health", evaluate_content_health)

    assert canary.main() == 1
    missing_required_schema_checks.assert_not_called()
    evaluate_content_health.assert_not_called()
