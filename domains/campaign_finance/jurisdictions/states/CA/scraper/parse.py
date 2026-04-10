
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterator

from . import _load_column_for_semantic_path, _load_columns_for_table

LOGGER = logging.getLogger(__name__)


def _resolve_date_column_for_table(table_name: str) -> str | None:
    """Look up the TSV column mapped to 'transaction.date' for this table.

    Returns None if the table has no transaction.date mapping (e.g. filer
    tables like CVR_CAMPAIGN_DISCLOSURE_CD, FILERNAME_CD, FILERS_CD).
    """
    try:
        return _load_column_for_semantic_path(table_name, "transaction.date")
    except RuntimeError:
        # Table has no transaction.date mapping — not a transaction table
        return None


def _extract_year_from_ca_date(date_value: str) -> int | None:
    """Extract the 4-digit year from a CA MM/DD/YYYY date string.

    Returns None if the string is too short or the year portion isn't numeric.
    CA dates are consistently MM/DD/YYYY but we also accept YYYY-MM-DD as a
    fallback since _parse_optional_ca_date in the loader handles both formats.

    Known limitation: single-digit month dates (e.g. "3/15/2020") would return
    None because they're 9 chars (not 10) and don't match either pattern. This
    is conservative — those rows pass through the filter rather than being
    dropped. The loader's strptime handles them fine. CAL-ACCESS typically
    zero-pads months, so this is a theoretical rather than practical gap.
    """
    if not date_value:
        return None

    # Try MM/DD/YYYY first (primary CA format) — year is after second slash
    if len(date_value) >= 10 and date_value[2] == "/" and date_value[5] == "/":
        try:
            return int(date_value[6:10])
        except ValueError:
            return None

    # Fallback: YYYY-MM-DD — year is the first 4 chars
    if len(date_value) >= 4 and date_value[4:5] in ("-", ""):
        try:
            return int(date_value[:4])
        except ValueError:
            return None

    return None


class CATsvParser:

    def __init__(
        self,
        path: Path,
        *,
        columns: tuple[str, ...],
        table_name: str,
        date_column: str | None = None,
        year_from: int | None = None,
    ):
        self.path = path
        self.columns = columns
        self.table_name = table_name
        # date_column: TSV column containing MM/DD/YYYY date for year filtering
        self.date_column = date_column
        # year_from: if set, skip rows where date year < year_from
        self.year_from = year_from
        self.skipped = 0
        self.filtered = 0

    def __iter__(self) -> Iterator[dict[str, str | None]]:
        self.skipped = 0
        self.filtered = 0

        # Resolve the date column index for year filtering. If date_column
        # is set but not present in the configured columns, filtering is
        # silently disabled (the column may exist in the header but not in
        # the config — the parser only knows about configured columns).
        date_column_name = self.date_column if self.year_from is not None else None

        with self.path.open("r", encoding="utf-8", errors="replace") as tsv_file:
            reader = csv.reader(tsv_file, delimiter="\t")
            header = next(reader, None)
            if header is None:
                return

            header_index_by_name: dict[str, int] = {}
            duplicate_header_names: set[str] = set()
            for index, column_name in enumerate(header):
                if column_name in header_index_by_name:
                    duplicate_header_names.add(column_name)
                    continue
                header_index_by_name[column_name] = index

            missing_columns = [column for column in self.columns if column not in header_index_by_name]
            duplicate_expected_columns = [column for column in self.columns if column in duplicate_header_names]
            if missing_columns or duplicate_expected_columns:
                raise ValueError(
                    f"Unexpected header for CA table {self.table_name}: "
                    f"expected columns {self.columns!r}, got {tuple(header)!r}; "
                    f"missing={tuple(missing_columns)!r}; "
                    f"duplicate_expected={tuple(duplicate_expected_columns)!r}"
                )

            column_indexes = tuple(header_index_by_name[column] for column in self.columns)
            row_width = len(header)

            # Resolve the index of the date column in the *header* (not in
            # the configured columns) so we can cheaply check it per row.
            date_col_header_index: int | None = None
            if date_column_name is not None:
                date_col_header_index = header_index_by_name.get(date_column_name)

            for line_num, raw_fields in enumerate(reader, start=2):
                if len(raw_fields) != row_width:
                    self.skipped += 1
                    LOGGER.warning(
                        "Skipping malformed %s row at line %d: expected %d fields, got %d",
                        self.table_name,
                        line_num,
                        row_width,
                        len(raw_fields),
                    )
                    continue

                # Year filter: skip rows older than the cutoff.
                # CA dates are MM/DD/YYYY; _extract_year_from_ca_date handles both formats.
                if date_col_header_index is not None and self.year_from is not None:
                    raw_date = raw_fields[date_col_header_index]
                    if raw_date:  # only filter if date is non-empty
                        row_year = _extract_year_from_ca_date(raw_date)
                        if row_year is not None and row_year < self.year_from:
                            self.filtered += 1
                            continue

                yield {
                    column: (raw_fields[column_index] if raw_fields[column_index] != "" else None)
                    for column, column_index in zip(self.columns, column_indexes)
                }


def parse_table(path: Path, table_name: str, *, year_from: int | None = None) -> CATsvParser:
    """Create a parser for a specific CA table using config-derived columns.

    year_from: if set, only return rows where the transaction date year >= year_from.
    Only effective for transaction tables (RCPT_CD, EXPN_CD, LOAN_CD) that have a
    'transaction.date' semantic mapping. Non-transaction tables silently ignore it.
    """
    columns = _load_columns_for_table(table_name)
    # Only resolve date_column if year_from filtering is requested
    date_column = _resolve_date_column_for_table(table_name) if year_from is not None else None
    return CATsvParser(
        path=path,
        columns=columns,
        table_name=table_name,
        date_column=date_column,
        year_from=year_from,
    )
