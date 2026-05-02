"""Tests for MA report-items parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.MA.scraper.parse import (
    REPORT_ITEM_COLUMNS,
    MAReportItemParser,
    parse_contributions,
    parse_expenditures,
    parse_all_items,
)

_FIXTURES_DIR = Path(__file__).parent / "test_fixtures"


class TestMAParseContributions:
    """Test contribution-filtered parsing."""

    def test_parse_contributions_filters_to_200_series(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_report_items.txt")
        rows = list(parser)
        # Rows with Record_Type_ID 201 and 211 are contributions.
        assert len(rows) == 2

    def test_first_contribution_has_expected_fields(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_report_items.txt")
        row = next(iter(parser))
        assert row["Item_ID"] == "100001"
        assert row["Record_Type_ID"] == "201"
        assert row["Amount"] == "500.00"
        assert row["First_Name"] == "John"
        assert row["Name"] == "Smith"

    def test_parse_contributions_includes_400_series_in_kind_rows(self, tmp_path: Path) -> None:
        tsv_path = tmp_path / "report-items.txt"
        base_row = {column: "" for column in REPORT_ITEM_COLUMNS}
        contribution_row = {
            **base_row,
            "Item_ID": "400001",
            "Record_Type_ID": "401",
            "Date": "02/01/2026",
            "Amount": "75.00",
            "Name": "In Kind Donor",
        }
        expenditure_row = {
            **base_row,
            "Item_ID": "300001",
            "Record_Type_ID": "301",
            "Date": "02/02/2026",
            "Amount": "90.00",
            "Name": "Print Shop",
        }

        def _row_to_line(row: dict[str, str]) -> str:
            return "\t".join(row[column] for column in REPORT_ITEM_COLUMNS)

        lines = [
            "\t".join(REPORT_ITEM_COLUMNS),
            _row_to_line(contribution_row),
            _row_to_line(expenditure_row),
        ]
        tsv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rows = list(parse_contributions(tsv_path))

        assert len(rows) == 1
        assert rows[0]["Item_ID"] == "400001"
        assert rows[0]["Record_Type_ID"] == "401"


class TestMAParseExpenditures:
    """Test expenditure-filtered parsing."""

    def test_parse_expenditures_filters_to_300_series(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_report_items.txt")
        rows = list(parser)
        # Rows with Record_Type_ID 301 are expenditures.
        assert len(rows) == 2

    def test_expenditure_has_schedule_301(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_report_items.txt")
        row = next(iter(parser))
        assert row["Record_Type_ID"] == "301"
        assert row["Amount"] == "2500.00"


class TestMAParseAllItems:
    """Test unfiltered parsing."""

    def test_parse_all_items_returns_all_rows(self) -> None:
        parser = parse_all_items(_FIXTURES_DIR / "sample_report_items.txt")
        rows = list(parser)
        assert len(rows) == 4


class TestMAParseColumns:
    """Test column contract."""

    def test_report_item_columns_has_21_fields(self) -> None:
        assert len(REPORT_ITEM_COLUMNS) == 21

    def test_columns_include_key_fields(self) -> None:
        assert "Item_ID" in REPORT_ITEM_COLUMNS
        assert "Report_ID" in REPORT_ITEM_COLUMNS
        assert "Record_Type_ID" in REPORT_ITEM_COLUMNS
        assert "Amount" in REPORT_ITEM_COLUMNS
        assert "Date" in REPORT_ITEM_COLUMNS


class TestMAParserRejectsInvalidHeader:
    """Test header validation."""

    def test_wrong_header_raises_value_error(self, tmp_path: Path) -> None:
        tsv_path = tmp_path / "bad.txt"
        tsv_path.write_text("col1\tcol2\nval1\tval2\n")
        parser = MAReportItemParser(path=tsv_path, columns=REPORT_ITEM_COLUMNS, row_label="test")
        with pytest.raises(ValueError, match="Unexpected MA test header"):
            list(parser)

    def test_trailing_tab_in_header_is_tolerated(self, tmp_path: Path) -> None:
        """Live OCPF data has a trailing tab producing an empty column."""
        header = "\t".join(REPORT_ITEM_COLUMNS) + "\t\n"
        row = "\t".join([""] * len(REPORT_ITEM_COLUMNS)) + "\t\n"
        tsv_path = tmp_path / "trailing_tab.txt"
        tsv_path.write_text(header + row)
        parser = MAReportItemParser(path=tsv_path, columns=REPORT_ITEM_COLUMNS, row_label="contribution")
        rows = list(parser)
        assert len(rows) == 1
