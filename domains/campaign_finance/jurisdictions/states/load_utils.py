from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, TypeVar
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


@dataclass(slots=True)
class RelationalLoadCounts:
    """Row outcomes a no-savepoint relational loop can actually observe.

    Deliberately narrower than :class:`LoadResult`: the loop cannot know
    ``quarantined``, ``superseded``, or ``elapsed_seconds``, so it must not
    invent zeros for them and become a second source of truth for load totals.
    Callers map these counts into whatever result type they own.
    """

    inserted: int = 0
    skipped: int = 0
    errors: int = 0


# ---------------------------------------------------------------------------
# Data-source lookup / upsert helpers
# ---------------------------------------------------------------------------


def select_data_source_id(
    conn: psycopg.Connection,
    domain: str,
    jurisdiction: str | None,
    name: str,
    *,
    filing_authority_type: str | None = None,
    filing_authority_code: str | None = None,
) -> UUID | None:
    """Look up a data source by typed authority/source identity."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND filing_authority_type IS NOT DISTINCT FROM %s
              AND filing_authority_code IS NOT DISTINCT FROM %s
              AND name = %s
            LIMIT 1
            """,
            (domain, filing_authority_type, filing_authority_code, name),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def reconcile_existing_data_source(conn: psycopg.Connection, data_source_id: UUID, data_source: DataSource) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.data_source
            SET source_url = %s::text,
                source_format = COALESCE(%s::text, source_format),
                license = COALESCE(%s::text, license),
                update_frequency = COALESCE(%s::text, update_frequency),
                notes = COALESCE(%s::text, notes),
                updated_at = NOW()
            WHERE id = %s
              AND (
                  source_url IS DISTINCT FROM %s::text
                  OR (%s::text IS NOT NULL AND source_format IS DISTINCT FROM %s::text)
                  OR (%s::text IS NOT NULL AND license IS DISTINCT FROM %s::text)
                  OR (%s::text IS NOT NULL AND update_frequency IS DISTINCT FROM %s::text)
                  OR (%s::text IS NOT NULL AND notes IS DISTINCT FROM %s::text)
              )
            """,
            (
                data_source.source_url,
                data_source.source_format,
                data_source.license,
                data_source.update_frequency,
                data_source.notes,
                data_source_id,
                data_source.source_url,
                data_source.source_format,
                data_source.source_format,
                data_source.license,
                data_source.license,
                data_source.update_frequency,
                data_source.update_frequency,
                data_source.notes,
                data_source.notes,
            ),
        )


def ensure_data_source(conn: psycopg.Connection, data_source: DataSource) -> UUID:
    existing_id = select_data_source_id(
        conn,
        data_source.domain,
        data_source.jurisdiction,
        data_source.name,
        filing_authority_type=data_source.filing_authority_type,
        filing_authority_code=data_source.filing_authority_code,
    )
    if existing_id is not None:
        reconcile_existing_data_source(conn, existing_id, data_source)
        return existing_id

    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id

    # Concurrent insert won the race — the row must exist now.
    existing_id = select_data_source_id(
        conn,
        data_source.domain,
        data_source.jurisdiction,
        data_source.name,
        filing_authority_type=data_source.filing_authority_type,
        filing_authority_code=data_source.filing_authority_code,
    )
    if existing_id is not None:
        reconcile_existing_data_source(conn, existing_id, data_source)
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
    fatal_exceptions: tuple[type[BaseException], ...] = (),
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

    Types listed in ``fatal_exceptions`` are re-raised untouched ahead of both
    handlers, so a jurisdiction's typed drift error aborts the load instead of
    being logged and counted as an ordinary row failure. An empty tuple (the
    default) never matches, leaving existing callers unchanged.

    Returns:
        (result, was_db_error) — result is None on failure, bool flag indicates
        whether the failure was a DB error that caused a transaction rollback.
    """
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        return row_callable(), False
    except fatal_exceptions:
        # Typed fatal drift: escapes untouched, ahead of both handlers below.
        raise
    except psycopg.Error:
        # DB error — transaction is now in error state. Must rollback.
        LOGGER.exception("DB error loading %s — rolling back current batch", label)
        conn.rollback()
        return None, True
    except Exception:  # noqa: BLE001
        # Python-level error (extraction, validation). Transaction still valid.
        LOGGER.exception("Failed loading %s", label)
        return None, False


def _resolve_and_link_relational_row(
    conn: psycopg.Connection,
    row: Mapping[str, Any],
    *,
    source_record_key_for_row: Callable[[Mapping[str, Any]], Any],
    resolve_source_record_id: Callable[[psycopg.Connection, Any], UUID | None],
    link_row: Callable[[psycopg.Connection, Mapping[str, Any], UUID], Any],
) -> bool:
    """Return True when the row linked, False when it was skipped.

    Skipping covers both a missing source record and a link callback that
    declined the row. Failures propagate so try_row_without_savepoint() can
    classify them.
    """
    source_record_id = resolve_source_record_id(conn, source_record_key_for_row(row))
    if source_record_id is None:
        return False
    return bool(link_row(conn, row, source_record_id))


def load_relational_rows_without_savepoints(  # noqa: PLR0913 - hook seam pinned by the IN/TX delegation contract
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, Any]],
    *,
    source_record_key_for_row: Callable[[Mapping[str, Any]], Any],
    resolve_source_record_id: Callable[[psycopg.Connection, Any], UUID | None],
    link_row: Callable[[psycopg.Connection, Mapping[str, Any], UUID], Any],
    batch_size: int,
    label: str = "row",
    fatal_exceptions: tuple[type[BaseException], ...] = (),
    on_db_error_recovery: Callable[..., None] | None = None,
    on_managed_commit_reset: Callable[..., None] | None = None,
    caller_owned_rollback_error: Callable[..., BaseException] | None = None,
) -> RelationalLoadCounts:
    """Iterate relational rows without per-row savepoints, owning only transaction cadence.

    This is the single owner of batch/terminal commit cadence, lost-success
    accounting after a database rollback, typed fatal passthrough, and the
    caller-owned rollback failure. Source-key construction, source-record
    lookup, row linking, row limiting, and jurisdiction recovery policy stay
    with the caller, supplied through the callbacks and hooks above.

    Ownership of the transaction is decided once from the entry status: an
    already-open transaction belongs to the caller and is never begun,
    committed, or reset here.
    """
    manages_outer_transaction = conn.info.transaction_status == TransactionStatus.IDLE
    counts = RelationalLoadCounts()
    processed_count = 0
    since_commit_inserted = 0

    def _commit_managed_batch(reason: str) -> None:
        """Commit a managed batch, then notify — only when a commit really happened."""
        nonlocal since_commit_inserted
        if not manages_outer_transaction or conn.info.transaction_status == TransactionStatus.IDLE:
            return
        commit_managed_transaction(conn, manages_outer_transaction)
        since_commit_inserted = 0
        if on_managed_commit_reset is not None:
            on_managed_commit_reset(processed_count=processed_count, reason=reason)

    def _recover_from_managed_rollback(failed_row: Mapping[str, Any]) -> None:
        """Re-open jurisdiction state, then charge the batch's lost successes as errors."""
        nonlocal since_commit_inserted
        if on_db_error_recovery is not None:
            on_db_error_recovery(conn, failed_row=failed_row)
        counts.inserted -= since_commit_inserted
        counts.errors += since_commit_inserted + 1
        since_commit_inserted = 0

    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError(f"{label} must be a mapping, got {type(row).__name__}")

        # Every yielded row advances the batch position, so a skipped or failed row
        # at position 1,000 reaches the boundary commit exactly like a success does.
        processed_count += 1
        linked, was_db_error = try_row_without_savepoint(
            conn,
            partial(
                _resolve_and_link_relational_row,
                conn,
                row,
                source_record_key_for_row=source_record_key_for_row,
                resolve_source_record_id=resolve_source_record_id,
                link_row=link_row,
            ),
            manages_outer_transaction=manages_outer_transaction,
            label=label,
            fatal_exceptions=fatal_exceptions,
        )

        if was_db_error:
            if not manages_outer_transaction:
                raise _caller_owned_rollback_failure(caller_owned_rollback_error, failed_row=row, label=label)
            _recover_from_managed_rollback(row)
            continue
        if linked is None:
            counts.errors += 1
        elif linked:
            counts.inserted += 1
            since_commit_inserted += 1
        else:
            counts.skipped += 1

        if processed_count % batch_size == 0:
            _commit_managed_batch("batch_boundary")

    _commit_managed_batch("terminal")
    return counts


def _caller_owned_rollback_failure(
    caller_owned_rollback_error: Callable[..., BaseException] | None,
    *,
    failed_row: Mapping[str, Any],
    label: str,
) -> BaseException:
    """Build the abort raised when a DB error rolled back a transaction we do not own.

    The caller's uncommitted work is already gone, so this path always fails
    loud rather than continuing with the next row.
    """
    if caller_owned_rollback_error is not None:
        return caller_owned_rollback_error(failed_row=failed_row)
    return RuntimeError(f"{label} DB error rolled back the caller-owned transaction; aborting load")


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
