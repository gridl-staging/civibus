from __future__ import annotations

import csv
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.OH.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.OH.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _write_csv(path: Path, *, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def test_columns_derive_from_oh_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")


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
    assert rows[0]["SUFFIX_NAME"] is None
    assert rows[0]["NON_INDIVIDUAL"] is None


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


def test_parse_uses_utf8_replace_error_handling(tmp_path: Path) -> None:
    encoded_path = tmp_path / "invalid-utf8.csv"
    row_values = [b"value" for _ in CONTRIBUTION_COLUMNS]
    row_values[0] = b"Committee \xff Name"

    encoded_path.write_bytes(",".join(CONTRIBUTION_COLUMNS).encode("utf-8") + b"\n" + b",".join(row_values) + b"\n")

    rows = list(parse_contributions(encoded_path))

    assert rows[0]["COM_NAME"] == "Committee \ufffd Name"


def test_parse_normalizes_documented_secondary_null_markers_to_none(tmp_path: Path) -> None:
    secondary_null_path = tmp_path / "secondary-nulls.csv"
    rows = [
        {
            "COM_NAME": "NA Committee",
            "FIRST_NAME": "NA",
            "MIDDLE_NAME": "N/A",
            "LAST_NAME": "Person",
        }
    ]
    _write_csv(secondary_null_path, columns=CONTRIBUTION_COLUMNS, rows=rows)

    parsed_rows = list(parse_contributions(secondary_null_path))

    assert parsed_rows[0]["COM_NAME"] == "NA Committee"
    assert parsed_rows[0]["FIRST_NAME"] is None
    assert parsed_rows[0]["MIDDLE_NAME"] is None
    assert parsed_rows[0]["LAST_NAME"] == "Person"


def test_parse_expenditures_reads_expected_rows() -> None:
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))

    assert len(rows) == 3
    assert rows[0]["OFFICE_SOUGHT"] == "State Representative"
