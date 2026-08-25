"""Shared coverage-registry field projectors for read-only status views."""

from __future__ import annotations

from datetime import date
from typing import Final

from domains.campaign_finance.coverage.registry import CoverageRegistryRow
from domains.campaign_finance.coverage.status.models import (
    NOT_APPLICABLE,
    UNKNOWN,
    FieldProvenance,
    JsonSerializableValue,
    OriginLiteral,
    ProjectedField,
    ProjectionReport,
)
from domains.campaign_finance.coverage.status.municipality import COVERAGE_REGISTRY_OWNER

REGISTRY_ROW_READ_PATH: Final[str] = "registry.py::CoverageRegistryRow"
EVIDENCE_DATE_ABSENT_REASON: Final[str] = "coverage-registry evidence_date absent"

_MUNICIPALITY_AUDIT_CLAIM_FIELDS: Final[tuple[str, ...]] = (
    "tier",
    "evidence_summary",
    "operational_reason",
    "next_action",
    "evidence_date",
)


def registry_provenance(origin: OriginLiteral) -> FieldProvenance:
    return FieldProvenance(owner=COVERAGE_REGISTRY_OWNER, read_path=REGISTRY_ROW_READ_PATH, origin=origin)


def project_evidence_dated_field(
    report: ProjectionReport,
    *,
    value: JsonSerializableValue,
    origin: OriginLiteral,
    evidence_date: date | None,
) -> ProjectedField:
    """Project a coverage-registry claim observed at its row's ``evidence_date``."""

    provenance = registry_provenance(origin)
    if evidence_date is not None:
        return report.project_field(value=value, provenance=provenance, source_observed_at=evidence_date)
    return ProjectedField(
        value=value,
        owner=provenance.owner,
        read_path=provenance.read_path,
        origin=provenance.origin,
        execution_origin=provenance.execution_origin,
        source_observed_at=UNKNOWN,
        age=UNKNOWN,
        observation_unknown_reason=EVIDENCE_DATE_ABSENT_REASON,
    )


def municipality_disposition_value(identity_row: CoverageRegistryRow) -> JsonSerializableValue:
    """Report the row's own municipality disposition, or that it carries none."""

    if identity_row.municipal_audit_decision is None:
        return NOT_APPLICABLE
    return {
        "municipal_audit_decision": identity_row.municipal_audit_decision,
        "parent_jurisdiction_code": identity_row.parent_jurisdiction_code,
    }


def project_municipality_audit_claim(report: ProjectionReport, identity_row: CoverageRegistryRow) -> ProjectedField:
    """Project the child row's local audit claim or an applicability null."""

    if identity_row.municipal_audit_decision != "covered_by_parent":
        return report.project_field(
            value=None,
            provenance=registry_provenance("direct"),
            source_observed_at=NOT_APPLICABLE,
        )

    claim: dict[str, JsonSerializableValue] = {"source_jurisdiction_code": identity_row.jurisdiction_code}
    claim.update({name: getattr(identity_row, name) for name in _MUNICIPALITY_AUDIT_CLAIM_FIELDS})
    return project_evidence_dated_field(
        report,
        value=claim,
        origin="direct",
        evidence_date=identity_row.evidence_date,
    )
