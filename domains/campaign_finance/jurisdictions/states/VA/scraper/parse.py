"""Virginia campaign finance CSV parser.

Parses ScheduleA (contributions), ScheduleD (expenditures), and Report CSVs
from the VA SBE bulk download. Column contracts are loaded from config.yaml
via the scraper __init__ helpers.

Follows the WA parser pattern: VACsvParser wraps csv.DictReader with
header validation, malformed row skipping, and empty-string normalization.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterator

from . import _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

# Sentinel objects used to detect extra/missing fields in csv.DictReader output.
# If a row has more columns than the header, the extras land under _EXTRA_FIELD_SENTINEL.
# If a row has fewer columns than the header, missing columns get _MISSING_FIELD_SENTINEL.
_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()

# Load column tuples from config.yaml at module import time.
# These are frozen tuples of CSV column names in header order.
CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")
REPORT_COLUMNS = _load_columns_for_data_type("reports")


class VACsvParser:
    """Iterator over rows of a VA SBE CSV file with validation.

    - Validates the CSV header against expected columns
    - Skips malformed rows (extra or missing fields) with a logged warning
    - Normalizes empty string values to None
    - Tracks count of skipped rows via .skipped attribute
    """

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        row_label: str,
    ):
        self.path = path
        self.columns = columns
        self.row_label = row_label
        self.skipped = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        """Iterate over parsed and validated rows from the CSV file."""
        self.skipped = 0

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
                    LOGGER.warning("Skipping malformed %s row at line %d", self.row_label, reader.line_num)
                    continue

                yield _normalize_row(raw_row)


def _validate_header(
    fieldnames: list[str] | None,
    expected_columns: tuple[str, ...],
    row_label: str,
) -> None:
    """Raise ValueError if the CSV header doesn't match the expected column contract."""
    if tuple(fieldnames or ()) != expected_columns:
        raise ValueError(f"Unexpected {row_label} CSV header")


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    """Return True if the row has extra or missing fields."""
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_row(raw_row: dict[object, object]) -> dict[str, str | None]:
    """Convert empty strings to None and ensure all values are str or None."""
    normalized_row: dict[str, str | None] = {}

    for key, value in raw_row.items():
        if value in ("", None):
            normalized_row[str(key)] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"Unexpected non-string CSV value for {key!r}: {type(value)!r}")
        normalized_row[str(key)] = value

    return normalized_row


def parse_contributions(path: Path) -> VACsvParser:
    """Create a parser for VA ScheduleA (contributions) CSV files."""
    return VACsvParser(path=path, columns=CONTRIBUTION_COLUMNS, row_label="contribution")


def parse_expenditures(path: Path) -> VACsvParser:
    """Create a parser for VA ScheduleD (expenditures) CSV files."""
    return VACsvParser(path=path, columns=EXPENDITURE_COLUMNS, row_label="expenditure")


def parse_reports(path: Path) -> VACsvParser:
    """Create a parser for VA Report CSV files."""
    return VACsvParser(path=path, columns=REPORT_COLUMNS, row_label="report")
