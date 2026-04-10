"""Tests for OR entity extraction."""

from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.OR.scraper.extract import (
    extract_or_contribution,
    extract_or_expenditure,
)
from domains.campaign_finance.jurisdictions.states.OR.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.xls"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.xls"


def _find_row_by_tran_id(rows: list[dict], tran_id: str) -> dict:
    for row in rows:
        if row.get("Tran Id") == tran_id:
            return row
    raise AssertionError(f"missing fixture row for Tran Id={tran_id}")


def test_extract_contribution_individual_returns_person() -> None:
    """THOMPSON MARIA is an Individual -- should yield a Person with split name."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    row = _find_row_by_tran_id(rows, "5002")

    extracted = extract_or_contribution(row)

    assert extracted["donor_person"] is not None
    # OR names are "LAST FIRST" format -- parser should split
    assert extracted["donor_person"].last_name == "THOMPSON"
    assert extracted["donor_person"].first_name == "MARIA"
    assert extracted["donor_org"] is None
    assert extracted["committee"].canonical_name == "Citizens for Oregon 2026"
    assert extracted["committee"].identifiers["or_filer_id"] == "60282"


def test_extract_contribution_business_entity_returns_org() -> None:
    """PACIFIC LUMBER CORPORATION is Business Entity -- should yield Organization."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    row = _find_row_by_tran_id(rows, "5003")

    extracted = extract_or_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "PACIFIC LUMBER CORPORATION"
    assert extracted["committee"].canonical_name == "Oregon Progressive PAC"


def test_extract_contribution_individual_with_two_name_parts() -> None:
    """CHEN DAVID -- Individual with two-part name."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    row = _find_row_by_tran_id(rows, "5004")

    extracted = extract_or_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].last_name == "CHEN"
    assert extracted["donor_person"].first_name == "DAVID"


def test_extract_expenditure_individual_returns_person() -> None:
    """REED PATRICIA is an Individual expenditure payee."""
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2022))
    row = _find_row_by_tran_id(rows, "6002")

    extracted = extract_or_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].last_name == "REED"
    assert extracted["payee_person"].first_name == "PATRICIA"
    assert extracted["payee_org"] is None
    assert extracted["committee"].identifiers["or_filer_id"] == "60282"


def test_extract_expenditure_business_returns_org() -> None:
    """PORTLAND PRESS LLC is Business Entity -- should yield Organization."""
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2000))
    row = _find_row_by_tran_id(rows, "6001")

    extracted = extract_or_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "PORTLAND PRESS LLC"
