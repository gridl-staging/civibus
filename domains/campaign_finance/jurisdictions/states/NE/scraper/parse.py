
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
import zipfile

from . import _load_column_for_semantic_path, _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()
MAX_ZIP_MEMBER_BYTES = 1_073_741_824

_NE_MEMBER_TEMPLATE_BY_TYPE = {
    "contributions": "{year}_ContributionLoanExtract.csv",
    "loans": "{year}_ContributionLoanExtract.csv",
    "expenditures": "{year}_ExpenditureExtract.csv",
}

CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
LOAN_COLUMNS = _load_columns_for_data_type("loans")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")

_RECEIPT_TRANSACTION_TYPE_COLUMN = _load_column_for_semantic_path("contributions", "ne.receipt_transaction_type")


class NECsvParser:
    """Streaming CSV parser for Nebraska bulk extracts."""

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        data_type: str,
        row_label: str,
        year: int,
        year_from: int,
        date_column: str,
        row_filter: Callable[[dict[str, str | None]], bool] | None = None,
    ):
        self.path = path
        self.columns = columns
        self.data_type = data_type
        self.row_label = row_label
        self.year = year
        self.year_from = year_from
        self.date_column = date_column
        self.row_filter = row_filter
        self.skipped = 0
        self.filtered = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0
        self.filtered = 0

        for source_name, reader in _iter_member_readers(self.path, data_type=self.data_type, year=self.year):
            _validate_header(reader.fieldnames, self.columns, self.row_label, source_name=source_name)
            for raw_row in reader:
                if _is_malformed_row(raw_row):
                    self.skipped += 1
                    LOGGER.warning(
                        "Skipping malformed %s row in %s at line %d",
                        self.row_label,
                        source_name,
                        reader.line_num,
                    )
                    continue

                normalized = _normalize_row(raw_row)
                if self.row_filter is not None and not self.row_filter(normalized):
                    continue

                row_year = _extract_year_from_date(normalized.get(self.date_column))
                if row_year is not None and row_year < self.year_from:
                    self.filtered += 1
                    continue

                yield normalized


def _iter_member_readers(
    path: Path,
    *,
    data_type: str,
    year: int,
) -> Iterator[tuple[str, csv.DictReader]]:
    if path.suffix.lower() != ".zip":
        with path.open("r", encoding="utf-8", errors="replace", newline="") as csv_file:
            reader = csv.DictReader(
                csv_file,
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            yield path.name, reader
        return

    with zipfile.ZipFile(path) as archive:
        member_name = _select_ne_member_name(archive, data_type=data_type, year=year)
        _validate_zip_member_size(archive, member_name)
        with archive.open(member_name) as member_stream:
            with io.TextIOWrapper(member_stream, encoding="utf-8", errors="replace", newline="") as csv_file:
                reader = csv.DictReader(
                    csv_file,
                    restkey=_EXTRA_FIELD_SENTINEL,
                    restval=_MISSING_FIELD_SENTINEL,
                )
                yield member_name, reader


def _select_ne_member_name(archive: zipfile.ZipFile, *, data_type: str, year: int) -> str:
    template = _NE_MEMBER_TEMPLATE_BY_TYPE.get(data_type)
    if template is None:
        raise ValueError(f"Unsupported NE data type: {data_type}")

    expected_member_basename = template.format(year=year).lower()
    matches = [
        member.filename
        for member in archive.infolist()
        if not member.is_dir() and Path(member.filename).name.lower() == expected_member_basename
    ]

    if len(matches) != 1:
        raise ValueError(
            f"NE ZIP must contain exactly one member named {template.format(year=year)!r} (found {len(matches)})"
        )

    return matches[0]


def _validate_zip_member_size(archive: zipfile.ZipFile, member_name: str) -> None:
    member_info = archive.getinfo(member_name)
    if member_info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(
            f"NE ZIP member {Path(member_name).name!r} exceeds the allowed size limit of {MAX_ZIP_MEMBER_BYTES} bytes"
        )


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

    if len(stripped) >= 4 and stripped[:4].isdigit():
        return int(stripped[:4])

    return None


def _is_loan_row(row: dict[str, str | None]) -> bool:
    transaction_type = row.get(_RECEIPT_TRANSACTION_TYPE_COLUMN)
    if transaction_type is None:
        return False
    return "loan" in transaction_type.lower()


def _resolve_year_from(year_from: int | None) -> int:
    if year_from is not None:
        return year_from
    return datetime.now(timezone.utc).year - 4


def parse_contributions(path: Path, *, year: int, year_from: int | None = None) -> NECsvParser:
    return NECsvParser(
        path=path,
        columns=CONTRIBUTION_COLUMNS,
        data_type="contributions",
        row_label="contribution",
        year=year,
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("contributions", "transaction.date"),
        row_filter=lambda row: not _is_loan_row(row),
    )


def parse_loans(path: Path, *, year: int, year_from: int | None = None) -> NECsvParser:
    return NECsvParser(
        path=path,
        columns=LOAN_COLUMNS,
        data_type="loans",
        row_label="loan",
        year=year,
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("loans", "transaction.date"),
        row_filter=_is_loan_row,
    )


def parse_expenditures(path: Path, *, year: int, year_from: int | None = None) -> NECsvParser:
    return NECsvParser(
        path=path,
        columns=EXPENDITURE_COLUMNS,
        data_type="expenditures",
        row_label="expenditure",
        year=year,
        year_from=_resolve_year_from(year_from),
        date_column=_load_column_for_semantic_path("expenditures", "transaction.date"),
        row_filter=None,
    )
