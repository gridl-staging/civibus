"""Campaign-finance filing and transaction upsert helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg

from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.types.models import Filing, Transaction


def _amendment_precedence_case(value_expression: str) -> str:
    return f"""
CASE {value_expression}
    WHEN 'T' THEN 3
    WHEN 'A' THEN 2
    WHEN 'N' THEN 1
    ELSE 0
END
"""


_TRANSACTION_AMENDMENT_INDICATOR_INDEX = 23


_normalize_optional_text = normalize_optional_text


@dataclass(frozen=True, slots=True)
class TransactionUpsertResult:
    transaction_id: UUID
    inserted: bool


def _normalize_state_code(state: str) -> str:
    normalized_state = state.strip().upper()
    if len(normalized_state) != 2:
        raise ValueError("state must be a two-letter state code")
    return normalized_state


def _normalize_native_committee_id(native_committee_id: str) -> str:
    normalized_native_id = _normalize_optional_text(native_committee_id)
    if not normalized_native_id:
        raise ValueError("native_committee_id must be non-empty")
    return normalized_native_id


def generate_synthetic_committee_id(state: str, native_committee_id: str) -> str:
    normalized_state = _normalize_state_code(state)
    normalized_native_id = _normalize_native_committee_id(native_committee_id)
    digest = hashlib.sha256(f"{normalized_state}:{normalized_native_id}".encode("utf-8")).digest()
    committee_number = int.from_bytes(digest[:8], byteorder="big") % 100_000_000
    return f"C{committee_number:08d}"


def _fetch_optional_scalar(
    conn: psycopg.Connection,
    query: str,
    params: tuple[object, ...],
) -> object | None:
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _select_organization_canonical_name(
    conn: psycopg.Connection,
    organization_id: UUID,
) -> str:
    canonical_name = _fetch_optional_scalar(
        conn,
        "SELECT canonical_name FROM core.organization WHERE id = %s LIMIT 1",
        (organization_id,),
    )
    if canonical_name is None:
        raise ValueError(f"organization_id {organization_id} does not reference an existing core.organization row")
    return canonical_name


def ensure_state_committee(
    conn: psycopg.Connection,
    state: str,
    native_committee_id: str,
    organization_id: UUID,
) -> UUID:
    canonical_name = _select_organization_canonical_name(conn, organization_id)
    normalized_state = _normalize_state_code(state)
    synthetic_fec_committee_id = generate_synthetic_committee_id(normalized_state, native_committee_id)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (fec_committee_id, name, organization_id, state)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fec_committee_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                organization_id = EXCLUDED.organization_id,
                state = EXCLUDED.state
            RETURNING id
            """,
            (
                synthetic_fec_committee_id,
                canonical_name,
                organization_id,
                normalized_state,
            ),
        )
        return cursor.fetchone()[0]


def resolve_transaction_counterparty_ids(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID | None,
    person_roles: Sequence[str],
    organization_roles: Sequence[str],
) -> tuple[UUID | None, UUID | None]:
    if source_record_id is None:
        return None, None

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_type, entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND (
                    (entity_type = 'person' AND extraction_role = ANY(%s))
                 OR (entity_type = 'organization' AND extraction_role = ANY(%s))
              )
            """,
            (source_record_id, list(person_roles), list(organization_roles)),
        )
        rows = cursor.fetchall()

    person_ids = {row[1] for row in rows if row[0] == "person"}
    organization_ids = {row[1] for row in rows if row[0] == "organization"}
    if len(person_ids) == 1 and not organization_ids:
        return next(iter(person_ids)), None
    if len(organization_ids) == 1 and not person_ids:
        return None, next(iter(organization_ids))
    return None, None


def update_transaction_contributor_identity_ids(
    conn: psycopg.Connection,
    *,
    transaction_id: UUID,
    contributor_person_id: UUID | None,
    contributor_organization_id: UUID | None,
) -> bool:
    """Update only contributor identity IDs for an existing transaction row."""
    if contributor_person_id is not None and contributor_organization_id is not None:
        raise ValueError("Only one contributor identifier may be provided")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE cf.transaction
            SET contributor_person_id = %s,
                contributor_organization_id = %s
            WHERE id = %s
              AND (
                    contributor_person_id IS DISTINCT FROM %s
                 OR contributor_organization_id IS DISTINCT FROM %s
              )
            RETURNING id
            """,
            (
                contributor_person_id,
                contributor_organization_id,
                transaction_id,
                contributor_person_id,
                contributor_organization_id,
            ),
        )
        return cursor.fetchone() is not None


def upsert_filing(conn: psycopg.Connection, filing: Filing) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO cf.filing (
                id,
                filing_fec_id,
                committee_id,
                candidate_id,
                election_id,
                report_type,
                amendment_indicator,
                filing_name,
                coverage_start_date,
                coverage_end_date,
                due_date,
                receipt_date,
                accepted_date,
                amended_from_filing_id,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (filing_fec_id)
            DO UPDATE SET
                committee_id = EXCLUDED.committee_id,
                candidate_id = COALESCE(EXCLUDED.candidate_id, cf.filing.candidate_id),
                election_id = COALESCE(EXCLUDED.election_id, cf.filing.election_id),
                report_type = COALESCE(EXCLUDED.report_type, cf.filing.report_type),
                amendment_indicator = CASE
                    WHEN (
                        {_amendment_precedence_case("EXCLUDED.amendment_indicator")}
                    ) > (
                        {_amendment_precedence_case("cf.filing.amendment_indicator")}
                    ) THEN EXCLUDED.amendment_indicator
                    ELSE cf.filing.amendment_indicator
                END,
                filing_name = COALESCE(EXCLUDED.filing_name, cf.filing.filing_name),
                coverage_start_date = COALESCE(EXCLUDED.coverage_start_date, cf.filing.coverage_start_date),
                coverage_end_date = COALESCE(EXCLUDED.coverage_end_date, cf.filing.coverage_end_date),
                due_date = COALESCE(EXCLUDED.due_date, cf.filing.due_date),
                receipt_date = COALESCE(EXCLUDED.receipt_date, cf.filing.receipt_date),
                accepted_date = COALESCE(EXCLUDED.accepted_date, cf.filing.accepted_date),
                amended_from_filing_id = COALESCE(EXCLUDED.amended_from_filing_id, cf.filing.amended_from_filing_id),
                source_record_id = COALESCE(EXCLUDED.source_record_id, cf.filing.source_record_id)
            RETURNING id
            """,
            (
                filing.id,
                filing.filing_fec_id,
                filing.committee_id,
                filing.candidate_id,
                filing.election_id,
                filing.report_type,
                filing.amendment_indicator,
                filing.filing_name,
                filing.coverage_start_date,
                filing.coverage_end_date,
                filing.due_date,
                filing.receipt_date,
                filing.accepted_date,
                filing.amended_from_filing_id,
                filing.source_record_id,
            ),
        )
        return cursor.fetchone()[0]


def upsert_filings_bulk(conn: psycopg.Connection, filings: Sequence[Filing]) -> dict[str, UUID]:
    from domains.campaign_finance.ingest import filing_loader_bulk

    return filing_loader_bulk.upsert_filings_bulk(conn, filings)


def _select_transaction_id_by_sub_id(conn: psycopg.Connection, sub_id: int) -> UUID | None:
    return _fetch_optional_scalar(
        conn,
        "SELECT id FROM cf.transaction WHERE sub_id = %s LIMIT 1",
        (sub_id,),
    )


def _select_transaction_id_by_filing_and_identifier(
    conn: psycopg.Connection,
    filing_id: UUID,
    transaction_identifier: str,
) -> UUID | None:
    return _fetch_optional_scalar(
        conn,
        """
        SELECT id
        FROM cf.transaction
        WHERE filing_id = %s
          AND transaction_identifier = %s
        LIMIT 1
        """,
        (filing_id, transaction_identifier),
    )


def _normalize_transaction(transaction: Transaction) -> Transaction:
    normalized_transaction_identifier = _normalize_optional_text(transaction.transaction_identifier)
    normalized_back_ref = _normalize_optional_text(transaction.back_ref_transaction_id)
    updates: dict[str, str | None] = {}
    if normalized_transaction_identifier != transaction.transaction_identifier:
        updates["transaction_identifier"] = normalized_transaction_identifier
    if normalized_back_ref != transaction.back_ref_transaction_id:
        updates["back_ref_transaction_id"] = normalized_back_ref
    if not updates:
        return transaction
    return transaction.model_copy(update=updates)


def _resolve_existing_transaction_id(conn: psycopg.Connection, transaction: Transaction) -> UUID | None:
    existing_id_by_sub_id = None
    if transaction.sub_id is not None:
        existing_id_by_sub_id = _select_transaction_id_by_sub_id(conn, transaction.sub_id)

    existing_id_by_filing_identifier = None
    if transaction.transaction_identifier is not None:
        existing_id_by_filing_identifier = _select_transaction_id_by_filing_and_identifier(
            conn,
            transaction.filing_id,
            transaction.transaction_identifier,
        )

    if (
        existing_id_by_sub_id is not None
        and existing_id_by_filing_identifier is not None
        and existing_id_by_sub_id != existing_id_by_filing_identifier
    ):
        raise ValueError("idempotency keys map to different existing transactions")

    return existing_id_by_sub_id or existing_id_by_filing_identifier


def _transaction_values(transaction: Transaction) -> tuple[object, ...]:
    return (
        transaction.filing_id,
        transaction.committee_id,
        transaction.transaction_type,
        transaction.transaction_identifier,
        transaction.back_ref_transaction_id,
        transaction.sub_id,
        transaction.transaction_date,
        transaction.amount,
        transaction.contributor_name_raw,
        transaction.contributor_entity_type,
        transaction.contributor_employer,
        transaction.contributor_occupation,
        transaction.contributor_city,
        transaction.contributor_state,
        transaction.contributor_zip,
        transaction.contributor_person_id,
        transaction.contributor_organization_id,
        transaction.contributor_address_id,
        transaction.recipient_candidate_id,
        transaction.recipient_committee_id,
        transaction.memo_code,
        transaction.memo_text,
        transaction.is_memo,
        transaction.amendment_indicator,
        transaction.amended_by_transaction_id,
        transaction.source_record_id,
        transaction.date_is_reliable,
        transaction.support_oppose,
        transaction.dissemination_date,
        transaction.aggregate_amount,
    )


def _transaction_update_values(transaction: Transaction) -> tuple[object, ...]:
    transaction_values = _transaction_values(transaction)
    amendment_indicator = transaction_values[_TRANSACTION_AMENDMENT_INDICATOR_INDEX]
    return (
        *transaction_values[: _TRANSACTION_AMENDMENT_INDICATOR_INDEX + 1],
        amendment_indicator,
        *transaction_values[_TRANSACTION_AMENDMENT_INDICATOR_INDEX + 1 :],
    )


def _update_transaction(
    conn: psycopg.Connection,
    *,
    existing_transaction_id: UUID,
    transaction: Transaction,
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE cf.transaction
            SET filing_id = %s,
                committee_id = %s,
                transaction_type = %s,
                transaction_identifier = COALESCE(%s, transaction_identifier),
                back_ref_transaction_id = COALESCE(%s, back_ref_transaction_id),
                sub_id = COALESCE(%s, sub_id),
                transaction_date = %s,
                amount = %s,
                contributor_name_raw = %s,
                contributor_entity_type = %s,
                contributor_employer = %s,
                contributor_occupation = %s,
                contributor_city = %s,
                contributor_state = %s,
                contributor_zip = %s,
                contributor_person_id = %s,
                contributor_organization_id = %s,
                contributor_address_id = %s,
                recipient_candidate_id = %s,
                recipient_committee_id = %s,
                memo_code = %s,
                memo_text = %s,
                is_memo = %s,
                amendment_indicator = CASE
                    WHEN ({_amendment_precedence_case("%s")}) > ({_amendment_precedence_case("amendment_indicator")})
                        THEN %s
                    ELSE amendment_indicator
                END,
                amended_by_transaction_id = %s,
                source_record_id = COALESCE(%s, source_record_id),
                date_is_reliable = %s,
                support_oppose = %s,
                dissemination_date = %s,
                aggregate_amount = %s
            WHERE id = %s
            RETURNING id
            """,
            (*_transaction_update_values(transaction), existing_transaction_id),
        )
        return cursor.fetchone()[0]


def _insert_transaction(conn: psycopg.Connection, transaction: Transaction) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.transaction (
                id,
                filing_id,
                committee_id,
                transaction_type,
                transaction_identifier,
                back_ref_transaction_id,
                sub_id,
                transaction_date,
                amount,
                contributor_name_raw,
                contributor_entity_type,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                contributor_person_id,
                contributor_organization_id,
                contributor_address_id,
                recipient_candidate_id,
                recipient_committee_id,
                memo_code,
                memo_text,
                is_memo,
                amendment_indicator,
                amended_by_transaction_id,
                source_record_id,
                date_is_reliable,
                support_oppose,
                dissemination_date,
                aggregate_amount
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (transaction.id, *_transaction_values(transaction)),
        )
        return cursor.fetchone()[0]


def upsert_transaction_with_status(conn: psycopg.Connection, transaction: Transaction) -> TransactionUpsertResult:
    normalized_transaction = _normalize_transaction(transaction)
    if normalized_transaction.sub_id is None and normalized_transaction.transaction_identifier is None:
        raise ValueError("upsert_transaction requires at least one idempotency key")

    existing_transaction_id = _resolve_existing_transaction_id(conn, normalized_transaction)
    if existing_transaction_id is not None:
        transaction_id = _update_transaction(
            conn,
            existing_transaction_id=existing_transaction_id,
            transaction=normalized_transaction,
        )
        return TransactionUpsertResult(transaction_id=transaction_id, inserted=False)
    return TransactionUpsertResult(
        transaction_id=_insert_transaction(conn, normalized_transaction),
        inserted=True,
    )


def upsert_transactions_with_status_bulk(
    conn: psycopg.Connection,
    transactions: Sequence[Transaction],
) -> list[TransactionUpsertResult]:
    from domains.campaign_finance.ingest import filing_loader_bulk

    return filing_loader_bulk.upsert_transactions_with_status_bulk(conn, transactions)


def upsert_transaction(conn: psycopg.Connection, transaction: Transaction) -> UUID:
    return upsert_transaction_with_status(conn, transaction).transaction_id


__all__ = [
    "ensure_state_committee",
    "generate_synthetic_committee_id",
    "resolve_transaction_counterparty_ids",
    "update_transaction_contributor_identity_ids",
    "upsert_filing",
    "upsert_filings_bulk",
    "upsert_transaction",
    "upsert_transaction_with_status",
    "upsert_transactions_with_status_bulk",
]
