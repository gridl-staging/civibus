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

from api._federal_first_test_support import (
    FEDERAL_FIRST_COUNTS,
    FEDERAL_FIRST_FLOORS,
    FakeConnection,
)

EXPECTED_FEDERAL_FIRST_CHECKS = {
    "cf_transaction_total",
    "core_person_total",
    "civic_officeholding_total",
    "cf_transaction_with_resolved_person",
    "cf_committee_summary_total",
    "cf_transaction_with_support_oppose",
    "cf_transaction_contribution_insights_sentinel",
}


def _load_api_main(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Mirror api/test_main.py loader: env must be set before import."""
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "health-content-test-key")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "20")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "10")
    monkeypatch.delenv("CIVIBUS_ADMIN_API_KEYS", raising=False)
    sys.modules.pop("api.main", None)
    return importlib.import_module("api.main")


def test_federal_first_owner_declares_expected_checks() -> None:
    assert set(FEDERAL_FIRST_COUNTS) == EXPECTED_FEDERAL_FIRST_CHECKS
    assert set(FEDERAL_FIRST_FLOORS) == EXPECTED_FEDERAL_FIRST_CHECKS
    assert FEDERAL_FIRST_COUNTS["cf_transaction_with_support_oppose"] > 0
    assert FEDERAL_FIRST_FLOORS["cf_transaction_with_support_oppose"] > 0
    assert FEDERAL_FIRST_COUNTS["cf_transaction_contribution_insights_sentinel"] > 0
    assert FEDERAL_FIRST_FLOORS["cf_transaction_contribution_insights_sentinel"] > 0


def test_floors_from_env_returns_defaults_when_unset() -> None:
    from api.health_content import floors_from_env

    floors = floors_from_env(env={})

    assert floors == FEDERAL_FIRST_FLOORS


def test_floors_from_env_overrides_specific_keys() -> None:
    from api.health_content import floors_from_env

    floors = floors_from_env(env={"CIVIBUS_HEALTH_CONTENT_FLOOR_CF_TRANSACTION_TOTAL": "42"})

    assert floors["cf_transaction_total"] == 42
    assert floors["cf_committee_summary_total"] == FEDERAL_FIRST_FLOORS["cf_committee_summary_total"]
    assert floors["cf_transaction_with_support_oppose"] == FEDERAL_FIRST_FLOORS["cf_transaction_with_support_oppose"]
    assert (
        floors["cf_transaction_contribution_insights_sentinel"]
        == FEDERAL_FIRST_FLOORS["cf_transaction_contribution_insights_sentinel"]
    )
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
        "cf_committee_summary_total": 20,
        "cf_transaction_with_support_oppose": 5,
        "cf_transaction_contribution_insights_sentinel": 25,
    }
    # Every count is at least the floor — this is a healthy DB.
    counts = [100, 10, 5, 50, 20, 5, 25]
    failures = evaluate_content_health(FakeConnection(counts), floors=floors)

    assert failures == []


def test_evaluate_content_health_accepts_federal_first_floors() -> None:
    from api.health_content import evaluate_content_health

    counts = list(FEDERAL_FIRST_COUNTS.values())

    failures = evaluate_content_health(
        FakeConnection(counts),
        floors=FEDERAL_FIRST_FLOORS,
    )

    assert failures == []


@pytest.mark.parametrize("check_name", FEDERAL_FIRST_COUNTS.keys())
def test_evaluate_content_health_rejects_federal_floor_above_actual(check_name: str) -> None:
    from api.health_content import evaluate_content_health

    floors = dict(FEDERAL_FIRST_FLOORS)
    floors[check_name] = FEDERAL_FIRST_COUNTS[check_name] + 1
    counts = list(FEDERAL_FIRST_COUNTS.values())

    failures = evaluate_content_health(FakeConnection(counts), floors=floors)

    assert len(failures) == 1
    assert failures[0].check == check_name
    assert failures[0].actual == FEDERAL_FIRST_COUNTS[check_name]
    assert failures[0].floor == FEDERAL_FIRST_COUNTS[check_name] + 1


def test_evaluate_content_health_flags_table_below_floor() -> None:
    from api.health_content import evaluate_content_health

    floors = {
        "cf_transaction_total": 1_000_000,
        "core_person_total": 1_000,
        "civic_officeholding_total": 100,
        "cf_transaction_with_resolved_person": 1_000,
        "cf_committee_summary_total": 1_000,
        "cf_transaction_with_support_oppose": 1,
        "cf_transaction_contribution_insights_sentinel": 1,
    }
    # cf.transaction returning 0 is the literal Apr 30 failure mode.
    counts = [0, 5_000, 500, 2_500, 32_404, 1, 1]
    failures = evaluate_content_health(FakeConnection(counts), floors=floors)

    assert len(failures) == 1
    failure = failures[0]
    assert failure.check == "cf_transaction_total"
    assert failure.actual == 0
    assert failure.floor == 1_000_000


def test_evaluate_content_health_runs_expected_sql_queries() -> None:
    """The SQL is the contract. Asserting on text catches typos in
    schema/table names that a smoke test would miss."""
    from api.health_content import evaluate_content_health

    fake = FakeConnection([100, 10, 5, 50, 20, 5, 25])
    evaluate_content_health(
        fake,
        floors={
            "cf_transaction_total": 1,
            "core_person_total": 1,
            "civic_officeholding_total": 1,
            "cf_transaction_with_resolved_person": 1,
            "cf_committee_summary_total": 1,
            "cf_transaction_with_support_oppose": 1,
            "cf_transaction_contribution_insights_sentinel": 1,
        },
    )

    executed = fake._cursor.executed
    transaction_total_query = executed[0]
    assert "pg_stat_user_tables" in transaction_total_query
    assert "n_live_tup" in transaction_total_query
    assert "relname = 'transaction'" in transaction_total_query
    assert "COUNT(*) FROM cf.transaction" not in transaction_total_query
    assert any("core.person" in q for q in executed), executed
    assert any("civic.officeholding" in q for q in executed), executed
    assert any("cf.committee_summary" in q and "WHERE" not in q.upper() for q in executed), executed
    assert any("cf.transaction" in q and "contributor_person_id IS NOT NULL" in q for q in executed), executed
    assert any("cf.transaction" in q and "support_oppose IS NOT NULL" in q for q in executed), executed
    assert any(
        all(
            fragment in q
            for fragment in (
                "cf.transaction",
                "lower(t.contributor_name_raw) LIKE 'bofinger%'",
                "transaction_date >= DATE '2022-01-01'",
                "transaction_type LIKE '1%%'",
                "contributor_entity_type = 'IND'",
                "is_memo = FALSE",
                "amendment_indicator != 'T'",
                "LEFT JOIN core.source_record sr",
                "ON sr.id = t.source_record_id AND sr.superseded_by IS NULL",
                "(t.source_record_id IS NULL OR sr.id IS NOT NULL)",
            )
        )
        for q in executed
    ), executed


def test_evaluate_content_health_reports_contribution_insights_floor_values() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    floors = {key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS}
    floors["cf_transaction_contribution_insights_sentinel"] = 42
    counts = [100, 10, 5, 50, 20, 5, 41]

    failures = evaluate_content_health(FakeConnection(counts), floors=floors)

    assert failures == [
        ContentHealthFailure(
            check="cf_transaction_contribution_insights_sentinel",
            actual=41,
            floor=42,
        )
    ]


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
        response = client.get("/health/content")

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
        response = client.get("/health/content")

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
        response = client.get("/health/content")

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
        response = client.get("/health/content")

    assert response.status_code == 200
