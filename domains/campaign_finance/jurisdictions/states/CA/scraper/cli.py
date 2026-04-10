
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection

from .download import download_ca_archive, extract_ingestion_members
from .load import LoadResult, load_ca_member_directory_with_filings
from .parse import parse_table

_TRANSACTION_TABLES = ("RCPT_CD", "EXPN_CD", "LOAN_CD")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load California CAL-ACCESS data into Civibus")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--path", type=Path, help="Path to a local CA archive ZIP or extracted member directory")
    input_group.add_argument("--download", action="store_true", help="Download the latest CA raw-data archive")
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load across CA tables")
    parser.add_argument(
        "--year-from",
        type=int,
        help="Only load transaction rows from this year onwards (default: all years). "
        "CA data goes back to 1999; use e.g. --year-from 2022 to load only recent data.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and count transaction rows without loading")
    return parser


def _extract_archive_to_temp_dir(archive_path: Path, *, temp_dir: tempfile.TemporaryDirectory[str]) -> Path:
    extracted_members = extract_ingestion_members(archive_path, dest_dir=Path(temp_dir.name))
    if not extracted_members:
        raise RuntimeError("CA archive extraction produced no ingestion members")
    first_extracted_path = next(iter(extracted_members.values()))
    return first_extracted_path.parent


def _resolve_input_directory(
    args: argparse.Namespace,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        if args.path.is_dir():
            return args.path, None
        if args.path.is_file():
            temp_dir = tempfile.TemporaryDirectory(prefix="ca-archive-")
            try:
                return _extract_archive_to_temp_dir(args.path, temp_dir=temp_dir), temp_dir
            except Exception:
                temp_dir.cleanup()
                raise
        raise FileNotFoundError(f"CA input path does not exist: {args.path}")

    temp_dir = tempfile.TemporaryDirectory(prefix="ca-download-")
    destination_dir = Path(temp_dir.name)
    try:
        archive_path = download_ca_archive(dest_dir=destination_dir)
        return _extract_archive_to_temp_dir(archive_path, temp_dir=temp_dir), temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_transaction_rows(member_dir: Path, *, year_from: int | None = None) -> int:
    total = 0
    for table_name in _TRANSACTION_TABLES:
        total += sum(1 for _ in parse_table(member_dir / f"{table_name}.TSV", table_name, year_from=year_from))
    return total


def _print_load_summary(result: LoadResult) -> None:
    print(
        "CA load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def run_ca_refresh(
    *,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    if path is None and not download:
        raise ValueError("CA refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("CA refresh accepts path or download mode, not both")

    args = argparse.Namespace(path=path, download=download, limit=limit, dry_run=False)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection: psycopg.Connection | None = None
    try:
        input_directory, temp_dir = _resolve_input_directory(args)
        connection = get_connection()
        load_result = load_ca_member_directory_with_filings(
            connection,
            input_directory,
            limit=limit,
            year_from=year_from,
        )
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
            input_directory, temp_dir = _resolve_input_directory(args)
            try:
                count = _count_transaction_rows(input_directory, year_from=args.year_from)
                print(f"CA dry-run: parsed {count} rows (year_from={args.year_from})")
                return 0
            finally:
                if temp_dir is not None:
                    temp_dir.cleanup()

        load_result = run_ca_refresh(
            path=args.path,
            download=args.download,
            limit=args.limit,
            year_from=args.year_from,
        )
    except Exception as error:  # noqa: BLE001
        print(f"CA ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
