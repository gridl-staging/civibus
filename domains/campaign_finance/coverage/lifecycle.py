
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .registry import TierLiteral, format_validation_errors

AcquisitionPatternLiteral = Literal[
    "bulk_file",
    "bulk_api",
    "search_export_portal",
    "browser_session_portal",
    "protected_or_blocked",
    "unknown",
]
DiscoveryMaturityLiteral = Literal["not_started", "researched", "interactively_proven", "blocked"]
SourceContractMaturityLiteral = Literal["not_started", "partial", "encoded", "verified"]
LegalFilingSemanticsMaturityLiteral = Literal["not_started", "partial", "substantial", "verified"]
ImplementationMaturityLiteral = Literal[
    "not_started",
    "scaffolded",
    "fixture_tested",
    "live_proven",
    "full_history_proven",
]
OperationalMaturityLiteral = Literal["unknown", "manual_only", "runner_wired", "operational"]
CompletenessIntelligenceMaturityLiteral = Literal[
    "not_started",
    "rules_only",
    "observed_only",
    "gap_detection_ready",
]
CivicsCandidacyStatusLiteral = Literal[
    "not_started",
    "loaded",
    "full_csv_proven",
]

DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "implemented-region-lifecycle.json"
)
DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "reference" / "research" / "implemented-region-lifecycle-summary.md"
)
_LIFECYCLE_AUTHORITY_NOTE = "Authoritative source: `docs/reference/research/implemented-region-lifecycle.json`."


class LifecycleBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImplementedRegionLifecycleRow(LifecycleBaseModel):

    jurisdiction_code: str
    name: str
    acquisition_pattern: AcquisitionPatternLiteral
    discovery_maturity: DiscoveryMaturityLiteral
    source_contract_maturity: SourceContractMaturityLiteral
    legal_filing_semantics_maturity: LegalFilingSemanticsMaturityLiteral
    implementation_maturity: ImplementationMaturityLiteral
    operational_maturity: OperationalMaturityLiteral
    public_claim_status: TierLiteral
    completeness_intelligence_maturity: CompletenessIntelligenceMaturityLiteral
    civics_candidacy_status: CivicsCandidacyStatusLiteral
    main_blocker: str

    @model_validator(mode="after")
    def _validate_main_blocker(self) -> "ImplementedRegionLifecycleRow":
        if not self.main_blocker.strip():
            raise ValueError(f"main_blocker must be non-empty for row '{self.jurisdiction_code}'")
        return self


class ImplementedRegionLifecycleRegistry(LifecycleBaseModel):
    updated_at: date
    rows: list[ImplementedRegionLifecycleRow]

    @model_validator(mode="after")
    def _validate_unique_jurisdiction_codes(self) -> "ImplementedRegionLifecycleRegistry":
        duplicate_codes = _collect_duplicate_jurisdiction_codes(self.rows)
        if duplicate_codes:
            details = "; ".join(
                f"{code} at row indexes {', '.join(str(index) for index in indexes)}"
                for code, indexes in sorted(duplicate_codes.items())
            )
            raise ValueError(f"Duplicate lifecycle jurisdiction code(s): {details}")
        return self


def _collect_duplicate_jurisdiction_codes(rows: list[ImplementedRegionLifecycleRow]) -> dict[str, list[int]]:
    code_to_indexes: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        code_to_indexes[row.jurisdiction_code].append(index)
    return {code: indexes for code, indexes in code_to_indexes.items() if len(indexes) > 1}


def load_lifecycle_json(path: str | Path) -> object:
    lifecycle_path = Path(path)
    try:
        return json.loads(lifecycle_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Failed to read lifecycle file at {lifecycle_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse lifecycle JSON at {lifecycle_path}: {error}") from error


def load_lifecycle(path: str | Path) -> ImplementedRegionLifecycleRegistry:
    lifecycle_path = Path(path)
    raw_payload = load_lifecycle_json(lifecycle_path)
    try:
        return ImplementedRegionLifecycleRegistry.model_validate(raw_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid lifecycle JSON at {lifecycle_path}: {format_validation_errors(error)}") from error


def write_lifecycle(path: str | Path, lifecycle: ImplementedRegionLifecycleRegistry) -> Path:
    lifecycle_path = Path(path)
    lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_path.write_text(f"{lifecycle.model_dump_json(indent=2)}\n", encoding="utf-8")
    return lifecycle_path


def _escape_markdown_cell(value: object) -> str:
    """Keep derived markdown tables stable even when human-edited text contains table syntax."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_lifecycle_summary_markdown(lifecycle: ImplementedRegionLifecycleRegistry) -> str:
    lines = [
        "# Implemented Region Lifecycle Summary (Derived)",
        "",
        f"Date: {lifecycle.updated_at.isoformat()}",
        "",
        _LIFECYCLE_AUTHORITY_NOTE,
        (
            "This summary is a derived view of lifecycle statuses for the FEC plus "
            "implemented campaign-finance state packages."
        ),
        "",
        "## Implemented Region Layer Status",
        "",
        (
            "| Jurisdiction | Acquisition Pattern | Discovery | Source Contract | "
            "Legal / Filing Semantics | Implementation | Operations | Public Claim | "
            "Completeness Intelligence | Civics Candidacy | Main Blocker |"
        ),
        ("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"),
    ]
    for row in lifecycle.rows:
        lines.append(
            f"| {_escape_markdown_cell(row.jurisdiction_code)} | "
            f"{_escape_markdown_cell(row.acquisition_pattern)} | "
            f"{_escape_markdown_cell(row.discovery_maturity)} | "
            f"{_escape_markdown_cell(row.source_contract_maturity)} | "
            f"{_escape_markdown_cell(row.legal_filing_semantics_maturity)} | "
            f"{_escape_markdown_cell(row.implementation_maturity)} | "
            f"{_escape_markdown_cell(row.operational_maturity)} | "
            f"{_escape_markdown_cell(row.public_claim_status)} | "
            f"{_escape_markdown_cell(row.completeness_intelligence_maturity)} | "
            f"{_escape_markdown_cell(row.civics_candidacy_status)} | "
            f"{_escape_markdown_cell(row.main_blocker)} |"
        )
    return "\n".join(lines) + "\n"


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render implemented-region lifecycle summary markdown from lifecycle JSON",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
        help="Input path for implemented-region lifecycle JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH,
        help="Output path for implemented-region lifecycle summary markdown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        lifecycle = load_lifecycle(args.path)
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_lifecycle_summary_markdown(lifecycle), encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print(f"Wrote implemented-region lifecycle summary markdown: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
