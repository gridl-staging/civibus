
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import _load_column_for_semantic_path, _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")

# Max JSON file size to guard against loading enormous files into memory.
MAX_JSON_FILE_BYTES = 2_147_483_648  # 2 GB


class ALJsonParser:
    """Streaming JSON parser for Alabama FCPA search results.

    Reads a JSON file containing {"totalRecords": N, "data": [...]},
    normalizes each row's fields, and applies a year filter on the
    date column.
    """

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

        rows = _load_json_data(self.path)
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, dict):
                self.skipped += 1
                LOGGER.warning(
                    "Skipping non-dict %s row at index %d in %s",
                    self.row_label,
                    index,
                    self.path.name,
                )
                continue

            normalized = _normalize_row(raw_row, self.columns)

            # Apply year filter based on the date column.
            row_year = _extract_year_from_date(normalized.get(self.date_column))
            if row_year is not None and row_year < self.year_from:
                self.filtered += 1
                continue

            yield normalized


def _load_json_data(path: Path) -> list[dict]:
    """Load and validate the JSON data array from an AL download file."""
    file_size = path.stat().st_size
    if file_size > MAX_JSON_FILE_BYTES:
        raise ValueError(f"AL JSON file exceeds the allowed size limit of {MAX_JSON_FILE_BYTES} bytes")

    raw = json.loads(path.read_text(encoding="utf-8"))

    # Support both the full API response shape and a bare list.
    if isinstance(raw, dict):
        data = raw.get("data")
        if not isinstance(data, list):
            raise ValueError(f"AL JSON missing 'data' array in {path.name}")
        return data
    elif isinstance(raw, list):
        return raw
    else:
        raise ValueError(f"AL JSON has unexpected root type in {path.name}")


def _normalize_row(raw_row: dict, columns: tuple[str, ...]) -> dict[str, str | None]:
    """Normalize a JSON row: convert empty strings to None, strip whitespace.

    Only includes keys that are in the expected columns set, to ensure
    consistency with config.yaml field_mappings.
    """
    normalized: dict[str, str | None] = {}
    for key in columns:
        value = raw_row.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            normalized[key] = None
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            # Numeric or other types — convert to string.
            normalized[key] = str(value).strip() or None
    return normalized


def _extract_year_from_date(raw_date: str | None) -> int | None:
    """Extract the year from an AL date string (MM/DD/YYYY format)."""
    if raw_date is None:
        return None

    stripped = raw_date.strip()
    if not stripped:
        return None

    # AL dates are typically MM/DD/YYYY.
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(stripped, fmt).year
        except ValueError:
            continue

    # Fallback: try extracting a 4-digit year from the string.
    if len(stripped) >= 4 and stripped[:4].isdigit():
        return int(stripped[:4])

    return None


def _resolve_year_from(year_from: int | None) -> int:
    """Default to current_year - 4 for the 5-year window."""
    if year_from is not None:
        return year_from
    return datetime.now(timezone.utc).year - 4


def parse_contributions(path: Path, *, year_from: int | None = None) -> ALJsonParser:
    """Parse AL contribution records from a downloaded JSON file."""
    return ALJsonParser(
        path=path,
        columns=CONTRIBUTION_COLUMNS,
        data_type="contributions",
        row_label="contribution",
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("contributions", "transaction.date"),
    )


def parse_expenditures(path: Path, *, year_from: int | None = None) -> ALJsonParser:
    """Parse AL expenditure records from a downloaded JSON file."""
    return ALJsonParser(
        path=path,
        columns=EXPENDITURE_COLUMNS,
        data_type="expenditures",
        row_label="expenditure",
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("expenditures", "transaction.date"),
    )
