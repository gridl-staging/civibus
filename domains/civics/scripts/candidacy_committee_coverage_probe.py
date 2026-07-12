from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg

from core.db import get_connection

_NORMALIZED_NONEMPTY_TEXT_PREDICATE = "NULLIF(trim(regexp_replace({value}, '\\s+', ' ', 'g')), '') IS NOT NULL"
_DEFAULT_UNRESOLVED_NAME_SAMPLE_LIMIT = 10

_PREREQUISITE_COLUMNS_SQL = """
SELECT
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'candidacy'
          AND column_name = 'name_on_ballot'
    ) AS has_name_on_ballot,
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'candidacy'
          AND column_name = 'committee_id'
    ) AS has_committee_id
"""

_COVERAGE_COUNTS_SQL = f"""
WITH nc_candidacies AS (
    SELECT
        ca.id,
        ca.committee_id,
        ofc.office_level,
        trim(regexp_replace(ca.name_on_ballot, '\\s+', ' ', 'g')) AS norm_name_on_ballot
    FROM civic.candidacy ca
    JOIN civic.contest ct ON ct.id = ca.contest_id
    JOIN civic.office ofc ON ofc.id = ct.office_id
    WHERE ofc.state = 'NC'
),
registry_matches AS (
    SELECT
        trim(regexp_replace(r.candidate_name, '\\s+', ' ', 'g')) AS norm_candidate_name,
        c.id AS committee_id
    FROM cf.nc_committee_registry r
    JOIN core.organization o
      ON o.identifiers ->> 'nc_sboe_id' = trim(regexp_replace(r.sboe_id, '\\s+', ' ', 'g'))
    JOIN cf.committee c
      ON c.organization_id = o.id
     AND c.state = 'NC'
    WHERE {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.candidate_name")}
      AND {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.sboe_id")}
),
registry_target_counts AS (
    SELECT
        norm_candidate_name,
        COUNT(DISTINCT committee_id)::int AS target_count
    FROM registry_matches
    GROUP BY norm_candidate_name
),
candidate_match_counts AS (
    SELECT
        nc.id,
        COALESCE(rt.target_count, 0)::int AS target_count
    FROM nc_candidacies nc
    LEFT JOIN registry_target_counts rt
      ON rt.norm_candidate_name = nc.norm_name_on_ballot
)
SELECT
    COUNT(*)::int AS total_nc_candidacies,
    COUNT(*) FILTER (WHERE nc.committee_id IS NOT NULL)::int AS linked_to_committee,
    COUNT(*) FILTER (WHERE nc.committee_id IS NULL AND cm.target_count > 1)::int AS ambiguous_unlinked,
    COUNT(*) FILTER (WHERE nc.committee_id IS NULL AND cm.target_count = 0)::int AS no_match_unlinked
FROM nc_candidacies nc
JOIN candidate_match_counts cm ON cm.id = nc.id
"""

_OFFICE_LEVEL_BREAKDOWN_SQL = """
WITH nc_candidacies AS (
    SELECT
        ca.committee_id,
        ofc.office_level
    FROM civic.candidacy ca
    JOIN civic.contest ct ON ct.id = ca.contest_id
    JOIN civic.office ofc ON ofc.id = ct.office_id
    WHERE ofc.state = 'NC'
)
SELECT
    office_level,
    COUNT(*)::int AS total_count,
    COUNT(*) FILTER (WHERE committee_id IS NOT NULL)::int AS linked_count
FROM nc_candidacies
GROUP BY office_level
ORDER BY office_level
"""

_UNRESOLVED_NAME_SAMPLE_SQL = f"""
WITH nc_candidacies AS (
    SELECT
        ca.committee_id,
        trim(regexp_replace(ca.name_on_ballot, '\\s+', ' ', 'g')) AS norm_name_on_ballot
    FROM civic.candidacy ca
    JOIN civic.contest ct ON ct.id = ca.contest_id
    JOIN civic.office ofc ON ofc.id = ct.office_id
    WHERE ofc.state = 'NC'
),
registry_matches AS (
    SELECT
        trim(regexp_replace(r.candidate_name, '\\s+', ' ', 'g')) AS norm_candidate_name,
        c.id AS committee_id
    FROM cf.nc_committee_registry r
    JOIN core.organization o
      ON o.identifiers ->> 'nc_sboe_id' = trim(regexp_replace(r.sboe_id, '\\s+', ' ', 'g'))
    JOIN cf.committee c
      ON c.organization_id = o.id
     AND c.state = 'NC'
    WHERE {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.candidate_name")}
      AND {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.sboe_id")}
),
registry_target_counts AS (
    SELECT
        norm_candidate_name,
        COUNT(DISTINCT committee_id)::int AS target_count
    FROM registry_matches
    GROUP BY norm_candidate_name
)
SELECT DISTINCT nc.norm_name_on_ballot
FROM nc_candidacies nc
LEFT JOIN registry_target_counts rt
  ON rt.norm_candidate_name = nc.norm_name_on_ballot
WHERE nc.committee_id IS NULL
  AND {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="nc.norm_name_on_ballot")}
ORDER BY nc.norm_name_on_ballot
LIMIT %(sample_limit)s
"""


def _compute_pct_linked(linked_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return linked_count / total_count


def _query_prerequisite_metadata(conn: psycopg.Connection) -> dict[str, Any]:
    row = conn.execute(_PREREQUISITE_COLUMNS_SQL).fetchone()
    assert row is not None
    has_name_on_ballot = bool(row[0])
    has_committee_id = bool(row[1])
    present_columns: list[str] = []
    if has_name_on_ballot:
        present_columns.append("name_on_ballot")
    if has_committee_id:
        present_columns.append("committee_id")
    return {
        "required_candidacy_columns": ["name_on_ballot", "committee_id"],
        "present_candidacy_columns": present_columns,
        "all_required_columns_present": has_name_on_ballot and has_committee_id,
    }


def _query_coverage_counts(conn: psycopg.Connection) -> dict[str, int]:
    row = conn.execute(_COVERAGE_COUNTS_SQL).fetchone()
    if row is None:
        return {
            "total_nc_candidacies": 0,
            "linked_to_committee": 0,
            "ambiguous_unlinked": 0,
            "no_match_unlinked": 0,
        }
    return {
        "total_nc_candidacies": int(row[0]),
        "linked_to_committee": int(row[1]),
        "ambiguous_unlinked": int(row[2]),
        "no_match_unlinked": int(row[3]),
    }


def _query_office_level_breakdown(conn: psycopg.Connection) -> dict[str, dict[str, float | int]]:
    breakdown: dict[str, dict[str, float | int]] = {}
    for office_level, total_count, linked_count in conn.execute(_OFFICE_LEVEL_BREAKDOWN_SQL).fetchall():
        total = int(total_count)
        linked = int(linked_count)
        breakdown[str(office_level)] = {
            "total": total,
            "linked": linked,
            "pct_linked": _compute_pct_linked(linked, total),
        }
    return breakdown


def _query_unresolved_name_sample(
    conn: psycopg.Connection,
    *,
    sample_limit: int = _DEFAULT_UNRESOLVED_NAME_SAMPLE_LIMIT,
) -> list[str]:
    rows = conn.execute(_UNRESOLVED_NAME_SAMPLE_SQL, {"sample_limit": sample_limit}).fetchall()
    return [str(row[0]) for row in rows if row[0] is not None]


def compute_nc_committee_coverage(conn: psycopg.Connection) -> dict[str, Any]:
    prerequisite_metadata = _query_prerequisite_metadata(conn)
    coverage_counts = _query_coverage_counts(conn)
    office_level_breakdown = _query_office_level_breakdown(conn)
    unresolved_name_sample = _query_unresolved_name_sample(conn)

    total_nc_candidacies = coverage_counts["total_nc_candidacies"]
    linked_to_committee = coverage_counts["linked_to_committee"]

    return {
        "prerequisite_metadata": prerequisite_metadata,
        "total_nc_candidacies": total_nc_candidacies,
        "linked_to_committee": linked_to_committee,
        "pct_linked": _compute_pct_linked(linked_to_committee, total_nc_candidacies),
        "ambiguous_unlinked": coverage_counts["ambiguous_unlinked"],
        "no_match_unlinked": coverage_counts["no_match_unlinked"],
        "linked_pct_by_office_level": office_level_breakdown,
        "unresolved_name_sample": unresolved_name_sample,
    }


def build_coverage_payload(coverage: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scope": "stage_05_nc_candidacy_committee_coverage",
        "prerequisite_metadata": coverage["prerequisite_metadata"],
        "total_nc_candidacies": coverage["total_nc_candidacies"],
        "linked_to_committee": coverage["linked_to_committee"],
        "pct_linked": coverage["pct_linked"],
        "ambiguous_unlinked": coverage["ambiguous_unlinked"],
        "no_match_unlinked": coverage["no_match_unlinked"],
        "linked_pct_by_office_level": coverage["linked_pct_by_office_level"],
        "unresolved_name_sample": coverage["unresolved_name_sample"],
    }


def write_coverage_artifact(payload: dict[str, Any], *, artifact_path: Path | str) -> dict[str, Any]:
    resolved_path = Path(artifact_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        f"{json.dumps(payload, indent=2, sort_keys=False)}\n",
        encoding="utf-8",
    )
    return payload


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only NC candidacy-to-committee coverage probe (Stage 5).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the JSON committee-coverage artifact.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    conn = get_connection()
    try:
        coverage = compute_nc_committee_coverage(conn)
    finally:
        conn.close()
    payload = build_coverage_payload(coverage)
    write_coverage_artifact(payload, artifact_path=args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
