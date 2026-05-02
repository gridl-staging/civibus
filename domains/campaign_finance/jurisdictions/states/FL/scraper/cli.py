"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar25_pm_2_easy_jurisdiction_expansion/civibus_dev/domains/campaign_finance/jurisdictions/states/FL/scraper/cli.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

import psycopg

from core.db import get_connection

from . import load_supported_data_types
from .download import download_fl_export
from .load import (
    LoadResult,
    load_fl_contributions_with_filings,
    load_fl_expenditures_with_filings,
    load_fl_other_with_filings,
    load_fl_transfers_with_filings,
)
from .parse import parse_contributions, parse_expenditures, parse_other, parse_transfers


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Florida campaign-finance TSV data into Civibus")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--path", type=Path, help="Path to a local FL TSV export")
    input_group.add_argument(
        "--download",
        action="store_true",
        help="Download current FL TSV export for the selected data type",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(load_supported_data_types()),
        help="FL data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")
    # FL-specific download parameters
    parser.add_argument("--election", default="All", help="Election filter for FL download (default: All)")
    parser.add_argument(
        "--rowlimit",
        type=_non_negative_int,
        default=100000,
        help="Row limit for FL download",
    )
    parser.add_argument("--date-from", help="Start date for FL download (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="End date for FL download (YYYY-MM-DD)")
    return parser


def _validate_data_type(data_type: str) -> str:
    if data_type not in load_supported_data_types():
        raise ValueError(f"Unsupported FL data type: {data_type}")
    return data_type


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"FL {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"FL {data_type} dry-run: parsed {parsed_count} rows")


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"fl-{args.data_type}-")
    try:
        date_from = date.fromisoformat(args.date_from) if args.date_from else date.today()
        date_to = date.fromisoformat(args.date_to) if args.date_to else date.today()
        download_path = download_fl_export(
            args.data_type,
            date_from=date_from,
            date_to=date_to,
            dest_dir=Path(temp_dir.name),
            election=args.election,
            rowlimit=args.rowlimit,
        )
        return download_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    normalized = _validate_data_type(data_type)
    # Built at call time so monkeypatching module-level names works in tests.
    parser = {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
        "transfers": parse_transfers,
        "other": parse_other,
    }[normalized](path)

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
    normalized = _validate_data_type(data_type)
    loader = {
        "contributions": load_fl_contributions_with_filings,
        "expenditures": load_fl_expenditures_with_filings,
        "transfers": load_fl_transfers_with_filings,
        "other": load_fl_other_with_filings,
    }[normalized]
    return loader(connection, input_path, limit=limit)


def _load_file_to_db(input_path: Path, *, data_type: str, limit: int | None) -> LoadResult:
    """Open DB connection, load file, commit, and close."""
    connection = get_connection()
    try:
        result = _load_path(connection, input_path, data_type=data_type, limit=limit)
        connection.commit()
        return result
    finally:
        connection.close()


def run_fl_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    """Run a FL campaign-finance ingest from path or download.

    Matches WA/TX run_*_refresh signature for refresh runner compatibility.
    Download-specific params (election, rowlimit, date range) use defaults.
    """
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("FL refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("FL refresh accepts path or download mode, not both")

    args = argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        election="All",
        rowlimit=100000,
        date_from=None,
        date_to=None,
    )
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        input_path, temp_dir = _resolve_input_path(args)
        return _load_file_to_db(input_path, data_type=data_type, limit=limit)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def run_fl_officeholder_refresh(
    *,
    rows: list[dict[str, str | None]],
) -> tuple[int, int, int]:
    """Load pre-parsed FL officeholder directory rows into the DB.

    Returns (inserted, skipped, errors) counts.
    """
    from core.types.python.models import DataSource
    from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source

    from .fl_officeholder_loader import load_fl_senate_officeholders

    connection = get_connection()
    try:
        ds_id = ensure_data_source(
            connection,
            DataSource(
                domain="campaign_finance",
                jurisdiction="state/FL/officeholder",
                name="FL Senate Officeholder Directory",
                source_url="https://www.flsenate.gov/Senators",
            ),
        )
        connection.commit()
        result = load_fl_senate_officeholders(connection, rows, data_source_id=ds_id)
        connection.commit()
        return result.inserted, result.skipped, result.errors
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        input_path, temp_dir = _resolve_input_path(args)
        try:
            if args.dry_run:
                _print_dry_run_summary(
                    args.data_type,
                    _count_rows(input_path, data_type=args.data_type, limit=args.limit),
                )
                return 0

            load_result = _load_file_to_db(input_path, data_type=args.data_type, limit=args.limit)
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()
    except Exception as error:  # noqa: BLE001
        print(f"FL ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
