
from __future__ import annotations

import csv
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from . import _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()

SF_TRANSACTION_COLUMNS = _load_columns_for_data_type("transactions")

_SF_AMOUNT_COLUMNS = {
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
}
_SF_DATE_COLUMNS = {
    "filing_date",
    "start_date",
    "end_date",
    "calculated_date",
    "transaction_date",
    "transaction_date_1",
}


class SFCsvParser:

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        row_label: str,
        year_from: int,
    ):
        self.path = path
        self.columns = columns
        self.row_label = row_label
        self.year_from = year_from
        self.skipped = self.filtered = 0

    def __iter__(self) -> Iterator[dict[str, str | Decimal | date | None]]:
        self.skipped = self.filtered = 0

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as csv_file:
            reader = csv.DictReader(
                csv_file,
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            _validate_header(reader.fieldnames, self.columns, self.row_label)

            for raw_row in reader:
                if _is_malformed_row(raw_row):
                    self.skipped += 1
                    LOGGER.warning("Skipping malformed SF %s row at line %d", self.row_label, reader.line_num)
                    continue

                normalized = _normalize_row(raw_row)
                if _is_before_year_cutoff(normalized, year_from=self.year_from):
                    self.filtered += 1
                    continue

                yield normalized


def parse_sf_amount(raw_value: str | None) -> Decimal | None:
    if raw_value is None:
        return None

    normalized_value = raw_value.strip().replace(",", "").replace("$", "")
    if not normalized_value:
        return None

    try:
        return Decimal(normalized_value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid SF amount value: {raw_value!r}") from error


def parse_sf_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None

    normalized_value = raw_value.strip()
    if not normalized_value:
        return None

    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_value, fmt).date()
        except ValueError:
            continue

    if len(normalized_value) >= 10:
        try:
            return date.fromisoformat(normalized_value[:10])
        except ValueError:
            pass

    raise ValueError(f"Invalid SF date value: {raw_value!r}")


def _validate_header(
    fieldnames: list[str] | None,
    expected_columns: tuple[str, ...],
    row_label: str,
) -> None:
    if tuple(fieldnames or ()) != expected_columns:
        raise ValueError(f"Unexpected SF {row_label} CSV header")


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_row(raw_row: dict[object, object]) -> dict[str, str | Decimal | date | None]:
    normalized_row: dict[str, str | Decimal | date | None] = {}

    for key, value in raw_row.items():
        column_name = str(key)

        if value in ("", None):
            normalized_value: str | Decimal | date | None = None
        else:
            if not isinstance(value, str):
                raise ValueError(f"Unexpected non-string CSV value for {key!r}: {type(value)!r}")

            normalized_value = value
            if column_name in _SF_AMOUNT_COLUMNS:
                normalized_value = parse_sf_amount(value)
            elif column_name in _SF_DATE_COLUMNS:
                normalized_value = parse_sf_date(value)

        normalized_row[column_name] = normalized_value

    return normalized_row


def _is_before_year_cutoff(row: dict[str, str | Decimal | date | None], *, year_from: int) -> bool:
    for column_name in ("transaction_date", "transaction_date_1"):
        transaction_date = row.get(column_name)
        if isinstance(transaction_date, date):
            return transaction_date.year < year_from
    return False


def _resolve_year_from(year_from: int | None) -> int:
    return year_from if year_from is not None else datetime.now(timezone.utc).year - 4


def parse_transactions(path: Path, *, year_from: int | None = None) -> SFCsvParser:
    return SFCsvParser(
        path=path,
        columns=SF_TRANSACTION_COLUMNS,
        row_label="transaction",
        year_from=_resolve_year_from(year_from),
    )
