"""Coverage registry data model and I/O for campaign finance jurisdiction tracking."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError, model_validator

from domains.campaign_finance.jurisdictions.config_schema import JurisdictionTypeLiteral, UpdateFrequencyLiteral

TierLiteral = Literal[
    "launch-support candidate",
    "freshness-limited",
    "deferred/blocked",
    "implemented but unproven",
]

MunicipalAuditDecisionLiteral = Literal[
    "covered_by_parent",
    "independent_target",
]

# Jurisdiction types that are state-equivalent (no parent linkage allowed)
_STATE_EQUIVALENT_TYPES: frozenset[str] = frozenset({"federal", "state"})
_MUNICIPALITY_TYPE = "municipality"

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "docs" / "research" / "coverage-registry.json"


class CoverageRegistryBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoverageRegistryRow(CoverageRegistryBaseModel):
    """Single jurisdiction entry in the coverage registry."""

    jurisdiction_code: str
    name: str
    jurisdiction_type: JurisdictionTypeLiteral

    best_update_frequency: UpdateFrequencyLiteral
    best_last_verified_working: date | None
    covers_sub_jurisdictions: bool
    source_count: StrictInt
    source_names: list[str]

    runner_wired: bool

    tier: TierLiteral | None
    evidence_summary: str | None
    operational_reason: str | None
    next_action: str | None
    evidence_date: date | None
    loaded_count: StrictInt | None = None
    expected_count: StrictInt | None = None
    # Tri-state evidence flag for outside-spending coverage. None = not yet
    # determined (existing tier-based behavior preserved). False is required when
    # the source's evidence shows the current bulk export does not carry IE
    # data, so the API must return null IE totals instead of misleading zeroes.
    ie_coverage_available: bool | None = None

    # Municipality layer fields (Stage 5) — null for state-equivalent rows
    parent_jurisdiction_code: str | None = None
    municipal_audit_decision: MunicipalAuditDecisionLiteral | None = None
    # Browser-verified portal URL for independent municipalities (Stage 1 city research)
    municipal_portal_url: str | None = None

    @model_validator(mode="after")
    def _validate_municipality_linkage(self) -> "CoverageRegistryRow":
        """Enforce parent/decision/portal constraints by jurisdiction type."""
        is_municipality = self.jurisdiction_type == _MUNICIPALITY_TYPE
        if not is_municipality:
            if self.parent_jurisdiction_code is not None:
                raise ValueError(
                    f"parent_jurisdiction_code must be null for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
                )
            if self.municipal_audit_decision is not None:
                raise ValueError(
                    f"municipal_audit_decision must be null for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
                )
            if self.municipal_portal_url is not None:
                raise ValueError(
                    f"municipal_portal_url must be null for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
                )
            return self

        if self.parent_jurisdiction_code is None:
            raise ValueError(
                f"parent_jurisdiction_code is required for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
            )
        if self.municipal_audit_decision is None:
            raise ValueError(
                f"municipal_audit_decision is required for {self.jurisdiction_type} row '{self.jurisdiction_code}'"
            )
        if self.municipal_audit_decision == "covered_by_parent" and self.municipal_portal_url is not None:
            raise ValueError(f"municipal_portal_url must be null for covered_by_parent row '{self.jurisdiction_code}'")
        if (
            self.municipal_audit_decision == "independent_target"
            and self.evidence_summary is not None
            and "browser-verified" in self.evidence_summary.lower()
            and not self.municipal_portal_url
        ):
            raise ValueError(
                f"municipal_portal_url is required for browser-verified independent_target row "
                f"'{self.jurisdiction_code}'"
            )
        return self


class CoverageRegistry(CoverageRegistryBaseModel):
    rows: list[CoverageRegistryRow]

    @model_validator(mode="after")
    def _validate_unique_jurisdiction_codes(self) -> "CoverageRegistry":
        duplicate_codes = collect_duplicate_jurisdiction_codes(self.rows)
        if duplicate_codes:
            details = "; ".join(
                f"{code} at row indexes {', '.join(str(index) for index in indexes)}"
                for code, indexes in sorted(duplicate_codes.items())
            )
            raise ValueError(f"Duplicate jurisdiction code(s): {details}")
        return self


def format_validation_errors(validation_error: ValidationError) -> str:
    formatted_errors: list[str] = []
    for error in validation_error.errors():
        location = ".".join(str(part) for part in error["loc"])
        if not location:
            location = "<root>"
        formatted_errors.append(f"{location}: {error['msg']}")
    return "; ".join(formatted_errors)


def collect_duplicate_jurisdiction_codes(rows: list[CoverageRegistryRow]) -> dict[str, list[int]]:
    code_to_indexes: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        code_to_indexes[row.jurisdiction_code].append(index)

    return {code: indexes for code, indexes in code_to_indexes.items() if len(indexes) > 1}


def load_registry_json(path: str | Path) -> object:
    registry_path = Path(path)
    try:
        return json.loads(registry_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Failed to read registry file at {registry_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Failed to parse registry JSON at {registry_path}: {error}") from error


def load_registry(path: str | Path) -> CoverageRegistry:
    registry_path = Path(path)
    raw_payload = load_registry_json(registry_path)

    try:
        return CoverageRegistry.model_validate(raw_payload)
    except ValidationError as error:
        raise ValueError(f"Invalid registry JSON at {registry_path}: {format_validation_errors(error)}") from error


def write_registry(path: str | Path, registry: CoverageRegistry) -> Path:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(f"{registry.model_dump_json(indent=2)}\n", encoding="utf-8")
    return registry_path
