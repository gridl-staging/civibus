from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.PA.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.PA.scraper.extract import (
    extract_pa_contribution,
    extract_pa_debt,
    extract_pa_expenditure,
    extract_pa_filing,
    extract_pa_receipt,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper.parse import (
    parse_contributions,
    parse_debts,
    parse_expenditures,
    parse_filings,
    parse_receipts,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv", year=2025))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_FIXTURE_DIR / "sample_expenditures.csv", year=2025))


def _debt_rows() -> list[dict[str, str | None]]:
    return list(parse_debts(_FIXTURE_DIR / "sample_debts.csv", year=2025))


def _receipt_rows() -> list[dict[str, str | None]]:
    return list(parse_receipts(_FIXTURE_DIR / "sample_receipts.csv", year=2025))


def _filing_rows() -> list[dict[str, str | None]]:
    return list(parse_filings(_FIXTURE_DIR / "sample_filings.csv", year=2025))


def test_load_column_for_semantic_path_matches_expected_pa_columns() -> None:
    assert _load_column_for_semantic_path("contributions", "donor.name") == "CONTRIBUTOR"
    assert _load_column_for_semantic_path("expenditures", "payee.name") == "EXPNAME"
    assert _load_column_for_semantic_path("debts", "lender.name") == "DBTNAME"
    assert _load_column_for_semantic_path("receipts", "pa.receipt_source_name") == "RECNAME"
    assert _load_column_for_semantic_path("filings", "committee.name") == "FILERNAME"


def test_extract_pa_contribution_routes_single_name_to_person_and_committee() -> None:
    row = dict(_contribution_rows()[0])
    row["CONTRIBUTOR"] = "José Café Donor"

    extracted = extract_pa_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].canonical_name == "José Café Donor"
    assert extracted["donor_org"] is None
    assert extracted["committee"].identifiers == {"pa_filer_id": "2004206"}


def test_extract_pa_contribution_routes_org_like_name_to_organization() -> None:
    row = dict(_contribution_rows()[0])
    row["CONTRIBUTOR"] = "Example Holdings LLC"

    extracted = extract_pa_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Example Holdings LLC"


def test_extract_pa_expenditure_builds_payee_and_address() -> None:
    row = dict(_expenditure_rows()[0])
    row["EXPNAME"] = "Jane Smith"
    row["ADDRESS1"] = "123 Market St"
    row["ADDRESS2"] = "Suite 200"
    row["CITY"] = "Philadelphia"
    row["STATE"] = "pa"
    row["ZIPCODE"] = "19106-4321"

    extracted = extract_pa_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].canonical_name == "Jane Smith"
    assert extracted["payee_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].raw_address == "123 Market St, Suite 200, Philadelphia, PA, 19106-4321"
    assert extracted["address"].state == "PA"
    assert extracted["address"].zip5 == "19106"
    assert extracted["address"].zip4 == "4321"


def test_extract_pa_debt_routes_org_like_lender_name_to_organization() -> None:
    row = _debt_rows()[4]

    extracted = extract_pa_debt(row)

    assert extracted["lender_person"] is None
    assert extracted["lender_org"] is not None
    assert extracted["lender_org"].canonical_name == "GOUDSOUZIAN & ASSOCIATES"


def test_extract_pa_receipt_routes_single_token_name_to_organization() -> None:
    row = _receipt_rows()[0]

    extracted = extract_pa_receipt(row)

    assert extracted["source_person"] is None
    assert extracted["source_org"] is not None
    assert extracted["source_org"].canonical_name == "ActBlue"
    assert extracted["committee"].identifiers == {"pa_filer_id": "20250112"}


def test_extract_pa_filing_builds_committee_and_mailing_address() -> None:
    row = dict(_filing_rows()[1])
    row["ADDRESS1"] = "100 State St"
    row["ADDRESS2"] = "Floor 3"

    extracted = extract_pa_filing(row)

    assert extracted["committee"].canonical_name.strip() == "YORK CO FED OF DEM WOMEN"
    assert extracted["committee"].identifiers == {"pa_filer_id": "2004174"}
    assert extracted["address"] is not None
    assert extracted["address"].city == "YORK"
    assert extracted["address"].state == "PA"
    assert extracted["address"].zip5 == "17403"
    assert extracted["address"].zip4 == "2013"
