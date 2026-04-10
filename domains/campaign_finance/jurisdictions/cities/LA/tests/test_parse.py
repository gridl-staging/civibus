from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.cities.LA.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.cities.LA.scraper.parse import (
    LA_TRANSACTION_COLUMNS,
    LACsvParser,
    parse_la_amount,
    parse_la_date,
    parse_transactions,
)

_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "sample_transactions.csv"

_AMOUNT_FIELDS = (
    "con_amount",
    "con_amount_pd_forgiven",
)
_DATE_FIELDS = (
    "con_date",
    "per_beg_date",
    "per_end_date",
    "election_date",
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(LA_TRANSACTION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def test_transaction_columns_derive_from_config() -> None:
    assert LA_TRANSACTION_COLUMNS == _load_columns_for_data_type("transactions")


def test_parse_transactions_yields_rows_from_fixture() -> None:
    parser = parse_transactions(_FIXTURE_PATH)
    rows = list(parser)

    # Fixture has 10 data rows; row 8 (2021-11-15) is filtered by default year_from
    assert len(rows) == 9


def test_parser_rejects_header_drift(tmp_path: Path) -> None:
    bad_header_path = tmp_path / "bad_header.csv"
    fixture_rows = _read_rows(_FIXTURE_PATH)
    bad_columns = list(LA_TRANSACTION_COLUMNS)
    bad_columns[0] = "wrong_column"

    with bad_header_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=bad_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(fixture_rows[0])

    parser = LACsvParser(path=bad_header_path, columns=LA_TRANSACTION_COLUMNS, row_label="transaction", year_from=2022)
    with pytest.raises(ValueError, match="Unexpected LA transaction CSV header"):
        list(parser)


def test_parse_transactions_normalizes_empty_strings_to_none() -> None:
    row = next(iter(parse_transactions(_FIXTURE_PATH)))

    # Row 1: dist_num is empty, con_desc is empty
    assert row["dist_num"] is None
    assert row["con_desc"] is None


def test_parse_la_amount_parses_and_normalizes_empty() -> None:
    assert parse_la_amount("1,234.50") == Decimal("1234.50")
    assert parse_la_amount("-100.00") == Decimal("-100.00")
    assert parse_la_amount("") is None
    assert parse_la_amount(None) is None


def test_parse_la_date_parses_iso_timestamp_and_empty() -> None:
    assert parse_la_date("2026-03-30T00:00:00.000") == date(2026, 3, 30)
    assert parse_la_date("2026-03-30") == date(2026, 3, 30)
    assert parse_la_date("") is None
    assert parse_la_date(None) is None


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
    rows[0]["con_date"] = "2021-12-31T00:00:00.000"
    rows[1]["con_date"] = "2022-01-01T00:00:00.000"
    _write_rows(filtered_fixture_path, rows)

    parsed = list(parse_transactions(filtered_fixture_path, year_from=2022))

    assert len(parsed) == 1
    assert parsed[0]["con_date"] == date(2022, 1, 1)


def test_parse_transactions_hand_checked_amount_values() -> None:
    """Verify specific amount values from the fixture match hand-calculated expectations."""
    rows = list(parse_transactions(_FIXTURE_PATH))

    # Row 1: $1000 contribution
    assert rows[0]["con_amount"] == Decimal("1000.00")
    assert rows[0]["con_amount_pd_forgiven"] == Decimal("0.00")

    # Row 2: $100 contribution
    assert rows[1]["con_amount"] == Decimal("100.00")

    # Row 4 (index 3): Refund of -$100
    assert rows[3]["con_amount"] == Decimal("-100.00")

    # Row 5 (index 4): $250 with $50 paid/forgiven
    assert rows[4]["con_amount"] == Decimal("250.00")
    assert rows[4]["con_amount_pd_forgiven"] == Decimal("50.00")


def test_parse_transactions_hand_checked_date_values() -> None:
    """Verify specific date values from the fixture match expectations."""
    rows = list(parse_transactions(_FIXTURE_PATH))

    # Row 1: 2025-12-31 contribution date
    assert rows[0]["con_date"] == date(2025, 12, 31)
    assert rows[0]["per_beg_date"] == date(2025, 7, 1)
    assert rows[0]["per_end_date"] == date(2025, 12, 31)
    assert rows[0]["election_date"] == date(2026, 6, 2)

    # Row 9 in fixture (boundary donor): 2022-01-01 — after year filter removes row 8, this is index 7
    assert rows[7]["con_date"] == date(2022, 1, 1)
