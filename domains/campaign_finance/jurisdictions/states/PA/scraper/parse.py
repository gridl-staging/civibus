"""
Stub summary for mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/parse.py.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Iterator
import zipfile

from . import _load_columns_for_data_type

LOGGER = logging.getLogger(__name__)

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()
MAX_ZIP_MEMBER_BYTES = 1_073_741_824

_PA_MEMBER_PREFIX_BY_TYPE = {
    "contributions": "contrib",
    "expenditures": "expense",
    "debts": "debt",
    "receipts": "receipt",
    "filings": "filer",
}
_PA_ENCODING_BY_TYPE = {
    "contributions": "cp437",
    "expenditures": "cp437",
    "debts": "utf-8",
    "receipts": "utf-8",
    "filings": "utf-8",
}

CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")
DEBT_COLUMNS = _load_columns_for_data_type("debts")
RECEIPT_COLUMNS = _load_columns_for_data_type("receipts")
FILING_COLUMNS = _load_columns_for_data_type("filings")


class PACsvParser:

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        data_type: str,
        row_label: str,
        year: int,
    ):
        self.path = path
        self.columns = columns
        self.data_type = data_type
        self.row_label = row_label
        self.year = year
        self.skipped = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0

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
                yield _normalize_row(raw_row)


def _iter_member_readers(
    path: Path,
    *,
    data_type: str,
    year: int,
) -> Iterator[tuple[str, csv.DictReader]]:
    encoding = _PA_ENCODING_BY_TYPE[data_type]

    if path.suffix.lower() != ".zip":
        with path.open("r", encoding=encoding, errors="replace", newline="") as csv_file:
            reader = csv.DictReader(
                csv_file,
                restkey=_EXTRA_FIELD_SENTINEL,
                restval=_MISSING_FIELD_SENTINEL,
            )
            yield path.name, reader
        return

    with zipfile.ZipFile(path) as archive:
        member_name = _select_pa_member_name(archive, data_type=data_type, year=year)
        _validate_zip_member_size(archive, member_name)
        with archive.open(member_name) as member_stream:
            with io.TextIOWrapper(member_stream, encoding=encoding, errors="replace", newline="") as csv_file:
                reader = csv.DictReader(
                    csv_file,
                    restkey=_EXTRA_FIELD_SENTINEL,
                    restval=_MISSING_FIELD_SENTINEL,
                )
                yield member_name, reader


def _select_pa_member_name(archive: zipfile.ZipFile, *, data_type: str, year: int) -> str:
    """Find the ZIP member matching the requested data type and year.

    PA publishes two naming conventions across different years:
      - Legacy: '{prefix}_{year}.txt'       e.g. 'contrib_2024.txt'
      - Live:   '{year}_{prefix}_Redacted.txt'  e.g. '2026_contrib_Redacted.txt'
    We accept either format so the parser works against both fixtures and
    real government downloads.
    """
    member_prefix = _PA_MEMBER_PREFIX_BY_TYPE.get(data_type)
    if member_prefix is None:
        raise ValueError(f"Unsupported PA data type: {data_type}")

    # Two known PA ZIP naming patterns (case-insensitive basename match)
    legacy_name = f"{member_prefix}_{year}.txt"  # contrib_2026.txt
    live_name = f"{year}_{member_prefix}_redacted.txt"  # 2026_contrib_Redacted.txt

    member_names = [member.filename for member in archive.infolist() if not member.is_dir()]
    matches = [name for name in member_names if Path(name).name.lower() in (legacy_name.lower(), live_name.lower())]

    if len(matches) != 1:
        raise ValueError(
            f"PA ZIP must contain exactly one member matching '{legacy_name}' or '{live_name}' (found {len(matches)})"
        )

    return matches[0]


def _validate_zip_member_size(archive: zipfile.ZipFile, member_name: str) -> None:
    member_info = archive.getinfo(member_name)
    # Reject unexpectedly large members before decompression to keep ingest bounded.
    if member_info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(
            f"PA ZIP member {Path(member_name).name!r} exceeds the allowed size limit of {MAX_ZIP_MEMBER_BYTES} bytes"
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


def parse_contributions(path: Path, year: int) -> PACsvParser:
    return PACsvParser(
        path=path, columns=CONTRIBUTION_COLUMNS, data_type="contributions", row_label="contribution", year=year
    )


def parse_expenditures(path: Path, year: int) -> PACsvParser:
    return PACsvParser(
        path=path, columns=EXPENDITURE_COLUMNS, data_type="expenditures", row_label="expenditure", year=year
    )


def parse_debts(path: Path, year: int) -> PACsvParser:
    return PACsvParser(path=path, columns=DEBT_COLUMNS, data_type="debts", row_label="debt", year=year)


def parse_receipts(path: Path, year: int) -> PACsvParser:
    return PACsvParser(path=path, columns=RECEIPT_COLUMNS, data_type="receipts", row_label="receipt", year=year)


def parse_filings(path: Path, year: int) -> PACsvParser:
    return PACsvParser(path=path, columns=FILING_COLUMNS, data_type="filings", row_label="filing", year=year)
