
from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.db import get_connection

from .download import ILDownloadResult, download_il_data_with_metadata
from .load import LoadResult, load_il_contributions_with_filings, load_il_expenditures_with_filings
from .parse import parse_contributions, parse_expenditures

_SUPPORTED_DATA_TYPES = ("contributions", "expenditures")


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Illinois campaign-finance bulk data into Civibus")
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local IL bulk export")
    input_source_group.add_argument(
        "--download", action="store_true", help="Download the selected IL bulk export from the official portal"
    )
    parser.add_argument(
        "--data-type", required=True, choices=list(_SUPPORTED_DATA_TYPES), help="IL data type to ingest"
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument(
        "--download-row-limit",
        type=_non_negative_int,
        help=(
            "When used with --download, stop the live stream after this many data rows and keep only "
            "a valid truncated TSV sample for proof or bounded ingest"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")
    parser.add_argument(
        "--allow-insecure-tls",
        action="store_true",
        help=(
            "Allow retry with TLS certificate verification disabled when download cert validation fails "
            "and CIVIBUS_ALLOW_INSECURE_TLS_RETRY=1 is set"
        ),
    )
    return parser


def _build_args(
    *,
    data_type: str,
    path: Path | None,
    download: bool,
    limit: int | None,
    download_row_limit: int | None = None,
    dry_run: bool = False,
    allow_insecure_tls: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        limit=limit,
        download_row_limit=download_row_limit,
        dry_run=dry_run,
        allow_insecure_tls=allow_insecure_tls,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedInput:
    path: Path
    temp_dir: tempfile.TemporaryDirectory[str] | None
    download_result: ILDownloadResult | None


def _validate_refresh_args(args: argparse.Namespace) -> None:
    if args.data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported IL data type: {args.data_type}")
    if args.path is None and not args.download:
        raise ValueError("IL refresh requires either path or download mode")
    if args.path is not None and args.download:
        raise ValueError("IL refresh accepts path or download mode, not both")
    if args.download_row_limit is not None and not args.download:
        raise ValueError("--download-row-limit requires --download")


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str] | None) -> None:
    if temp_dir is not None:
        temp_dir.cleanup()


def _resolve_input_path(args: argparse.Namespace) -> _ResolvedInput:
    if args.path is not None:
        return _ResolvedInput(path=args.path, temp_dir=None, download_result=None)

    temp_dir = tempfile.TemporaryDirectory(prefix=f"il-{args.data_type}-")
    try:
        download_result = download_il_data_with_metadata(
            args.data_type,
            dest_dir=Path(temp_dir.name),
            allow_insecure_tls=args.allow_insecure_tls,
            max_data_rows=args.download_row_limit,
        )
        return _ResolvedInput(path=download_result.path, temp_dir=temp_dir, download_result=download_result)
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    try:
        parser = parse_contributions(path) if data_type == "contributions" else parse_expenditures(path)
        count = 0
        for index, _row in enumerate(parser, start=1):
            if limit is not None and index > limit:
                break
            count += 1
        return count
    except ValueError as error:
        raise RuntimeError(
            f"IL {data_type} file did not match the expected tab-delimited header; "
            "the portal may have returned HTML or a non-export error page"
        ) from error


def _load_path(connection: object, input_path: Path, *, data_type: str, limit: int | None) -> LoadResult:
    try:
        if data_type == "contributions":
            return load_il_contributions_with_filings(connection, input_path, limit=limit)
        return load_il_expenditures_with_filings(connection, input_path, limit=limit)
    except ValueError as error:
        raise RuntimeError(
            f"IL {data_type} file did not match the expected tab-delimited header; "
            "the portal may have returned HTML or a non-export error page"
        ) from error


def _render_download_metadata(download_result: ILDownloadResult | None) -> str:
    if download_result is None:
        return ""
    rendered_parts = [f"downloaded_bytes={download_result.bytes_written}"]
    if download_result.data_rows_written is not None:
        rendered_parts.append(f"downloaded_rows={download_result.data_rows_written}")
    rendered_parts.append(f"download_truncated={'yes' if download_result.truncated else 'no'}")
    return " " + " ".join(rendered_parts)


def _print_load_summary(result: LoadResult, data_type: str, *, download_result: ILDownloadResult | None = None) -> None:
    print(
        f"IL {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
        f"{_render_download_metadata(download_result)}"
    )


def _print_dry_run_summary(
    data_type: str,
    parsed_count: int,
    *,
    download_result: ILDownloadResult | None = None,
) -> None:
    print(f"IL {data_type} dry-run: parsed={parsed_count} rows{_render_download_metadata(download_result)}")


def _execute_refresh(args: argparse.Namespace) -> tuple[LoadResult, ILDownloadResult | None]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection = get_connection()
    try:
        resolved_input = _resolve_input_path(args)
        temp_dir = resolved_input.temp_dir
        load_result = _load_path(connection, resolved_input.path, data_type=args.data_type, limit=args.limit)
        connection.commit()
        return load_result, resolved_input.download_result
    finally:
        connection.close()
        _cleanup_temp_dir(temp_dir)


def run_il_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    download_row_limit: int | None = None,
    allow_insecure_tls: bool = False,
) -> LoadResult:
    args = _build_args(
        data_type=data_type,
        path=path,
        download=download,
        limit=limit,
        download_row_limit=download_row_limit,
        allow_insecure_tls=allow_insecure_tls,
    )
    _validate_refresh_args(args)
    load_result, _download_result = _execute_refresh(args)
    return load_result


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        _validate_refresh_args(args)
        if args.dry_run:
            resolved_input = _resolve_input_path(args)
            try:
                _print_dry_run_summary(
                    args.data_type,
                    _count_rows(resolved_input.path, data_type=args.data_type, limit=args.limit),
                    download_result=resolved_input.download_result,
                )
            finally:
                _cleanup_temp_dir(resolved_input.temp_dir)
            return 0

        load_result, download_result = _execute_refresh(args)
    except Exception as error:  # noqa: BLE001
        print(f"IL ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, args.data_type, download_result=download_result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
