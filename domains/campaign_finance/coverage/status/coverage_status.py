"""The read-only ``coverage-status`` portfolio view.

Projects the coverage-registry public-claim set against derived implemented membership
and the lifecycle snapshot, resolving municipality inheritance through the shared
municipality owner (see ``docs/reference/specs/campaign-finance-region-lifecycle.md``
"``coverage-status`` — portfolio + municipality inheritance").

It owns no fact. Membership comes from ``derive_implemented_jurisdiction_codes()``,
public claims from the coverage registry, and the portfolio snapshot time from the
lifecycle registry; every published fact is wrapped in the shared projection envelope.
A whole-view input failure (an unreadable registry or an unreadable membership
derivation) refuses the invocation, while a per-region defect becomes one scoped
``Refusal`` inside ``regions`` — the view's only error surface.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Final, Literal, Union

from pydantic import Field

from domains.campaign_finance.coverage.lifecycle import (
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
    ImplementedRegionLifecycleRegistry,
    load_lifecycle,
)
from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    CoverageRegistryRow,
    load_registry,
)
from domains.campaign_finance.coverage.render_summary import derive_implemented_jurisdiction_codes
from domains.campaign_finance.coverage.status.models import (
    NOT_APPLICABLE,
    FieldProvenance,
    OriginLiteral,
    ProjectedField,
    ProjectionOutcome,
    ProjectionReport,
    Refusal,
    StatusProjectionModel,
    UnknownFact,
    refuse,
)
from domains.campaign_finance.coverage.status.registry_fields import (
    EVIDENCE_DATE_ABSENT_REASON,
    project_evidence_dated_field,
    project_municipality_audit_claim,
    registry_provenance,
    municipality_disposition_value,
)
from domains.campaign_finance.coverage.status.municipality import (
    LIFECYCLE_OWNER,
    RegionOwnerIndex,
    RegistryBranchSelection,
    build_region_owner_index,
    resolve_region_owners_from_index,
    select_registry_owners_from_index,
)

MEMBERSHIP_OWNER: Final[str] = "derive_implemented_jurisdiction_codes"

_LIFECYCLE_REGISTRY_READ_PATH: Final[str] = "lifecycle.py::ImplementedRegionLifecycleRegistry"
_MEMBERSHIP_READ_PATH: Final[str] = "render_summary.py::derive_implemented_jurisdiction_codes"

_MEMBERSHIP_PROVENANCE: Final[FieldProvenance] = FieldProvenance(
    owner=MEMBERSHIP_OWNER,
    read_path=_MEMBERSHIP_READ_PATH,
    origin="direct",
)
_LIFECYCLE_SNAPSHOT_PROVENANCE: Final[FieldProvenance] = FieldProvenance(
    owner=LIFECYCLE_OWNER,
    read_path=_LIFECYCLE_REGISTRY_READ_PATH,
    origin="direct",
)

# A conditional fact is present with provenance or absent with a reason; it is never a
# refusal, because a defective region refuses as a whole row instead.
ConditionalOutcome = Annotated[Union[ProjectedField, UnknownFact], Field(discriminator="status")]


class CoverageStatusRegion(StatusProjectionModel):
    """One successfully projected portfolio row."""

    status: Literal["region"] = "region"
    jurisdiction_code: ProjectedField
    implemented: ProjectedField
    public_tier: ProjectedField
    tier_evidence_at: ConditionalOutcome
    municipality_disposition: ProjectedField
    municipality_audit_claim: ProjectedField


# One row per code: either the projected region or the scoped refusal that replaced it.
# This union is the view's sole error surface; there is no parallel refusals collection.
CoverageStatusRegionEntry = Annotated[Union[CoverageStatusRegion, Refusal], Field(discriminator="status")]


class CoverageStatusReport(ProjectionReport):
    """The full portfolio report: membership denominator, snapshot time, and rows."""

    implemented_membership: ProjectionOutcome
    portfolio_snapshot_at: ProjectionOutcome
    regions: list[CoverageStatusRegionEntry]


def build_coverage_status_report(
    *,
    coverage_registry: CoverageRegistry,
    lifecycle_registry: ImplementedRegionLifecycleRegistry,
    implemented_membership: set[str],
    calculated_at: datetime,
) -> CoverageStatusReport:
    """Project the portfolio from already-typed owners at one report time.

    Pure: it loads nothing and reads no clock, so a caller supplies the canonical
    registries, the derived membership set, and the UTC report time.
    """

    envelope = ProjectionReport(calculated_at=calculated_at)
    index = build_region_owner_index(coverage_registry, lifecycle_registry)
    portfolio_codes = set(index.registry_by_code) | set(implemented_membership) | set(index.lifecycle_by_code)
    return CoverageStatusReport(
        calculated_at=envelope.calculated_at,
        implemented_membership=envelope.project_field(
            value=sorted(implemented_membership),
            provenance=_MEMBERSHIP_PROVENANCE,
            source_observed_at=NOT_APPLICABLE,
        ),
        portfolio_snapshot_at=envelope.project_field(
            value=lifecycle_registry.updated_at,
            provenance=_LIFECYCLE_SNAPSHOT_PROVENANCE,
            source_observed_at=lifecycle_registry.updated_at,
        ),
        regions=[
            _project_region(envelope, code, index=index, implemented_membership=implemented_membership)
            for code in sorted(portfolio_codes)
        ],
    )


def _project_region(
    report: ProjectionReport,
    jurisdiction_code: str,
    *,
    index: RegionOwnerIndex,
    implemented_membership: set[str],
) -> CoverageStatusRegionEntry:
    """Project one portfolio code, or return the scoped refusal that replaces its row."""

    implemented = jurisdiction_code in implemented_membership
    if not implemented and jurisdiction_code in index.lifecycle_by_code:
        return refuse(
            scope=jurisdiction_code,
            reason=f"implemented-region-lifecycle row for '{jurisdiction_code}' is outside derived implemented "
            "membership",
            canonical_owner=MEMBERSHIP_OWNER,
        )

    # A member must satisfy its branch's lifecycle join; a non-member has no lifecycle
    # requirement but still resolves its registry branch so inherited claims stay correct.
    selection = (
        resolve_region_owners_from_index(jurisdiction_code, index=index)
        if implemented
        else select_registry_owners_from_index(jurisdiction_code, index=index)
    )
    if isinstance(selection, Refusal):
        return selection
    return _project_region_row(report, selection, implemented=implemented)


def _project_region_row(
    report: ProjectionReport,
    selection: RegistryBranchSelection,
    *,
    implemented: bool,
) -> CoverageStatusRegion:
    identity_row = selection.identity_registry_row
    status_row = selection.status_registry_row
    claim_origin = selection.status_origin
    return CoverageStatusRegion(
        jurisdiction_code=report.project_field(
            value=identity_row.jurisdiction_code,
            provenance=registry_provenance("direct"),
            source_observed_at=NOT_APPLICABLE,
        ),
        implemented=report.project_field(
            value=implemented,
            provenance=_MEMBERSHIP_PROVENANCE,
            source_observed_at=NOT_APPLICABLE,
        ),
        public_tier=project_evidence_dated_field(
            report,
            value=status_row.tier,
            origin=claim_origin,
            evidence_date=status_row.evidence_date,
        ),
        tier_evidence_at=_project_tier_evidence_at(report, status_row, claim_origin),
        municipality_disposition=report.project_field(
            value=municipality_disposition_value(identity_row),
            provenance=registry_provenance("direct"),
            source_observed_at=NOT_APPLICABLE,
        ),
        municipality_audit_claim=project_municipality_audit_claim(report, identity_row),
    )


def _project_tier_evidence_at(
    report: ProjectionReport,
    status_row: CoverageRegistryRow,
    origin: OriginLiteral,
) -> ConditionalOutcome:
    """Project the observation time of ``public_tier``; absent is ``UNKNOWN``, not a refusal."""

    if status_row.evidence_date is None:
        return UnknownFact(reason=EVIDENCE_DATE_ABSENT_REASON)
    return report.project_field(
        value=status_row.evidence_date,
        provenance=registry_provenance(origin),
        source_observed_at=status_row.evidence_date,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the coverage-status command."""

    parser = argparse.ArgumentParser(description="Project the read-only coverage-status portfolio view as JSON")
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="Input path for coverage registry JSON",
    )
    parser.add_argument(
        "--lifecycle-path",
        type=Path,
        default=DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
        help="Input path for implemented-region lifecycle JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: load the canonical owners and print one coverage-status report."""

    args = _build_argument_parser().parse_args(argv)
    try:
        coverage_registry = load_registry(args.registry_path)
        lifecycle_registry = load_lifecycle(args.lifecycle_path)
        implemented_membership = derive_implemented_jurisdiction_codes()
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    report = build_coverage_status_report(
        coverage_registry=coverage_registry,
        lifecycle_registry=lifecycle_registry,
        implemented_membership=implemented_membership,
        calculated_at=datetime.now(timezone.utc),
    )
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
