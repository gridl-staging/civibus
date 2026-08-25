"""Indiana filing and transaction linkage for rows loaded by the raw phase."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

import psycopg

from core.types.python.models import Address
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    commit_managed_transaction,
    iter_rows_with_limit,
    try_row_without_savepoint,
)
from domains.campaign_finance.types.models import Filing, Transaction

from .load_helpers import (
    _in_amendment_indicator,
    _in_counterparty_occupation,
    _in_data_type_spec,
    _in_extract_row,
    _in_filing_fec_id,
    _in_native_committee_id,
    _in_row_value,
    _in_source_record_key,
    _in_transaction_identifier,
    _in_transaction_type,
    _parse_in_date,
    _required_in_amount_from_row,
    _resolve_in_committee_organization_id,
)

_COMMIT_BATCH_ROWS = 1_000
_PENDING_RELATIONAL_ID = UUID(int=0)


class INFilingLookupDrift(ValueError):
    """The cached filing id for a filing key disagrees with the database result.

    This is an integrity violation in loader state, not a bad-data row. The shared row
    boundary catches every ``Exception``, so the relational pass explicitly re-raises it.
    """


class INCallerTransactionRolledBack(RuntimeError):
    """A relational DB error rolled back a caller-owned transaction."""


@dataclass(frozen=True, slots=True)
class _INFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


def _select_in_source_record_id(
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


def _resolve_in_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _in_extract_row(row, data_type)
    committee_organization_id = _resolve_in_committee_organization_id(conn, extracted["committee"])
    native_committee_id = _in_native_committee_id(row, data_type=data_type)

    return ensure_state_committee(
        conn,
        state="IN",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_in_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    extracted = _in_extract_row(row, data_type)
    transaction_date = _parse_in_date(_in_row_value(row, data_type=data_type, semantic_path="transaction.date"))

    return Filing(
        filing_fec_id=_in_filing_fec_id(row, data_type=data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator=_in_amendment_indicator(row, data_type=data_type),
        filing_name=normalize_optional_text(extracted["committee"].canonical_name),
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )


def _upsert_in_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _INFilingLookupEntry],
) -> _INFilingLookupEntry:
    filing_fec_id = _in_filing_fec_id(row, data_type=data_type)
    existing_entry = filing_lookup.get(filing_fec_id)

    if existing_entry is None:
        committee_id = _resolve_in_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_in_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise INFilingLookupDrift(
            f"IN filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _INFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    return _counterparty_details(row, data_type)[0]


def _counterparty_details(row: Mapping[str, str | None], data_type: str) -> tuple[str | None, Address | None]:
    extracted = _in_extract_row(row, data_type)
    spec = _in_data_type_spec(data_type)
    address = extracted.get("address")

    person = extracted[spec.person_key]
    if person is not None:
        return normalize_optional_text(person.canonical_name), address

    organization = extracted[spec.organization_key]
    if organization is not None:
        return normalize_optional_text(organization.canonical_name), address

    return None, address


def _resolve_in_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _in_data_type_spec(data_type).address_role

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = 'address'
              AND extraction_role = %s
            LIMIT 1
            """,
            (source_record_id, address_role),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def _counterparty_address(row: Mapping[str, str | None], data_type: str) -> Address | None:
    return _counterparty_details(row, data_type)[1]


def _build_in_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
) -> Transaction:
    """Build and validate an IN transaction before the relational phase writes."""
    spec = _in_data_type_spec(data_type)
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=spec.person_roles,
        organization_roles=spec.organization_roles,
    )

    contributor_address_id = _resolve_in_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )
    contributor_name_raw, counterparty_address = _counterparty_details(row, data_type)

    contributor_city = counterparty_address.city if counterparty_address is not None else None
    contributor_state = counterparty_address.state if counterparty_address is not None else None
    contributor_zip = counterparty_address.zip5 if counterparty_address is not None else None

    return Transaction(
        filing_id=_PENDING_RELATIONAL_ID,
        committee_id=_PENDING_RELATIONAL_ID,
        transaction_type=_in_transaction_type(row, data_type=data_type),
        transaction_identifier=_in_transaction_identifier(row, data_type=data_type),
        transaction_date=_parse_in_date(_in_row_value(row, data_type=data_type, semantic_path="transaction.date")),
        amount=_required_in_amount_from_row(row, data_type=data_type, semantic_path="transaction.amount"),
        contributor_name_raw=contributor_name_raw,
        contributor_employer=None,
        contributor_occupation=_in_counterparty_occupation(row, data_type=data_type),
        contributor_city=contributor_city,
        contributor_state=contributor_state,
        contributor_zip=contributor_zip,
        contributor_person_id=contributor_person_id,
        contributor_organization_id=contributor_organization_id,
        contributor_address_id=contributor_address_id,
        recipient_committee_id=_PENDING_RELATIONAL_ID,
        amendment_indicator=_in_amendment_indicator(row, data_type=data_type),
        source_record_id=source_record_id,
    )


def _upsert_in_transaction_with_filing(
    conn: psycopg.Connection,
    transaction: Transaction,
    *,
    filing_id: UUID,
    committee_id: UUID,
) -> None:
    """Write a validated transaction using the filing resolved for its row."""
    upsert_transaction(
        conn,
        transaction.model_copy(
            update={
                "filing_id": filing_id,
                "committee_id": committee_id,
                "recipient_committee_id": committee_id,
            }
        ),
    )


def _link_in_row_without_savepoint(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _INFilingLookupEntry],
    manages_outer_transaction: bool,
) -> tuple[bool, bool]:
    """Link one loaded row through the shared no-savepoint boundary."""
    drift_error: INFilingLookupDrift | None = None

    def _link_row() -> bool:
        nonlocal drift_error
        transaction = _build_in_transaction(
            conn,
            row,
            source_record_id=source_record_id,
            data_type=data_type,
        )
        try:
            filing_entry = _upsert_in_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
        except INFilingLookupDrift as drift:
            drift_error = drift
            raise
        _upsert_in_transaction_with_filing(
            conn,
            transaction,
            filing_id=filing_entry.filing_id,
            committee_id=filing_entry.committee_id,
        )
        return True

    result, was_db_error = try_row_without_savepoint(
        conn,
        _link_row,
        manages_outer_transaction=manages_outer_transaction,
        label=f"IN {data_type.rstrip('s')} filing link",
    )
    if drift_error is not None:
        raise drift_error
    return result is not None, was_db_error


def _load_in_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> int:
    """Link loaded IN rows to filings and return the number of lost links."""
    filing_lookup: dict[str, _INFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    processed_count = 0
    error_count = 0
    linked_rows_since_commit = 0

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_in_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_in_source_record_key(row, data_type=data_type),
        )
        if source_record_id is not None:
            linked, was_db_error = _link_in_row_without_savepoint(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
                manages_outer_transaction=manages_outer_transaction,
            )
            if linked:
                linked_rows_since_commit += 1
            else:
                error_count += 1
            if was_db_error:
                if not manages_outer_transaction:
                    raise INCallerTransactionRolledBack(
                        "IN relational DB error rolled back the caller-owned transaction; aborting load"
                    )
                error_count += linked_rows_since_commit
                linked_rows_since_commit = 0
                # A DB rollback erases every uncommitted filing in the batch, so restoring
                # one key can leave another cached filing pointing at a row that vanished.
                filing_lookup.clear()

        processed_count += 1
        if processed_count % _COMMIT_BATCH_ROWS == 0:
            commit_managed_transaction(conn, manages_outer_transaction)
            if manages_outer_transaction:
                linked_rows_since_commit = 0

    commit_managed_transaction(conn, manages_outer_transaction)
    return error_count
