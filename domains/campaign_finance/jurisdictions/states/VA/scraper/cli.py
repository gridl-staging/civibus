"""Virginia campaign finance CLI entry point.

Supports:
  --path <file>      Parse a local VA CSV file
  --download         Download from the VA SBE portal
  --data-type        contributions | expenditures
  --year-month       YYYY_MM for download mode (e.g. 2026_03)
  --limit N          Max rows to process
  --dry-run          Parse and count without writing to DB

Example usage:
  # Dry-run against a local file
  python -m domains.campaign_finance.jurisdictions.states.VA.scraper.cli \
      --path data/va_contributions.csv --data-type contributions --dry-run

  # Download and dry-run
  python -m domains.campaign_finance.jurisdictions.states.VA.scraper.cli \
      --download --data-type contributions --year-month 2026_03 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection
from .download import download_va_csv
from .load import (
    LoadResult,
    load_va_contributions_with_filings,
    load_va_expenditures_with_filings,
)
from .parse import parse_contributions, parse_expenditures

# Data types supported by this CLI
_SUPPORTED_DATA_TYPES = ("contributions", "expenditures")


def _non_negative_int(raw_value: str) -> int:
    """Argparse type for non-negative integers."""
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for the VA scraper."""
    parser = argparse.ArgumentParser(description="Load Virginia campaign-finance SBE CSV data into Civibus")

    # Input source: either a local file or download from portal
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local VA CSV file")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download VA CSV from the SBE portal for the selected data type and month",
    )

    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(_SUPPORTED_DATA_TYPES),
        help="VA data type to ingest",
    )
    parser.add_argument(
        "--year-month",
        type=str,
        default=None,
        help="Month to download in YYYY_MM format (required for --download mode)",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        help="Optional maximum rows to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report row count without writing to DB",
    )

    return parser


def _validate_data_type(data_type: str) -> str:
    """Raise ValueError if data_type is not supported."""
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported VA data type: {data_type}")
    return data_type


def _parser_for_data_type(data_type: str):
    """Return the appropriate parser function for the given data type."""
    normalized = _validate_data_type(data_type)
    if normalized == "contributions":
        return parse_contributions
    return parse_expenditures


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    """Parse a CSV and count rows, optionally capped by limit."""
    parser = _parser_for_data_type(data_type)(path)
    count = 0
    for index, _row in enumerate(parser, start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    """Print a summary line for dry-run mode."""
    print(f"VA {data_type} dry-run: parsed {parsed_count} rows")


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    """Print a summary line after a real load."""
    print(
        f"VA {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    """Clean up a temporary directory if one was created."""
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(
    args: argparse.Namespace,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Resolve the input path from either --path or --download mode.

    For --download, creates a temp directory, downloads the CSV into it,
    and returns the path along with the temp dir (for cleanup).
    """
    if args.path is not None:
        return args.path, None

    # Download mode requires --year-month
    if not args.year_month:
        raise ValueError("--year-month is required when using --download mode")

    temp_dir = tempfile.TemporaryDirectory(prefix=f"va-{args.data_type}-")
    try:
        download_path = download_va_csv(
            args.data_type,
            dest_dir=Path(temp_dir.name),
            year_month=args.year_month,
        )
        return download_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def run_va_refresh(
    *,
    data_type: str,
    year_month: str | None = None,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> LoadResult | int:
    """Programmatic entry point for VA data refresh.

    Returns a LoadResult for real loads, or row count (int) for dry-run.
    """
    _validate_data_type(data_type)

    args = argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        year_month=year_month,
        limit=limit,
        dry_run=dry_run,
    )

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection: psycopg.Connection | None = None
    try:
        input_path, temp_dir = _resolve_input_path(args)

        if dry_run:
            return _count_rows(input_path, data_type=data_type, limit=limit)

        loader = (
            load_va_contributions_with_filings if data_type == "contributions" else load_va_expenditures_with_filings
        )
        connection = get_connection()
        result = loader(connection, input_path, limit=limit)
        return result
    finally:
        if connection is not None:
            connection.close()
        _cleanup_temp_dir(temp_dir)


def main(argv: list[str] | None = None) -> int:
    """CLI main entry point. Returns 0 on success, 1 on failure."""
    args = _build_argument_parser().parse_args(argv)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    try:
        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args)
            row_count = _count_rows(input_path, data_type=args.data_type, limit=args.limit)
            _print_dry_run_summary(args.data_type, row_count)
            return 0

        # Non-dry-run: attempt full load (currently stubbed)
        result = run_va_refresh(
            data_type=args.data_type,
            year_month=args.year_month,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )

        if isinstance(result, LoadResult):
            _print_load_summary(result, args.data_type)
        return 0

    except Exception as error:  # noqa: BLE001
        print(f"VA ingest failed: {error}", file=sys.stderr)
        return 1
    finally:
        _cleanup_temp_dir(temp_dir)


if __name__ == "__main__":
    raise SystemExit(main())
