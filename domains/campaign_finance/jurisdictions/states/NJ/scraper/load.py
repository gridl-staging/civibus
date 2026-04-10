"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_am_3_new_state_pipeline_builds/civibus_dev/domains/campaign_finance/jurisdictions/states/NJ/scraper/load.py.
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
    Person,
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
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import (
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
)
from .extract import extract_nj_contribution
from .parse import parse_contributions

LOGGER = logging.getLogger(__name__)

_NJ_DOMAIN = "campaign_finance"
_NJ_JURISDICTION = "state/NJ"
_NJ_SOURCE_FORMAT = "csv"


@dataclass(slots=True)
class _NJLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _NJFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


def _column(semantic_path: str) -> str:
    return _load_column_for_semantic_path("contributions", semantic_path)


def _normalized_column_text(row: Mapping[str, str | None], semantic_path: str) -> str | None:
    return normalize_optional_text(row.get(_column(semantic_path)))


# --- Date / amount parsing ---


def _parse_nj_date(raw_value: str | None) -> date | None:
    """Parse NJ date strings in mm/dd/yyyy or ISO format; return None for empty."""
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    if not normalized:
        return None

    for date_format in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"NJ row has invalid date: {raw_value!r}")


def _parse_nj_amount(raw_value: str | None) -> Decimal:
    """Parse a comma-separated dollar amount into Decimal."""
    if raw_value is None or raw_value.strip() == "":
        raise ValueError("NJ row has invalid ContributionAmount: empty")
    try:
        return Decimal(raw_value.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"NJ row has invalid ContributionAmount: {raw_value!r}") from exc


# --- Filing ID ---


def _build_nj_filing_fec_id(row: Mapping[str, str | None]) -> str:
    """Build a synthetic filing ID from EntityName + ElectionYear."""
    entity_name = _normalized_column_text(row, "committee.name") or ""
    election_year = _normalized_column_text(row, "transaction.year") or ""
    return f"NJ-{entity_name}-{election_year}-contributions"


# --- Data source ---


def ensure_nj_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    """Ensure the NJ data source row exists and return its ID."""
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_NJ_DOMAIN,
        jurisdiction=_NJ_JURISDICTION,
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_NJ_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


# --- Base entity load (pass 1) ---


def _nj_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_nj_source_record(data_source_id: UUID, row: Mapping[str, str | None]) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_nj_source_record_key(row),
        source_url=_load_data_source_url_for_data_type("contributions"),
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _resolve_nj_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("NJ committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _load_nj_contribution_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict[str, object],
) -> None:
    """Persist extracted entities (person, org, committee, address) with provenance links."""
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

    contributor_person = extracted["contributor_person"]
    if isinstance(contributor_person, Person):
        person_id = resolve_person_by_name_and_zip(
            conn, contributor_person, address if isinstance(address, Address) else None
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

    committee = extracted["committee"]
    if not isinstance(committee, Organization):
        raise ValueError("NJ extraction must include committee organization")

    committee_org_id = _resolve_nj_committee_organization_id(conn, committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_org_id,
        source_record_id=source_record_id,
        extraction_role="recipient",
        address_id=None,
    )

    contributor_org = extracted["contributor_org"]
    if isinstance(contributor_org, Organization):
        contributor_org_id = resolve_organization_by_canonical_name(conn, contributor_org)
        if contributor_org_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="organization",
                entity_id=contributor_org_id,
                source_record_id=source_record_id,
                extraction_role="contributor",
                address_id=address_id,
            )


def _extract_and_load_nj_row(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    source_record = _build_nj_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_nj_contribution(dict(row))
    _load_nj_contribution_entities(conn, source_record_id=source_record_id, extracted=extracted)
    return True


def _try_load_nj_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)

        with conn.transaction():
            return _extract_and_load_nj_row(conn, row, data_source_id)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading NJ contribution row")
        return None


def _load_nj_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _NJLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        inserted = _try_load_nj_row(
            conn,
            row,
            data_source_id=data_source_id,
            manages_outer_transaction=manages_outer_transaction,
        )

        if inserted is None:
            counts.errors += 1
        elif inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

        processed_count = counts.inserted + counts.skipped + counts.errors
        if processed_count % 1_000 == 0:
            commit_managed_transaction(conn, manages_outer_transaction)

    commit_managed_transaction(conn, manages_outer_transaction)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_nj_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = parse_contributions(Path(file_path))
    return _load_nj_rows(conn, parser, data_source_id=data_source_id, limit=validated_row_limit)


# --- Relational pass (filings + transactions, pass 2) ---


def _select_nj_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _resolve_nj_filing_committee_id(conn: psycopg.Connection, row: Mapping[str, str | None]) -> UUID:
    extracted = extract_nj_contribution(dict(row))
    committee = extracted["committee"]
    if not isinstance(committee, Organization):
        raise ValueError("NJ row does not include resolvable committee")

    committee_organization_id = _resolve_nj_committee_organization_id(conn, committee)
    # NJ has no registrant_id; use EntityName as native committee ID
    native_committee_id = _normalized_column_text(row, "committee.name") or ""
    return ensure_state_committee(
        conn,
        state="NJ",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_nj_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    transaction_date = _parse_nj_date(row.get(_column("transaction.date")))
    committee_name = _normalized_column_text(row, "committee.name")

    return Filing(
        filing_fec_id=_build_nj_filing_fec_id(row),
        committee_id=committee_id,
        report_type="contributions",
        amendment_indicator="N",
        filing_name=committee_name,
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )


def _upsert_nj_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    filing_lookup: dict[str, _NJFilingLookupEntry],
) -> _NJFilingLookupEntry:
    filing_fec_id = _build_nj_filing_fec_id(row)
    existing_entry = filing_lookup.get(filing_fec_id)

    if existing_entry is None:
        committee_id = _resolve_nj_filing_committee_id(conn, row)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_nj_filing(row, committee_id=committee_id, source_record_id=filing_source_record_id)
    filing_id = upsert_filing(conn, filing)

    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"NJ filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _NJFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _resolve_nj_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = %s
              AND extraction_role = %s
            LIMIT 1
            """,
            (source_record_id, "address", "contributor_address"),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _upsert_nj_contribution_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
) -> None:
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=("contributor",),
        organization_roles=("contributor",),
    )

    contributor_address_id = _resolve_nj_transaction_address_id(conn, source_record_id=source_record_id)

    # Build contributor name from NJ structured fields
    is_individual = _normalized_column_text(row, "donor.is_individual")
    if is_individual and is_individual.lower() == "true":
        first = _normalized_column_text(row, "donor.first_name") or ""
        last = _normalized_column_text(row, "donor.last_name") or ""
        contributor_name = f"{first} {last}".strip() or None
    else:
        contributor_name = _normalized_column_text(row, "donor.organization_name")

    contributor_city = _normalized_column_text(row, "donor.address.city")
    contributor_state = _normalized_column_text(row, "donor.address.state")
    contributor_zip = _normalized_column_text(row, "donor.address.zip")
    contributor_occupation = _normalized_column_text(row, "donor.occupation")
    contributor_employer = _normalized_column_text(row, "donor.employer")

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=_normalized_column_text(row, "transaction.type") or "contribution",
            transaction_identifier=None,
            transaction_date=_parse_nj_date(row.get(_column("transaction.date"))),
            amount=_parse_nj_amount(row.get(_column("transaction.amount"))),
            contributor_name_raw=contributor_name,
            contributor_employer=contributor_employer,
            contributor_occupation=contributor_occupation,
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
            support_oppose=None,
        ),
    )


def _load_nj_relational_contributions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    limit: int | None,
) -> int:
    """Second pass: upsert filings and transactions linked to already-loaded source records."""
    filing_lookup: dict[str, _NJFilingLookupEntry] = {}
    relational_errors = 0
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_nj_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_nj_source_record_key(row),
        )
        if source_record_id is None:
            continue

        try:
            if manages_outer_transaction:
                ensure_transaction_open(conn)

            with conn.transaction():
                filing_entry = _upsert_nj_filing(
                    conn,
                    row,
                    source_record_id=source_record_id,
                    filing_lookup=filing_lookup,
                )
                _upsert_nj_contribution_with_filing(
                    conn,
                    row,
                    filing_id=filing_entry.filing_id,
                    committee_id=filing_entry.committee_id,
                    source_record_id=source_record_id,
                )
        except Exception:  # noqa: BLE001
            relational_errors += 1
            LOGGER.exception("Failed linking NJ contribution row to filing")

    commit_managed_transaction(conn, manages_outer_transaction)
    return relational_errors


# --- Public entry point ---


def load_nj_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    """Two-pass NJ contribution load: base entities, then filings + transactions."""
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_nj_data_source(conn, data_type="contributions")
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    if manages_outer_transaction:
        ensure_transaction_open(conn)

    try:
        load_result = _load_nj_file(conn, fp, data_source_id=data_source_id, limit=validated_row_limit)
        load_result.errors += _load_nj_relational_contributions(
            conn,
            parse_contributions(Path(fp)),
            data_source_id=data_source_id,
            limit=validated_row_limit,
        )
    except Exception:
        if manages_outer_transaction:
            conn.rollback()
        raise

    if manages_outer_transaction:
        conn.commit()

    return load_result


__all__ = [
    "LoadResult",
    "ensure_nj_data_source",
    "load_nj_contributions_with_filings",
    "_parse_nj_date",
    "_parse_nj_amount",
    "_build_nj_filing_fec_id",
]
