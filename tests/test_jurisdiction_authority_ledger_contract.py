from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.coverage.lifecycle import load_lifecycle
from domains.campaign_finance.coverage.registry import load_registry
from domains.campaign_finance.coverage.status.models import Refusal
from domains.campaign_finance.coverage.status.municipality import (
    RegionOwnerResolution,
    resolve_region_owners,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = REPO_ROOT / "decisions" / "2026-08-27_jurisdiction_identity_boundaries_and_public_region_routing.md"
LIFECYCLE_PATH = REPO_ROOT / "docs" / "reference" / "specs" / "campaign-finance-region-lifecycle.md"
DISCOVERY_PATH = REPO_ROOT / "docs" / "reference" / "specs" / "jurisdiction-discovery.md"
AUDIT_PATH = REPO_ROOT / "docs" / "reference" / "research" / "coverage-audit-contract.md"
SSOT_PATH = REPO_ROOT / "docs" / "reference" / "ssot-registry.md"
REGISTRY_PATH = REPO_ROOT / "docs" / "reference" / "research" / "coverage-registry.json"
MASTER_PATH = REPO_ROOT / "docs" / "reference" / "research" / "jurisdiction-master.csv"
GEOGRAPHY_SCHEMA_PATH = REPO_ROOT / "core" / "schema" / "jurisdiction.sql"
GAP_PATH = REPO_ROOT / "docs" / "live-state" / "2026_08_28_jurisdiction_authority_ledger_gap_assessment.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_docs_define_the_general_filing_authority_relation_contract() -> None:
    adr = _read(ADR_PATH)
    lifecycle = _read(LIFECYCLE_PATH)
    ssot = _read(SSOT_PATH)
    adr_words = " ".join(adr.split())
    lifecycle_words = " ".join(lifecycle.split())

    for relation in (
        "inherited_from_parent",
        "independent",
        "partitioned_or_overlapping",
        "unresolved_refuse",
    ):
        assert relation in adr
        assert relation in lifecycle

    assert "filing-authority decision source of truth" in adr_words
    assert "filing-authority decision source of truth" in lifecycle_words
    assert "Filing-authority decision source of truth" in ssot
    assert "bootstrap evidence debt" in lifecycle
    assert "jurisdiction-master.csv" in adr and "derived" in adr
    assert MASTER_PATH.is_file()


def test_geography_owner_remains_separate_from_filing_authority() -> None:
    sql = _read(GEOGRAPHY_SCHEMA_PATH)
    adr = _read(ADR_PATH)

    assert "parent_id" in sql
    assert "geometry" in sql
    assert "filing_authority" not in sql
    assert "`core.jurisdiction.parent_id` alone owns containment" in adr
    assert "County or special-district geography never authorizes finance" in adr


def test_autonomous_docs_have_no_stale_routine_approval_or_planned_registry_gate() -> None:
    discovery = _read(DISCOVERY_PATH).lower()
    lifecycle = _read(LIFECYCLE_PATH).lower()
    audit = _read(AUDIT_PATH).lower()
    discovery_words = " ".join(discovery.split())

    assert "human must approve" not in discovery
    assert "humans reviewing and approving" not in discovery
    assert "human-first" not in lifecycle
    assert "human-maintained editorial judgment" not in lifecycle
    assert "future registry" not in audit
    assert "routine discovery, config work, and bounded verification have no human approval gate" in discovery_words


def test_legacy_parent_boolean_bootstrap_evidence_is_explicit_debt() -> None:
    registry = load_registry(REGISTRY_PATH)
    audit = _read(AUDIT_PATH)
    gap = _read(GAP_PATH)
    legacy_rows = [
        row
        for row in registry.rows
        if row.municipal_audit_decision == "covered_by_parent"
        and "so this municipality inherits parent authority" in (row.evidence_summary or "")
    ]

    assert len(legacy_rows) == 54
    assert "54 current `covered_by_parent` summaries" in audit
    assert "Fifty-four legacy `covered_by_parent` rows" in gap


def test_nyc_direct_route_compatibility_stays_separate_from_typed_overlap() -> None:
    registry = load_registry(REGISTRY_PATH)
    lifecycle = load_lifecycle(LIFECYCLE_PATH.parent.parent / "research" / "implemented-region-lifecycle.json")
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}

    state = rows_by_code["NY"]
    city = rows_by_code["NY_NEW_YORK"]
    assert state.jurisdiction_type == "state"
    assert state.covers_sub_jurisdictions is True
    assert city.jurisdiction_type == "municipality"
    assert city.name == "New York City"
    assert city.parent_jurisdiction_code == "NY"
    assert city.municipal_audit_decision == "independent_target"
    assert city.authority_relation.relation == "partitioned_overlapping"

    resolution = resolve_region_owners(
        "NY_NEW_YORK",
        coverage_registry=registry,
        lifecycle_registry=lifecycle,
    )
    assert not isinstance(resolution, Refusal)
    assert isinstance(resolution, RegionOwnerResolution)
    assert resolution.branch == "independent_target"
    assert resolution.status_origin == "direct"
    assert resolution.identity_registry_row.jurisdiction_code == "NY_NEW_YORK"
    assert resolution.status_registry_row.jurisdiction_code == "NY_NEW_YORK"
    assert resolution.status_lifecycle_row.jurisdiction_code == "NY_NEW_YORK"


def test_seattle_parent_route_compatibility_stays_separate_from_typed_overlap() -> None:
    registry = load_registry(REGISTRY_PATH)
    lifecycle = load_lifecycle(LIFECYCLE_PATH.parent.parent / "research" / "implemented-region-lifecycle.json")

    resolution = resolve_region_owners(
        "WA_SEATTLE",
        coverage_registry=registry,
        lifecycle_registry=lifecycle,
    )
    assert not isinstance(resolution, Refusal)
    assert isinstance(resolution, RegionOwnerResolution)
    seattle = next(row for row in registry.rows if row.jurisdiction_code == "WA_SEATTLE")
    assert seattle.authority_relation.relation == "partitioned_overlapping"
    assert resolution.branch == "covered_by_parent"
    assert resolution.status_origin == "inherited"
    assert resolution.identity_registry_row.jurisdiction_code == "WA_SEATTLE"
    assert resolution.status_registry_row.jurisdiction_code == "WA"
