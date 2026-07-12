"""Stage 4 loaders for filtered FEC transaction ingest."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
import functools
from hashlib import sha256
import logging
from pathlib import Path
from typing import Literal
from uuid import UUID
from zipfile import ZipFile

import psycopg

from core.db import try_insert_source_record, try_insert_source_records_bulk
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.bulk_parser import _find_matching_txt_member, read_bulk_file
from domains.campaign_finance.ingest.bulk_transaction_loader import (
    build_filing_from_contribution,
    build_transaction_from_contribution,
    resolve_source_record_id,
    resolve_source_record_ids,
)
from domains.campaign_finance.ingest.fec_lookup import (
    current_federal_officeholder_committee_fec_ids,
    find_committee_id_by_fec_id,
    find_committee_ids_by_fec_ids,
)
from domains.campaign_finance.ingest.field_mapper import map_contribution_fields
from domains.campaign_finance.ingest.filing_loader import (
    upsert_filing,
    upsert_filings_bulk,
    upsert_transaction_with_status,
    upsert_transactions_with_status_bulk,
)
from domains.campaign_finance.ingest.loader import load_contribution
from domains.campaign_finance.ingest.text_utils import normalize_optional_text

LOGGER = logging.getLogger(__name__)

_STAGE4_ROW_SAVEPOINT = "stage4_row"
_STAGE4_BATCH_SAVEPOINT = "stage4_batch"
_DEFAULT_STAGE4_CYCLE = 0
_MIN_STAGE4_TRANSACTIONS_BATCH_ROWS = 2_000
STAGE4_RESUME_IDENTITY_COLUMNS: tuple[str, str, str] = ("data_source_id", "cycle", "file_type")
_LEGACY_STAGE4_OPTION_KEYS = frozenset(
    {
        "batch_size",
        "limit",
        "graph_enabled",
        "with_transactions",
        "entity_extraction",
        "committee_fec_ids",
        "min_transaction_date",
        "count_only",
        "canonical_resume_enabled",
    }
)


@dataclass(slots=True)
class LoadResult:
    inserted: int = 0
    skipped: int = 0
    quarantined: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class Stage4LoadOptions:

    batch_size: int = 1000
    limit: int | None = None
    graph_enabled: bool = False
    with_transactions: bool = False
    entity_extraction: bool = True
    committee_fec_ids: frozenset[str] | None = None
    min_transaction_date: date | None = None
    count_only: bool = False
    canonical_resume_enabled: bool = False

    @property
    def has_full_source_row_scope(self) -> bool:
        return (
            self.limit is None
            and self.committee_fec_ids is None
            and self.min_transaction_date is None
            and not self.count_only
        )

    @property
    def checkpoint_mode_key(self) -> str:
        return "|".join(
            (
                "entity-extraction" if self.entity_extraction else "provenance-only",
                "with-transactions" if self.with_transactions else "without-transactions",
                "graph-enabled" if self.graph_enabled else "graph-disabled",
            )
        )

    @property
    def uses_legacy_checkpoint_fingerprint(self) -> bool:
        return self.entity_extraction and not self.with_transactions and not self.graph_enabled


@dataclass(frozen=True, slots=True)
class Stage4ResumeIdentity:
    data_source_id: UUID
    cycle: int
    file_type: Literal["itcont", "itpas2"]

    def as_key_tuple(self) -> tuple[UUID, int, Literal["itcont", "itpas2"]]:
        return (self.data_source_id, self.cycle, self.file_type)

    @property
    def checkpoint_enabled(self) -> bool:
        return self.file_type == "itcont" and self.cycle != _DEFAULT_STAGE4_CYCLE


@dataclass(frozen=True, slots=True)
class Stage4ResumeCheckpoint:

    resume_identity: Stage4ResumeIdentity
    archive_fingerprint: str
    archive_member_name: str | None
    next_source_row_number: int
    checkpoint_mode_key: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.next_source_row_number < 0:
            raise ValueError("next_source_row_number must be >= 0")

    def stored_archive_fingerprint(self) -> str:
        if self.checkpoint_mode_key is None:
            return self.archive_fingerprint
        return f"{self.archive_fingerprint}|mode={self.checkpoint_mode_key}"

    @classmethod
    def parse_stored_archive_fingerprint(cls, stored_archive_fingerprint: str) -> tuple[str, str | None]:
        archive_fingerprint, separator, checkpoint_mode_key = stored_archive_fingerprint.partition("|mode=")
        if separator == "":
            return stored_archive_fingerprint, None
        return archive_fingerprint, checkpoint_mode_key or None


@dataclass(frozen=True, slots=True)
class Stage4ArchiveReference:
    archive_fingerprint: str
    archive_member_name: str | None


@dataclass(frozen=True, slots=True)
class _Stage4ResumeResolution:
    start_row: int
    checkpoint_rewritten: bool = False


@dataclass(frozen=True, slots=True)
class _Stage4CheckpointContext:
    archive_reference: Stage4ArchiveReference
    start_row: int


@dataclass(frozen=True, slots=True)
class Stage4LoadRequest:

    file_type: Literal["itcont", "itpas2"]
    path: str | Path
    data_source_id: UUID
    cycle: int = _DEFAULT_STAGE4_CYCLE
    options: Stage4LoadOptions = field(default_factory=Stage4LoadOptions)
    canonical_resume_enabled: bool = False

    @property
    def resume_identity(self) -> Stage4ResumeIdentity:
        return build_stage4_resume_identity(
            data_source_id=self.data_source_id,
            cycle=self.cycle,
            file_type=self.file_type,
        )

    @property
    def checkpoint_enabled(self) -> bool:
        return (
            self.canonical_resume_enabled
            and self.resume_identity.checkpoint_enabled
            and self.options.has_full_source_row_scope
        )

    def checkpoint_archive_fingerprint(self, archive_fingerprint: str) -> str:
        return archive_fingerprint


def build_stage4_resume_identity(
    *,
    data_source_id: UUID,
    cycle: int | str,
    file_type: Literal["itcont", "itpas2"],
) -> Stage4ResumeIdentity:
    return Stage4ResumeIdentity(data_source_id=data_source_id, cycle=int(cycle), file_type=file_type)


@dataclass(frozen=True, slots=True)
class _PendingStage4Row:
    source_record_key: str
    contribution_record: dict[str, object]
    processed_row_number: int


@dataclass(frozen=True, slots=True)
class _MappedStage4Row:
    source_record_key: str
    committee_fec_id: str
    contribution_record: dict[str, object]


@dataclass(slots=True)
class _Stage4StreamingState:

    load_result: LoadResult = field(default_factory=LoadResult)
    processed_rows: int = 0
    selected_rows: int = 0
    processed_since_commit: int = 0
    checkpoint_ready_rows: int = 0
    checkpoint_written_rows: int = 0
    checkpoint_blocked: bool = False
    pending_rows: list[_PendingStage4Row] = field(default_factory=list)

    def record_checkpoint_outcome(self, processed_row_number: int, *, source_row_committable: bool) -> None:
        if self.checkpoint_blocked:
            return
        if source_row_committable and processed_row_number == self.checkpoint_ready_rows + 1:
            self.checkpoint_ready_rows = processed_row_number
            return
        self.checkpoint_blocked = True


@dataclass(frozen=True, slots=True)
class _Stage4RowLoadOutcome:
    source_row_committable: bool


@dataclass(frozen=True, slots=True)
class _Stage4BatchLoadResult:
    row_outcomes: tuple[_Stage4RowLoadOutcome, ...]

    @classmethod
    def empty(cls) -> _Stage4BatchLoadResult:
        return cls(row_outcomes=())


def _validate_batch_size(batch_size: int) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")


def _commit_batch(conn: psycopg.Connection, processed_since_commit: int, batch_size: int) -> int:
    if processed_since_commit >= batch_size:
        conn.commit()
        return 0
    return processed_since_commit


def _commit_final_batch(conn: psycopg.Connection, processed_since_commit: int) -> None:
    if processed_since_commit > 0:
        conn.commit()


_normalize_optional_text = normalize_optional_text


def _resolve_stage4_options(
    options: Stage4LoadOptions | None,
    legacy_kwargs: dict[str, object],
) -> Stage4LoadOptions:
    unexpected_keys = set(legacy_kwargs) - _LEGACY_STAGE4_OPTION_KEYS
    if unexpected_keys:
        unexpected_key_list = ", ".join(sorted(unexpected_keys))
        raise TypeError(f"Unexpected Stage 4 loader options: {unexpected_key_list}")

    if options is not None and legacy_kwargs:
        raise TypeError("Use either options=Stage4LoadOptions(...) or legacy Stage 4 kwargs, not both")

    if options is not None:
        return options

    return Stage4LoadOptions(
        batch_size=int(legacy_kwargs.get("batch_size", 1000)),
        limit=legacy_kwargs.get("limit"),
        graph_enabled=bool(legacy_kwargs.get("graph_enabled", False)),
        with_transactions=bool(legacy_kwargs.get("with_transactions", False)),
        entity_extraction=bool(legacy_kwargs.get("entity_extraction", True)),
        committee_fec_ids=legacy_kwargs.get("committee_fec_ids"),
        min_transaction_date=legacy_kwargs.get("min_transaction_date"),
        count_only=bool(legacy_kwargs.get("count_only", False)),
        canonical_resume_enabled=bool(legacy_kwargs.get("canonical_resume_enabled", False)),
    )


def _build_stage4_request(
    *,
    file_type: Literal["itcont", "itpas2"],
    path: str | Path,
    cycle: int | str,
    data_source_id: UUID,
    options: Stage4LoadOptions | None,
    legacy_kwargs: dict[str, object],
    canonical_resume_enabled: bool = False,
) -> Stage4LoadRequest:
    resolved_options = _resolve_stage4_options(options, legacy_kwargs)
    return Stage4LoadRequest(
        file_type=file_type,
        path=path,
        data_source_id=data_source_id,
        cycle=int(cycle),
        options=resolved_options,
        canonical_resume_enabled=(canonical_resume_enabled or resolved_options.canonical_resume_enabled),
    )


def _row_value(row: object, column_name: str, column_index: int) -> object:
    if isinstance(row, dict):
        return row[column_name]
    return row[column_index]  # type: ignore[index]


def _select_stage4_resume_checkpoint(
    conn: psycopg.Connection,
    resume_identity: Stage4ResumeIdentity,
) -> Stage4ResumeCheckpoint | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT archive_fingerprint,
                   archive_member_name,
                   next_source_row_number
            FROM cf.stage4_resume_checkpoint
            WHERE data_source_id = %s
              AND cycle = %s
              AND file_type = %s
            """,
            resume_identity.as_key_tuple(),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    archive_fingerprint, checkpoint_mode_key = Stage4ResumeCheckpoint.parse_stored_archive_fingerprint(
        str(_row_value(row, "archive_fingerprint", 0))
    )

    return Stage4ResumeCheckpoint(
        resume_identity=resume_identity,
        archive_fingerprint=archive_fingerprint,
        archive_member_name=_stage4_optional_text(_row_value(row, "archive_member_name", 1)),
        next_source_row_number=int(_row_value(row, "next_source_row_number", 2)),
        checkpoint_mode_key=checkpoint_mode_key,
    )


def _write_stage4_resume_checkpoint(
    conn: psycopg.Connection,
    checkpoint: Stage4ResumeCheckpoint,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.stage4_resume_checkpoint (
                data_source_id,
                cycle,
                file_type,
                archive_fingerprint,
                archive_member_name,
                next_source_row_number
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (data_source_id, cycle, file_type)
            DO UPDATE SET
                archive_fingerprint = EXCLUDED.archive_fingerprint,
                archive_member_name = EXCLUDED.archive_member_name,
                next_source_row_number = EXCLUDED.next_source_row_number,
                updated_at = NOW()
            """,
            (
                *checkpoint.resume_identity.as_key_tuple(),
                checkpoint.stored_archive_fingerprint(),
                checkpoint.archive_member_name,
                checkpoint.next_source_row_number,
            ),
        )


def _stage4_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _resolve_stage4_resume_checkpoint(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    archive_fingerprint: str,
    archive_member_name: str | None,
) -> _Stage4ResumeResolution:
    resume_identity = request.resume_identity
    if not request.checkpoint_enabled:
        return _Stage4ResumeResolution(start_row=0)

    checkpoint = _select_stage4_resume_checkpoint(conn, resume_identity)
    if checkpoint is None:
        return _Stage4ResumeResolution(start_row=0)

    checkpoint_mode_matches = checkpoint.checkpoint_mode_key == request.options.checkpoint_mode_key or (
        checkpoint.checkpoint_mode_key is None and request.options.uses_legacy_checkpoint_fingerprint
    )
    if (
        checkpoint.archive_fingerprint == request.checkpoint_archive_fingerprint(archive_fingerprint)
        and checkpoint.archive_member_name == archive_member_name
        and checkpoint_mode_matches
    ):
        return _Stage4ResumeResolution(start_row=checkpoint.next_source_row_number)

    _write_stage4_resume_checkpoint(
        conn,
        Stage4ResumeCheckpoint(
            resume_identity=resume_identity,
            archive_fingerprint=request.checkpoint_archive_fingerprint(archive_fingerprint),
            archive_member_name=archive_member_name,
            next_source_row_number=0,
            checkpoint_mode_key=request.options.checkpoint_mode_key,
        ),
    )
    return _Stage4ResumeResolution(start_row=0, checkpoint_rewritten=True)


def _resolve_stage4_resume_start_row(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    archive_fingerprint: str,
    archive_member_name: str | None,
) -> int:
    return _resolve_stage4_resume_checkpoint(
        conn,
        request=request,
        archive_fingerprint=archive_fingerprint,
        archive_member_name=archive_member_name,
    ).start_row


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_stage4_archive_reference(path: str | Path, file_type: Literal["itcont", "itpas2"]) -> Stage4ArchiveReference:
    file_path = Path(path)
    if file_path.suffix.lower() == ".zip":
        member_name = _find_matching_txt_member(file_path, file_type)
        with ZipFile(file_path) as archive:
            member_info = archive.getinfo(member_name)
        fingerprint_input = f"zip:{member_name}:{member_info.CRC}:{member_info.file_size}"
        return Stage4ArchiveReference(
            archive_fingerprint=sha256(fingerprint_input.encode("utf-8")).hexdigest(),
            archive_member_name=member_name,
        )

    return Stage4ArchiveReference(
        archive_fingerprint=_sha256_file(file_path),
        archive_member_name=None,
    )


def _write_stage4_checkpoint_for_processed_rows(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    checkpoint_context: _Stage4CheckpointContext,
    processed_rows: int,
) -> None:
    _write_stage4_resume_checkpoint(
        conn,
        Stage4ResumeCheckpoint(
            resume_identity=request.resume_identity,
            archive_fingerprint=request.checkpoint_archive_fingerprint(
                checkpoint_context.archive_reference.archive_fingerprint
            ),
            archive_member_name=checkpoint_context.archive_reference.archive_member_name,
            next_source_row_number=checkpoint_context.start_row + processed_rows,
            checkpoint_mode_key=request.options.checkpoint_mode_key,
        ),
    )


def _commit_stage4_batch_progress(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
    checkpoint_context: _Stage4CheckpointContext | None,
) -> None:
    if state.processed_since_commit < _stage4_flush_row_threshold(request):
        return
    checkpoint_rows = state.checkpoint_ready_rows
    should_write_checkpoint = checkpoint_context is not None and checkpoint_rows > state.checkpoint_written_rows
    if should_write_checkpoint:
        _write_stage4_checkpoint_for_processed_rows(
            conn,
            request=request,
            checkpoint_context=checkpoint_context,
            processed_rows=checkpoint_rows,
        )
    conn.commit()
    if should_write_checkpoint:
        state.checkpoint_written_rows = checkpoint_rows
    state.processed_since_commit = 0


def _commit_stage4_final_progress(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
    checkpoint_context: _Stage4CheckpointContext | None,
) -> bool:
    if state.processed_since_commit <= 0:
        return False
    checkpoint_rows = state.checkpoint_ready_rows
    should_write_checkpoint = checkpoint_context is not None and checkpoint_rows > state.checkpoint_written_rows
    if should_write_checkpoint:
        _write_stage4_checkpoint_for_processed_rows(
            conn,
            request=request,
            checkpoint_context=checkpoint_context,
            processed_rows=checkpoint_rows,
        )
    conn.commit()
    if should_write_checkpoint:
        state.checkpoint_written_rows = checkpoint_rows
    state.processed_since_commit = 0
    return True


def resolve_stage4_committee_scope(
    conn: psycopg.Connection,
    *,
    spine_only: bool,
) -> frozenset[str] | None:
    if not spine_only:
        return None
    return current_federal_officeholder_committee_fec_ids(conn)


def _build_stage4_source_record(
    data_source_id: UUID,
    contribution_record: dict[str, object],
) -> SourceRecord:
    source_record_key = contribution_record.get("sub_id")
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key if isinstance(source_record_key, str) else None,
        raw_fields=contribution_record,
        pull_date=utc_now(),
        record_hash=compute_record_hash(contribution_record),
    )


def _insert_stage4_provenance_only(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    contribution_record: dict[str, object],
) -> bool:
    source_record_id = try_insert_source_record(
        conn,
        _build_stage4_source_record(data_source_id, contribution_record),
    )
    return source_record_id is not None


def _passes_stage4_min_transaction_date(
    contribution_record: dict[str, object],
    *,
    min_transaction_date: date | None,
) -> bool:
    if min_transaction_date is None:
        return True

    raw_date = contribution_record.get("contribution_receipt_date")
    if raw_date is None:
        return False

    if not bool(contribution_record.get("contribution_receipt_date_is_reliable", True)):
        return False

    return date.fromisoformat(str(raw_date)) >= min_transaction_date


def _load_stage4_row_with_savepoint(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    source_record_key: str,
    contribution_record: dict[str, object],
) -> tuple[bool, bool]:
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
        try:
            if request.options.entity_extraction:
                inserted = load_contribution(
                    conn,
                    request.data_source_id,
                    contribution_record,
                    graph_enabled=request.options.graph_enabled,
                )
            else:
                inserted = _insert_stage4_provenance_only(
                    conn,
                    data_source_id=request.data_source_id,
                    contribution_record=contribution_record,
                )
            relational_inserted = False
            if request.options.with_transactions:
                relational_inserted = _load_stage4_relational_row(
                    conn,
                    data_source_id=request.data_source_id,
                    source_record_key=source_record_key,
                    contribution_record=contribution_record,
                    resolve_counterparty=request.options.entity_extraction,
                )
        except Exception:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
            cursor.execute(f"RELEASE SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
            raise
        cursor.execute(f"RELEASE SAVEPOINT {_STAGE4_ROW_SAVEPOINT}")
    return inserted, relational_inserted


def _load_stage4_relational_row(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    contribution_record: dict[str, object],
    resolve_counterparty: bool = True,
) -> bool:
    source_record_id = resolve_source_record_id(conn, data_source_id, source_record_key)
    if source_record_id is None:
        raise RuntimeError(
            f"source_record_id missing for data_source_id={data_source_id} source_record_key={source_record_key}"
        )

    filing = build_filing_from_contribution(
        conn,
        contribution_record,
        source_record_id=source_record_id,
    )
    filing_id = upsert_filing(conn, filing)

    transaction = build_transaction_from_contribution(
        conn,
        contribution_record,
        filing_id=filing_id,
        committee_id=filing.committee_id,
        source_record_id=source_record_id,
        resolve_counterparty=resolve_counterparty,
    )
    return upsert_transaction_with_status(conn, transaction).inserted


def _load_stage4_transactions_batch(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    load_result: LoadResult,
    rows: list[_PendingStage4Row],
) -> _Stage4BatchLoadResult:
    if not rows:
        return _Stage4BatchLoadResult.empty()

    committee_id_by_fec_id = find_committee_ids_by_fec_ids(
        conn,
        list(dict.fromkeys(str(row.contribution_record["committee_id"]) for row in rows)),
    )

    row_outcomes = [_Stage4RowLoadOutcome(source_row_committable=False) for _row in rows]
    resolved_rows: list[tuple[int, _PendingStage4Row, UUID]] = []
    for row_index, row in enumerate(rows):
        committee_fec_id = str(row.contribution_record["committee_id"])
        committee_id = committee_id_by_fec_id.get(committee_fec_id)
        if committee_id is None:
            load_result.errors += 1
            LOGGER.warning(
                "Skipping %s row with unresolved CMTE_ID=%s sub_id=%s; load committees before Stage 4",
                request.file_type,
                committee_fec_id,
                row.source_record_key,
            )
            continue
        resolved_rows.append((row_index, row, committee_id))

    if not resolved_rows:
        return _Stage4BatchLoadResult(row_outcomes=tuple(row_outcomes))

    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_STAGE4_BATCH_SAVEPOINT}")

    try:
        provenance_inserted_by_key: dict[str, bool] = {}
        source_record_keys = [row.source_record_key for _row_index, row, _committee_id in resolved_rows]
        source_records = [
            _build_stage4_source_record(request.data_source_id, row.contribution_record)
            for _row_index, row, _committee_id in resolved_rows
        ]
        provenance_results = try_insert_source_records_bulk(conn, source_records)
        for (_row_index, row, _committee_id), provenance_result in zip(
            resolved_rows,
            provenance_results,
            strict=True,
        ):
            provenance_inserted = provenance_result.inserted
            provenance_inserted_by_key[row.source_record_key] = provenance_inserted
        source_record_id_by_key = resolve_source_record_ids(conn, request.data_source_id, source_record_keys)

        filings = [
            build_filing_from_contribution(
                conn,
                row.contribution_record,
                committee_id=committee_id,
                source_record_id=source_record_id_by_key[row.source_record_key],
            )
            for _row_index, row, committee_id in resolved_rows
        ]
        filing_id_by_fec_id = upsert_filings_bulk(conn, filings)
        other_ids = list(
            dict.fromkeys(
                other_id
                for _row_index, row, _committee_id in resolved_rows
                if (other_id := _normalize_optional_text(row.contribution_record.get("other_id"))) is not None
            )
        )
        recipient_committee_id_by_fec_id = find_committee_ids_by_fec_ids(conn, other_ids) if other_ids else {}
        transactions = [
            build_transaction_from_contribution(
                conn,
                row.contribution_record,
                filing_id=filing_id_by_fec_id[filing.filing_fec_id],
                committee_id=committee_id,
                source_record_id=source_record_id_by_key[row.source_record_key],
                resolve_counterparty=request.options.entity_extraction,
                recipient_committee_id_by_fec_id=recipient_committee_id_by_fec_id,
            )
            for (_row_index, row, committee_id), filing in zip(resolved_rows, filings, strict=True)
        ]
        transaction_results = upsert_transactions_with_status_bulk(conn, transactions)
    except Exception:
        with conn.cursor() as cursor:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_STAGE4_BATCH_SAVEPOINT}")
            cursor.execute(f"RELEASE SAVEPOINT {_STAGE4_BATCH_SAVEPOINT}")

        return _replay_stage4_rows_after_batch_failure(
            conn,
            request=request,
            load_result=load_result,
            row_count=len(rows),
            resolved_rows=resolved_rows,
        )

    with conn.cursor() as cursor:
        cursor.execute(f"RELEASE SAVEPOINT {_STAGE4_BATCH_SAVEPOINT}")

    for (row_index, row, _committee_id), transaction_result in zip(resolved_rows, transaction_results, strict=True):
        durable_work = provenance_inserted_by_key[row.source_record_key] or transaction_result.inserted
        if durable_work:
            load_result.inserted += 1
        else:
            load_result.skipped += 1
        row_outcomes[row_index] = _Stage4RowLoadOutcome(
            source_row_committable=True,
        )
    return _Stage4BatchLoadResult(row_outcomes=tuple(row_outcomes))


def _replay_stage4_rows_after_batch_failure(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    load_result: LoadResult,
    row_count: int,
    resolved_rows: list[tuple[int, _PendingStage4Row, UUID]],
) -> _Stage4BatchLoadResult:
    row_outcomes = [_Stage4RowLoadOutcome(source_row_committable=False) for _row_index in range(row_count)]
    for row_index, row, _committee_id in resolved_rows:
        try:
            provenance_inserted, relational_inserted = _load_stage4_row_with_savepoint(
                conn,
                request=request,
                source_record_key=row.source_record_key,
                contribution_record=row.contribution_record,
            )
        except Exception:
            load_result.errors += 1
            LOGGER.warning(
                "Skipping %s row due to row-level load failure sub_id=%s cmte_id=%s",
                request.file_type,
                row.source_record_key,
                row.contribution_record["committee_id"],
                exc_info=True,
            )
        else:
            durable_work = provenance_inserted or relational_inserted
            if durable_work:
                load_result.inserted += 1
            else:
                load_result.skipped += 1
            row_outcomes[row_index] = _Stage4RowLoadOutcome(
                source_row_committable=True,
            )
    return _Stage4BatchLoadResult(row_outcomes=tuple(row_outcomes))


def _flush_stage4_pending_rows_if_needed(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    load_result: LoadResult,
    pending_rows: list[_PendingStage4Row],
    processed_since_commit: int,
) -> tuple[list[_PendingStage4Row], _Stage4BatchLoadResult]:
    if processed_since_commit < _stage4_flush_row_threshold(request):
        return pending_rows, _Stage4BatchLoadResult.empty()
    batch_result = _load_stage4_transactions_batch(
        conn,
        request=request,
        load_result=load_result,
        rows=pending_rows,
    )
    return [], batch_result


def _record_stage4_batch_checkpoint_outcomes(
    *,
    state: _Stage4StreamingState,
    rows: list[_PendingStage4Row],
    batch_result: _Stage4BatchLoadResult,
) -> None:
    if not batch_result.row_outcomes:
        return
    for row, outcome in zip(rows, batch_result.row_outcomes, strict=True):
        state.record_checkpoint_outcome(
            row.processed_row_number,
            source_row_committable=outcome.source_row_committable,
        )


def _log_stage4_progress(file_type: str, processed_rows: int, load_result: LoadResult) -> None:
    if processed_rows % 10000 == 0:
        LOGGER.info(
            "Processed %s %s rows (inserted=%s skipped=%s errors=%s)",
            processed_rows,
            file_type,
            load_result.inserted,
            load_result.skipped,
            load_result.errors,
        )


def _stage4_flush_row_threshold(request: Stage4LoadRequest) -> int:
    if (
        request.options.with_transactions
        and not request.options.entity_extraction
        and request.options.batch_size >= 1_000
    ):
        return max(request.options.batch_size, _MIN_STAGE4_TRANSACTIONS_BATCH_ROWS)
    return request.options.batch_size


def _finalize_stage4_iteration(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    load_result: LoadResult,
    pending_rows: list[_PendingStage4Row],
    processed_rows: int,
    processed_since_commit: int,
    state: _Stage4StreamingState | None = None,
    checkpoint_context: _Stage4CheckpointContext | None = None,
) -> tuple[list[_PendingStage4Row], int]:
    _log_stage4_progress(request.file_type, processed_rows, load_result)
    rows_before_flush = pending_rows
    pending_rows, batch_result = _flush_stage4_pending_rows_if_needed(
        conn,
        request=request,
        load_result=load_result,
        pending_rows=pending_rows,
        processed_since_commit=processed_since_commit,
    )
    if state is not None:
        _record_stage4_batch_checkpoint_outcomes(
            state=state,
            rows=rows_before_flush,
            batch_result=batch_result,
        )

    if state is None:
        processed_since_commit = _commit_batch(conn, processed_since_commit, _stage4_flush_row_threshold(request))
    else:
        _commit_stage4_batch_progress(
            conn,
            request=request,
            state=state,
            checkpoint_context=checkpoint_context,
        )
        processed_since_commit = state.processed_since_commit
    return pending_rows, processed_since_commit


def _finalize_stage4_state_iteration(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
    checkpoint_context: _Stage4CheckpointContext | None,
) -> None:
    state.pending_rows, state.processed_since_commit = _finalize_stage4_iteration(
        conn,
        request=request,
        load_result=state.load_result,
        pending_rows=state.pending_rows,
        processed_rows=state.processed_rows,
        processed_since_commit=state.processed_since_commit,
        state=state,
        checkpoint_context=checkpoint_context,
    )


def _stage4_record_passes_filters(
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
    row: _MappedStage4Row,
) -> bool:
    if request.options.committee_fec_ids is not None and row.committee_fec_id not in request.options.committee_fec_ids:
        _record_stage4_filter_skip(request=request, state=state)
        return False

    if not _passes_stage4_min_transaction_date(
        row.contribution_record,
        min_transaction_date=request.options.min_transaction_date,
    ):
        _record_stage4_filter_skip(request=request, state=state)
        return False

    return True


def _record_stage4_filter_skip(
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
) -> None:
    if request.options.limit is None:
        state.load_result.skipped += 1


def _stage4_limit_reached(
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
) -> bool:
    return request.options.limit is not None and state.selected_rows >= request.options.limit


def _load_stage4_non_batch_row(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
    resolve_committee: object,
    row: _MappedStage4Row,
) -> _Stage4RowLoadOutcome:
    if resolve_committee(row.committee_fec_id) is None:
        state.load_result.errors += 1
        LOGGER.warning(
            "Skipping %s row with unresolved CMTE_ID=%s sub_id=%s; load committees before Stage 4",
            request.file_type,
            row.committee_fec_id,
            row.source_record_key,
        )
        return _Stage4RowLoadOutcome(source_row_committable=False)

    try:
        row_outcome = _load_stage4_row_with_savepoint(
            conn,
            request=request,
            source_record_key=row.source_record_key,
            contribution_record=row.contribution_record,
        )
    except Exception:
        state.load_result.errors += 1
        LOGGER.warning(
            "Skipping %s row due to row-level load failure sub_id=%s cmte_id=%s",
            request.file_type,
            row.source_record_key,
            row.committee_fec_id,
            exc_info=True,
        )
        return _Stage4RowLoadOutcome(source_row_committable=False)

    provenance_inserted, relational_inserted = row_outcome
    durable_work = provenance_inserted or (request.options.with_transactions and relational_inserted)
    if durable_work:
        state.load_result.inserted += 1
    else:
        state.load_result.skipped += 1
    return _Stage4RowLoadOutcome(source_row_committable=True)


def _process_stage4_raw_row(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
    state: _Stage4StreamingState,
    raw_row: dict[str, str | None],
    resolve_committee: object,
    checkpoint_context: _Stage4CheckpointContext | None,
) -> None:
    state.processed_rows += 1
    state.processed_since_commit += 1

    contribution_record = map_contribution_fields(raw_row)
    source_record_key = _normalize_optional_text(contribution_record.get("sub_id"))
    committee_fec_id = _normalize_optional_text(contribution_record.get("committee_id"))
    if source_record_key is None or committee_fec_id is None:
        state.load_result.errors += 1
        LOGGER.warning(
            "Skipping %s row with missing SUB_ID or CMTE_ID: %s",
            request.file_type,
            dict(raw_row),
        )
        state.record_checkpoint_outcome(state.processed_rows, source_row_committable=False)
        _finalize_stage4_state_iteration(
            conn,
            request=request,
            state=state,
            checkpoint_context=checkpoint_context,
        )
        return

    contribution_record["sub_id"] = source_record_key
    contribution_record["committee_id"] = committee_fec_id
    mapped_row = _MappedStage4Row(
        source_record_key=source_record_key,
        committee_fec_id=committee_fec_id,
        contribution_record=contribution_record,
    )

    if not _stage4_record_passes_filters(
        request=request,
        state=state,
        row=mapped_row,
    ):
        _finalize_stage4_state_iteration(
            conn,
            request=request,
            state=state,
            checkpoint_context=checkpoint_context,
        )
        return

    state.selected_rows += 1

    if request.options.count_only:
        state.load_result.inserted += 1
        _finalize_stage4_state_iteration(
            conn,
            request=request,
            state=state,
            checkpoint_context=checkpoint_context,
        )
        return

    if request.options.with_transactions and not request.options.entity_extraction:
        state.pending_rows.append(
            _PendingStage4Row(
                source_record_key=mapped_row.source_record_key,
                contribution_record=mapped_row.contribution_record,
                processed_row_number=state.processed_rows,
            )
        )
    else:
        row_outcome = _load_stage4_non_batch_row(
            conn,
            request=request,
            state=state,
            resolve_committee=resolve_committee,
            row=mapped_row,
        )
        state.record_checkpoint_outcome(
            state.processed_rows,
            source_row_committable=row_outcome.source_row_committable,
        )

    _finalize_stage4_state_iteration(
        conn,
        request=request,
        state=state,
        checkpoint_context=checkpoint_context,
    )


def _load_stage4_contributions(
    conn: psycopg.Connection,
    *,
    request: Stage4LoadRequest,
) -> LoadResult:
    _validate_batch_size(request.options.batch_size)
    checkpoint_context: _Stage4CheckpointContext | None = None
    if request.checkpoint_enabled:
        archive_reference = _build_stage4_archive_reference(request.path, request.file_type)
        resume_resolution = _resolve_stage4_resume_checkpoint(
            conn,
            request=request,
            archive_fingerprint=archive_reference.archive_fingerprint,
            archive_member_name=archive_reference.archive_member_name,
        )
        if resume_resolution.checkpoint_rewritten:
            conn.commit()
        checkpoint_context = _Stage4CheckpointContext(
            archive_reference=archive_reference,
            start_row=resume_resolution.start_row,
        )

    state = _Stage4StreamingState()

    if checkpoint_context is None:
        raw_rows: Iterable[dict[str, str | None]] = read_bulk_file(
            request.path,
            request.file_type,
            limit=None,
        )
    else:
        raw_rows = read_bulk_file(
            request.path,
            request.file_type,
            limit=None,
            next_source_row_number=checkpoint_context.start_row,
        )
    resolve_committee = functools.cache(lambda fec_id: find_committee_id_by_fec_id(conn, fec_id))
    for raw_row in raw_rows:
        _process_stage4_raw_row(
            conn,
            request=request,
            state=state,
            raw_row=raw_row,
            resolve_committee=resolve_committee,
            checkpoint_context=checkpoint_context,
        )
        if _stage4_limit_reached(request=request, state=state):
            break

    final_batch_result = _load_stage4_transactions_batch(
        conn,
        request=request,
        load_result=state.load_result,
        rows=state.pending_rows,
    )
    _record_stage4_batch_checkpoint_outcomes(
        state=state,
        rows=state.pending_rows,
        batch_result=final_batch_result,
    )
    state.pending_rows = []
    final_commit_written = _commit_stage4_final_progress(
        conn,
        request=request,
        state=state,
        checkpoint_context=checkpoint_context,
    )
    if state.processed_rows > 0 and not final_commit_written:
        conn.commit()
    return state.load_result


def load_contributions(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str = _DEFAULT_STAGE4_CYCLE,
    data_source_id: UUID,
    options: Stage4LoadOptions | None = None,
    **legacy_kwargs: object,
) -> LoadResult:
    return _load_stage4_contributions(
        conn,
        request=_build_stage4_request(
            file_type="itcont",
            path=path,
            cycle=cycle,
            data_source_id=data_source_id,
            options=options,
            legacy_kwargs=legacy_kwargs,
        ),
    )


def load_committee_transactions(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str = _DEFAULT_STAGE4_CYCLE,
    data_source_id: UUID,
    options: Stage4LoadOptions | None = None,
    **legacy_kwargs: object,
) -> LoadResult:
    return _load_stage4_contributions(
        conn,
        request=_build_stage4_request(
            file_type="itpas2",
            path=path,
            cycle=cycle,
            data_source_id=data_source_id,
            options=options,
            legacy_kwargs=legacy_kwargs,
        ),
    )


__all__ = [
    "LoadResult",
    "STAGE4_RESUME_IDENTITY_COLUMNS",
    "Stage4ArchiveReference",
    "Stage4LoadOptions",
    "Stage4LoadRequest",
    "Stage4ResumeCheckpoint",
    "Stage4ResumeIdentity",
    "_commit_batch",
    "_commit_final_batch",
    "_build_stage4_archive_reference",
    "_build_stage4_source_record",
    "_resolve_stage4_resume_start_row",
    "_select_stage4_resume_checkpoint",
    "_write_stage4_resume_checkpoint",
    "build_stage4_resume_identity",
    "_insert_stage4_provenance_only",
    "_load_stage4_contributions",
    "_load_stage4_relational_row",
    "_passes_stage4_min_transaction_date",
    "_validate_batch_size",
    "load_committee_transactions",
    "load_contributions",
    "resolve_stage4_committee_scope",
]
