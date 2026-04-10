"""CLI for MA campaign finance pipeline — download from OCPF and load into DB.

MA differs from other states: it downloads per-year ZIP files, extracts
report-items.txt, and loads them. The --download mode pulls all years in
the 5-year window (2022-2026). The --path mode loads a single pre-extracted
report-items.txt file.

Used by the refresh runner (run_ma_refresh) and manually via:
  python -m domains.campaign_finance.jurisdictions.states.MA.scraper.cli \
    --download --data-type contributions
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_ma_report_items
from .load import (
    LoadResult,
    load_ma_contributions_with_filings,
    load_ma_expenditures_with_filings,
)
from .parse import parse_contributions, parse_expenditures

_SUPPORTED_DATA_TYPES = ("contributions", "expenditures")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be >= 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for MA OCPF loader."""
    parser = argparse.ArgumentParser(
        description="Load Massachusetts OCPF campaign-finance data into Civibus",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--path", type=Path, help="Path to a local report-items.txt file")
    input_group.add_argument(
        "--download",
        action="store_true",
        help="Download current OCPF ZIP files and extract report-items.txt",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(_SUPPORTED_DATA_TYPES),
        help="MA data type to ingest (contributions or expenditures from report-items.txt)",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Max rows to load per file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and count without writing to DB")
    return parser


def _validate_data_type(data_type: str) -> str:
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported MA data type: {data_type}")
    return data_type


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"MA {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _resolve_input_paths(args: argparse.Namespace) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None]:
    """Resolve input files — either a single --path or download all years."""
    if args.path is not None:
        return [args.path], None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"ma-{args.data_type}-")
    try:
        paths = download_ma_report_items(Path(temp_dir.name))
        return paths, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(paths: list[Path], *, data_type: str, limit: int | None) -> int:
    """Dry-run: parse and count rows across all files."""
    normalized = _validate_data_type(data_type)
    parse_fn = parse_contributions if normalized == "contributions" else parse_expenditures

    total = 0
    for path in paths:
        for index, _row in enumerate(parse_fn(path), start=1):
            if limit is not None and index > limit:
                break
            total += 1
    return total


def _load_paths(
    connection: psycopg.Connection,
    input_paths: list[Path],
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    """Load all input files, aggregating results."""
    normalized = _validate_data_type(data_type)
    load_fn = load_ma_contributions_with_filings if normalized == "contributions" else load_ma_expenditures_with_filings

    # Aggregate LoadResults across all year files.
    total = LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)
    for path in input_paths:
        result = load_fn(connection, path, limit=limit)
        total.inserted += result.inserted
        total.skipped += result.skipped
        total.quarantined += result.quarantined
        total.errors += result.errors
        total.elapsed_seconds += result.elapsed_seconds
    return total


def run_ma_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    """Entry point for the refresh runner."""
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("MA refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("MA refresh accepts path or download mode, not both")

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
        input_paths, temp_dir = _resolve_input_paths(args)
        connection = get_connection()
        load_result = _load_paths(connection, input_paths, data_type=data_type, limit=limit)
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
            input_paths, temp_dir = _resolve_input_paths(args)
            count = _count_rows(input_paths, data_type=args.data_type, limit=args.limit)
            print(f"MA {args.data_type} dry-run: parsed {count} rows")
            if temp_dir is not None:
                temp_dir.cleanup()
            return 0

        load_result = run_ma_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"MA ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
