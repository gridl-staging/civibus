"""Tests for the content-aware health probe.

Apr 30 incident background: the prod DB was silently replaced with an empty
volume because docker compose was invoked without the prod overlay.
``/health`` continued returning 200 because the API process itself was up,
so external uptime monitors never paged. This module exists so an empty or
under-populated DB returns 503 — page-able by any standard uptime monitor.

These tests are deliberately strict about *values* (not just shapes) because
this module is the watchdog. A lax test here would mask the exact failure
mode it exists to detect.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _load_api_main(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Mirror api/test_main.py loader: env must be set before import."""
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "health-content-test-key")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "20")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "10")
    monkeypatch.delenv("CIVIBUS_ADMIN_API_KEYS", raising=False)
    sys.modules.pop("api.main", None)
    return importlib.import_module("api.main")


class _FakeCursor:
    """Cursor that returns counts in declaration order of ``_CHECK_QUERIES``.

    The contract under test: ``evaluate_content_health`` runs each query in
    a fixed order and reads ``COUNT(*)`` from row[0]. We verify both the
    query *text* (so a typo in the SQL fails the test) and the count
    handling, hence we assert on ``self.executed`` in the corresponding
    test below.
    """

    def __init__(self, counts: list[int]) -> None:
        self._counts = list(counts)
        self.executed: list[str] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object) -> None:
        # Implementation may pass psycopg.sql.SQL or a plain string; coerce
        # to str so assertions on ``self.executed`` are uniform.
        self.executed.append(str(query))

    def fetchone(self) -> tuple[int]:
        # Fail loud if test setup gives wrong number of counts.
        return (self._counts.pop(0),)


class _FakeConnection:
    def __init__(self, counts: list[int]) -> None:
        self._cursor = _FakeCursor(counts)

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_floors_from_env_returns_defaults_when_unset() -> None:
    from api.health_content import floors_from_env

    floors = floors_from_env(env={})

    # Defaults must reflect prod data volumes; if these defaults regress
    # to zero or a placeholder the watchdog becomes a rubber stamp.
    assert floors["cf_transaction_total"] >= 1_000_000
    assert floors["core_person_total"] >= 1_000
    assert floors["civic_officeholding_total"] >= 100
    assert floors["cf_transaction_with_resolved_person"] >= 1_000


def test_floors_from_env_overrides_specific_keys() -> None:
    from api.health_content import floors_from_env

    floors = floors_from_env(env={"CIVIBUS_HEALTH_CONTENT_FLOOR_CF_TRANSACTION_TOTAL": "42"})

    assert floors["cf_transaction_total"] == 42
    # Unrelated keys must still get defaults — partial override must not zero
    # out other floors.
    assert floors["core_person_total"] >= 1_000


def test_floors_from_env_rejects_negative_values() -> None:
    from api.health_content import floors_from_env

    with pytest.raises(ValueError):
        floors_from_env(env={"CIVIBUS_HEALTH_CONTENT_FLOOR_CORE_PERSON_TOTAL": "-1"})


def test_floors_from_env_rejects_non_integer() -> None:
    from api.health_content import floors_from_env

    with pytest.raises(ValueError):
        floors_from_env(env={"CIVIBUS_HEALTH_CONTENT_FLOOR_CORE_PERSON_TOTAL": "lots"})


def test_evaluate_content_health_returns_empty_when_all_floors_met() -> None:
    from api.health_content import evaluate_content_health

    floors = {
        "cf_transaction_total": 100,
        "core_person_total": 10,
        "civic_officeholding_total": 5,
        "cf_transaction_with_resolved_person": 50,
    }
    # Every count is at least the floor — this is a healthy DB.
    counts = [100, 10, 5, 50]
    failures = evaluate_content_health(_FakeConnection(counts), floors=floors)

    assert failures == []


def test_evaluate_content_health_flags_table_below_floor() -> None:
    from api.health_content import evaluate_content_health

    floors = {
        "cf_transaction_total": 1_000_000,
        "core_person_total": 1_000,
        "civic_officeholding_total": 100,
        "cf_transaction_with_resolved_person": 1_000,
    }
    # cf.transaction returning 0 is the literal Apr 30 failure mode.
    counts = [0, 5_000, 500, 2_500]
    failures = evaluate_content_health(_FakeConnection(counts), floors=floors)

    assert len(failures) == 1
    failure = failures[0]
    assert failure.check == "cf_transaction_total"
    assert failure.actual == 0
    assert failure.floor == 1_000_000


def test_evaluate_content_health_runs_expected_sql_queries() -> None:
    """The SQL is the contract. Asserting on text catches typos in
    schema/table names that a smoke test would miss."""
    from api.health_content import evaluate_content_health

    fake = _FakeConnection([100, 10, 5, 50])
    evaluate_content_health(
        fake,
        floors={
            "cf_transaction_total": 1,
            "core_person_total": 1,
            "civic_officeholding_total": 1,
            "cf_transaction_with_resolved_person": 1,
        },
    )

    executed = fake._cursor.executed
    assert any("cf.transaction" in q and "WHERE" not in q.upper() for q in executed), executed
    assert any("core.person" in q for q in executed), executed
    assert any("civic.officeholding" in q for q in executed), executed
    assert any("cf.transaction" in q and "contributor_person_id IS NOT NULL" in q for q in executed), executed


def test_content_health_endpoint_returns_200_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    import api.health_content as health_content_module

    monkeypatch.setattr(health_content_module, "evaluate_content_health", lambda *a, **k: [])

    fake_pool_connection_cm = MagicMock()
    fake_pool_connection_cm.__enter__ = MagicMock(return_value=MagicMock())
    fake_pool_connection_cm.__exit__ = MagicMock(return_value=None)

    class _FakePool:
        def connection(self):  # noqa: D401
            return fake_pool_connection_cm

        def open(self, *, wait: bool) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_main, "_build_app_connection_pool", lambda: _FakePool())

    with TestClient(api_main.create_app()) as client:
        response = client.get("/api/health/content")

    assert response.status_code == 200
    assert response.json() == {"healthy": True}


def test_content_health_endpoint_returns_503_when_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    import api.health_content as health_content_module
    from api.health_content import ContentHealthFailure

    monkeypatch.setattr(
        health_content_module,
        "evaluate_content_health",
        lambda *a, **k: [ContentHealthFailure(check="cf_transaction_total", actual=0, floor=1_000_000)],
    )

    class _FakePool:
        def connection(self):
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=MagicMock())
            cm.__exit__ = MagicMock(return_value=None)
            return cm

        def open(self, *, wait: bool) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_main, "_build_app_connection_pool", lambda: _FakePool())

    with TestClient(api_main.create_app()) as client:
        response = client.get("/api/health/content")

    assert response.status_code == 503
    body = response.json()
    assert body["healthy"] is False
    # Failure detail must include the specific check name and the values
    # that produced the failure — uptime alerts read these.
    assert body["failures"] == [{"check": "cf_transaction_total", "actual": 0, "floor": 1_000_000}]


def test_content_health_endpoint_returns_503_when_db_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_main = _load_api_main(monkeypatch)

    class _BrokenPool:
        def connection(self):
            raise RuntimeError("simulated db outage")

        def open(self, *, wait: bool) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_main, "_build_app_connection_pool", lambda: _BrokenPool())

    with TestClient(api_main.create_app()) as client:
        response = client.get("/api/health/content")

    assert response.status_code == 503
    body = response.json()
    assert body["healthy"] is False
    assert body["error"] == "db_unreachable"


def test_content_health_endpoint_does_not_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uptime monitors need to hit the endpoint without rotating credentials.
    The probe MUST live outside ``/v1/`` so it bypasses the key middleware."""
    api_main = _load_api_main(monkeypatch)
    import api.health_content as health_content_module

    monkeypatch.setattr(health_content_module, "evaluate_content_health", lambda *a, **k: [])

    class _FakePool:
        def connection(self):
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=MagicMock())
            cm.__exit__ = MagicMock(return_value=None)
            return cm

        def open(self, *, wait: bool) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_main, "_build_app_connection_pool", lambda: _FakePool())

    with TestClient(api_main.create_app()) as client:
        # No X-API-Key header.
        response = client.get("/api/health/content")

    assert response.status_code == 200
