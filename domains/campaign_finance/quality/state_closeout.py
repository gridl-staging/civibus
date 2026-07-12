"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/quality/state_closeout.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import psycopg

from domains.campaign_finance.ingest.bulk_loader import sync_data_source_metadata
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import (
    LoadResult as COLoadResult,
    ensure_co_data_source,
    load_co_contributions,
    load_co_expenditures,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.load import (
    LoadResult as GALoadResult,
    ensure_ga_data_source,
    load_ga_contributions,
    load_ga_expenditures,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    parse_contributions as ga_parse_contributions,
    parse_expenditures as ga_parse_expenditures,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult as NCLoadResult,
    ensure_nc_data_source,
    load_nc_transactions,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    parse_committee_docs as nc_parse_committee_docs,
)
from domains.campaign_finance.quality import cli as quality_cli
from domains.campaign_finance.quality.closeout_evidence_base import (
    write_evidence_artifact,
)
from domains.campaign_finance.quality.reconciliation import (
    derive_pull_status_from_counts,
    fetch_data_source_snapshot,
)
from domains.campaign_finance.quality.state_closeout_models import (
    CoCloseoutSection,
    GaCloseoutSection,
    LoadResultSnapshot,
    NcCloseoutSection,
    NcCommitteeDocValidation,
    StateCloseoutEvidence,
)

_CO_JURISDICTION = "state/CO"
_GA_JURISDICTION = "state/GA"
_NC_JURISDICTION = "state/NC"


def _sync_pull_status(
    conn: psycopg.Connection,
    data_source_id: UUID,
    load_result: COLoadResult | GALoadResult | NCLoadResult,
) -> None:
    """Derive pull status from load counts and sync to data-source metadata."""
    pull_status = derive_pull_status_from_counts(
        load_result.inserted,
        load_result.skipped,
        load_result.errors,
    )
    sync_data_source_metadata(conn, data_source_id, pull_status=pull_status)


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Configuration for a single state closeout run."""

    jurisdiction: str
    data_type: str
    source_file: Path
    ga_candidate: str | None = None
    ga_date_start: str | None = None
    ga_date_end: str | None = None
    nc_acquisition_timestamp: str | None = None
    nc_committee_doc_path: Path | None = None
    tracer_summary_notes: str | None = None
    portal_summary_notes: str | None = None


@dataclass(slots=True)
class _COLoadOutput:
    """Internal wrapper for CO load + parser results."""

    result: COLoadResult
    parser_skipped: int


def _count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV file (excluding header)."""
    count = 0
    with path.open("rb") as f:
        for _ in f:
            count += 1
    return max(count - 1, 0)


def _compute_file_identity(path: Path) -> tuple[str, int]:
    """Return (sha256_hex, byte_size) for a file."""
    sha256 = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
            byte_size += len(chunk)
    return sha256.hexdigest(), byte_size


def _run_co_load(
    conn: psycopg.Connection,
    config: RunConfig,
    data_source_id: UUID,
) -> _COLoadOutput:
    """Run CO parser + loader, returning combined output.

    CO's load functions accept file_path and create their own parser internally,
    so we iterate a separate parser instance first to capture .skipped, then call
    the loader which re-parses. This is correct because parsing is deterministic.
    """
    from collections import deque

    from domains.campaign_finance.jurisdictions.states.CO.scraper.parse import (
        parse_contributions,
        parse_expenditures,
    )

    if config.data_type == "contributions":
        parser = parse_contributions(config.source_file)
        deque(parser, maxlen=0)
        result = load_co_contributions(
            conn,
            config.source_file,
            data_source_id=data_source_id,
        )
    elif config.data_type == "expenditures":
        parser = parse_expenditures(config.source_file)
        deque(parser, maxlen=0)
        result = load_co_expenditures(
            conn,
            config.source_file,
            data_source_id=data_source_id,
        )
    else:
        raise ValueError(f"Unsupported CO data_type: {config.data_type}")
    return _COLoadOutput(result=result, parser_skipped=parser.skipped)


def _run_ga_load(
    conn: psycopg.Connection,
    config: RunConfig,
) -> GALoadResult:
    """Run GA parser + loader."""
    if config.data_type == "contributions":
        rows = ga_parse_contributions(config.source_file)
        return load_ga_contributions(conn, rows)
    elif config.data_type == "expenditures":
        rows = ga_parse_expenditures(config.source_file)
        return load_ga_expenditures(conn, rows)
    else:
        raise ValueError(f"Unsupported GA data_type: {config.data_type}")


def _discover_and_run(
    conn: psycopg.Connection,
    jurisdiction: str,
    check_filter: str | None,
) -> quality_cli.QualityReport:
    """Thin wrapper over quality CLI discovery for testability."""
    return quality_cli._discover_and_run(conn, jurisdiction, check_filter)


def _build_co_evidence(
    config: RunConfig,
    load_output: _COLoadOutput,
    raw_csv_row_count: int,
) -> CoCloseoutSection:
    r = load_output.result
    return CoCloseoutSection(
        source_file=str(config.source_file),
        raw_csv_row_count=raw_csv_row_count,
        parser_skipped=load_output.parser_skipped,
        load_result=LoadResultSnapshot(
            inserted=r.inserted,
            skipped=r.skipped,
            quarantined=r.quarantined,
            superseded=r.superseded,
            errors=r.errors,
            elapsed_seconds=r.elapsed_seconds,
        ),
        tracer_summary_notes=config.tracer_summary_notes,
    )


def _build_ga_evidence(
    config: RunConfig,
    load_result: GALoadResult,
    file_sha256: str,
    file_byte_size: int,
) -> GaCloseoutSection:
    return GaCloseoutSection(
        source_file=str(config.source_file),
        file_sha256=file_sha256,
        file_byte_size=file_byte_size,
        query_candidate=config.ga_candidate or "",
        query_date_start=config.ga_date_start or "",
        query_date_end=config.ga_date_end or "",
        query_data_type=config.data_type,
        load_result=LoadResultSnapshot(
            inserted=load_result.inserted,
            skipped=load_result.skipped,
            errors=load_result.errors,
            elapsed_seconds=load_result.elapsed_seconds,
        ),
        portal_summary_notes=config.portal_summary_notes,
    )


def _validate_nc_committee_doc(path: Path) -> NcCommitteeDocValidation:
    """Parse NC committee doc CSV for validation-only stats."""
    file_sha256, _ = _compute_file_identity(path)
    parser = nc_parse_committee_docs(path)
    total_rows = sum(1 for _ in parser)
    return NcCommitteeDocValidation(
        source_file=str(path),
        file_sha256=file_sha256,
        total_rows=total_rows,
        parse_skipped=parser.skipped,
    )


def _build_nc_evidence(
    config: RunConfig,
    load_result: NCLoadResult,
    file_sha256: str,
    file_byte_size: int,
    committee_doc: NcCommitteeDocValidation | None,
) -> NcCloseoutSection:
    return NcCloseoutSection(
        transaction_source_file=str(config.source_file),
        transaction_file_sha256=file_sha256,
        transaction_file_byte_size=file_byte_size,
        acquisition_timestamp=config.nc_acquisition_timestamp or "",
        load_result=LoadResultSnapshot(
            inserted=load_result.inserted,
            skipped=load_result.skipped,
            quarantined=load_result.quarantined,
            superseded=load_result.superseded,
            errors=load_result.errors,
            elapsed_seconds=load_result.elapsed_seconds,
        ),
        committee_doc_validation=committee_doc,
    )


def run_state_closeout(
    conn: psycopg.Connection,
    config: RunConfig,
) -> StateCloseoutEvidence:
    """Orchestrate a single state closeout run."""
    co_evidence: CoCloseoutSection | None = None
    ga_evidence: GaCloseoutSection | None = None
    nc_evidence: NcCloseoutSection | None = None
    known_limitations: list[dict[str, object]] = []

    if config.jurisdiction == _CO_JURISDICTION:
        with conn.transaction():
            data_source_id = ensure_co_data_source(conn, config.data_type)
        raw_csv_row_count = _count_csv_rows(config.source_file)
        load_output = _run_co_load(conn, config, data_source_id)
        _sync_pull_status(conn, data_source_id, load_output.result)
        co_evidence = _build_co_evidence(config, load_output, raw_csv_row_count)

    elif config.jurisdiction == _GA_JURISDICTION:
        with conn.transaction():
            data_source_id = ensure_ga_data_source(conn, config.data_type)
        file_sha256, file_byte_size = _compute_file_identity(config.source_file)
        load_result = _run_ga_load(conn, config)
        _sync_pull_status(conn, data_source_id, load_result)
        ga_evidence = _build_ga_evidence(config, load_result, file_sha256, file_byte_size)

    elif config.jurisdiction == _NC_JURISDICTION:
        with conn.transaction():
            data_source_id = ensure_nc_data_source(conn)
        file_sha256, file_byte_size = _compute_file_identity(config.source_file)
        nc_load_result = load_nc_transactions(
            conn,
            config.source_file,
            data_source_id=data_source_id,
        )
        _sync_pull_status(conn, data_source_id, nc_load_result)
        committee_doc = None
        if config.nc_committee_doc_path is not None:
            committee_doc = _validate_nc_committee_doc(config.nc_committee_doc_path)
        else:
            known_limitations.append(
                {
                    "jurisdiction": _NC_JURISDICTION,
                    "name": "nc_committee_doc_not_provided",
                    "status": "warn",
                    "message": "Committee-document export was not provided for cross-reference validation.",
                    "details": {"category": "gap-marker"},
                }
            )
        nc_evidence = _build_nc_evidence(
            config,
            nc_load_result,
            file_sha256,
            file_byte_size,
            committee_doc,
        )

    else:
        raise ValueError(f"Unsupported jurisdiction: {config.jurisdiction}")

    snapshot = fetch_data_source_snapshot(conn, data_source_id)
    quality_report = _discover_and_run(conn, config.jurisdiction, None)

    return StateCloseoutEvidence(
        jurisdiction=config.jurisdiction,
        data_type=config.data_type,
        data_source_id=str(data_source_id),
        data_source_snapshot={
            "record_count": snapshot.record_count,
            "last_pull_status": snapshot.last_pull_status,
            "last_pull_at": snapshot.last_pull_at,
        },
        quality_report=quality_report,
        known_limitations=known_limitations,
        co_evidence=co_evidence,
        ga_evidence=ga_evidence,
        nc_evidence=nc_evidence,
    )


__all__ = ["RunConfig", "run_state_closeout", "write_evidence_artifact"]
