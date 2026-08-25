"""Red-first tests for the pure municipality owner-composition resolver."""

from __future__ import annotations

from datetime import date

from domains.campaign_finance.coverage.lifecycle import (
    ImplementedRegionLifecycleRegistry,
    ImplementedRegionLifecycleRow,
)
from domains.campaign_finance.coverage.registry import CoverageRegistry, CoverageRegistryRow
from domains.campaign_finance.coverage.status.models import Refusal
from domains.campaign_finance.coverage.status.municipality import (
    RegionOwnerResolution,
    RegistryBranchSelection,
    build_region_owner_index,
    resolve_region_owners,
    resolve_region_owners_from_index,
    select_registry_owners_from_index,
)


def _registry_row(
    code: str,
    name: str,
    **overrides: object,
) -> CoverageRegistryRow:
    values: dict[str, object] = {
        "jurisdiction_code": code,
        "name": name,
        "jurisdiction_type": "state",
        "best_update_frequency": "daily",
        "best_last_verified_working": None,
        "covers_sub_jurisdictions": False,
        "source_count": 1,
        "source_names": ["Source"],
        "runner_wired": True,
        "tier": "launch-support candidate",
        "evidence_summary": None,
        "operational_reason": None,
        "next_action": None,
        "evidence_date": None,
        "parent_jurisdiction_code": None,
        "municipal_audit_decision": None,
        "municipal_portal_url": None,
    }
    values.update(overrides)
    return CoverageRegistryRow.model_validate(values)


def _lifecycle_row(
    code: str,
    name: str,
    *,
    public_claim_status: str = "launch-support candidate",
    main_blocker: str = "Example blocker",
    acquisition_pattern: str = "bulk_file",
) -> ImplementedRegionLifecycleRow:
    return ImplementedRegionLifecycleRow.model_validate(
        {
            "jurisdiction_code": code,
            "name": name,
            "acquisition_pattern": acquisition_pattern,
            "discovery_maturity": "researched",
            "source_contract_maturity": "encoded",
            "legal_filing_semantics_maturity": "partial",
            "implementation_maturity": "fixture_tested",
            "operational_maturity": "manual_only",
            "public_claim_status": public_claim_status,
            "completeness_intelligence_maturity": "not_started",
            "civics_candidacy_status": "not_started",
            "main_blocker": main_blocker,
        }
    )


def _registry(*rows: CoverageRegistryRow) -> CoverageRegistry:
    return CoverageRegistry(rows=list(rows))


def _lifecycle(*rows: ImplementedRegionLifecycleRow) -> ImplementedRegionLifecycleRegistry:
    return ImplementedRegionLifecycleRegistry(updated_at=date(2026, 8, 22), rows=list(rows))


# --- successful resolutions ---------------------------------------------------


def test_non_municipality_resolves_to_own_rows_direct() -> None:
    registry = _registry(_registry_row("CA", "California"))
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))

    resolution = resolve_region_owners("CA", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(resolution, RegionOwnerResolution)
    assert resolution.branch == "non_municipality"
    assert resolution.status_origin == "direct"
    assert resolution.identity_registry_row.jurisdiction_code == "CA"
    assert resolution.status_registry_row.jurisdiction_code == "CA"
    assert resolution.status_lifecycle_row.jurisdiction_code == "CA"
    assert resolution.child_lifecycle_row is None


def test_independent_target_resolves_to_child_rows_never_parent() -> None:
    child = _registry_row(
        "LA",
        "Los Angeles",
        jurisdiction_type="municipality",
        municipal_audit_decision="independent_target",
        parent_jurisdiction_code="CA",
        tier="freshness-limited",
    )
    parent = _registry_row("CA", "California", tier="launch-support candidate")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(
        _lifecycle_row("LA", "Los Angeles", public_claim_status="freshness-limited"),
        _lifecycle_row("CA", "California", public_claim_status="launch-support candidate"),
    )

    resolution = resolve_region_owners("LA", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(resolution, RegionOwnerResolution)
    assert resolution.branch == "independent_target"
    assert resolution.status_origin == "direct"
    assert resolution.identity_registry_row.jurisdiction_code == "LA"
    assert resolution.status_registry_row.jurisdiction_code == "LA"
    assert resolution.status_lifecycle_row.jurisdiction_code == "LA"
    assert resolution.child_lifecycle_row is None


def test_covered_by_parent_resolves_child_identity_with_parent_status_owners_inherited() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
        tier="implemented but unproven",
        evidence_summary="child audit note",
        evidence_date=date(2026, 7, 1),
    )
    parent = _registry_row("CA", "California", tier="launch-support candidate")
    registry = _registry(child, parent)
    # The child lifecycle row correctly names the child; ``name`` is child identity owned
    # by the child coverage-registry row, not an inherited lifecycle field, so a child
    # name that differs from the parent's must NOT refuse.
    child_lifecycle = _lifecycle_row("SF", "San Francisco")
    lifecycle = _lifecycle(child_lifecycle, _lifecycle_row("CA", "California"))

    resolution = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(resolution, RegionOwnerResolution)
    assert resolution.branch == "covered_by_parent"
    assert resolution.status_origin == "inherited"
    assert resolution.identity_registry_row.jurisdiction_code == "SF"
    assert resolution.status_registry_row.jurisdiction_code == "CA"
    assert resolution.status_lifecycle_row.jurisdiction_code == "CA"
    assert resolution.child_lifecycle_row is not None
    assert resolution.child_lifecycle_row.jurisdiction_code == "SF"
    assert resolution.child_lifecycle_row.name == "San Francisco"


def test_covered_by_parent_without_child_lifecycle_row_still_resolves() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))

    resolution = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(resolution, RegionOwnerResolution)
    assert resolution.child_lifecycle_row is None


def test_covered_by_parent_child_audit_metadata_may_differ_from_parent_public_claim() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
        tier="deferred/blocked",
        evidence_summary="child audit differs",
        next_action="child next action",
        evidence_date=date(2026, 6, 1),
    )
    parent = _registry_row("CA", "California", tier="launch-support candidate", next_action="parent next action")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))

    resolution = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(resolution, RegionOwnerResolution)
    assert resolution.identity_registry_row.tier == "deferred/blocked"
    assert resolution.status_registry_row.tier == "launch-support candidate"


# --- identity / join refusals -------------------------------------------------


def test_missing_target_registry_row_refuses_naming_coverage_registry() -> None:
    registry = _registry(_registry_row("CA", "California"))
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))

    result = resolve_region_owners("NV", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result == Refusal(
        scope="NV",
        reason="no coverage-registry row for 'NV'",
        canonical_owner="coverage-registry",
    )


def test_covered_by_parent_missing_parent_registry_row_refuses() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    registry = _registry(child)
    lifecycle = _lifecycle(_lifecycle_row("SF", "San Francisco"))

    result = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result == Refusal(
        scope="SF",
        reason=(
            "covered_by_parent 'SF' has no resolvable parent coverage-registry row for parent_jurisdiction_code 'CA'"
        ),
        canonical_owner="coverage-registry",
    )


def test_covered_by_parent_parent_that_is_itself_covered_by_parent_refuses() -> None:
    # A covered_by_parent chain (child -> covered_by_parent parent -> grandparent) must
    # refuse: an intermediate covered_by_parent row is not itself a status owner, so it
    # may not be projected as the canonical status registry/lifecycle owner.
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="LA",
    )
    intermediate = _registry_row(
        "LA",
        "Los Angeles",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    grandparent = _registry_row("CA", "California")
    registry = _registry(child, intermediate, grandparent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"), _lifecycle_row("LA", "Los Angeles"))

    result = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result.scope == "SF"
    assert result.canonical_owner == "coverage-registry"
    assert "LA" in result.reason


def test_covered_by_parent_missing_parent_lifecycle_row_refuses() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("SF", "San Francisco"))

    result = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result == Refusal(
        scope="SF",
        reason="covered_by_parent 'SF' has no parent implemented-region-lifecycle row for 'CA'",
        canonical_owner="implemented-region-lifecycle",
    )


def test_non_municipality_missing_own_lifecycle_row_refuses() -> None:
    registry = _registry(_registry_row("CA", "California"))
    lifecycle = _lifecycle()

    result = resolve_region_owners("CA", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result == Refusal(
        scope="CA",
        reason="no implemented-region-lifecycle row for 'CA'",
        canonical_owner="implemented-region-lifecycle",
    )


def test_independent_target_missing_own_lifecycle_row_refuses_without_parent_fallback() -> None:
    child = _registry_row(
        "LA",
        "Los Angeles",
        jurisdiction_type="municipality",
        municipal_audit_decision="independent_target",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))

    result = resolve_region_owners("LA", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result == Refusal(
        scope="LA",
        reason="no implemented-region-lifecycle row for 'LA'",
        canonical_owner="implemented-region-lifecycle",
    )


# --- duplicate-mismatch refusals ----------------------------------------------


def test_direct_lifecycle_name_mismatch_refuses_favoring_coverage_registry() -> None:
    registry = _registry(_registry_row("CA", "California"))
    lifecycle = _lifecycle(_lifecycle_row("CA", "Calfornia typo"))

    result = resolve_region_owners("CA", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result.canonical_owner == "coverage-registry"


def test_direct_lifecycle_public_claim_mismatch_refuses_favoring_coverage_registry() -> None:
    registry = _registry(_registry_row("CA", "California", tier="launch-support candidate"))
    lifecycle = _lifecycle(_lifecycle_row("CA", "California", public_claim_status="deferred/blocked"))

    result = resolve_region_owners("CA", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result.canonical_owner == "coverage-registry"


def test_covered_by_parent_parent_lifecycle_tier_mismatch_refuses_favoring_coverage_registry() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California", tier="launch-support candidate")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California", public_claim_status="deferred/blocked"))

    result = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result.canonical_owner == "coverage-registry"


def test_covered_by_parent_child_lifecycle_mismatch_refuses_favoring_parent_lifecycle() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California")
    registry = _registry(child, parent)
    # Child lifecycle names the child correctly but disagrees with the parent on a genuine
    # inherited lifecycle field (main_blocker); that inherited-field disagreement refuses.
    child_lifecycle = _lifecycle_row("SF", "San Francisco", main_blocker="different child blocker")
    parent_lifecycle = _lifecycle_row("CA", "California", main_blocker="Example blocker")
    lifecycle = _lifecycle(child_lifecycle, parent_lifecycle)

    result = resolve_region_owners("SF", coverage_registry=registry, lifecycle_registry=lifecycle)

    assert isinstance(result, Refusal)
    assert result.canonical_owner == "implemented-region-lifecycle"
    assert "main_blocker" in result.reason
    assert "CA" in result.reason


# --- prebuilt-index seam ------------------------------------------------------


def test_prebuilt_index_resolves_many_regions_matching_single_region_wrapper() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))

    index = build_region_owner_index(registry, lifecycle)
    for code in ("CA", "SF"):
        from_index = resolve_region_owners_from_index(code, index=index)
        from_wrapper = resolve_region_owners(code, coverage_registry=registry, lifecycle_registry=lifecycle)
        assert isinstance(from_index, RegionOwnerResolution)
        assert from_index == from_wrapper


# --- registry-only branch selection -------------------------------------------


def test_registry_only_selection_direct_row_selects_itself_without_lifecycle() -> None:
    registry = _registry(_registry_row("CA", "California"))
    index = build_region_owner_index(registry, _lifecycle())

    selection = select_registry_owners_from_index("CA", index=index)

    assert isinstance(selection, RegistryBranchSelection)
    assert selection == RegistryBranchSelection(
        jurisdiction_code="CA",
        branch="non_municipality",
        status_origin="direct",
        identity_registry_row=registry.rows[0],
        status_registry_row=registry.rows[0],
    )


def test_registry_only_selection_independent_target_selects_itself_without_lifecycle() -> None:
    child = _registry_row(
        "LA",
        "Los Angeles",
        jurisdiction_type="municipality",
        municipal_audit_decision="independent_target",
        parent_jurisdiction_code="CA",
        tier="freshness-limited",
    )
    parent = _registry_row("CA", "California")
    index = build_region_owner_index(_registry(child, parent), _lifecycle())

    selection = select_registry_owners_from_index("LA", index=index)

    assert isinstance(selection, RegistryBranchSelection)
    assert selection.branch == "independent_target"
    assert selection.status_origin == "direct"
    assert selection.identity_registry_row is child
    assert selection.status_registry_row is child


def test_registry_only_selection_covered_by_parent_inherits_parent_without_any_lifecycle() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
        tier="deferred/blocked",
    )
    parent = _registry_row("CA", "California", tier="launch-support candidate")
    index = build_region_owner_index(_registry(child, parent), _lifecycle())

    selection = select_registry_owners_from_index("SF", index=index)

    assert isinstance(selection, RegistryBranchSelection)
    assert selection.branch == "covered_by_parent"
    assert selection.status_origin == "inherited"
    assert selection.identity_registry_row is child
    assert selection.status_registry_row is parent


def test_registry_only_selection_missing_row_refuses_naming_coverage_registry() -> None:
    index = build_region_owner_index(_registry(_registry_row("CA", "California")), _lifecycle())

    result = select_registry_owners_from_index("NV", index=index)

    assert result == Refusal(
        scope="NV",
        reason="no coverage-registry row for 'NV'",
        canonical_owner="coverage-registry",
    )


def test_registry_only_selection_missing_parent_refuses_naming_coverage_registry() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    index = build_region_owner_index(_registry(child), _lifecycle())

    result = select_registry_owners_from_index("SF", index=index)

    assert result == Refusal(
        scope="SF",
        reason=(
            "covered_by_parent 'SF' has no resolvable parent coverage-registry row for parent_jurisdiction_code 'CA'"
        ),
        canonical_owner="coverage-registry",
    )


def test_registry_only_selection_self_inheriting_parent_refuses_naming_coverage_registry() -> None:
    self_inheriting = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="SF",
    )
    index = build_region_owner_index(_registry(self_inheriting), _lifecycle())

    result = select_registry_owners_from_index("SF", index=index)

    assert result == Refusal(
        scope="SF",
        reason=(
            "covered_by_parent 'SF' resolves to parent 'SF' which is itself covered_by_parent and is not a status owner"
        ),
        canonical_owner="coverage-registry",
    )


def test_full_resolution_reuses_the_registry_only_branch_selection() -> None:
    child = _registry_row(
        "SF",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
    )
    parent = _registry_row("CA", "California")
    registry = _registry(child, parent)
    lifecycle = _lifecycle(_lifecycle_row("CA", "California"))
    index = build_region_owner_index(registry, lifecycle)

    for code in ("CA", "SF"):
        resolution = resolve_region_owners_from_index(code, index=index)
        selection = select_registry_owners_from_index(code, index=index)
        assert isinstance(resolution, RegionOwnerResolution)
        assert isinstance(selection, RegistryBranchSelection)
        # The full resolver adds lifecycle owners on top of the one branch selection; it
        # must not re-decide the branch, origin, or registry owners itself.
        assert isinstance(resolution, RegistryBranchSelection)
        assert selection.model_dump() == {
            field: resolution.model_dump()[field] for field in RegistryBranchSelection.model_fields
        }
