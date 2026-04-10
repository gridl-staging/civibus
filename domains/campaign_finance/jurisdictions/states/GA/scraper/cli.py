
from __future__ import annotations

import argparse
import logging
import string
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import psycopg

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.GA.scraper.download import download_ga_export
from domains.campaign_finance.jurisdictions.states.GA.scraper.load import (
    LoadResult,
    load_ga_contributions_with_filings,
    load_ga_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    ParsedGARow,
    parse_contributions,
    parse_expenditures,
)

logger = logging.getLogger(__name__)

# The GA portal's Candidate field is a prefix-match name filter, not a
# race-type selector. An empty candidate returns almost nothing (<10 rows).
# To get comprehensive data, we iterate A-Z as single-letter candidate
# prefixes — each letter returns all candidates whose last name starts with
# that letter. This covers all data without needing a candidate roster.
_ALPHABET_PREFIXES = tuple(string.ascii_uppercase)


@dataclass(frozen=True, slots=True)
class _DataTypeConfig:
    parser: Callable[[Path], Iterator[ParsedGARow]]
    loader: Callable[..., LoadResult]
    label: str


class _GAArgumentParser(argparse.ArgumentParser):

    def parse_args(
        self,
        args: list[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        parsed_args = super().parse_args(args, namespace)
        if parsed_args.download:
            # candidate is optional — empty means "all candidates" on the portal.
            _require_download_options(
                self,
                parsed_args,
                "--date-start",
                "--date-end",
            )
        return parsed_args


_DATA_TYPE_DISPATCH: dict[str, _DataTypeConfig] = {
    "contributions": _DataTypeConfig(
        parser=parse_contributions,
        loader=load_ga_contributions_with_filings,
        label="contributions",
    ),
    "expenditures": _DataTypeConfig(
        parser=parse_expenditures,
        loader=load_ga_expenditures_with_filings,
        label="expenditures",
    ),
}


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _require_download_options(
    parser: argparse.ArgumentParser,
    parsed_args: argparse.Namespace,
    *option_names: str,
) -> None:
    for option_name in option_names:
        attribute_name = option_name.removeprefix("--").replace("-", "_")
        if getattr(parsed_args, attribute_name):
            continue
        parser.error(f"--download requires {option_name}")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = _GAArgumentParser(description="Load Georgia campaign finance data into Civibus")
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a GA export file")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download a GA export from the portal before parsing and loading",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=sorted(_DATA_TYPE_DISPATCH),
        help="GA data type to ingest",
    )
    parser.add_argument("--candidate", help="Candidate name filter used for portal download search")
    parser.add_argument("--date-start", help="Start date filter used for portal download search (MM/DD/YYYY)")
    parser.add_argument("--date-end", help="End date filter used for portal download search (MM/DD/YYYY)")
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without loading")
    return parser


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"GA {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, row_count: int) -> None:
    print(f"GA {data_type} dry-run: parsed {row_count} rows")


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix="ga-portal-")
    destination_directory = Path(temp_dir.name)
    try:
        downloaded_path = download_ga_export(
            args.data_type,
            dest_dir=destination_directory,
            candidate=args.candidate,
            date_start=args.date_start,
            date_end=args.date_end,
        )
    except Exception:
        temp_dir.cleanup()
        raise
    return downloaded_path, temp_dir


def _run_single_candidate_refresh(
    *,
    data_type: str,
    config: _DataTypeConfig,
    candidate: str,
    date_start: str,
    date_end: str,
    limit: int | None = None,
    connection: psycopg.Connection | None = None,
) -> LoadResult:
    """Download, parse, and load GA data for one candidate filter value."""
    args = argparse.Namespace(
        path=None,
        download=True,
        data_type=data_type,
        candidate=candidate,
        date_start=date_start,
        date_end=date_end,
        limit=limit,
        dry_run=False,
    )
    temp_dir: tempfile.TemporaryDirectory | None = None
    owns_connection = connection is None
    try:
        input_path, temp_dir = _resolve_input_path(args)
        if connection is None:
            connection = get_connection()
        load_result = config.loader(connection, input_path, limit=limit)
        connection.commit()
        return load_result
    finally:
        if owns_connection and connection is not None:
            connection.close()
        if temp_dir is not None:
            temp_dir.cleanup()


def _run_alphabet_refresh(
    *,
    data_type: str,
    config: _DataTypeConfig,
    date_start: str,
    date_end: str,
    limit: int | None = None,
) -> LoadResult:
    """Iterate A-Z candidate prefixes to get comprehensive GA data.

    The GA portal requires a candidate name filter to return meaningful
    results. Single-letter prefixes cover all candidates via prefix matching.
    Each letter downloads, parses, and loads independently so partial
    failures don't lose already-loaded data.
    """
    start_time = time.monotonic()
    total_inserted = 0
    total_skipped = 0
    total_errors = 0
    connection: psycopg.Connection | None = None

    try:
        connection = get_connection()
        for letter in _ALPHABET_PREFIXES:
            try:
                result = _run_single_candidate_refresh(
                    data_type=data_type,
                    config=config,
                    candidate=letter,
                    date_start=date_start,
                    date_end=date_end,
                    limit=limit,
                    connection=connection,
                )
                total_inserted += result.inserted
                total_skipped += result.skipped
                total_errors += result.errors
                logger.info(
                    "GA %s letter %s: inserted=%d skipped=%d errors=%d",
                    data_type,
                    letter,
                    result.inserted,
                    result.skipped,
                    result.errors,
                )
            except Exception:
                # Log and continue — don't let one letter block the rest.
                logger.exception("GA %s letter %s failed", data_type, letter)
                total_errors += 1
    finally:
        if connection is not None:
            connection.close()

    elapsed = time.monotonic() - start_time
    return LoadResult(
        inserted=total_inserted,
        skipped=total_skipped,
        errors=total_errors,
        elapsed_seconds=elapsed,
    )


def run_ga_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    candidate: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int | None = None,
) -> LoadResult:
    if data_type not in _DATA_TYPE_DISPATCH:
        raise ValueError(f"Unsupported GA data type: {data_type}")
    if path is None and not download:
        raise ValueError("GA refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("GA refresh accepts path or download mode, not both")
    if download and (not date_start or not date_end):
        raise ValueError("GA download mode requires date_start and date_end")

    config = _DATA_TYPE_DISPATCH[data_type]

    # Path mode: load a single file directly.
    if path is not None:
        connection: psycopg.Connection | None = None
        try:
            connection = get_connection()
            load_result = config.loader(connection, path, limit=limit)
            connection.commit()
            return load_result
        finally:
            if connection is not None:
                connection.close()

    # Download mode: if candidate is specified, download once. If candidate
    # is empty/None, iterate A-Z to get comprehensive coverage.
    if candidate:
        return _run_single_candidate_refresh(
            data_type=data_type,
            config=config,
            candidate=candidate,
            date_start=date_start,
            date_end=date_end,
            limit=limit,
        )

    return _run_alphabet_refresh(
        data_type=data_type,
        config=config,
        date_start=date_start,
        date_end=date_end,
        limit=limit,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    config = _DATA_TYPE_DISPATCH[args.data_type]

    try:
        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args)
            rows = list(config.parser(input_path))
            _print_dry_run_summary(config.label, len(rows))
            if temp_dir is not None:
                temp_dir.cleanup()
            return 0

        load_result = run_ga_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            candidate=args.candidate,
            date_start=args.date_start,
            date_end=args.date_end,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"GA ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, config.label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
