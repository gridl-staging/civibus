from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

import pytest

from domains.campaign_finance.jurisdictions.states.TX.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.TX.scraper import parse as tx_parse
from domains.campaign_finance.jurisdictions.states.TX.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    LOAN_COLUMNS,
    parse_contributions,
    parse_expenditures,
    parse_loans,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _write_csv(path: Path, *, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _build_zip_with_members(zip_path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(zip_path, mode="w") as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)


def _rows_to_csv_payload(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return output.getvalue()


def test_columns_derive_from_tx_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")
    assert LOAN_COLUMNS == _load_columns_for_data_type("loans")


def test_parse_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad-header.csv"
    contributions_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    bad_columns = list(CONTRIBUTION_COLUMNS)
    bad_columns[0] = "wrongColumn"
    _write_csv(bad_header_path, columns=tuple(bad_columns), rows=contributions_rows[:1])

    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parse_contributions(bad_header_path))


def test_parse_normalizes_empty_strings_to_none() -> None:
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))

    assert rows
    assert rows[0]["contributionDescr"] is None
    assert rows[0]["contributorNameOrganization"] is None


def test_parse_skips_rows_with_missing_or_extra_fields(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.csv"
    good_row = [f"value_{index}" for index in range(len(CONTRIBUTION_COLUMNS))]
    missing_field_row = good_row[:-1]
    extra_field_row = [*good_row, "too_many_fields"]
    malformed_path.write_text(
        "\n".join(
            [
                ",".join(CONTRIBUTION_COLUMNS),
                ",".join(good_row),
                ",".join(missing_field_row),
                ",".join(extra_field_row),
                "",
            ]
        ),
        encoding="utf-8",
    )

    parser = parse_contributions(malformed_path)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 2


def test_parse_contributions_concatenates_split_members_in_sorted_order(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:2]
    zip_path = tmp_path / "tx_contribs.zip"
    _build_zip_with_members(
        zip_path,
        {
            "contribs_02.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, [fixture_rows[1]]),
            "contribs_01.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, [fixture_rows[0]]),
        },
    )

    rows = list(parse_contributions(zip_path))

    assert [row["contributionInfoId"] for row in rows] == [
        fixture_rows[0]["contributionInfoId"],
        fixture_rows[1]["contributionInfoId"],
    ]


def test_parse_expenditures_concatenates_split_members_in_sorted_order(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_EXPENDITURES_PATH)[:2]
    zip_path = tmp_path / "tx_expend.zip"
    _build_zip_with_members(
        zip_path,
        {
            "expend_10.csv": _rows_to_csv_payload(EXPENDITURE_COLUMNS, [fixture_rows[1]]),
            "expend_01.csv": _rows_to_csv_payload(EXPENDITURE_COLUMNS, [fixture_rows[0]]),
        },
    )

    rows = list(parse_expenditures(zip_path))

    assert [row["expendInfoId"] for row in rows] == [
        fixture_rows[0]["expendInfoId"],
        fixture_rows[1]["expendInfoId"],
    ]


def test_split_member_inputs_match_single_fixture_rows_for_contributions_and_expenditures(tmp_path: Path) -> None:
    contribution_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    expenditure_rows = _read_rows(_SAMPLE_EXPENDITURES_PATH)

    contribution_zip = tmp_path / "contrib_split.zip"
    expenditure_zip = tmp_path / "expend_split.zip"

    midpoint_contrib = len(contribution_rows) // 2
    midpoint_expend = len(expenditure_rows) // 2

    _build_zip_with_members(
        contribution_zip,
        {
            "contribs_02.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, contribution_rows[midpoint_contrib:]),
            "contribs_01.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, contribution_rows[:midpoint_contrib]),
        },
    )
    _build_zip_with_members(
        expenditure_zip,
        {
            "expend_02.csv": _rows_to_csv_payload(EXPENDITURE_COLUMNS, expenditure_rows[midpoint_expend:]),
            "expend_01.csv": _rows_to_csv_payload(EXPENDITURE_COLUMNS, expenditure_rows[:midpoint_expend]),
        },
    )

    assert list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH)) == list(parse_contributions(contribution_zip))
    assert list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH)) == list(parse_expenditures(expenditure_zip))


def test_parse_contributions_filters_by_year_from(tmp_path: Path) -> None:
    """year_from filters out rows with contributionDt before the cutoff year."""
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    # Fixture dates are 2008/2009. Filtering from 2009 should keep only 2009+ rows.
    old_rows = [r for r in fixture_rows if r["contributionDt"][:4] == "2008"]
    new_rows = [r for r in fixture_rows if r["contributionDt"][:4] == "2009"]

    assert len(old_rows) > 0, "Need 2008 rows in fixture for this test"
    assert len(new_rows) > 0, "Need 2009 rows in fixture for this test"

    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2009))

    assert len(rows) == len(new_rows)
    assert all(r["contributionDt"][:4] >= "2009" for r in rows)


def test_parse_contributions_no_filter_returns_all_rows() -> None:
    """Without year_from, all rows are returned (backwards compatible)."""
    all_rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))
    no_filter_rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=None))

    assert len(all_rows) == len(no_filter_rows)


def test_parse_expenditures_filters_by_year_from(tmp_path: Path) -> None:
    """year_from filters expenditure rows by expendDt."""
    fixture_rows = _read_rows(_SAMPLE_EXPENDITURES_PATH)
    # Fixture expenditure dates are 2006/2007
    rows_2007 = [r for r in fixture_rows if r["expendDt"][:4] == "2007"]

    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2007))

    assert len(rows) == len(rows_2007)


def test_parse_loans_filters_by_year_from() -> None:
    """year_from filters loan rows by loanDt."""
    # Fixture loan dates are 2013+. Filtering from 2020 should return none.
    rows = list(parse_loans(_SAMPLE_LOANS_PATH, year_from=2020))

    assert len(rows) == 0


def test_parse_rejects_oversized_zip_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:1]
    payload = _rows_to_csv_payload(CONTRIBUTION_COLUMNS, fixture_rows)
    zip_path = tmp_path / "tx_contrib_oversized.zip"
    _build_zip_with_members(zip_path, {"contribs_01.csv": payload})
    monkeypatch.setattr(tx_parse, "MAX_ZIP_MEMBER_BYTES", len(payload) - 1)

    with pytest.raises(ValueError, match="exceeds the allowed size limit"):
        list(parse_contributions(zip_path))


def test_parse_loans_accepts_single_loans_member_zip(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_LOANS_PATH)[:2]
    zip_path = tmp_path / "tx_loans.zip"
    _build_zip_with_members(
        zip_path,
        {
            "loans.csv": _rows_to_csv_payload(LOAN_COLUMNS, fixture_rows),
        },
    )

    rows = list(parse_loans(zip_path))

    assert [row["loanInfoId"] for row in rows] == [
        fixture_rows[0]["loanInfoId"],
        fixture_rows[1]["loanInfoId"],
    ]
