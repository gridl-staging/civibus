
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

from core.db import insert_entity_address, insert_entity_source, try_insert_data_source
from core.types.python.models import DataSource

_RowT = TypeVar("_RowT")

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical LoadResult — shared by all 6-field state loaders
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LoadResult:
    inserted: int
    skipped: int
    quarantined: int
    superseded: int
    errors: int
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Data-source lookup / upsert helpers
# ---------------------------------------------------------------------------


def select_data_source_id(
    conn: psycopg.Connection,
    domain: str,
    jurisdiction: str | None,
    name: str,
) -> UUID | None:
    """Look up a data source by (domain, jurisdiction, name) and return its UUID, or None."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction IS NOT DISTINCT FROM %s
              AND name = %s
            LIMIT 1
            """,
            (domain, jurisdiction, name),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def ensure_data_source(conn: psycopg.Connection, data_source: DataSource) -> UUID:
    existing_id = select_data_source_id(conn, data_source.domain, data_source.jurisdiction, data_source.name)
    if existing_id is not None:
        return existing_id

    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id

    # Concurrent insert won the race — the row must exist now.
    existing_id = select_data_source_id(conn, data_source.domain, data_source.jurisdiction, data_source.name)
    if existing_id is not None:
        return existing_id

    raise RuntimeError(f"{data_source.name} insert reported a conflict, but the existing row could not be selected")


def ensure_transaction_open(conn: psycopg.Connection) -> None:
    if conn.info.transaction_status == TransactionStatus.IDLE:
        conn.execute("BEGIN")


def commit_managed_transaction(
    conn: psycopg.Connection,
    manages_outer_transaction: bool,
) -> None:
    if manages_outer_transaction and conn.info.transaction_status != TransactionStatus.IDLE:
        conn.commit()


def validated_limit(limit: int | None) -> int | None:
    if limit is not None and limit < 0:
        raise ValueError("limit must be greater than or equal to 0")
    return limit


def iter_rows_with_limit(rows: Iterable[_RowT], limit: int | None) -> Iterator[_RowT]:
    row_limit = validated_limit(limit)

    for index, row in enumerate(rows, start=1):
        if row_limit is not None and index > row_limit:
            break
        yield row


def try_row_without_savepoint(
    conn: psycopg.Connection,
    row_callable: Callable[[], _RowT],
    *,
    manages_outer_transaction: bool,
    label: str = "row",
) -> tuple[_RowT | None, bool]:
    """Execute a row-level load operation WITHOUT per-row savepoints.

    Per-row savepoints (conn.transaction()) each consume a shared lock table
    entry in PostgreSQL. At 500K rows this exhausts max_locks_per_transaction.
    This utility avoids savepoints entirely for the happy path.

    On Python-level errors (extraction, validation): logs and returns (None, False).
    The transaction is NOT broken — the caller can continue.

    On DB-level errors (psycopg.Error): the transaction is in error state.
    Rolls back, re-opens if we manage the transaction, and returns (None, True).
    The caller should account for losing uncommitted rows in the current batch.

    Returns:
        (result, was_db_error) — result is None on failure, bool flag indicates
        whether the failure was a DB error that caused a transaction rollback.
    """
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        return row_callable(), False
    except psycopg.Error:
        # DB error — transaction is now in error state. Must rollback.
        LOGGER.exception("DB error loading %s — rolling back current batch", label)
        conn.rollback()
        return None, True
    except Exception:  # noqa: BLE001
        # Python-level error (extraction, validation). Transaction still valid.
        LOGGER.exception("Failed loading %s", label)
        return None, False


def link_entity_source_and_optional_mailing_address(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_id: UUID,
    source_record_id: UUID,
    extraction_role: str,
    address_id: UUID | None,
) -> None:
    insert_entity_source(conn, entity_type, entity_id, source_record_id, extraction_role)
    if address_id is not None:
        insert_entity_address(conn, entity_type, entity_id, address_id, source_record_id, "mailing")
