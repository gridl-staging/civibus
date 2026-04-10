
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import _load_column_for_semantic_path, _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()

CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")


class KYCsvParser:
    """Streaming CSV parser for Kentucky KREF exports."""

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        data_type: str,
        row_label: str,
        year_from: int,
        date_column: str,
    ):
        self.path = path
        self.columns = columns
        self.data_type = data_type
        self.row_label = row_label
        self.year_from = year_from
        self.date_column = date_column
        self.skipped = 0
        self.filtered = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0
        self.filtered = 0

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as csv_file:
            reader = csv.DictReader(
                csv_file,
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            _validate_header(reader.fieldnames, self.columns, self.row_label, source_name=self.path.name)

            for raw_row in reader:
                if _is_malformed_row(raw_row):
                    self.skipped += 1
                    LOGGER.warning(
                        "Skipping malformed %s row in %s at line %d",
                        self.row_label,
                        self.path.name,
                        reader.line_num,
                    )
                    continue

                normalized = _normalize_row(raw_row)

                # Apply the 5-year date filter
                row_year = _extract_year_from_date(normalized.get(self.date_column))
                if row_year is not None and row_year < self.year_from:
                    self.filtered += 1
                    continue

                yield normalized


def _validate_header(
    fieldnames: list[str] | None,
    expected_columns: tuple[str, ...],
    row_label: str,
    *,
    source_name: str,
) -> None:
    if tuple(fieldnames or ()) != expected_columns:
        raise ValueError(f"Unexpected {row_label} CSV header in {source_name}")


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_row(raw_row: dict[object, object]) -> dict[str, str | None]:
    """Strip whitespace from values and convert empty strings to None."""
    normalized_row: dict[str, str | None] = {}

    for key, value in raw_row.items():
        if value in ("", None):
            normalized_row[str(key)] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"Unexpected non-string CSV value for {key!r}: {type(value)!r}")
        normalized_row[str(key)] = value.strip() or None

    return normalized_row


def _extract_year_from_date(raw_date: str | None) -> int | None:
    """Extract the year from common date formats (MM/DD/YYYY, ISO, etc.)."""
    if raw_date is None:
        return None

    stripped = raw_date.strip()
    if not stripped:
        return None

    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(stripped, fmt).year
        except ValueError:
            continue

    # Fallback: try leading 4-digit year
    if len(stripped) >= 4 and stripped[:4].isdigit():
        return int(stripped[:4])

    return None


def _resolve_year_from(year_from: int | None) -> int:
    """Default to current_year - 4 if no explicit year_from is given."""
    if year_from is not None:
        return year_from
    return datetime.now(timezone.utc).year - 4


def parse_contributions(path: Path, *, year_from: int | None = None) -> KYCsvParser:
    """Parse a KY contributions CSV, filtering rows older than year_from."""
    return KYCsvParser(
        path=path,
        columns=CONTRIBUTION_COLUMNS,
        data_type="contributions",
        row_label="contribution",
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("contributions", "transaction.date"),
    )


def parse_expenditures(path: Path, *, year_from: int | None = None) -> KYCsvParser:
    """Parse a KY expenditures CSV, filtering rows older than year_from."""
    return KYCsvParser(
        path=path,
        columns=EXPENDITURE_COLUMNS,
        data_type="expenditures",
        row_label="expenditure",
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("expenditures", "transaction.date"),
    )
