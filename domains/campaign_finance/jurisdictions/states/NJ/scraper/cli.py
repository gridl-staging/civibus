"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_am_3_new_state_pipeline_builds/civibus_dev/domains/campaign_finance/jurisdictions/states/NJ/scraper/cli.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from core.db import get_connection

from .download import download_nj_csv
from .load import LoadResult, load_nj_contributions_with_filings
from .parse import parse_contributions

_SUPPORTED_DATA_TYPES = ("contributions",)


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load New Jersey campaign-finance contribution data into Civibus")
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local NJ CSV export")
    input_source_group.add_argument(
        "--download", action="store_true", help="Download NJ CSV export for the selected data type"
    )
    parser.add_argument("--data-type", required=True, help="NJ data type to ingest")
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")
    return parser


def _validate_data_type(data_type: str) -> str:
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported NJ data type: {data_type}")
    return data_type


def _build_args(
    *,
    data_type: str,
    path: Path | None,
    download: bool,
    limit: int | None,
    dry_run: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(path=path, download=download, data_type=data_type, limit=limit, dry_run=dry_run)


def _validate_refresh_args(args: argparse.Namespace) -> None:
    _validate_data_type(args.data_type)
    if args.path is None and not args.download:
        raise ValueError("NJ refresh requires either path or download mode")
    if args.path is not None and args.download:
        raise ValueError("NJ refresh accepts path or download mode, not both")


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"NJ {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"NJ {data_type} dry-run: parsed {parsed_count} rows")


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"nj-{args.data_type}-")
    try:
        download_path = download_nj_csv(args.data_type, dest_dir=Path(temp_dir.name))
        return download_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, limit: int | None) -> int:
    count = 0
    for index, _row in enumerate(parse_contributions(path), start=1):
        if limit is not None and index > limit:
            break
        count += 1
    return count


def _load_path(
    connection: object,
    input_path: Path,
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    _validate_data_type(data_type)
    return load_nj_contributions_with_filings(connection, input_path, limit=limit)


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


def run_nj_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    args = _build_args(data_type=data_type, path=path, download=download, limit=limit)
    _validate_refresh_args(args)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        input_path, temp_dir = _resolve_input_path(args)
        return _load_resolved_path(input_path, data_type=data_type, limit=limit)
    finally:
        _cleanup_temp_dir(temp_dir)


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    try:
        _validate_refresh_args(args)

        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args)
            _print_dry_run_summary(args.data_type, _count_rows(input_path, limit=args.limit))
            return 0

        load_result = run_nj_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"NJ ingest failed: {error}", file=sys.stderr)
        return 1
    finally:
        _cleanup_temp_dir(temp_dir)

    _print_load_summary(load_result, args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
