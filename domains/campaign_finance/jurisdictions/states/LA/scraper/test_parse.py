from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

import pytest

from domains.campaign_finance.jurisdictions.states.LA.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.LA.scraper import parse as la_parse
from domains.campaign_finance.jurisdictions.states.LA.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    LOAN_COLUMNS,
    parse_contributions,
    parse_expenditures,
    parse_loans,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"
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


def test_columns_derive_from_la_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert LOAN_COLUMNS == _load_columns_for_data_type("loans")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")


def test_parse_contributions_filters_year_window() -> None:
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year=2026, year_from=2025))

    assert len(rows) == 2
    assert rows[0]["ContributionDate"].endswith("2025 12:00:00 AM")
    assert rows[1]["ContributionDate"].endswith("2026 12:00:00 AM")


def test_parse_loans_filters_year_window() -> None:
    rows = list(parse_loans(_SAMPLE_LOANS_PATH, year=2026, year_from=2025))

    assert len(rows) == 2
    assert rows[0]["LoanDate"].endswith("2025 12:00:00 AM")
    assert rows[1]["LoanDate"].endswith("2026 12:00:00 AM")


def test_parse_expenditures_filters_year_window() -> None:
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year=2026, year_from=2025))

    assert len(rows) == 4
    assert rows[0]["ExpenditureDate"].endswith("2025 12:00:00 AM")
    assert rows[1]["ExpenditureDate"].endswith("2026 12:00:00 AM")
    assert rows[2]["Schedule"] == "E-2"
    assert rows[3]["Schedule"] == "E-3"


def test_parse_expenditures_preserves_f305_f306_contract_fields(tmp_path: Path) -> None:
    zip_path = tmp_path / "la_expenditures_ie_contract.zip"
    _build_zip_with_members(
        zip_path,
        {
            "Expenditures_2024_to_2027.csv": _rows_to_csv_payload(
                EXPENDITURE_COLUMNS,
                [
                    {
                        "FilerNumber": "4521",
                        "FilerLastName": "Citizens for Progress",
                        "FilerFirstName": "",
                        "ReportCode": "F305",
                        "ReportType": "40G",
                        "ReportNumber": "LA-200001",
                        "Schedule": "E-1",
                        "RecipientName": "ACME MEDIA GROUP",
                        "ExpenditureDescription": "Supports Jane Candidate for Mayor",
                        "CandidateBeneficiary": "Jane Candidate",
                        "ExpenditureDate": "3/15/2026 12:00:00 AM",
                        "ExpenditureAmt": "50000.00",
                    },
                    {
                        "FilerNumber": "4521",
                        "FilerLastName": "Citizens for Progress",
                        "FilerFirstName": "",
                        "ReportCode": "F306",
                        "ReportType": "40G",
                        "ReportNumber": "LA-200002",
                        "Schedule": "E-4",
                        "RecipientName": "DELTA PRINT SHOP",
                        "ExpenditureDescription": "Opposes John Candidate through mailers",
                        "CandidateBeneficiary": "John Candidate",
                        "ExpenditureDate": "4/01/2026 12:00:00 AM",
                        "ExpenditureAmt": "12500.00",
                    },
                ],
            )
        },
    )

    rows = list(parse_expenditures(zip_path, year=2026, year_from=2025))

    assert len(rows) == 2
    assert rows[0]["ReportCode"] == "F305"
    assert rows[0]["CandidateBeneficiary"] == "Jane Candidate"
    assert rows[0]["ExpenditureDescription"] == "Supports Jane Candidate for Mayor"
    assert rows[0]["ExpenditureDate"] == "3/15/2026 12:00:00 AM"
    assert rows[0]["ExpenditureAmt"] == "50000.00"
    assert rows[1]["ReportCode"] == "F306"
    assert rows[1]["CandidateBeneficiary"] == "John Candidate"
    assert rows[1]["ExpenditureDescription"] == "Opposes John Candidate through mailers"
    assert rows[1]["ExpenditureDate"] == "4/01/2026 12:00:00 AM"
    assert rows[1]["ExpenditureAmt"] == "12500.00"


def test_parse_normalizes_empty_strings_to_none() -> None:
    rows = list(parse_loans(_SAMPLE_LOANS_PATH, year=2026, year_from=2025))

    assert rows[1]["LoanHolderAddr2"] is None


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
        list(parse_contributions(bad_header_path, year=2026, year_from=2025))


def test_parse_selects_member_name_range_for_requested_year(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    zip_path = tmp_path / "la_contrib.zip"
    _build_zip_with_members(
        zip_path,
        {
            "Contributions_2020_to_2023.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, [fixture_rows[0]]),
            "Contributions_2024_to_2027.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, [fixture_rows[2]]),
        },
    )

    rows = list(parse_contributions(zip_path, year=2026, year_from=2025))

    assert len(rows) == 1
    assert rows[0]["ReportNumber"] == fixture_rows[2]["ReportNumber"]


def test_parse_rejects_oversized_zip_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_rows = _read_rows(_SAMPLE_EXPENDITURES_PATH)[:1]
    payload = _rows_to_csv_payload(EXPENDITURE_COLUMNS, fixture_rows)
    zip_path = tmp_path / "la_expenditures_oversized.zip"
    _build_zip_with_members(zip_path, {"Expenditures_2024_to_2027.csv": payload})
    monkeypatch.setattr(la_parse, "MAX_ZIP_MEMBER_BYTES", len(payload) - 1)

    with pytest.raises(ValueError, match="exceeds the allowed size limit"):
        list(parse_expenditures(zip_path, year=2026, year_from=2025))
