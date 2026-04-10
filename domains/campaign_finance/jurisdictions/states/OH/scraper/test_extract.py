"""Tests for Ohio campaign finance entity extraction.

All column lookups go through config-driven field mappings — no hardcoded
OH column names in tests except when asserting expected fixture values.
"""

from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.OH.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.OH.scraper.extract import (
    extract_oh_contribution,
    extract_oh_expenditure,
)
from domains.campaign_finance.jurisdictions.states.OH.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def _column(data_type: str, semantic_path: str) -> str:
    return _load_column_for_semantic_path(data_type, semantic_path)


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv"))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_FIXTURE_DIR / "sample_expenditures.csv"))


# --- Contribution extraction: individual routing ---


def test_contribution_routes_individual_to_person() -> None:
    """Row 0: individual donor (split name fields populated, NON_INDIVIDUAL empty)."""
    row = _contribution_rows()[0]

    extracted = extract_oh_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "John"
    assert extracted["donor_person"].last_name == "Smith"
    assert extracted["donor_org"] is None


def test_contribution_includes_middle_name_in_person() -> None:
    """Row 0 has MIDDLE_NAME='A' — must appear in Person.middle_name and canonical_name."""
    row = _contribution_rows()[0]

    extracted = extract_oh_contribution(row)

    person = extracted["donor_person"]
    assert person is not None
    assert person.middle_name == "A"
    assert "A" in person.canonical_name
    # canonical_name should be "John A Smith" (first middle last)
    assert person.canonical_name == "John A Smith"


def test_contribution_person_without_middle_name() -> None:
    """Row 2: Mary Jones has no middle name — Person.middle_name should be None."""
    row = _contribution_rows()[2]

    extracted = extract_oh_contribution(row)

    person = extracted["donor_person"]
    assert person is not None
    assert person.first_name == "Mary"
    assert person.last_name == "Jones"
    assert person.middle_name is None
    assert person.canonical_name == "Mary Jones"


# --- Contribution extraction: organization routing ---


def test_contribution_routes_organization_when_non_individual_populated() -> None:
    """Row 1: NON_INDIVIDUAL='Ohio Teachers Union' — route to Organization."""
    row = _contribution_rows()[1]

    extracted = extract_oh_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Ohio Teachers Union"


# --- Committee extraction ---


def test_contribution_committee_has_oh_committee_id() -> None:
    """Committee builds Organization with oh_committee_id from MASTER_KEY."""
    row = _contribution_rows()[0]

    extracted = extract_oh_contribution(row)

    committee = extracted["committee"]
    assert committee.canonical_name == "Friends of Smith"
    assert committee.identifiers == {"oh_committee_id": "12345"}


# --- Address extraction ---


def test_contribution_extracts_address_with_zip_splitting() -> None:
    """Row 0: ADDRESS/CITY/STATE/ZIP fields produce an Address with zip5."""
    row = _contribution_rows()[0]

    extracted = extract_oh_contribution(row)

    address = extracted["address"]
    assert address is not None
    assert address.city == "Columbus"
    assert address.state == "OH"
    assert address.zip5 == "43215"


def test_contribution_address_includes_street_in_raw() -> None:
    """Raw address should include the street from ADDRESS field."""
    row = _contribution_rows()[0]

    extracted = extract_oh_contribution(row)

    address = extracted["address"]
    assert address is not None
    assert "123 Main St" in address.raw_address


def test_contribution_zip_with_plus4_splits_correctly() -> None:
    """ZIP with dash format splits into zip5 and zip4."""
    row = dict(_contribution_rows()[0])
    row[_column("contributions", "donor.address.zip")] = "43215-1234"

    extracted = extract_oh_contribution(row)

    address = extracted["address"]
    assert address is not None
    assert address.zip5 == "43215"
    assert address.zip4 == "1234"


# --- Expenditure extraction ---


def test_expenditure_routes_organization_when_non_individual_populated() -> None:
    """Expenditure row 0: NON_INDIVIDUAL='ABC Printing Co' — route to Organization."""
    row = _expenditure_rows()[0]

    extracted = extract_oh_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "ABC Printing Co"


def test_expenditure_routes_individual_to_person() -> None:
    """Expenditure row 1: individual payee (split name fields, no NON_INDIVIDUAL)."""
    row = _expenditure_rows()[1]

    extracted = extract_oh_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].first_name == "Sarah"
    assert extracted["payee_person"].last_name == "Williams"
    assert extracted["payee_person"].middle_name == "B"
    assert extracted["payee_org"] is None


def test_expenditure_committee_has_oh_committee_id() -> None:
    """Expenditure committee builds Organization with oh_committee_id."""
    row = _expenditure_rows()[0]

    extracted = extract_oh_expenditure(row)

    committee = extracted["committee"]
    assert committee.canonical_name == "Friends of Smith"
    assert committee.identifiers == {"oh_committee_id": "12345"}


def test_expenditure_extracts_address() -> None:
    """Expenditure row 0 builds address from payee address fields."""
    row = _expenditure_rows()[0]

    extracted = extract_oh_expenditure(row)

    address = extracted["address"]
    assert address is not None
    assert address.city == "Columbus"
    assert address.state == "OH"
    assert address.zip5 == "43215"


# --- Edge cases ---


def test_extraction_routes_by_non_individual_presence_not_name_heuristics() -> None:
    """Entity routing uses NON_INDIVIDUAL field presence, not name content heuristics."""
    row = dict(_contribution_rows()[0])
    # Force NON_INDIVIDUAL populated — even though individual name fields exist
    row[_column("contributions", "donor.name.organization")] = "Person Looking Name"

    extracted = extract_oh_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Person Looking Name"


def test_empty_name_fields_produce_no_person_or_org() -> None:
    """When both individual fields and NON_INDIVIDUAL are empty, no person or org."""
    row = dict(_contribution_rows()[0])
    row[_column("contributions", "donor.name.first")] = ""
    row[_column("contributions", "donor.name.last")] = ""
    row[_column("contributions", "donor.name.middle")] = ""
    row[_column("contributions", "donor.name.organization")] = ""

    extracted = extract_oh_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is None
