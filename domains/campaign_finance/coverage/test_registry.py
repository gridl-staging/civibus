from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from domains.campaign_finance.coverage.registry import (
    CoverageRegistry,
    CoverageRegistryRow,
    coverage_parent_linkage_error,
)


def _base_row_payload() -> dict[str, object]:
    return {
        "jurisdiction_code": "CA",
        "name": "California",
        "jurisdiction_type": "state",
        "best_update_frequency": "daily",
        "best_last_verified_working": "2026-03-21",
        "covers_sub_jurisdictions": True,
        "source_count": 2,
        "source_names": ["CAL-ACCESS Raw Data Export", "CAL-ACCESS Documentation Bundle"],
        "runner_wired": True,
        "tier": None,
        "evidence_summary": None,
        "operational_reason": None,
        "next_action": None,
        "evidence_date": None,
    }


def test_registry_row_accepts_valid_payload() -> None:
    row = CoverageRegistryRow.model_validate(_base_row_payload())

    assert row.jurisdiction_code == "CA"
    assert row.best_update_frequency == "daily"
    assert row.best_last_verified_working == date(2026, 3, 21)


def test_registry_row_rejects_missing_required_field() -> None:
    payload = _base_row_payload()
    payload.pop("jurisdiction_code")

    with pytest.raises(ValidationError, match="jurisdiction_code"):
        CoverageRegistryRow.model_validate(payload)


def test_registry_row_rejects_unknown_tier_string() -> None:
    payload = _base_row_payload()
    payload["tier"] = "unknown-tier"

    with pytest.raises(ValidationError, match="tier"):
        CoverageRegistryRow.model_validate(payload)


def test_registry_row_rejects_extra_fields_with_extra_forbid() -> None:
    payload = _base_row_payload()
    payload["unexpected"] = "boom"

    with pytest.raises(ValidationError, match=r"extra fields not permitted|Extra inputs are not permitted"):
        CoverageRegistryRow.model_validate(payload)


def test_registry_rejects_duplicate_jurisdiction_codes() -> None:
    first = _base_row_payload()
    second = _base_row_payload()
    second["name"] = "California Duplicate"

    with pytest.raises(ValidationError, match="Duplicate jurisdiction code"):
        CoverageRegistry.model_validate({"rows": [first, second]})


def test_registry_json_round_trip_preserves_all_fields() -> None:
    first = _base_row_payload()
    second = _base_row_payload()
    second.update(
        {
            "jurisdiction_code": "MN",
            "name": "Minnesota",
            "best_update_frequency": "quarterly",
            "covers_sub_jurisdictions": False,
            "source_count": 3,
            "source_names": ["MN A", "MN B", "MN C"],
            "runner_wired": True,
            "best_last_verified_working": "2026-03-21",
            "tier": "freshness-limited",
            "evidence_summary": "Quarterly exports only",
            "operational_reason": "Known cadence limit",
            "next_action": "Investigate supplemental API",
            "evidence_date": "2026-03-25",
        }
    )
    inherited = _municipality_row_payload(code="CA_CHILD", parent="CA", decision="covered_by_parent")
    independent = _municipality_row_payload(code="MN_CHILD", parent="MN", decision="independent_target")
    registry = CoverageRegistry.model_validate({"rows": [first, second, inherited, independent]})

    json_payload = registry.model_dump_json(indent=2)
    reparsed = CoverageRegistry.model_validate_json(json_payload)

    assert reparsed.model_dump(mode="json") == registry.model_dump(mode="json")
    rows_by_code = {row.jurisdiction_code: row for row in reparsed.rows}
    assert rows_by_code["CA_CHILD"].parent_jurisdiction_code == "CA"
    assert rows_by_code["CA_CHILD"].municipal_audit_decision == "covered_by_parent"
    assert rows_by_code["MN_CHILD"].parent_jurisdiction_code == "MN"
    assert rows_by_code["MN_CHILD"].municipal_audit_decision == "independent_target"


def test_registry_allows_zero_rows() -> None:
    registry = CoverageRegistry.model_validate({"rows": []})

    assert registry.rows == []


# --- Municipality layer contract tests (Stage 5) ---


def _municipality_row_payload(
    code: str = "CA_LOS_ANGELES",
    parent: str = "CA",
    decision: str = "covered_by_parent",
) -> dict[str, object]:
    return {
        "jurisdiction_code": code,
        "name": "Los Angeles",
        "jurisdiction_type": "municipality",
        "best_update_frequency": "daily",
        "best_last_verified_working": "2026-03-25",
        "covers_sub_jurisdictions": False,
        "source_count": 1,
        "source_names": ["Inherited from CA"],
        "runner_wired": False,
        "tier": "launch-support candidate",
        "evidence_summary": "Covered by parent state CA",
        "operational_reason": None,
        "next_action": "Inherits parent pipeline",
        "evidence_date": "2026-03-25",
        "parent_jurisdiction_code": parent,
        "municipal_audit_decision": decision,
    }


def test_municipality_row_accepts_valid_payload() -> None:
    row = CoverageRegistryRow.model_validate(_municipality_row_payload())

    assert row.jurisdiction_code == "CA_LOS_ANGELES"
    assert row.parent_jurisdiction_code == "CA"
    assert row.municipal_audit_decision == "covered_by_parent"


def test_municipality_row_accepts_independent_target_decision() -> None:
    payload = _municipality_row_payload(code="MN_MINNEAPOLIS", parent="MN", decision="independent_target")
    row = CoverageRegistryRow.model_validate(payload)

    assert row.municipal_audit_decision == "independent_target"


def test_municipality_row_rejects_null_parent() -> None:
    payload = _municipality_row_payload()
    payload["parent_jurisdiction_code"] = None

    with pytest.raises(ValidationError, match="parent_jurisdiction_code"):
        CoverageRegistryRow.model_validate(payload)


def test_municipality_row_rejects_null_decision() -> None:
    payload = _municipality_row_payload()
    payload["municipal_audit_decision"] = None

    with pytest.raises(ValidationError, match="municipal_audit_decision"):
        CoverageRegistryRow.model_validate(payload)


def test_municipality_row_rejects_invalid_decision_string() -> None:
    payload = _municipality_row_payload()
    payload["municipal_audit_decision"] = "maybe_covered"

    with pytest.raises(ValidationError, match="municipal_audit_decision"):
        CoverageRegistryRow.model_validate(payload)


def test_state_row_rejects_non_null_parent() -> None:
    payload = _base_row_payload()
    payload["parent_jurisdiction_code"] = "US"
    payload["municipal_audit_decision"] = None

    with pytest.raises(ValidationError, match="parent_jurisdiction_code"):
        CoverageRegistryRow.model_validate(payload)


def test_state_row_rejects_non_null_decision() -> None:
    payload = _base_row_payload()
    payload["parent_jurisdiction_code"] = None
    payload["municipal_audit_decision"] = "covered_by_parent"

    with pytest.raises(ValidationError, match="municipal_audit_decision"):
        CoverageRegistryRow.model_validate(payload)


def test_state_row_rejects_non_null_municipal_portal_url() -> None:
    payload = _base_row_payload()
    payload["municipal_portal_url"] = "https://example.com/city-portal"

    with pytest.raises(ValidationError, match="municipal_portal_url"):
        CoverageRegistryRow.model_validate(payload)


def test_state_row_accepts_null_municipality_fields() -> None:
    """State rows default to null parent and null decision — backward compatible."""
    payload = _base_row_payload()
    row = CoverageRegistryRow.model_validate(payload)

    assert row.parent_jurisdiction_code is None
    assert row.municipal_audit_decision is None


def test_county_row_accepts_null_municipality_fields() -> None:
    payload = _base_row_payload()
    payload["jurisdiction_code"] = "HENNEPIN"
    payload["name"] = "Hennepin County"
    payload["jurisdiction_type"] = "county"

    row = CoverageRegistryRow.model_validate(payload)

    assert row.parent_jurisdiction_code is None
    assert row.municipal_audit_decision is None


def test_county_row_rejects_municipality_linkage_fields() -> None:
    payload = _base_row_payload()
    payload["jurisdiction_code"] = "HENNEPIN"
    payload["name"] = "Hennepin County"
    payload["jurisdiction_type"] = "county"
    payload["parent_jurisdiction_code"] = "MN"
    payload["municipal_audit_decision"] = "covered_by_parent"

    with pytest.raises(ValidationError, match="must be null"):
        CoverageRegistryRow.model_validate(payload)


def test_coverage_parent_linkage_requires_existing_state_parent() -> None:
    state = CoverageRegistryRow.model_validate(_base_row_payload())
    child = CoverageRegistryRow.model_validate(_municipality_row_payload())

    assert coverage_parent_linkage_error(child, {"CA": state, "CA_LOS_ANGELES": child}) is None
    assert "no coverage-registry parent" in coverage_parent_linkage_error(child, {"CA_LOS_ANGELES": child})

    municipal_parent = CoverageRegistryRow.model_validate(
        _municipality_row_payload(code="CA", parent="NY", decision="independent_target")
    )
    error = coverage_parent_linkage_error(child, {"CA": municipal_parent, "CA_LOS_ANGELES": child})
    assert error is not None
    assert "must be a state" in error


def test_coverage_parent_linkage_uses_scope_only_for_explicit_inheritance() -> None:
    state_payload = _base_row_payload()
    state_payload["covers_sub_jurisdictions"] = False
    state = CoverageRegistryRow.model_validate(state_payload)
    covered = CoverageRegistryRow.model_validate(_municipality_row_payload())
    independent = CoverageRegistryRow.model_validate(_municipality_row_payload(decision="independent_target"))
    rows_by_code = {"CA": state, "CA_LOS_ANGELES": covered}

    covered_error = coverage_parent_linkage_error(covered, rows_by_code)
    assert covered_error is not None
    assert "covers_sub_jurisdictions=false" in covered_error
    assert coverage_parent_linkage_error(independent, rows_by_code) is None


def test_covered_by_parent_row_rejects_municipal_portal_url() -> None:
    payload = _municipality_row_payload()
    payload["municipal_portal_url"] = "https://example.com/city-portal"

    with pytest.raises(ValidationError, match="municipal_portal_url"):
        CoverageRegistryRow.model_validate(payload)


def test_browser_verified_independent_target_requires_municipal_portal_url() -> None:
    payload = _municipality_row_payload(code="CA_LOS_ANGELES", parent="CA", decision="independent_target")
    payload["evidence_summary"] = "Browser-verified city portal research (2026-03-31): LA open data portal"

    with pytest.raises(ValidationError, match="municipal_portal_url"):
        CoverageRegistryRow.model_validate(payload)


def test_non_browser_verified_independent_target_allows_missing_municipal_portal_url() -> None:
    payload = _municipality_row_payload(code="MN_MINNEAPOLIS", parent="MN", decision="independent_target")
    payload["evidence_summary"] = "Independent target from prior municipal audit"

    row = CoverageRegistryRow.model_validate(payload)

    assert row.municipal_audit_decision == "independent_target"
    assert row.municipal_portal_url is None


def test_registry_rejects_duplicate_municipality_codes() -> None:
    state_row = _base_row_payload()
    muni_a = _municipality_row_payload()
    muni_b = _municipality_row_payload()

    with pytest.raises(ValidationError, match="Duplicate jurisdiction code"):
        CoverageRegistry.model_validate({"rows": [state_row, muni_a, muni_b]})
