from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.KY.scraper.extract import (
    extract_ky_contribution,
    extract_ky_expenditure,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _first_matching_row(path: Path, *, match_column: str, value: str) -> dict[str, str | None]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get(match_column) == value:
                return row
    raise AssertionError(f"missing fixture row for {match_column}={value}")


def test_extract_ky_contribution_returns_person_and_committee() -> None:
    """Individual contribution row: Sheila Enyart donating to Brian Smith."""
    row = _first_matching_row(
        _SAMPLE_CONTRIBUTIONS_PATH,
        match_column="Contributor Last Name",
        value="Enyart",
    )

    extracted = extract_ky_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "Sheila"
    assert extracted["donor_person"].last_name == "Enyart"
    assert extracted["donor_org"] is None
    assert extracted["committee"].canonical_name == "Brian Smith"


def test_extract_ky_contribution_returns_org_for_pac() -> None:
    """PAC contribution row: KENTUCKY BUILDERS ASSOCIATION."""
    row = _first_matching_row(
        _SAMPLE_CONTRIBUTIONS_PATH,
        match_column="From Organization Name",
        value="KENTUCKY BUILDERS ASSOCIATION",
    )

    extracted = extract_ky_contribution(row)

    # PAC rows have the org name in ContributorName but empty FirstName/LastName
    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert "KENTUCKY BUILDERS ASSOCIATION" in extracted["donor_org"].canonical_name


def test_extract_ky_contribution_builds_address() -> None:
    row = _first_matching_row(
        _SAMPLE_CONTRIBUTIONS_PATH,
        match_column="Contributor Last Name",
        value="Enyart",
    )

    extracted = extract_ky_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].city == "Radcliff"
    assert extracted["address"].state == "KY"
    assert extracted["address"].zip5 == "40160"


def test_extract_ky_expenditure_returns_payee_person() -> None:
    """Expenditure row: AMY JOHNSON as payee."""
    row = _first_matching_row(
        _SAMPLE_EXPENDITURES_PATH,
        match_column="Recipient Last Name",
        value="JOHNSON",
    )

    extracted = extract_ky_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].first_name == "AMY"
    assert extracted["payee_person"].last_name == "JOHNSON"
    assert extracted["payee_org"] is None
    assert extracted["committee"].canonical_name == "Jane Doe"


def test_extract_ky_expenditure_returns_org_for_vendor() -> None:
    """Expenditure row: BLUEGRASS PRINTING INC as vendor (org)."""
    row = _first_matching_row(
        _SAMPLE_EXPENDITURES_PATH,
        match_column="Organization Name",
        value="BLUEGRASS PRINTING INC",
    )

    extracted = extract_ky_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert "BLUEGRASS PRINTING INC" in extracted["payee_org"].canonical_name


def test_extract_ky_expenditure_builds_address() -> None:
    row = _first_matching_row(
        _SAMPLE_EXPENDITURES_PATH,
        match_column="Recipient Last Name",
        value="JOHNSON",
    )

    extracted = extract_ky_expenditure(row)

    assert extracted["address"] is None
