"""Parse MA OCPF report-items.txt files (tab-delimited).

The report-items.txt file contains all transactions for a year —
contributions AND expenditures in one file. The Record_Type_ID field
distinguishes them:
  200-series (201-211) = Receipts/Contributions
  300-series (301-315) = Expenditures
  400-series (401-405) = In-Kind contributions
  500-series (501-509) = Liabilities
  700-series (701-754) = Savings

The parser can filter to contributions-only or expenditures-only
at parse time.
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

# Column tuple from config.yaml field_mappings — applies to all record types.
REPORT_ITEM_COLUMNS = _load_columns_for_data_type("contributions")

# Record_Type_ID ranges for filtering.
# 200-series + 400-series = contributions (monetary + in-kind).
_CONTRIBUTION_RECORD_TYPE_IDS = set(range(200, 212)) | set(range(400, 406))
# 300-series = expenditures.
_EXPENDITURE_RECORD_TYPE_IDS = set(range(300, 316))


class MAReportItemParser:
    """Streaming tab-delimited parser for MA report-items.txt."""

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        row_label: str,
        record_type_filter: set[int] | None = None,
    ):
        self.path = path
        self.columns = columns
        self.row_label = row_label
        self.record_type_filter = record_type_filter
        self.skipped = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        """Yield normalized rows, optionally filtered by Record_Type_ID."""
        self.skipped = 0

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(
                f,
                delimiter="\t",
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            _validate_header(reader.fieldnames, self.columns, self.row_label)

            for raw_row in reader:
                if _is_malformed_row(raw_row):
                    self.skipped += 1
                    LOGGER.warning("Skipping malformed MA %s row at line %d", self.row_label, reader.line_num)
                    continue

                # Apply record type filter if set.
                if self.record_type_filter is not None:
                    record_type_raw = raw_row.get("Record_Type_ID")
                    if record_type_raw:
                        try:
                            record_type_id = int(str(record_type_raw).strip())
                        except ValueError:
                            self.skipped += 1
                            continue
                        if record_type_id not in self.record_type_filter:
                            continue

                yield _normalize_row(raw_row)


def _validate_header(
    fieldnames: list[str] | None,
    expected_columns: tuple[str, ...],
    row_label: str,
) -> None:
    # Live OCPF data has a trailing tab producing an empty column — strip it.
    cleaned = list(fieldnames or ())
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    if tuple(cleaned) != expected_columns:
        raise ValueError(f"Unexpected MA {row_label} header: got {fieldnames!r}, expected {list(expected_columns)!r}")


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_row(raw_row: dict[object, object]) -> dict[str, str | None]:
    """Convert empty strings to None, strip whitespace."""
    result: dict[str, str | None] = {}
    for key, value in raw_row.items():
        if value in ("", None):
            result[str(key)] = None
            continue
        if not isinstance(value, str):
            raise ValueError(f"Unexpected non-string value for {key!r}: {type(value)!r}")
        stripped = value.strip()
        result[str(key)] = stripped if stripped else None
    return result


def parse_contributions(path: Path) -> MAReportItemParser:
    """Parse report-items.txt filtered to contribution record types only."""
    return MAReportItemParser(
        path=path,
        columns=REPORT_ITEM_COLUMNS,
        row_label="contribution",
        record_type_filter=_CONTRIBUTION_RECORD_TYPE_IDS,
    )


def parse_expenditures(path: Path) -> MAReportItemParser:
    """Parse report-items.txt filtered to expenditure record types only."""
    return MAReportItemParser(
        path=path,
        columns=REPORT_ITEM_COLUMNS,
        row_label="expenditure",
        record_type_filter=_EXPENDITURE_RECORD_TYPE_IDS,
    )


def parse_all_items(path: Path) -> MAReportItemParser:
    """Parse report-items.txt with no record type filtering."""
    return MAReportItemParser(
        path=path,
        columns=REPORT_ITEM_COLUMNS,
        row_label="report_item",
        record_type_filter=None,
    )
