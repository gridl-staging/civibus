
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from core.db import get_connection

from .download import (
    DEFAULT_PAGE_SIZE,
    PHLCartoQuery,
    write_rows_to_jsonl,
)
from .load import (
    LoadResult,
    load_phl_relational,
    load_phl_source_records,
)

_SUPPORTED_DATA_TYPES = ("contributions", "expenditures")
_DATA_TYPE_TO_TABLE = {
    "contributions": "campfin_contributions",
    "expenditures": "campfin_expenditures",
}


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be >= 0")
    return value


def _add_data_type_argument(p: argparse.ArgumentParser) -> None:
    """Attach the --data-type argument shared by every subcommand."""
    p.add_argument(
        "--data-type",
        type=str,
        choices=list(_SUPPORTED_DATA_TYPES),
        required=True,
        help="Which PHL data set to ingest",
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PHL Carto SQL campaign-finance ingest",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download",
        help="Download from Carto SQL API to a JSONL file",
    )
    _add_data_type_argument(download_parser)
    download_parser.add_argument("--output", type=Path, required=True, help="Destination JSONL path")
    download_parser.add_argument(
        "--limit",
        type=_non_negative_int,
        help="Optional row cap (applied via SQL LIMIT, not post-filter)",
    )

    load_parser = subparsers.add_parser(
        "load",
        help="Load a JSONL file into core.source_record",
    )
    _add_data_type_argument(load_parser)
    load_parser.add_argument("--path", type=Path, required=True, help="Source JSONL")
    load_parser.add_argument("--limit", type=_non_negative_int, help="Optional max rows to load")

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="Download + load in one shot (uses a temporary JSONL file)",
    )
    _add_data_type_argument(refresh_parser)
    refresh_parser.add_argument("--limit", type=_non_negative_int, help="Optional row cap")

    return parser


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"PHL {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _build_query_for_data_type(data_type: str, limit: int | None) -> PHLCartoQuery:
    """Build the per-page Carto SQL query for a data type.

    `limit` here is the *total* row cap the operator wants. We pass it
    through to PHLCartoQuery.limit so the SQL `LIMIT` clause caps the
    first (and only, when limit < DEFAULT_PAGE_SIZE) page response too,
    but the ACTUAL total bound is enforced by passing `total_limit` to
    write_rows_to_jsonl / iter_all_rows separately. See iter_all_rows
    docstring for why page_size and total cap are different concepts.
    """
    table = _DATA_TYPE_TO_TABLE[data_type]
    if limit is not None:
        # Cap the per-page request to the user's total cap when smaller
        # than the default page size, so we don't waste a 5000-row
        # response just to throw 4995 away.
        page_size = min(limit, DEFAULT_PAGE_SIZE) if limit > 0 else DEFAULT_PAGE_SIZE
        return PHLCartoQuery(table=table, limit=page_size)
    return PHLCartoQuery(table=table)


def _run_download(args: argparse.Namespace) -> int:
    query = _build_query_for_data_type(args.data_type, args.limit)
    count = write_rows_to_jsonl(query, args.output, total_limit=args.limit)
    print(f"PHL {args.data_type} download complete: rows={count} dest={args.output}")
    return 0


def _run_load(args: argparse.Namespace) -> int:
    if not args.path.exists():
        print(f"ERROR: input path does not exist: {args.path}", file=sys.stderr)
        return 2
    is_expenditure = args.data_type == "expenditures"
    conn = get_connection()
    try:
        result = load_phl_source_records(
            conn,
            args.path,
            is_expenditure=is_expenditure,
            limit=args.limit,
        )
        conn.commit()
    finally:
        conn.close()
    _print_load_summary(result, args.data_type)
    return 0 if result.errors == 0 else 1


def _run_refresh(args: argparse.Namespace) -> int:
    query = _build_query_for_data_type(args.data_type, args.limit)
    is_expenditure = args.data_type == "expenditures"
    with tempfile.TemporaryDirectory(prefix=f"phl-{args.data_type}-") as temp_dir:
        jsonl = Path(temp_dir) / f"phl_{args.data_type}.jsonl"
        count = write_rows_to_jsonl(query, jsonl, total_limit=args.limit)
        print(f"PHL {args.data_type} download complete: rows={count}")
        conn = get_connection()
        try:
            result = load_phl_source_records(
                conn,
                jsonl,
                is_expenditure=is_expenditure,
                limit=args.limit,
            )
            conn.commit()
            pass2 = load_phl_relational(
                conn,
                jsonl,
                is_expenditure=is_expenditure,
                limit=args.limit,
            )
            conn.commit()
        finally:
            conn.close()
    _print_load_summary(result, args.data_type)
    print(
        f"PHL {args.data_type} pass-2 relational complete: "
        f"inserted={pass2.inserted} skipped={pass2.skipped} "
        f"errors={pass2.errors} elapsed={pass2.elapsed_seconds:.2f}s"
    )
    return 0 if (result.errors == 0 and pass2.errors == 0) else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    if args.command == "download":
        return _run_download(args)
    if args.command == "load":
        return _run_load(args)
    if args.command == "refresh":
        return _run_refresh(args)
    parser.error(f"Unknown command: {args.command}")
    return 2  # unreachable, parser.error sys.exits


def run_phl_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> "LoadResult":
    """Public API for the canonical refresh runner.

    Mirrors the SF/NYC `run_*_refresh` shape so `core/refresh/job_builders.py`
    can wire PHL into the same `_download_refresh_callable` adapter.

    `data_type` must be one of `_SUPPORTED_DATA_TYPES`. `download=True`
    pulls fresh JSONL via the Carto SQL API into a temporary file then
    loads it; `path=...` skips the download and loads an existing JSONL.
    The two are mutually exclusive.
    """
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported PHL data_type: {data_type!r}")
    if path is None and not download:
        raise ValueError("PHL refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("PHL refresh accepts path or download mode, not both")

    is_expenditure = data_type == "expenditures"
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    conn = None
    try:
        if download:
            temp_dir = tempfile.TemporaryDirectory(prefix=f"phl-{data_type}-")
            jsonl_path = Path(temp_dir.name) / f"phl_{data_type}.jsonl"
            query = _build_query_for_data_type(data_type, limit)
            write_rows_to_jsonl(query, jsonl_path, total_limit=limit)
        else:
            assert path is not None  # noqa: S101 — guaranteed by branch above
            jsonl_path = path
        conn = get_connection()
        result = load_phl_source_records(
            conn,
            jsonl_path,
            is_expenditure=is_expenditure,
            limit=limit,
        )
        conn.commit()
        _print_load_summary(result, data_type)
        # Pass-2: relational projection from source_record provenance into
        # cf.committee/filing/transaction. Pass-1 must commit first so
        # pass-2's source_record dedupe lookups see the just-inserted rows
        # under READ COMMITTED.
        pass2 = load_phl_relational(
            conn,
            jsonl_path,
            is_expenditure=is_expenditure,
            limit=limit,
        )
        conn.commit()
        print(
            f"PHL {data_type} pass-2 relational complete: "
            f"inserted={pass2.inserted} skipped={pass2.skipped} "
            f"errors={pass2.errors} elapsed={pass2.elapsed_seconds:.2f}s"
        )
        return result
    finally:
        if conn is not None:
            conn.close()
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
