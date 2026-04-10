from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile

import pytest

from domains.campaign_finance.jurisdictions.states.IN.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.IN.scraper import parse as in_parse
from domains.campaign_finance.jurisdictions.states.IN.scraper.parse import (
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


def _rows_to_csv_payload(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return output.getvalue()


def _build_zip_with_members(zip_path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(zip_path, mode="w") as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)


def test_columns_derive_from_in_config() -> None:
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


def test_parse_reads_plain_csv_fixtures() -> None:
    contribution_rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))
    expenditure_rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))

    assert len(contribution_rows) == 8
    assert len(expenditure_rows) == 9


def test_parse_normalizes_empty_strings_to_none() -> None:
    contribution_rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))
    expenditure_rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))

    assert contribution_rows[0]["CandidateName"] is None
    assert contribution_rows[0]["Description"] is None
    assert expenditure_rows[0]["CandidateName"] is None
    assert expenditure_rows[0]["Description"] is None


def test_parse_reads_single_member_zip_from_downloader_contract(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:2]
    zip_path = tmp_path / "2025_ContributionData.csv.zip"
    _build_zip_with_members(
        zip_path,
        {
            "2025_ContributionData.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, fixture_rows),
        },
    )

    rows = list(parse_contributions(zip_path))

    assert [row["Name"] for row in rows] == [fixture_rows[0]["Name"], fixture_rows[1]["Name"]]


def test_parse_rejects_zip_archives_without_exactly_one_csv_member(tmp_path: Path) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:1]
    zip_path = tmp_path / "2025_ContributionData.csv.zip"
    _build_zip_with_members(
        zip_path,
        {
            "a.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, fixture_rows),
            "b.csv": _rows_to_csv_payload(CONTRIBUTION_COLUMNS, fixture_rows),
        },
    )

    with pytest.raises(ValueError, match="exactly one CSV member"):
        list(parse_contributions(zip_path))


def test_parse_decodes_legacy_single_byte_rows_from_data_semantics(tmp_path: Path) -> None:
    encoded_path = tmp_path / "legacy-single-byte.csv"
    name_index = list(CONTRIBUTION_COLUMNS).index("Name")

    row_values = [b"value" for _ in CONTRIBUTION_COLUMNS]
    row_values[name_index] = b"Cafe\xe9 Donor"
    encoded_path.write_bytes(",".join(CONTRIBUTION_COLUMNS).encode("ascii") + b"\n" + b",".join(row_values) + b"\n")

    rows = list(parse_contributions(encoded_path))

    assert rows[0]["Name"] == "Cafeé Donor"


def test_parse_preserves_non_utf8_cp1252_undefined_byte_via_latin1_fallback(tmp_path: Path) -> None:
    encoded_path = tmp_path / "legacy-undefined-cp1252-byte.csv"
    name_index = list(CONTRIBUTION_COLUMNS).index("Name")

    row_values = [b"value" for _ in CONTRIBUTION_COLUMNS]
    row_values[name_index] = b"Legacy\x81Byte"
    encoded_path.write_bytes(",".join(CONTRIBUTION_COLUMNS).encode("ascii") + b"\n" + b",".join(row_values) + b"\n")

    rows = list(parse_contributions(encoded_path))

    assert rows[0]["Name"] == "Legacy\x81Byte"


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


def test_parse_rejects_oversized_zip_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_rows = _read_rows(_SAMPLE_CONTRIBUTIONS_PATH)[:1]
    payload = _rows_to_csv_payload(CONTRIBUTION_COLUMNS, fixture_rows)
    zip_path = tmp_path / "2025_ContributionData.csv.zip"
    _build_zip_with_members(zip_path, {"2025_ContributionData.csv": payload})
    monkeypatch.setattr(in_parse, "MAX_ZIP_MEMBER_BYTES", len(payload) - 1)

    with pytest.raises(ValueError, match="exceeds the allowed size limit"):
        list(parse_contributions(zip_path))


def test_parse_rejects_oversized_plain_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "oversized.csv"
    csv_path.write_text(",".join(CONTRIBUTION_COLUMNS) + "\nvalue\n", encoding="utf-8")
    monkeypatch.setattr(in_parse, "MAX_ZIP_MEMBER_BYTES", csv_path.stat().st_size - 1)

    with pytest.raises(ValueError, match="IN CSV file 'oversized.csv' exceeds the allowed size limit"):
        list(parse_contributions(csv_path))
