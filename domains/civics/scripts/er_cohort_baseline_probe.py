
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import psycopg

from core.db import get_connection


# ---------------------------------------------------------------------------
# Cohort classification contract
# ---------------------------------------------------------------------------
# Each cohort is a tuple of:
#   * an `office_level` filter (must equal one of the values defined by
#     civic.office.office_level CHECK in domains/civics/schema/tables.sql:23-42)
#   * an optional state filter (two-letter code or None for "any state")
#   * an optional list of name regexes (matched case-insensitively against
#     `civic.office.name` OR `civic.office.title`); None means "match any
#     office at this level/state"
#   * a regression floor used when computing gate_target_pct
#
# Floors come from the Stage 1 intake contract: federal/state cohorts require
# 0.80 floor; sub-state cohorts (county, judicial, municipal, school_board,
# special_district) require 0.70 floor.
COHORT_RULES: dict[str, dict[str, Any]] = {
    "federal": {
        "office_level": "federal",
        "state": None,
        "name_patterns": None,
        "floor": 0.80,
    },
    "ncga_senate": {
        "office_level": "state",
        "state": "NC",
        "name_patterns": [r"senate"],
        "floor": 0.80,
    },
    "ncga_house": {
        "office_level": "state",
        "state": "NC",
        "name_patterns": [r"house"],
        "floor": 0.80,
    },
    "council_of_state": {
        "office_level": "state",
        "state": "NC",
        "name_patterns": [
            r"governor",
            r"lieutenant[_ ]governor",
            r"attorney[_ ]general",
            r"secretary[_ ]of[_ ]state",
            r"state[_ ]auditor",
            r"state[_ ]treasurer",
            r"superintendent",
            r"commissioner[_ ]of[_ ]agriculture",
            r"commissioner[_ ]of[_ ]insurance",
            r"commissioner[_ ]of[_ ]labor",
        ],
        "floor": 0.80,
    },
    "appellate": {
        "office_level": "judicial",
        "state": "NC",
        "name_patterns": [r"supreme", r"court[_ ]of[_ ]appeals", r"appellate"],
        "floor": 0.70,
    },
    "trial_judges": {
        "office_level": "judicial",
        "state": "NC",
        "name_patterns": [r"superior[_ ]court", r"district[_ ]court", r"trial"],
        "floor": 0.70,
    },
    "das": {
        "office_level": "judicial",
        "state": "NC",
        "name_patterns": [r"district[_ ]attorney"],
        "floor": 0.70,
    },
    "sheriffs": {
        "office_level": "county",
        "state": "NC",
        "name_patterns": [r"sheriff"],
        "floor": 0.70,
    },
    "register_of_deeds": {
        "office_level": "county",
        "state": "NC",
        "name_patterns": [r"register[_ ]of[_ ]deeds"],
        "floor": 0.70,
    },
    "commissioners": {
        "office_level": "county",
        "state": "NC",
        "name_patterns": [r"commissioner"],
        "floor": 0.70,
    },
    "soil_water": {
        "office_level": "special_district",
        "state": "NC",
        "name_patterns": [r"soil", r"water"],
        "floor": 0.70,
    },
    "municipal": {
        "office_level": "municipal",
        "state": "NC",
        "name_patterns": None,
        "floor": 0.70,
    },
    "school_board": {
        "office_level": "school_board",
        "state": "NC",
        "name_patterns": None,
        "floor": 0.70,
    },
}

# Office levels that at least one cohort targets. An office whose
# (office_level, state) tuple is targeted but whose name/title matches no
# cohort pattern is "drift" (silently misbucketed). The drift detector lives
# in `find_unclassified_office_drift`.
_TARGETED_LEVEL_STATE_PAIRS: set[tuple[str, str | None]] = {
    (rule["office_level"], rule["state"]) for rule in COHORT_RULES.values()
}


def _name_patterns_match(name: str, title: str | None, patterns: list[str] | None) -> bool:
    """Return True if any compiled pattern matches `name` or `title` case-insensitively."""
    if patterns is None:
        return True
    for pattern in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        if compiled.search(name) is not None:
            return True
        if title is not None and compiled.search(title) is not None:
            return True
    return False


def cohort_for_office(
    *,
    office_level: str,
    state: str | None,
    name: str,
    title: str | None,
) -> str | None:
    """Return the first cohort slug that classifies the given office, or None.

    Cohort iteration order matches `COHORT_RULES` insertion order. Callers that
    care about ambiguity (an office matching multiple rules) should use
    `all_cohorts_for_office`.
    """
    for cohort_slug, rule in COHORT_RULES.items():
        if rule["office_level"] != office_level:
            continue
        rule_state = rule["state"]
        if rule_state is not None and rule_state != state:
            continue
        if not _name_patterns_match(name, title, rule["name_patterns"]):
            continue
        return cohort_slug
    return None


def all_cohorts_for_office(
    *,
    office_level: str,
    state: str | None,
    name: str,
    title: str | None,
) -> list[str]:
    """Return every cohort slug whose rule matches the given office (order preserved)."""
    matches: list[str] = []
    for cohort_slug, rule in COHORT_RULES.items():
        if rule["office_level"] != office_level:
            continue
        rule_state = rule["state"]
        if rule_state is not None and rule_state != state:
            continue
        if not _name_patterns_match(name, title, rule["name_patterns"]):
            continue
        matches.append(cohort_slug)
    return matches


def is_targeted_level_state(office_level: str, state: str | None) -> bool:
    """Return True if any cohort targets this (office_level, state) combination.

    Targeting also covers cohorts whose `state` is None (any state) -- if
    `office_level=federal` is targeted with state=None, then any federal
    office is in a targeted bucket.
    """
    for level, target_state in _TARGETED_LEVEL_STATE_PAIRS:
        if level != office_level:
            continue
        if target_state is None or target_state == state:
            return True
    return False


def find_unclassified_office_drift(
    offices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the subset of offices whose (level, state) is targeted but match zero cohort name rules.

    `offices` is a list of dicts with keys office_level, state, name, title.
    The returned list is the silent-drift set: any non-empty result indicates
    cohort coverage gaps that the regression test must catch.
    """
    drift: list[dict[str, Any]] = []
    for office in offices:
        office_level = office["office_level"]
        state = office.get("state")
        if not is_targeted_level_state(office_level, state):
            continue
        if all_cohorts_for_office(
            office_level=office_level,
            state=state,
            name=office["name"],
            title=office.get("title"),
        ):
            continue
        drift.append(office)
    return drift


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------


def compute_pct_resolved(resolved_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return resolved_count / total_count


def compute_gate_target_pct(pct_resolved: float, floor: float) -> float:
    """Return max(pct_resolved + 0.30, floor) -- the Stage 2 gate target.

    Capped at 1.0 because percentages cannot exceed 100%.
    """
    target = max(pct_resolved + 0.30, floor)
    return min(target, 1.0)


# ---------------------------------------------------------------------------
# DB query
# ---------------------------------------------------------------------------


_PERSON_COUNT_SQL = """
WITH cohort_offices AS (
    SELECT id, name, title
    FROM civic.office
    WHERE office_level = %(office_level)s
      AND (
          %(state_filter_active)s = FALSE
          OR state = %(state)s
      )
),
matching_offices AS (
    SELECT id FROM cohort_offices
    WHERE %(skip_name_filter)s = TRUE
       OR name ~* %(name_regex)s
       OR (title IS NOT NULL AND title ~* %(name_regex)s)
),
cohort_persons AS (
    SELECT DISTINCT p.id, p.er_cluster_id
    FROM core.person p
    WHERE p.id IN (
        SELECT person_id FROM civic.officeholding
        WHERE office_id IN (SELECT id FROM matching_offices)
        UNION
        SELECT cd.person_id
        FROM civic.candidacy cd
        JOIN civic.contest c ON cd.contest_id = c.id
        WHERE c.office_id IN (SELECT id FROM matching_offices)
    )
)
SELECT
    COUNT(*) AS total_count,
    COUNT(*) FILTER (WHERE er_cluster_id IS NOT NULL) AS resolved_count
FROM cohort_persons
"""


def _build_combined_regex(patterns: list[str]) -> str:
    """Combine multiple alternation patterns into a single POSIX regex.

    Each pattern is wrapped in a non-capturing group and joined with `|`.
    Postgres ERE does not support inline `(?i)`, so case-insensitivity is
    requested via the `~*` operator at the call site.
    """
    return "|".join(f"(?:{pattern})" for pattern in patterns)


def query_cohort_counts(
    conn: psycopg.Connection,
    *,
    office_level: str,
    state: str | None,
    name_patterns: list[str] | None,
) -> tuple[int, int]:
    """Run the cohort count SQL. Returns `(total_count, resolved_count)`."""
    skip_name_filter = name_patterns is None
    name_regex = "" if skip_name_filter else _build_combined_regex(name_patterns)
    state_filter_active = state is not None

    params = {
        "office_level": office_level,
        "state": state,
        "state_filter_active": state_filter_active,
        "skip_name_filter": skip_name_filter,
        "name_regex": name_regex,
    }
    with conn.cursor() as cur:
        cur.execute(_PERSON_COUNT_SQL, params)
        row = cur.fetchone()
    if row is None:
        return 0, 0
    total_count = int(row[0])
    resolved_count = int(row[1])
    return total_count, resolved_count


def compute_cohort_baseline(
    conn: psycopg.Connection,
    cohort_slug: str,
) -> dict[str, Any]:
    rule = COHORT_RULES[cohort_slug]
    total_count, resolved_count = query_cohort_counts(
        conn,
        office_level=rule["office_level"],
        state=rule["state"],
        name_patterns=rule["name_patterns"],
    )
    pct_resolved = compute_pct_resolved(resolved_count, total_count)
    floor = float(rule["floor"])
    gate_target_pct = compute_gate_target_pct(pct_resolved, floor)
    return {
        "resolved_count": resolved_count,
        "total_count": total_count,
        "pct_resolved": pct_resolved,
        "gate_target_pct": gate_target_pct,
        "floor": floor,
    }


def compute_all_cohort_baselines(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    return {slug: compute_cohort_baseline(conn, slug) for slug in COHORT_RULES}


# ---------------------------------------------------------------------------
# Artifact emission (mirrors core/entity_resolution/proof.py:122-130)
# ---------------------------------------------------------------------------


def write_baseline_artifact(payload: dict[str, Any], *, artifact_path: Path | str) -> dict[str, Any]:
    resolved_path = Path(artifact_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        f"{json.dumps(payload, indent=2, sort_keys=False)}\n",
        encoding="utf-8",
    )
    return payload


def build_baseline_payload(cohort_baselines: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scope": "stage_02_dwo_er_baseline",
        "cohorts": cohort_baselines,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only ER cohort baseline probe (Stage 2, dwo_er tuning).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the JSON baseline artifact.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    conn = get_connection()
    try:
        cohort_baselines = compute_all_cohort_baselines(conn)
    finally:
        conn.close()
    payload = build_baseline_payload(cohort_baselines)
    write_baseline_artifact(payload, artifact_path=args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
