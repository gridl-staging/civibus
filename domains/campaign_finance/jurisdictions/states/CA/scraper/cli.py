
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

import psycopg

from core.db import get_connection

from .download import download_ca_archive, extract_ingestion_members
from .load import LoadResult, load_ca_member_directory_with_filings
from .parse import parse_table

_TRANSACTION_TABLES = ("RCPT_CD", "EXPN_CD", "LOAN_CD")
_CA_DOWNLOAD_TEMPDIR_PREFIX = "ca-download-"
_CA_ARCHIVE_TEMPDIR_PREFIX = "ca-archive-"
_DEFAULT_HOST_MODE_CONNECTION_ERROR_PREFIX = "Unable to connect to PostgreSQL at "
_DEFAULT_HOST_MODE_CONNECTION_ERROR_SUFFIXES = (":5432/", ":5433/")


def _purge_stale_ca_temp_dirs(
    *,
    tempdir_root: Path | None = None,
    age_threshold_seconds: int = 24 * 3600,
    logger: Callable[[str], None] = print,
    process_iter: Callable | None = None,
) -> list[str]:
    removed_dirs: list[str] = []
    target_root = tempdir_root or Path(tempfile.gettempdir())
    now = time.time()
    tempdir_prefixes = (_CA_DOWNLOAD_TEMPDIR_PREFIX, _CA_ARCHIVE_TEMPDIR_PREFIX)

    resolved_process_iter = process_iter
    if resolved_process_iter is None:
        try:
            import psutil  # type: ignore
        except ImportError:
            resolved_process_iter = None
        else:
            resolved_process_iter = psutil.process_iter

    def _has_live_handle(candidate_dir: Path) -> bool:
        if resolved_process_iter is None:
            return True
        try:
            processes = resolved_process_iter()
        except Exception:  # noqa: BLE001
            return True
        resolved_candidate_dir = candidate_dir.resolve(strict=False)
        for process in processes:
            try:
                open_files = process.open_files()
            except Exception:  # noqa: BLE001
                continue
            if not open_files:
                continue
            for open_file in open_files:
                open_path = getattr(open_file, "path", None)
                if not open_path:
                    continue
                try:
                    resolved_open_path = Path(open_path).resolve(strict=False)
                except Exception:  # noqa: BLE001
                    continue
                if resolved_open_path == resolved_candidate_dir or resolved_candidate_dir in resolved_open_path.parents:
                    return True
        return False

    try:
        candidate_dirs = target_root.iterdir()
    except Exception:  # noqa: BLE001
        return removed_dirs

    for candidate_dir in candidate_dirs:
        if not candidate_dir.is_dir():
            continue
        if not candidate_dir.name.startswith(tempdir_prefixes):
            continue
        try:
            age_seconds = now - candidate_dir.stat().st_mtime
        except Exception:  # noqa: BLE001
            continue
        if age_seconds < age_threshold_seconds:
            continue
        if _has_live_handle(candidate_dir):
            continue
        try:
            shutil.rmtree(candidate_dir)
        except Exception:  # noqa: BLE001
            continue
        removed_dirs.append(candidate_dir.name)
        try:
            logger(f"Removed stale CA tempdir: {candidate_dir}")
        except Exception:  # noqa: BLE001
            pass

    return removed_dirs


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
            temp_dir = tempfile.TemporaryDirectory(prefix=_CA_ARCHIVE_TEMPDIR_PREFIX)
            try:
                return _extract_archive_to_temp_dir(args.path, temp_dir=temp_dir), temp_dir
            except Exception:
                temp_dir.cleanup()
                raise
        raise FileNotFoundError(f"CA input path does not exist: {args.path}")

    temp_dir = tempfile.TemporaryDirectory(prefix=_CA_DOWNLOAD_TEMPDIR_PREFIX)
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


def _should_retry_ca_connection_on_production_host(error: RuntimeError) -> bool:
    raw_host = os.getenv("POSTGRES_HOST")
    raw_port = os.getenv("POSTGRES_PORT")
    if raw_host is not None or raw_port is not None:
        configured_host = (raw_host or "localhost").strip().lower()
        configured_port = (raw_port or "5433").strip()
        if configured_host == "db" and not os.path.exists("/.dockerenv"):
            configured_host = "127.0.0.1"
        default_host_mode_is_explicit = configured_host in {"localhost", "127.0.0.1"} and configured_port in {
            "5432",
            "5433",
        }
        if not default_host_mode_is_explicit:
            return False
    error_message = str(error)
    if not error_message.startswith(_DEFAULT_HOST_MODE_CONNECTION_ERROR_PREFIX):
        return False
    error_target = error_message.removeprefix(_DEFAULT_HOST_MODE_CONNECTION_ERROR_PREFIX)
    retry_hosts = ("localhost", "127.0.0.1")
    for retry_host in retry_hosts:
        for port_suffix in _DEFAULT_HOST_MODE_CONNECTION_ERROR_SUFFIXES:
            if error_target.startswith(f"{retry_host}{port_suffix}"):
                return True
    return False


def _open_ca_connection() -> psycopg.Connection:
    try:
        return get_connection()
    except RuntimeError as connection_error:
        if not _should_retry_ca_connection_on_production_host(connection_error):
            raise
    return get_connection(host="127.0.0.1", port=5432)


def run_ca_refresh(
    *,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    try:
        _purge_stale_ca_temp_dirs()
    except Exception:  # noqa: BLE001
        pass

    if path is None and not download:
        raise ValueError("CA refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("CA refresh accepts path or download mode, not both")

    args = argparse.Namespace(path=path, download=download, limit=limit, dry_run=False)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection: psycopg.Connection | None = None
    try:
        input_directory, temp_dir = _resolve_input_directory(args)
        connection = _open_ca_connection()
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
            try:
                _purge_stale_ca_temp_dirs()
            except Exception:  # noqa: BLE001
                pass
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
