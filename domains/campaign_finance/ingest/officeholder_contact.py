"""Shared helpers for officeholder directory loaders."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from uuid import UUID

import psycopg

from core.db import insert_person
from core.db_ingest import (
    find_person_by_identifier,
    insert_entity_source,
    try_insert_source_record,
    upsert_contact_point,
)
from core.types.python.models import (
    CONTACT_POINT_OWNER_TYPES,
    ContactPoint,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)

_ROW_SAVEPOINT_NAME = "officeholder_row"


def upsert_owned_contact_point(
    conn: psycopg.Connection,
    *,
    cp_type: str,
    value_raw: str,
    owner_type: CONTACT_POINT_OWNER_TYPES,
    owner_id: UUID,
    role: str | None = None,
    source_record_id: UUID | None = None,
) -> None:
    """Insert or update one contact point with explicit ownership semantics."""
    normalized_value = value_raw.strip()
    if not normalized_value:
        return

    upsert_contact_point(
        conn,
        ContactPoint(
            type=cp_type,
            value_raw=normalized_value,
            owner_type=owner_type,
            owner_id=owner_id,
            role=role,
            source_record_id=source_record_id,
        ),
    )


def insert_officeholder_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    raw_row: Mapping[str, object],
) -> UUID | None:
    """Persist one raw officeholder row as a source_record when possible."""
    raw_fields = {key: value for key, value in raw_row.items() if value is not None}
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    return try_insert_source_record(conn, source_record)


def resolve_or_create_person_by_identifier(
    conn: psycopg.Connection,
    *,
    identifier_key: str,
    identifier_value: str,
    first_name: str,
    last_name: str,
    source_record_id: UUID | None,
) -> UUID:
    """Find a person by one directory identifier or create it once."""
    existing_person_id = find_person_by_identifier(conn, identifier_key, identifier_value)
    if existing_person_id is not None:
        return existing_person_id

    person = Person(
        canonical_name=f"{last_name}, {first_name}".strip().rstrip(","),
        first_name=first_name or None,
        last_name=last_name or None,
        identifiers={identifier_key: identifier_value},
    )
    insert_person(conn, person)
    if source_record_id is not None:
        insert_entity_source(conn, "person", person.id, source_record_id, "person")
    return person.id


def run_officeholder_row(
    conn: psycopg.Connection,
    *,
    logger: logging.Logger,
    failure_message: str,
    raw_row: Mapping[str, object],
    operation: Callable[[], None],
) -> bool:
    """Run one officeholder loader row behind a SAVEPOINT.

    The loaders intentionally keep going after bad rows. PostgreSQL marks the
    transaction aborted after a statement error, so we must roll back to a
    SAVEPOINT before the next row can safely run.
    """
    with conn.cursor() as cur:
        cur.execute(f"SAVEPOINT {_ROW_SAVEPOINT_NAME}")

    try:
        operation()
    except Exception:
        with conn.cursor() as cur:
            cur.execute(f"ROLLBACK TO SAVEPOINT {_ROW_SAVEPOINT_NAME}")
            cur.execute(f"RELEASE SAVEPOINT {_ROW_SAVEPOINT_NAME}")
        logger.exception(failure_message, raw_row)
        return False

    with conn.cursor() as cur:
        cur.execute(f"RELEASE SAVEPOINT {_ROW_SAVEPOINT_NAME}")
    return True
