"""Parse NY campaign finance CSV files downloaded from the SODA API.

Both contributions and expenditures share the same 45-column schema
(differentiated by filing_sched_abbrev). The parser validates the
header against config.yaml field_mappings and normalizes empty strings
to None.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterator

from . import _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()

# Column tuples derived from config.yaml field_mappings at import time.
CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")
IE_COLUMNS = _load_columns_for_data_type("independent_expenditures")


class NYCsvParser:
    """Streaming CSV parser with header validation and row normalization."""

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
        """Yield normalized rows as dicts. Skips malformed rows."""
        self.skipped = 0

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(
                f,
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            _validate_header(reader.fieldnames, self.columns, self.row_label)

            for raw_row in reader:
                if _is_malformed_row(raw_row):
                    self.skipped += 1
                    LOGGER.warning("Skipping malformed NY %s row at line %d", self.row_label, reader.line_num)
                    continue

                yield _normalize_row(raw_row)


def _validate_header(
    fieldnames: list[str] | None,
    expected_columns: tuple[str, ...],
    row_label: str,
) -> None:
    if tuple(fieldnames or ()) != expected_columns:
        raise ValueError(
            f"Unexpected NY {row_label} CSV header: got {fieldnames!r}, expected {list(expected_columns)!r}"
        )


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_row(raw_row: dict[object, object]) -> dict[str, str | None]:
    """Convert empty strings to None, verify all values are strings."""
    result: dict[str, str | None] = {}
    for key, value in raw_row.items():
        if value in ("", None):
            result[str(key)] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"Unexpected non-string value for {key!r}: {type(value)!r}")
        result[str(key)] = value
    return result


def parse_contributions(path: Path) -> NYCsvParser:
    """Return a streaming parser for NY contribution CSV files."""
    return NYCsvParser(path=path, columns=CONTRIBUTION_COLUMNS, row_label="contribution")


def parse_expenditures(path: Path) -> NYCsvParser:
    """Return a streaming parser for NY expenditure CSV files."""
    return NYCsvParser(path=path, columns=EXPENDITURE_COLUMNS, row_label="expenditure")


def parse_independent_expenditures(path: Path) -> NYCsvParser:
    return NYCsvParser(path=path, columns=IE_COLUMNS, row_label="independent_expenditure")
