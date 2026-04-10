from __future__ import annotations

import csv
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.FL.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.FL.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    OTHER_COLUMNS,
    TRANSFER_COLUMNS,
    parse_contributions,
    parse_expenditures,
    parse_other,
    parse_transfers,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.txt"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.txt"
_SAMPLE_TRANSFERS_PATH = _FIXTURE_DIR / "sample_transfers.txt"
_SAMPLE_OTHER_PATH = _FIXTURE_DIR / "sample_other.txt"


def _read_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as tsv_file:
        return list(csv.DictReader(tsv_file, delimiter="\t"))


def _write_tsv(path: Path, *, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as tsv_file:
        writer = csv.DictWriter(
            tsv_file,
            fieldnames=list(columns),
            delimiter="\t",
            lineterminator="\r\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def test_columns_derive_from_fl_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")
    assert TRANSFER_COLUMNS == _load_columns_for_data_type("transfers")
    assert OTHER_COLUMNS == _load_columns_for_data_type("other")


def test_parse_fixture_round_trip_for_all_four_data_types() -> None:
    contributions = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))
    expenditures = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))
    transfers = list(parse_transfers(_SAMPLE_TRANSFERS_PATH))
    other = list(parse_other(_SAMPLE_OTHER_PATH))

    assert len(contributions) == 2
    assert contributions[0]["Typ"] == "CHE"
    assert contributions[0]["Contributor Name"] == '"STAATS, MD" NANCY'

    assert len(expenditures) == 2
    assert expenditures[0]["Type"] == "MON"
    assert expenditures[1]["Payee Name"] == "AAIM CONSULTING SERVICES"

    assert len(transfers) == 1
    assert transfers[0]["Nature Of Account"] == "MM"

    assert len(other) == 2
    assert other[0]["Distributed To"] == "AIR CANADA"


def test_parse_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad-header.txt"
    contribution_rows = _read_tsv_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    bad_columns = list(CONTRIBUTION_COLUMNS)
    bad_columns[0] = "Wrong Header"
    _write_tsv(bad_header_path, columns=tuple(bad_columns), rows=contribution_rows[:1])

    with pytest.raises(ValueError, match="Unexpected contribution TSV header"):
        list(parse_contributions(bad_header_path))


def test_parse_handles_tab_delimited_crlf_input(tmp_path: Path) -> None:
    path = tmp_path / "crlf.txt"
    rows = [
        {
            "Candidate/Committee": "Committee A",
            "Date": "07/10/2024",
            "Amount": "10.00",
            "Typ": "CHE",
            "Contributor Name": "DONOR A",
            "Address": "123 MAIN ST",
            "City State Zip": "TALLAHASSEE, FL 32301",
            "Occupation": "ENGINEER",
            "Inkind Desc": "",
        }
    ]
    _write_tsv(path, columns=CONTRIBUTION_COLUMNS, rows=rows)

    parsed_rows = list(parse_contributions(path))

    assert len(parsed_rows) == 1
    assert parsed_rows[0]["Candidate/Committee"] == "Committee A"
    assert parsed_rows[0]["Inkind Desc"] is None


def test_parse_normalizes_empty_trailing_fields_to_none() -> None:
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))

    assert rows
    assert rows[0]["Inkind Desc"] is None


def test_parse_skips_rows_with_missing_or_extra_fields(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.txt"
    good_row = [f"value_{index}" for index in range(len(CONTRIBUTION_COLUMNS))]
    missing_field_row = good_row[:-1]
    extra_field_row = [*good_row, "too_many_fields"]
    malformed_path.write_text(
        "\r\n".join(
            [
                "\t".join(CONTRIBUTION_COLUMNS),
                "\t".join(good_row),
                "\t".join(missing_field_row),
                "\t".join(extra_field_row),
                "",
            ]
        ),
        encoding="utf-8",
    )

    parser = parse_contributions(malformed_path)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 2
