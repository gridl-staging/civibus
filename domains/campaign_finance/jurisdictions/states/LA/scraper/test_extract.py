from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.LA.scraper.extract import (
    extract_la_contribution,
    extract_la_expenditure,
    extract_la_loan,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _first_matching_row(path: Path, *, match_column: str, value: str) -> dict[str, str | None]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get(match_column) == value:
                return row
    raise AssertionError(f"missing fixture row for {match_column}={value}")


def test_extract_la_contribution_returns_org_and_committee() -> None:
    row = _first_matching_row(
        _SAMPLE_CONTRIBUTIONS_PATH,
        match_column="ContributorTypeCode",
        value="BUS",
    )

    extracted = extract_la_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "MECHANICAL SYSTEMS INSULATION"
    assert extracted["committee"].identifiers["la_filer_number"] == "4790"


def test_extract_la_loan_returns_person_and_committee() -> None:
    row = _first_matching_row(
        _SAMPLE_LOANS_PATH,
        match_column="LoanHolderName",
        value="ANGELA ROBERTS",
    )

    extracted = extract_la_loan(row)

    assert extracted["lender_person"] is not None
    assert extracted["lender_person"].first_name == "ANGELA"
    assert extracted["lender_org"] is None
    assert extracted["committee"].canonical_name == "ROBERTS"


def test_extract_la_expenditure_returns_payee_org() -> None:
    row = _first_matching_row(
        _SAMPLE_EXPENDITURES_PATH,
        match_column="RecipientName",
        value="BILANTA AARON",
    )

    extracted = extract_la_expenditure(row)

    assert extracted["payee_org"] is not None
    assert extracted["payee_person"] is None
    assert extracted["committee"].identifiers["la_filer_number"] == "975"
