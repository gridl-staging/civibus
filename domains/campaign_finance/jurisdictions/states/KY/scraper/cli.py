
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from . import load_supported_data_types
from .download import download_ky_csv
from .load import (
    LoadResult,
    load_ky_contributions_with_filings,
    load_ky_expenditures_with_filings,
)
from .parse import parse_contributions, parse_expenditures

KY_LOADABLE_REFRESH_DATA_TYPES = load_supported_data_types()


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Kentucky campaign-finance data into Civibus")
    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(KY_LOADABLE_REFRESH_DATA_TYPES),
        help="KY data type to ingest",
    )
    parser.add_argument("--year-from", type=int, help="Optional lower year bound for parsed transaction dates")
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")
    parser.add_argument("--election-date", type=str, help="Optional election date filter (e.g. 5/19/2026)")

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local KY CSV data file")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download the KY CSV export from KREF for the selected data type",
    )
    return parser


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Resolve the input CSV path: either the given --path or download from KREF."""
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"ky-{args.data_type}-")
    try:
        csv_path = download_ky_csv(
            args.data_type,
            dest_dir=Path(temp_dir.name),
            election_date=getattr(args, "election_date", None),
        )
        return csv_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _validate_data_type(data_type: str) -> str:
    if data_type not in KY_LOADABLE_REFRESH_DATA_TYPES:
        raise ValueError(f"Unsupported KY data type: {data_type}")
    return data_type


def _parser_for_data_type(data_type: str):
    """Return the parse function for the given data type."""
    normalized_data_type = _validate_data_type(data_type)
    return {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
    }[normalized_data_type]


def _count_limited_rows(rows: object, *, limit: int | None) -> int:
    count = 0
    for index, _row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _count_rows(path: Path, *, data_type: str, year_from: int | None, limit: int | None) -> int:
    parse_fn = _parser_for_data_type(data_type)
    return _count_limited_rows(parse_fn(path, year_from=year_from), limit=limit)


def _load_path(
    connection: psycopg.Connection,
    path: Path,
    *,
    data_type: str,
    year_from: int | None,
    limit: int | None,
) -> LoadResult:
    normalized_data_type = _validate_data_type(data_type)
    loader = {
        "contributions": load_ky_contributions_with_filings,
        "expenditures": load_ky_expenditures_with_filings,
    }[normalized_data_type]
    return loader(
        connection,
        path,
        year_from=year_from,
        limit=limit,
    )


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"KY {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"KY {data_type} dry-run: parsed {parsed_count} rows")


def _load_resolved_path(
    path: Path,
    *,
    data_type: str,
    year_from: int | None,
    limit: int | None,
) -> LoadResult:
    """Open a DB connection, load the file, commit, and close."""
    connection = get_connection()
    try:
        load_result = _load_path(connection, path, data_type=data_type, year_from=year_from, limit=limit)
        connection.commit()
        return load_result
    finally:
        connection.close()


def run_ky_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    year_from: int | None = None,
    limit: int | None = None,
    election_date: str | None = None,
) -> LoadResult:
    """Programmatic entry point for the KY refresh pipeline."""
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("KY refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("KY refresh accepts path or download mode, not both")

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        resolved_path, temp_dir = _resolve_input_path(
            argparse.Namespace(
                data_type=data_type,
                path=path,
                download=download,
                limit=limit,
                year_from=year_from,
                dry_run=False,
                election_date=election_date,
            )
        )
        return _load_resolved_path(
            resolved_path,
            data_type=data_type,
            year_from=year_from,
            limit=limit,
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            path, temp_dir = _resolve_input_path(args)
            try:
                _print_dry_run_summary(
                    args.data_type,
                    _count_rows(
                        path,
                        data_type=args.data_type,
                        year_from=args.year_from,
                        limit=args.limit,
                    ),
                )
                return 0
            finally:
                if temp_dir is not None:
                    temp_dir.cleanup()

        load_result = run_ky_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            year_from=args.year_from,
            limit=args.limit,
            election_date=args.election_date,
        )
    except Exception as error:  # noqa: BLE001
        print(f"KY ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
