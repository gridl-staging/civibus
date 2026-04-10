from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.cities.SF.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.cities.SF.scraper.parse import (
    SF_TRANSACTION_COLUMNS,
    SFCsvParser,
    parse_sf_amount,
    parse_sf_date,
    parse_transactions,
)

_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "sample_transactions.csv"

_AMOUNT_FIELDS = (
    "calculated_amount",
    "transaction_amount_1",
    "transaction_amount_2",
    "loan_amount_1",
    "loan_amount_2",
    "loan_amount_3",
    "loan_amount_4",
    "loan_amount_5",
    "loan_amount_6",
    "loan_amount_7",
    "loan_amount_8",
)
_DATE_FIELDS = (
    "filing_date",
    "start_date",
    "end_date",
    "calculated_date",
    "transaction_date",
    "transaction_date_1",
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(SF_TRANSACTION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def test_transaction_columns_derive_from_config() -> None:
    assert SF_TRANSACTION_COLUMNS == _load_columns_for_data_type("transactions")


def test_parse_transactions_yields_rows_from_fixture() -> None:
    parser = parse_transactions(_FIXTURE_PATH)
    rows = list(parser)

    assert len(rows) == 10


def test_parser_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad_header.csv"
    fixture_rows = _read_rows(_FIXTURE_PATH)
    bad_columns = list(SF_TRANSACTION_COLUMNS)
    bad_columns[0] = "wrong_column"

    with bad_header_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=bad_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(fixture_rows[0])

    parser = SFCsvParser(path=bad_header_path, columns=SF_TRANSACTION_COLUMNS, row_label="transaction", year_from=2022)
    with pytest.raises(ValueError, match="Unexpected SF transaction CSV header"):
        list(parser)


def test_parse_transactions_normalizes_empty_strings_to_none() -> None:
    row = next(iter(parse_transactions(_FIXTURE_PATH)))

    assert row["start_date"] is None
    assert row["transaction_amount_2"] is None
    assert row["loan_amount_8"] is None


def test_parse_sf_amount_parses_and_normalizes_empty() -> None:
    assert parse_sf_amount("1,234.50") == Decimal("1234.50")
    assert parse_sf_amount("") is None
    assert parse_sf_amount(None) is None


def test_parse_sf_date_parses_iso_timestamp_and_empty() -> None:
    assert parse_sf_date("2026-03-30T00:00:00.000") == date(2026, 3, 30)
    assert parse_sf_date("2026-03-30") == date(2026, 3, 30)
    assert parse_sf_date("") is None
    assert parse_sf_date(None) is None


def test_parse_transactions_casts_amount_and_date_fields() -> None:
    row = next(iter(parse_transactions(_FIXTURE_PATH)))

    for field in _AMOUNT_FIELDS:
        value = row[field]
        assert value is None or isinstance(value, Decimal), field

    for field in _DATE_FIELDS:
        value = row[field]
        assert value is None or isinstance(value, date), field


def test_parse_transactions_filters_rows_older_than_year_from(tmp_path: Path) -> None:
    filtered_fixture_path = tmp_path / "transactions_year_filter.csv"
    rows = _read_rows(_FIXTURE_PATH)[:2]
    rows[0]["transaction_date"] = "2021-12-31T00:00:00.000"
    rows[1]["transaction_date"] = "2022-01-01T00:00:00.000"
    _write_rows(filtered_fixture_path, rows)

    parsed = list(parse_transactions(filtered_fixture_path, year_from=2022))

    assert len(parsed) == 1
    assert parsed[0]["transaction_date"] == date(2022, 1, 1)
