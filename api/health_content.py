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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

import psycopg
from psycopg.sql import SQL

from api.contribution_insights_contract import (
    CONTRIBUTION_INSIGHTS_MIN_DATE,
    NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL,
    contribution_insights_transaction_where_sql,
)
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


# Federal-first production counts verified during the July 2026 Fly load.
# ``civic_officeholding_total`` is the unfiltered
# ``SELECT COUNT(*) FROM civic.officeholding`` total.
FEDERAL_FIRST_CONTENT_COUNTS: Mapping[str, int] = {
    "cf_transaction_total": 16_050_580,
    "core_person_total": 8_705,
    "civic_officeholding_total": 543,
    "cf_transaction_with_resolved_person": 0,
    "cf_committee_summary_total": 32_404,
    "cf_transaction_with_support_oppose": 10_409,
    "cf_transaction_contribution_insights_sentinel": 4_495,
}

# Current prod launch floors. These are 80% of the current Fly production
# counts where populated. Unresolved optional links stay pinned to zero until
# those refresh paths are populated.
FEDERAL_FIRST_CONTENT_FLOORS: Mapping[str, int] = {
    "cf_transaction_total": 12_840_464,
    "core_person_total": 6_964,
    "civic_officeholding_total": 434,
    "cf_transaction_with_resolved_person": 0,
    "cf_committee_summary_total": 25_923,
    "cf_transaction_with_support_oppose": 8_327,
    "cf_transaction_contribution_insights_sentinel": 3_596,
}

_DEFAULT_FLOORS: Mapping[str, int] = FEDERAL_FIRST_CONTENT_FLOORS

_FLOOR_ENV_VAR_PREFIX = "CIVIBUS_HEALTH_CONTENT_FLOOR_"

_FEC_BULK_FRESHNESS_CHECK = "campaign_finance_federal_fec_fresh"
_FEC_BULK_FRESHNESS_MAX_AGE = timedelta(days=7)
_FEC_BULK_FRESHNESS_INDETERMINATE_ACTUAL = 0
_FEC_BULK_FRESHNESS_SUCCESS_STATUS = "success"


# Per-check SQL. Order is preserved so the cursor's ``executed`` log lines
# up 1:1 with the failures returned — useful when reading test output.
_CHECK_QUERIES: Mapping[str, str] = {
    "cf_transaction_total": (
        "SELECT COALESCE((SELECT s.n_live_tup FROM pg_stat_user_tables s "
        "WHERE s.schemaname = 'cf' AND s.relname = 'transaction'), 0)"
    ),
    "core_person_total": "SELECT COUNT(*) FROM core.person",
    "civic_officeholding_total": "SELECT COUNT(*) FROM civic.officeholding",
    # Cross-domain link probe: at least N transactions resolved to a person
    # entity. Catches "schema bootstrapped fine but ER never ran / data
    # never landed in core.person" partial-failure modes.
    "cf_transaction_with_resolved_person": (
        "SELECT COUNT(*) FROM cf.transaction WHERE contributor_person_id IS NOT NULL"
    ),
    "cf_committee_summary_total": "SELECT COUNT(*) FROM cf.committee_summary",
    "cf_transaction_with_support_oppose": "SELECT COUNT(*) FROM cf.transaction WHERE support_oppose IS NOT NULL",
    "cf_transaction_contribution_insights_sentinel": (
        "SELECT COUNT(*) FROM cf.transaction t "
        f"WHERE lower(t.contributor_name_raw) LIKE '{_CONTRIBUTION_INSIGHTS_SENTINEL_DONOR_PREFIX}'"
        f"{_CONTRIBUTION_INSIGHTS_TRANSACTION_WHERE_SQL}"
        f"{NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}"
    ),
}

_FEC_BULK_FRESHNESS_QUERY = """
    SELECT MAX(last_pull_at)
    FROM core.data_source
    WHERE domain = %s
      AND jurisdiction = %s
      AND name = %s
      AND last_pull_status = %s
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


def _fec_bulk_freshness_failure(
    last_pull_at: object,
    *,
    now: datetime,
) -> ContentHealthFailure | None:
    cutoff_epoch = int((now - _FEC_BULK_FRESHNESS_MAX_AGE).timestamp())
    now_epoch = int(now.timestamp())
    source_epoch = _to_utc_epoch_seconds(last_pull_at)
    if source_epoch is None or source_epoch > now_epoch:
        return ContentHealthFailure(
            check=_FEC_BULK_FRESHNESS_CHECK,
            actual=_FEC_BULK_FRESHNESS_INDETERMINATE_ACTUAL,
            floor=cutoff_epoch,
        )
    if source_epoch < cutoff_epoch:
        return ContentHealthFailure(
            check=_FEC_BULK_FRESHNESS_CHECK,
            actual=source_epoch,
            floor=cutoff_epoch,
        )
    return None


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
    failures: list[ContentHealthFailure] = []
    with connection.cursor() as cursor:
        for check, query in _CHECK_QUERIES.items():
            # Wrap as psycopg SQL composable: queries are static literals
            # defined in this module (no user input), so SQL() is safe and
            # satisfies the typed cursor.execute() contract.
            cursor.execute(SQL(query))  # type: ignore[arg-type]
            row = cursor.fetchone()
            actual = int(row[0]) if row is not None else 0
            floor = resolved_floors.get(check, _DEFAULT_FLOORS[check])
            if actual < floor:
                failures.append(ContentHealthFailure(check=check, actual=actual, floor=floor))
        cursor.execute(SQL(_FEC_BULK_FRESHNESS_QUERY), _FEC_BULK_FRESHNESS_PARAMS)  # type: ignore[arg-type]
        row = cursor.fetchone()
        last_pull_at = row[0] if row is not None else None
        freshness_failure = _fec_bulk_freshness_failure(last_pull_at, now=resolved_now)
        if freshness_failure is not None:
            failures.append(freshness_failure)
    return failures
