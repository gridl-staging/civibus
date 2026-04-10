
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_tx_archive
from .load import (
    LoadResult,
    load_tx_contributions_with_filings,
    load_tx_expenditures_with_filings,
    load_tx_loans_with_filings,
)
from .parse import parse_contributions, parse_expenditures, parse_loans

_TX_DATA_TYPES = ("contributions", "expenditures", "loans")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Texas campaign-finance data into Civibus")
    parser.add_argument(
        "--data-type",
        required=True,
        choices=["contributions", "expenditures", "loans"],
        help="TX data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local TX CSV file or TEC_CF_CSV.zip archive")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download TEC_CF_CSV.zip before parsing",
    )

    return parser


def _build_args(
    *,
    data_type: str,
    path: Path | None,
    download: bool,
    limit: int | None,
) -> argparse.Namespace:
    return argparse.Namespace(path=path, download=download, data_type=data_type, limit=limit, dry_run=False)


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"tx-{args.data_type}-")
    try:
        archive_path = download_tx_archive(args.data_type, Path(temp_dir.name))
        return archive_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _validate_data_type(data_type: str) -> str:
    if data_type not in _TX_DATA_TYPES:
        raise ValueError(f"Unsupported TX data type: {data_type}")
    return data_type


def _parser_for_data_type(data_type: str):
    normalized_data_type = _validate_data_type(data_type)
    return {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
        "loans": parse_loans,
    }[normalized_data_type]


def _count_limited_rows(rows: object, *, limit: int | None) -> int:
    count = 0
    for index, _row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    return _count_limited_rows(_parser_for_data_type(data_type)(path), limit=limit)


def _load_path(
    connection: psycopg.Connection,
    path: Path,
    *,
    data_type: str,
    limit: int | None,
    year_from: int | None = None,
) -> LoadResult:
    normalized_data_type = _validate_data_type(data_type)
    loader = {
        "contributions": load_tx_contributions_with_filings,
        "expenditures": load_tx_expenditures_with_filings,
        "loans": load_tx_loans_with_filings,
    }[normalized_data_type]
    return loader(connection, path, limit=limit, year_from=year_from)


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"TX {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"TX {data_type} dry-run: parsed {parsed_count} rows")


def _load_resolved_path(
    path: Path,
    *,
    data_type: str,
    limit: int | None,
    year_from: int | None = None,
) -> LoadResult:
    connection = get_connection()
    try:
        load_result = _load_path(connection, path, data_type=data_type, limit=limit, year_from=year_from)
        connection.commit()
        return load_result
    finally:
        connection.close()


def run_tx_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("TX refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("TX refresh accepts path or download mode, not both")

    args = _build_args(data_type=data_type, path=path, download=download, limit=limit)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        resolved_path, temp_dir = _resolve_input_path(args)
        return _load_resolved_path(resolved_path, data_type=data_type, limit=limit, year_from=year_from)
    finally:
        _cleanup_temp_dir(temp_dir)


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            path, temp_dir = _resolve_input_path(args)
            try:
                _print_dry_run_summary(args.data_type, _count_rows(path, data_type=args.data_type, limit=args.limit))
                return 0
            finally:
                _cleanup_temp_dir(temp_dir)

        load_result = run_tx_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"TX ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
