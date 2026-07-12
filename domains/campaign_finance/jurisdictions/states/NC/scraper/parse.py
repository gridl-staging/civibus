
from __future__ import annotations

import csv
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from domains.campaign_finance.ingest.text_utils import normalize_optional_text

from . import _find_nc_data_source_block

LOGGER = logging.getLogger(__name__)

_TRANSACTION_SOURCE_NAME = "North Carolina SBoE Transaction Search"
_COMMITTEE_DOC_SOURCE_NAME = "North Carolina SBoE Committee/Document Search"
_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()
_TRANSACTION_TYPE_CLASSIFICATION = {
    "Individual": "person",
    "Non-Party Comm": "organization",
    "Business/Group/Org": "organization",
}
_AMENDMENT_FLAG_MAPPING = {
    "Y": True,
    "N": False,
}
_NC_IE_DOC_NAMES = frozenset({"independent expenditure report"})


@lru_cache(maxsize=None)
def _load_columns(source_name: str) -> tuple[str, ...]:
    data_source_block = _find_nc_data_source_block(source_name)
    if data_source_block is None:
        raise RuntimeError(f"Could not load NC columns from config.yaml for source {source_name!r}")

    in_target_field_mappings = False
    columns: list[str] = []

    for line in data_source_block.lines:
        stripped_line = line.strip()
        if stripped_line == "field_mappings:":
            in_target_field_mappings = True
            continue
        if not in_target_field_mappings:
            continue
        if not line.startswith("      "):
            break

        columns.append(stripped_line.split(":", maxsplit=1)[0].strip('"'))

    if columns:
        return tuple(columns)

    raise RuntimeError(f"Could not load NC columns from config.yaml for source {source_name!r}")


TRANSACTION_COLUMNS = _load_columns(_TRANSACTION_SOURCE_NAME)
COMMITTEE_DOC_COLUMNS = _load_columns(_COMMITTEE_DOC_SOURCE_NAME)
NCCommitteeDocumentRowKey = tuple[str, ...]


class NCSBoECsvParser:

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...] = TRANSACTION_COLUMNS,
        row_label: str = "transaction",
        year_from: int | None = None,
        date_column: str = "Date Occured",
    ):
        self.path = path
        self.columns = columns
        self.row_label = row_label
        self.year_from = year_from
        self.date_column = date_column
        self.skipped = 0
        self.filtered = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0
        self.filtered = 0

        with self.path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(
                csv_file,
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            _validate_header(reader.fieldnames, self.columns, self.row_label)
            for raw_row in reader:
                if _is_malformed_row(raw_row):
                    self.skipped += 1
                    LOGGER.warning(
                        "Skipping malformed %s row at line %d",
                        self.row_label,
                        reader.line_num,
                    )
                    continue

                normalized = _normalize_row(raw_row)

                if self.year_from is not None:
                    row_year = _extract_year_from_date(normalized.get(self.date_column))
                    if row_year is not None and row_year < self.year_from:
                        self.filtered += 1
                        continue

                yield normalized


def _extract_year_from_date(raw_date: str | None) -> int | None:
    normalized = normalize_optional_text(raw_date)
    if normalized is None:
        return None

    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).year
        except ValueError:
            continue
    return None


def _resolve_year_from(year_from: int | None) -> int:
    if year_from is not None:
        return year_from
    return datetime.now(timezone.utc).year - 4


def _validate_header(
    fieldnames: list[str] | None,
    expected_columns: tuple[str, ...],
    row_label: str,
) -> None:
    if tuple(fieldnames or ()) != expected_columns:
        raise ValueError(f"Unexpected {row_label} CSV header")


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_row(raw_row: dict[object, object]) -> dict[str, str | None]:
    normalized_row: dict[str, str | None] = {}
    for key, value in raw_row.items():
        if value in ("", None):
            normalized_value: str | None = None
        elif isinstance(value, str):
            normalized_value = value
        else:
            raise ValueError(f"Unexpected non-string CSV value for {key!r}: {type(value)!r}")
        normalized_row[str(key)] = normalized_value

    return normalized_row


def parse_transactions(path: Path, *, year_from: int | None = None) -> NCSBoECsvParser:
    return NCSBoECsvParser(path=path, year_from=_resolve_year_from(year_from))


def parse_committee_docs(path: Path) -> NCSBoECsvParser:
    return NCSBoECsvParser(
        path=path,
        columns=COMMITTEE_DOC_COLUMNS,
        row_label="committee_document",
    )


# Cross-endpoint inconsistency in the NC SBoE portal: the CFDocLkup
# /ExportSearchResults CSV reports the real "Doc Type" per filing (which can
# be either "Disclosure Report" or "Informational Report"), while the
# CFDocLkup/DocumentResult HTML grid does NOT carry a Doc Type column at all
# — the parser hardcodes "Disclosure Report" for every row when synthesizing
# the linkage key. Including "Doc Type" in the linkage key therefore drops
# every CSV row whose Doc Type is "Informational Report" — a real loss
# observed live 2026-04-25 (6 of 47 IE candidates were silently un-URL'd).
# Excluded from the linkage key for cross-endpoint robustness; the remaining
# 11 columns are unique enough to identify a specific filing.
_LINKAGE_KEY_COLUMNS = tuple(c for c in COMMITTEE_DOC_COLUMNS if c != "Doc Type")


def build_nc_committee_doc_linkage_key(
    row: Mapping[str, str | None],
) -> NCCommitteeDocumentRowKey:
    """Build the Stage 1 linkage key from parse_committee_docs-owned columns.

    Doc Type is intentionally excluded — see _LINKAGE_KEY_COLUMNS for why.
    """
    return tuple("" if row.get(column) is None else str(row.get(column)) for column in _LINKAGE_KEY_COLUMNS)


def classify_ie_filing(row: Mapping[str, str | None]) -> bool:
    doc_name = normalize_optional_text(row.get("Doc Name"))
    if doc_name is None:
        return False
    return doc_name.lower() in _NC_IE_DOC_NAMES


def is_within_ie_year_window(
    row: Mapping[str, str | None],
    *,
    current_year: int | None = None,
) -> bool:
    normalized_year = normalize_optional_text(row.get("Year"))
    if normalized_year is None:
        return False

    try:
        filing_year = int(normalized_year)
    except ValueError:
        return False

    window_end = datetime.now(timezone.utc).year if current_year is None else current_year
    window_start = window_end - 4
    return window_start <= filing_year <= window_end


def parse_amendment_flag(raw: str | None) -> bool | None:
    normalized = normalize_optional_text(raw)
    if normalized is None:
        return None

    try:
        return _AMENDMENT_FLAG_MAPPING[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown NC amendment flag: {raw!r}") from exc


def parse_nc_date(raw: str | None) -> str | None:
    normalized = normalize_optional_text(raw)
    if normalized is None:
        return None

    try:
        parsed_date = datetime.strptime(normalized, "%m/%d/%Y")
    except ValueError as exc:
        raise ValueError(f"Invalid NC date: {raw!r}") from exc

    return parsed_date.date().isoformat()


def parse_nc_amount(raw: str | None) -> Decimal | None:
    normalized = normalize_optional_text(raw)
    if normalized is None:
        return None

    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid NC amount: {raw!r}") from exc


def classify_transction_type(raw: str | None) -> str | None:
    normalized = normalize_optional_text(raw)
    if normalized is None:
        return None

    return _TRANSACTION_TYPE_CLASSIFICATION.get(normalized, "unknown")
