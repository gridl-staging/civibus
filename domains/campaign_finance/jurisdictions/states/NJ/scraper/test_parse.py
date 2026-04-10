from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.NJ.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    parse_contributions,
)


def _write_fixture(path: Path, *, header: tuple[str, ...], rows: list[list[str]]) -> None:
    payload_lines = [",".join(header)]
    for row in rows:
        payload_lines.append(",".join(row))
    payload_lines.append("")
    path.write_text("\n".join(payload_lines), encoding="utf-8")


def _valid_row(columns: tuple[str, ...]) -> list[str]:
    return [f"value_{index}" for index in range(len(columns))]


def test_contribution_columns_match_verified_elec_api_contract() -> None:
    assert len(CONTRIBUTION_COLUMNS) == 23
    assert CONTRIBUTION_COLUMNS[0] == "IsIndividual"
    assert CONTRIBUTION_COLUMNS[-1] == "ElectionYear"


def test_parse_contributions_reads_rows_and_normalizes_empty_strings(tmp_path: Path) -> None:
    fixture_path = tmp_path / "contributions.csv"
    row = _valid_row(CONTRIBUTION_COLUMNS)
    row[2] = ""  # MI field empty
    _write_fixture(fixture_path, header=CONTRIBUTION_COLUMNS, rows=[row])

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == CONTRIBUTION_COLUMNS
    assert rows[0]["MI"] is None


def test_parse_contributions_rejects_unexpected_header(tmp_path: Path) -> None:
    fixture_path = tmp_path / "bad-header.csv"
    bad_header = list(CONTRIBUTION_COLUMNS)
    bad_header[0] = "Wrong"
    _write_fixture(fixture_path, header=tuple(bad_header), rows=[_valid_row(CONTRIBUTION_COLUMNS)])

    parser = parse_contributions(fixture_path)
    with pytest.raises(ValueError, match="Unexpected contribution CSV header"):
        list(parser)


def test_parse_contributions_skips_malformed_rows_with_extra_fields(tmp_path: Path) -> None:
    fixture_path = tmp_path / "extra-field.csv"
    valid_row = _valid_row(CONTRIBUTION_COLUMNS)
    malformed_row = valid_row + ["extra_value"]
    _write_fixture(fixture_path, header=CONTRIBUTION_COLUMNS, rows=[valid_row, malformed_row])

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1


def test_parse_contributions_skips_malformed_rows_with_missing_fields(tmp_path: Path) -> None:
    fixture_path = tmp_path / "missing-field.csv"
    valid_row = _valid_row(CONTRIBUTION_COLUMNS)
    short_row = valid_row[:-1]
    _write_fixture(fixture_path, header=CONTRIBUTION_COLUMNS, rows=[valid_row, short_row])

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1


def test_sample_fixture_matches_header_shape_and_parses_all_rows() -> None:
    fixture_path = Path(__file__).with_name("test_fixtures") / "sample_contributions.csv"

    parser = parse_contributions(fixture_path)
    rows = list(parser)

    assert len(rows) == 3
    assert parser.skipped == 0
