from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator

from core.db import get_connection
from core.graph.loader import CONTRIBUTION_LIKE_TYPES

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ANCHORS_ROOT = _REPO_ROOT / "docs" / "anchors"
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L1"
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n?", re.DOTALL)
_SECTION_HEADING_RE = re.compile(r"^## (?P<title>.+)$", re.MULTILINE)
_PRIMARY_CONTRIBUTION_METRICS = frozenset({"total_contributions_raised", "total_contributions"})
_L1_ADDITIONAL_RECEIPT_TYPES = frozenset(
    {
        # NC loads preserve the source's receipt-side contributor class in
        # transaction_type instead of rewriting it to the FEC-style monetary labels.
        "Individual",
        "Non-Party Comm",
        "Business/Group/Org",
    }
)
_L1_RECEIPT_TYPES = frozenset(CONTRIBUTION_LIKE_TYPES | _L1_ADDITIONAL_RECEIPT_TYPES)


class AnchorFrontmatter(BaseModel, extra="forbid"):
    scope: str
    domain: str
    review_cadence_days: int = Field(ge=1)
    created: date
    updated: date
    schema_version: int = Field(ge=1)


class AggregateExpectation(BaseModel, extra="forbid"):
    metric: str
    value_expected: int | float | list[int | float]
    unit: str
    cycle: int = Field(ge=1900)
    source: HttpUrl
    tier: int = Field(ge=1, le=3)
    accessed: date
    notes: str | None = None

    @property
    def expected_minimum(self) -> Decimal:
        minimum, _ = _normalize_expected_range(self.value_expected)
        return minimum

    @property
    def expected_maximum(self) -> Decimal:
        _, maximum = _normalize_expected_range(self.value_expected)
        return maximum


class NamedEntityExpectation(BaseModel, extra="forbid"):
    name: str
    entity_type: str
    role_or_office: str
    cycle: int = Field(ge=1900)
    source: HttpUrl
    tier: int = Field(ge=1, le=3)
    accessed: date


class NegativeExpectation(BaseModel, extra="forbid"):
    pattern: str
    reason: str
    source: str
    tier: int | str
    accessed: date

    @field_validator("tier")
    @classmethod
    def _validate_tier(cls, value: int | str) -> int | str:
        if value == "internal":
            return value
        if value in {1, 2, 3}:
            return value
        raise ValueError("negative expectation tier must be 1, 2, 3, or 'internal'")


class SourceBibliographyEntry(BaseModel, extra="forbid"):
    url: HttpUrl
    description: str


class AnchorFile(BaseModel, extra="forbid"):
    frontmatter: AnchorFrontmatter
    coverage_boundary: str
    aggregate_expectations: list[AggregateExpectation]
    named_entity_expectations: list[NamedEntityExpectation]
    negative_expectations: list[NegativeExpectation]
    source_bibliography: list[SourceBibliographyEntry]


class L1Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    current_total: float
    expected_range: dict[str, float]
    ratio: float
    anchor_path: str
    anchor_schema_version: int
    data_store_environment: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=_REPO_ROOT, text=True).strip()


def _data_store_environment() -> str:
    return os.getenv("CIVIBUS_ENV", "development")


def _display_anchor_path(anchor_path: Path) -> str:
    try:
        return str(anchor_path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(anchor_path)


def _normalize_expected_range(value: int | float | list[int | float]) -> tuple[Decimal, Decimal]:
    if isinstance(value, (int, float)):
        normalized = Decimal(str(value))
        return normalized, normalized

    if len(value) != 2:
        raise ValueError("aggregate expectation ranges must contain exactly two values")

    minimum = Decimal(str(value[0]))
    maximum = Decimal(str(value[1]))
    if maximum < minimum:
        raise ValueError("aggregate expectation range maximum must be >= minimum")
    return minimum, maximum


def _split_sections(markdown_body: str) -> dict[str, str]:
    matches = list(_SECTION_HEADING_RE.finditer(markdown_body))
    if not matches:
        raise ValueError("anchor file is missing required markdown sections")

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        section_start = match.end()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_body)
        sections[match.group("title")] = markdown_body[section_start:section_end].strip()
    return sections


def _load_yaml_section(sections: dict[str, str], section_name: str) -> object:
    section_body = sections.get(section_name)
    if not section_body:
        raise ValueError(f"anchor file is missing the '{section_name}' section")
    return yaml.safe_load(section_body)


def _load_text_section(sections: dict[str, str], section_name: str) -> str:
    section_body = sections.get(section_name)
    if not section_body:
        raise ValueError(f"anchor file is missing the '{section_name}' section")
    return section_body.strip()


def load_anchor_file(anchor_path: Path) -> AnchorFile:
    markdown = anchor_path.read_text(encoding="utf-8")
    frontmatter_match = _FRONTMATTER_RE.match(markdown)
    if frontmatter_match is None:
        raise ValueError(f"anchor file {anchor_path} is missing YAML frontmatter")

    frontmatter = AnchorFrontmatter.model_validate(yaml.safe_load(frontmatter_match.group("frontmatter")))
    sections = _split_sections(markdown[frontmatter_match.end() :])

    anchor = AnchorFile(
        frontmatter=frontmatter,
        coverage_boundary=_load_text_section(sections, "Coverage boundary"),
        aggregate_expectations=_load_yaml_section(sections, "Aggregate expectations"),
        named_entity_expectations=_load_yaml_section(sections, "Named-entity expectations"),
        negative_expectations=_load_yaml_section(sections, "Negative expectations"),
        source_bibliography=_load_yaml_section(sections, "Source bibliography"),
    )
    if not anchor.coverage_boundary:
        raise ValueError("anchor file must include a non-empty coverage boundary")
    if len(anchor.aggregate_expectations) < 3:
        raise ValueError("anchor file must include at least 3 aggregate expectations")
    if len(anchor.named_entity_expectations) < 5:
        raise ValueError("anchor file must include at least 5 named-entity expectations")
    if len(anchor.negative_expectations) < 2:
        raise ValueError("anchor file must include at least 2 negative expectations")
    return anchor


def select_primary_metric(anchor: AnchorFile) -> AggregateExpectation:
    preferred = [
        metric
        for metric in anchor.aggregate_expectations
        if metric.metric in _PRIMARY_CONTRIBUTION_METRICS
        or (metric.unit == "usd" and "contribution" in metric.metric.lower())
    ]
    if not preferred:
        raise ValueError("anchor file is missing a contribution-total aggregate expectation for L1 ratio checks")
    return sorted(preferred, key=lambda metric: metric.cycle, reverse=True)[0]


def query_scope_total(
    connection: psycopg.Connection,
    *,
    jurisdiction: str,
    cycle: int,
) -> Decimal:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(SUM(t.amount), 0)
            FROM cf.transaction t
            JOIN cf.committee c
              ON c.id = t.committee_id
            WHERE c.state = %s
              AND t.transaction_type = ANY(%s)
              AND t.support_oppose IS NULL
              AND t.transaction_date >= %s
              AND t.transaction_date < %s
            """,
            (
                jurisdiction,
                sorted(_L1_RECEIPT_TYPES),
                date(cycle, 1, 1),
                date(cycle + 1, 1, 1),
            ),
        )
        total = cursor.fetchone()[0]
    return Decimal(str(total))


def _ratio(*, current_total: Decimal, expected_minimum: Decimal) -> Decimal:
    if expected_minimum <= 0:
        return Decimal("1")
    return current_total / expected_minimum


def _status(*, current_total: Decimal, metric: AggregateExpectation) -> str:
    return "pass" if metric.expected_minimum <= current_total <= metric.expected_maximum else "fail"


def write_l1_evidence(
    *,
    jurisdiction: str,
    metric: AggregateExpectation,
    current_total: Decimal,
    repo_sha: str,
    produced_at: datetime,
    evidence_root: Path,
    anchor_path: Path,
    anchor_schema_version: int,
    data_store_environment: str,
    status: str | None = None,
) -> Path:
    destination_root = evidence_root / jurisdiction
    destination_root.mkdir(parents=True, exist_ok=True)
    ratio = _ratio(current_total=current_total, expected_minimum=metric.expected_minimum)
    payload = L1Evidence(
        layer="L1",
        scope=jurisdiction,
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command=f"make gate-L1 JURISDICTION={jurisdiction}",
        status=_status(current_total=current_total, metric=metric) if status is None else status,
        current_total=float(current_total),
        expected_range={
            "minimum": float(metric.expected_minimum),
            "maximum": float(metric.expected_maximum),
        },
        ratio=float(ratio),
        anchor_path=_display_anchor_path(anchor_path),
        anchor_schema_version=anchor_schema_version,
        data_store_environment=data_store_environment,
    )
    destination = destination_root / f"{produced_at.date().isoformat()}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel L1 jurisdiction-anchor gate")
    parser.add_argument("--jurisdiction", required=True, help="Jurisdiction scope code, e.g. NC")
    parser.add_argument("--anchors-root", type=Path, default=_DEFAULT_ANCHORS_ROOT)
    parser.add_argument("--evidence-root", type=Path, default=_DEFAULT_EVIDENCE_ROOT)
    return parser


def require_production_data_store() -> str:
    data_store_environment = _data_store_environment()
    if data_store_environment != "production":
        raise RuntimeError(
            "gate-L1 must run against the production data store "
            f"(CIVIBUS_ENV=production, got {data_store_environment!r})"
        )
    return data_store_environment


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    jurisdiction = args.jurisdiction.upper()
    anchor_path = args.anchors_root / f"{jurisdiction}.md"
    produced_at = _utc_now()
    anchor: AnchorFile | None = None
    metric: AggregateExpectation | None = None
    data_store_environment = _data_store_environment()

    connection: psycopg.Connection | None = None
    try:
        anchor = load_anchor_file(anchor_path)
        if anchor.frontmatter.scope != jurisdiction:
            raise ValueError(f"anchor scope mismatch: expected {jurisdiction!r}, found {anchor.frontmatter.scope!r}")
        metric = select_primary_metric(anchor)
        data_store_environment = require_production_data_store()
        connection = get_connection()
        current_total = query_scope_total(connection, jurisdiction=jurisdiction, cycle=metric.cycle)
        evidence_path = write_l1_evidence(
            jurisdiction=jurisdiction,
            metric=metric,
            current_total=current_total,
            repo_sha=_repo_sha(),
            produced_at=produced_at,
            evidence_root=args.evidence_root,
            anchor_path=anchor_path,
            anchor_schema_version=anchor.frontmatter.schema_version,
            data_store_environment=data_store_environment,
        )
    except Exception as error:  # noqa: BLE001
        if anchor is not None and metric is not None:
            write_l1_evidence(
                jurisdiction=jurisdiction,
                metric=metric,
                current_total=Decimal("0"),
                repo_sha=_repo_sha(),
                produced_at=produced_at,
                evidence_root=args.evidence_root,
                anchor_path=anchor_path,
                anchor_schema_version=anchor.frontmatter.schema_version,
                data_store_environment=data_store_environment,
                status="error",
            )
        print(f"gate-L1 failed for {jurisdiction}: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    status = _status(current_total=current_total, metric=metric)
    print(
        f"{status.upper()}: jurisdiction={jurisdiction} cycle={metric.cycle} "
        f"current_total={current_total} expected_min={metric.expected_minimum} "
        f"expected_max={metric.expected_maximum} evidence={evidence_path}"
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
