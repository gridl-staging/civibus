from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.MN.scraper.extract import (
    _pad_zip5,
    _split_zip,
    extract_mn_contribution,
    extract_mn_expenditure,
    extract_mn_independent_expenditure,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_independent_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv"))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_FIXTURE_DIR / "sample_expenditures.csv"))


def _independent_expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_independent_expenditures(_FIXTURE_DIR / "sample_independent_expenditures.csv"))


def test_extract_mn_contribution_individual_row() -> None:
    row = _contribution_rows()[0]

    extracted = extract_mn_contribution(row)

    assert extracted["committee"].canonical_name == "Friends of Example"
    assert extracted["committee"].identifiers == {"mn_committee_reg_num": "9001"}
    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].canonical_name == "Jane Doe"
    assert extracted["donor_person"].identifiers["employer"] == "Acme Corp"
    assert extracted["donor_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "55101"


def test_extract_mn_contribution_business_row_creates_organization() -> None:
    row = _contribution_rows()[1]

    extracted = extract_mn_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Example Holdings LLC"


def test_extract_mn_expenditure_person_payee_row() -> None:
    row = _expenditure_rows()[0]

    extracted = extract_mn_expenditure(row)

    assert extracted["committee"].identifiers == {"mn_committee_reg_num": "9001"}
    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].canonical_name == "John Smith"
    assert extracted["payee_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].city == "Saint Paul"
    assert extracted["address"].state == "MN"


def test_extract_mn_expenditure_organization_payee_row() -> None:
    row = _expenditure_rows()[1]

    extracted = extract_mn_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "North Star Printing LLC"


class TestPadZip5:
    """Regression tests for _pad_zip5 — east-coast zips lose leading zeros."""

    def test_five_digit_zip_unchanged(self) -> None:
        assert _pad_zip5("55101") == "55101"

    def test_four_digit_zip_padded(self) -> None:
        """Regression: MN data had '7307' for NJ zip 07307."""
        assert _pad_zip5("7307") == "07307"

    def test_three_digit_zip_padded(self) -> None:
        """Regression: east-coast zips like 00501 (IRS) → '501'."""
        assert _pad_zip5("501") == "00501"

    def test_none_returns_none(self) -> None:
        assert _pad_zip5(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _pad_zip5("") is None

    def test_two_digit_too_short_returns_none(self) -> None:
        assert _pad_zip5("12") is None

    def test_six_digit_too_long_returns_none(self) -> None:
        assert _pad_zip5("123456") is None


class TestSplitZipShortCodes:
    """Regression tests for _split_zip with short zip codes."""

    def test_four_digit_zip_padded_to_five(self) -> None:
        zip5, zip4 = _split_zip("7307")
        assert zip5 == "07307"
        assert zip4 is None

    def test_hyphenated_short_zip_padded(self) -> None:
        zip5, zip4 = _split_zip("7307-1234")
        assert zip5 == "07307"
        assert zip4 == "1234"

    def test_normal_zip_still_works(self) -> None:
        zip5, zip4 = _split_zip("55101")
        assert zip5 == "55101"
        assert zip4 is None

    def test_zip_plus_four(self) -> None:
        zip5, zip4 = _split_zip("55101-4321")
        assert zip5 == "55101"
        assert zip4 == "4321"

    def test_none_input(self) -> None:
        zip5, zip4 = _split_zip(None)
        assert zip5 is None
        assert zip4 is None


def test_extract_mn_independent_expenditure_person_payee_row() -> None:
    row = _independent_expenditure_rows()[1]

    extracted = extract_mn_independent_expenditure(row)

    assert extracted["committee"].identifiers == {"mn_committee_reg_num": "9102"}
    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].canonical_name == "Jane Smith"
    assert extracted["payee_org"] is None
    assert extracted["address"] is not None
    assert extracted["address"].city == "Saint Paul"
    assert extracted["address"].state == "MN"
