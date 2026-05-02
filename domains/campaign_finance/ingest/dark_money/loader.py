
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.sql import SQL, Identifier, Placeholder

from core.db import try_insert_source_record
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
    processed_since_commit = 0

    records = iter_rows_with_limit(read_irs_527_records(Path(txt_path)), limit)
    for record in records:
        processed_since_commit += 1
        with conn.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {_IRS_527_ROW_SAVEPOINT}")
            rollback = True
            try:
                source_record_id = try_insert_source_record(
                    conn,
                    _build_source_record(data_source_id=data_source_id, record=record),
                )
                if source_record_id is None:
                    result.skipped += 1
                elif not _insert_irs_527_row(conn, record, source_record_id=source_record_id):
                    result.skipped += 1
                else:
                    result.inserted += 1
                    rollback = False
            except Exception:
                result.errors += 1
                LOGGER.warning("Skipping IRS 527 row during ingest: %s", record, exc_info=True)
            if rollback:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {_IRS_527_ROW_SAVEPOINT}")
            cursor.execute(f"RELEASE SAVEPOINT {_IRS_527_ROW_SAVEPOINT}")
        processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)

    if processed_since_commit > 0:
        conn.commit()

    return result


__all__ = [
    "ensure_irs_527_data_source",
    "load_irs_527_records",
]
