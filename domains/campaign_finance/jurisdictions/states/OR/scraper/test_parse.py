"""Tests for OR TSV/XLS parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.OR.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.OR.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.xls"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.xls"


def test_columns_derive_from_or_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")


def test_parse_contributions_filters_old_rows_by_year() -> None:
    """Sample has 4 rows: 1 from 2021 (filtered), 3 from 2026 (kept)."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))

    assert len(rows) == 3
    # All remaining rows should be 2026
    for row in rows:
        assert "2026" in row["Tran Date"]


def test_parse_expenditures_filters_old_rows_by_year() -> None:
    """Sample has 2 rows: 1 from 2021 (filtered), 1 from 2026 (kept)."""
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2022))

    assert len(rows) == 1
    assert "2026" in rows[0]["Tran Date"]


def test_parse_normalizes_empty_strings_to_none() -> None:
    """Fields with empty/whitespace values should become None."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))

    # The sample fixture has empty fields for Contributor/Payee Committee ID
    for row in rows:
        if row.get("Contributor/Payee Committee ID") is not None:
            assert row["Contributor/Payee Committee ID"].strip() != ""


def test_parse_rejects_header_drift(tmp_path: Path) -> None:
    """Parser should raise on unexpected headers."""
    bad_path = tmp_path / "bad_header.xls"
    bad_path.write_text("Wrong Header\tAnother\n1\t2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unexpected contribution"):
        list(parse_contributions(bad_path, year_from=2022))


def test_parse_contributions_preserves_field_values() -> None:
    """Verify specific field values from fixture data."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))

    # Find the THOMPSON MARIA row
    thompson_rows = [r for r in rows if r["Contributor/Payee"] == "THOMPSON MARIA"]
    assert len(thompson_rows) == 1
    row = thompson_rows[0]

    assert row["Tran Id"] == "5002"
    assert row["Amount"] == "1000.00"
    assert row["Filer"] == "Citizens for Oregon 2026"
    assert row["Filer Id"] == "60282"
    assert row["Employer Name"] == "Oregon Health Sciences"
    assert row["Addr Book Type"] == "Individual"


def test_parse_contributions_without_year_from_uses_default_five_year_window() -> None:
    """With year_from=None, the parser should still enforce the default 5-year window."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=None))

    assert len(rows) == 3


def test_parse_expenditures_preserves_business_entity_type() -> None:
    """Verify Business Entity addr book type is preserved."""
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2000))

    portland_rows = [r for r in rows if r["Contributor/Payee"] == "PORTLAND PRESS LLC"]
    assert len(portland_rows) == 1
    assert portland_rows[0]["Addr Book Type"] == "Business Entity"
