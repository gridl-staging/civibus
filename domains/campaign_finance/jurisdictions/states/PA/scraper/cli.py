"""
Stub summary for mar24_pm_3_freshness_truth_pa_mn_in/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/cli.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_pa_archive
from .load import (
    LoadResult,
    load_pa_contributions_with_filings,
    load_pa_debts_with_filings,
    load_pa_expenditures_with_filings,
    load_pa_receipts_with_filings,
)
from .parse import (
    parse_contributions,
    parse_debts,
    parse_expenditures,
    parse_filings,
    parse_receipts,
)

PA_LOADABLE_REFRESH_DATA_TYPES = ("contributions", "expenditures", "debts", "receipts")
_PA_CLI_DATA_TYPES = (*PA_LOADABLE_REFRESH_DATA_TYPES, "filings")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Pennsylvania campaign-finance data into Civibus")
    parser.add_argument("--year", required=True, type=int, help="PA yearly archive year")
    parser.add_argument(
        "--data-type",
        required=True,
        choices=_PA_CLI_DATA_TYPES,
        help="PA data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local PA archive or extracted data file")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download the PA annual archive for the selected year and data type",
    )
    return parser


def _build_args(
    *,
    year: int,
    data_type: str,
    path: Path | None,
    download: bool,
    limit: int | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        year=year,
        data_type=data_type,
        path=path,
        download=download,
        limit=limit,
        dry_run=False,
    )


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"pa-{args.data_type}-{args.year}-")
    try:
        archive_path = download_pa_archive(args.data_type, args.year, Path(temp_dir.name))
        return archive_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _parser_for_data_type(data_type: str):
    return {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
        "debts": parse_debts,
        "receipts": parse_receipts,
        "filings": parse_filings,
    }[data_type]


def _count_limited_rows(rows: object, *, limit: int | None) -> int:
    count = 0
    for index, _row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _count_rows(path: Path, *, data_type: str, year: int, limit: int | None) -> int:
    return _count_limited_rows(_parser_for_data_type(data_type)(path, year), limit=limit)


def _load_path(
    connection: psycopg.Connection,
    path: Path,
    *,
    data_type: str,
    year: int,
    limit: int | None,
) -> LoadResult:
    # Filing rows are an index used to enrich detail records and are not loaded standalone.
    if data_type == "filings":
        raise ValueError("PA filings data type is supported for parse/dry-run only")

    loader = {
        "contributions": load_pa_contributions_with_filings,
        "expenditures": load_pa_expenditures_with_filings,
        "debts": load_pa_debts_with_filings,
        "receipts": load_pa_receipts_with_filings,
    }[data_type]
    return loader(connection, path, year=year, limit=limit)


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"PA {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"PA {data_type} dry-run: parsed {parsed_count} rows")


def _load_resolved_path(
    path: Path,
    *,
    data_type: str,
    year: int,
    limit: int | None,
) -> LoadResult:
    connection = get_connection()
    try:
        load_result = _load_path(
            connection,
            path,
            data_type=data_type,
            year=year,
            limit=limit,
        )
        connection.commit()
        return load_result
    finally:
        connection.close()


def run_pa_refresh(
    *,
    year: int,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    if data_type == "filings":
        raise ValueError("PA filings data type is supported for parse/dry-run only")
    if data_type not in PA_LOADABLE_REFRESH_DATA_TYPES:
        raise ValueError(f"Unsupported PA data type: {data_type}")
    if path is None and not download:
        raise ValueError("PA refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("PA refresh accepts path or download mode, not both")

    args = _build_args(year=year, data_type=data_type, path=path, download=download, limit=limit)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        input_path, temp_dir = _resolve_input_path(args)
        return _load_resolved_path(
            input_path,
            data_type=data_type,
            year=year,
            limit=limit,
        )
    finally:
        _cleanup_temp_dir(temp_dir)


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args)
            try:
                _print_dry_run_summary(
                    args.data_type,
                    _count_rows(input_path, data_type=args.data_type, year=args.year, limit=args.limit),
                )
                return 0
            finally:
                _cleanup_temp_dir(temp_dir)

        load_result = run_pa_refresh(
            year=args.year,
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"PA ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
