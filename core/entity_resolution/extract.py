from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.entity_resolution.splink_config import (
    ORGANIZATION_PREPROCESSING_SQL,
    PERSON_PREPROCESSING_SQL,
)

RowDict = dict[str, Any]
_PROBABILISTIC_ROW_ID_SEPARATOR = "__splink_row__"


def _fetch_preprocessed_rows(conn: psycopg.Connection, preprocessing_sql: str) -> list[RowDict]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(preprocessing_sql)
        rows = cursor.fetchall()

    return list(rows)


def extract_persons_for_matching(conn: psycopg.Connection) -> list[RowDict]:
    return _fetch_preprocessed_rows(conn, PERSON_PREPROCESSING_SQL)


def extract_organizations_for_matching(conn: psycopg.Connection) -> list[RowDict]:
    return _fetch_preprocessed_rows(conn, ORGANIZATION_PREPROCESSING_SQL)


def extract_rows_for_matching(
    conn: psycopg.Connection,
    entity_type: str,
) -> list[RowDict]:
    if entity_type == "person":
        return extract_persons_for_matching(conn)
    if entity_type == "organization":
        return extract_organizations_for_matching(conn)

    raise ValueError(f"entity_type must be 'person' or 'organization', got {entity_type!r}")


def _synthetic_probabilistic_row_id(entity_id: Any, row_index: int) -> str:
    return f"{entity_id}{_PROBABILISTIC_ROW_ID_SEPARATOR}{row_index}"


def _restore_uuid_string(row_id: str) -> UUID | str:
    try:
        return UUID(row_id)
    except ValueError:
        return row_id


def restore_entity_id_from_probabilistic_row(row_id: Any) -> Any:
    """Recover the original entity ID from a prepared Splink row ID or UUID string."""
    if isinstance(row_id, UUID):
        return row_id
    if not isinstance(row_id, str):
        return row_id

    prefix, separator, suffix = row_id.rpartition(_PROBABILISTIC_ROW_ID_SEPARATOR)
    if not separator or not suffix.isdigit():
        return _restore_uuid_string(row_id)

    return _restore_uuid_string(prefix)


def restore_entity_pair_from_prediction_record(record: RowDict) -> tuple[Any, Any]:
    """Recover canonical entity IDs from a Splink prediction record."""
    left_row_id = record.get("unique_id_l", record.get("id_l"))
    right_row_id = record.get("unique_id_r", record.get("id_r"))
    if left_row_id is None or right_row_id is None:
        raise RuntimeError("Splink prediction rows must include left/right entity IDs.")

    return (
        restore_entity_id_from_probabilistic_row(left_row_id),
        restore_entity_id_from_probabilistic_row(right_row_id),
    )


def prediction_record_restores_same_entity(record: RowDict) -> bool:
    """Return True when both prediction sides map back to the same entity ID."""
    left_entity_id, right_entity_id = restore_entity_pair_from_prediction_record(record)
    return left_entity_id == right_entity_id


def prepare_rows_for_probabilistic_scoring(rows: list[RowDict]) -> list[RowDict]:
    """Preserve all rows while assigning Splink-safe string record IDs."""
    row_count_by_entity_id = Counter(row["id"] for row in rows)

    row_index_by_entity_id: defaultdict[Any, int] = defaultdict(int)
    prepared_rows: list[RowDict] = []
    for row in rows:
        prepared_row = dict(row)
        entity_id = prepared_row["id"]
        row_index = row_index_by_entity_id[entity_id]
        row_index_by_entity_id[entity_id] += 1
        if row_count_by_entity_id[entity_id] > 1:
            prepared_row["id"] = _synthetic_probabilistic_row_id(entity_id, row_index)
        else:
            prepared_row["id"] = str(entity_id)
        prepared_rows.append(prepared_row)

    return prepared_rows
