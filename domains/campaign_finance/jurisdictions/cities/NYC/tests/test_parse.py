"""Unit tests for the NYC CSV parser."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.cities.NYC.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.cities.NYC.scraper.parse import (
    NYC_TRANSACTION_COLUMNS,
    NYCCsvParser,
    parse_nyc_amount,
    parse_nyc_date,
    parse_transactions,
)

_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "sample_transactions.csv"

_AMOUNT_FIELDS = ("AMNT", "MATCHAMNT", "PREVAMNT")
_DATE_FIELDS = ("DATE", "REFUNDDATE")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(NYC_TRANSACTION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def test_transaction_columns_derive_from_config() -> None:
    assert NYC_TRANSACTION_COLUMNS == _load_columns_for_data_type("transactions")


def test_parse_transactions_yields_rows_from_fixture() -> None:
    parser = parse_transactions(_FIXTURE_PATH)
    rows = list(parser)

    # Fixture has 10 data rows; row 8 (2021-06-10) is filtered by default year_from
    assert len(rows) == 9


def test_parser_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad_header.csv"
    fixture_rows = _read_rows(_FIXTURE_PATH)
    bad_columns = list(NYC_TRANSACTION_COLUMNS)
    bad_columns[0] = "WRONG_COLUMN"

    with bad_header_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=bad_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(fixture_rows[0])

    parser = NYCCsvParser(
        path=bad_header_path, columns=NYC_TRANSACTION_COLUMNS, row_label="transaction", year_from=2022
    )
    with pytest.raises(ValueError, match="Unexpected NYC transaction CSV header"):
        list(parser)


def test_parse_transactions_normalizes_empty_strings_to_none() -> None:
    rows = list(parse_transactions(_FIXTURE_PATH))

    # Row 1 (index 0): APARTMENT is "4A" (populated), but REFUNDDATE is empty
    assert rows[0]["REFUNDDATE"] is None
    # Row 6 (index 5): zero-amount row — OCCUPATION is "Retired", EMPNAME is empty
    assert rows[5]["EMPNAME"] is None


def test_parse_nyc_amount_parses_and_normalizes_empty() -> None:
    assert parse_nyc_amount("1,234.50") == Decimal("1234.50")
    assert parse_nyc_amount("-250") == Decimal("-250")
    assert parse_nyc_amount("$100.00") == Decimal("100.00")
    assert parse_nyc_amount("") is None
    assert parse_nyc_amount(None) is None


def test_parse_nyc_amount_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Invalid NYC amount"):
        parse_nyc_amount("not-a-number")


def test_parse_nyc_date_parses_mdy_format_and_empty() -> None:
    assert parse_nyc_date("1/3/2025") == date(2025, 1, 3)
    assert parse_nyc_date("12/31/2025") == date(2025, 12, 31)
    assert parse_nyc_date("") is None
    assert parse_nyc_date(None) is None


def test_parse_nyc_date_handles_iso_fallback() -> None:
    assert parse_nyc_date("2025-06-15") == date(2025, 6, 15)


def test_parse_nyc_date_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Invalid NYC date"):
        parse_nyc_date("not-a-date")


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
    rows[0]["DATE"] = "12/31/2021"
    rows[1]["DATE"] = "1/1/2022"
    _write_rows(filtered_fixture_path, rows)

    parsed = list(parse_transactions(filtered_fixture_path, year_from=2022))

    assert len(parsed) == 1
    assert parsed[0]["DATE"] == date(2022, 1, 1)


def test_parse_transactions_hand_checked_amount_values() -> None:
    """Verify specific amount values from the fixture match hand-calculated expectations."""
    rows = list(parse_transactions(_FIXTURE_PATH))

    # Row 1 (index 0): $1000 contribution
    assert rows[0]["AMNT"] == Decimal("1000")
    assert rows[0]["MATCHAMNT"] == Decimal("250")
    assert rows[0]["PREVAMNT"] == Decimal("0")

    # Row 2 (index 1): $100 contribution
    assert rows[1]["AMNT"] == Decimal("100")
    assert rows[1]["MATCHAMNT"] == Decimal("100")

    # Row 3 (index 2): Refund of -$250
    assert rows[2]["AMNT"] == Decimal("-250")

    # Row 5 (index 4): LLC $10000
    assert rows[4]["AMNT"] == Decimal("10000")

    # Row 6 (index 5): Zero amount
    assert rows[5]["AMNT"] == Decimal("0")


def test_parse_transactions_hand_checked_date_values() -> None:
    """Verify specific date values from the fixture match expectations."""
    rows = list(parse_transactions(_FIXTURE_PATH))

    # Row 1: 1/3/2025 contribution date
    assert rows[0]["DATE"] == date(2025, 1, 3)
    assert rows[0]["REFUNDDATE"] is None

    # Row 3 (index 2): refund with both DATE and REFUNDDATE
    assert rows[2]["DATE"] == date(2025, 6, 15)
    assert rows[2]["REFUNDDATE"] == date(2025, 6, 15)

    # Row 9 in fixture (boundary): 1/1/2022 — after year filter removes row 8, this is index 7
    assert rows[7]["DATE"] == date(2022, 1, 1)


def test_parse_transactions_hand_checked_string_values() -> None:
    """Verify specific string values from the fixture match expectations."""
    rows = list(parse_transactions(_FIXTURE_PATH))

    # Row 1: contributor info
    assert rows[0]["NAME"] == "Smith, John"
    assert rows[0]["C_CODE"] == "IND"
    assert rows[0]["RECIPNAME"] == "Rajkumar, Jenifer"
    assert rows[0]["RECIPID"] == "1682"
    assert rows[0]["CITY"] == "New York"
    assert rows[0]["STATE"] == "NY"

    # Row 3 (index 2): CORP type
    assert rows[2]["C_CODE"] == "CORP"
    assert rows[2]["NAME"] == "Refund Corp"
