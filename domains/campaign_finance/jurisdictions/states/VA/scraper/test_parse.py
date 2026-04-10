"""Tests for Virginia CSV parser.

Tests the VACsvParser against real fixture data and validates
column contracts, malformed row handling, and normalization.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.VA.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    REPORT_COLUMNS,
    VACsvParser,
    parse_contributions,
    parse_expenditures,
    parse_reports,
)

# Fixture directory lives next to this test file
_FIXTURE_DIR = Path(__file__).resolve().parent / "test_fixtures"


def _write_fixture(path: Path, *, header: tuple[str, ...], rows: list[list[str]]) -> None:
    """Write a simple CSV with the given header and rows."""
    payload_lines = [",".join(f'"{col}"' for col in header)]
    for row in rows:
        payload_lines.append(",".join(f'"{val}"' for val in row))
    payload_lines.append("")
    path.write_text("\n".join(payload_lines), encoding="utf-8")


def _valid_row(columns: tuple[str, ...]) -> list[str]:
    """Generate a synthetic valid row with placeholder values."""
    return [f"value_{index}" for index in range(len(columns))]


# --- Column contract tests ---


def test_contribution_columns_match_verified_contract_shape() -> None:
    """ScheduleA has 22 columns, starting with ReportId and ending with ReportUID."""
    assert len(CONTRIBUTION_COLUMNS) == 22
    assert CONTRIBUTION_COLUMNS[0] == "ReportId"
    assert CONTRIBUTION_COLUMNS[-1] == "ReportUID"


def test_expenditure_columns_match_verified_contract_shape() -> None:
    """ScheduleD has 20 columns, starting with ScheduleDId and ending with ReportUID."""
    assert len(EXPENDITURE_COLUMNS) == 20
    assert EXPENDITURE_COLUMNS[0] == "ScheduleDId"
    assert EXPENDITURE_COLUMNS[-1] == "ReportUID"


def test_report_columns_match_verified_contract_shape() -> None:
    """Report.csv has 39 columns, starting with ReportId and ending with ReportUID."""
    assert len(REPORT_COLUMNS) == 39
    assert REPORT_COLUMNS[0] == "ReportId"
    assert REPORT_COLUMNS[-1] == "ReportUID"


# --- Fixture parsing tests ---


def test_parse_contributions_reads_fixture_rows() -> None:
    """Parse the real sample_contributions.csv fixture and verify row count."""
    fixture_path = _FIXTURE_DIR / "sample_contributions.csv"
    parser = parse_contributions(fixture_path)
    rows = list(parser)
    # Fixture has 5 contribution rows
    assert len(rows) == 5
    assert parser.skipped == 0


def test_parse_contributions_extracts_expected_fields_from_fixture() -> None:
    """Verify key field values from the first fixture row."""
    fixture_path = _FIXTURE_DIR / "sample_contributions.csv"
    rows = list(parse_contributions(fixture_path))

    first_row = rows[0]
    assert first_row["ReportId"] == "297173"
    assert first_row["FirstName"] == "LaVonne"
    assert first_row["LastOrCompanyName"] == "Benton"
    assert first_row["Amount"] == "200.00"
    assert first_row["IsIndividual"] == "True"
    assert first_row["City"] == "Hampton"
    assert first_row["StateCode"] == "VA"


def test_parse_expenditures_reads_fixture_rows() -> None:
    """Parse the real sample_expenditures.csv fixture and verify row count."""
    fixture_path = _FIXTURE_DIR / "sample_expenditures.csv"
    parser = parse_expenditures(fixture_path)
    rows = list(parser)
    # Fixture has 5 expenditure rows
    assert len(rows) == 5
    assert parser.skipped == 0


def test_parse_expenditures_extracts_expected_fields_from_fixture() -> None:
    """Verify key field values from the third fixture row (org expenditure)."""
    fixture_path = _FIXTURE_DIR / "sample_expenditures.csv"
    rows = list(parse_expenditures(fixture_path))

    # Third row is Cardwell Printing (an org, IsIndividual=False)
    org_row = rows[2]
    assert org_row["LastOrCompanyName"] == "Cardwell Printing"
    assert org_row["IsIndividual"] == "False"
    assert org_row["ItemOrService"] == "Palm Cards"
    assert org_row["Amount"] == "465.42"


def test_parse_reports_reads_fixture_rows() -> None:
    """Parse the real sample_reports.csv fixture and verify row count."""
    fixture_path = _FIXTURE_DIR / "sample_reports.csv"
    parser = parse_reports(fixture_path)
    rows = list(parser)
    # Fixture has 5 report rows
    assert len(rows) == 5
    assert parser.skipped == 0


def test_parse_reports_extracts_expected_fields_from_fixture() -> None:
    """Verify key field values from the first fixture row."""
    fixture_path = _FIXTURE_DIR / "sample_reports.csv"
    rows = list(parse_reports(fixture_path))

    first_row = rows[0]
    assert first_row["CommitteeCode"] == "CC-26-00123"
    assert first_row["CommitteeName"] == "Friends of Andrew Rice"
    assert first_row["CommitteeType"] == "Candidate Campaign Committee"
    assert first_row["Party"] == "Republican"
    assert first_row["OfficeSought"] == "Member, House Of Delegates"


# --- Normalization and error handling tests ---


def test_parse_contributions_normalizes_empty_strings_to_none(tmp_path: Path) -> None:
    """Empty string CSV values should become None in parsed output."""
    fixture_path = tmp_path / "contributions.csv"
    row = _valid_row(CONTRIBUTION_COLUMNS)
    # MiddleName (index 3) set to empty
    row[3] = ""
    _write_fixture(fixture_path, header=CONTRIBUTION_COLUMNS, rows=[row])

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert rows[0]["MiddleName"] is None


@pytest.mark.parametrize(
    ("parse_func", "header"),
    [
        (parse_contributions, CONTRIBUTION_COLUMNS),
        (parse_expenditures, EXPENDITURE_COLUMNS),
        (parse_reports, REPORT_COLUMNS),
    ],
)
def test_parse_rejects_unexpected_header(tmp_path: Path, parse_func, header: tuple[str, ...]) -> None:
    """Parser should raise ValueError when CSV header doesn't match expected columns."""
    fixture_path = tmp_path / "bad-header.csv"
    bad_header = list(header)
    bad_header[0] = "WrongColumn"
    _write_fixture(fixture_path, header=tuple(bad_header), rows=[_valid_row(header)])

    parser = parse_func(fixture_path)

    with pytest.raises(ValueError, match="Unexpected"):
        list(parser)


def test_parse_skips_malformed_rows(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Rows with too few or too many columns should be skipped with a warning."""
    fixture_path = tmp_path / "contributions.csv"
    good_row = _valid_row(CONTRIBUTION_COLUMNS)
    # Malformed row: missing the last column
    malformed_row = _valid_row(CONTRIBUTION_COLUMNS)[:-1]
    _write_fixture(fixture_path, header=CONTRIBUTION_COLUMNS, rows=[good_row, malformed_row])

    parser = parse_contributions(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text


def test_parser_returns_va_csv_parser_instance() -> None:
    """parse_contributions etc. should return VACsvParser instances."""
    fixture_path = _FIXTURE_DIR / "sample_contributions.csv"
    parser = parse_contributions(fixture_path)
    assert isinstance(parser, VACsvParser)
