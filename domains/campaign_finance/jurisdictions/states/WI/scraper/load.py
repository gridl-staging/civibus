
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
    find_organization_by_identifier,
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
    try_row_without_savepoint,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import (
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
)
from .extract import extract_wi_transaction
from .parse import parse_transactions

LOGGER = logging.getLogger(__name__)

_WI_DOMAIN = "campaign_finance"
_WI_JURISDICTION = "state/WI"
_WI_SOURCE_FORMAT = "csv"


@dataclass(slots=True)
class _WILoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _WIFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


def _column(semantic_path: str) -> str:
    return _load_column_for_semantic_path("transactions", semantic_path)


def _normalized_column_text(row: Mapping[str, str | None], semantic_path: str) -> str | None:
    return normalize_optional_text(row.get(_column(semantic_path)))


def _required_column_text(row: Mapping[str, str | None], semantic_path: str) -> str:
    column_name = _column(semantic_path)
    return _required_wi_text(row.get(column_name), column_name)


def ensure_wi_data_source(conn: psycopg.Connection, data_type: str = "transactions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_WI_DOMAIN,
        jurisdiction=_WI_JURISDICTION,
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_WI_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _wi_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_wi_source_record(data_source_id: UUID, row: Mapping[str, str | None]) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_wi_source_record_key(row),
        source_url=_load_data_source_url_for_data_type("transactions"),
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _resolve_wi_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = normalize_optional_text(committee.identifiers.get("wi_registrant_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "wi_registrant_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("WI committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _load_wi_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict[str, object],
) -> None:
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
        raise ValueError("WI extraction must include committee organization")

    committee_org_id = _resolve_wi_committee_organization_id(conn, committee)
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


def _extract_and_load_wi_row(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    source_record = _build_wi_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_wi_transaction(dict(row))
    _load_wi_transaction_entities(conn, source_record_id=source_record_id, extracted=extracted)
    return True


def _try_load_wi_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    manages_outer_transaction: bool,
) -> tuple[bool | None, bool]:
    return try_row_without_savepoint(
        conn,
        lambda: _extract_and_load_wi_row(conn, row, data_source_id),
        manages_outer_transaction=manages_outer_transaction,
        label="WI transaction row",
    )


def _load_wi_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _WILoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        inserted, was_db_error = _try_load_wi_row(
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


def _load_wi_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = parse_transactions(Path(file_path))
    return _load_wi_rows(conn, parser, data_source_id=data_source_id, limit=validated_row_limit)


def _required_wi_text(value: str | None, field_name: str) -> str:
    normalized_value = normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"WI row is missing {field_name}")
    return normalized_value


def _parse_wi_amount(raw_value: str | None) -> Decimal:
    normalized_value = _required_wi_text(raw_value, "Amount")
    try:
        return Decimal(normalized_value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"WI row has invalid Amount: {raw_value!r}") from exc


def _parse_wi_date(raw_value: str | None) -> date | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    for date_format in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"WI row has invalid date: {raw_value!r}")


def _effective_wi_transaction_date(row: Mapping[str, str | None]) -> date | None:
    """Use the row's transaction date, falling back to communication date when needed."""
    transaction_date = _parse_wi_date(row.get(_column("transaction.date")))
    if transaction_date is not None:
        return transaction_date
    return _parse_wi_date(row.get(_column("wi.transaction.communication_date")))


def _normalize_support_stance(raw_value: str | None) -> str | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    lowered_value = normalized_value.lower()
    if lowered_value.startswith("support"):
        return "S"
    if lowered_value.startswith("oppose"):
        return "O"
    return None


def _build_wi_filing_fec_id(row: Mapping[str, str | None]) -> str:
    registrant_id = _required_column_text(row, "committee.id")
    transaction_date = _effective_wi_transaction_date(row)
    if transaction_date is None:
        raise ValueError("WI row is missing both Date and Communication Date")

    return f"WI-{registrant_id}-{transaction_date.year}-transactions"


def _select_wi_source_record_id(
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


def _resolve_wi_filing_committee_id(conn: psycopg.Connection, row: Mapping[str, str | None]) -> UUID:
    extracted = extract_wi_transaction(dict(row))
    committee = extracted["committee"]
    if not isinstance(committee, Organization):
        raise ValueError("WI row does not include resolvable committee")

    committee_organization_id = _resolve_wi_committee_organization_id(conn, committee)
    native_committee_id = _required_column_text(row, "committee.id")
    return ensure_state_committee(
        conn,
        state="WI",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_wi_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    transaction_date = _effective_wi_transaction_date(row)
    committee_name = _normalized_column_text(row, "committee.name")

    return Filing(
        filing_fec_id=_build_wi_filing_fec_id(row),
        committee_id=committee_id,
        report_type="transactions",
        amendment_indicator="N",
        filing_name=committee_name,
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )


def _upsert_wi_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    filing_lookup: dict[str, _WIFilingLookupEntry],
) -> _WIFilingLookupEntry:
    filing_fec_id = _build_wi_filing_fec_id(row)
    existing_entry = filing_lookup.get(filing_fec_id)

    if existing_entry is None:
        committee_id = _resolve_wi_filing_committee_id(conn, row)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_wi_filing(row, committee_id=committee_id, source_record_id=filing_source_record_id)
    filing_id = upsert_filing(conn, filing)

    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"WI filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _WIFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _resolve_wi_transaction_address_id(
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


def _upsert_wi_transaction_with_filing(
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

    contributor_address_id = _resolve_wi_transaction_address_id(conn, source_record_id=source_record_id)
    extracted = extract_wi_transaction(dict(row))
    contributor_address = extracted["address"]
    contributor_name = _normalized_column_text(row, "donor.name")
    contributor_city = contributor_address.city if contributor_address is not None else None
    contributor_state = contributor_address.state if contributor_address is not None else None
    contributor_zip = contributor_address.zip5 if contributor_address is not None else None
    contributor_occupation = _normalized_column_text(row, "donor.occupation")
    support_oppose = _normalize_support_stance(row.get(_column("transaction.support_stance")))
    transaction_type = (
        "Independent Expenditure" if support_oppose is not None else _required_column_text(row, "transaction.type")
    )

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            transaction_identifier=_normalized_column_text(row, "wi.transaction.id"),
            transaction_date=_effective_wi_transaction_date(row),
            amount=_parse_wi_amount(row.get(_column("transaction.amount"))),
            contributor_name_raw=contributor_name,
            contributor_employer=None,
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
            support_oppose=support_oppose,
        ),
    )


def _load_wi_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    limit: int | None,
) -> int:
    filing_lookup: dict[str, _WIFilingLookupEntry] = {}
    relational_errors = 0
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_wi_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_wi_source_record_key(row),
        )
        if source_record_id is None:
            continue

        def _link_wi_row() -> bool:
            """Upsert filing + link transaction. No per-row savepoint.
            Returns True on success so try_row_without_savepoint can
            distinguish success (True) from failure (None)."""
            filing_entry = _upsert_wi_filing(
                conn,
                row,
                source_record_id=source_record_id,
                filing_lookup=filing_lookup,
            )
            _upsert_wi_transaction_with_filing(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
            )
            return True

        result, was_db_error = try_row_without_savepoint(
            conn,
            _link_wi_row,
            manages_outer_transaction=manages_outer_transaction,
            label="WI filing link",
        )

        if result is None:
            relational_errors += 1
            # Invalidate any filing lookup entry that was created/updated
            # by this row, since the DB change was rolled back or never committed.
            try:
                filing_lookup.pop(_build_wi_filing_fec_id(row), None)
            except Exception:  # noqa: BLE001
                pass

    commit_managed_transaction(conn, manages_outer_transaction)
    return relational_errors


def load_wi_transactions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_wi_data_source(conn, data_type="transactions")
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    if manages_outer_transaction:
        ensure_transaction_open(conn)

    try:
        load_result = _load_wi_file(conn, fp, data_source_id=data_source_id, limit=validated_row_limit)
        load_result.errors += _load_wi_relational_transactions(
            conn,
            parse_transactions(Path(fp)),
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
    "ensure_wi_data_source",
    "load_wi_transactions_with_filings",
    "_parse_wi_date",
    "_normalize_support_stance",
    "_build_wi_filing_fec_id",
]
