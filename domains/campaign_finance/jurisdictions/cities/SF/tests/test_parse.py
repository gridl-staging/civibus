"""SF transaction parser tests.

Live-header regression coverage is pinned to a committed fixture captured from
the config-declared bulk download source:

- Dataset: DataSF ``pitq-e56w`` (``https://data.sfgov.org/resource/pitq-e56w.csv``)
- Captured: 2026-08-23 via ``?$limit=3`` (header + 3 real rows)

The captured live header has ``_LIVE_HEADER_COLUMN_COUNT`` columns; that module
constant is the single pinned owner of the count, and a deliberate re-capture
must edit it. ``_validate_header`` accepts the live header because
``SF_TRANSACTION_COLUMNS`` (56 expected columns) is an ordered subsequence of the
102-column live header.
"""

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
_LIVE_HEADER_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "live_header_transactions.csv"
_LIVE_HEADER_COLUMN_COUNT = 102
# All 3 captured rows are dated 2026; pin a year_from safely below them so the
# acceptance test keeps every row (filtered == 0) without depending on the clock.
_LIVE_HEADER_YEAR_FROM = 2020

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


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return next(csv.reader(csv_file))


def _is_ordered_subsequence(expected: tuple[str, ...], header: list[str]) -> bool:
    remaining = iter(header)
    return all(column in remaining for column in expected)


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


def test_parser_rejects_permuted_expected_header(tmp_path: Path) -> None:
    # Order-sensitivity is the intended half of the ordered-subsequence contract:
    # a header carrying every expected column but out of order is rejected. The
    # live pitq-e56w header satisfies the order and is accepted (see
    # test_parser_accepts_unmapped_live_socrata_columns); this proves the guard
    # still fails when order is violated rather than degenerating to a set check.
    permuted_path = tmp_path / "permuted_header.csv"
    fixture_row = _read_rows(_FIXTURE_PATH)[0]
    permuted_columns = list(SF_TRANSACTION_COLUMNS)
    permuted_columns[0], permuted_columns[1] = permuted_columns[1], permuted_columns[0]

    with permuted_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=permuted_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(fixture_row)

    parser = SFCsvParser(
        path=permuted_path,
        columns=SF_TRANSACTION_COLUMNS,
        row_label="transaction",
        year_from=2022,
    )
    with pytest.raises(ValueError, match="Unexpected SF transaction CSV header"):
        list(parser)


def test_live_header_fixture_is_real_superset_of_expected_columns() -> None:
    header = _read_header(_LIVE_HEADER_FIXTURE_PATH)

    assert len(header) == _LIVE_HEADER_COLUMN_COUNT
    assert _is_ordered_subsequence(SF_TRANSACTION_COLUMNS, header)
    live_only_extras = set(header) - set(SF_TRANSACTION_COLUMNS)
    # A non-empty extra set proves the fixture is a genuine live superset rather
    # than a re-spelling of the expected tuple.
    assert live_only_extras


def test_parser_accepts_unmapped_live_socrata_columns() -> None:
    parser = parse_transactions(_LIVE_HEADER_FIXTURE_PATH, year_from=_LIVE_HEADER_YEAR_FROM)

    rows = list(parser)

    # skipped/filtered are only meaningful after the generator is fully drained.
    assert len(rows) == 3
    assert parser.skipped == 0
    assert parser.filtered == 0
    # Values transcribed directly from live_header_transactions.csv, not recomputed.
    assert rows[0]["filing_id_number"] == "217270011"
    assert isinstance(rows[0]["filing_id_number"], str)
    assert rows[0]["transaction_amount_1"] == Decimal("15000.0")
    assert rows[0]["transaction_date"] == date(2026, 8, 19)
    assert rows[1]["transaction_amount_1"] == Decimal("1782.42")
    assert rows[2]["filing_id_number"] == "217264520"
    assert rows[2]["transaction_date"] == date(2026, 5, 8)


def test_live_header_short_row_is_skipped(tmp_path: Path) -> None:
    short_row_path = tmp_path / "live_header_short_row.csv"
    header = _read_header(_LIVE_HEADER_FIXTURE_PATH)
    with short_row_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        # Row missing all trailing fields -> restval sentinel -> malformed skip.
        writer.writerow(["217270011", "15000.0"])

    parser = parse_transactions(short_row_path, year_from=_LIVE_HEADER_YEAR_FROM)
    rows = list(parser)

    assert rows == []
    assert parser.skipped == 1
    assert parser.filtered == 0


def test_live_header_stale_row_is_filtered(tmp_path: Path) -> None:
    stale_row_path = tmp_path / "live_header_stale_row.csv"
    header = _read_header(_LIVE_HEADER_FIXTURE_PATH)
    stale_row = _read_rows(_LIVE_HEADER_FIXTURE_PATH)[0]
    stale_row["transaction_date"] = "2019-12-31T00:00:00.000"
    with stale_row_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=header)
        writer.writeheader()
        writer.writerow(stale_row)

    parser = parse_transactions(stale_row_path, year_from=_LIVE_HEADER_YEAR_FROM)
    rows = list(parser)

    assert rows == []
    assert parser.filtered == 1
    assert parser.skipped == 0


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
