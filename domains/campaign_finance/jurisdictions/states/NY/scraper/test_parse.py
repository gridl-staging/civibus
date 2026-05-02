"""Tests for NY CSV parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    IE_COLUMNS,
    NYCsvParser,
    parse_contributions,
    parse_expenditures,
    parse_independent_expenditures,
)

_FIXTURES_DIR = Path(__file__).parent / "test_fixtures"
_KNOWN_CF01_SCHEDULE_CODES = {chr(code) for code in range(ord("A"), ord("U") + 1)}
_KNOWN_CONTRIBUTION_SCHEDULE_CODES = {"A", "B", "C", "D", "G"}


class TestNYParseContributions:
    """Test contribution CSV parsing."""

    def test_parse_sample_contributions_yields_rows(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        rows = list(parser)
        assert len(rows) == 3

    def test_first_row_has_expected_fields(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        assert row["filer_id"] == "12345"
        assert row["cand_comm_name"] == "Friends of Jane Smith"
        assert row["flng_ent_first_name"] == "John"
        assert row["flng_ent_last_name"] == "Doe"
        assert row["org_amt"] == "500.00"
        assert row["cntrbr_type_desc"] == "Individual"

    def test_empty_fields_normalized_to_none(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        assert row["county_desc"] is None

    def test_contribution_columns_has_45_fields(self) -> None:
        assert len(CONTRIBUTION_COLUMNS) == 45

    def test_contribution_columns_match_expenditure_columns(self) -> None:
        assert CONTRIBUTION_COLUMNS == EXPENDITURE_COLUMNS

    def test_contribution_fixture_schedule_codes_match_contract(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        schedule_codes = {row["filing_sched_abbrev"] for row in parser}
        assert schedule_codes == {"A", "C"}
        assert schedule_codes <= _KNOWN_CONTRIBUTION_SCHEDULE_CODES


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

    def test_expenditure_fixture_rows_are_schedule_f(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        schedule_codes = {row["filing_sched_abbrev"] for row in parser}
        assert schedule_codes == {"F"}

    def test_fixture_schedule_codes_stay_within_known_cf01_range(self) -> None:
        contribution_rows = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        expenditure_rows = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        schedule_codes = {row["filing_sched_abbrev"] for row in (*contribution_rows, *expenditure_rows)}
        assert schedule_codes <= _KNOWN_CF01_SCHEDULE_CODES


class TestNYParseIndependentExpenditures:
    """Test IE CSV parsing and column parity with expenditures."""

    def test_ie_columns_equal_expenditure_columns(self) -> None:
        assert IE_COLUMNS == EXPENDITURE_COLUMNS

    def test_ie_columns_has_45_fields(self) -> None:
        assert len(IE_COLUMNS) == 45

    def test_parse_sample_ie_yields_two_rows(self) -> None:
        parser = parse_independent_expenditures(_FIXTURES_DIR / "sample_ie.csv")
        rows = list(parser)
        assert len(rows) == 2

    def test_ie_first_row_has_expected_values(self) -> None:
        parser = parse_independent_expenditures(_FIXTURES_DIR / "sample_ie.csv")
        row = next(iter(parser))
        assert row["filer_id"] == "99001"
        assert row["cand_comm_name"] == "NY Future PAC"
        assert row["filing_cat_desc"] == "IE 24 Hour/Weekly Notices"
        assert row["filing_sched_abbrev"] == "J"
        assert row["flng_ent_name"] == "Metro Media Group"
        assert row["org_amt"] == "15000.00"

    def test_ie_fixture_all_rows_have_ie_filing_cat(self) -> None:
        parser = parse_independent_expenditures(_FIXTURES_DIR / "sample_ie.csv")
        filing_cats = {row["filing_cat_desc"] for row in parser}
        assert filing_cats == {"IE 24 Hour/Weekly Notices"}

    def test_ie_fixture_schedule_codes_within_cf01_range(self) -> None:
        parser = parse_independent_expenditures(_FIXTURES_DIR / "sample_ie.csv")
        schedule_codes = {row["filing_sched_abbrev"] for row in parser}
        assert schedule_codes <= _KNOWN_CF01_SCHEDULE_CODES


class TestNYParserRejectsInvalidHeader:
    """Test that the parser rejects CSVs with unexpected headers."""

    def test_wrong_header_raises_value_error(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "bad_header.csv"
        csv_path.write_text("wrong_col1,wrong_col2\nval1,val2\n")
        parser = NYCsvParser(path=csv_path, columns=CONTRIBUTION_COLUMNS, row_label="test")
        with pytest.raises(ValueError, match="Unexpected NY test CSV header"):
            list(parser)
