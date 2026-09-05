"""Transaction-boundary orchestration for WA's relational loader pass."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

import psycopg

from domains.campaign_finance.jurisdictions.states.load_utils import (
    commit_managed_transaction,
    ensure_transaction_open,
)

from .ie_record_classes import _WATransactionDispatch, _resolve_wa_ie_record_class
from .load_support import WAIdentityAmbiguityError

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class WALoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(slots=True)
class WASourceRecordKeyLedger:
    """Source-record outcomes that determine whether the relational pass may link a key.

    A rejected key is blocked only until a byte-identical row persists it during the
    same source-record pass. Keeping both outcomes together prevents the relational pass
    from double-counting a failed attempt or dropping content that ultimately landed.
    """

    rejected_attempts: Counter[str] = field(default_factory=Counter)
    persisted: set[str] = field(default_factory=set)

    def blocks_relational_link(self, record_hash: str) -> bool:
        """Return whether every attempt for this exact row content failed."""
        return record_hash in self.rejected_attempts and record_hash not in self.persisted

    def rejected_attempts_for_persisted_keys(self) -> int:
        """Count failed attempts whose content another row successfully persisted."""
        return sum(self.rejected_attempts[record_hash] for record_hash in self.persisted)


@dataclass(frozen=True, slots=True)
class WAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


@dataclass(frozen=True, slots=True)
class WARelationalOperations:
    """WA loader-owned operations invoked by the relational pass coordinator."""

    source_record_key: Callable[[Mapping[str, str | None]], str]
    record_hash: Callable[[Mapping[str, str | None]], str]
    filing_identity: Callable[[Mapping[str, str | None]], str]
    select_source_record_id: Callable[..., UUID | None]
    remove_source_only_claim: Callable[..., None]
    upsert_filing: Callable[..., WAFilingLookupEntry]
    upsert_transaction: Callable[..., None]
    evict_rolled_back_filing: Callable[..., None]


@dataclass(frozen=True, slots=True)
class WARelationalPassSettings:
    data_source_id: UUID
    data_type: str
    limit: int | None
    commit_batch_rows: int
    key_ledger: WASourceRecordKeyLedger | None
    operations: WARelationalOperations


@dataclass(frozen=True, slots=True)
class _WARelationalPassContext:
    settings: WARelationalPassSettings
    filing_lookup: dict[str, WAFilingLookupEntry]
    manages_outer_transaction: bool


def _link_wa_relational_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    context: _WARelationalPassContext,
    counts: WALoadCounts,
) -> None:
    """Link one persisted WA source record, returning normally for every row outcome."""
    settings = context.settings
    operations = settings.operations
    row_hash = operations.record_hash(row)
    if settings.key_ledger is not None and settings.key_ledger.blocks_relational_link(row_hash):
        return

    # The source-record lookup and record-class resolution run inside the per-row try so
    # an unknown/empty origin (or a lookup failure) still raises loudly but is counted as
    # one row error and logged, rather than aborting the whole relational pass and
    # skipping the terminal commit that persists already-linked rows. The lookup runs
    # first because this pass only links rows that pass already persisted.
    record_class: _WATransactionDispatch | None = None
    try:
        row_key = operations.source_record_key(row)
        source_record_id = operations.select_source_record_id(
            conn,
            data_source_id=settings.data_source_id,
            source_record_key=row_key,
            record_hash=row_hash,
        )
        if source_record_id is None:
            return

        record_class = _resolve_wa_ie_record_class(row, settings.data_type)
        if record_class is not None and not record_class.lands_transaction:
            if context.manages_outer_transaction:
                ensure_transaction_open(conn)
            with conn.transaction():
                operations.remove_source_only_claim(
                    conn,
                    data_source_id=settings.data_source_id,
                    source_record_key=row_key,
                    data_type=settings.data_type,
                )
            counts.skipped += 1
            return

        try:
            operations.filing_identity(row)
        except ValueError:
            if context.manages_outer_transaction:
                ensure_transaction_open(conn)
            with conn.transaction():
                operations.remove_source_only_claim(
                    conn,
                    data_source_id=settings.data_source_id,
                    source_record_key=row_key,
                    data_type=settings.data_type,
                )
            raise

        if context.manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            filing_entry = operations.upsert_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_source_id=settings.data_source_id,
                data_type=settings.data_type,
                filing_lookup=context.filing_lookup,
                record_class=record_class,
            )
            operations.upsert_transaction(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
                data_source_id=settings.data_source_id,
                data_type=settings.data_type,
                record_class=record_class,
            )
    except WAIdentityAmbiguityError:
        raise
    except Exception:  # noqa: BLE001
        operations.evict_rolled_back_filing(
            context.filing_lookup,
            row,
            settings.data_type,
            record_class,
        )
        counts.errors += 1
        LOGGER.exception("Failed linking WA %s row to filing", settings.data_type.rstrip("s"))


def load_wa_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    settings: WARelationalPassSettings,
) -> WALoadCounts:
    """Link WA rows and commit each complete batch, including skipped and errored rows.

    Owns what the returned counts mean. ``errors`` counts rows that raised while linking
    and ``skipped`` counts rows whose resolved IE record class does not land a transaction
    (``lands_transaction is False``, today only ``C6.5``). ``inserted`` stays zero: this
    pass links rows the source-record pass already counted as inserted. The caller folds
    ``errors`` and ``skipped`` into that pass's ``LoadResult``, so ``LoadResult.skipped``
    carries three causes — source-pass dedupe skips, failed source-pass attempts whose
    content a duplicate row persisted, and non-landing record-class skips.

    ``settings.key_ledger`` holds what the source-record pass rejected and what it
    persisted, as :class:`WASourceRecordKeyLedger` describes; a row it rejected and
    nothing persisted is skipped here rather than counted twice. Rows with no source
    record at all are likewise skipped, so calling this standalone surfaces an unknown
    origin only for rows a previous load did persist.
    """
    context = _WARelationalPassContext(
        settings=settings,
        filing_lookup={},
        manages_outer_transaction=conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE,
    )
    counts = WALoadCounts()
    processed_count = 0

    try:
        for index, row in enumerate(rows, start=1):
            if settings.limit is not None and index > settings.limit:
                break
            if not isinstance(row, Mapping):
                raise TypeError(f"Expected mapping row, got {type(row)!r}")

            _link_wa_relational_row(conn, row, context=context, counts=counts)
            processed_count += 1
            if processed_count % settings.commit_batch_rows == 0:
                commit_managed_transaction(conn, context.manages_outer_transaction)
    except WAIdentityAmbiguityError:
        if context.manages_outer_transaction:
            conn.rollback()
        raise

    commit_managed_transaction(conn, context.manages_outer_transaction)
    return counts
