from __future__ import annotations

import csv
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.KY.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.KY.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_columns_derive_from_ky_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")


def test_parse_contributions_filters_by_year_window() -> None:
    """Fixture has 4 rows: 1 from 2021 and 3 within the current 5-year window."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))

    assert len(rows) == 3
    # All returned rows should be inside the 5-year window.
    for row in rows:
        assert row["Receipt Date"] in {"11/28/2025", "03/01/2026", "03/10/2026"}


def test_parse_contributions_old_row_is_filtered() -> None:
    """The 2021 row should be excluded by the 5-year filter."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))

    dates = [row["Receipt Date"] for row in rows]
    assert not any("2021" in d for d in dates)


def test_parse_expenditures_filters_by_year_window() -> None:
    """Fixture has 3 rows: 1 from 2021, 2 from 2026. Only 2026 rows pass."""
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2022))

    assert len(rows) == 2
    dates = [row["Disbursement Date"] for row in rows]
    assert all("2026" in d for d in dates)


def test_parse_normalizes_empty_strings_to_none() -> None:
    """Empty CSV fields become None after normalization."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))

    pac_rows = [r for r in rows if r.get("From Organization Name") == "KENTUCKY BUILDERS ASSOCIATION"]
    assert len(pac_rows) == 1
    assert pac_rows[0]["Contributor First Name"] is None


def test_parse_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad-header.csv"
    rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    bad_columns = list(CONTRIBUTION_COLUMNS)
    bad_columns[0] = "wrongColumn"

    with bad_header_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=bad_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(rows[0])

    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parse_contributions(bad_header_path, year_from=2022))


def test_parse_without_year_from_returns_all_rows() -> None:
    """When year_from is not specified, it defaults to current_year - 4."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))

    # 2021 is outside default 5-year window (2022+), so still filtered
    assert len(rows) == 3


def test_parse_with_generous_year_from_returns_all_rows() -> None:
    """When year_from is set far back, all rows should pass the filter."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2000))

    assert len(rows) == 4
