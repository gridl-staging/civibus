"""Streaming parser for FEC Schedule B (operating expenditures / oppexp.txt) bulk files.

oppexp files are headerless pipe-delimited with 25 fields — the same legacy format
as itcont/itpas2 parsed by bulk_parser.py, but with Schedule B-specific columns
(RPT_YR, LINE_NUM, FORM_TP_CD, SCHED_TP_CD, PURPOSE, CATEGORY, CATEGORY_DESC,
BACK_REF_TRAN_ID).

Returns raw string dicts from read_schedule_b_file() and typed dicts from
map_schedule_b_fields(). Date and amount conversion uses Schedule B-specific
helpers (_parse_schedule_b_date → datetime.date, _parse_schedule_b_amount →
Decimal) instead of field_mapper which returns incompatible types.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile

from domains.campaign_finance.ingest.bulk_parser import (
    _iter_limited,
    parse_pipe_delimited,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text

LOGGER = logging.getLogger(__name__)

SCHEDULE_B_COLUMNS: tuple[str, ...] = (
    "CMTE_ID",
    "AMNDT_IND",
    "RPT_YR",
    "RPT_TP",
    "IMAGE_NUM",
    "LINE_NUM",
    "FORM_TP_CD",
    "SCHED_TP_CD",
    "NAME",
    "CITY",
    "STATE",
    "ZIP_CODE",
    "TRANSACTION_DT",
    "TRANSACTION_AMT",
    "TRANSACTION_PGI",
    "PURPOSE",
    "CATEGORY",
    "CATEGORY_DESC",
    "MEMO_CD",
    "MEMO_TEXT",
    "ENTITY_TP",
    "SUB_ID",
    "FILE_NUM",
    "TRAN_ID",
    "BACK_REF_TRAN_ID",
)


def _parse_schedule_b_date(raw: str | None) -> date | None:
    """Parse MMDDYYYY or MM/DD/YYYY → datetime.date. Returns None for empty, '00000000', or malformed."""
    if not raw or raw == "00000000":
        return None
    for fmt in ("%m%d%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    LOGGER.warning("Unparseable Schedule B date: %r", raw)
    return None


def _parse_schedule_b_amount(raw: str | None) -> Decimal | None:
    """Parse numeric string → Decimal. Returns None for empty."""
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        LOGGER.warning("Unparseable Schedule B amount: %r", raw)
        return None


_normalize_optional_text = normalize_optional_text


def _cutoff_date() -> date:
    """5-year window: current year minus 4. For 2026 → 2022-01-01."""
    return date(date.today().year - 4, 1, 1)


def _apply_date_filter(
    rows: Iterator[dict[str, str | None]],
) -> Iterator[dict[str, str | None]]:
    """Exclude rows with a provably-old transaction date. Rows with empty/malformed dates pass through."""
    cutoff = _cutoff_date()
    for row in rows:
        parsed = _parse_schedule_b_date(row.get("TRANSACTION_DT"))
        if parsed is not None and parsed < cutoff:
            continue
        yield row


def read_schedule_b_file(path: str | Path, *, limit: int | None = None) -> Iterator[dict[str, str | None]]:
    """Read an oppexp bulk file and yield raw string dicts with the 5-year date filter applied."""
    file_path = Path(path)

    if file_path.suffix.lower() == ".zip":
        with ZipFile(file_path) as archive:
            txt_members = [n for n in archive.namelist() if n.lower().endswith(".txt")]
            oppexp_members = [n for n in txt_members if Path(n).name.lower().startswith("oppexp")]
            member_name = oppexp_members[0] if oppexp_members else txt_members[0]
            with archive.open(member_name, "r") as binary_stream:
                with io.TextIOWrapper(binary_stream, encoding="latin-1") as text_stream:
                    rows = parse_pipe_delimited(text_stream, SCHEDULE_B_COLUMNS)
                    yield from _iter_limited(_apply_date_filter(rows), limit)
        return

    with file_path.open("r", encoding="latin-1") as text_stream:
        rows = parse_pipe_delimited(text_stream, SCHEDULE_B_COLUMNS)
        yield from _iter_limited(_apply_date_filter(rows), limit)


def map_schedule_b_fields(row: dict[str, str | None]) -> dict:
    """Map a raw Schedule B row dict to typed output fields."""
    return {
        "committee_id": row["CMTE_ID"],
        "amendment_indicator": row["AMNDT_IND"],
        "report_year": row["RPT_YR"],
        "report_type": row["RPT_TP"],
        "image_number": row["IMAGE_NUM"],
        "line_number": row["LINE_NUM"],
        "form_type_code": row["FORM_TP_CD"],
        "schedule_type_code": row["SCHED_TP_CD"],
        "contributor_name_raw": row["NAME"],
        "city": row["CITY"],
        "state": row["STATE"],
        "zip_code": row["ZIP_CODE"],
        "transaction_date": _parse_schedule_b_date(row["TRANSACTION_DT"]),
        "transaction_amount": _parse_schedule_b_amount(row["TRANSACTION_AMT"]),
        "transaction_pgi": row["TRANSACTION_PGI"],
        "purpose": row["PURPOSE"],
        "category": row["CATEGORY"],
        "category_desc": row["CATEGORY_DESC"],
        "memo_code": _normalize_optional_text(row["MEMO_CD"]),
        "memo_text": _normalize_optional_text(row["MEMO_TEXT"]),
        "entity_type": row["ENTITY_TP"],
        "sub_id": row["SUB_ID"],
        "file_number": row["FILE_NUM"],
        "transaction_identifier": row["TRAN_ID"],
        "back_ref_transaction_id": _normalize_optional_text(row["BACK_REF_TRAN_ID"]),
    }
