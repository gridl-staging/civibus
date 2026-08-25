from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.WA.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    INDEPENDENT_EXPENDITURE_COLUMNS,
    LOAN_COLUMNS,
    parse_contributions,
    parse_expenditures,
    parse_independent_expenditures,
    parse_loans,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_MIXED_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "mixed_record_classes_independent_expenditures.csv"
_SAMPLE_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_independent_expenditures.csv"


def _write_fixture(path: Path, *, header: tuple[str, ...], rows: list[list[str]]) -> None:
    payload_lines = [",".join(header)]
    for row in rows:
        payload_lines.append(",".join(row))
    payload_lines.append("")
    path.write_text("\n".join(payload_lines), encoding="utf-8")


def _valid_row(columns: tuple[str, ...]) -> list[str]:
    return [f"value_{index}" for index in range(len(columns))]


def test_contribution_columns_match_expected_shape_from_config() -> None:
    assert len(CONTRIBUTION_COLUMNS) == 37
    assert CONTRIBUTION_COLUMNS[0] == "id"
    assert CONTRIBUTION_COLUMNS[-1] == "contributor_location"


def test_expenditure_columns_match_expected_shape_from_config() -> None:
    assert len(EXPENDITURE_COLUMNS) == 32
    assert EXPENDITURE_COLUMNS[0] == "id"
    assert EXPENDITURE_COLUMNS[-1] == "creditor"


def test_loan_columns_match_expected_shape_from_config() -> None:
    assert len(LOAN_COLUMNS) == 37
    assert LOAN_COLUMNS[0] == "id"
    assert LOAN_COLUMNS[-1] == "description"


def test_independent_expenditure_columns_match_expected_shape_from_config() -> None:
    assert len(INDEPENDENT_EXPENDITURE_COLUMNS) == 62
    assert INDEPENDENT_EXPENDITURE_COLUMNS[0] == "id"
    assert INDEPENDENT_EXPENDITURE_COLUMNS[-1] == "filer_id"


def test_parse_independent_expenditures_reads_committed_fixture() -> None:
    parser = parse_independent_expenditures(_SAMPLE_INDEPENDENT_EXPENDITURES_PATH)
    rows = list(parser)

    assert len(rows) == 2
    assert tuple(rows[0].keys()) == INDEPENDENT_EXPENDITURE_COLUMNS
    assert rows[0]["for_or_against"] == "For"
    assert rows[1]["for_or_against"] == "Against"


def test_parse_independent_expenditures_preserves_mixed_record_class_shapes() -> None:
    rows = list(parse_independent_expenditures(_MIXED_INDEPENDENT_EXPENDITURES_PATH))

    assert len(rows) == 7
    assert tuple(rows[0].keys()) == INDEPENDENT_EXPENDITURE_COLUMNS
    assert Counter(row["origin"] for row in rows) == {
        "C6.2 - Itemized Expenditures": 2,
        "C6.3 - Identified Entities": 3,
        "C6.5 - Funding Sources": 2,
    }

    c62_rows = [row for row in rows if row["origin"] == "C6.2 - Itemized Expenditures"]
    assert {row["expenditure_amount"] for row in c62_rows} == {"30.90", "9204.71"}
    assert all(row["portion_of_amount"] is None and row["amount"] is None for row in c62_rows)

    c63_rows = [row for row in rows if row["origin"] == "C6.3 - Identified Entities"]
    assert {(row["for_or_against"], row["portion_of_amount"]) for row in c63_rows} == {
        ("For", "25000.00"),
        ("Against", "8450.00"),
        (None, "2787.86"),
    }
    assert all(row["expenditure_amount"] is None and row["amount"] is None for row in c63_rows)

    c65_rows = [row for row in rows if row["origin"] == "C6.5 - Funding Sources"]
    assert {(row["funders_name"], row["date_received"], row["amount"]) for row in c65_rows} == {
        ("SEIU WASHINGTON STATE COUNCIL PAC", "2026-06-03T00:00:00.000", "100000.00"),
        ("JUSTICE FOR ALL PAC", "2026-06-17T00:00:00.000", "100000.00"),
    }
    assert all(row["expenditure_amount"] is None for row in c65_rows)
    assert {row["for_or_against"] for row in rows} == {"For", "Against", None}


def test_parse_contributions_reads_rows_and_normalizes_empty_strings(tmp_path: Path) -> None:
    fixture_path = tmp_path / "contributions.csv"
    row = _valid_row(CONTRIBUTION_COLUMNS)
    row[2] = ""
    _write_fixture(fixture_path, header=CONTRIBUTION_COLUMNS, rows=[row])

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == CONTRIBUTION_COLUMNS
    assert rows[0]["origin"] is None


@pytest.mark.parametrize(
    "parse_func, header",
    [
        (parse_contributions, CONTRIBUTION_COLUMNS),
        (parse_expenditures, EXPENDITURE_COLUMNS),
        (parse_loans, LOAN_COLUMNS),
        (parse_independent_expenditures, INDEPENDENT_EXPENDITURE_COLUMNS),
    ],
)
def test_parse_rejects_unexpected_header(
    tmp_path: Path,
    parse_func,
    header: tuple[str, ...],
) -> None:
    fixture_path = tmp_path / "bad-header.csv"
    bad_header = list(header)
    bad_header[0] = "Wrong"
    _write_fixture(fixture_path, header=tuple(bad_header), rows=[_valid_row(header)])

    parser = parse_func(fixture_path)

    with pytest.raises(ValueError, match="Unexpected"):
        list(parser)


@pytest.mark.parametrize(
    "parse_func, header, row_label",
    [
        (parse_contributions, CONTRIBUTION_COLUMNS, "contribution"),
        (parse_expenditures, EXPENDITURE_COLUMNS, "expenditure"),
        (parse_loans, LOAN_COLUMNS, "loan"),
        (parse_independent_expenditures, INDEPENDENT_EXPENDITURE_COLUMNS, "independent_expenditure"),
    ],
)
def test_parse_skips_malformed_rows(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    parse_func,
    header: tuple[str, ...],
    row_label: str,
) -> None:
    fixture_path = tmp_path / f"{row_label}.csv"
    good_row = _valid_row(header)
    malformed_row = _valid_row(header)[:-1]
    _write_fixture(fixture_path, header=header, rows=[good_row, malformed_row])

    parser = parse_func(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text
