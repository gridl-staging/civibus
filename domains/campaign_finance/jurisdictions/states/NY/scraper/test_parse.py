"""Tests for NY CSV parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    NYCsvParser,
    parse_contributions,
    parse_expenditures,
)

_FIXTURES_DIR = Path(__file__).parent / "test_fixtures"


class TestNYParseContributions:
    """Test contribution CSV parsing."""

    def test_parse_sample_contributions_yields_rows(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        rows = list(parser)
        assert len(rows) == 3

    def test_first_row_has_expected_fields(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        # Verify key fields from the sample fixture.
        assert row["filer_id"] == "12345"
        assert row["cand_comm_name"] == "Friends of Jane Smith"
        assert row["flng_ent_first_name"] == "John"
        assert row["flng_ent_last_name"] == "Doe"
        assert row["org_amt"] == "500.00"
        assert row["cntrbr_type_desc"] == "Individual"

    def test_empty_fields_normalized_to_none(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        # county_desc is empty in the first row.
        assert row["county_desc"] is None

    def test_contribution_columns_has_45_fields(self) -> None:
        # Both contributions and expenditures share the same 45-column schema.
        assert len(CONTRIBUTION_COLUMNS) == 45

    def test_contribution_columns_match_expenditure_columns(self) -> None:
        # NY SODA contributions and expenditures use the same schema.
        assert CONTRIBUTION_COLUMNS == EXPENDITURE_COLUMNS


class TestNYParseExpenditures:
    """Test expenditure CSV parsing."""

    def test_parse_sample_expenditures_yields_rows(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        rows = list(parser)
        assert len(rows) == 2

    def test_expenditure_row_has_schedule_f(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        row = next(iter(parser))
        assert row["filing_sched_abbrev"] == "F"

    def test_expenditure_amount_is_present(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        row = next(iter(parser))
        assert row["org_amt"] == "2500.00"


class TestNYParserRejectsInvalidHeader:
    """Test that the parser rejects CSVs with unexpected headers."""

    def test_wrong_header_raises_value_error(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "bad_header.csv"
        csv_path.write_text("wrong_col1,wrong_col2\nval1,val2\n")
        parser = NYCsvParser(path=csv_path, columns=CONTRIBUTION_COLUMNS, row_label="test")
        with pytest.raises(ValueError, match="Unexpected NY test CSV header"):
            list(parser)
