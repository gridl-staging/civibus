"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_01_backend_api_completeness/civibus_dev/domains/campaign_finance/quality/fec_closeout.py.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg

from core.db import get_connection
from domains.campaign_finance.ingest import bulk_cli
from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source
from domains.campaign_finance.quality import cli as quality_cli
from domains.campaign_finance.quality.closeout_evidence_base import (
    write_evidence_artifact,
)
from domains.campaign_finance.quality.fec_closeout_models import (
    FecCloseoutEvidence,
    FecIngestMetadata,
    FecIngestStepSummary,
)
from domains.campaign_finance.quality.reconciliation import (
    count_source_records,
    fetch_data_source_snapshot,
)

_FEDERAL_FEC_JURISDICTION = "federal/fec"
_ARTIFACT_FILENAME = "closeout_evidence.json"
_SCOPED_TABLE_ALLOWLIST = frozenset({"cf.committee", "cf.candidate", "cf.candidate_committee_link"})
_KNOWN_LIMITATION_ANOMALIES: tuple[dict[str, object], ...] = (
    {
        "jurisdiction": _FEDERAL_FEC_JURISDICTION,
        "name": "known_limitation_no_cf_transaction_population",
        "status": "warn",
        "message": "Bulk ingest does not populate cf.transaction until filing ingest is implemented.",
        "details": {
            "category": "accepted-limitation",
            "source": "docs/research/stage2-fec-known-limitations.md#5",
        },
    },
)


@dataclass(frozen=True, slots=True)
class FecCloseoutConfig:
    cycle: int
    directory: Path
    artifact_path: Path
    batch_size: int
    transaction_limit: int | None
    graph_enabled: bool


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run fixture/real federal FEC closeout and write structured evidence JSON"
    )
    parser.add_argument("--cycle", required=True, type=int, help="Election cycle year (example: 2024)")
    parser.add_argument(
        "--directory", required=True, type=Path, help="Directory containing cm/cn/ccl/itcont/itpas2 files"
    )
    parser.add_argument("--artifact-path", type=Path, help="Output evidence JSON path")
    parser.add_argument("--batch-size", type=int, default=1000, help="Commit interval (default: 1000)")
    parser.add_argument("--limit", type=int, help="Transaction row cap applied to itcont/itpas2 in full-cycle mode")
    parser.add_argument("--graph", action="store_true", help="Enable graph loading for itcont/itpas2")
    return parser


def _default_artifact_path(cycle: int) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "docs" / "research" / "artifacts" / "federal_fec" / str(cycle) / _ARTIFACT_FILENAME


def _is_readable_directory(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.R_OK)


def _build_cli_config(args: argparse.Namespace) -> FecCloseoutConfig:
    if args.batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("limit must be greater than zero")
    if not _is_readable_directory(args.directory):
        raise ValueError(f"closeout requires a readable directory path: {args.directory}")

    artifact_path = args.artifact_path if args.artifact_path is not None else _default_artifact_path(args.cycle)
    return FecCloseoutConfig(
        cycle=args.cycle,
        directory=args.directory,
        artifact_path=artifact_path,
        batch_size=args.batch_size,
        transaction_limit=args.limit,
        graph_enabled=args.graph,
    )


def _fetch_data_source_metadata_snapshot(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> FecIngestMetadata:
    snapshot = fetch_data_source_snapshot(conn, data_source_id)
    if snapshot.record_count is None or snapshot.last_pull_status is None:
        raise RuntimeError(f"data_source not found for id={data_source_id}")
    return FecIngestMetadata(
        record_count=snapshot.record_count,
        last_pull_status=snapshot.last_pull_status,
        last_pull_at=snapshot.last_pull_at,
    )


def _count_rows_for_scoped_table(
    conn: psycopg.Connection,
    data_source_id: UUID,
    table_name: str,
) -> int:
    if table_name not in _SCOPED_TABLE_ALLOWLIST:
        raise ValueError(f"Table name not in scoped-table allowlist: {table_name!r}")
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name} scoped_row
            JOIN core.source_record source_record
              ON source_record.id = scoped_row.source_record_id
            WHERE source_record.data_source_id = %s
              AND source_record.superseded_by IS NULL
            """,  # noqa: S608
            (data_source_id,),
        )
        return cursor.fetchone()[0]


def _collect_scoped_table_counts(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> dict[str, int]:
    return {
        "cf.committee": _count_rows_for_scoped_table(conn, data_source_id, "cf.committee"),
        "cf.candidate": _count_rows_for_scoped_table(conn, data_source_id, "cf.candidate"),
        "cf.candidate_committee_link": _count_rows_for_scoped_table(
            conn, data_source_id, "cf.candidate_committee_link"
        ),
        "core.source_record_active": count_source_records(conn, data_source_id),
    }


def _build_ingest_config(config: FecCloseoutConfig) -> bulk_cli.CliConfig:
    return bulk_cli.CliConfig(
        mode="full",
        cycle=config.cycle,
        file_type=None,
        path=None,
        directory=config.directory,
        batch_size=config.batch_size,
        limit=config.transaction_limit,
        graph_enabled=config.graph_enabled,
    )


def _known_ingest_limitation_anomalies() -> list[dict[str, object]]:
    return [deepcopy(anomaly) for anomaly in _KNOWN_LIMITATION_ANOMALIES]


def run_fec_closeout(conn: psycopg.Connection, config: FecCloseoutConfig) -> FecCloseoutEvidence:
    resolved_paths = bulk_cli.resolve_full_cycle_directory(config.directory)
    with conn.transaction():
        data_source_id = ensure_fec_bulk_data_source(conn)

    ingest_config = _build_ingest_config(config)
    step_summaries = bulk_cli.load_full_cycle(
        conn=conn,
        config=ingest_config,
        data_source_id=data_source_id,
        resolved_paths=resolved_paths,
    )
    bulk_cli.finalize_full_cycle_metadata(conn, data_source_id, step_summaries)
    metadata = _fetch_data_source_metadata_snapshot(conn, data_source_id)
    if not metadata.last_pull_status:
        raise RuntimeError("closeout requires persisted data_source.last_pull_status after metadata finalization")
    scoped_counts = _collect_scoped_table_counts(conn, data_source_id)
    quality_report = quality_cli._discover_and_run(conn, _FEDERAL_FEC_JURISDICTION, None)
    baseline_urls = bulk_cli.fec_baseline_urls(config.cycle)

    ingest_steps = [
        FecIngestStepSummary(
            file_type=step.file_type,
            source_path=str(step.source_path),
            baseline_url=baseline_urls[step.file_type],
            inserted=step.result.inserted,
            skipped=step.result.skipped,
            errors=step.result.errors,
            elapsed_seconds=step.elapsed_seconds,
        )
        for step in step_summaries
    ]
    return FecCloseoutEvidence(
        cycle=config.cycle,
        jurisdiction=_FEDERAL_FEC_JURISDICTION,
        data_source_id=str(data_source_id),
        transaction_limit=config.transaction_limit,
        baseline_urls=baseline_urls,
        scoped_table_counts=scoped_counts,
        ingest_steps=ingest_steps,
        ingest_metadata=metadata,
        quality_report=quality_report,
        known_limitations=_known_ingest_limitation_anomalies(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    try:
        args = parser.parse_args(argv)
        config = _build_cli_config(args)
    except SystemExit as error:
        return int(error.code)
    except ValueError as error:
        print(f"CLI validation failed: {error}", file=sys.stderr)
        return 2

    connection: psycopg.Connection | None = None
    try:
        connection = get_connection()
        evidence = run_fec_closeout(connection, config)
        write_evidence_artifact(evidence, config.artifact_path)
    except Exception as error:  # noqa: BLE001
        print(f"FEC closeout failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    print(config.artifact_path)
    if evidence.quality_report.status in ("fail", "error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
