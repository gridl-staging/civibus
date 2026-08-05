"""Content-aware health probe for production monitoring.

Apr 30 incident background: an empty Postgres bootstrapped on the wrong
volume because ``docker compose up`` was invoked without the prod overlay.
``/health`` kept returning 200 (the API process was running) so external
uptime monitors saw a healthy site and never paged. This module exists so
an under-populated DB returns 503 — page-able by any standard uptime
monitor.

Design constraints:

* Stay simple. Most checks are static ``COUNT(*)`` probes over the narrowest
  table or serving-path contract that proves the launch surface is populated.
  The large ``cf.transaction`` total uses Postgres live-row statistics so the
  endpoint stays fast enough for external uptime probes. A bug in this
  watchdog must fail OPEN (alarms fire), not CLOSED (alarms suppressed).
  Clever ER probes are rejected for that reason — too easy to silently break.
* Floors are operator-tunable via env vars so the same image runs in dev
  (small DB) and prod (full DB) without code changes.
* Defaults are the current federal-first prod launch floors. Operators can
  tighten them through env vars as data volumes grow.
"""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, Protocol

import psycopg
from psycopg.sql import SQL

from api.contribution_insights_contract import (
    CONTRIBUTION_INSIGHTS_MIN_DATE,
    NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL,
    contribution_insights_transaction_where_sql,
)
from api.queries.campaign_finance import (
    _AUTHORIZED_CANDIDATE_COMMITTEE_FILTER,
    resolve_selected_cycle,
)
from core.people.federal_officeholders import current_federal_officeholder_predicate
from domains.campaign_finance.constants import (
    FEC_BULK_DATA_SOURCE_DOMAIN,
    FEC_BULK_DATA_SOURCE_JURISDICTION,
    FEC_BULK_DATA_SOURCE_NAME,
)


_CONTRIBUTION_INSIGHTS_SENTINEL_DONOR_PREFIX = "bofinger%"
_CONTRIBUTION_INSIGHTS_MIN_DATE_SQL = f"DATE '{CONTRIBUTION_INSIGHTS_MIN_DATE.isoformat()}'"
_CONTRIBUTION_INSIGHTS_TRANSACTION_WHERE_SQL = contribution_insights_transaction_where_sql(
    min_date_sql=_CONTRIBUTION_INSIGHTS_MIN_DATE_SQL
)

CONTENT_FLOOR_HEADROOM_RATIO = 0.8
CANDIDATE_MONEY_SERVING_COVERAGE_MEASUREMENT_CYCLE = 2026


def content_floor_with_headroom(count: int) -> int:
    return int(CONTENT_FLOOR_HEADROOM_RATIO * count)


# Federal-first production counts verified during the July 2026 Fly load.
# ``civic_officeholding_total`` is the unfiltered
# ``SELECT COUNT(*) FROM civic.officeholding`` total, measured as 544 on
# 2026-07-31. It includes closed vacancy-predecessor officeholding rows and is
# not the vacancy-sensitive current seated-official count.
FEDERAL_FIRST_CONTENT_COUNTS: Mapping[str, int] = {
    "cf_transaction_total": 16_050_580,
    "core_person_total": 8_705,
    "civic_officeholding_total": 544,
    "cf_transaction_with_resolved_person": 0,
    "cf_committee_summary_total": 32_404,
    "cf_transaction_with_support_oppose": 10_409,
    "cf_transaction_contribution_insights_sentinel": 4_495,
    # Serving coverage counts the official totals the public federal route
    # actually promotes: in-window totals PLUS prior-cycle totals promoted
    # out-of-cycle when no selected-cycle committee activity suppresses them
    # (mirrors _build_out_of_cycle_official_total). Production read-only
    # measurement 2026-08-03: docs/live-state/2026_08_04_content_floor_headroom_repair.md.
    "cf_candidate_money_serving_coverage": 7_021,
    "cf_candidate_money_recent_summary_coverage": 1_799,
    # Measured 527/540 current federal officeholder people on 2026-07-31.
    "cf_federal_officeholder_money_coverage": 527,
    "cf_donor_search_rollup_total": 0,
}

# Current prod launch floors. Populated defaults must stay below the standard
# headroom floor owned by ``CONTENT_FLOOR_HEADROOM_RATIO``. Unresolved optional
# links stay pinned to zero until those refresh paths are populated.
FEDERAL_FIRST_CONTENT_FLOORS: Mapping[str, int] = {
    "cf_transaction_total": 12_840_464,
    "core_person_total": 6_964,
    "civic_officeholding_total": 434,
    "cf_transaction_with_resolved_person": 0,
    "cf_committee_summary_total": 25_923,
    "cf_transaction_with_support_oppose": 8_327,
    "cf_transaction_contribution_insights_sentinel": 3_596,
    # 2026-cycle production read-only measurement; see
    # docs/live-state/2026_08_04_content_floor_headroom_repair.md.
    "cf_candidate_money_serving_coverage": 5_616,
    "cf_candidate_money_recent_summary_coverage": 1_439,
    # The 500 P0 recovery threshold ships through repair-first deploy ordering;
    # it must not be weakened to accommodate the broken production value of 13.
    "cf_federal_officeholder_money_coverage": 500,
    "cf_donor_search_rollup_total": 0,
}

_DEFAULT_FLOORS: Mapping[str, int] = FEDERAL_FIRST_CONTENT_FLOORS

_FLOOR_ENV_VAR_PREFIX = "CIVIBUS_HEALTH_CONTENT_FLOOR_"

_FEC_BULK_FRESHNESS_CHECK = "campaign_finance_federal_fec_fresh"
# Serving coverage counts every promoted official total (in-window plus
# out-of-cycle promotions). The narrower 120-day freshness subset measured
# 1,799 during the 2026-07-28 deploy; its 1,439 floor preserves the
# standard content floor headroom.
_CANDIDATE_MONEY_COVERAGE_CHECK = "cf_candidate_money_serving_coverage"
_CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK = "cf_candidate_money_recent_summary_coverage"
_FEDERAL_OFFICEHOLDER_MONEY_COVERAGE_CHECK = "cf_federal_officeholder_money_coverage"
_CANDIDATE_MONEY_RECENT_SUMMARY_MAX_AGE = timedelta(days=120)
_FEC_BULK_FRESHNESS_MAX_AGE = timedelta(days=7)
_FEC_BULK_FRESHNESS_INDETERMINATE_ACTUAL = 0
_FEC_BULK_FRESHNESS_SUCCESS_STATUS = "success"

_DONOR_ROLLUP_FRESHNESS_CHECK = "cf_donor_search_rollup_fresh"
# Donor search fails CLOSED once the rollup provenance row is older than
# _DONOR_SEARCH_ROLLUP_MAX_AGE (api/queries/campaign_finance.py) — the page
# renders its 503 arm with no code change, no deploy, and no data change, purely
# on elapsed time. /api/health/content counts rows, so it cannot observe that
# transition; before this check, the first signal was users hitting the 503.
#
# This bound is deliberately TIGHTER than the serving bound so the guard predicts
# the outage instead of announcing it. Sizing, both directions:
#   - the rebuild cadence is weekly, so a healthy rollup reaches ~7d0h before the
#     next refresh replaces it; a bound at or under 7d would flap every cycle.
#   - the serving bound is 8d, so 7d6h leaves ~18h of warning — enough for a
#     scheduled run to be observed missing and a manual rebuild (~142s) to run.
# test_donor_rollup_health_bound_fires_strictly_before_the_serving_bound pins the
# ordering and a 12h minimum margin so neither constant can drift into vacuity.
_DONOR_ROLLUP_FRESHNESS_MAX_AGE = timedelta(days=7, hours=6)
_CF_TRANSACTION_TOTAL_CHECK = "cf_transaction_total"
_CF_TRANSACTION_TOTAL_CONFIRM_QUERY = "SELECT count(*) FROM cf.transaction"
_CF_TRANSACTION_TOTAL_CONFIRM_TIMEOUT_MS = 5_000
_CF_TRANSACTION_TOTAL_CONFIRM_SAVEPOINT = "content_health_transaction_total_confirm"
_CF_TRANSACTION_TOTAL_CONFIRM_TIMEOUT_SQL = f"SET LOCAL statement_timeout = {_CF_TRANSACTION_TOTAL_CONFIRM_TIMEOUT_MS}"
_RESET_LOCAL_STATEMENT_TIMEOUT_SQL = "SET LOCAL statement_timeout = DEFAULT"


class _SelectedCycleWindow(Protocol):
    selected_cycle: int
    coverage_start_date: date
    coverage_end_date: date


_QueryParams = tuple[object, ...] | None
_CheckParamsResolver = Callable[[_SelectedCycleWindow, datetime], _QueryParams]


@dataclass(frozen=True)
class _ContentCheckSpec:
    query: str
    params_resolver: _CheckParamsResolver | None = None

    def params(self, *, selected_cycle: _SelectedCycleWindow, now: datetime) -> _QueryParams:
        if self.params_resolver is None:
            return None
        return self.params_resolver(selected_cycle, now)


def _candidate_money_serving_coverage_params(
    selected_cycle: _SelectedCycleWindow,
    now: datetime,
) -> tuple[object, object, object]:
    del now
    # The cycle integer scopes the out-of-cycle suppression subquery to the
    # selected cycle's cf.committee_summary rows. Read it from the cycle owner's
    # own field rather than re-deriving it from the window end date, so the
    # "window end year IS the cycle" invariant stays owned by
    # resolve_selected_cycle().
    return (
        selected_cycle.coverage_start_date,
        selected_cycle.coverage_end_date,
        selected_cycle.selected_cycle,
    )


def _candidate_money_recent_summary_coverage_params(
    selected_cycle: _SelectedCycleWindow,
    now: datetime,
) -> tuple[object, object, object, object]:
    evaluation_date = now.date()
    cutoff_date = evaluation_date - _CANDIDATE_MONEY_RECENT_SUMMARY_MAX_AGE
    return (
        selected_cycle.coverage_start_date,
        selected_cycle.coverage_end_date,
        cutoff_date,
        evaluation_date,
    )


def _federal_officeholder_money_coverage_params(
    selected_cycle: _SelectedCycleWindow,
    now: datetime,
) -> tuple[date]:
    del selected_cycle
    return (now.date(),)


_CANDIDATE_MONEY_OFFICIAL_TOTALS_PREDICATE = """
    (
        total_receipts IS NOT NULL
        OR total_disbursements IS NOT NULL
        OR cash_on_hand IS NOT NULL
    )
"""

# Suppression signal for the out-of-cycle promotion branch. Mirrors
# fetch_candidate_summary's arbitration: a prior-cycle official total is only
# promoted when the candidate has NO selected-cycle fundraising activity. That
# activity can come from selected-cycle committee-summary dollars or from the
# ``transaction_count`` produced by fetch_committee_fundraising_summary. A
# populated derived_transaction_count is authoritative even when it is zero;
# qualifying raw transactions are counted only when no stored aggregate exists.
# The authorized-committee filter is imported from the query owner so both
# paths share one denylist definition. ``candidate`` and
# ``selected_cycle_window`` are correlated from the outer serving query below.
_CANDIDATE_MONEY_SELECTED_CYCLE_ACTIVITY_EXISTS = (
    """EXISTS (
            SELECT 1
            FROM cf.candidate_committee_link link
            JOIN cf.committee cm ON cm.id = link.committee_id
            JOIN LATERAL (
                SELECT
                    COALESCE(SUM(cs.total_receipts), 0) AS total_receipts,
                    COALESCE(SUM(cs.total_disbursements), 0) AS total_disbursements,
                    COALESCE(SUM(cs.derived_transaction_count), 0)::integer AS transaction_count,
                    BOOL_OR(cs.derived_transaction_count IS NOT NULL) AS has_precomputed_aggregate
                FROM cf.committee_summary cs
                WHERE cs.committee_id = cm.id
                  AND cs.cycle = selected_cycle_window.selected_cycle
            ) selected_cycle_summary ON TRUE
            WHERE link.candidate_id = candidate.id
              AND link.valid_period && daterange(
                  selected_cycle_window.window_start,
                  selected_cycle_window.window_end,
                  '[]'
              )
              AND """
    + _AUTHORIZED_CANDIDATE_COMMITTEE_FILTER
    + """
              AND (
                  selected_cycle_summary.total_receipts <> 0
                  OR selected_cycle_summary.total_disbursements <> 0
                  OR CASE
                      WHEN COALESCE(selected_cycle_summary.has_precomputed_aggregate, FALSE)
                      THEN selected_cycle_summary.transaction_count > 0
                      ELSE EXISTS (
                          SELECT 1
                          FROM cf.transaction t
                          WHERE t.committee_id = cm.id
                            AND t.transaction_date >= selected_cycle_window.window_start
                            AND t.transaction_date <= selected_cycle_window.window_end
                            AND t.is_memo = FALSE
                            AND t.amendment_indicator != 'T'
"""
    + NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL
    + """
                      )
                  END
              )
        )"""
)

# Content-health serving coverage counts the official totals the public federal
# route actually promotes, matching the campaign-finance arbitration:
#   (a) populated official totals whose coverage-end falls inside the selected
#       cycle window (the primary serving path), plus
#   (b) older populated official totals promoted out-of-cycle because no
#       selected-cycle committee activity suppresses them.
# Future-dated totals (coverage-end after the window) are excluded from both
# branches: (a) fails the BETWEEN upper bound and (b) requires coverage-end
# strictly before the window start.
_CANDIDATE_MONEY_SERVING_COVERAGE_QUERY = (
    """
    WITH selected_cycle_window AS (
        SELECT
            %s::date AS window_start,
            %s::date AS window_end,
            %s::int AS selected_cycle
    )
    SELECT COUNT(*)
    FROM cf.candidate AS candidate, selected_cycle_window
    WHERE """
    + _CANDIDATE_MONEY_OFFICIAL_TOTALS_PREDICATE
    + """
      AND candidate.summary_coverage_end_date IS NOT NULL
      AND (
          candidate.summary_coverage_end_date
              BETWEEN selected_cycle_window.window_start AND selected_cycle_window.window_end
          OR (
              candidate.summary_coverage_end_date < selected_cycle_window.window_start
              AND NOT """
    + _CANDIDATE_MONEY_SELECTED_CYCLE_ACTIVITY_EXISTS
    + """
          )
      )
"""
)

_CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_QUERY = (
    """
    SELECT COUNT(*)
    FROM cf.candidate
    WHERE """
    + _CANDIDATE_MONEY_OFFICIAL_TOTALS_PREDICATE
    + """
      AND summary_coverage_end_date BETWEEN %s AND %s
      AND summary_coverage_end_date >= %s
      AND summary_coverage_end_date <= %s
    """
)

_FEDERAL_OFFICEHOLDER_MONEY_COVERAGE_QUERY = (
    """
    SELECT COUNT(DISTINCT person.id)
    FROM core.person person
    JOIN civic.officeholding officeholding
      ON officeholding.person_id = person.id
    JOIN civic.office office
      ON office.id = officeholding.office_id
    WHERE """
    + current_federal_officeholder_predicate(
        officeholding_alias="officeholding",
        office_alias="office",
        as_of_sql="%s::date",
    )
    + """
      AND EXISTS (
          SELECT 1
          FROM cf.candidate candidate
          WHERE candidate.person_id = person.id
            AND """
    + _CANDIDATE_MONEY_OFFICIAL_TOTALS_PREDICATE
    + """
      )
"""
)


# Per-check specs. Order is preserved so the cursor's ``executed`` log lines
# up 1:1 with the failures returned. The shape supports dynamic parameters for
# selected-cycle checks while static checks keep params as ``None``.
_CHECK_QUERIES: Mapping[str, _ContentCheckSpec] = {
    _CF_TRANSACTION_TOTAL_CHECK: _ContentCheckSpec(
        "SELECT COALESCE((SELECT s.n_live_tup FROM pg_stat_user_tables s "
        "WHERE s.schemaname = 'cf' AND s.relname = 'transaction'), 0)"
    ),
    "core_person_total": _ContentCheckSpec("SELECT COUNT(*) FROM core.person"),
    "civic_officeholding_total": _ContentCheckSpec("SELECT COUNT(*) FROM civic.officeholding"),
    # Cross-domain link probe: at least N transactions resolved to a person
    # entity. Catches "schema bootstrapped fine but ER never ran / data
    # never landed in core.person" partial-failure modes.
    "cf_transaction_with_resolved_person": _ContentCheckSpec(
        "SELECT COUNT(*) FROM cf.transaction WHERE contributor_person_id IS NOT NULL"
    ),
    "cf_committee_summary_total": _ContentCheckSpec("SELECT COUNT(*) FROM cf.committee_summary"),
    "cf_transaction_with_support_oppose": _ContentCheckSpec(
        "SELECT COUNT(*) FROM cf.transaction WHERE support_oppose IS NOT NULL"
    ),
    "cf_transaction_contribution_insights_sentinel": _ContentCheckSpec(
        "SELECT COUNT(*) FROM cf.transaction t "
        f"WHERE lower(t.contributor_name_raw) LIKE '{_CONTRIBUTION_INSIGHTS_SENTINEL_DONOR_PREFIX}'"
        f"{_CONTRIBUTION_INSIGHTS_TRANSACTION_WHERE_SQL}"
        f"{NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}"
    ),
    _CANDIDATE_MONEY_COVERAGE_CHECK: _ContentCheckSpec(
        _CANDIDATE_MONEY_SERVING_COVERAGE_QUERY,
        params_resolver=_candidate_money_serving_coverage_params,
    ),
    _CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_CHECK: _ContentCheckSpec(
        _CANDIDATE_MONEY_RECENT_SUMMARY_COVERAGE_QUERY,
        params_resolver=_candidate_money_recent_summary_coverage_params,
    ),
    _FEDERAL_OFFICEHOLDER_MONEY_COVERAGE_CHECK: _ContentCheckSpec(
        _FEDERAL_OFFICEHOLDER_MONEY_COVERAGE_QUERY,
        params_resolver=_federal_officeholder_money_coverage_params,
    ),
    "cf_donor_search_rollup_total": _ContentCheckSpec("SELECT COUNT(*) FROM cf.donor_search_rollup"),
}

_FEC_BULK_FRESHNESS_QUERY = """
    SELECT MAX(last_pull_at)
    FROM core.data_source
    WHERE domain = %s
      AND jurisdiction = %s
      AND name = %s
      AND last_pull_status = %s
"""

# The serving guard reads this exact singleton row; health must read the same one
# or the two can disagree about whether donor search is about to fail.
_DONOR_ROLLUP_FRESHNESS_QUERY = """
    SELECT completed_at
    FROM cf.donor_search_rollup_provenance
    WHERE singleton IS TRUE
"""

_FEC_BULK_FRESHNESS_PARAMS = (
    FEC_BULK_DATA_SOURCE_DOMAIN,
    FEC_BULK_DATA_SOURCE_JURISDICTION,
    FEC_BULK_DATA_SOURCE_NAME,
    _FEC_BULK_FRESHNESS_SUCCESS_STATUS,
)


@dataclass(frozen=True)
class ContentHealthFailure:
    """A single failed content-health check, ready for JSON serialisation."""

    check: str
    actual: int
    floor: int


class _HealthCursor(Protocol):
    def execute(self, query: object, params: object = None) -> object: ...

    def fetchone(self) -> tuple[object, ...] | None: ...


def _fetch_single_int(cursor: _HealthCursor) -> int:
    row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def candidate_money_serving_coverage_count(
    connection: psycopg.Connection,
    *,
    cycle: int | None = None,
) -> int:
    """Count candidates whose official totals are served for the selected cycle.

    This aggregate mirrors the full serving arbitration:
    ``_has_official_candidate_totals()`` plus
    ``_official_candidate_totals_cover_selected_cycle()`` for the in-window
    branch, and ``_build_out_of_cycle_official_total()`` gated by
    ``_has_selected_cycle_fundraising_activity()`` for the prior-cycle totals the
    public route promotes. The health owner needs aggregate SQL, while
    ``resolve_selected_cycle()`` remains the cycle-window owner.
    """
    spec = _CHECK_QUERIES[_CANDIDATE_MONEY_COVERAGE_CHECK]
    selected_cycle = resolve_selected_cycle(cycle)
    with connection.cursor() as cursor:
        cursor.execute(
            SQL(spec.query),
            spec.params(selected_cycle=selected_cycle, now=_resolve_health_now(None)),  # type: ignore[arg-type]
        )
        return _fetch_single_int(cursor)


def _confirm_transaction_total(cursor: _HealthCursor) -> int:
    cursor.execute(SQL(f"SAVEPOINT {_CF_TRANSACTION_TOTAL_CONFIRM_SAVEPOINT}"))
    try:
        cursor.execute(SQL(_CF_TRANSACTION_TOTAL_CONFIRM_TIMEOUT_SQL))
        cursor.execute(SQL(_CF_TRANSACTION_TOTAL_CONFIRM_QUERY))
        actual = _fetch_single_int(cursor)
    except Exception:
        with suppress(Exception):
            cursor.execute(SQL(f"ROLLBACK TO SAVEPOINT {_CF_TRANSACTION_TOTAL_CONFIRM_SAVEPOINT}"))
            cursor.execute(SQL(f"RELEASE SAVEPOINT {_CF_TRANSACTION_TOTAL_CONFIRM_SAVEPOINT}"))
        raise
    cursor.execute(SQL(_RESET_LOCAL_STATEMENT_TIMEOUT_SQL))
    cursor.execute(SQL(f"RELEASE SAVEPOINT {_CF_TRANSACTION_TOTAL_CONFIRM_SAVEPOINT}"))
    return actual


def _to_utc_epoch_seconds(value: object) -> int | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return int(value.astimezone(timezone.utc).timestamp())


def _resolve_health_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("content-health now must be an aware UTC datetime")
    return now.astimezone(timezone.utc)


def _stale_timestamp_failure(
    value: object,
    *,
    now: datetime,
    check: str,
    max_age: timedelta,
) -> ContentHealthFailure | None:
    """Single owner for every timestamp-based content-health check.

    Fails CLOSED on indeterminate input: an absent, tz-naive, or future
    timestamp reports the indeterminate sentinel rather than passing. "No
    freshness evidence" must never mean "fresh" — a guard that reads a missing
    timestamp as healthy cannot fail for the defect it exists to catch.

    Both bounds are reported as epoch seconds so ``actual`` / ``floor`` stay
    integers and serialise identically to the count-based checks.
    """
    cutoff_epoch = int((now - max_age).timestamp())
    now_epoch = int(now.timestamp())
    source_epoch = _to_utc_epoch_seconds(value)
    if source_epoch is None or source_epoch > now_epoch:
        return ContentHealthFailure(
            check=check,
            actual=_FEC_BULK_FRESHNESS_INDETERMINATE_ACTUAL,
            floor=cutoff_epoch,
        )
    if source_epoch < cutoff_epoch:
        return ContentHealthFailure(check=check, actual=source_epoch, floor=cutoff_epoch)
    return None


def _fec_bulk_freshness_failure(
    last_pull_at: object,
    *,
    now: datetime,
) -> ContentHealthFailure | None:
    return _stale_timestamp_failure(
        last_pull_at,
        now=now,
        check=_FEC_BULK_FRESHNESS_CHECK,
        max_age=_FEC_BULK_FRESHNESS_MAX_AGE,
    )


def _donor_rollup_freshness_failure(
    completed_at: object,
    *,
    now: datetime,
) -> ContentHealthFailure | None:
    return _stale_timestamp_failure(
        completed_at,
        now=now,
        check=_DONOR_ROLLUP_FRESHNESS_CHECK,
        max_age=_DONOR_ROLLUP_FRESHNESS_MAX_AGE,
    )


def floors_from_env(env: Mapping[str, str] | None = None) -> dict[str, int]:
    """Resolve content-floor thresholds from environment with safe defaults.

    Override format: ``CIVIBUS_HEALTH_CONTENT_FLOOR_<UPPERCASE_KEY>=N``.

    Misconfiguration (non-integer or negative values) raises ``ValueError``
    so it fails fast at startup rather than silently relaxing the gate.
    """
    source = os.environ if env is None else env
    floors: dict[str, int] = {}
    for key, default in _DEFAULT_FLOORS.items():
        env_var = _FLOOR_ENV_VAR_PREFIX + key.upper()
        raw = source.get(env_var)
        if raw is None or raw == "":
            floors[key] = default
            continue
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{env_var} must be an integer, got {raw!r}") from exc
        if value < 0:
            raise ValueError(f"{env_var} must be non-negative, got {value}")
        floors[key] = value
    return floors


def evaluate_content_health(
    connection: psycopg.Connection,
    *,
    floors: Mapping[str, int] | None = None,
    now: datetime | None = None,
) -> list[ContentHealthFailure]:
    """Run all content-health checks against ``connection``.

    Returns the list of failures; an empty list means the DB is healthy.
    Caller decides the HTTP / exit-code mapping.
    """
    resolved_floors = dict(floors) if floors is not None else floors_from_env()
    resolved_now = _resolve_health_now(now)
    selected_cycle = resolve_selected_cycle(None)
    failures: list[ContentHealthFailure] = []
    with connection.cursor() as cursor:
        for check, spec in _CHECK_QUERIES.items():
            # Wrap as psycopg SQL composable: queries are static literals
            # defined in this module (no user input), so SQL() is safe and
            # satisfies the typed cursor.execute() contract.
            cursor.execute(
                SQL(spec.query),
                spec.params(selected_cycle=selected_cycle, now=resolved_now),  # type: ignore[arg-type]
            )
            actual = _fetch_single_int(cursor)
            floor = resolved_floors.get(check, _DEFAULT_FLOORS[check])
            if check == _CF_TRANSACTION_TOTAL_CHECK and actual <= floor:
                try:
                    # The exact count is expensive on the hot path, so it only
                    # confirms suspicious stale-low estimates. If confirmation
                    # cannot complete, fail closed with the existing integer
                    # sentinel instead of reporting the database as healthy.
                    actual = _confirm_transaction_total(cursor)
                except Exception:
                    failures.append(ContentHealthFailure(check=check, actual=0, floor=floor))
                    continue
            if actual < floor:
                failures.append(ContentHealthFailure(check=check, actual=actual, floor=floor))
        cursor.execute(SQL(_FEC_BULK_FRESHNESS_QUERY), _FEC_BULK_FRESHNESS_PARAMS)  # type: ignore[arg-type]
        row = cursor.fetchone()
        last_pull_at = row[0] if row is not None else None
        freshness_failure = _fec_bulk_freshness_failure(last_pull_at, now=resolved_now)
        if freshness_failure is not None:
            failures.append(freshness_failure)
        # Donor-search rollup provenance: a timestamp predicate, not a count, so
        # no _CHECK_QUERIES floor can express it. Runs last and reads the same
        # singleton row the serving guard reads.
        cursor.execute(SQL(_DONOR_ROLLUP_FRESHNESS_QUERY))
        provenance_row = cursor.fetchone()
        rollup_completed_at = provenance_row[0] if provenance_row is not None else None
        rollup_failure = _donor_rollup_freshness_failure(rollup_completed_at, now=resolved_now)
        if rollup_failure is not None:
            failures.append(rollup_failure)
    return failures
