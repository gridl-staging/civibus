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
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api._federal_first_test_support import (
    FEDERAL_FIRST_COUNTS,
    FEDERAL_FIRST_FLOORS,
    FakeConnection,
    fresh_federal_fec_bulk_pull_row,
)

FEC_FRESHNESS_CHECK = "campaign_finance_federal_fec_fresh"
FIXED_NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
FEC_FRESHNESS_CUTOFF = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
FEC_FRESHNESS_CUTOFF_EPOCH = 1_784_289_600
FEC_FRESHNESS_STALE_EPOCH = 1_784_289_599
CANDIDATE_MONEY_COVERAGE_CHECK = "cf_candidate_money_serving_coverage"
CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK = "cf_candidate_money_recent_summary_coverage"
CANDIDATE_MONEY_PRODUCTION_OBSERVATION = 2_079
CANDIDATE_MONEY_DEFAULT_FLOOR = 1_800
CANDIDATE_MONEY_RECENT_SUMMARY_PRODUCTION_OBSERVATION = 1_799
CANDIDATE_MONEY_RECENT_SUMMARY_DEFAULT_FLOOR = 1_440
CANDIDATE_MONEY_RECENT_SUMMARY_CUTOFF = date(2026, 3, 29)
CANDIDATE_MONEY_RECENT_SUMMARY_EVALUATION_DATE = date(2026, 7, 27)
CANDIDATE_MONEY_RECENT_SUMMARY_FRESH_FEC_ROW = (datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),)

EXPECTED_FEDERAL_FIRST_CHECKS = {
    "cf_transaction_total",
    "core_person_total",
    "civic_officeholding_total",
    "cf_transaction_with_resolved_person",
    "cf_committee_summary_total",
    "cf_transaction_with_support_oppose",
    "cf_transaction_contribution_insights_sentinel",
    CANDIDATE_MONEY_COVERAGE_CHECK,
    CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK,
}


@dataclass(frozen=True)
class _SyntheticSelectedCycle:
    coverage_start_date: date
    coverage_end_date: date


def _healthy_counts() -> list[int]:
    return list(FEDERAL_FIRST_COUNTS.values())


def _healthy_connection(*, freshness_result: tuple[object, ...] | None) -> FakeConnection:
    return FakeConnection(_healthy_counts(), freshness_result=freshness_result)


def _is_transaction_confirm_query(query: str) -> bool:
    normalized_query = " ".join(query.lower().split())
    return "select count(*) from cf.transaction" in normalized_query and " where " not in normalized_query


def _normalized_sql(query: str) -> str:
    return " ".join(query.replace("\\n", " ").split())


def _candidate_money_serving_query_indices(fake: FakeConnection) -> list[int]:
    return [
        index
        for index, query in enumerate(fake._cursor.executed)
        if (
            "FROM cf.candidate" in query
            and "summary_coverage_end_date BETWEEN %s AND %s" in query
            and "summary_coverage_end_date >= %s" not in query
        )
    ]


def _candidate_money_recent_summary_query_indices(fake: FakeConnection) -> list[int]:
    return [
        index
        for index, query in enumerate(fake._cursor.executed)
        if (
            "FROM cf.candidate" in query
            and "summary_coverage_end_date BETWEEN %s AND %s" in query
            and "summary_coverage_end_date >= %s" in query
        )
    ]


def _single_query(fake: FakeConnection, indices: list[int]) -> str:
    assert len(indices) == 1, fake._cursor.executed
    return fake._cursor.executed[indices[0]]


def _single_query_params(fake: FakeConnection, indices: list[int]) -> object:
    assert len(indices) == 1, fake._cursor.executed
    return fake._cursor.executed_params[indices[0]]


def _candidate_money_query(fake: FakeConnection) -> str:
    candidate_query_indices = _candidate_money_serving_query_indices(fake)
    assert len(candidate_query_indices) == 1, fake._cursor.executed
    return fake._cursor.executed[candidate_query_indices[0]]


def _candidate_money_query_params(fake: FakeConnection) -> object:
    candidate_query_indices = _candidate_money_serving_query_indices(fake)
    assert len(candidate_query_indices) == 1, fake._cursor.executed
    return fake._cursor.executed_params[candidate_query_indices[0]]


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
    assert FEDERAL_FIRST_COUNTS[CANDIDATE_MONEY_COVERAGE_CHECK] == CANDIDATE_MONEY_PRODUCTION_OBSERVATION
    assert FEDERAL_FIRST_FLOORS[CANDIDATE_MONEY_COVERAGE_CHECK] == CANDIDATE_MONEY_DEFAULT_FLOOR
    assert (
        FEDERAL_FIRST_COUNTS[CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK]
        == CANDIDATE_MONEY_RECENT_SUMMARY_PRODUCTION_OBSERVATION
    )
    assert (
        FEDERAL_FIRST_FLOORS[CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK]
        == CANDIDATE_MONEY_RECENT_SUMMARY_DEFAULT_FLOOR
    )
    # Keep the deploy-safe default below the 2026-07-27 production observation:
    # docs/live-state/2026_07_27_candidate_money_production_coverage.md
    # Follow-up: the tighter post-recovery bound is recorded in the receipt,
    # not shipped as the default floor while production is still at 2,079.
    assert FEDERAL_FIRST_FLOORS[CANDIDATE_MONEY_COVERAGE_CHECK] < CANDIDATE_MONEY_PRODUCTION_OBSERVATION
    assert (
        FEDERAL_FIRST_FLOORS[CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK]
        < CANDIDATE_MONEY_RECENT_SUMMARY_PRODUCTION_OBSERVATION
    )
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

    floors = floors_from_env(
        env={
            "CIVIBUS_HEALTH_CONTENT_FLOOR_CF_TRANSACTION_TOTAL": "42",
            "CIVIBUS_HEALTH_CONTENT_FLOOR_CF_CANDIDATE_MONEY_SERVING_COVERAGE": "43",
            "CIVIBUS_HEALTH_CONTENT_FLOOR_CF_CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE": "44",
        }
    )

    assert floors["cf_transaction_total"] == 42
    assert floors[CANDIDATE_MONEY_COVERAGE_CHECK] == 43
    assert floors[CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK] == 44
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
        CANDIDATE_MONEY_COVERAGE_CHECK: 30,
        CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK: 30,
    }
    # Every count is at least the floor — this is a healthy DB.
    counts = [100, 10, 5, 50, 20, 5, 25, 30, 30]
    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=fresh_federal_fec_bulk_pull_row()),
        floors=floors,
    )

    assert failures == []


def test_evaluate_content_health_accepts_federal_first_floors() -> None:
    from api.health_content import evaluate_content_health

    counts = list(FEDERAL_FIRST_COUNTS.values())

    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=fresh_federal_fec_bulk_pull_row()),
        floors=FEDERAL_FIRST_FLOORS,
    )

    assert failures == []


def test_evaluate_content_health_confirms_stale_low_transaction_estimate() -> None:
    from api.health_content import evaluate_content_health

    counts = list(FEDERAL_FIRST_COUNTS.values())
    counts[0] = 0
    fake = FakeConnection(
        counts,
        freshness_result=fresh_federal_fec_bulk_pull_row(),
        transaction_confirm_count=FEDERAL_FIRST_COUNTS["cf_transaction_total"],
    )

    failures = evaluate_content_health(
        fake,
        floors=FEDERAL_FIRST_FLOORS,
    )

    assert failures == []
    assert any(_is_transaction_confirm_query(query) for query in fake._cursor.executed)


def test_evaluate_content_health_flags_confirmed_transaction_loss() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    floors = dict(FEDERAL_FIRST_FLOORS)
    floors["cf_transaction_total"] = 1_000
    counts = list(FEDERAL_FIRST_COUNTS.values())
    counts[0] = 0

    failures = evaluate_content_health(
        FakeConnection(
            counts,
            freshness_result=fresh_federal_fec_bulk_pull_row(),
            transaction_confirm_count=100,
        ),
        floors=floors,
    )

    assert failures == [
        ContentHealthFailure(
            check="cf_transaction_total",
            actual=100,
            floor=1_000,
        )
    ]


def test_evaluate_content_health_skips_transaction_confirmation_when_estimate_is_healthy() -> None:
    from api.health_content import evaluate_content_health

    fake = FakeConnection(
        list(FEDERAL_FIRST_COUNTS.values()),
        freshness_result=fresh_federal_fec_bulk_pull_row(),
        transaction_confirm_count=AssertionError("confirmation count should not run"),
    )

    failures = evaluate_content_health(
        fake,
        floors=FEDERAL_FIRST_FLOORS,
    )

    assert failures == []
    assert not any(_is_transaction_confirm_query(query) for query in fake._cursor.executed)


def test_evaluate_content_health_fails_when_transaction_confirmation_is_indeterminate() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    counts = list(FEDERAL_FIRST_COUNTS.values())
    counts[0] = 0

    fake = FakeConnection(
        counts,
        freshness_result=fresh_federal_fec_bulk_pull_row(),
        transaction_confirm_count=TimeoutError("simulated statement timeout"),
    )

    failures = evaluate_content_health(
        fake,
        floors=FEDERAL_FIRST_FLOORS,
    )

    assert any(_is_transaction_confirm_query(query) for query in fake._cursor.executed)
    assert failures == [
        ContentHealthFailure(
            check="cf_transaction_total",
            actual=0,
            floor=FEDERAL_FIRST_FLOORS["cf_transaction_total"],
        )
    ]


@pytest.mark.parametrize("check_name", FEDERAL_FIRST_COUNTS.keys())
def test_evaluate_content_health_rejects_federal_floor_above_actual(check_name: str) -> None:
    from api.health_content import evaluate_content_health

    floors = dict(FEDERAL_FIRST_FLOORS)
    floors[check_name] = FEDERAL_FIRST_COUNTS[check_name] + 1
    counts = _healthy_counts()

    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=fresh_federal_fec_bulk_pull_row()),
        floors=floors,
    )

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
        CANDIDATE_MONEY_COVERAGE_CHECK: 1,
        CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK: 1,
    }
    # cf.transaction returning 0 is the literal Apr 30 failure mode.
    counts = [0, 5_000, 500, 2_500, 32_404, 1, 1, 1, 1]
    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=fresh_federal_fec_bulk_pull_row()),
        floors=floors,
    )

    assert len(failures) == 1
    failure = failures[0]
    assert failure.check == "cf_transaction_total"
    assert failure.actual == 0
    assert failure.floor == 1_000_000


def test_evaluate_content_health_runs_expected_sql_queries() -> None:
    """The SQL is the contract. Asserting on text catches typos in
    schema/table names that a smoke test would miss."""
    from api.health_content import evaluate_content_health

    from api.queries.campaign_finance import resolve_selected_cycle

    selected = resolve_selected_cycle(None)
    fake = FakeConnection([100, 10, 5, 50, 20, 5, 25, 30, 31], freshness_result=fresh_federal_fec_bulk_pull_row())
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
            CANDIDATE_MONEY_COVERAGE_CHECK: 1,
            CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK: 1,
        },
        now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
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
                "t.source_record_id IS NULL",
                "OR t.source_record_id NOT IN",
                "SELECT superseded.id",
                "FROM core.source_record superseded",
                "WHERE superseded.superseded_by IS NOT NULL",
            )
        )
        for q in executed
    ), executed
    candidate_query = _normalized_sql(_candidate_money_query(fake))
    assert (
        "total_receipts IS NOT NULL OR total_disbursements IS NOT NULL OR cash_on_hand IS NOT NULL"
    ) in candidate_query
    assert "summary_coverage_end_date BETWEEN %s AND %s" in candidate_query
    assert _candidate_money_query_params(fake) == (selected.coverage_start_date, selected.coverage_end_date)
    recent_summary_query = _normalized_sql(_single_query(fake, _candidate_money_recent_summary_query_indices(fake)))
    assert (
        "total_receipts IS NOT NULL OR total_disbursements IS NOT NULL OR cash_on_hand IS NOT NULL"
    ) in recent_summary_query
    assert "summary_coverage_end_date BETWEEN %s AND %s" in recent_summary_query
    assert "summary_coverage_end_date >= %s" in recent_summary_query
    assert "summary_coverage_end_date <= %s" in recent_summary_query
    assert _single_query_params(fake, _candidate_money_recent_summary_query_indices(fake)) == (
        selected.coverage_start_date,
        selected.coverage_end_date,
        CANDIDATE_MONEY_RECENT_SUMMARY_CUTOFF,
        CANDIDATE_MONEY_RECENT_SUMMARY_EVALUATION_DATE,
    )
    freshness_query = executed[-1]
    freshness_params = fake._cursor.executed_params[-1]
    assert "MAX(last_pull_at)" in freshness_query
    assert "FROM core.data_source" in freshness_query
    assert "last_pull_status = %s" in freshness_query
    assert "core.source_record" not in freshness_query
    assert "core.refresh_run" not in freshness_query
    assert "copied" not in freshness_query.lower()
    assert freshness_params == (
        "campaign_finance",
        "federal/fec",
        "FEC Bulk Data",
        "success",
    )


def test_candidate_money_serving_coverage_count() -> None:
    from api.health_content import candidate_money_serving_coverage_count
    from api.queries.campaign_finance import resolve_selected_cycle

    cycle = 2026
    selected = resolve_selected_cycle(cycle)
    fake = FakeConnection([17])

    count = candidate_money_serving_coverage_count(fake, cycle=cycle)

    normalized_sql = _normalized_sql(_candidate_money_query(fake))
    assert count == 17
    assert (
        "total_receipts IS NOT NULL OR total_disbursements IS NOT NULL OR cash_on_hand IS NOT NULL"
    ) in normalized_sql
    assert "summary_coverage_end_date BETWEEN %s AND %s" in normalized_sql
    assert _candidate_money_query_params(fake) == (selected.coverage_start_date, selected.coverage_end_date)


def test_evaluate_content_health_flags_candidate_money_coverage_below_floor() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    floors = {key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS}
    floors[CANDIDATE_MONEY_COVERAGE_CHECK] = CANDIDATE_MONEY_DEFAULT_FLOOR
    counts = [100, 10, 5, 50, 20, 5, 25, CANDIDATE_MONEY_DEFAULT_FLOOR - 1, 30]

    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=fresh_federal_fec_bulk_pull_row()),
        floors=floors,
    )

    assert failures == [
        ContentHealthFailure(
            check=CANDIDATE_MONEY_COVERAGE_CHECK,
            actual=1_799,
            floor=1_800,
        )
    ]


def test_evaluate_content_health_flags_candidate_money_recent_summary_below_floor() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    floors = {key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS}
    floors[CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK] = CANDIDATE_MONEY_RECENT_SUMMARY_DEFAULT_FLOOR
    counts = [100, 10, 5, 50, 20, 5, 25, 30, CANDIDATE_MONEY_RECENT_SUMMARY_DEFAULT_FLOOR - 1]

    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=CANDIDATE_MONEY_RECENT_SUMMARY_FRESH_FEC_ROW),
        floors=floors,
        now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert failures == [
        ContentHealthFailure(
            check=CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK,
            actual=1_439,
            floor=1_440,
        )
    ]


def test_candidate_money_recent_summary_fixture_excludes_null_and_future_dates() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    fake = FakeConnection(
        [100, 10, 5, 50, 20, 5, 25],
        freshness_result=CANDIDATE_MONEY_RECENT_SUMMARY_FRESH_FEC_ROW,
        candidate_money_rows=[
            {"summary_coverage_end_date": date(2026, 6, 30), "total_receipts": 1},
            {"summary_coverage_end_date": None, "total_receipts": 1},
            {"summary_coverage_end_date": date(2026, 7, 28), "total_receipts": 1},
            {"summary_coverage_end_date": date(2026, 3, 28), "total_receipts": 1},
            {"summary_coverage_end_date": date(2026, 6, 30)},
        ],
    )

    failures = evaluate_content_health(
        fake,
        floors={
            **{key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS},
            CANDIDATE_MONEY_COVERAGE_CHECK: 3,
            CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK: 2,
        },
        now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert failures == [
        ContentHealthFailure(
            check=CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK,
            actual=1,
            floor=2,
        )
    ]
    assert _single_query_params(fake, _candidate_money_recent_summary_query_indices(fake)) == (
        date(2025, 1, 1),
        date(2026, 12, 31),
        CANDIDATE_MONEY_RECENT_SUMMARY_CUTOFF,
        CANDIDATE_MONEY_RECENT_SUMMARY_EVALUATION_DATE,
    )


def test_evaluate_content_health_resolves_candidate_money_window_each_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.health_content as health_content

    calls: list[int | None] = []
    windows = [
        _SyntheticSelectedCycle(date(2025, 1, 1), date(2026, 12, 31)),
        _SyntheticSelectedCycle(date(2027, 1, 1), date(2028, 12, 31)),
    ]

    def fake_resolve_selected_cycle(cycle: int | None) -> _SyntheticSelectedCycle:
        calls.append(cycle)
        return windows[len(calls) - 1]

    monkeypatch.setattr(health_content, "resolve_selected_cycle", fake_resolve_selected_cycle)

    first = FakeConnection(_healthy_counts(), freshness_result=CANDIDATE_MONEY_RECENT_SUMMARY_FRESH_FEC_ROW)
    second = FakeConnection(
        _healthy_counts(),
        freshness_result=(datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),),
    )

    assert (
        health_content.evaluate_content_health(
            first,
            floors={key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS},
            now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        )
        == []
    )
    assert (
        health_content.evaluate_content_health(
            second,
            floors={key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS},
            now=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
        )
        == []
    )

    assert calls == [None, None]
    assert _candidate_money_query_params(first) == (date(2025, 1, 1), date(2026, 12, 31))
    assert _candidate_money_query_params(second) == (date(2027, 1, 1), date(2028, 12, 31))
    assert _single_query_params(first, _candidate_money_recent_summary_query_indices(first)) == (
        date(2025, 1, 1),
        date(2026, 12, 31),
        date(2026, 3, 29),
        date(2026, 7, 27),
    )
    assert _single_query_params(second, _candidate_money_recent_summary_query_indices(second)) == (
        date(2027, 1, 1),
        date(2028, 12, 31),
        date(2026, 3, 30),
        date(2026, 7, 28),
    )


def test_evaluate_content_health_reports_contribution_insights_floor_values() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    floors = {key: 0 for key in EXPECTED_FEDERAL_FIRST_CHECKS}
    floors["cf_transaction_contribution_insights_sentinel"] = 42
    counts = [100, 10, 5, 50, 20, 5, 41, 30, 30]

    failures = evaluate_content_health(
        FakeConnection(counts, freshness_result=fresh_federal_fec_bulk_pull_row()),
        floors=floors,
    )

    assert failures == [
        ContentHealthFailure(
            check="cf_transaction_contribution_insights_sentinel",
            actual=41,
            floor=42,
        )
    ]


@pytest.mark.parametrize(
    "freshness_result",
    [
        (FEC_FRESHNESS_CUTOFF,),
        (FEC_FRESHNESS_CUTOFF + timedelta(seconds=1),),
    ],
)
def test_evaluate_content_health_accepts_fec_bulk_freshness_at_boundary_or_newer(
    freshness_result: tuple[datetime],
) -> None:
    from api.health_content import evaluate_content_health

    failures = evaluate_content_health(
        _healthy_connection(freshness_result=freshness_result),
        floors=FEDERAL_FIRST_FLOORS,
        now=FIXED_NOW,
    )

    assert failures == []


def test_evaluate_content_health_rejects_stale_fec_bulk_freshness_with_source_epoch() -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    failures = evaluate_content_health(
        _healthy_connection(freshness_result=(FEC_FRESHNESS_CUTOFF - timedelta(seconds=1),)),
        floors=FEDERAL_FIRST_FLOORS,
        now=FIXED_NOW,
    )

    assert failures == [
        ContentHealthFailure(
            check=FEC_FRESHNESS_CHECK,
            actual=FEC_FRESHNESS_STALE_EPOCH,
            floor=FEC_FRESHNESS_CUTOFF_EPOCH,
        )
    ]


@pytest.mark.parametrize(
    ("case_name", "freshness_result"),
    [
        ("null", (None,)),
        ("non_success_canonical_row", (None,)),
        ("future", (FIXED_NOW + timedelta(seconds=1),)),
        ("malformed", ("2026-07-24T12:00:00Z",)),
        ("naive_datetime", (datetime(2026, 7, 24, 12, 0),)),
        ("aggregate_no_row", None),
    ],
)
def test_evaluate_content_health_rejects_indeterminate_fec_bulk_freshness(
    case_name: str,
    freshness_result: tuple[object, ...] | None,
) -> None:
    from api.health_content import ContentHealthFailure
    from api.health_content import evaluate_content_health

    failures = evaluate_content_health(
        _healthy_connection(freshness_result=freshness_result),
        floors=FEDERAL_FIRST_FLOORS,
        now=FIXED_NOW,
    )

    assert case_name
    assert failures == [
        ContentHealthFailure(
            check=FEC_FRESHNESS_CHECK,
            actual=0,
            floor=FEC_FRESHNESS_CUTOFF_EPOCH,
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
