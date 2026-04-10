"""LA city campaign-finance filing-aware loader (two-pass: provenance then relational)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import resolve_organization_by_canonical_name, try_insert_source_record
from core.types.python.models import (
    DataSource,
    Organization,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import _load_data_source_for_data_type
from .parse import parse_transactions

LOGGER = logging.getLogger(__name__)

_LA_DOMAIN = "campaign_finance"
_LA_JURISDICTION = "municipality/LA"
_LA_SOURCE_FORMAT = "csv"
_LA_DATA_TYPE = "transactions"


@dataclass(slots=True)
class _LALoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _LAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_la_data_source(conn: psycopg.Connection) -> UUID:
    """Create or retrieve the LA Ethics data source row."""
    ds_block = _load_data_source_for_data_type(_LA_DATA_TYPE)
    data_source = DataSource(
        domain=_LA_DOMAIN,
        jurisdiction=_LA_JURISDICTION,
        name=ds_block.name,
        source_url=ds_block.url,
        source_format=_LA_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def load_la_transactions_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    """Load LA transactions CSV with filing-aware two-pass approach."""
    row_limit = validated_limit(limit)
    data_source_id = ensure_la_data_source(conn)
    started_at = time.monotonic()
    counts = _LALoadCounts()
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    # Pass 1: provenance — insert source records for every parsed row
    source_record_ids: dict[str, UUID] = {}

    for row in _iter_la_rows(file_path, limit=row_limit, year_from=year_from):
        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                sr = _build_la_source_record(data_source_id, row)
                sr_id = try_insert_source_record(conn, sr)
                if sr_id is None:
                    counts.skipped += 1
                else:
                    source_record_ids[sr.record_hash] = sr_id
                    counts.inserted += 1
        except Exception:  # noqa: BLE001
            counts.errors += 1
            LOGGER.exception("Failed inserting LA source record")

    commit_managed_transaction(conn, manages_outer)

    # Pass 2: relational — upsert filings + transactions for rows with provenance
    filing_lookup: dict[str, _LAFilingLookupEntry] = {}

    for row in _iter_la_rows(file_path, limit=row_limit, year_from=year_from):
        raw_fields = _to_json_safe(row)
        record_hash = compute_record_hash(raw_fields)
        sr_id = source_record_ids.get(record_hash)
        if sr_id is None:
            continue

        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                _upsert_la_filing_and_transaction(
                    conn,
                    row,
                    sr_id,
                    record_hash,
                    filing_lookup=filing_lookup,
                )
        except Exception:  # noqa: BLE001
            counts.errors += 1
            LOGGER.exception("Failed linking LA transaction to filing")

    commit_managed_transaction(conn, manages_outer)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=0,
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_la_rows(
    file_path: str | Path,
    *,
    limit: int | None,
    year_from: int | None,
):
    """Iterate parsed LA transaction rows, respecting limit."""
    parser = parse_transactions(Path(file_path), year_from=year_from)
    for idx, row in enumerate(parser, start=1):
        if limit is not None and idx > limit:
            break
        yield row


def _to_json_safe(row: dict[str, object]) -> dict[str, object]:
    """Convert Decimal/date values to JSON-compatible strings for hashing."""
    result: dict[str, object] = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            result[k] = str(v)
        elif isinstance(v, date):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _build_la_source_record(
    data_source_id: UUID,
    row: dict[str, object],
) -> SourceRecord:
    """Build a SourceRecord from a parsed LA row."""
    raw_fields = _to_json_safe(row)
    record_hash = compute_record_hash(raw_fields)
    ds_block = _load_data_source_for_data_type(_LA_DATA_TYPE)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        source_url=ds_block.url,
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _resolve_la_native_committee_id(row: dict[str, object]) -> str:
    """Prefer cmt_id (FPPC ID) for committee identity; fall back to namespaced cmt_nm."""
    cmt_id = normalize_optional_text(row.get("cmt_id"))
    if cmt_id is not None:
        return cmt_id
    cmt_nm = normalize_optional_text(row.get("cmt_nm"))
    if cmt_nm is not None:
        return f"la-{cmt_nm}"
    raise ValueError("LA row has neither cmt_id nor cmt_nm")


def _build_la_filing_fec_id(row: dict[str, object]) -> str:
    """Deterministic filing FEC ID: LA-{native_committee_id}-{form}-{per_beg_date}-{per_end_date}.

    LA has no filing_id_number, so we construct a composite key from
    committee, form type, and period dates.
    """
    native_id = _resolve_la_native_committee_id(row)
    form = normalize_optional_text(row.get("form")) or "unknown"
    per_beg = row.get("per_beg_date")
    per_end = row.get("per_end_date")
    beg_str = per_beg.isoformat() if isinstance(per_beg, date) else "unknown"
    end_str = per_end.isoformat() if isinstance(per_end, date) else "unknown"
    return f"LA-{native_id}-{form}-{beg_str}-{end_str}"


def _build_la_filing(
    row: dict[str, object],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    """Build a Filing model from a parsed LA row."""
    per_beg_date = row.get("per_beg_date")
    per_end_date = row.get("per_end_date")
    cmt_nm = normalize_optional_text(row.get("cmt_nm"))
    form = normalize_optional_text(row.get("form"))
    return Filing(
        filing_fec_id=_build_la_filing_fec_id(row),
        committee_id=committee_id,
        report_type=form or _LA_DATA_TYPE,
        amendment_indicator="N",
        filing_name=cmt_nm,
        coverage_start_date=per_beg_date if isinstance(per_beg_date, date) else None,
        coverage_end_date=per_end_date if isinstance(per_end_date, date) else None,
        receipt_date=per_beg_date if isinstance(per_beg_date, date) else None,
        accepted_date=per_beg_date if isinstance(per_beg_date, date) else None,
        source_record_id=source_record_id,
    )


def _build_la_transaction(
    row: dict[str, object],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    record_hash: str,
) -> Transaction:
    """Build a Transaction model from a parsed LA row."""
    contributor_name = normalize_optional_text(row.get("con_name"))

    con_type = normalize_optional_text(row.get("con_type"))

    amount = row.get("con_amount")
    if not isinstance(amount, Decimal):
        amount = Decimal("0")

    transaction_date = row.get("con_date")
    if not isinstance(transaction_date, date):
        transaction_date = None

    return Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type=con_type or "contribution",
        transaction_identifier=record_hash,
        transaction_date=transaction_date,
        amount=amount,
        contributor_name_raw=contributor_name,
        contributor_employer=normalize_optional_text(row.get("con_empr")),
        contributor_city=normalize_optional_text(row.get("con_city_nm")),
        contributor_state=normalize_optional_text(row.get("con_state_nm")),
        contributor_zip=normalize_optional_text(row.get("con_zip_cd")),
        amendment_indicator="N",
        source_record_id=source_record_id,
    )


def _upsert_la_filing_and_transaction(
    conn: psycopg.Connection,
    row: dict[str, object],
    source_record_id: UUID,
    record_hash: str,
    *,
    filing_lookup: dict[str, _LAFilingLookupEntry],
) -> None:
    """Resolve committee, upsert filing, upsert transaction for one row."""
    # Resolve organization and committee
    native_committee_id = _resolve_la_native_committee_id(row)
    cmt_nm = normalize_optional_text(row.get("cmt_nm")) or "Unknown LA Filer"
    org = Organization(canonical_name=cmt_nm)
    organization_id = resolve_organization_by_canonical_name(conn, org)

    committee_id = ensure_state_committee(
        conn,
        state="CA",
        native_committee_id=native_committee_id,
        organization_id=organization_id,
    )

    # Upsert filing (cache by filing_fec_id to avoid redundant writes)
    filing_fec_id = _build_la_filing_fec_id(row)
    existing_entry = filing_lookup.get(filing_fec_id)
    if existing_entry is not None:
        filing_committee_id = existing_entry.committee_id
        filing_sr_id = existing_entry.source_record_id
    else:
        filing_committee_id = committee_id
        filing_sr_id = source_record_id

    filing = _build_la_filing(
        row,
        committee_id=filing_committee_id,
        source_record_id=filing_sr_id,
    )
    filing_id = upsert_filing(conn, filing)

    # Upsert transaction
    txn = _build_la_transaction(
        row,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
        record_hash=record_hash,
    )
    upsert_transaction(conn, txn)

    # Cache filing only after both filing and transaction succeed — if the
    # savepoint rolls back, stale cache entries would cause FK violations
    # on subsequent rows referencing a rolled-back committee_id.
    filing_lookup[filing_fec_id] = _LAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=filing_committee_id,
        source_record_id=filing_sr_id,
    )
