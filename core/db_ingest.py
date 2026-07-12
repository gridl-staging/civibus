
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg.types.range import DateRange

from core.types.python.models import Address, ContactPoint, SourceRecord


class SourceRecordBulkInsertAttribution(StrEnum):
    FAST_PATH_INSERTED = "fast_path_inserted"
    FAST_PATH_FALLBACK = "fast_path_fallback"
    FORCED_PER_ROW = "forced_per_row"


@dataclass(frozen=True, slots=True)
class SourceRecordBulkInsertResult:
    source_record_id: UUID | None
    inserted: bool
    attribution: SourceRecordBulkInsertAttribution


@dataclass(frozen=True, slots=True)
class SourceRecordBulkInsertAttributionCounts:
    fast_path_candidates: int
    forced_per_row_rows: int
    fast_path_inserted: int
    fast_path_fallbacks: int


def summarize_source_record_bulk_insert_attribution(
    results: list[SourceRecordBulkInsertResult],
) -> SourceRecordBulkInsertAttributionCounts:
    fast_path_inserted = sum(
        result.attribution == SourceRecordBulkInsertAttribution.FAST_PATH_INSERTED for result in results
    )
    fast_path_fallbacks = sum(
        result.attribution == SourceRecordBulkInsertAttribution.FAST_PATH_FALLBACK for result in results
    )
    forced_per_row_rows = sum(
        result.attribution == SourceRecordBulkInsertAttribution.FORCED_PER_ROW for result in results
    )
    return SourceRecordBulkInsertAttributionCounts(
        fast_path_candidates=fast_path_inserted + fast_path_fallbacks,
        forced_per_row_rows=forced_per_row_rows,
        fast_path_inserted=fast_path_inserted,
        fast_path_fallbacks=fast_path_fallbacks,
    )


def _strip_null_bytes(value: object) -> object:
    """Remove Unicode null bytes (\x00) from strings in raw_fields.

    PostgreSQL cannot store \u0000 in text or jsonb columns. Government
    source data occasionally contains embedded null bytes (e.g., CA's
    CTRIB_EMP field has "Michaelb\u0000" in some records). Rather than
    failing the entire row, strip the null bytes before insertion.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_null_bytes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_null_bytes(item) for item in value]
    return value


_ORGANIZATION_IDENTIFIER_QUERY = "SELECT id FROM core.organization WHERE identifiers @> %s LIMIT 1"
_PERSON_IDENTIFIER_QUERY = "SELECT id FROM core.person WHERE identifiers @> %s LIMIT 1"
_PERSON_BY_NAME_QUERY = """
    SELECT p.id
    FROM core.person p
    WHERE p.last_name = %s
      AND p.first_name = %s
    LIMIT 1
"""
_PERSON_BY_NAME_AND_ZIP_QUERY = """
    SELECT p.id
    FROM core.person p
    JOIN core.entity_address ea
      ON ea.entity_type = 'person'
     AND ea.entity_id = p.id
    JOIN core.address a
      ON a.id = ea.address_id
    WHERE p.last_name = %s
      AND p.first_name = %s
      AND a.zip5 = %s
    LIMIT 1
"""


def _extract_id(row: tuple[UUID] | None) -> UUID | None:
    if row is None:
        return None
    return row[0]


def _select_existing_id(
    cursor: psycopg.Cursor,
    query: str,
    params: tuple[object, ...],
) -> UUID | None:
    cursor.execute(query, params)
    return _extract_id(cursor.fetchone())


def _insert_or_select_existing_id(
    conn: psycopg.Connection,
    *,
    insert_query: str,
    insert_params: tuple[object, ...],
    select_query: str,
    select_params: tuple[object, ...],
    conflict_error: str,
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(insert_query, insert_params)
        inserted_id = _extract_id(cursor.fetchone())
        if inserted_id is not None:
            return inserted_id

        existing_id = _select_existing_id(cursor, select_query, select_params)

    if existing_id is None:
        raise RuntimeError(conflict_error)

    return existing_id


def _find_identifier_match(
    conn: psycopg.Connection,
    select_query: str,
    key: str,
    value: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        return _select_existing_id(cursor, select_query, (Jsonb({key: value}),))


def upsert_address(conn: psycopg.Connection, address: Address) -> UUID:
    return _insert_or_select_existing_id(
        conn,
        insert_query="""
        INSERT INTO core.address (
            id,
            raw_address,
            normalized_address,
            street_number,
            street_name,
            unit,
            city,
            state,
            zip5,
            zip4,
            county_fips,
            geometry,
            geocode_confidence,
            geocode_source,
            geocoded_at,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (raw_address) WHERE raw_address IS NOT NULL
        DO NOTHING
        RETURNING id
        """,
        insert_params=(
            address.id,
            address.raw_address,
            address.normalized_address,
            address.street_number,
            address.street_name,
            address.unit,
            address.city,
            address.state,
            address.zip5,
            address.zip4,
            address.county_fips,
            None,
            address.geocode_confidence,
            address.geocode_source,
            address.geocoded_at,
            address.created_at,
            address.updated_at,
        ),
        select_query="SELECT id FROM core.address WHERE raw_address = %s LIMIT 1",
        select_params=(address.raw_address,),
        conflict_error="Address upsert conflict occurred but no existing row could be selected",
    )


def _insert_source_record_null_key(conn: psycopg.Connection, sr: SourceRecord) -> UUID:
    """Fast path for records with no source_record_key — always inserts.

    Records with NULL source_record_key bypass the partial unique index
    entirely, so there is no conflict to handle.
    """
    with conn.cursor() as cursor:
        return _insert_source_record_row(cursor, sr, superseded_by=sr.superseded_by, source_record_key=None)


def _insert_source_record_row(
    cursor: psycopg.Cursor,
    sr: SourceRecord,
    *,
    superseded_by: UUID | None,
    source_record_key: str | None,
) -> UUID:
    cursor.execute(
        """
        INSERT INTO core.source_record (
            id, data_source_id, source_record_key, source_url,
            raw_fields, pull_date, record_hash, superseded_by, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            sr.id,
            sr.data_source_id,
            source_record_key,
            sr.source_url,
            Jsonb(_strip_null_bytes(sr.raw_fields)),
            sr.pull_date,
            sr.record_hash,
            superseded_by,
            sr.created_at,
        ),
    )
    return cursor.fetchone()[0]


def _lock_source_record_key(
    cursor: psycopg.Cursor,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> None:
    """Serialize active-key writes so concurrent ingests cannot race the insert path."""
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
        (str(data_source_id), source_record_key),
    )


def try_insert_source_record(conn: psycopg.Connection, sr: SourceRecord) -> UUID | None:
    # Null-key records bypass the partial unique index entirely
    if sr.source_record_key is None:
        return _insert_source_record_null_key(conn, sr)

    with conn.cursor() as cursor:
        _lock_source_record_key(
            cursor,
            data_source_id=sr.data_source_id,
            source_record_key=sr.source_record_key,
        )

        # Lock the existing active record for this key (if any)
        cursor.execute(
            """
            SELECT id, record_hash
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            FOR UPDATE
            """,
            (sr.data_source_id, sr.source_record_key),
        )
        existing = cursor.fetchone()

        if existing is None:
            # No active record — fresh insert
            return _insert_source_record_row(
                cursor,
                sr,
                superseded_by=sr.superseded_by,
                source_record_key=sr.source_record_key,
            )

        old_id, old_hash = existing

        # Same hash — identical re-ingest, skip
        if old_hash == sr.record_hash:
            return None

        # Different hash — amendment supersession (three-step pattern)
        # Step 1: INSERT new record with superseded_by = old_id
        #   FK satisfied (old_id exists), not "active" (superseded_by IS NOT NULL)
        #   so no partial unique index conflict
        new_id = _insert_source_record_row(
            cursor,
            sr,
            superseded_by=old_id,
            source_record_key=sr.source_record_key,
        )

        # Step 2: UPDATE old record — mark superseded by new
        #   FK satisfied (new_id now exists); old drops out of partial unique index
        cursor.execute(
            "UPDATE core.source_record SET superseded_by = %s WHERE id = %s",
            (new_id, old_id),
        )

        # Step 3: UPDATE new record — make it active
        #   Enters partial unique index as the single active record for this key
        cursor.execute(
            "UPDATE core.source_record SET superseded_by = NULL WHERE id = %s",
            (new_id,),
        )

        return new_id


def _is_setwise_bulk_candidate(record: SourceRecord, key_counts: dict[tuple[UUID, str | None], int]) -> bool:
    if record.source_record_key is None:
        return False
    return key_counts[(record.data_source_id, record.source_record_key)] == 1


def _bulk_insert_fresh_source_records(
    conn: psycopg.Connection,
    records: list[SourceRecord],
) -> set[int]:
    """Set-wise insert records with no active row; return the ordinals this statement inserted.

    Ordinals absent from the result already had an active row (or lost the insert race)
    and must go through the locked ``try_insert_source_record()`` owner.
    """
    if not records:
        return set()

    ordinals = list(range(len(records)))
    ids = [record.id for record in records]
    data_source_ids = [record.data_source_id for record in records]
    source_record_keys = [record.source_record_key for record in records]
    source_urls = [record.source_url for record in records]
    raw_fields = [Jsonb(_strip_null_bytes(record.raw_fields)) for record in records]
    pull_dates = [record.pull_date for record in records]
    record_hashes = [record.record_hash for record in records]
    created_at_values = [record.created_at for record in records]

    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH incoming (
                ordinal, id, data_source_id, source_record_key, source_url,
                raw_fields, pull_date, record_hash, created_at
            ) AS (
                SELECT *
                FROM unnest(
                    %s::integer[],
                    %s::uuid[],
                    %s::uuid[],
                    %s::text[],
                    %s::text[],
                    %s::jsonb[],
                    %s::timestamptz[],
                    %s::text[],
                    %s::timestamptz[]
                )
            ),
            active AS (
                SELECT
                    incoming.ordinal,
                    source_record.id AS active_id
                FROM incoming
                JOIN core.source_record AS source_record
                  ON source_record.data_source_id = incoming.data_source_id
                 AND source_record.source_record_key = incoming.source_record_key
                 AND source_record.superseded_by IS NULL
            ),
            inserted AS (
                INSERT INTO core.source_record (
                    id, data_source_id, source_record_key, source_url,
                    raw_fields, pull_date, record_hash, superseded_by, created_at
                )
                SELECT
                    incoming.id,
                    incoming.data_source_id,
                    incoming.source_record_key,
                    incoming.source_url,
                    incoming.raw_fields,
                    incoming.pull_date,
                    incoming.record_hash,
                    NULL,
                    incoming.created_at
                FROM incoming
                LEFT JOIN active ON active.ordinal = incoming.ordinal
                WHERE active.active_id IS NULL
                ON CONFLICT (data_source_id, source_record_key)
                WHERE superseded_by IS NULL AND source_record_key IS NOT NULL
                DO NOTHING
                RETURNING id
            )
            SELECT incoming.ordinal
            FROM incoming
            JOIN inserted ON inserted.id = incoming.id
            LEFT JOIN active ON active.ordinal = incoming.ordinal
            WHERE active.active_id IS NULL
            """,
            (
                ordinals,
                ids,
                data_source_ids,
                source_record_keys,
                source_urls,
                raw_fields,
                pull_dates,
                record_hashes,
                created_at_values,
            ),
        )
        return {ordinal for (ordinal,) in cursor}


def try_insert_source_records_bulk(
    conn: psycopg.Connection,
    source_records: list[SourceRecord],
) -> list[SourceRecordBulkInsertResult]:
    key_counts: dict[tuple[UUID, str | None], int] = {}
    for record in source_records:
        key = (record.data_source_id, record.source_record_key)
        key_counts[key] = key_counts.get(key, 0) + 1

    results: list[SourceRecordBulkInsertResult | None] = [None] * len(source_records)
    setwise_records: list[SourceRecord] = []
    setwise_indexes: list[int] = []
    for index, record in enumerate(source_records):
        if _is_setwise_bulk_candidate(record, key_counts):
            setwise_records.append(record)
            setwise_indexes.append(index)
        else:
            inserted_id = try_insert_source_record(conn, record)
            results[index] = SourceRecordBulkInsertResult(
                inserted_id,
                inserted_id is not None,
                SourceRecordBulkInsertAttribution.FORCED_PER_ROW,
            )

    inserted_ordinals = _bulk_insert_fresh_source_records(conn, setwise_records)
    for ordinal, record in enumerate(setwise_records):
        result_index = setwise_indexes[ordinal]
        if ordinal in inserted_ordinals:
            results[result_index] = SourceRecordBulkInsertResult(
                record.id,
                True,
                SourceRecordBulkInsertAttribution.FAST_PATH_INSERTED,
            )
        else:
            inserted_id = try_insert_source_record(conn, record)
            results[result_index] = SourceRecordBulkInsertResult(
                inserted_id,
                inserted_id is not None,
                SourceRecordBulkInsertAttribution.FAST_PATH_FALLBACK,
            )

    return [result for result in results if result is not None]


def find_organization_by_canonical_name(conn: psycopg.Connection, canonical_name: str) -> UUID | None:
    with conn.cursor() as cursor:
        return _select_existing_id(
            cursor,
            "SELECT id FROM core.organization WHERE canonical_name = %s LIMIT 1",
            (canonical_name,),
        )


def find_organization_by_identifier(conn: psycopg.Connection, key: str, value: str) -> UUID | None:
    return _find_identifier_match(conn, _ORGANIZATION_IDENTIFIER_QUERY, key, value)


def find_person_by_identifier(conn: psycopg.Connection, key: str, value: str) -> UUID | None:
    return _find_identifier_match(conn, _PERSON_IDENTIFIER_QUERY, key, value)


def find_person_by_name_and_zip(
    conn: psycopg.Connection,
    last_name: str,
    first_name: str,
    zip5: str | None,
) -> UUID | None:
    query = _PERSON_BY_NAME_QUERY if zip5 is None else _PERSON_BY_NAME_AND_ZIP_QUERY
    params: tuple[object, ...] = (last_name, first_name) if zip5 is None else (last_name, first_name, zip5)

    with conn.cursor() as cursor:
        return _select_existing_id(cursor, query, params)


def insert_entity_source(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
    source_record_id: UUID,
    extraction_role: str,
    confidence: float | None = None,
    extracted_fields: dict[str, object] | None = None,
) -> UUID:
    extracted_fields_json = Jsonb(extracted_fields) if extracted_fields is not None else None
    return _insert_or_select_existing_id(
        conn,
        insert_query="""
        INSERT INTO core.entity_source (
            entity_type,
            entity_id,
            source_record_id,
            extraction_role,
            confidence,
            extracted_fields
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (entity_type, entity_id, source_record_id, extraction_role)
        DO NOTHING
        RETURNING id
        """,
        insert_params=(
            entity_type,
            entity_id,
            source_record_id,
            extraction_role,
            confidence,
            extracted_fields_json,
        ),
        select_query="""
        SELECT id
        FROM core.entity_source
        WHERE entity_type = %s
          AND entity_id = %s
          AND source_record_id = %s
          AND extraction_role IS NOT DISTINCT FROM %s
        LIMIT 1
        """,
        select_params=(entity_type, entity_id, source_record_id, extraction_role),
        conflict_error="Entity source insert conflict occurred but existing row was not found",
    )


def _clear_current_field_provenance(
    cursor: psycopg.Cursor,
    *,
    entity_type: str,
    entity_id: UUID,
    field_name: str,
) -> None:
    """Mark all current rows for one field as non-current before upserting the next value."""
    cursor.execute(
        """
        UPDATE core.field_provenance
        SET is_current = FALSE
        WHERE entity_type = %s
          AND entity_id = %s
          AND field_name = %s
          AND is_current = TRUE
        """,
        (entity_type, entity_id, field_name),
    )


def insert_field_provenance(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
    field_name: str,
    field_value: str,
    source_record_id: UUID,
    observed_at: datetime | None = None,
) -> UUID:
    """Insert or update one field-level provenance row and enforce a single current value."""
    with conn.cursor() as cursor:
        _clear_current_field_provenance(
            cursor,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
        )
        cursor.execute(
            """
            INSERT INTO core.field_provenance (
                entity_type,
                entity_id,
                field_name,
                field_value,
                source_record_id,
                first_seen,
                last_seen,
                is_current
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                COALESCE(%s, NOW()),
                COALESCE(%s, NOW()),
                TRUE
            )
            ON CONFLICT (entity_type, entity_id, field_name, field_value, source_record_id)
            DO UPDATE
            SET first_seen = LEAST(core.field_provenance.first_seen, EXCLUDED.first_seen),
                last_seen = GREATEST(core.field_provenance.last_seen, EXCLUDED.last_seen),
                is_current = TRUE
            RETURNING id
            """,
            (
                entity_type,
                entity_id,
                field_name,
                field_value,
                source_record_id,
                observed_at,
                observed_at,
            ),
        )
        inserted_id = _extract_id(cursor.fetchone())

    if inserted_id is None:
        raise RuntimeError("Field provenance insert did not return an id")

    return inserted_id


def insert_entity_address(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
    address_id: UUID,
    source_record_id: UUID,
    address_role: str = "mailing",
    valid_period: DateRange | None = None,
    date_precision: str = "day",
) -> UUID:
    effective_valid_period = valid_period if valid_period is not None else DateRange(None, None)
    select_query = """
        SELECT id
        FROM core.entity_address
        WHERE entity_type = %s
          AND entity_id = %s
          AND address_id = %s
          AND address_role IS NOT DISTINCT FROM %s
          AND valid_period IS NOT DISTINCT FROM %s
          AND date_precision IS NOT DISTINCT FROM %s
        LIMIT 1
    """
    select_params = (
        entity_type,
        entity_id,
        address_id,
        address_role,
        effective_valid_period,
        date_precision,
    )

    with conn.cursor() as cursor:
        existing_id = _select_existing_id(cursor, select_query, select_params)
        if existing_id is not None:
            return existing_id

        try:
            with conn.transaction():
                cursor.execute(
                    """
                    INSERT INTO core.entity_address (
                        entity_type,
                        entity_id,
                        address_id,
                        address_role,
                        valid_period,
                        date_precision,
                        source_record_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        entity_type,
                        entity_id,
                        address_id,
                        address_role,
                        effective_valid_period,
                        date_precision,
                        source_record_id,
                    ),
                )
                inserted_id = _extract_id(cursor.fetchone())
        except (psycopg.errors.ExclusionViolation, psycopg.errors.UniqueViolation):
            existing_id = _select_existing_id(cursor, select_query, select_params)
            if existing_id is not None:
                return existing_id
            raise

    if inserted_id is None:
        raise RuntimeError("Entity address insert did not return an id")

    return inserted_id


# ---------------------------------------------------------------------------
# Contact Point upsert
# ---------------------------------------------------------------------------

# PostgreSQL cannot match two partial unique indexes in a single ON CONFLICT
# clause. core.contact_point has two:
#   uq_contact_point_natural_key       — WHERE role IS NOT NULL
#   uq_contact_point_natural_key_null_role — WHERE role IS NULL
# We branch on whether role is NULL and issue the appropriate INSERT.

_UPSERT_CONTACT_POINT_WITH_ROLE = """
    INSERT INTO core.contact_point (
        id, type, value_raw, value_normalized, role,
        owner_type, owner_id, source_record_id,
        last_verified_at, is_preferred, valid_period
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (owner_type, owner_id, type, value_raw, role)
    WHERE role IS NOT NULL
    DO UPDATE SET
        value_normalized = COALESCE(EXCLUDED.value_normalized, core.contact_point.value_normalized),
        last_verified_at = COALESCE(EXCLUDED.last_verified_at, core.contact_point.last_verified_at),
        is_preferred = EXCLUDED.is_preferred,
        source_record_id = COALESCE(EXCLUDED.source_record_id, core.contact_point.source_record_id),
        updated_at = NOW()
    RETURNING id
"""

_UPSERT_CONTACT_POINT_NULL_ROLE = """
    INSERT INTO core.contact_point (
        id, type, value_raw, value_normalized, role,
        owner_type, owner_id, source_record_id,
        last_verified_at, is_preferred, valid_period
    )
    VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (owner_type, owner_id, type, value_raw)
    WHERE role IS NULL
    DO UPDATE SET
        value_normalized = COALESCE(EXCLUDED.value_normalized, core.contact_point.value_normalized),
        last_verified_at = COALESCE(EXCLUDED.last_verified_at, core.contact_point.last_verified_at),
        is_preferred = EXCLUDED.is_preferred,
        source_record_id = COALESCE(EXCLUDED.source_record_id, core.contact_point.source_record_id),
        updated_at = NOW()
    RETURNING id
"""


def upsert_contact_point(conn: psycopg.Connection, cp: ContactPoint) -> UUID:
    """Upsert a contact_point row, branching on role NULL/non-NULL for the correct partial index."""
    valid_period = DateRange(cp.valid_period.start_date, cp.valid_period.end_date)

    with conn.cursor() as cur:
        if cp.role is not None:
            cur.execute(
                _UPSERT_CONTACT_POINT_WITH_ROLE,
                (
                    cp.id,
                    cp.type,
                    cp.value_raw,
                    cp.value_normalized,
                    cp.role,
                    cp.owner_type,
                    cp.owner_id,
                    cp.source_record_id,
                    cp.last_verified_at,
                    cp.is_preferred,
                    valid_period,
                ),
            )
        else:
            cur.execute(
                _UPSERT_CONTACT_POINT_NULL_ROLE,
                (
                    cp.id,
                    cp.type,
                    cp.value_raw,
                    cp.value_normalized,
                    cp.owner_type,
                    cp.owner_id,
                    cp.source_record_id,
                    cp.last_verified_at,
                    cp.is_preferred,
                    valid_period,
                ),
            )
        row_id: UUID = cur.fetchone()[0]

    if cp.source_record_id is not None:
        insert_entity_source(conn, "contact_point", row_id, cp.source_record_id, "contact_point")

    return row_id
