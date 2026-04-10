
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_mn_csv
from .load import (
    LoadResult,
    load_mn_contributions_with_filings,
    load_mn_expenditures_with_filings,
    load_mn_independent_expenditures_with_filings,
)
from .parse import parse_contributions, parse_expenditures, parse_independent_expenditures

_SUPPORTED_DATA_TYPES = ("contributions", "expenditures", "independent_expenditures")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Minnesota campaign-finance CSV data into Civibus")
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local MN CSV export")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download current MN CSV export for the selected data type",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(_SUPPORTED_DATA_TYPES),
        help="MN data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")
    return parser


def _validate_data_type(data_type: str) -> str:
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported MN data type: {data_type}")
    return data_type


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"MN {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"MN {data_type} dry-run: parsed {parsed_count} rows")


def _resolve_input_path(
    args: argparse.Namespace,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"mn-{args.data_type}-")
    try:
        download_path = download_mn_csv(args.data_type, dest_dir=Path(temp_dir.name))
        return download_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    normalized_data_type = _validate_data_type(data_type)
    parser = {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
        "independent_expenditures": parse_independent_expenditures,
    }[normalized_data_type](path)
    if limit is None:
        return sum(1 for _row in parser)
    return sum(1 for _row in zip(range(limit), parser))


def _load_path(
    connection: psycopg.Connection,
    input_path: Path,
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    normalized_data_type = _validate_data_type(data_type)
    loader = {
        "contributions": load_mn_contributions_with_filings,
        "expenditures": load_mn_expenditures_with_filings,
        "independent_expenditures": load_mn_independent_expenditures_with_filings,
    }[normalized_data_type]
    return loader(connection, input_path, limit=limit)


def run_mn_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("MN refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("MN refresh accepts path or download mode, not both")

    args = argparse.Namespace(path=path, download=download, data_type=data_type, limit=limit, dry_run=False)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection: psycopg.Connection | None = None
    try:
        input_path, temp_dir = _resolve_input_path(args)
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
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args)
            _print_dry_run_summary(
                args.data_type,
                _count_rows(input_path, data_type=args.data_type, limit=args.limit),
            )
            if temp_dir is not None:
                temp_dir.cleanup()
            return 0

        load_result = run_mn_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"MN ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
