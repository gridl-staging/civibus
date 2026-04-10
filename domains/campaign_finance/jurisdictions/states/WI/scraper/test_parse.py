from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.WI.scraper.parse import (
    COMMITTEE_COLUMNS,
    REPORT_COLUMNS,
    TRANSACTION_COLUMNS,
    parse_committees,
    parse_reports,
    parse_transactions,
)


def _write_fixture(path: Path, *, header: tuple[str, ...], rows: list[list[str]]) -> None:
    payload_lines = [",".join(header)]
    for row in rows:
        payload_lines.append(",".join(row))
    payload_lines.append("")
    path.write_text("\n".join(payload_lines), encoding="utf-8")


def _valid_row(columns: tuple[str, ...]) -> list[str]:
    return [f"value_{index}" for index in range(len(columns))]


def test_transactions_columns_match_verified_contract_shape() -> None:
    assert len(TRANSACTION_COLUMNS) == 61
    assert TRANSACTION_COLUMNS[0] == "ID"
    assert TRANSACTION_COLUMNS[-1] == "Reports"


def test_reports_columns_match_verified_contract_shape() -> None:
    assert len(REPORT_COLUMNS) == 17
    assert REPORT_COLUMNS[0] == "ID"
    assert REPORT_COLUMNS[-1] == "Amended"


def test_committees_columns_match_verified_contract_shape() -> None:
    assert len(COMMITTEE_COLUMNS) == 13
    assert COMMITTEE_COLUMNS[0] == "Registrant ID"
    assert COMMITTEE_COLUMNS[-1] == "Ballot events"


def test_parse_transactions_reads_rows_and_normalizes_empty_strings(tmp_path: Path) -> None:
    fixture_path = tmp_path / "transactions.csv"
    row = _valid_row(TRANSACTION_COLUMNS)
    row[3] = ""
    _write_fixture(fixture_path, header=TRANSACTION_COLUMNS, rows=[row])

    parser = parse_transactions(fixture_path)
    rows = list(parser)

    assert len(rows) == 1
    assert tuple(rows[0].keys()) == TRANSACTION_COLUMNS
    assert rows[0]["Comment"] is None


@pytest.mark.parametrize(
    ("parse_func", "header"),
    [
        (parse_transactions, TRANSACTION_COLUMNS),
        (parse_reports, REPORT_COLUMNS),
        (parse_committees, COMMITTEE_COLUMNS),
    ],
)
def test_parse_rejects_unexpected_header(tmp_path: Path, parse_func, header: tuple[str, ...]) -> None:
    fixture_path = tmp_path / "bad-header.csv"
    bad_header = list(header)
    bad_header[0] = "Wrong"
    _write_fixture(fixture_path, header=tuple(bad_header), rows=[_valid_row(header)])

    parser = parse_func(fixture_path)

    with pytest.raises(ValueError, match="Unexpected"):
        list(parser)


def test_parse_skips_malformed_rows(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    fixture_path = tmp_path / "transactions.csv"
    good_row = _valid_row(TRANSACTION_COLUMNS)
    malformed_row = _valid_row(TRANSACTION_COLUMNS)[:-1]
    _write_fixture(fixture_path, header=TRANSACTION_COLUMNS, rows=[good_row, malformed_row])

    parser = parse_transactions(fixture_path)

    with caplog.at_level("WARNING"):
        rows = list(parser)

    assert len(rows) == 1
    assert parser.skipped == 1
    assert "line 3" in caplog.text
