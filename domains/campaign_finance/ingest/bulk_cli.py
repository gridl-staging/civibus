"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/ingest/bulk_cli.py.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
import sys
from time import perf_counter
from typing import Callable, Literal
from uuid import UUID

import psycopg

from core.db import get_connection
from core.graph import age_post_connect, ensure_graph
from domains.campaign_finance.ingest.bulk_loader import (
    LoadResult,
    Stage4LoadOptions,
    ensure_fec_bulk_data_source,
    load_candidate_committee_links,
    load_candidates,
    load_committee_transactions,
    load_committees,
    load_contributions,
    sync_data_source_metadata,
)
from domains.campaign_finance.ingest.schedule_b_loader import load_schedule_b
from domains.campaign_finance.ingest.schedule_e_loader import load_schedule_e

FILE_TYPES: tuple[str, ...] = ("cm", "cn", "ccl", "itcont", "itpas2", "schedule_e", "schedule_b")
FULL_CYCLE_FILE_ORDER: tuple[str, ...] = ("cm", "cn", "ccl", "itcont", "itpas2")
TRANSACTION_FILE_TYPES: frozenset[str] = frozenset({"itcont", "itpas2"})
_BULK_FILE_EXTENSIONS = {".txt", ".zip"}

_FEC_BULK_DOWNLOAD_BASE = "https://www.fec.gov/files/bulk-downloads"
_FEC_BULK_URL_SLUGS: dict[str, str] = {
    "cm": "cm",
    "cn": "cn",
    "ccl": "ccl",
    "itcont": "indiv",
    "itpas2": "pas2",
}


def fec_baseline_url(cycle: int, file_type: str) -> str:
    """Derive the canonical FEC bulk download URL for a cycle and file type."""
    if file_type not in FULL_CYCLE_FILE_ORDER:
        raise ValueError(f"Unknown FEC file type: {file_type}")
    slug = _FEC_BULK_URL_SLUGS[file_type]
    yy = str(cycle)[-2:]
    return f"{_FEC_BULK_DOWNLOAD_BASE}/{cycle}/{slug}{yy}.zip"


def fec_schedule_b_url(cycle: int) -> str:
    yy = str(cycle)[-2:]
    return f"{_FEC_BULK_DOWNLOAD_BASE}/{cycle}/oppexp{yy}.zip"


def fec_schedule_e_url(cycle: int) -> str:
    filename = f"independent_expenditure_{cycle}.csv"
    return f"{_FEC_BULK_DOWNLOAD_BASE}/{cycle}/{filename}"


def fec_baseline_urls(cycle: int) -> dict[str, str]:
    """Return the canonical FEC bulk download URL for every file type in the full cycle."""
    return {ft: fec_baseline_url(cycle, ft) for ft in FULL_CYCLE_FILE_ORDER}


def effective_limit_for_dispatch(file_type: str, config: "CliConfig") -> int | None:
    """Return the row limit for a file type. In full-cycle mode, only transaction files are limited."""
    if config.limit is None:
        return None
    if config.mode == "single":
        return config.limit
    if file_type in TRANSACTION_FILE_TYPES:
        return config.limit
    return None


@dataclass(frozen=True, slots=True)
class CliConfig:
    mode: Literal["single", "full"]
    cycle: int
    file_type: str | None
    path: Path | None
    directory: Path | None
    batch_size: int
    limit: int | None
    graph_enabled: bool
    with_transactions: bool = False


@dataclass(frozen=True, slots=True)
class LoaderSpec:
    loader: Callable[..., LoadResult]
    requires_cycle: bool
    supports_graph: bool


@dataclass(frozen=True, slots=True)
class LoadStepSummary:
    file_type: str
    source_path: Path
    result: LoadResult
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class LoadRequest:
    file_type: str
    path: Path


@dataclass(frozen=True, slots=True)
class FullCycleFinalizationOutcome:
    pull_status: str
    record_count: int


FILE_TYPE_LOADERS: dict[str, LoaderSpec] = {
    "cm": LoaderSpec(loader=load_committees, requires_cycle=True, supports_graph=False),
    "cn": LoaderSpec(loader=load_candidates, requires_cycle=True, supports_graph=False),
    "ccl": LoaderSpec(loader=load_candidate_committee_links, requires_cycle=True, supports_graph=False),
    "itcont": LoaderSpec(loader=load_contributions, requires_cycle=False, supports_graph=True),
    "itpas2": LoaderSpec(loader=load_committee_transactions, requires_cycle=False, supports_graph=True),
    "schedule_e": LoaderSpec(loader=load_schedule_e, requires_cycle=True, supports_graph=True),
    "schedule_b": LoaderSpec(loader=load_schedule_b, requires_cycle=True, supports_graph=True),
}


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load FEC bulk files into Civibus")
    parser.add_argument("--cycle", required=True, type=int, help="Election cycle year (example: 2024)")
    parser.add_argument("--file-type", choices=FILE_TYPES, help="Single-file mode file type")
    parser.add_argument("--path", type=Path, help="Single-file mode bulk file path")
    parser.add_argument("--all", action="store_true", help="Full-cycle mode")
    parser.add_argument("--directory", type=Path, help="Full-cycle mode directory path")
    parser.add_argument("--batch-size", type=int, default=1000, help="Commit interval (default: 1000)")
    parser.add_argument("--limit", type=int, help="Maximum rows per file")
    parser.add_argument("--graph", action="store_true", help="Enable graph loading for itcont/itpas2")
    parser.add_argument(
        "--with-transactions",
        action="store_true",
        help="For itcont/itpas2: also upsert cf.filing and cf.transaction rows from mapped records",
    )
    return parser


def _is_readable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.R_OK)


def _is_readable_directory(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.R_OK)


def _build_cli_config(
    args: argparse.Namespace,
    *,
    mode: Literal["single", "full"],
    file_type: str | None,
    path: Path | None,
    directory: Path | None,
) -> CliConfig:
    return CliConfig(
        mode=mode,
        cycle=args.cycle,
        file_type=file_type,
        path=path,
        directory=directory,
        batch_size=args.batch_size,
        limit=args.limit,
        graph_enabled=args.graph,
        with_transactions=args.with_transactions,
    )


def validate_cli_arguments(args: argparse.Namespace) -> CliConfig:
    if args.batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("limit must be greater than zero")

    single_mode_selected = args.file_type is not None or args.path is not None
    full_mode_selected = args.all or args.directory is not None

    if single_mode_selected and full_mode_selected:
        raise ValueError("single-file mode and full-cycle mode are mutually exclusive")

    if single_mode_selected:
        if args.file_type is None or args.path is None:
            raise ValueError("single-file mode requires both --file-type and --path")
        if not _is_readable_file(args.path):
            raise ValueError(f"single-file mode requires a readable file path: {args.path}")
        if args.with_transactions and args.file_type not in {"itcont", "itpas2"}:
            raise ValueError("--with-transactions is supported only for itcont and itpas2 single-file loads")
        return _build_cli_config(args, mode="single", file_type=args.file_type, path=args.path, directory=None)

    if full_mode_selected:
        if not args.all or args.directory is None:
            raise ValueError("full-cycle mode requires both --all and --directory")
        if not _is_readable_directory(args.directory):
            raise ValueError(f"full-cycle mode requires a readable directory path: {args.directory}")
        return _build_cli_config(args, mode="full", file_type=None, path=None, directory=args.directory)

    raise ValueError("Select either single-file mode (--file-type + --path) or full-cycle mode (--all + --directory)")


def _matches_file_type(path: Path, file_type: str) -> bool:
    if path.suffix.lower() not in _BULK_FILE_EXTENSIONS:
        return False

    normalized_name = path.name.lower()
    aliases = {file_type.lower(), _FEC_BULK_URL_SLUGS.get(file_type, file_type).lower()}
    return any(
        normalized_name.startswith(alias) or f"_{alias}" in normalized_name or f"-{alias}" in normalized_name
        for alias in aliases
    )


def _resolve_full_cycle_file_path(directory: Path, files_in_directory: list[Path], file_type: str) -> Path:
    matches = [path for path in files_in_directory if _matches_file_type(path, file_type)]
    if not matches:
        raise ValueError(f"Missing required bulk file for file_type={file_type} in {directory}")
    if len(matches) > 1:
        matched_names = ", ".join(sorted(path.name for path in matches))
        raise ValueError(f"Ambiguous bulk files for file_type={file_type}: {matched_names}")

    matched_path = matches[0]
    if not _is_readable_file(matched_path):
        raise ValueError(f"Unreadable bulk file for file_type={file_type}: {matched_path}")
    return matched_path


def resolve_full_cycle_directory(directory: Path) -> dict[str, Path]:
    resolved_paths: dict[str, Path] = {}
    files_in_directory = [path for path in directory.iterdir() if path.is_file()]
    assigned_file_types: dict[Path, str] = {}

    for file_type in FULL_CYCLE_FILE_ORDER:
        matched_path = _resolve_full_cycle_file_path(directory, files_in_directory, file_type)
        prior_file_type = assigned_file_types.get(matched_path)
        if prior_file_type is not None:
            raise ValueError(
                f"Bulk file {matched_path.name} matches multiple required file types: {prior_file_type}, {file_type}"
            )
        assigned_file_types[matched_path] = file_type
        resolved_paths[file_type] = matched_path

    return resolved_paths


def bootstrap_connection(*, graph_enabled: bool) -> psycopg.Connection:
    post_connect = age_post_connect if graph_enabled else None
    connection = get_connection(post_connect=post_connect)
    if graph_enabled:
        try:
            ensure_graph(connection)
            connection.commit()
        except Exception:
            connection.close()
            raise
    return connection


def dispatch_load(
    *,
    conn: psycopg.Connection,
    config: CliConfig,
    request: LoadRequest,
    data_source_id: UUID,
) -> LoadResult:
    loader_spec = FILE_TYPE_LOADERS[request.file_type]
    effective_limit = effective_limit_for_dispatch(request.file_type, config)
    loader_kwargs: dict[str, object] = {"data_source_id": data_source_id}
    if loader_spec.requires_cycle:
        loader_kwargs["batch_size"] = config.batch_size
        loader_kwargs["limit"] = effective_limit
        loader_kwargs["cycle"] = config.cycle
    else:
        loader_kwargs["options"] = Stage4LoadOptions(
            batch_size=config.batch_size,
            limit=effective_limit,
            graph_enabled=config.graph_enabled and loader_spec.supports_graph,
            with_transactions=config.with_transactions,
        )

    return loader_spec.loader(conn, request.path, **loader_kwargs)


def _run_load_phase(
    *,
    conn: psycopg.Connection,
    config: CliConfig,
    request: LoadRequest,
    data_source_id: UUID,
) -> LoadStepSummary:
    started_at = perf_counter()
    try:
        load_result = dispatch_load(
            conn=conn,
            config=config,
            request=request,
            data_source_id=data_source_id,
        )
    except Exception as error:
        raise RuntimeError(f"{request.file_type} phase failed for {request.path}: {error}") from error

    return LoadStepSummary(
        file_type=request.file_type,
        source_path=request.path,
        result=load_result,
        elapsed_seconds=perf_counter() - started_at,
    )


def load_full_cycle(
    *,
    conn: psycopg.Connection,
    config: CliConfig,
    data_source_id: UUID,
    resolved_paths: dict[str, Path],
) -> list[LoadStepSummary]:
    assert config.mode == "full"

    return [
        _run_load_phase(
            conn=conn,
            config=config,
            request=LoadRequest(file_type=file_type, path=resolved_paths[file_type]),
            data_source_id=data_source_id,
        )
        for file_type in FULL_CYCLE_FILE_ORDER
    ]


def print_summary(summaries: list[LoadStepSummary]) -> None:
    total_inserted = 0
    total_skipped = 0
    total_errors = 0
    total_elapsed = 0.0

    print("Bulk ingest summary")
    print("file_type | source_path | inserted | skipped | errors | elapsed_s")
    for summary in summaries:
        print(
            f"{summary.file_type} | {summary.source_path} | "
            f"{summary.result.inserted} | {summary.result.skipped} | {summary.result.errors} | "
            f"{summary.elapsed_seconds:.2f}"
        )
        total_inserted += summary.result.inserted
        total_skipped += summary.result.skipped
        total_errors += summary.result.errors
        total_elapsed += summary.elapsed_seconds

    print(
        f"Totals: inserted={total_inserted} skipped={total_skipped} errors={total_errors} elapsed={total_elapsed:.2f}s"
    )


def derive_pull_status(summaries: list[LoadStepSummary]) -> str:
    """Derive pull_status from load step summaries: success, partial, or failed."""
    total_errors = sum(s.result.errors for s in summaries)
    total_successes = sum(s.result.inserted + s.result.skipped for s in summaries)
    if total_errors == 0:
        return "success"
    if total_successes > 0:
        return "partial"
    return "failed"


def finalize_full_cycle_metadata(
    conn: psycopg.Connection,
    data_source_id: UUID,
    summaries: list[LoadStepSummary],
) -> FullCycleFinalizationOutcome:
    """Finalize metadata for full-cycle runs using one shared status+sync path."""
    pull_status = derive_pull_status(summaries)
    record_count = sync_data_source_metadata(conn, data_source_id, pull_status=pull_status)
    return FullCycleFinalizationOutcome(pull_status=pull_status, record_count=record_count)


def _run_single_file_mode(
    *,
    conn: psycopg.Connection,
    config: CliConfig,
    data_source_id: UUID,
) -> list[LoadStepSummary]:
    assert config.file_type is not None
    assert config.path is not None

    return [
        _run_load_phase(
            conn=conn,
            config=config,
            request=LoadRequest(file_type=config.file_type, path=config.path),
            data_source_id=data_source_id,
        )
    ]


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        config = validate_cli_arguments(args)
    except ValueError as error:
        print(f"CLI validation failed: {error}", file=sys.stderr)
        return 2

    resolved_paths: dict[str, Path] | None = None
    if config.mode == "full":
        assert config.directory is not None
        try:
            resolved_paths = resolve_full_cycle_directory(config.directory)
        except ValueError as error:
            print(f"Bulk ingest setup failed: {error}", file=sys.stderr)
            return 1

    connection: psycopg.Connection | None = None
    try:
        connection = bootstrap_connection(graph_enabled=config.graph_enabled)
        with connection.transaction():
            data_source_id = ensure_fec_bulk_data_source(connection)

        if config.mode == "single":
            summaries = _run_single_file_mode(conn=connection, config=config, data_source_id=data_source_id)
        else:
            assert resolved_paths is not None
            summaries = load_full_cycle(
                conn=connection,
                config=config,
                data_source_id=data_source_id,
                resolved_paths=resolved_paths,
            )

        if config.mode == "full":
            finalize_full_cycle_metadata(connection, data_source_id, summaries)
    except Exception as error:
        print(f"Bulk ingest failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    print_summary(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
