from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.NE.scraper.extract import (
    extract_ne_contribution,
    extract_ne_expenditure,
    extract_ne_loan,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTION_LOAN_PATH = _FIXTURE_DIR / "sample_contribution_loan.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _first_matching_row(path: Path, *, match_column: str, value: str) -> dict[str, str | None]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get(match_column) == value:
                return row
    raise AssertionError(f"missing fixture row for {match_column}={value}")


def test_extract_ne_contribution_returns_person_and_committee() -> None:
    row = _first_matching_row(
        _SAMPLE_CONTRIBUTION_LOAN_PATH,
        match_column="Receipt ID",
        value="1002",
    )

    extracted = extract_ne_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "BOB"
    assert extracted["donor_org"] is None
    assert extracted["committee"].identifiers["ne_org_id"] == "7001"


def test_extract_ne_loan_reuses_contribution_shape() -> None:
    row = _first_matching_row(
        _SAMPLE_CONTRIBUTION_LOAN_PATH,
        match_column="Receipt Transaction/Contribution Type",
        value="Loan",
    )

    extracted = extract_ne_loan(row)

    assert extracted["lender_person"] is not None
    assert extracted["lender_person"].first_name == "ALEX"
    assert extracted["committee"].canonical_name == "Committee A"


def test_extract_ne_expenditure_returns_payee_person() -> None:
    row = _first_matching_row(
        _SAMPLE_EXPENDITURES_PATH,
        match_column="Expenditure ID",
        value="2002",
    )

    extracted = extract_ne_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].first_name == "DREW"
    assert extracted["payee_org"] is None
    assert extracted["committee"].identifiers["ne_org_id"] == "8001"
