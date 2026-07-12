"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/CO/scraper/parse.py.
"""

from __future__ import annotations

import csv
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Mapping

from . import _find_co_data_source_block

LOGGER = logging.getLogger(__name__)

_CONTRIBUTION_SOURCE_NAME = "TRACER Bulk Download — Contributions"
_EXPENDITURE_SOURCE_NAME = "TRACER Bulk Download — Expenditures"
_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()
_LLC_MEMBER_PATTERN = re.compile(r"^(.+?)\s*\(Member of LLC:\s*(.+?)\)$")
_CO_DATE_TIME_SUFFIX_PATTERN = re.compile(r"\s+\d{2}:\d{2}:\d{2}$")


@lru_cache(maxsize=None)
def _load_columns(source_name: str) -> tuple[str, ...]:
    data_source_block = _find_co_data_source_block(source_name)
    if data_source_block is None:
        raise RuntimeError(f"Could not load CO columns from config.yaml for source {source_name!r}")

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

        columns.append(stripped_line.split(":", maxsplit=1)[0])

    if columns:
        return tuple(columns)

    raise RuntimeError(f"Could not load CO columns from config.yaml for source {source_name!r}")


CONTRIBUTION_COLUMNS = _load_columns(_CONTRIBUTION_SOURCE_NAME)
EXPENDITURE_COLUMNS = _load_columns(_EXPENDITURE_SOURCE_NAME)


class COTracerCsvParser:

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...] = CONTRIBUTION_COLUMNS,
        row_label: str = "contribution",
    ):
        self.path = path
        self.columns = columns
        self.row_label = row_label
        self.skipped = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0

        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as csv_file:
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

                yield _normalize_row(raw_row)


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


def parse_contributions(path: Path) -> COTracerCsvParser:
    return COTracerCsvParser(path=path)


def parse_expenditures(path: Path) -> COTracerCsvParser:
    return COTracerCsvParser(path=path, columns=EXPENDITURE_COLUMNS, row_label="expenditure")


def is_superseded(row: Mapping[str, object]) -> bool:
    return row.get("Amended") == "Y"


def parse_contributor_type(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None

    match = _LLC_MEMBER_PATTERN.match(raw)
    if match is None:
        return raw, None

    base_type, llc_name = match.groups()
    return base_type, llc_name


def parse_co_date(raw: str | None) -> str | None:
    if raw is None:
        return None

    normalized = raw.strip()
    if not normalized:
        return None

    return _CO_DATE_TIME_SUFFIX_PATTERN.sub("", normalized)
