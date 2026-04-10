"""Indiana scraper parser utilities."""

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
_LEGACY_ENCODINGS = ("cp1252", "latin-1")

CONTRIBUTION_COLUMNS = _load_columns_for_data_type("contributions")
EXPENDITURE_COLUMNS = _load_columns_for_data_type("expenditures")


class INCsvParser:
    """Iterate Indiana CSV rows as normalized dictionaries."""

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        data_type: str,
        row_label: str,
    ):
        self.path = path
        self.columns = columns
        self.data_type = data_type
        self.row_label = row_label
        self.skipped = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0

        for source_name, reader in _iter_member_readers(self.path):
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


def _iter_member_readers(path: Path) -> Iterator[tuple[str, csv.DictReader[str]]]:
    """Yield one CSV reader from plain CSV input or a single-member Indiana archive."""
    if path.suffix.lower() != ".zip":
        yield path.name, _dict_reader_from_bytes(_read_plain_csv_bytes(path))
        return

    with zipfile.ZipFile(path) as archive:
        member_name = _select_single_csv_member(archive)
        _validate_zip_member_size(archive, member_name)
        with archive.open(member_name) as member_stream:
            yield member_name, _dict_reader_from_bytes(member_stream.read())


def _select_single_csv_member(archive: zipfile.ZipFile) -> str:
    member_names = [member.filename for member in archive.infolist() if not member.is_dir()]
    csv_members = [name for name in member_names if Path(name).suffix.lower() == ".csv"]

    if len(csv_members) != 1:
        raise ValueError("IN ZIP must contain exactly one CSV member")

    return csv_members[0]


def _dict_reader_from_bytes(payload: bytes) -> csv.DictReader[str]:
    decoded_payload = _decode_single_byte_text(payload)
    return csv.DictReader(
        io.StringIO(decoded_payload, newline=""),
        restkey=_EXTRA_FIELD_SENTINEL,
        restval=_MISSING_FIELD_SENTINEL,
    )


def _decode_single_byte_text(payload: bytes) -> str:
    last_error: UnicodeDecodeError | None = None

    # Indiana exports are legacy single-byte, but contributions can include bytes
    # undefined in cp1252 (for example 0x81), so we fall back to latin-1.
    for encoding in _LEGACY_ENCODINGS:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError as error:
            last_error = error

    raise ValueError("Unable to decode IN CSV payload as a supported legacy single-byte encoding") from last_error


def _validate_zip_member_size(archive: zipfile.ZipFile, member_name: str) -> None:
    member_info = archive.getinfo(member_name)
    if member_info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(
            f"IN ZIP member {Path(member_name).name!r} exceeds the allowed size limit of {MAX_ZIP_MEMBER_BYTES} bytes"
        )


def _read_plain_csv_bytes(path: Path) -> bytes:
    if path.stat().st_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(f"IN CSV file {path.name!r} exceeds the allowed size limit of {MAX_ZIP_MEMBER_BYTES} bytes")
    return path.read_bytes()


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


def parse_contributions(path: Path) -> INCsvParser:
    return INCsvParser(path=path, columns=CONTRIBUTION_COLUMNS, data_type="contributions", row_label="contribution")


def parse_expenditures(path: Path) -> INCsvParser:
    return INCsvParser(path=path, columns=EXPENDITURE_COLUMNS, data_type="expenditures", row_label="expenditure")
