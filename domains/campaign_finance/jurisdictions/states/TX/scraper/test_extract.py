from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.TX.scraper.extract import (
    extract_tx_contribution,
    extract_tx_expenditure,
    extract_tx_loan,
)
from domains.campaign_finance.jurisdictions.states.TX.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_loans,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv"))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_FIXTURE_DIR / "sample_expenditures.csv"))


def _loan_rows() -> list[dict[str, str | None]]:
    return list(parse_loans(_FIXTURE_DIR / "sample_loans.csv"))


def test_extract_tx_contribution_routes_individual_to_person() -> None:
    row = _contribution_rows()[0]

    extracted = extract_tx_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "Daniel"
    assert extracted["donor_person"].last_name == "Chism"
    assert extracted["donor_org"] is None


def test_extract_tx_contribution_routes_entity_to_organization() -> None:
    row = dict(_contribution_rows()[0])
    row["contributorPersentTypeCd"] = "ENTITY"
    row["contributorNameOrganization"] = "Example Holdings LLC"

    extracted = extract_tx_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Example Holdings LLC"


def test_extract_tx_expenditure_builds_payee_and_street_address() -> None:
    row = dict(_expenditure_rows()[0])
    row["payeeStreetAddr1"] = "123 Congress Ave"
    row["payeeStreetAddr2"] = "Suite 200"
    row["payeeStreetCity"] = "Austin"
    row["payeeStreetStateCd"] = "TX"
    row["payeeStreetPostalCode"] = "78701"

    extracted = extract_tx_expenditure(row)

    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "Houston Bar Association Appellate Section"
    assert extracted["address"] is not None
    assert extracted["address"].raw_address == "123 Congress Ave, Suite 200, Austin, TX, 78701"


def test_extract_tx_loan_builds_lender_and_committee() -> None:
    row = _loan_rows()[2]

    extracted = extract_tx_loan(row)

    assert extracted["lender_org"] is not None
    assert extracted["lender_org"].canonical_name == "Lone Star National Bank"
    assert extracted["committee"].identifiers == {"tx_committee_id": "00013805"}


def test_extract_tx_contribution_handles_9digit_zip_without_dash() -> None:
    """TX live data sometimes has ZIP+4 as '774946162' (9 digits, no dash).
    The extractor must split this into zip5='77494' and zip4='6162' instead
    of passing all 9 digits as zip5 (which fails Address validation)."""
    row = dict(_contribution_rows()[0])
    row["contributorStreetPostalCode"] = "774946162"

    extracted = extract_tx_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "77494"
    assert extracted["address"].zip4 == "6162"


def test_extract_tx_contribution_handles_5digit_zip() -> None:
    """Standard 5-digit ZIP should still work."""
    row = dict(_contribution_rows()[0])
    row["contributorStreetPostalCode"] = "77494"

    extracted = extract_tx_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "77494"
    assert extracted["address"].zip4 is None


def test_extract_tx_contribution_handles_zip_with_dash() -> None:
    """Standard ZIP+4 with dash should still work."""
    row = dict(_contribution_rows()[0])
    row["contributorStreetPostalCode"] = "77494-6162"

    extracted = extract_tx_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "77494"
    assert extracted["address"].zip4 == "6162"


def test_extractors_route_by_persent_type_without_name_heuristics() -> None:
    contribution_row = dict(_contribution_rows()[0])
    contribution_row["contributorPersentTypeCd"] = "ENTITY"
    contribution_row["contributorNameOrganization"] = "Person Looking Name"
    contribution_row["contributorNameLast"] = "Human"
    contribution_row["contributorNameFirst"] = "Name"

    extracted = extract_tx_contribution(contribution_row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Person Looking Name"
