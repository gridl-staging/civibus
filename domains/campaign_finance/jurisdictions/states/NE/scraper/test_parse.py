from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

import pytest

from domains.campaign_finance.jurisdictions.states.NE.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.NE.scraper import parse as ne_parse
from domains.campaign_finance.jurisdictions.states.NE.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    LOAN_COLUMNS,
    parse_contributions,
    parse_expenditures,
    parse_loans,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTION_LOAN_PATH = _FIXTURE_DIR / "sample_contribution_loan.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _rows_to_csv_payload(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return output.getvalue()


def _build_zip_with_members(zip_path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(zip_path, mode="w") as archive:
        for member_name, payload in members.items():
            archive.writestr(member_name, payload)


def test_columns_derive_from_ne_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert LOAN_COLUMNS == _load_columns_for_data_type("loans")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")


def test_parse_contributions_filters_loan_rows_and_year_window() -> None:
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTION_LOAN_PATH, year=2026, year_from=2022))

    assert len(rows) == 1
    assert rows[0]["Receipt Transaction/Contribution Type"] == "Monetary"
    assert rows[0]["Receipt Date"].endswith("2026")


def test_parse_loans_filters_to_loan_rows_in_same_extract() -> None:
    rows = list(parse_loans(_SAMPLE_CONTRIBUTION_LOAN_PATH, year=2026, year_from=2022))

    assert len(rows) == 2
    assert all("loan" in (row["Receipt Transaction/Contribution Type"] or "").lower() for row in rows)


def test_parse_expenditures_filters_year_window() -> None:
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year=2026, year_from=2022))

    assert len(rows) == 3
    assert all(row["Expenditure Date"].endswith("2026") for row in rows)


def test_parse_normalizes_empty_strings_to_none() -> None:
    rows = list(parse_loans(_SAMPLE_CONTRIBUTION_LOAN_PATH, year=2026, year_from=2022))

    assert rows[0]["Other Funds Type"] is None


def test_parse_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad-header.csv"
    rows = _read_rows(_SAMPLE_CONTRIBUTION_LOAN_PATH)
    bad_columns = list(CONTRIBUTION_COLUMNS)
    bad_columns[0] = "wrongColumn"

    with bad_header_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=bad_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(rows[0])

    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parse_contributions(bad_header_path, year=2026, year_from=2022))


def test_parse_selects_exact_member_name_for_requested_year(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTION_LOAN_PATH)
    zip_path = tmp_path / "ne_contrib.zip"
    _build_zip_with_members(
        zip_path,
        {
            "2025_ContributionLoanExtract.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, [fixture_rows[0]]),
            "2026_ContributionLoanExtract.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, [fixture_rows[1]]),
        },
    )

    rows = list(parse_contributions(zip_path, year=2026, year_from=2022))

    assert len(rows) == 1
    assert rows[0]["Receipt ID"] == fixture_rows[1]["Receipt ID"]


def test_parse_rejects_oversized_zip_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTION_LOAN_PATH)[:1]
    payload = _rows_to_csv_payload(CONTRIBUTION_COLUMNS, fixture_rows)
    zip_path = tmp_path / "ne_contrib_oversized.zip"
    _build_zip_with_members(zip_path, {"2026_ContributionLoanExtract.csv": payload})
    monkeypatch.setattr(ne_parse, "MAX_ZIP_MEMBER_BYTES", len(payload) - 1)

    with pytest.raises(ValueError, match="exceeds the allowed size limit"):
        list(parse_contributions(zip_path, year=2026, year_from=2022))
