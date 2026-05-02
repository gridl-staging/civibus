from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
from pydantic import BaseModel

from core.db import get_connection

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L7"
_DEFAULT_FINDINGS_ROOT = _REPO_ROOT / "findings"
_L7_FINDINGS_START = "<!-- keel:L7:start -->"
_L7_FINDINGS_END = "<!-- keel:L7:end -->"

_DISCREPANCY_SQL = """
WITH entity_source_rows AS (
    SELECT
        'person'::text AS entity_type,
        p.er_cluster_id AS cluster_id,
        p.canonical_name,
        addr.normalized_address AS primary_address,
        sr.data_source_id,
        ds.name AS data_source_name
    FROM core.person p
    JOIN core.entity_source es
      ON es.entity_type = 'person'
     AND es.entity_id = p.id
    JOIN core.source_record sr
      ON sr.id = es.source_record_id
     AND sr.superseded_by IS NULL
    JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    LEFT JOIN core.address addr
      ON addr.id = p.primary_address_id
    WHERE p.er_cluster_id IS NOT NULL

    UNION ALL

    SELECT
        'organization'::text AS entity_type,
        o.er_cluster_id AS cluster_id,
        o.canonical_name,
        addr.normalized_address AS primary_address,
        sr.data_source_id,
        ds.name AS data_source_name
    FROM core.organization o
    JOIN core.entity_source es
      ON es.entity_type = 'organization'
     AND es.entity_id = o.id
    JOIN core.source_record sr
      ON sr.id = es.source_record_id
     AND sr.superseded_by IS NULL
    JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    LEFT JOIN core.address addr
      ON addr.id = o.primary_address_id
    WHERE o.er_cluster_id IS NOT NULL
),
cluster_source_coverage AS (
    SELECT
        entity_type,
        cluster_id
    FROM entity_source_rows
    GROUP BY entity_type, cluster_id
    HAVING COUNT(DISTINCT data_source_id) > 1
),
discrepancy_candidates AS (
    SELECT
        entity_type,
        cluster_id,
        'canonical_name'::text AS field,
        COUNT(DISTINCT LOWER(REGEXP_REPLACE(BTRIM(canonical_name), '\\s+', ' ', 'g'))) FILTER (
            WHERE canonical_name IS NOT NULL AND BTRIM(canonical_name) <> ''
        ) AS distinct_value_count,
        COUNT(DISTINCT data_source_id) AS source_count,
        ARRAY_AGG(DISTINCT data_source_name ORDER BY data_source_name) AS source_names,
        ARRAY_AGG(DISTINCT canonical_name ORDER BY canonical_name) FILTER (
            WHERE canonical_name IS NOT NULL AND BTRIM(canonical_name) <> ''
        ) AS values
    FROM entity_source_rows
    WHERE (entity_type, cluster_id) IN (SELECT entity_type, cluster_id FROM cluster_source_coverage)
    GROUP BY entity_type, cluster_id

    UNION ALL

    SELECT
        entity_type,
        cluster_id,
        'primary_address'::text AS field,
        COUNT(DISTINCT LOWER(REGEXP_REPLACE(BTRIM(primary_address), '\\s+', ' ', 'g'))) FILTER (
            WHERE primary_address IS NOT NULL AND BTRIM(primary_address) <> ''
        ) AS distinct_value_count,
        COUNT(DISTINCT data_source_id) AS source_count,
        ARRAY_AGG(DISTINCT data_source_name ORDER BY data_source_name) AS source_names,
        ARRAY_AGG(DISTINCT primary_address ORDER BY primary_address) FILTER (
            WHERE primary_address IS NOT NULL AND BTRIM(primary_address) <> ''
        ) AS values
    FROM entity_source_rows
    WHERE (entity_type, cluster_id) IN (SELECT entity_type, cluster_id FROM cluster_source_coverage)
    GROUP BY entity_type, cluster_id
)
SELECT
    entity_type,
    cluster_id::text,
    field,
    source_count,
    distinct_value_count,
    source_names,
    values,
    COUNT(*) OVER ()::integer AS total_discrepancy_count,
    COUNT(*) FILTER (WHERE field = 'canonical_name') OVER ()::integer AS canonical_name_discrepancy_count,
    COUNT(*) FILTER (WHERE field = 'primary_address') OVER ()::integer AS primary_address_discrepancy_count
FROM discrepancy_candidates
WHERE distinct_value_count > 1
ORDER BY entity_type, cluster_id::text, field
LIMIT %s
"""

_OVERVIEW_SQL = """
WITH entity_source_rows AS (
    SELECT
        'person'::text AS entity_type,
        p.er_cluster_id AS cluster_id,
        sr.data_source_id
    FROM core.person p
    JOIN core.entity_source es
      ON es.entity_type = 'person'
     AND es.entity_id = p.id
    JOIN core.source_record sr
      ON sr.id = es.source_record_id
     AND sr.superseded_by IS NULL
    WHERE p.er_cluster_id IS NOT NULL

    UNION ALL

    SELECT
        'organization'::text AS entity_type,
        o.er_cluster_id AS cluster_id,
        sr.data_source_id
    FROM core.organization o
    JOIN core.entity_source es
      ON es.entity_type = 'organization'
     AND es.entity_id = o.id
    JOIN core.source_record sr
      ON sr.id = es.source_record_id
     AND sr.superseded_by IS NULL
    WHERE o.er_cluster_id IS NOT NULL
),
cluster_rollup AS (
    SELECT
        entity_type,
        cluster_id,
        COUNT(DISTINCT data_source_id) AS source_count
    FROM entity_source_rows
    GROUP BY entity_type, cluster_id
)
SELECT
    COUNT(*)::integer AS checked_clusters,
    COUNT(*) FILTER (WHERE source_count > 1)::integer AS overlapping_clusters
FROM cluster_rollup
"""


@dataclass(frozen=True, slots=True)
class L7Discrepancy:
    entity_type: str
    cluster_id: str
    field: str
    source_count: int
    distinct_value_count: int
    source_names: list[str]
    values: list[str]


@dataclass(frozen=True, slots=True)
class L7Summary:
    checked_clusters: int
    overlapping_clusters: int
    discrepancy_count: int
    discrepancies_by_field: dict[str, int]
    sample_discrepancies: list[L7Discrepancy]


class L7EvidenceDiscrepancy(BaseModel, extra="forbid"):
    entity_type: str
    cluster_id: str
    field: str
    source_count: int
    distinct_value_count: int
    source_names: list[str]
    values: list[str]


class L7Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    checked_clusters: int
    overlapping_clusters: int
    discrepancy_count: int
    discrepancies_by_field: dict[str, int]
    sample_discrepancies: list[L7EvidenceDiscrepancy]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_date(value: str | None) -> date:
    if value is None:
        return _utc_now().date()
    return date.fromisoformat(value)


def _repo_sha(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_root, text=True).strip()


def summarize_discrepancies(
    connection: psycopg.Connection,
    *,
    sample_limit: int = 20,
) -> L7Summary:
    with connection.cursor() as cursor:
        cursor.execute(_OVERVIEW_SQL)
        checked_clusters, overlapping_clusters = cursor.fetchone()
        cursor.execute(_DISCREPANCY_SQL, (sample_limit,))
        rows = cursor.fetchall()

    total_discrepancy_count = 0
    discrepancies_by_field: dict[str, int] = {"canonical_name": 0, "primary_address": 0}
    if rows:
        total_discrepancy_count = int(rows[0][7])
        discrepancies_by_field = {
            "canonical_name": int(rows[0][8]),
            "primary_address": int(rows[0][9]),
        }

    sample_discrepancies = [
        L7Discrepancy(
            entity_type=row[0],
            cluster_id=row[1],
            field=row[2],
            source_count=row[3],
            distinct_value_count=row[4],
            source_names=list(row[5] or []),
            values=list(row[6] or []),
        )
        for row in rows
    ]

    return L7Summary(
        checked_clusters=checked_clusters,
        overlapping_clusters=overlapping_clusters,
        discrepancy_count=total_discrepancy_count,
        discrepancies_by_field=discrepancies_by_field,
        sample_discrepancies=sample_discrepancies,
    )


def _evidence_status(summary: L7Summary) -> str:
    return "pass" if summary.discrepancy_count == 0 else "fail"


def write_l7_evidence(
    *,
    repo_root: Path,
    evidence_root: Path,
    evidence_date: date,
    produced_at: datetime,
    summary: L7Summary,
) -> Path:
    scope_root = evidence_root / "global"
    scope_root.mkdir(parents=True, exist_ok=True)
    payload = L7Evidence(
        layer="L7",
        scope="global",
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=_repo_sha(repo_root),
        gate_command="make gate-L7",
        status=_evidence_status(summary),
        checked_clusters=summary.checked_clusters,
        overlapping_clusters=summary.overlapping_clusters,
        discrepancy_count=summary.discrepancy_count,
        discrepancies_by_field=summary.discrepancies_by_field,
        sample_discrepancies=[
            L7EvidenceDiscrepancy(
                entity_type=item.entity_type,
                cluster_id=item.cluster_id,
                field=item.field,
                source_count=item.source_count,
                distinct_value_count=item.distinct_value_count,
                source_names=item.source_names,
                values=item.values,
            )
            for item in summary.sample_discrepancies
        ],
    )
    destination = scope_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def _build_l7_findings_section(*, evidence_date: date, summary: L7Summary) -> str:
    lines = [
        _L7_FINDINGS_START,
        "## L7 - Cross-Source Reconciliation",
        "",
        f"- Date: {evidence_date.isoformat()}",
        f"- Checked clusters: {summary.checked_clusters}",
        f"- Overlapping clusters: {summary.overlapping_clusters}",
        f"- Discrepancies: {summary.discrepancy_count}",
        "",
    ]
    for item in summary.sample_discrepancies:
        lines.append(
            f"- {item.entity_type} cluster `{item.cluster_id}` field `{item.field}` "
            f"sources={item.source_count} values={', '.join(item.values)}"
        )
    lines.extend(["", _L7_FINDINGS_END])
    return "\n".join(lines)


def sync_findings_section(
    *,
    findings_root: Path,
    evidence_date: date,
    section_start: str,
    section_end: str,
    section_text: str,
    remove_section_when_empty: bool = False,
) -> Path | None:
    """Sync a date-scoped findings section by replacing the existing marker block in place."""
    findings_root.mkdir(parents=True, exist_ok=True)
    findings_path = findings_root / f"{evidence_date.isoformat()}.md"
    existing_text = findings_path.read_text(encoding="utf-8") if findings_path.exists() else ""
    section_pattern = re.compile(re.escape(section_start) + r".*?" + re.escape(section_end), flags=re.DOTALL)

    if remove_section_when_empty and not section_text:
        if not existing_text:
            return None
        updated_text = section_pattern.sub("", existing_text).strip()
        if updated_text:
            findings_path.write_text(updated_text + "\n", encoding="utf-8")
            return findings_path
        findings_path.unlink()
        return None

    if existing_text:
        if section_pattern.search(existing_text):
            updated_text = section_pattern.sub(section_text, existing_text)
        else:
            updated_text = existing_text.rstrip() + "\n\n" + section_text + "\n"
    else:
        updated_text = f"# Keel Findings - {evidence_date.isoformat()}\n\n{section_text}\n"

    findings_path.write_text(updated_text, encoding="utf-8")
    return findings_path


def sync_l7_findings(
    *,
    findings_root: Path,
    evidence_date: date,
    summary: L7Summary,
) -> Path | None:
    if summary.discrepancy_count == 0:
        return sync_findings_section(
            findings_root=findings_root,
            evidence_date=evidence_date,
            section_start=_L7_FINDINGS_START,
            section_end=_L7_FINDINGS_END,
            section_text="",
            remove_section_when_empty=True,
        )

    section_text = _build_l7_findings_section(evidence_date=evidence_date, summary=summary)
    return sync_findings_section(
        findings_root=findings_root,
        evidence_date=evidence_date,
        section_start=_L7_FINDINGS_START,
        section_end=_L7_FINDINGS_END,
        section_text=section_text,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize cross-source reconciliation discrepancies for Keel L7")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--date", help="UTC date to write evidence for (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--findings-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    evidence_date = _parse_date(args.date)
    produced_at = _utc_now()
    evidence_root = args.evidence_root.resolve() if args.evidence_root else repo_root / "evidence" / "L7"
    findings_root = args.findings_root.resolve() if args.findings_root else repo_root / "findings"

    connection: psycopg.Connection | None = None
    try:
        connection = get_connection()
        summary = summarize_discrepancies(connection, sample_limit=args.sample_limit)
        evidence_path = write_l7_evidence(
            repo_root=repo_root,
            evidence_root=evidence_root,
            evidence_date=evidence_date,
            produced_at=produced_at,
            summary=summary,
        )
        findings_path = sync_l7_findings(
            findings_root=findings_root,
            evidence_date=evidence_date,
            summary=summary,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L7 failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    status = _evidence_status(summary)
    findings_detail = "none" if findings_path is None else findings_path
    print(
        f"{status.upper()}: checked_clusters={summary.checked_clusters} "
        f"overlapping_clusters={summary.overlapping_clusters} discrepancies={summary.discrepancy_count} "
        f"evidence={evidence_path} findings={findings_detail}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
