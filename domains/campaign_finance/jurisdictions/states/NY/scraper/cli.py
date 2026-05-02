"""CLI for NY campaign finance pipeline — download from SODA API and load into DB.

Used by the refresh runner (run_ny_refresh) and manually via:
  python -m domains.campaign_finance.jurisdictions.states.NY.scraper.cli \
    --download --data-type contributions
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_ny_csv
from .load import (
    LoadResult,
    _NY_PARSER_FN,
    _load_ny_with_filings,
)

_SUPPORTED_DATA_TYPES = ("contributions", "expenditures", "independent_expenditures")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be >= 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for NY campaign finance loader."""
    parser = argparse.ArgumentParser(
        description="Load New York campaign-finance SODA data into Civibus",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--path", type=Path, help="Path to a local NY CSV file")
    input_group.add_argument(
        "--download",
        action="store_true",
        help="Download current NY CSV export from data.ny.gov SODA API",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(_SUPPORTED_DATA_TYPES),
        help="NY data type to ingest",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        help="Max rows to process (download is also capped when using --download)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and count without writing to DB")
    return parser


def _validate_data_type(data_type: str) -> str:
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported NY data type: {data_type}")
    return data_type


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"NY {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _resolve_input_path(
    args: argparse.Namespace,
    *,
    download_limit: int | None = None,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Resolve the input CSV path — either from --path or by downloading."""
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"ny-{args.data_type}-")
    try:
        download_path = download_ny_csv(
            args.data_type,
            dest_dir=Path(temp_dir.name),
            limit=download_limit,
        )
        return download_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    """Dry-run: parse and count rows without loading."""
    normalized = _validate_data_type(data_type)
    parser = _NY_PARSER_FN[normalized](path)

    count = 0
    for index, _row in enumerate(parser, start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _load_path(
    connection: psycopg.Connection,
    input_path: Path,
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    """Load a CSV file into the database."""
    normalized = _validate_data_type(data_type)
    return _load_ny_with_filings(connection, input_path, data_type=normalized, limit=limit)


def run_ny_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    """Entry point for the refresh runner. Downloads and loads NY data.

    Args:
        data_type: "contributions", "expenditures", or "independent_expenditures"
        path: Path to a local CSV file (mutually exclusive with download)
        download: If True, download from SODA API first
        limit: Max rows to load (None = all)

    Returns:
        LoadResult with insert/skip/error counts.
    """
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("NY refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("NY refresh accepts path or download mode, not both")

    args = argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        limit=limit,
        dry_run=False,
    )
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection: psycopg.Connection | None = None
    try:
        input_path, temp_dir = _resolve_input_path(args, download_limit=limit)
        connection = get_connection()
        load_result = _load_path(connection, input_path, data_type=data_type, limit=limit)
        connection.commit()
        return load_result
    finally:
        if connection is not None:
            connection.close()
        if temp_dir is not None:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args, download_limit=args.limit)
            try:
                count = _count_rows(input_path, data_type=args.data_type, limit=args.limit)
            finally:
                if temp_dir is not None:
                    temp_dir.cleanup()
            print(f"NY {args.data_type} dry-run: parsed_row_count={count}")
            return 0

        load_result = run_ny_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"NY ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
