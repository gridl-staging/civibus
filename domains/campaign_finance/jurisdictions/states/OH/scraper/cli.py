"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar24_pm_3_freshness_truth_pa_mn_in/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/cli.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_oh_csv
from .load import (
    LoadResult,
    load_oh_contributions,
    load_oh_expenditures,
)
from .parse import parse_contributions, parse_expenditures

_OH_REFRESH_DOWNLOAD_COMMITTEE_TYPES = ("CAN", "PAC", "PARTY")
_OH_DATA_TYPES = ("contributions", "expenditures")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load Ohio campaign-finance data into Civibus",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=["contributions", "expenditures"],
        help="OH data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local OH CSV file")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download OH CSV from the Secretary of State website",
    )

    # Download-only parameters — validated in main() when --download is set
    parser.add_argument(
        "--committee-type",
        choices=["CAN", "PAC", "PARTY"],
        help="OH committee type (required with --download)",
    )
    parser.add_argument("--year", type=int, help="OH data year (required with --download)")

    return parser


def _validate_download_args(args: argparse.Namespace) -> str | None:
    """Return an error message if download-mode args are missing, else None."""
    missing = []
    if args.committee_type is None:
        missing.append("--committee-type")
    if args.year is None:
        missing.append("--year")
    if missing:
        return f"--download requires {' and '.join(missing)}"
    return None


def _build_args(
    *,
    year: int,
    data_type: str,
    path: Path | None,
    download: bool,
    limit: int | None,
    committee_type: str | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        limit=limit,
        dry_run=False,
        committee_type=committee_type,
        year=year,
    )


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(
    args: argparse.Namespace,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"oh-{args.data_type}-{args.year}-")
    try:
        csv_path = download_oh_csv(args.data_type, args.committee_type, args.year, Path(temp_dir.name))
        return csv_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _parser_for_data_type(data_type: str):
    return {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
    }[data_type]


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
) -> LoadResult:
    loader = {
        "contributions": load_oh_contributions,
        "expenditures": load_oh_expenditures,
    }[data_type]
    return loader(connection, path, limit=limit)


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"OH {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"OH {data_type} dry-run: parsed {parsed_count} rows")


def _combine_load_results(results: list[LoadResult]) -> LoadResult:
    return LoadResult(
        inserted=sum(result.inserted for result in results),
        skipped=sum(result.skipped for result in results),
        quarantined=sum(result.quarantined for result in results),
        superseded=sum(result.superseded for result in results),
        errors=sum(result.errors for result in results),
        elapsed_seconds=sum(result.elapsed_seconds for result in results),
    )


def _load_resolved_paths(
    paths: list[Path],
    *,
    data_type: str,
    limit: int | None,
) -> list[LoadResult]:
    connection = get_connection()
    try:
        load_results = [_load_path(connection, path, data_type=data_type, limit=limit) for path in paths]
        connection.commit()
        return load_results
    finally:
        connection.close()


def run_oh_refresh(
    *,
    year: int,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    committee_types: tuple[str, ...] | None = None,
) -> LoadResult:
    if data_type not in _OH_DATA_TYPES:
        raise ValueError(f"Unsupported OH data type: {data_type}")
    if path is None and not download:
        raise ValueError("OH refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("OH refresh accepts path or download mode, not both")
    if not download and committee_types is not None:
        raise ValueError("OH committee_types is only supported in download mode")

    resolved_committee_types = committee_types or _OH_REFRESH_DOWNLOAD_COMMITTEE_TYPES
    temp_dirs: list[tempfile.TemporaryDirectory[str]] = []
    try:
        if not download:
            input_path, temp_dir = _resolve_input_path(
                _build_args(
                    year=year,
                    data_type=data_type,
                    path=path,
                    download=False,
                    limit=limit,
                    committee_type=None,
                )
            )
            if temp_dir is not None:
                temp_dirs.append(temp_dir)
            return _load_resolved_paths([input_path], data_type=data_type, limit=limit)[0]

        resolved_paths: list[Path] = []
        for committee_type in resolved_committee_types:
            input_path, temp_dir = _resolve_input_path(
                _build_args(
                    year=year,
                    data_type=data_type,
                    path=None,
                    download=True,
                    limit=limit,
                    committee_type=committee_type,
                )
            )
            if temp_dir is not None:
                temp_dirs.append(temp_dir)
            resolved_paths.append(input_path)

        return _combine_load_results(_load_resolved_paths(resolved_paths, data_type=data_type, limit=limit))
    finally:
        for temp_dir in temp_dirs:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    # Validate download-only args post-parse
    if args.download:
        error = _validate_download_args(args)
        if error:
            print(f"OH ingest failed: {error}", file=sys.stderr)
            return 1

    try:
        if args.dry_run:
            path, temp_dir = _resolve_input_path(args)
            try:
                _print_dry_run_summary(
                    args.data_type,
                    _count_rows(path, data_type=args.data_type, limit=args.limit),
                )
                return 0
            finally:
                _cleanup_temp_dir(temp_dir)

        resolved_year = args.year if args.year is not None else datetime.now(timezone.utc).year
        committee_types = (args.committee_type,) if args.download else None
        load_result = run_oh_refresh(
            year=resolved_year,
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
            committee_types=committee_types,
        )
    except Exception as error:  # noqa: BLE001
        print(f"OH ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
