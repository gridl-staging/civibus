"""
Stub summary for mar21_01_fec_pipeline_hardening/civibus_dev/domains/campaign_finance/jurisdictions/states/CO/scraper/cli.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import psycopg

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.CO.scraper.download import (
    download_tracer_file,
    extract_csv_from_zip,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import (
    LoadResult,
    load_co_contributions_with_filings,
    load_co_expenditures_with_filings,
)


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Colorado TRACER CSV data into Civibus")
    parser.add_argument("--year", required=True, type=int, help="TRACER bulk download year")
    parser.add_argument(
        "--data-type",
        required=True,
        choices=["contributions", "expenditures"],
        help="TRACER data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument(
        "--allow-insecure-tls",
        action="store_true",
        help=(
            "Allow retry with TLS certificate verification disabled when download cert validation fails "
            "(unsafe; also requires CIVIBUS_ALLOW_INSECURE_TLS_RETRY=1)"
        ),
    )

    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to an existing TRACER CSV file")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download and extract TRACER CSV for the provided year and data type",
    )

    return parser


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"CO {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _resolve_csv_path(
    args: argparse.Namespace,
) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix="co-tracer-")
    dest_dir = Path(temp_dir.name)
    zip_path = download_tracer_file(
        year=args.year,
        data_type=args.data_type,
        dest_dir=dest_dir,
        allow_insecure_tls=args.allow_insecure_tls,
    )
    return extract_csv_from_zip(zip_path, dest_dir=dest_dir), temp_dir


def _load_selected_data_type(
    connection: psycopg.Connection,
    csv_path: Path,
    args: argparse.Namespace,
) -> LoadResult:
    if args.data_type == "expenditures":
        return load_co_expenditures_with_filings(
            connection,
            csv_path,
            limit=args.limit,
        )

    return load_co_contributions_with_filings(
        connection,
        csv_path,
        limit=args.limit,
    )


def run_co_refresh(
    *,
    year: int,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    allow_insecure_tls: bool = False,
) -> LoadResult:
    """Run one CO refresh with typed parameters and no argv synthesis."""
    if path is None and not download:
        raise ValueError("CO refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("CO refresh accepts path or download mode, not both")

    args = argparse.Namespace(
        year=year,
        data_type=data_type,
        path=path,
        download=download,
        limit=limit,
        allow_insecure_tls=allow_insecure_tls,
    )

    connection: psycopg.Connection | None = None
    temp_dir: tempfile.TemporaryDirectory | None = None
    try:
        csv_path, temp_dir = _resolve_csv_path(args)
        connection = get_connection()
        load_result = _load_selected_data_type(connection, csv_path, args)
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
        load_result = run_co_refresh(
            year=args.year,
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
            allow_insecure_tls=args.allow_insecure_tls,
        )
    except Exception as error:  # noqa: BLE001
        print(f"CO ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
