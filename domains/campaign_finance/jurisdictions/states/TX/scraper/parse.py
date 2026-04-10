
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Iterator
import zipfile

from . import _load_column_for_semantic_path, _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()
MAX_ZIP_MEMBER_BYTES = 1_073_741_824

_TX_MEMBER_PREFIX_BY_TYPE = {
    "contributions": "contribs_",
    "expenditures": "expend_",
}
_TX_SINGLE_MEMBER_BY_TYPE = {
    "loans": "loans.csv",
}

CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")
LOAN_COLUMNS = _load_columns_for_data_type("loans")


class TXCsvParser:

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        data_type: str,
        row_label: str,
        date_column: str | None = None,
        year_from: int | None = None,
    ):
        self.path = path
        self.columns = columns
        self.data_type = data_type
        self.row_label = row_label
        # date_column: CSV column containing YYYYMMDD date for year filtering
        self.date_column = date_column
        # year_from: if set, skip rows where date year < year_from
        self.year_from = year_from
        self.skipped = 0
        self.filtered = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0
        self.filtered = 0

        for source_name, reader in _iter_member_readers(self.path, data_type=self.data_type):
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

                # Year filter: skip rows older than the cutoff.
                # TX dates are YYYYMMDD format, so first 4 chars = year.
                if self.year_from is not None and self.date_column is not None:
                    date_value = normalized.get(self.date_column)
                    if date_value is not None and len(date_value) >= 4:
                        try:
                            row_year = int(date_value[:4])
                            if row_year < self.year_from:
                                self.filtered += 1
                                continue
                        except ValueError:
                            pass  # unparseable date — let the loader handle it

                yield normalized


def _iter_member_readers(
    path: Path,
    *,
    data_type: str,
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
        member_names = _select_tx_member_names(archive, data_type=data_type)
        for member_name in member_names:
            _validate_zip_member_size(archive, member_name)
            with archive.open(member_name) as member_stream:
                with io.TextIOWrapper(member_stream, encoding="utf-8", errors="replace", newline="") as csv_file:
                    reader = csv.DictReader(
                        csv_file,
                        restkey=_EXTRA_FIELD_SENTINEL,
                        restval=_MISSING_FIELD_SENTINEL,
                    )
                    yield member_name, reader


def _select_tx_member_names(archive: zipfile.ZipFile, *, data_type: str) -> list[str]:
    member_names = [member.filename for member in archive.infolist() if not member.is_dir()]

    single_member_name = _TX_SINGLE_MEMBER_BY_TYPE.get(data_type)
    if single_member_name is not None:
        matches = [name for name in member_names if Path(name).name.lower() == single_member_name]
        if len(matches) != 1:
            raise ValueError(f"TX ZIP must contain exactly one {single_member_name!r} member")
        return matches

    member_prefix = _TX_MEMBER_PREFIX_BY_TYPE.get(data_type)
    if member_prefix is None:
        raise ValueError(f"Unsupported TX data type: {data_type}")

    matches = [
        name
        for name in member_names
        if Path(name).name.lower().startswith(member_prefix) and Path(name).name.lower().endswith(".csv")
    ]
    if not matches:
        raise ValueError(f"TX ZIP does not contain any members matching prefix {member_prefix!r}")

    return sorted(matches, key=lambda name: Path(name).name.lower())


def _validate_zip_member_size(archive: zipfile.ZipFile, member_name: str) -> None:
    member_info = archive.getinfo(member_name)
    # Reject unexpectedly large members before decompression to keep ingest bounded.
    if member_info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(
            f"TX ZIP member {Path(member_name).name!r} exceeds the allowed size limit of {MAX_ZIP_MEMBER_BYTES} bytes"
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
        normalized_row[str(key)] = value

    return normalized_row


def _resolve_date_column(data_type: str) -> str:
    """Look up the CSV column that maps to 'transaction.date' for this data type."""
    return _load_column_for_semantic_path(data_type, "transaction.date")


def parse_contributions(path: Path, *, year_from: int | None = None) -> TXCsvParser:
    return TXCsvParser(
        path=path,
        columns=CONTRIBUTION_COLUMNS,
        data_type="contributions",
        row_label="contribution",
        date_column=_resolve_date_column("contributions") if year_from else None,
        year_from=year_from,
    )


def parse_expenditures(path: Path, *, year_from: int | None = None) -> TXCsvParser:
    return TXCsvParser(
        path=path,
        columns=EXPENDITURE_COLUMNS,
        data_type="expenditures",
        row_label="expenditure",
        date_column=_resolve_date_column("expenditures") if year_from else None,
        year_from=year_from,
    )


def parse_loans(path: Path, *, year_from: int | None = None) -> TXCsvParser:
    return TXCsvParser(
        path=path,
        columns=LOAN_COLUMNS,
        data_type="loans",
        row_label="loan",
        date_column=_resolve_date_column("loans") if year_from else None,
        year_from=year_from,
    )
