"""
Stub summary for jun04_3pm_5_launch_gate_and_golive/civibus_dev/domains/campaign_finance/ingest/dark_money/loader.py.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.sql import SQL, Identifier, Placeholder
from psycopg.types.json import Jsonb

from core.db import try_insert_source_record
from core.db_ingest import _strip_null_bytes
from core.types.python.models import DataSource, SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.dark_money.download import IRS_527_FULL_DATA_URL
from domains.campaign_finance.ingest.dark_money.parser import (
    Irs527Record,
    read_irs_527_records,
)
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source, iter_rows_with_limit
from domains.campaign_finance.types import Contribution527, Expenditure527, Filing8872, PoliticalOrganization527

LOGGER = logging.getLogger(__name__)

_IRS_527_DATA_SOURCE_DOMAIN = "campaign_finance"
_IRS_527_DATA_SOURCE_JURISDICTION = "federal/irs_527"
_IRS_527_DATA_SOURCE_NAME = "IRS Form 8872 Political Organizations"
_IRS_527_DATA_SOURCE_FORMAT = "pipe_delimited"

_IRS_527_ROW_SAVEPOINT = "irs_527_row"
_IRS_527_BATCH_SAVEPOINT = "irs_527_batch"


@dataclass(frozen=True)
class _PreparedIrs527Row:
    record: Irs527Record
    source_record: SourceRecord
    source_record_key: str


def ensure_irs_527_data_source(conn: psycopg.Connection) -> UUID:
    data_source = DataSource(
        domain=_IRS_527_DATA_SOURCE_DOMAIN,
        jurisdiction=_IRS_527_DATA_SOURCE_JURISDICTION,
        name=_IRS_527_DATA_SOURCE_NAME,
        source_url=IRS_527_FULL_DATA_URL,
        source_format=_IRS_527_DATA_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _validate_batch_size(batch_size: int) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")


def _commit_batch(conn: psycopg.Connection, processed_since_commit: int, batch_size: int) -> int:
    if processed_since_commit >= batch_size:
        conn.commit()
        return 0
    return processed_since_commit


def _json_compatible_raw_fields(record: Irs527Record) -> dict[str, object]:
    raw_fields = record.model_dump(
        exclude={"id", "created_at", "updated_at", "source_record_id"},
        exclude_none=False,
    )
    json_ready: dict[str, object] = {}
    for key, value in raw_fields.items():
        if isinstance(value, Decimal):
            json_ready[key] = str(value)
        elif isinstance(value, (date, datetime)):
            json_ready[key] = value.isoformat()
        else:
            json_ready[key] = value
    return json_ready


def _source_record_key(record: Irs527Record) -> str:
    if isinstance(record, PoliticalOrganization527):
        return f"irs_527:1:{record.ein}"
    if isinstance(record, Filing8872):
        return f"irs_527:2:{record.form_id_number}"
    if isinstance(record, Contribution527):
        return f"irs_527:A:{record.sched_a_id}"
    if isinstance(record, Expenditure527):
        return f"irs_527:B:{record.sched_b_id}"
    raise TypeError(f"Unsupported IRS 527 record type: {type(record).__name__}")


def _insert_model_with_conflict_do_nothing(
    conn: psycopg.Connection,
    *,
    table_name: str,
    conflict_column: str,
    payload: dict[str, Any],
) -> bool:
    column_names = tuple(payload.keys())
    values = [payload[column_name] for column_name in column_names]
    statement = SQL(
        """
        INSERT INTO cf.{table_name} ({columns})
        VALUES ({values})
        ON CONFLICT ({conflict_column})
        DO NOTHING
        RETURNING id
        """
    ).format(
        table_name=Identifier(table_name),
        columns=SQL(", ").join(Identifier(column_name) for column_name in column_names),
        values=SQL(", ").join(Placeholder() for _ in column_names),
        conflict_column=Identifier(conflict_column),
    )
    with conn.cursor() as cursor:
        cursor.execute(statement, values)
        return cursor.fetchone() is not None


def _insert_models_with_conflict_do_nothing_bulk(
    conn: psycopg.Connection,
    *,
    table_name: str,
    conflict_column: str,
    payloads: Sequence[dict[str, Any]],
) -> int:
    if not payloads:
        return 0
    column_names = tuple(payloads[0].keys())
    statement = SQL(
        """
        INSERT INTO cf.{table_name} ({columns})
        VALUES ({values})
        ON CONFLICT ({conflict_column})
        DO NOTHING
        """
    ).format(
        table_name=Identifier(table_name),
        columns=SQL(", ").join(Identifier(column_name) for column_name in column_names),
        values=SQL(", ").join(Placeholder() for _ in column_names),
        conflict_column=Identifier(conflict_column),
    )
    values = [[payload[column_name] for column_name in column_names] for payload in payloads]
    with conn.cursor() as cursor:
        cursor.executemany(statement, values)
        return cursor.rowcount if cursor.rowcount >= 0 else len(payloads)


def _upsert_model_with_conflict_update(
    conn: psycopg.Connection,
    *,
    table_name: str,
    conflict_column: str,
    payload: dict[str, Any],
) -> bool:
    column_names = tuple(payload.keys())
    values = [payload[column_name] for column_name in column_names]
    update_columns = tuple(column_name for column_name in column_names if column_name != conflict_column)
    assignments = SQL(", ").join(
        SQL("{column} = EXCLUDED.{column}").format(column=Identifier(column_name)) for column_name in update_columns
    )
    statement = SQL(
        """
        INSERT INTO cf.{table_name} ({columns})
        VALUES ({values})
        ON CONFLICT ({conflict_column})
        DO UPDATE SET {assignments}
        RETURNING id
        """
    ).format(
        table_name=Identifier(table_name),
        columns=SQL(", ").join(Identifier(column_name) for column_name in column_names),
        values=SQL(", ").join(Placeholder() for _ in column_names),
        conflict_column=Identifier(conflict_column),
        assignments=assignments,
    )
    with conn.cursor() as cursor:
        cursor.execute(statement, values)
        return cursor.fetchone() is not None


def _upsert_models_with_conflict_update_bulk(
    conn: psycopg.Connection,
    *,
    table_name: str,
    conflict_column: str,
    payloads: Sequence[dict[str, Any]],
) -> int:
    if not payloads:
        return 0
    column_names = tuple(payloads[0].keys())
    update_columns = tuple(column_name for column_name in column_names if column_name != conflict_column)
    assignments = SQL(", ").join(
        SQL("{column} = EXCLUDED.{column}").format(column=Identifier(column_name)) for column_name in update_columns
    )
    statement = SQL(
        """
        INSERT INTO cf.{table_name} ({columns})
        VALUES ({values})
        ON CONFLICT ({conflict_column})
        DO UPDATE SET {assignments}
        """
    ).format(
        table_name=Identifier(table_name),
        columns=SQL(", ").join(Identifier(column_name) for column_name in column_names),
        values=SQL(", ").join(Placeholder() for _ in column_names),
        conflict_column=Identifier(conflict_column),
        assignments=assignments,
    )
    values = [[payload[column_name] for column_name in column_names] for payload in payloads]
    with conn.cursor() as cursor:
        cursor.executemany(statement, values)
        return cursor.rowcount if cursor.rowcount >= 0 else len(payloads)


def _insert_irs_527_row(conn: psycopg.Connection, record: Irs527Record, *, source_record_id: UUID) -> bool:
    payload = record.model_dump(
        exclude={"id", "created_at", "updated_at"},
        exclude_none=False,
    )
    payload["source_record_id"] = source_record_id

    if isinstance(record, PoliticalOrganization527):
        # Form 8871 registrations are amendable: a later row for the same EIN should
        # advance provenance and replace the current organization snapshot.
        return _upsert_model_with_conflict_update(
            conn,
            table_name="political_organization_527",
            conflict_column="ein",
            payload=payload,
        )
    if isinstance(record, Filing8872):
        return _insert_model_with_conflict_do_nothing(
            conn,
            table_name="filing_8872",
            conflict_column="form_id_number",
            payload=payload,
        )
    if isinstance(record, Contribution527):
        return _insert_model_with_conflict_do_nothing(
            conn,
            table_name="contribution_527",
            conflict_column="sched_a_id",
            payload=payload,
        )
    if isinstance(record, Expenditure527):
        return _insert_model_with_conflict_do_nothing(
            conn,
            table_name="expenditure_527",
            conflict_column="sched_b_id",
            payload=payload,
        )
    raise TypeError(f"Unsupported IRS 527 record type: {type(record).__name__}")


def _payload_for_irs_527_row(record: Irs527Record, *, source_record_id: UUID) -> dict[str, Any]:
    payload = record.model_dump(
        exclude={"id", "created_at", "updated_at"},
        exclude_none=False,
    )
    payload["source_record_id"] = source_record_id
    return payload


def _bulk_insert_irs_527_rows(conn: psycopg.Connection, rows: Sequence[_PreparedIrs527Row]) -> int:
    org_payloads: list[dict[str, Any]] = []
    filing_payloads: list[dict[str, Any]] = []
    contribution_payloads: list[dict[str, Any]] = []
    expenditure_payloads: list[dict[str, Any]] = []

    for row in rows:
        payload = _payload_for_irs_527_row(row.record, source_record_id=row.source_record.id)
        if isinstance(row.record, PoliticalOrganization527):
            org_payloads.append(payload)
        elif isinstance(row.record, Filing8872):
            filing_payloads.append(payload)
        elif isinstance(row.record, Contribution527):
            contribution_payloads.append(payload)
        elif isinstance(row.record, Expenditure527):
            expenditure_payloads.append(payload)
        else:
            raise TypeError(f"Unsupported IRS 527 record type: {type(row.record).__name__}")

    return (
        _upsert_models_with_conflict_update_bulk(
            conn,
            table_name="political_organization_527",
            conflict_column="ein",
            payloads=org_payloads,
        )
        + _insert_models_with_conflict_do_nothing_bulk(
            conn,
            table_name="filing_8872",
            conflict_column="form_id_number",
            payloads=filing_payloads,
        )
        + _insert_models_with_conflict_do_nothing_bulk(
            conn,
            table_name="contribution_527",
            conflict_column="sched_a_id",
            payloads=contribution_payloads,
        )
        + _insert_models_with_conflict_do_nothing_bulk(
            conn,
            table_name="expenditure_527",
            conflict_column="sched_b_id",
            payloads=expenditure_payloads,
        )
    )


def _build_source_record(
    *,
    data_source_id: UUID,
    record: Irs527Record,
) -> SourceRecord:
    raw_fields = _json_compatible_raw_fields(record)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_source_record_key(record),
        source_url=IRS_527_FULL_DATA_URL,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )


def _prepare_irs_527_row(*, data_source_id: UUID, record: Irs527Record) -> _PreparedIrs527Row:
    source_record = _build_source_record(data_source_id=data_source_id, record=record)
    source_record_key = source_record.source_record_key
    if source_record_key is None:
        raise ValueError("IRS 527 source records must have source_record_key")
    return _PreparedIrs527Row(
        record=record,
        source_record=source_record,
        source_record_key=source_record_key,
    )


def _fetch_active_source_record_hashes(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_keys: Sequence[str],
) -> dict[str, str]:
    if not source_record_keys:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_record_key, record_hash
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            """,
            (data_source_id, list(source_record_keys)),
        )
        return {source_record_key: record_hash for source_record_key, record_hash in cursor.fetchall()}


def _insert_source_records_bulk(conn: psycopg.Connection, rows: Sequence[_PreparedIrs527Row]) -> int:
    if not rows:
        return 0
    statement = """
        INSERT INTO core.source_record (
            id, data_source_id, source_record_key, source_url,
            raw_fields, pull_date, record_hash, superseded_by, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (data_source_id, source_record_key)
        WHERE superseded_by IS NULL AND source_record_key IS NOT NULL
        DO NOTHING
    """
    values = [
        (
            row.source_record.id,
            row.source_record.data_source_id,
            row.source_record_key,
            row.source_record.source_url,
            Jsonb(_strip_null_bytes(row.source_record.raw_fields)),
            row.source_record.pull_date,
            row.source_record.record_hash,
            row.source_record.superseded_by,
            row.source_record.created_at,
        )
        for row in rows
    ]
    with conn.cursor() as cursor:
        cursor.executemany(statement, values)
        return cursor.rowcount if cursor.rowcount >= 0 else len(rows)


def _load_irs_527_row_with_savepoint(
    conn: psycopg.Connection,
    result: LoadResult,
    prepared_row: _PreparedIrs527Row,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_IRS_527_ROW_SAVEPOINT}")
        rollback = True
        try:
            source_record_id = try_insert_source_record(conn, prepared_row.source_record)
            if source_record_id is None:
                result.skipped += 1
            elif not _insert_irs_527_row(conn, prepared_row.record, source_record_id=source_record_id):
                result.skipped += 1
            else:
                result.inserted += 1
                rollback = False
        except Exception:
            result.errors += 1
            LOGGER.warning("Skipping IRS 527 row during ingest: %s", prepared_row.record, exc_info=True)
        if rollback:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_IRS_527_ROW_SAVEPOINT}")
        cursor.execute(f"RELEASE SAVEPOINT {_IRS_527_ROW_SAVEPOINT}")


def _load_irs_527_rows_with_savepoints(
    conn: psycopg.Connection,
    result: LoadResult,
    rows: Sequence[_PreparedIrs527Row],
) -> None:
    for row in rows:
        _load_irs_527_row_with_savepoint(conn, result, row)


def _load_fresh_unique_irs_527_rows_bulk(
    conn: psycopg.Connection,
    result: LoadResult,
    rows: Sequence[_PreparedIrs527Row],
) -> None:
    if not rows:
        return
    with conn.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {_IRS_527_BATCH_SAVEPOINT}")
    try:
        source_record_count = _insert_source_records_bulk(conn, rows)
        if source_record_count != len(rows):
            raise RuntimeError("bulk IRS 527 source-record insert conflicted")
        inserted_count = _bulk_insert_irs_527_rows(conn, rows)
        if inserted_count != len(rows):
            raise RuntimeError("bulk IRS 527 row insert conflicted")
    except Exception:
        with conn.cursor() as cursor:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {_IRS_527_BATCH_SAVEPOINT}")
            cursor.execute(f"RELEASE SAVEPOINT {_IRS_527_BATCH_SAVEPOINT}")
        _load_irs_527_rows_with_savepoints(conn, result, rows)
        return

    with conn.cursor() as cursor:
        cursor.execute(f"RELEASE SAVEPOINT {_IRS_527_BATCH_SAVEPOINT}")
    result.inserted += inserted_count


def _load_irs_527_batch(
    conn: psycopg.Connection,
    result: LoadResult,
    rows: Sequence[_PreparedIrs527Row],
    *,
    data_source_id: UUID,
) -> None:
    duplicate_keys = {
        source_record_key
        for source_record_key, count in Counter(row.source_record_key for row in rows).items()
        if count > 1
    }
    ordered_rows = [row for row in rows if row.source_record_key in duplicate_keys]
    unique_rows = [row for row in rows if row.source_record_key not in duplicate_keys]

    existing_hashes = _fetch_active_source_record_hashes(
        conn,
        data_source_id=data_source_id,
        source_record_keys=[row.source_record_key for row in unique_rows],
    )
    fresh_rows: list[_PreparedIrs527Row] = []
    changed_rows: list[_PreparedIrs527Row] = []
    for row in unique_rows:
        existing_hash = existing_hashes.get(row.source_record_key)
        if existing_hash is None:
            fresh_rows.append(row)
        elif existing_hash == row.source_record.record_hash:
            result.skipped += 1
        else:
            changed_rows.append(row)

    _load_irs_527_rows_with_savepoints(conn, result, ordered_rows)
    _load_irs_527_rows_with_savepoints(conn, result, changed_rows)
    _load_fresh_unique_irs_527_rows_bulk(conn, result, fresh_rows)


def load_irs_527_records(
    conn: psycopg.Connection,
    txt_path: str | Path,
    *,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    _validate_batch_size(batch_size)

    result = LoadResult()
    rows: list[_PreparedIrs527Row] = []

    records = iter_rows_with_limit(read_irs_527_records(Path(txt_path)), limit)
    for record in records:
        rows.append(_prepare_irs_527_row(data_source_id=data_source_id, record=record))
        if len(rows) >= batch_size:
            _load_irs_527_batch(conn, result, rows, data_source_id=data_source_id)
            conn.commit()
            rows = []

    if rows:
        _load_irs_527_batch(conn, result, rows, data_source_id=data_source_id)
        conn.commit()

    return result


__all__ = [
    "ensure_irs_527_data_source",
    "load_irs_527_records",
]
