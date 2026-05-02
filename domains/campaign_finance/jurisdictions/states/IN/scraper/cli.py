"""
Stub summary for IN scraper CLI.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_in_data
from .load import (
    LoadResult,
    load_in_contributions_with_filings,
    load_in_expenditures_with_filings,
)
from .parse import parse_contributions, parse_expenditures


@dataclass(frozen=True, slots=True)
class _INCliDataTypeSpec:
    parse_rows: Callable[[Path], Iterable[Mapping[str, str | None]]]
    load_rows: Callable[..., LoadResult]


def _parse_contribution_rows(path: Path) -> Iterable[Mapping[str, str | None]]:
    return parse_contributions(path)


def _parse_expenditure_rows(path: Path) -> Iterable[Mapping[str, str | None]]:
    return parse_expenditures(path)


def _load_contribution_rows(
    connection: psycopg.Connection,
    path: str | Path,
    *,
    limit: int | None,
) -> LoadResult:
    return load_in_contributions_with_filings(connection, path, limit=limit)


def _load_expenditure_rows(
    connection: psycopg.Connection,
    path: str | Path,
    *,
    limit: int | None,
) -> LoadResult:
    return load_in_expenditures_with_filings(connection, path, limit=limit)


_IN_CLI_DATA_TYPE_SPECS = {
    "contributions": _INCliDataTypeSpec(
        parse_rows=_parse_contribution_rows,
        load_rows=_load_contribution_rows,
    ),
    "expenditures": _INCliDataTypeSpec(
        parse_rows=_parse_expenditure_rows,
        load_rows=_load_expenditure_rows,
    ),
}


def _cli_data_type_spec(data_type: str) -> _INCliDataTypeSpec:
    try:
        return _IN_CLI_DATA_TYPE_SPECS[data_type]
    except KeyError as error:
        raise ValueError(f"Unsupported IN data type: {data_type}") from error


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Indiana campaign-finance data into Civibus")
    parser.add_argument(
        "--data-type",
        required=True,
        choices=tuple(_IN_CLI_DATA_TYPE_SPECS),
        help="IN data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local IN CSV file or yearly ZIP archive")
    input_source_group.add_argument("--download", action="store_true", help="Download IN yearly ZIP before parsing")

    # Download-only parameter — validated in main() when --download is set.
    parser.add_argument("--year", type=int, help="IN data year (required with --download)")

    return parser


def _build_args(
    *,
    data_type: str,
    path: Path | None,
    download: bool,
    year: int | None,
    limit: int | None,
    dry_run: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        year=year,
        limit=limit,
        dry_run=dry_run,
    )


def _validate_download_args(args: argparse.Namespace) -> str | None:
    if args.year is None:
        return "--download requires --year"
    return None


def _validate_refresh_args(args: argparse.Namespace) -> None:
    _cli_data_type_spec(args.data_type)
    if args.path is None and not args.download:
        raise ValueError("IN refresh requires either path or download mode")
    if args.path is not None and args.download:
        raise ValueError("IN refresh accepts path or download mode, not both")
    if args.download:
        error = _validate_download_args(args)
        if error:
            raise ValueError(error)


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"in-{args.data_type}-{args.year}-")
    try:
        archive_path = download_in_data(year=args.year, data_type=args.data_type, dest_dir=Path(temp_dir.name))
        return archive_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    parser = _cli_data_type_spec(data_type).parse_rows(path)
    count = 0
    for index, _row in enumerate(parser, start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _load_path(
    connection: psycopg.Connection,
    path: Path,
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    return _cli_data_type_spec(data_type).load_rows(connection, path, limit=limit)


def _load_resolved_path(
    path: Path,
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    connection = get_connection()
    try:
        load_result = _load_path(connection, path, data_type=data_type, limit=limit)
        connection.commit()
        return load_result
    finally:
        connection.close()


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"IN {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"IN {data_type} dry-run: parsed {parsed_count} rows")


def run_in_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    year: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    args = _build_args(
        data_type=data_type,
        path=path,
        download=download,
        year=year,
        limit=limit,
    )
    _validate_refresh_args(args)

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        resolved_path, temp_dir = _resolve_input_path(args)
        return _load_resolved_path(resolved_path, data_type=data_type, limit=limit)
    finally:
        _cleanup_temp_dir(temp_dir)


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.dry_run:
            _validate_refresh_args(args)
            path, temp_dir = _resolve_input_path(args)
            _print_dry_run_summary(args.data_type, _count_rows(path, data_type=args.data_type, limit=args.limit))
            return 0

        load_result = run_in_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            year=args.year,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"IN ingest failed: {error}", file=sys.stderr)
        return 1
    finally:
        _cleanup_temp_dir(temp_dir)

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
