
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

_SF_DOMAIN = "campaign_finance"
_SF_JURISDICTION = "municipality/SF"
_SF_SOURCE_FORMAT = "csv"
_SF_DATA_TYPE = "transactions"


@dataclass(slots=True)
class _SFLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _SFFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_sf_data_source(conn: psycopg.Connection) -> UUID:
    """Create or retrieve the SF Ethics data source row."""
    ds_block = _load_data_source_for_data_type(_SF_DATA_TYPE)
    data_source = DataSource(
        domain=_SF_DOMAIN,
        jurisdiction=_SF_JURISDICTION,
        name=ds_block.name,
        source_url=ds_block.url,
        source_format=_SF_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def load_sf_transactions_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    """Load SF transactions CSV with filing-aware two-pass approach."""
    row_limit = validated_limit(limit)
    data_source_id = ensure_sf_data_source(conn)
    started_at = time.monotonic()
    counts = _SFLoadCounts()
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    # Pass 1: provenance — insert source records for every parsed row
    source_record_ids: dict[str, UUID] = {}

    for row in _iter_sf_rows(file_path, limit=row_limit, year_from=year_from):
        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                sr = _build_sf_source_record(data_source_id, row)
                sr_id = try_insert_source_record(conn, sr)
                if sr_id is None:
                    counts.skipped += 1
                else:
                    source_record_ids[sr.record_hash] = sr_id
                    counts.inserted += 1
        except Exception:  # noqa: BLE001
            counts.errors += 1
            LOGGER.exception("Failed inserting SF source record")

    commit_managed_transaction(conn, manages_outer)

    # Pass 2: relational — upsert filings + transactions for rows with provenance
    filing_lookup: dict[str, _SFFilingLookupEntry] = {}

    for row in _iter_sf_rows(file_path, limit=row_limit, year_from=year_from):
        raw_fields = _to_json_safe(row)
        record_hash = compute_record_hash(raw_fields)
        sr_id = source_record_ids.get(record_hash)
        if sr_id is None:
            continue

        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                _upsert_sf_filing_and_transaction(
                    conn,
                    row,
                    sr_id,
                    filing_lookup=filing_lookup,
                )
        except Exception:  # noqa: BLE001
            counts.errors += 1
            LOGGER.exception("Failed linking SF transaction to filing")

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


def _iter_sf_rows(
    file_path: str | Path,
    *,
    limit: int | None,
    year_from: int | None,
):
    """Iterate parsed SF transaction rows, respecting limit."""
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


def _build_sf_source_record(
    data_source_id: UUID,
    row: dict[str, object],
) -> SourceRecord:
    """Build a SourceRecord from a parsed SF row."""
    raw_fields = _to_json_safe(row)
    record_hash = compute_record_hash(raw_fields)
    ds_block = _load_data_source_for_data_type(_SF_DATA_TYPE)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        source_url=ds_block.url,
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _resolve_sf_native_committee_id(row: dict[str, object]) -> str:
    """Prefer fppc_id for committee identity; fall back to namespaced filer name."""
    fppc_id = normalize_optional_text(row.get("fppc_id"))
    if fppc_id is not None:
        return fppc_id
    filer_name = normalize_optional_text(row.get("filer_name"))
    if filer_name is not None:
        return f"sf-{filer_name}"
    raise ValueError("SF row has neither fppc_id nor filer_name")


def _build_sf_filing_fec_id(row: dict[str, object]) -> str:
    """Deterministic filing FEC ID: SF-{native_committee_id}-{filing_id_number}."""
    filing_id_number = row.get("filing_id_number")
    if filing_id_number is None:
        raise ValueError("SF row is missing filing_id_number")
    native_id = _resolve_sf_native_committee_id(row)
    return f"SF-{native_id}-{filing_id_number}"


def _build_sf_filing(
    row: dict[str, object],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    filing_date = row.get("filing_date")
    start_date = row.get("start_date")
    end_date = row.get("end_date")
    filer_name = normalize_optional_text(row.get("filer_name"))
    form_type = normalize_optional_text(row.get("form_type"))
    return Filing(
        filing_fec_id=_build_sf_filing_fec_id(row),
        committee_id=committee_id,
        report_type=form_type or _SF_DATA_TYPE,
        amendment_indicator="N",
        filing_name=filer_name,
        coverage_start_date=start_date if isinstance(start_date, date) else None,
        coverage_end_date=end_date if isinstance(end_date, date) else None,
        receipt_date=filing_date if isinstance(filing_date, date) else None,
        accepted_date=filing_date if isinstance(filing_date, date) else None,
        source_record_id=source_record_id,
    )


def _build_sf_transaction(
    row: dict[str, object],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
) -> Transaction:
    first = normalize_optional_text(row.get("transaction_first_name"))
    last = normalize_optional_text(row.get("transaction_last_name"))
    name_parts = [p for p in (first, last) if p is not None]
    contributor_name_raw = " ".join(name_parts) if name_parts else None

    transaction_id = normalize_optional_text(row.get("transaction_id"))
    transaction_code = normalize_optional_text(row.get("transaction_code"))

    amount = row.get("transaction_amount_1")
    if not isinstance(amount, Decimal):
        amount = row.get("calculated_amount")
    if not isinstance(amount, Decimal):
        amount = Decimal("0")

    transaction_date = row.get("transaction_date")
    if not isinstance(transaction_date, date):
        transaction_date = row.get("calculated_date")
    if not isinstance(transaction_date, date):
        transaction_date = None

    return Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type=transaction_code or "contribution",
        transaction_identifier=transaction_id,
        transaction_date=transaction_date,
        amount=amount,
        contributor_name_raw=contributor_name_raw,
        contributor_employer=normalize_optional_text(row.get("transaction_employer")),
        contributor_city=normalize_optional_text(row.get("transaction_city")),
        contributor_state=normalize_optional_text(row.get("transaction_state")),
        contributor_zip=normalize_optional_text(row.get("transaction_zip")),
        amendment_indicator="N",
        source_record_id=source_record_id,
    )


def _upsert_sf_filing_and_transaction(
    conn: psycopg.Connection,
    row: dict[str, object],
    source_record_id: UUID,
    *,
    filing_lookup: dict[str, _SFFilingLookupEntry],
) -> None:
    """Resolve committee, upsert filing, upsert transaction for one row."""
    # Resolve organization and committee
    native_committee_id = _resolve_sf_native_committee_id(row)
    filer_name = normalize_optional_text(row.get("filer_name")) or "Unknown SF Filer"
    org = Organization(canonical_name=filer_name)
    organization_id = resolve_organization_by_canonical_name(conn, org)

    committee_id = ensure_state_committee(
        conn,
        state="CA",
        native_committee_id=native_committee_id,
        organization_id=organization_id,
    )

    # Upsert filing (cache by filing_fec_id to avoid redundant writes)
    filing_fec_id = _build_sf_filing_fec_id(row)
    existing_entry = filing_lookup.get(filing_fec_id)
    if existing_entry is not None:
        filing_committee_id = existing_entry.committee_id
        filing_sr_id = existing_entry.source_record_id
    else:
        filing_committee_id = committee_id
        filing_sr_id = source_record_id

    filing = _build_sf_filing(
        row,
        committee_id=filing_committee_id,
        source_record_id=filing_sr_id,
    )
    filing_id = upsert_filing(conn, filing)
    filing_lookup[filing_fec_id] = _SFFilingLookupEntry(
        filing_id=filing_id,
        committee_id=filing_committee_id,
        source_record_id=filing_sr_id,
    )

    # Upsert transaction
    txn = _build_sf_transaction(
        row,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
    )
    upsert_transaction(conn, txn)
