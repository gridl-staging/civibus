
from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Literal
from uuid import UUID

import psycopg

from domains.campaign_finance.ingest.filing_loader import (
    TransactionUpsertResult,
    _amendment_precedence_case,
    _normalize_transaction,
    _transaction_values,
    upsert_transaction_with_status,
)
from domains.campaign_finance.types.models import Filing, Transaction


@lru_cache(maxsize=32)
def _values_placeholders(*, row_count: int, column_count: int) -> str:
    if row_count <= 0:
        raise ValueError("row_count must be greater than zero")
    if column_count <= 0:
        raise ValueError("column_count must be greater than zero")

    row_sql = f"({', '.join('%s' for _ in range(column_count))})"
    return ", ".join(row_sql for _ in range(row_count))


def _flatten_rows(rows: Sequence[tuple[object, ...]]) -> list[object]:
    return [value for row in rows for value in row]


def _filing_values(filing: Filing) -> tuple[object, ...]:
    return (
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
    )


_TransactionConflictMode = Literal["sub_id", "filing_identifier"]
_TRANSACTION_CONFLICT_SQL: dict[_TransactionConflictMode, tuple[str, str]] = {
    "sub_id": ("sub_id", "sub_id IS NOT NULL"),
    "filing_identifier": ("filing_id, transaction_identifier", "transaction_identifier IS NOT NULL"),
}


@lru_cache(maxsize=8)
def _filing_upsert_statement(*, row_count: int, column_count: int) -> str:
    return f"""
        WITH input_rows (
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
        ) AS (
            VALUES {_values_placeholders(row_count=row_count, column_count=column_count)}
        )
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
        SELECT
            id,
            filing_fec_id,
            committee_id,
            candidate_id::uuid,
            election_id::uuid,
            report_type,
            amendment_indicator,
            filing_name,
            coverage_start_date::date,
            coverage_end_date::date,
            due_date::date,
            receipt_date::date,
            accepted_date::date,
            amended_from_filing_id::uuid,
            source_record_id::uuid
        FROM input_rows
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
        RETURNING id, filing_fec_id
        """


@lru_cache(maxsize=16)
def _transaction_upsert_statement(
    *,
    row_count: int,
    column_count: int,
    conflict_mode: _TransactionConflictMode,
) -> str:
    conflict_target, conflict_predicate = _TRANSACTION_CONFLICT_SQL[conflict_mode]
    return f"""
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
        VALUES {_values_placeholders(row_count=row_count, column_count=column_count)}
        ON CONFLICT ({conflict_target}) WHERE {conflict_predicate}
        DO UPDATE SET
            filing_id = EXCLUDED.filing_id,
            committee_id = EXCLUDED.committee_id,
            transaction_type = EXCLUDED.transaction_type,
            transaction_identifier = COALESCE(EXCLUDED.transaction_identifier, cf.transaction.transaction_identifier),
            back_ref_transaction_id = COALESCE(EXCLUDED.back_ref_transaction_id, cf.transaction.back_ref_transaction_id),
            sub_id = COALESCE(EXCLUDED.sub_id, cf.transaction.sub_id),
            transaction_date = EXCLUDED.transaction_date,
            amount = EXCLUDED.amount,
            contributor_name_raw = EXCLUDED.contributor_name_raw,
            contributor_entity_type = EXCLUDED.contributor_entity_type,
            contributor_employer = EXCLUDED.contributor_employer,
            contributor_occupation = EXCLUDED.contributor_occupation,
            contributor_city = EXCLUDED.contributor_city,
            contributor_state = EXCLUDED.contributor_state,
            contributor_zip = EXCLUDED.contributor_zip,
            contributor_person_id = EXCLUDED.contributor_person_id,
            contributor_organization_id = EXCLUDED.contributor_organization_id,
            contributor_address_id = EXCLUDED.contributor_address_id,
            recipient_candidate_id = EXCLUDED.recipient_candidate_id,
            recipient_committee_id = EXCLUDED.recipient_committee_id,
            memo_code = EXCLUDED.memo_code,
            memo_text = EXCLUDED.memo_text,
            is_memo = EXCLUDED.is_memo,
            amendment_indicator = CASE
                WHEN ({_amendment_precedence_case("EXCLUDED.amendment_indicator")}) > (
                    {_amendment_precedence_case("cf.transaction.amendment_indicator")}
                )
                    THEN EXCLUDED.amendment_indicator
                ELSE cf.transaction.amendment_indicator
            END,
            amended_by_transaction_id = EXCLUDED.amended_by_transaction_id,
            source_record_id = COALESCE(EXCLUDED.source_record_id, cf.transaction.source_record_id),
            date_is_reliable = EXCLUDED.date_is_reliable,
            support_oppose = EXCLUDED.support_oppose,
            dissemination_date = EXCLUDED.dissemination_date,
            aggregate_amount = EXCLUDED.aggregate_amount
        RETURNING id, (xmax = 0) AS inserted, sub_id, filing_id, transaction_identifier
        """


@lru_cache(maxsize=8)
def _dual_key_conflict_probe_statement(*, row_count: int, column_count: int) -> str:
    return f"""
        WITH incoming(filing_id, transaction_identifier, sub_id) AS (
            VALUES {_values_placeholders(row_count=row_count, column_count=column_count)}
        )
        SELECT 1
        FROM incoming
        JOIN cf.transaction AS existing_transaction
          ON existing_transaction.filing_id = incoming.filing_id
         AND existing_transaction.transaction_identifier = incoming.transaction_identifier
        WHERE existing_transaction.sub_id IS DISTINCT FROM incoming.sub_id
        LIMIT 1
        """


def upsert_filings_bulk(conn: psycopg.Connection, filings: Sequence[Filing]) -> dict[str, UUID]:
    """Upsert filings in one statement and return ids by filing_fec_id."""
    if not filings:
        return {}

    deduped_by_filing_fec_id: dict[str, Filing] = {}
    for filing in filings:
        deduped_by_filing_fec_id[filing.filing_fec_id] = filing

    ordered_filings = list(deduped_by_filing_fec_id.values())
    rows = [_filing_values(filing) for filing in ordered_filings]
    statement = _filing_upsert_statement(row_count=len(rows), column_count=len(rows[0]))
    with conn.cursor() as cursor:
        cursor.execute(statement, _flatten_rows(rows))
        return {filing_fec_id: filing_id for filing_id, filing_fec_id in cursor.fetchall()}


def _bulk_upsert_transactions_for_conflict_target(
    conn: psycopg.Connection,
    *,
    transactions: Sequence[Transaction],
    conflict_mode: _TransactionConflictMode,
) -> list[tuple[UUID, bool, int | None, UUID, str | None]]:
    if not transactions:
        return []

    rows = [(transaction.id, *_transaction_values(transaction)) for transaction in transactions]
    statement = _transaction_upsert_statement(
        row_count=len(rows),
        column_count=len(rows[0]),
        conflict_mode=conflict_mode,
    )
    with conn.cursor() as cursor:
        cursor.execute(statement, _flatten_rows(rows))
        return cursor.fetchall()


def _has_duplicate_transaction_idempotency_keys(transactions: Sequence[Transaction]) -> bool:
    seen_keys: set[tuple[str, object, object | None]] = set()
    for transaction in transactions:
        transaction_keys: list[tuple[str, object, object | None]] = []
        if transaction.sub_id is not None:
            transaction_keys.append(("sub_id", transaction.sub_id, None))
        if transaction.transaction_identifier is not None:
            transaction_keys.append(("filing_identifier", transaction.filing_id, transaction.transaction_identifier))
        if not transaction_keys:
            raise RuntimeError("validated transaction unexpectedly lost its idempotency key")
        for key in transaction_keys:
            if key in seen_keys:
                return True
            seen_keys.add(key)
    return False


def _has_existing_dual_key_filing_identifier_conflict(
    conn: psycopg.Connection,
    transactions: Sequence[Transaction],
) -> bool:
    dual_key_rows = [
        (transaction.filing_id, transaction.transaction_identifier, transaction.sub_id)
        for transaction in transactions
        if transaction.sub_id is not None and transaction.transaction_identifier is not None
    ]
    if not dual_key_rows:
        return False

    statement = _dual_key_conflict_probe_statement(row_count=len(dual_key_rows), column_count=len(dual_key_rows[0]))
    with conn.cursor() as cursor:
        cursor.execute(statement, _flatten_rows(dual_key_rows))
        return cursor.fetchone() is not None


def upsert_transactions_with_status_bulk(
    conn: psycopg.Connection,
    transactions: Sequence[Transaction],
) -> list[TransactionUpsertResult]:
    """Bulk Stage 4 upsert path preserving per-row inserted/skipped accounting."""
    if not transactions:
        return []

    normalized_transactions = [_normalize_transaction(transaction) for transaction in transactions]
    for transaction in normalized_transactions:
        if transaction.sub_id is None and transaction.transaction_identifier is None:
            raise ValueError("upsert_transaction requires at least one idempotency key")

    if _has_duplicate_transaction_idempotency_keys(
        normalized_transactions
    ) or _has_existing_dual_key_filing_identifier_conflict(conn, normalized_transactions):
        return [upsert_transaction_with_status(conn, transaction) for transaction in normalized_transactions]

    results_by_sub_id: dict[int, TransactionUpsertResult] = {}
    results_by_filing_identifier: dict[tuple[UUID, str], TransactionUpsertResult] = {}

    sub_id_transactions = [transaction for transaction in normalized_transactions if transaction.sub_id is not None]
    if sub_id_transactions:
        for (
            transaction_id,
            inserted,
            sub_id,
            _filing_id,
            _transaction_identifier,
        ) in _bulk_upsert_transactions_for_conflict_target(
            conn,
            transactions=sub_id_transactions,
            conflict_mode="sub_id",
        ):
            if sub_id is None:
                raise RuntimeError("bulk sub_id upsert returned row without sub_id")
            results_by_sub_id[int(sub_id)] = TransactionUpsertResult(
                transaction_id=transaction_id,
                inserted=inserted,
            )

    identifier_transactions = [transaction for transaction in normalized_transactions if transaction.sub_id is None]
    if identifier_transactions:
        for (
            transaction_id,
            inserted,
            _sub_id,
            filing_id,
            transaction_identifier,
        ) in _bulk_upsert_transactions_for_conflict_target(
            conn,
            transactions=identifier_transactions,
            conflict_mode="filing_identifier",
        ):
            if transaction_identifier is None:
                raise RuntimeError("bulk filing+identifier upsert returned row without transaction_identifier")
            results_by_filing_identifier[(filing_id, transaction_identifier)] = TransactionUpsertResult(
                transaction_id=transaction_id,
                inserted=inserted,
            )

    results: list[TransactionUpsertResult] = []
    for transaction in normalized_transactions:
        if transaction.sub_id is not None:
            results.append(results_by_sub_id[transaction.sub_id])
            continue
        if transaction.transaction_identifier is None:
            raise RuntimeError("validated transaction unexpectedly lost its idempotency key")
        results.append(results_by_filing_identifier[(transaction.filing_id, transaction.transaction_identifier)])
    return results


__all__ = [
    "upsert_filings_bulk",
    "upsert_transactions_with_status_bulk",
]
