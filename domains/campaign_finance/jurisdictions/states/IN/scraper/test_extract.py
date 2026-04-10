from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.IN.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.IN.scraper.extract import (
    extract_in_contribution,
    extract_in_expenditure,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv"))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_FIXTURE_DIR / "sample_expenditures.csv"))


def test_extract_in_contribution_routes_individual_type_to_person() -> None:
    donor_type_column = _load_column_for_semantic_path("contributions", "donor.type")
    row = next(source_row for source_row in _contribution_rows() if source_row[donor_type_column] == "Individual")

    extracted = extract_in_contribution(dict(row))

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "Abbi"
    assert extracted["donor_person"].last_name == "Smith"
    assert extracted["donor_org"] is None


def test_extract_in_contribution_routes_non_individual_type_to_organization() -> None:
    donor_type_column = _load_column_for_semantic_path("contributions", "donor.type")
    row = next(source_row for source_row in _contribution_rows() if source_row[donor_type_column] == "Corporation")

    extracted = extract_in_contribution(dict(row))

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Allied Automation Inc."


def test_extract_in_contribution_builds_committee_from_config_driven_fields() -> None:
    contribution_fields = {
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "committee_type": _load_column_for_semantic_path("contributions", "committee.type"),
    }
    row = dict(_contribution_rows()[0])

    extracted = extract_in_contribution(row)

    assert extracted["committee"].canonical_name == row[contribution_fields["committee_name"]]
    assert extracted["committee"].org_type == row[contribution_fields["committee_type"]].lower()
    assert extracted["committee"].identifiers == {}


def test_extract_in_contribution_returns_no_counterparty_for_blank_name() -> None:
    name_column = _load_column_for_semantic_path("contributions", "donor.name")
    donor_type_column = _load_column_for_semantic_path("contributions", "donor.type")
    row = dict(_contribution_rows()[0])
    row[name_column] = "   "
    row[donor_type_column] = "Individual"

    extracted = extract_in_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is None


def test_extract_in_expenditure_routes_contribution_code_to_organization_payee() -> None:
    code_column = _load_column_for_semantic_path("expenditures", "transaction.code")
    row = next(source_row for source_row in _expenditure_rows() if source_row[code_column] == "Contributions")

    extracted = extract_in_expenditure(dict(row))

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "Clark County Republican Party"


def test_extract_in_expenditure_routes_operations_human_name_to_person_payee() -> None:
    code_column = _load_column_for_semantic_path("expenditures", "transaction.code")
    row = next(
        source_row
        for source_row in _expenditure_rows()
        if source_row[code_column] == "Operations" and source_row["Name"] == "Abigail Harms"
    )

    extracted = extract_in_expenditure(dict(row))

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].first_name == "Abigail"
    assert extracted["payee_person"].last_name == "Harms"
    assert extracted["payee_org"] is None


def test_extract_in_expenditure_routes_known_lodge_payee_to_organization() -> None:
    code_column = _load_column_for_semantic_path("expenditures", "transaction.code")
    row = next(
        source_row
        for source_row in _expenditure_rows()
        if source_row[code_column] == "Operations" and source_row["Name"] == "Abe Martin Lodge"
    )

    extracted = extract_in_expenditure(dict(row))

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "Abe Martin Lodge"


def test_extract_in_expenditure_uses_occupation_to_override_name_heuristics() -> None:
    code_column = _load_column_for_semantic_path("expenditures", "transaction.code")
    occupation_column = _load_column_for_semantic_path("expenditures", "payee.occupation")
    row = dict(next(source_row for source_row in _expenditure_rows() if source_row[code_column] == "Operations"))
    row["Name"] = "Acme Holdings LLC"
    row[occupation_column] = "Consultant"

    extracted = extract_in_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_org"] is None


def test_extract_in_expenditure_returns_no_counterparty_for_blank_name() -> None:
    name_column = _load_column_for_semantic_path("expenditures", "payee.name")
    row = dict(_expenditure_rows()[0])
    row[name_column] = ""

    extracted = extract_in_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is None


def test_extract_normalizes_state_and_zip_when_building_address() -> None:
    state_column = _load_column_for_semantic_path("contributions", "donor.address.state")
    zip_column = _load_column_for_semantic_path("contributions", "donor.address.zip")
    row = dict(_contribution_rows()[0])
    row[state_column] = "in"
    row[zip_column] = "46220-1234"

    extracted = extract_in_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].state == "IN"
    assert extracted["address"].zip5 == "46220"
    assert extracted["address"].zip4 == "1234"
