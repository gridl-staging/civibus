"""Content-aware health probe for production monitoring.

Apr 30 incident background: an empty Postgres bootstrapped on the wrong
volume because ``docker compose up`` was invoked without the prod overlay.
``/health`` kept returning 200 (the API process was running) so external
uptime monitors saw a healthy site and never paged. This module exists so
an under-populated DB returns 503 — page-able by any standard uptime
monitor.

Design constraints:

* Stay simple. Each check is a single ``COUNT(*)`` against a single table.
  A bug in this watchdog must fail OPEN (alarms fire), not CLOSED (alarms
  suppressed). Joins, subqueries, and clever ER probes were rejected for
  that reason — too easy to silently break.
* Floors are operator-tunable via env vars so the same image runs in dev
  (small DB) and prod (full DB) without code changes.
* Defaults are intended for prod. Tests override via ``floors=`` kwarg or
  the env-var prefix ``CIVIBUS_HEALTH_CONTENT_FLOOR_``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import psycopg
from psycopg.sql import SQL


# Default floors aimed at the live prod data set as it stood pre-incident
# (cf.transaction ~10M rows, core.person O(50K), civic.officeholding O(8K)).
# These are intentionally conservative so a future partial-load doesn't
# silently flip the gate green; tighten them upward as data grows, never
# downward to "make the alert green again."
_DEFAULT_FLOORS: Mapping[str, int] = {
    "cf_transaction_total": 1_000_000,
    "core_person_total": 1_000,
    "civic_officeholding_total": 100,
    "cf_transaction_with_resolved_person": 1_000,
}

_FLOOR_ENV_VAR_PREFIX = "CIVIBUS_HEALTH_CONTENT_FLOOR_"


# Per-check SQL. Order is preserved so the cursor's ``executed`` log lines
# up 1:1 with the failures returned — useful when reading test output.
_CHECK_QUERIES: Mapping[str, str] = {
    "cf_transaction_total": "SELECT COUNT(*) FROM cf.transaction",
    "core_person_total": "SELECT COUNT(*) FROM core.person",
    "civic_officeholding_total": "SELECT COUNT(*) FROM civic.officeholding",
    # Cross-domain link probe: at least N transactions resolved to a person
    # entity. Catches "schema bootstrapped fine but ER never ran / data
    # never landed in core.person" partial-failure modes.
    "cf_transaction_with_resolved_person": (
        "SELECT COUNT(*) FROM cf.transaction WHERE contributor_person_id IS NOT NULL"
    ),
}


@dataclass(frozen=True)
class ContentHealthFailure:
    """A single failed content-health check, ready for JSON serialisation."""

    check: str
    actual: int
    floor: int


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
) -> list[ContentHealthFailure]:
    """Run all content-health checks against ``connection``.

    Returns the list of failures; an empty list means the DB is healthy.
    Caller decides the HTTP / exit-code mapping.
    """
    resolved_floors = dict(floors) if floors is not None else floors_from_env()
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
    return failures
