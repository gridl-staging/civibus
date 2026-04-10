"""Streaming CSV parser for FEC Schedule E (independent expenditures) bulk files.

Schedule E CSVs are comma-delimited UTF-8 with a header row — a different format
from the pipe-delimited headerless legacy bulk files parsed by bulk_parser.py.

Returns typed values: dates as datetime.date, amounts as Decimal, empty strings
as None. Amendment indicator values (N, A1-A4) are passed through as-is;
normalization to the N/A/T constraint is a loader concern (Stage 3).
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

SCHEDULE_E_COLUMNS: tuple[str, ...] = (
    "cand_id",
    "cand_name",
    "spe_id",
    "spe_nam",
    "ele_type",
    "can_office_state",
    "can_office_dis",
    "can_office",
    "cand_pty_aff",
    "exp_amo",
    "exp_date",
    "agg_amo",
    "sup_opp",
    "pur",
    "pay",
    "file_num",
    "amndt_ind",
    "tran_id",
    "image_num",
    "receipt_dat",
    "fec_election_yr",
    "prev_file_num",
    "dissem_dt",
)

# Columns that contain DD-MON-YY dates (e.g. "27-SEP-24")
_DATE_COLUMNS = frozenset({"exp_date", "receipt_dat", "dissem_dt"})

# Columns that contain numeric amounts
_AMOUNT_COLUMNS = frozenset({"exp_amo", "agg_amo"})


def _parse_fec_date(raw: str) -> date | None:
    """Parse FEC Schedule E date format DD-MON-YY (e.g. '27-SEP-24').

    Returns None for empty strings. Two-digit years are interpreted as
    2000-2099 (consistent with FEC data range).
    """
    if not raw:
        return None
    # strptime handles %y as 00-68 -> 2000-2068, 69-99 -> 1969-1999
    # FEC data is modern (2000+), so this works correctly
    try:
        return datetime.strptime(raw, "%d-%b-%y").date()
    except ValueError:
        LOGGER.warning("Unparseable date: %r", raw)
        return None


def _parse_amount(raw: str) -> Decimal | None:
    """Parse a numeric amount string to Decimal. Returns None for empty strings."""
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        LOGGER.warning("Unparseable amount: %r", raw)
        return None


def _normalize_row(raw_row: dict[str, str]) -> dict[str, Any]:
    """Convert raw CSV string values to typed Python values.

    - Empty strings -> None
    - Date columns -> datetime.date via DD-MON-YY parsing
    - Amount columns -> Decimal
    - All other columns -> str or None
    """
    typed: dict[str, Any] = {}
    for key, value in raw_row.items():
        stripped = value.strip() if value else ""
        if not stripped:
            typed[key] = None
        elif key in _DATE_COLUMNS:
            typed[key] = _parse_fec_date(stripped)
        elif key in _AMOUNT_COLUMNS:
            typed[key] = _parse_amount(stripped)
        else:
            typed[key] = stripped
    return typed


def read_schedule_e_file(
    path: str | Path,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream-parse a FEC Schedule E CSV file.

    Validates the header row against SCHEDULE_E_COLUMNS, then yields one dict
    per valid data row with typed values (dates, decimals).

    Args:
        path: Path to the Schedule E CSV file.
        limit: Maximum number of rows to yield. None means all rows.

    Yields:
        Dict mapping column names to typed values.

    Raises:
        ValueError: If the CSV header doesn't match expected columns, or limit < 0.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    if limit == 0:
        return

    file_path = Path(path)
    expected_count = len(SCHEDULE_E_COLUMNS)
    yielded = 0

    with file_path.open("r", encoding="utf-8", newline="") as csvfile:
        reader = csv.DictReader(csvfile)

        actual = tuple(reader.fieldnames) if reader.fieldnames else ()
        if actual != SCHEDULE_E_COLUMNS:
            actual_set = set(actual)
            expected_set = set(SCHEDULE_E_COLUMNS)
            # Distinguish wrong-order from missing/extra columns
            order_note = ", columns present but in wrong order" if actual_set == expected_set else ""
            raise ValueError(
                f"Schedule E CSV header mismatch: "
                f"missing={expected_set - actual_set}, "
                f"extra={actual_set - expected_set}" + order_note
            )

        for line_number, raw_row in enumerate(reader, start=2):
            # csv.DictReader stores extra fields under restkey (None)
            if None in raw_row:
                LOGGER.warning(
                    "Skipping row %d: too many fields (%d extra)",
                    line_number,
                    len(raw_row[None]),  # type: ignore[arg-type]
                )
                continue
            # DictReader fills missing fields with restval (None).
            # Real CSV empty fields are "" not None, so None means absent.
            if any(v is None for v in raw_row.values()):
                present = sum(1 for v in raw_row.values() if v is not None)
                LOGGER.warning(
                    "Skipping row %d: expected %d fields, got %d",
                    line_number,
                    expected_count,
                    present,
                )
                continue

            yield _normalize_row(raw_row)
            yielded += 1
            if limit is not None and yielded >= limit:
                return
