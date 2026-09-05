"""Pure municipality owner-composition resolver for status projections.

Given a requested ``jurisdiction_code``, this resolves which coverage-registry and
lifecycle rows are canonical for that region, honoring the municipality-inheritance
branch owned by ``coverage-registry`` ``municipal_audit_decision`` (see
``docs/reference/specs/campaign-finance-region-lifecycle.md`` "Municipality inheritance").

Branch guarantees for Stages 2 and 3:

- ``non_municipality`` and ``independent_target`` — the region's own registry and
  lifecycle rows are canonical and required (``status_origin = direct``); a parent row
  is never substituted for a missing own row.
- ``covered_by_parent`` — the child registry row owns identity and local audit metadata
  (``origin = direct`` for those fields), while the parent's registry and lifecycle rows
  are canonical for inherited status output (``status_origin = inherited``). A child
  lifecycle row is optional and duplicate-only; when present it is checked against the
  parent lifecycle and any inherited-field disagreement refuses.

The resolver is a pure function over the already-typed registry/lifecycle containers.
It adds no second registry validator, loader, enum, or fact store; the typed loaders
own those. On any missing owner/join or cross-owner disagreement it returns the shared
scoped ``Refusal`` naming the canonical owner to correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from domains.campaign_finance.coverage.lifecycle import (
    ImplementedRegionLifecycleRegistry,
    ImplementedRegionLifecycleRow,
)
from domains.campaign_finance.coverage.registry import (
    CoverageRegistry,
    CoverageRegistryRow,
    coverage_parent_linkage_error,
)
from domains.campaign_finance.coverage.status.models import (
    OriginLiteral,
    Refusal,
    StatusProjectionModel,
    refuse,
)

MunicipalityBranchLiteral = Literal["non_municipality", "independent_target", "covered_by_parent"]

# Canonical owner names, shared by refusals here and by projection provenance in the
# views that compose this resolver. One spelling per owner across the status package.
COVERAGE_REGISTRY_OWNER = "coverage-registry"
LIFECYCLE_OWNER = "implemented-region-lifecycle"

# Child-identity lifecycle fields owned by the child's own coverage-registry row, never
# inherited from the parent: a covered-by-parent child lifecycle row correctly names the
# child, so these are excluded from the parent duplicate check.
_CHILD_IDENTITY_LIFECYCLE_FIELDS = frozenset({"jurisdiction_code", "name"})

# Inherited lifecycle output fields a child covered-by-parent row duplicates; each must
# equal the parent's. Derived as every lifecycle field except the child-identity ones.
_INHERITED_LIFECYCLE_FIELDS = tuple(
    name for name in ImplementedRegionLifecycleRow.model_fields if name not in _CHILD_IDENTITY_LIFECYCLE_FIELDS
)


class RegistryBranchSelection(StatusProjectionModel):
    """The coverage-registry owners selected for one region by the inheritance branch.

    This is the half of the resolution that carries no lifecycle requirement, so a caller
    projecting a non-implemented registry row (which has no lifecycle row of its own) can
    inherit a parent's public claim without acquiring an invalid lifecycle join.
    """

    jurisdiction_code: str
    branch: MunicipalityBranchLiteral
    status_origin: OriginLiteral
    identity_registry_row: CoverageRegistryRow
    status_registry_row: CoverageRegistryRow


class RegionOwnerResolution(RegistryBranchSelection):
    """A branch selection plus the lifecycle owners required of an implemented member."""

    status_lifecycle_row: ImplementedRegionLifecycleRow
    child_lifecycle_row: ImplementedRegionLifecycleRow | None = None


@dataclass(frozen=True)
class RegionOwnerIndex:
    """Code-keyed lookups over the registry/lifecycle owners, built once per view.

    A multi-region caller (``coverage-status`` resolves every implemented member) builds
    this once and resolves each region against it, instead of rebuilding both maps per
    region.
    """

    registry_by_code: dict[str, CoverageRegistryRow]
    lifecycle_by_code: dict[str, ImplementedRegionLifecycleRow]


def build_region_owner_index(
    coverage_registry: CoverageRegistry,
    lifecycle_registry: ImplementedRegionLifecycleRegistry,
) -> RegionOwnerIndex:
    """Build the code-keyed owner lookups once for reuse across many region resolutions."""

    return RegionOwnerIndex(
        registry_by_code={row.jurisdiction_code: row for row in coverage_registry.rows},
        lifecycle_by_code={row.jurisdiction_code: row for row in lifecycle_registry.rows},
    )


def resolve_region_owners(
    jurisdiction_code: str,
    *,
    coverage_registry: CoverageRegistry,
    lifecycle_registry: ImplementedRegionLifecycleRegistry,
) -> RegionOwnerResolution | Refusal:
    """Resolve the canonical registry/lifecycle owners for ``jurisdiction_code``.

    Thin single-region wrapper over :func:`resolve_region_owners_from_index`; a caller
    resolving many regions should build the index once and use that entry point.
    """

    index = build_region_owner_index(coverage_registry, lifecycle_registry)
    return resolve_region_owners_from_index(jurisdiction_code, index=index)


def resolve_region_owners_from_index(
    jurisdiction_code: str,
    *,
    index: RegionOwnerIndex,
) -> RegionOwnerResolution | Refusal:
    """Resolve the canonical owners for ``jurisdiction_code`` against a prebuilt index.

    The branch, origin, and registry owners come from the one registry-only selection;
    this adds the member-only lifecycle requirements and duplicate checks on top.
    """

    selection = select_registry_owners_from_index(jurisdiction_code, index=index)
    if isinstance(selection, Refusal):
        return selection
    return _require_lifecycle_owners(selection, index.lifecycle_by_code)


def select_registry_owners_from_index(
    jurisdiction_code: str,
    *,
    index: RegionOwnerIndex,
) -> RegistryBranchSelection | Refusal:
    """Select the canonical coverage-registry owners for ``jurisdiction_code``.

    Resolves the municipality-inheritance branch and nothing else: no lifecycle row is
    read or required, so this is valid for registry rows outside implemented membership.
    """

    identity_row = index.registry_by_code.get(jurisdiction_code)
    if identity_row is None:
        return refuse(
            scope=jurisdiction_code,
            reason=f"no coverage-registry row for '{jurisdiction_code}'",
            canonical_owner=COVERAGE_REGISTRY_OWNER,
        )

    linkage_error = coverage_parent_linkage_error(identity_row, index.registry_by_code)
    if linkage_error is not None:
        return refuse(
            scope=jurisdiction_code,
            reason=linkage_error,
            canonical_owner=COVERAGE_REGISTRY_OWNER,
        )

    decision = identity_row.municipal_audit_decision
    if decision == "covered_by_parent":
        return _select_parent_registry_owner(identity_row, index.registry_by_code)

    branch: MunicipalityBranchLiteral = "independent_target" if decision == "independent_target" else "non_municipality"
    return RegistryBranchSelection(
        jurisdiction_code=identity_row.jurisdiction_code,
        branch=branch,
        status_origin="direct",
        identity_registry_row=identity_row,
        status_registry_row=identity_row,
    )


def _select_parent_registry_owner(
    child_row: CoverageRegistryRow,
    registry_by_code: dict[str, CoverageRegistryRow],
) -> RegistryBranchSelection | Refusal:
    code = child_row.jurisdiction_code
    parent_code = child_row.parent_jurisdiction_code

    parent_row = registry_by_code.get(parent_code) if parent_code is not None else None
    if parent_row is None:
        return refuse(
            scope=code,
            reason=(
                f"covered_by_parent '{code}' has no resolvable parent coverage-registry row "
                f"for parent_jurisdiction_code '{parent_code}'"
            ),
            canonical_owner=COVERAGE_REGISTRY_OWNER,
        )

    if parent_row.municipal_audit_decision == "covered_by_parent":
        return refuse(
            scope=code,
            reason=(
                f"covered_by_parent '{code}' resolves to parent '{parent_row.jurisdiction_code}' "
                f"which is itself covered_by_parent and is not a status owner"
            ),
            canonical_owner=COVERAGE_REGISTRY_OWNER,
        )

    return RegistryBranchSelection(
        jurisdiction_code=code,
        branch="covered_by_parent",
        status_origin="inherited",
        identity_registry_row=child_row,
        status_registry_row=parent_row,
    )


def _require_lifecycle_owners(
    selection: RegistryBranchSelection,
    lifecycle_by_code: dict[str, ImplementedRegionLifecycleRow],
) -> RegionOwnerResolution | Refusal:
    """Add the branch's required lifecycle owners to an already-selected registry branch."""

    code = selection.jurisdiction_code
    status_row = selection.status_registry_row
    inherits_from_parent = selection.branch == "covered_by_parent"

    status_lifecycle = lifecycle_by_code.get(status_row.jurisdiction_code)
    if status_lifecycle is None:
        missing_reason = (
            f"covered_by_parent '{code}' has no parent implemented-region-lifecycle row "
            f"for '{status_row.jurisdiction_code}'"
            if inherits_from_parent
            else f"no implemented-region-lifecycle row for '{code}'"
        )
        return refuse(scope=code, reason=missing_reason, canonical_owner=LIFECYCLE_OWNER)

    mismatch = _check_registry_lifecycle_agreement(code, status_row, status_lifecycle)
    if mismatch is not None:
        return mismatch

    child_lifecycle = lifecycle_by_code.get(code) if inherits_from_parent else None
    if child_lifecycle is not None:
        duplicate_mismatch = _check_child_parent_lifecycle_agreement(code, child_lifecycle, status_lifecycle)
        if duplicate_mismatch is not None:
            return duplicate_mismatch

    return RegionOwnerResolution(
        jurisdiction_code=code,
        branch=selection.branch,
        status_origin=selection.status_origin,
        identity_registry_row=selection.identity_registry_row,
        status_registry_row=status_row,
        status_lifecycle_row=status_lifecycle,
        child_lifecycle_row=child_lifecycle,
    )


def _check_registry_lifecycle_agreement(
    scope: str,
    registry_row: CoverageRegistryRow,
    lifecycle_row: ImplementedRegionLifecycleRow,
) -> Refusal | None:
    """Refuse when the duplicate lifecycle name / public_claim_status disagrees with its owner."""
    if lifecycle_row.name != registry_row.name:
        return refuse(
            scope=scope,
            reason=(
                f"lifecycle name '{lifecycle_row.name}' disagrees with coverage-registry name "
                f"'{registry_row.name}' for '{registry_row.jurisdiction_code}'"
            ),
            canonical_owner=COVERAGE_REGISTRY_OWNER,
        )
    if lifecycle_row.public_claim_status != registry_row.tier:
        return refuse(
            scope=scope,
            reason=(
                f"lifecycle public_claim_status '{lifecycle_row.public_claim_status}' disagrees with "
                f"coverage-registry tier '{registry_row.tier}' for '{registry_row.jurisdiction_code}'"
            ),
            canonical_owner=COVERAGE_REGISTRY_OWNER,
        )
    return None


def _check_child_parent_lifecycle_agreement(
    scope: str,
    child_lifecycle: ImplementedRegionLifecycleRow,
    parent_lifecycle: ImplementedRegionLifecycleRow,
) -> Refusal | None:
    """Refuse when a present child lifecycle duplicate disagrees with the parent's owner value."""
    for field_name in _INHERITED_LIFECYCLE_FIELDS:
        child_value = getattr(child_lifecycle, field_name)
        parent_value = getattr(parent_lifecycle, field_name)
        if child_value != parent_value:
            return refuse(
                scope=scope,
                reason=(
                    f"child lifecycle {field_name} '{child_value}' disagrees with parent "
                    f"'{parent_lifecycle.jurisdiction_code}' lifecycle value '{parent_value}'"
                ),
                canonical_owner=LIFECYCLE_OWNER,
            )
    return None
