from __future__ import annotations

import csv
import html
import re
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator

from . import CONTRIBUTION_COLUMNS, EXPENDITURE_COLUMNS

_EXTRA_FIELD_SENTINEL = object()
_MISSING_FIELD_SENTINEL = object()
_DATE_FIELDS = frozenset({"Date"})
_CONTRIBUTION_AMOUNT_FIELDS = frozenset({"Cash_Amount", "In_Kind_Amount"})
_EXPENDITURE_AMOUNT_FIELDS = frozenset({"Paid", "Other"})
_GA_DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"
_GA_AMOUNT_PATTERN = re.compile(r"-?\d+\.\d{4}")
_AMOUNT_QUANTIZE_EXPONENT = Decimal("0.01")
_TABLE_PATTERN = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_ROW_PATTERN = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_PATTERN = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")

type ParsedGAValue = str | Decimal | None
type ParsedGARow = dict[str, ParsedGAValue]


def parse_contributions(path: Path) -> Iterator[ParsedGARow]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(
            csv_file,
            restkey=_EXTRA_FIELD_SENTINEL,
            restval=_MISSING_FIELD_SENTINEL,
        )
        _validate_contribution_header(reader.fieldnames)
        for raw_row in reader:
            if _is_malformed_row(raw_row):
                raise ValueError(f"Malformed contribution CSV row at line {reader.line_num}")
            yield _normalize_contribution_row(raw_row)


def parse_expenditures(path: Path) -> Iterator[ParsedGARow]:
    with path.open("r", encoding="utf-8") as source_file:
        html_text = source_file.read()

    rows = _extract_html_table_rows(html_text)
    if not rows:
        raise ValueError("Missing expenditure HTML header row")

    header_cells = tuple(_normalize_header_cell(cell) for cell in rows[0])
    if header_cells != EXPENDITURE_COLUMNS:
        raise ValueError("Unexpected expenditure HTML header")

    for row_index, row_cells in enumerate(rows[1:], start=1):
        if len(row_cells) != len(EXPENDITURE_COLUMNS):
            raise ValueError(f"Malformed expenditure HTML row at index {row_index}")
        normalized_cells = [_normalize_html_cell(cell) for cell in row_cells]
        raw_values = dict(zip(EXPENDITURE_COLUMNS, normalized_cells, strict=True))
        yield _normalize_ga_row(raw_values, EXPENDITURE_COLUMNS, _EXPENDITURE_AMOUNT_FIELDS)


def parse_ga_date(raw: str | None) -> str | None:
    if raw is None:
        return None

    normalized = raw.strip()
    if not normalized:
        return None

    try:
        parsed_datetime = datetime.strptime(normalized, _GA_DATE_FORMAT)
    except ValueError as error:
        raise ValueError(f"Invalid GA date value: {raw!r}") from error
    if parsed_datetime.time() != time():
        raise ValueError(f"Invalid GA date value: {raw!r}")
    return parsed_datetime.strftime("%Y-%m-%d")


def parse_ga_amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None

    normalized = raw.strip()
    if not normalized:
        return None
    if _GA_AMOUNT_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"Invalid GA amount value: {raw!r}")

    try:
        amount = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError(f"Invalid GA amount value: {raw!r}") from error
    if not amount.is_finite():
        raise ValueError(f"Invalid GA amount value: {raw!r}")
    quantized_amount = amount.quantize(_AMOUNT_QUANTIZE_EXPONENT)
    if quantized_amount != amount:
        raise ValueError(f"Invalid GA amount value: {raw!r}")
    return quantized_amount


def infer_entity_type(last_name: str | None, first_name: str | None) -> str:
    has_last_name = _has_non_blank_text(last_name)
    has_first_name = _has_non_blank_text(first_name)

    if has_last_name and has_first_name:
        return "person"
    if has_last_name:
        return "organization"
    return "unknown"


def _validate_contribution_header(fieldnames: list[str] | None) -> None:
    if tuple(fieldnames or ()) != CONTRIBUTION_COLUMNS:
        raise ValueError("Unexpected contribution CSV header")


def _is_malformed_row(raw_row: dict[object, object]) -> bool:
    return _EXTRA_FIELD_SENTINEL in raw_row or _MISSING_FIELD_SENTINEL in raw_row.values()


def _normalize_contribution_row(raw_row: dict[object, object]) -> ParsedGARow:
    raw_values: dict[str, str | None] = {}
    for column in CONTRIBUTION_COLUMNS:
        raw_values[column] = _normalize_raw_csv_value(raw_row[column], column)
    return _normalize_ga_row(raw_values, CONTRIBUTION_COLUMNS, _CONTRIBUTION_AMOUNT_FIELDS)


def _normalize_raw_csv_value(value: object, column: str) -> str | None:
    if value in ("", None):
        return None
    if isinstance(value, str):
        return value
    raise ValueError(f"Unexpected non-string CSV value for {column!r}: {type(value)!r}")


def _has_non_blank_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _normalize_ga_row(
    raw_values: dict[str, str | None],
    columns: tuple[str, ...],
    amount_fields: frozenset[str],
) -> ParsedGARow:
    normalized_row: ParsedGARow = {}
    for column in columns:
        normalized_row[column] = _normalize_by_field_type(column, raw_values[column], amount_fields)
    return normalized_row


def _normalize_by_field_type(
    column: str,
    raw_value: str | None,
    amount_fields: frozenset[str],
) -> ParsedGAValue:
    if column in _DATE_FIELDS:
        return parse_ga_date(raw_value)
    if column in amount_fields:
        return parse_ga_amount(raw_value)
    return raw_value


def _extract_html_table_rows(html_text: str) -> list[list[str]]:
    table_match = _TABLE_PATTERN.search(html_text)
    if table_match is None:
        return []

    table_html = table_match.group(1)
    parsed_rows: list[list[str]] = []
    for row_match in _ROW_PATTERN.finditer(table_html):
        row_html = row_match.group(1)
        row_cells = [_TAG_PATTERN.sub("", cell_match.group(1)) for cell_match in _CELL_PATTERN.finditer(row_html)]
        if row_cells:
            parsed_rows.append(row_cells)
    return parsed_rows


def _normalize_header_cell(raw_cell: str) -> str:
    normalized = _normalize_html_cell(raw_cell)
    if normalized is None:
        return ""
    return normalized


def _normalize_html_cell(raw_cell: str) -> str | None:
    decoded_cell = html.unescape(raw_cell)
    normalized_whitespace = decoded_cell.replace("\u00a0", " ")
    trimmed_cell = normalized_whitespace.strip()
    if not trimmed_cell:
        return None
    return trimmed_cell


__all__ = [
    "infer_entity_type",
    "parse_contributions",
    "parse_expenditures",
    "parse_ga_amount",
    "parse_ga_date",
]
