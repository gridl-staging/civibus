
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, model_validator

from api.models.provenance import SourceInfo
from api.queries import CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, fetch_campaign_finance_provenance, fetch_one_row
from api.queries._common import fetch_entity_provenance
from core.db import get_connection

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L9"
_DEFAULT_FINDINGS_ROOT = _REPO_ROOT / "findings"
_L9_FINDINGS_START = "<!-- keel:L9:start -->"
_L9_FINDINGS_END = "<!-- keel:L9:end -->"
_SAFE_TRACE_SCHEMES = frozenset({"http", "https"})
MISSING_SAFE_TRACE_URL = "missing_safe_trace_url"

# Stage 1 of the walker intentionally stays narrow. It samples only detail
# routes whose existing API owners already expose provenance-backed SourceInfo
# rows today: campaign-finance committee detail pages and civic office detail
# pages. It does not try to crawl arbitrary rendered HTML or cover every domain.
_TRACE_TARGET_SQL = """
WITH committee_candidates AS (
    SELECT id
    FROM (
        SELECT
            c.id
        FROM cf.committee c
        WHERE c.source_record_id IS NOT NULL
        ORDER BY c.id
        LIMIT %s
    ) direct_committees

    UNION ALL

    SELECT id
    FROM (
        SELECT
            c.id
        FROM core.entity_source es
        JOIN cf.committee c
          ON c.organization_id = es.entity_id
        WHERE es.entity_type = 'organization'
        ORDER BY c.id
        LIMIT %s
    ) entity_source_committees
),
committee_targets AS (
    SELECT
        1 AS route_order,
        '/v1/committees/' || c.id::text AS route,
        c.id::text AS detail_id,
        'committee'::text AS target_type
    FROM cf.committee c
    JOIN (
        SELECT DISTINCT id
        FROM committee_candidates
        ORDER BY id
        LIMIT %s
    ) candidates
      ON candidates.id = c.id
),
office_targets AS (
    SELECT
        2 AS route_order,
        '/v1/offices/' || o.id::text AS route,
        o.id::text AS detail_id,
        'office'::text AS target_type
    FROM core.entity_source es
    JOIN civic.office o
      ON o.id = es.entity_id
    WHERE es.entity_type = 'office'
    GROUP BY o.id
    ORDER BY o.id
    LIMIT %s
)
SELECT route, detail_id, target_type
FROM (
    SELECT * FROM committee_targets
    UNION ALL
    SELECT * FROM office_targets
) targets
ORDER BY route_order, detail_id
LIMIT %s
"""


class ResolvedTraceUrl(BaseModel, extra="forbid"):
    url: str
    url_source: Literal["record_url", "data_source_url"]


class L9TraceSample(BaseModel, extra="forbid"):
    route: str
    detail_id: str
    data_source_name: str
    source_record_key: str | None = None
    selected_url: str
    selected_url_source: Literal["record_url", "data_source_url"]


class L9TraceOrphan(BaseModel, extra="forbid"):
    route: str
    detail_id: str
    data_source_name: str
    source_record_key: str | None = None
    record_url: str | None = None
    data_source_url: str
    orphan_reason: Literal["missing_safe_trace_url"] = MISSING_SAFE_TRACE_URL


class L9Evidence(BaseModel, extra="forbid"):

    layer: Literal["L9"]
    scope: str
    schema_version: Literal[1]
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: Literal["pass", "fail", "error", "waived", "stale"]
    sampled_record_count: int
    orphan_record_count: int
    sampled_records: list[L9TraceSample]
    orphan_records: list[L9TraceOrphan]

    @model_validator(mode="after")
    def validate_counts_match_payload(self) -> L9Evidence:
        if self.sampled_record_count != len(self.sampled_records):
            raise ValueError("sampled_record_count must match sampled_records length")
        if self.orphan_record_count != len(self.orphan_records):
            raise ValueError("orphan_record_count must match orphan_records length")
        return self


@dataclass(frozen=True, slots=True)
class L9TraceTarget:
    route: str
    detail_id: str
    target_type: Literal["committee", "office"]


@dataclass(frozen=True, slots=True)
class L9TraceReport:
    sampled_records: list[L9TraceSample]
    orphan_records: list[L9TraceOrphan]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_date(value: str | None) -> date:
    if value is None:
        return _utc_now().date()
    return date.fromisoformat(value)


def _parse_positive_sample_limit(value: str) -> int:
    parsed_value = int(value)
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError("--sample-limit must be greater than zero")
    return parsed_value


def _split_trace_target_limits(sample_limit: int) -> tuple[int, int]:
    """Reserve deterministic per-surface capacity within the overall L9 sample."""
    office_limit = sample_limit // 2
    committee_limit = sample_limit - office_limit
    return committee_limit, office_limit


def _repo_sha(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_root, text=True).strip()


def _sanitize_trace_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in _SAFE_TRACE_SCHEMES:
        return None
    if not parsed.netloc:
        return None
    return parsed.geturl()


def resolve_trace_url(source: SourceInfo) -> ResolvedTraceUrl | None:
    """Resolve trace URLs using the same precedence the UI already exposes."""
    safe_record_url = _sanitize_trace_url(source.record_url)
    if safe_record_url is not None:
        return ResolvedTraceUrl(url=safe_record_url, url_source="record_url")

    safe_source_url = _sanitize_trace_url(source.data_source_url)
    if safe_source_url is not None:
        return ResolvedTraceUrl(url=safe_source_url, url_source="data_source_url")

    return None


def list_trace_targets(
    connection: psycopg.Connection,
    *,
    sample_limit: int = 50,
) -> list[L9TraceTarget]:
    """Return the bounded, deterministic Stage 1 target set for L9."""
    committee_limit, office_limit = _split_trace_target_limits(sample_limit)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _TRACE_TARGET_SQL,
            (
                committee_limit,
                committee_limit,
                committee_limit,
                office_limit,
                sample_limit,
            ),
        )
        rows = list(cursor.fetchall())

    return [
        L9TraceTarget(
            route=row["route"],
            detail_id=row["detail_id"],
            target_type=row["target_type"],
        )
        for row in rows
    ]


def fetch_trace_target_sources(
    connection: psycopg.Connection,
    target: L9TraceTarget,
) -> list[SourceInfo]:
    """Load the exact provenance row shape that the supported detail routes expose."""
    detail_id = UUID(target.detail_id)
    if target.target_type == "committee":
        detail_row = fetch_one_row(connection, query=CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, row_id=detail_id)
        if detail_row is None:
            return []
        provenance_rows = fetch_campaign_finance_provenance(
            connection,
            row_source_record_id=detail_row["source_record_id"],
            canonical_entity_type="organization",
            canonical_entity_id=detail_row["organization_id"],
        )
    elif target.target_type == "office":
        provenance_rows = fetch_entity_provenance(connection, "office", detail_id)
    else:  # pragma: no cover - guarded by list_trace_targets/query contract.
        raise ValueError(f"Unsupported L9 target type: {target.target_type}")

    return [SourceInfo.model_validate(row) for row in provenance_rows]


def collect_trace_report(
    targets: Sequence[L9TraceTarget],
    source_loader: Callable[[L9TraceTarget], Iterable[SourceInfo]],
) -> L9TraceReport:
    """Resolve URLs for each supported target's provenance rows.

    The walker sorts targets defensively even though the SQL already orders them.
    That keeps test fixtures and any future alternate loaders deterministic.
    """
    sampled_records: list[L9TraceSample] = []
    orphan_records: list[L9TraceOrphan] = []

    for target in sorted(targets, key=lambda item: (item.route, item.detail_id)):
        for source in source_loader(target):
            resolved = resolve_trace_url(source)
            if resolved is None:
                orphan_records.append(
                    L9TraceOrphan(
                        route=target.route,
                        detail_id=target.detail_id,
                        data_source_name=source.data_source_name,
                        source_record_key=source.source_record_key,
                        record_url=source.record_url,
                        data_source_url=source.data_source_url,
                        orphan_reason=MISSING_SAFE_TRACE_URL,
                    )
                )
                continue

            sampled_records.append(
                L9TraceSample(
                    route=target.route,
                    detail_id=target.detail_id,
                    data_source_name=source.data_source_name,
                    source_record_key=source.source_record_key,
                    selected_url=resolved.url,
                    selected_url_source=resolved.url_source,
                )
            )

    return L9TraceReport(
        sampled_records=sampled_records,
        orphan_records=orphan_records,
    )


def build_trace_report(
    connection: psycopg.Connection,
    *,
    sample_limit: int = 50,
) -> L9TraceReport:
    """Run the Stage 1 L9 walk against the supported detail routes."""
    targets = list_trace_targets(connection, sample_limit=sample_limit)
    return collect_trace_report(
        targets,
        lambda target: fetch_trace_target_sources(connection, target),
    )


def _evidence_status(report: L9TraceReport) -> Literal["pass", "fail"]:
    return "pass" if not report.orphan_records else "fail"


def _build_gate_command(evidence_date: date, sample_limit: int) -> str:
    return f"uv run python -m core.keel_gate_l9 --date {evidence_date.isoformat()} --sample-limit {sample_limit}"


def write_l9_evidence(
    *,
    repo_root: Path,
    evidence_root: Path,
    evidence_date: date,
    produced_at: datetime,
    sample_limit: int,
    report: L9TraceReport,
) -> Path:
    """Persist the L9 evidence artifact for the requested UTC date."""
    evidence_root.mkdir(parents=True, exist_ok=True)
    payload = L9Evidence(
        layer="L9",
        scope="global",
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=_repo_sha(repo_root),
        gate_command=_build_gate_command(evidence_date, sample_limit),
        status=_evidence_status(report),
        sampled_record_count=len(report.sampled_records),
        orphan_record_count=len(report.orphan_records),
        sampled_records=report.sampled_records,
        orphan_records=report.orphan_records,
    )
    destination = evidence_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def _build_l9_findings_section(*, evidence_date: date, report: L9TraceReport) -> str:
    lines = [
        _L9_FINDINGS_START,
        "## L9 - Provenance Walker",
        "",
        f"- Date: {evidence_date.isoformat()}",
        f"- Successful trace rows: {len(report.sampled_records)}",
        f"- Orphan trace rows: {len(report.orphan_records)}",
        "- Sample scope: committee detail and office detail provenance rows",
        "",
    ]
    for orphan in report.orphan_records:
        lines.append(
            f"- route={orphan.route} detail_id={orphan.detail_id} "
            f"source={orphan.data_source_name} record_key={orphan.source_record_key or 'none'} "
            f"reason={orphan.orphan_reason}"
        )
    lines.extend(["", _L9_FINDINGS_END])
    return "\n".join(lines)


def sync_l9_findings(
    *,
    findings_root: Path,
    evidence_date: date,
    report: L9TraceReport,
) -> Path | None:
    """Replace the same-day L9 findings block or remove it when the run is clean."""
    findings_root.mkdir(parents=True, exist_ok=True)
    findings_path = findings_root / f"{evidence_date.isoformat()}.md"
    existing_text = findings_path.read_text(encoding="utf-8") if findings_path.exists() else ""
    section_pattern = re.compile(
        re.escape(_L9_FINDINGS_START) + r".*?" + re.escape(_L9_FINDINGS_END),
        flags=re.DOTALL,
    )

    if not report.orphan_records:
        if not existing_text:
            return None
        updated_text = section_pattern.sub("", existing_text).strip()
        if updated_text:
            findings_path.write_text(updated_text + "\n", encoding="utf-8")
            return findings_path
        findings_path.unlink()
        return None

    section_text = _build_l9_findings_section(evidence_date=evidence_date, report=report)
    if existing_text:
        if section_pattern.search(existing_text):
            updated_text = section_pattern.sub(section_text, existing_text)
        else:
            updated_text = existing_text.rstrip() + "\n\n" + section_text + "\n"
    else:
        updated_text = f"# Keel Findings - {evidence_date.isoformat()}\n\n{section_text}\n"
    findings_path.write_text(updated_text, encoding="utf-8")
    return findings_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel L9 provenance walker")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--date", help="UTC date to write evidence for (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument("--sample-limit", type=_parse_positive_sample_limit, default=50)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--findings-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the bounded L9 trace walk and persist evidence + findings outputs."""
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    evidence_date = _parse_date(args.date)
    produced_at = _utc_now()
    evidence_root = args.evidence_root.resolve() if args.evidence_root else repo_root / "evidence" / "L9"
    findings_root = args.findings_root.resolve() if args.findings_root else repo_root / "findings"

    connection: psycopg.Connection | None = None
    try:
        connection = get_connection()
        report = build_trace_report(connection, sample_limit=args.sample_limit)
        evidence_path = write_l9_evidence(
            repo_root=repo_root,
            evidence_root=evidence_root,
            evidence_date=evidence_date,
            produced_at=produced_at,
            sample_limit=args.sample_limit,
            report=report,
        )
        findings_path = sync_l9_findings(
            findings_root=findings_root,
            evidence_date=evidence_date,
            report=report,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L9 failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    status = _evidence_status(report)
    findings_detail = "none" if findings_path is None else findings_path
    print(
        f"{status.upper()}: sampled={len(report.sampled_records)} "
        f"orphans={len(report.orphan_records)} "
        f"evidence={evidence_path} findings={findings_detail}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
