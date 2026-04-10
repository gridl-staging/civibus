from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.WA.scraper.extract import (
    _extract_street_address,
    extract_wa_contribution,
    extract_wa_expenditure,
    extract_wa_loan,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper.parse import (
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


def test_extract_wa_contribution_individual_row() -> None:
    row = _contribution_rows()[0]

    extracted = extract_wa_contribution(row)

    assert extracted["committee"].canonical_name == "Friends of Example"
    assert extracted["committee"].identifiers == {"wa_committee_id": "9001"}
    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].canonical_name == "Jane Doe"
    assert extracted["donor_person"].identifiers["employer"] == "Example Co"
    assert extracted["donor_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "98501"


def test_extract_wa_contribution_business_row_creates_organization() -> None:
    row = _contribution_rows()[1]

    extracted = extract_wa_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Example Holdings LLC"


def test_extract_wa_expenditure_person_payee_row() -> None:
    row = _expenditure_rows()[0]

    extracted = extract_wa_expenditure(row)

    assert extracted["committee"].identifiers == {"wa_committee_id": "9001"}
    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].canonical_name == "John Smith"
    assert extracted["payee_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].city == "Seattle"
    assert extracted["address"].state == "WA"


def test_extract_wa_expenditure_organization_payee_row() -> None:
    row = _expenditure_rows()[1]

    extracted = extract_wa_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "North Star Printing LLC"


def test_extract_wa_loan_person_lender_row() -> None:
    row = _loan_rows()[0]

    extracted = extract_wa_loan(row)

    assert extracted["committee"].identifiers == {"wa_committee_id": "9003"}
    assert extracted["lender_person"] is not None
    assert extracted["lender_person"].canonical_name == "Alex Taylor"
    assert extracted["lender_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "98501"


def test_extract_wa_loan_organization_lender_row() -> None:
    row = _loan_rows()[1]

    extracted = extract_wa_loan(row)

    assert extracted["lender_person"] is None
    assert extracted["lender_org"] is not None
    assert extracted["lender_org"].canonical_name == "Community Bank LLC"


@pytest.mark.parametrize(
    "raw_zip, expected_zip5, expected_zip4",
    [
        ("98501", "98501", None),
        ("98501-1234", "98501", "1234"),
        ("921024548", "92102", "4548"),  # 9-digit concatenated zip+4
        ("940404177", "94040", "4177"),  # another 9-digit concatenated
        ("6371", None, None),  # 4-digit international postal code
        ("180202", None, None),  # 6-digit postal code
        ("8401", None, None),  # 4-digit
        ("", None, None),
        (None, None, None),
    ],
)
def test_extract_street_address_handles_non_standard_zip_gracefully(
    raw_zip: str | None,
    expected_zip5: str | None,
    expected_zip4: str | None,
) -> None:
    """Regression: live WA Socrata data includes 9-digit concatenated zip+4 codes
    and international postal codes. _extract_street_address must not raise on these."""
    address = _extract_street_address(
        address1="123 Main St",
        city="Seattle",
        state="WA",
        raw_zip=raw_zip,
    )

    assert address is not None
    assert address.zip5 == expected_zip5
    assert address.zip4 == expected_zip4
