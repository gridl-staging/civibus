"""Virginia campaign finance DB loader.

Two-phase loading following the WI pattern:
  Phase 1: Source records + entity resolution (person/org/address)
  Phase 2: Filing upserts + transaction upserts (relational layer)

Uses try_row_without_savepoint to avoid exhausting max_locks_per_transaction
on large datasets. Commits every 1,000 rows.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

from core.db import (
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
    try_row_without_savepoint,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import (
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
)
from .extract import (
    VAContributionExtraction,
    VAExpenditureExtraction,
    extract_va_contribution,
    extract_va_expenditure,
)
from .parse import parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_VA_DOMAIN = "campaign_finance"
_VA_JURISDICTION = "state/VA"
_VA_SOURCE_FORMAT = "csv"

# VA date formats vary: MM/DD/YYYY (common) and YYYY-MM-DD HH:MM:SS.nnnnnnnnn
_VA_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d")


@dataclass(slots=True)
class _VALoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _VAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


def ensure_va_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    """Upsert the VA data source and return its UUID."""
    normalized = data_type.strip().lower()
    source_name = _load_data_source_name_for_data_type(normalized)
    source_url = _load_data_source_url_for_data_type(normalized)

    data_source = DataSource(
        domain=_VA_DOMAIN,
        jurisdiction=_VA_JURISDICTION,
        name=source_name,
        source_url=source_url,
        source_format=_VA_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


# ---------------------------------------------------------------------------
# Source record helpers
# ---------------------------------------------------------------------------


def _va_source_record_key(row: Mapping[str, str | None], data_type: str) -> str:
    """Build a deterministic key for deduplication.

    Contributions use ScheduleAId; expenditures use ScheduleDId.
    Falls back to full-row hash if the ID column is missing.
    """
    id_column = "ScheduleAId" if data_type == "contributions" else "ScheduleDId"
    native_id = normalize_optional_text(row.get(id_column))
    if native_id is not None:
        return f"va-{data_type}-{native_id}"
    return compute_record_hash(dict(row))


def _build_va_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    record_hash = compute_record_hash(raw_fields)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_va_source_record_key(row, data_type),
        source_url=_load_data_source_url_for_data_type(data_type),
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


# ---------------------------------------------------------------------------
# Date and amount parsing
# ---------------------------------------------------------------------------


def _parse_va_date(raw_value: str | None) -> date | None:
    """Parse a VA date string, trying multiple known formats."""
    text = normalize_optional_text(raw_value)
    if text is None:
        return None

    # Strip trailing nanosecond portion if longer than microseconds
    # e.g. "2025-01-15 00:00:00.000000000" → "2025-01-15 00:00:00.000000"
    if "." in text and len(text.split(".")[-1]) > 6:
        text = text[: text.index(".") + 7]

    for fmt in _VA_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    LOGGER.warning("VA date parse failed: %r", raw_value)
    return None


def _parse_va_amount(raw_value: str | None) -> Decimal:
    """Parse a VA amount string to Decimal. Returns Decimal(0) on failure."""
    text = normalize_optional_text(raw_value)
    if text is None:
        return Decimal(0)
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ArithmeticError):
        LOGGER.warning("VA amount parse failed: %r", raw_value)
        return Decimal(0)


# ---------------------------------------------------------------------------
# Entity loading (Phase 1)
# ---------------------------------------------------------------------------


def _resolve_va_committee_organization_id(conn: psycopg.Connection, committee_name: str) -> UUID:
    """Resolve or create the committee Organization by canonical name."""
    committee_org = Organization(canonical_name=committee_name)
    org_id = resolve_organization_by_canonical_name(conn, committee_org)
    if org_id is not None:
        return org_id
    from core.db import insert_organization

    return insert_organization(conn, committee_org)


def _load_va_contribution_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: VAContributionExtraction,
) -> None:
    """Load person/org/address entities from a VA contribution extraction."""
    address = extracted["address"]
    address_id: UUID | None = None
    if isinstance(address, Address):
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role="contributor_address",
            address_id=None,
        )

    donor_person = extracted["donor_person"]
    if donor_person is not None:
        person_id = resolve_person_by_name_and_zip(
            conn, donor_person, address if isinstance(address, Address) else None
        )
        if person_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="person",
                entity_id=person_id,
                source_record_id=source_record_id,
                extraction_role="contributor",
                address_id=address_id,
            )

    donor_org = extracted["donor_org"]
    if donor_org is not None:
        org_id = resolve_organization_by_canonical_name(conn, donor_org)
        if org_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="organization",
                entity_id=org_id,
                source_record_id=source_record_id,
                extraction_role="contributor",
                address_id=address_id,
            )


def _load_va_expenditure_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: VAExpenditureExtraction,
) -> None:
    """Load person/org/address entities from a VA expenditure extraction."""
    address = extracted["address"]
    address_id: UUID | None = None
    if isinstance(address, Address):
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role="payee_address",
            address_id=None,
        )

    payee_person = extracted["payee_person"]
    if payee_person is not None:
        person_id = resolve_person_by_name_and_zip(
            conn, payee_person, address if isinstance(address, Address) else None
        )
        if person_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="person",
                entity_id=person_id,
                source_record_id=source_record_id,
                extraction_role="payee",
                address_id=address_id,
            )

    payee_org = extracted["payee_org"]
    if payee_org is not None:
        org_id = resolve_organization_by_canonical_name(conn, payee_org)
        if org_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="organization",
                entity_id=org_id,
                source_record_id=source_record_id,
                extraction_role="payee",
                address_id=address_id,
            )


# ---------------------------------------------------------------------------
# Phase 1: Extract and load source records + entities
# ---------------------------------------------------------------------------


def _extract_and_load_va_contribution_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    """Phase 1 for a single contribution row: source record + entities."""
    source_record = _build_va_source_record(data_source_id, row, "contributions")
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_va_contribution(dict(row))
    _load_va_contribution_entities(conn, source_record_id=source_record_id, extracted=extracted)
    return True


def _extract_and_load_va_expenditure_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    """Phase 1 for a single expenditure row: source record + entities."""
    source_record = _build_va_source_record(data_source_id, row, "expenditures")
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_va_expenditure(dict(row))
    _load_va_expenditure_entities(conn, source_record_id=source_record_id, extracted=extracted)
    return True


def _load_va_phase1(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    """Phase 1: Insert source records and resolve entities for all rows."""
    started_at = time.monotonic()
    counts = _VALoadCounts()
    manages_outer = conn.info.transaction_status == TransactionStatus.IDLE

    row_loader = (
        _extract_and_load_va_contribution_row if data_type == "contributions" else _extract_and_load_va_expenditure_row
    )

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        inserted, _was_db_error = try_row_without_savepoint(
            conn,
            lambda r=row: row_loader(conn, r, data_source_id),
            manages_outer_transaction=manages_outer,
            label=f"VA {data_type} row",
        )

        if inserted is None:
            counts.errors += 1
        elif inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

        processed = counts.inserted + counts.skipped + counts.errors
        if processed % 1_000 == 0:
            commit_managed_transaction(conn, manages_outer)

    commit_managed_transaction(conn, manages_outer)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


# ---------------------------------------------------------------------------
# Phase 2: Filing + transaction upserts (relational layer)
# ---------------------------------------------------------------------------


def _build_va_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    """Build a synthetic filing FEC ID for a VA row.

    VA groups transactions by ReportId. The filing_fec_id is unique per
    (ReportId, data_type) combination.
    """
    report_id = normalize_optional_text(row.get("ReportId"))
    if report_id is None:
        raise ValueError("VA row missing ReportId for filing construction")
    return f"VA-{report_id}-{data_type}"


def _select_va_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    """Find the source_record_id for a row we already loaded in Phase 1."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def _resolve_va_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
) -> UUID:
    """Resolve the VA committee for a row using CommitteeContactId."""
    committee_contact_id = normalize_optional_text(row.get("CommitteeContactId"))
    if committee_contact_id is None:
        raise ValueError("VA row missing CommitteeContactId")

    committee_name = f"VA Committee {committee_contact_id}"
    committee_org_id = _resolve_va_committee_organization_id(conn, committee_name)

    return ensure_state_committee(
        conn,
        state="VA",
        native_committee_id=committee_contact_id,
        organization_id=committee_org_id,
    )


def _upsert_va_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_type: str,
    source_record_id: UUID,
    filing_lookup: dict[str, _VAFilingLookupEntry],
) -> _VAFilingLookupEntry:
    """Upsert a VA filing, caching by filing_fec_id to avoid redundant DB work."""
    filing_fec_id = _build_va_filing_fec_id(row, data_type)

    cached = filing_lookup.get(filing_fec_id)
    if cached is not None:
        return cached

    committee_id = _resolve_va_filing_committee_id(conn, row)
    transaction_date = _parse_va_date(row.get("TransactionDate"))

    filing = Filing(
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="N",
        filing_name=normalize_optional_text(row.get("ReportId")),
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _VAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _build_contributor_name(row: Mapping[str, str | None]) -> str | None:
    """Build a display name from VA name parts."""
    parts = [
        normalize_optional_text(row.get("FirstName")),
        normalize_optional_text(row.get("MiddleName")),
        normalize_optional_text(row.get("LastOrCompanyName")),
    ]
    name_parts = [p for p in parts if p]
    return " ".join(name_parts) if name_parts else None


def _upsert_va_contribution_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
) -> None:
    """Upsert a single VA contribution transaction."""
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=("contributor",),
        organization_roles=("contributor",),
    )

    extracted = extract_va_contribution(dict(row))
    address = extracted["address"]

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="contribution",
            transaction_identifier=normalize_optional_text(row.get("ScheduleAId")),
            transaction_date=_parse_va_date(row.get("TransactionDate")),
            amount=_parse_va_amount(row.get("Amount")),
            contributor_name_raw=_build_contributor_name(row),
            contributor_employer=normalize_optional_text(row.get("NameOfEmployer")),
            contributor_occupation=normalize_optional_text(row.get("OccupationOrTypeOfBusiness")),
            contributor_city=address.city if address else None,
            contributor_state=address.state if address else None,
            contributor_zip=address.zip5 if address else None,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=None,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
        ),
    )


def _upsert_va_expenditure_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
) -> None:
    """Upsert a single VA expenditure transaction."""
    payee_person_id, payee_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=("payee",),
        organization_roles=("payee",),
    )

    extracted = extract_va_expenditure(dict(row))
    address = extracted["address"]

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="expenditure",
            transaction_identifier=normalize_optional_text(row.get("ScheduleDId")),
            transaction_date=_parse_va_date(row.get("TransactionDate")),
            amount=_parse_va_amount(row.get("Amount")),
            contributor_name_raw=_build_contributor_name(row),
            contributor_employer=None,
            contributor_occupation=None,
            contributor_city=address.city if address else None,
            contributor_state=address.state if address else None,
            contributor_zip=address.zip5 if address else None,
            contributor_person_id=payee_person_id,
            contributor_organization_id=payee_organization_id,
            contributor_address_id=None,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
            memo_text=normalize_optional_text(row.get("ItemOrService")),
        ),
    )


def _load_va_phase2(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> int:
    """Phase 2: Upsert filings and transactions for rows loaded in Phase 1."""
    filing_lookup: dict[str, _VAFilingLookupEntry] = {}
    relational_errors = 0
    manages_outer = conn.info.transaction_status == TransactionStatus.IDLE

    txn_upserter = (
        _upsert_va_contribution_transaction if data_type == "contributions" else _upsert_va_expenditure_transaction
    )

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_key = _va_source_record_key(row, data_type)
        source_record_id = _select_va_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
        )
        if source_record_id is None:
            continue

        def _link_va_row(r=row, sr_id=source_record_id) -> bool:
            filing_entry = _upsert_va_filing(
                conn,
                r,
                data_type=data_type,
                source_record_id=sr_id,
                filing_lookup=filing_lookup,
            )
            txn_upserter(
                conn,
                r,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=sr_id,
            )
            return True

        result, _was_db_error = try_row_without_savepoint(
            conn,
            _link_va_row,
            manages_outer_transaction=manages_outer,
            label=f"VA {data_type} filing link",
        )

        if result is None:
            relational_errors += 1
            try:
                filing_lookup.pop(_build_va_filing_fec_id(row, data_type), None)
            except Exception:  # noqa: BLE001
                pass

    commit_managed_transaction(conn, manages_outer)
    return relational_errors


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def load_va_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    """Load VA contributions from a CSV file into the database."""
    return _load_va_file(conn, fp, data_type="contributions", limit=limit)


def load_va_expenditures_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    """Load VA expenditures from a CSV file into the database."""
    return _load_va_file(conn, fp, data_type="expenditures", limit=limit)


def _load_va_file(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    """Full two-phase load for a VA CSV file."""
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_va_data_source(conn, data_type=data_type)
    manages_outer = conn.info.transaction_status == TransactionStatus.IDLE

    if manages_outer:
        ensure_transaction_open(conn)

    parser_fn = parse_contributions if data_type == "contributions" else parse_expenditures

    try:
        # Phase 1: source records + entities
        phase1_rows = parser_fn(Path(fp))
        load_result = _load_va_phase1(
            conn,
            phase1_rows,
            data_source_id=data_source_id,
            data_type=data_type,
            limit=validated_row_limit,
        )

        # Phase 2: filing + transaction upserts (re-parse the file)
        phase2_rows = parser_fn(Path(fp))
        load_result.errors += _load_va_phase2(
            conn,
            phase2_rows,
            data_source_id=data_source_id,
            data_type=data_type,
            limit=validated_row_limit,
        )
    except Exception:
        if manages_outer:
            conn.rollback()
        raise

    if manages_outer:
        conn.commit()

    return load_result


__all__ = [
    "LoadResult",
    "ensure_va_data_source",
    "load_va_contributions_with_filings",
    "load_va_expenditures_with_filings",
]
