
from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier, Placeholder
from psycopg.types.json import Jsonb

from core import db_ingest
from core.types.python.models import Address, DataSource, Organization, Person, PersonPortrait, RefreshRun, SourceRecord

ConnectionOverrideValue = str | int
PostConnectHook = Callable[[psycopg.Connection], None]
DatabaseRow = dict[str, Any]

_PERSON_COLUMNS = (
    "id",
    "canonical_name",
    "name_variants",
    "first_name",
    "middle_name",
    "last_name",
    "suffix",
    "occupation",
    "education",
    "bio_text",
    "bio_source_url",
    "bio_license",
    "bio_pulled_at",
    "date_of_birth",
    "year_of_birth",
    "identifiers",
    "primary_address_id",
    "er_cluster_id",
    "er_confidence",
    "created_at",
    "updated_at",
)
_PERSON_BIO_COLUMNS = (
    "bio_text",
    "bio_source_url",
    "bio_license",
    "bio_pulled_at",
)
_PERSON_COLUMNS_WITHOUT_BIO = tuple(column for column in _PERSON_COLUMNS if column not in _PERSON_BIO_COLUMNS)
_PERSON_HAS_BIO_COLUMNS: bool | None = None

_ORGANIZATION_COLUMNS = (
    "id",
    "canonical_name",
    "name_variants",
    "org_type",
    "identifiers",
    "registered_state",
    "formation_date",
    "dissolution_date",
    "primary_address_id",
    "er_cluster_id",
    "er_confidence",
    "created_at",
    "updated_at",
)

_ADDRESS_COLUMNS = (
    "id",
    "raw_address",
    "normalized_address",
    "street_number",
    "street_name",
    "unit",
    "city",
    "state",
    "zip5",
    "zip4",
    "county_fips",
    "geometry",
    "geocode_confidence",
    "geocode_source",
    "geocoded_at",
    "created_at",
    "updated_at",
)

_DATA_SOURCE_COLUMNS = (
    "id",
    "domain",
    "jurisdiction",
    "name",
    "source_url",
    "source_format",
    "license",
    "update_frequency",
    "last_pull_at",
    "last_pull_status",
    "record_count",
    "notes",
    "created_at",
    "updated_at",
)

_SOURCE_RECORD_COLUMNS = (
    "id",
    "data_source_id",
    "source_record_key",
    "source_url",
    "raw_fields",
    "pull_date",
    "record_hash",
    "superseded_by",
    "created_at",
)

_PERSON_PORTRAIT_COLUMNS = (
    "id",
    "person_id",
    "source_record_id",
    "status",
    "rights_status",
    "image_hash",
    "dedup_key",
    "mime_type",
    "width_px",
    "height_px",
    "source_image_url",
    "storage_uri",
    "created_at",
    "updated_at",
)

_REFRESH_RUN_COLUMNS = (
    "id",
    "job_key",
    "domain",
    "jurisdiction",
    "data_source_names",
    "pull_status",
    "started_at",
    "completed_at",
    "inserted_count",
    "skipped_count",
    "quarantined_count",
    "superseded_count",
    "error_count",
    "metadata_updates",
    "message",
    "error",
    "created_at",
)

upsert_address = db_ingest.upsert_address
find_organization_by_canonical_name = db_ingest.find_organization_by_canonical_name
find_organization_by_identifier = db_ingest.find_organization_by_identifier
find_person_by_identifier = db_ingest.find_person_by_identifier
find_person_by_name_and_zip = db_ingest.find_person_by_name_and_zip
insert_entity_source = db_ingest.insert_entity_source
insert_field_provenance = db_ingest.insert_field_provenance
insert_entity_address = db_ingest.insert_entity_address
try_insert_source_record = db_ingest.try_insert_source_record
try_insert_source_records_bulk = db_ingest.try_insert_source_records_bulk


def resolve_person_by_name_and_zip(
    conn: psycopg.Connection,
    person: Person | None,
    address: Address | None,
) -> UUID | None:
    if person is None:
        return None

    zip5 = address.zip5 if address is not None else None
    existing_person_id = None
    if person.last_name and person.first_name:
        existing_person_id = find_person_by_name_and_zip(conn, person.last_name, person.first_name, zip5)
    if existing_person_id is not None:
        return existing_person_id

    return insert_person(conn, person)


def resolve_organization_by_canonical_name(
    conn: psycopg.Connection,
    organization: Organization | None,
) -> UUID | None:
    if organization is None:
        return None

    existing_org_id = find_organization_by_canonical_name(conn, organization.canonical_name)
    if existing_org_id is not None:
        return existing_org_id

    return insert_organization(conn, organization)


def _build_connection_parameters(
    overrides: Mapping[str, ConnectionOverrideValue],
) -> dict[str, ConnectionOverrideValue]:
    env_password = os.getenv("POSTGRES_PASSWORD")
    # Remap Docker-internal hostname "db" to localhost for host-level execution,
    # but keep "db" when this process runs inside a container on the compose network.
    running_in_container = os.path.exists("/.dockerenv")
    raw_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_host = "127.0.0.1" if raw_host == "db" and not running_in_container else raw_host

    connection_parameters: dict[str, ConnectionOverrideValue] = {
        "user": os.getenv("POSTGRES_USER", "civibus"),
        "dbname": os.getenv("POSTGRES_DB", "civibus"),
        "host": pg_host,
        "port": int(os.getenv("POSTGRES_PORT", "5433")),
    }
    if env_password:
        connection_parameters["password"] = env_password

    allowed_override_keys = {"user", "password", "dbname", "host", "port"}
    unexpected_override_keys = set(overrides) - allowed_override_keys
    if unexpected_override_keys:
        invalid_keys = ", ".join(sorted(unexpected_override_keys))
        raise ValueError(f"Unsupported connection override keys: {invalid_keys}")

    for key, value in overrides.items():
        connection_parameters[key] = value

    return connection_parameters


def build_connection_parameters(
    **overrides: ConnectionOverrideValue,
) -> dict[str, ConnectionOverrideValue]:
    """Build PostgreSQL connection parameters from environment plus overrides."""
    return _build_connection_parameters(overrides)


def get_connection(
    *,
    post_connect: PostConnectHook | None = None,
    **overrides: ConnectionOverrideValue,
) -> psycopg.Connection:
    connection_parameters = build_connection_parameters(**overrides)

    try:
        connection = psycopg.connect(**connection_parameters)
    except psycopg.Error as error:
        host = connection_parameters["host"]
        port = connection_parameters["port"]
        database_name = connection_parameters["dbname"]
        raise RuntimeError(f"Unable to connect to PostgreSQL at {host}:{port}/{database_name}") from error

    connection.autocommit = False

    if post_connect is not None:
        try:
            post_connect(connection)
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            raise

    return connection


def _insert_row(
    conn: psycopg.Connection,
    table_name: str,
    columns: Sequence[str],
    values: Sequence[object],
) -> None:
    statement = SQL("INSERT INTO core.{table} ({columns}) VALUES ({values})").format(
        table=Identifier(table_name),
        columns=SQL(", ").join(Identifier(column_name) for column_name in columns),
        values=SQL(", ").join(Placeholder() for _ in columns),
    )

    with conn.cursor() as cursor:
        cursor.execute(statement, values)


def _person_has_bio_columns(conn: psycopg.Connection) -> bool:
    global _PERSON_HAS_BIO_COLUMNS
    if _PERSON_HAS_BIO_COLUMNS is None:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'core'
                  AND table_name = 'person'
                  AND column_name IN ('bio_text', 'bio_source_url', 'bio_license', 'bio_pulled_at')
                """
            )
            _PERSON_HAS_BIO_COLUMNS = int(cursor.fetchone()[0]) == len(_PERSON_BIO_COLUMNS)
    return _PERSON_HAS_BIO_COLUMNS


def _person_columns_for_schema(conn: psycopg.Connection) -> tuple[str, ...]:
    if _person_has_bio_columns(conn):
        return _PERSON_COLUMNS
    return _PERSON_COLUMNS_WITHOUT_BIO


def _select_row_by_id(
    conn: psycopg.Connection,
    table_name: str,
    columns: Sequence[str],
    record_id: UUID,
) -> DatabaseRow | None:
    statement = SQL("SELECT {columns} FROM core.{table} WHERE id = %s").format(
        columns=SQL(", ").join(Identifier(column_name) for column_name in columns),
        table=Identifier(table_name),
    )

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(statement, (record_id,))
        row = cursor.fetchone()

    return row


def _normalize_json_dictionary(value: object, field_name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        decoded_value = json.loads(value)
        if isinstance(decoded_value, dict):
            return decoded_value

    raise TypeError(f"{field_name} must deserialize to a dictionary, got {type(value).__name__}")


def _normalize_string_identifier_dictionary(value: object, field_name: str) -> dict[str, str]:
    normalized_value = _normalize_json_dictionary(value, field_name=field_name)
    return {
        key: dictionary_value for key, dictionary_value in normalized_value.items() if isinstance(dictionary_value, str)
    }


def _data_source_values(ds: DataSource) -> tuple[object, ...]:
    return (
        ds.id,
        ds.domain,
        ds.jurisdiction,
        ds.name,
        ds.source_url,
        ds.source_format,
        ds.license,
        ds.update_frequency,
        ds.last_pull_at,
        ds.last_pull_status,
        ds.record_count,
        ds.notes,
        ds.created_at,
        ds.updated_at,
    )


def insert_person(conn: psycopg.Connection, person: Person) -> UUID:
    person_columns = _person_columns_for_schema(conn)
    person_value_by_column: dict[str, object] = {
        "id": person.id,
        "canonical_name": person.canonical_name,
        "name_variants": person.name_variants,
        "first_name": person.first_name,
        "middle_name": person.middle_name,
        "last_name": person.last_name,
        "suffix": person.suffix,
        "occupation": person.occupation,
        "education": person.education,
        "bio_text": person.bio_text,
        "bio_source_url": person.bio_source_url,
        "bio_license": person.bio_license,
        "bio_pulled_at": person.bio_pulled_at,
        "date_of_birth": person.date_of_birth,
        "year_of_birth": person.year_of_birth,
        "identifiers": Jsonb(person.identifiers),
        "primary_address_id": person.primary_address_id,
        "er_cluster_id": person.er_cluster_id,
        "er_confidence": person.er_confidence,
        "created_at": person.created_at,
        "updated_at": person.updated_at,
    }
    _insert_row(
        conn,
        "person",
        person_columns,
        tuple(person_value_by_column[column_name] for column_name in person_columns),
    )
    return person.id


def select_person(conn: psycopg.Connection, person_id: UUID) -> Person | None:
    row = _select_row_by_id(conn, "person", _person_columns_for_schema(conn), person_id)
    if row is None:
        return None

    row["identifiers"] = _normalize_string_identifier_dictionary(row["identifiers"], field_name="person.identifiers")
    return Person(**row)


def update_person_bio_fields_if_missing(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    occupation: str | None,
    education: str | None,
    bio_text: str | None,
    bio_source_url: str | None,
    bio_license: str | None,
) -> tuple[str, ...]:
    """Fill empty person bio fields without overwriting existing non-empty values."""

    def _normalize_optional_text(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized if normalized != "" else None

    def _is_blank(value: str | None) -> bool:
        return value is None or value.strip() == ""

    has_bio_columns = _person_has_bio_columns(conn)
    existing_row: tuple[object, ...] | None
    with conn.cursor() as cursor:
        if has_bio_columns:
            cursor.execute(
                """
                SELECT occupation, education, bio_text, bio_source_url, bio_license
                FROM core.person
                WHERE id = %s
                """,
                (person_id,),
            )
        else:
            cursor.execute(
                """
                SELECT occupation, education
                FROM core.person
                WHERE id = %s
                """,
                (person_id,),
            )
        existing_row = cursor.fetchone()

    if existing_row is None:
        return ()

    existing_occupation = existing_row[0]
    existing_education = existing_row[1]
    existing_bio_text = existing_row[2] if has_bio_columns else None
    existing_bio_source_url = existing_row[3] if has_bio_columns else None
    existing_bio_license = existing_row[4] if has_bio_columns else None

    normalized_occupation = _normalize_optional_text(occupation)
    normalized_education = _normalize_optional_text(education)
    normalized_bio_text = _normalize_optional_text(bio_text)
    normalized_bio_source_url = _normalize_optional_text(bio_source_url)
    normalized_bio_license = _normalize_optional_text(bio_license)

    assignments: list[str] = []
    params: list[object] = []
    updated_fields: list[str] = []

    if normalized_occupation and _is_blank(existing_occupation):
        assignments.append("occupation = %s")
        params.append(normalized_occupation)
        updated_fields.append("occupation")

    if normalized_education and _is_blank(existing_education):
        assignments.append("education = %s")
        params.append(normalized_education)
        updated_fields.append("education")

    if has_bio_columns:
        wrote_bio_companion_state = False
        writing_first_bio_text = False

        if normalized_bio_text and _is_blank(existing_bio_text):
            assignments.append("bio_text = %s")
            params.append(normalized_bio_text)
            updated_fields.append("bio_text")
            wrote_bio_companion_state = True
            writing_first_bio_text = True

        # Bio metadata is companion state for biography, but rights gating can suppress
        # bio_text while still requiring source URL/license persistence.
        should_update_bio_source_url = normalized_bio_source_url is not None and (
            _is_blank(existing_bio_source_url)
            or (writing_first_bio_text and existing_bio_source_url != normalized_bio_source_url)
        )
        if should_update_bio_source_url:
            assignments.append("bio_source_url = %s")
            params.append(normalized_bio_source_url)
            updated_fields.append("bio_source_url")
            wrote_bio_companion_state = True

        should_update_bio_license = normalized_bio_license is not None and (
            _is_blank(existing_bio_license)
            or (writing_first_bio_text and existing_bio_license != normalized_bio_license)
        )
        if should_update_bio_license:
            assignments.append("bio_license = %s")
            params.append(normalized_bio_license)
            updated_fields.append("bio_license")
            wrote_bio_companion_state = True

        if wrote_bio_companion_state:
            assignments.append("bio_pulled_at = NOW()")

    if not assignments:
        return ()

    params.append(person_id)
    update_sql = f"""
        UPDATE core.person
        SET {", ".join(assignments)},
            updated_at = NOW()
        WHERE id = %s
    """
    with conn.cursor() as cursor:
        cursor.execute(update_sql, tuple(params))

    return tuple(updated_fields)


def merge_person_identifiers(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    identifiers: dict[str, str],
) -> None:
    """Merge new identifier key-value pairs into a person's JSONB identifiers column;
    keys present in both are taken from the new payload (right-side-wins semantics
    inherent to the JSONB ``||`` operator). The ``@>`` guard avoids no-op writes
    when the new payload is already a subset of what is already stored."""
    if not identifiers:
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.person
            SET identifiers = identifiers || %s,
                updated_at = NOW()
            WHERE id = %s
              AND NOT identifiers @> %s
            """,
            (Jsonb(identifiers), person_id, Jsonb(identifiers)),
        )


def insert_organization(conn: psycopg.Connection, org: Organization) -> UUID:
    _insert_row(
        conn,
        "organization",
        _ORGANIZATION_COLUMNS,
        (
            org.id,
            org.canonical_name,
            org.name_variants,
            org.org_type,
            Jsonb(org.identifiers),
            org.registered_state,
            org.formation_date,
            org.dissolution_date,
            org.primary_address_id,
            org.er_cluster_id,
            org.er_confidence,
            org.created_at,
            org.updated_at,
        ),
    )
    return org.id


def select_organization(conn: psycopg.Connection, org_id: UUID) -> Organization | None:
    row = _select_row_by_id(conn, "organization", _ORGANIZATION_COLUMNS, org_id)
    if row is None:
        return None

    row["identifiers"] = _normalize_json_dictionary(row["identifiers"], field_name="organization.identifiers")
    return Organization(**row)


def insert_address(conn: psycopg.Connection, address: Address) -> UUID:
    _insert_row(
        conn,
        "address",
        _ADDRESS_COLUMNS,
        (
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
    )
    return address.id


def select_address(conn: psycopg.Connection, address_id: UUID) -> Address | None:
    row = _select_row_by_id(conn, "address", _ADDRESS_COLUMNS, address_id)
    if row is None:
        return None

    row["geometry"] = None
    return Address(**row)


def insert_data_source(conn: psycopg.Connection, ds: DataSource) -> UUID:
    _insert_row(
        conn,
        "data_source",
        _DATA_SOURCE_COLUMNS,
        _data_source_values(ds),
    )
    return ds.id


def try_insert_data_source(conn: psycopg.Connection, ds: DataSource) -> UUID | None:
    statement = SQL(
        """
        INSERT INTO core.data_source ({columns})
        VALUES ({values})
        ON CONFLICT (domain, jurisdiction, name)
        DO NOTHING
        RETURNING id
        """
    ).format(
        columns=SQL(", ").join(Identifier(column_name) for column_name in _DATA_SOURCE_COLUMNS),
        values=SQL(", ").join(Placeholder() for _ in _DATA_SOURCE_COLUMNS),
    )

    with conn.cursor() as cursor:
        cursor.execute(statement, _data_source_values(ds))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def select_data_source(conn: psycopg.Connection, ds_id: UUID) -> DataSource | None:
    row = _select_row_by_id(conn, "data_source", _DATA_SOURCE_COLUMNS, ds_id)
    if row is None:
        return None

    return DataSource(**row)


def insert_source_record(conn: psycopg.Connection, sr: SourceRecord) -> UUID:
    _insert_row(
        conn,
        "source_record",
        _SOURCE_RECORD_COLUMNS,
        (
            sr.id,
            sr.data_source_id,
            sr.source_record_key,
            sr.source_url,
            Jsonb(sr.raw_fields),
            sr.pull_date,
            sr.record_hash,
            sr.superseded_by,
            sr.created_at,
        ),
    )
    return sr.id


def select_source_record(conn: psycopg.Connection, sr_id: UUID) -> SourceRecord | None:
    row = _select_row_by_id(conn, "source_record", _SOURCE_RECORD_COLUMNS, sr_id)
    if row is None:
        return None

    row["raw_fields"] = _normalize_json_dictionary(row["raw_fields"], field_name="source_record.raw_fields")
    return SourceRecord(**row)


def select_active_source_record_by_key(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> SourceRecord | None:
    """Return the active source record for a (data_source_id, source_record_key) pair."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return select_source_record(conn, row[0])


def _person_portrait_values(portrait: PersonPortrait) -> tuple[object, ...]:
    return (
        portrait.id,
        portrait.person_id,
        portrait.source_record_id,
        portrait.status,
        portrait.rights_status,
        portrait.image_hash,
        portrait.dedup_key,
        portrait.mime_type,
        portrait.width_px,
        portrait.height_px,
        portrait.source_image_url,
        portrait.storage_uri,
        portrait.created_at,
        portrait.updated_at,
    )


def insert_person_portrait(conn: psycopg.Connection, portrait: PersonPortrait) -> UUID:
    statement = SQL(
        """
        INSERT INTO core.person_portrait ({columns})
        VALUES ({values})
        ON CONFLICT (person_id, dedup_key)
        DO UPDATE SET
            source_record_id = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.source_record_id
                ELSE EXCLUDED.source_record_id
            END,
            status = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.status
                ELSE EXCLUDED.status
            END,
            rights_status = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.rights_status
                ELSE EXCLUDED.rights_status
            END,
            mime_type = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.mime_type
                ELSE EXCLUDED.mime_type
            END,
            width_px = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.width_px
                ELSE EXCLUDED.width_px
            END,
            height_px = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.height_px
                ELSE EXCLUDED.height_px
            END,
            source_image_url = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.source_image_url
                ELSE EXCLUDED.source_image_url
            END,
            storage_uri = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.storage_uri
                ELSE EXCLUDED.storage_uri
            END,
            updated_at = CASE
                WHEN core.person_portrait.status = 'takedown_requested' THEN core.person_portrait.updated_at
                ELSE EXCLUDED.updated_at
            END
        RETURNING id
        """
    ).format(
        columns=SQL(", ").join(Identifier(column_name) for column_name in _PERSON_PORTRAIT_COLUMNS),
        values=SQL(", ").join(Placeholder() for _ in _PERSON_PORTRAIT_COLUMNS),
    )

    with conn.cursor() as cursor:
        cursor.execute(statement, _person_portrait_values(portrait))
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("insert_person_portrait expected RETURNING id row")
    return row[0]


def select_person_portrait(conn: psycopg.Connection, portrait_id: UUID) -> PersonPortrait | None:
    row = _select_row_by_id(conn, "person_portrait", _PERSON_PORTRAIT_COLUMNS, portrait_id)
    if row is None:
        return None
    return PersonPortrait(**row)


def select_active_roster_portrait_for_person(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
) -> PersonPortrait | None:
    """Return the newest active portrait whose provenance points at a registered roster source."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT pp.id
            FROM core.person_portrait AS pp
            JOIN core.source_record AS sr ON sr.id = pp.source_record_id
            JOIN core.data_source AS ds ON ds.id = sr.data_source_id
            WHERE pp.person_id = %s
              AND pp.status = 'active'
              AND sr.superseded_by IS NULL
              AND ds.domain = 'civics'
              AND CASE
                    WHEN ds.notes ~ '^\s*\\{'
                    THEN COALESCE(ds.notes::jsonb->>'roster_source', 'false') = 'true'
                    ELSE FALSE
                  END
            ORDER BY pp.updated_at DESC, pp.created_at DESC, pp.id DESC
            LIMIT 1
            """,
            (person_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return select_person_portrait(conn, row[0])


def mark_person_portrait_takedown_requested(
    conn: psycopg.Connection,
    portrait_id: UUID,
) -> PersonPortrait | None:
    """Mark a portrait row as takedown requested and return the updated row."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE core.person_portrait
            SET status = 'takedown_requested', updated_at = now()
            WHERE id = %s
            RETURNING id, person_id, source_record_id, status, rights_status, image_hash, dedup_key,
                      mime_type, width_px, height_px, source_image_url, storage_uri, created_at, updated_at
            """,
            (portrait_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return PersonPortrait(**row)


def person_has_takedown_requested_portrait_source_image(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    source_image_url: str,
) -> bool:
    """Return whether a takedown-requested portrait exists for the person+source URL pair."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM core.person_portrait
                WHERE person_id = %s
                  AND source_image_url = %s
                  AND status = 'takedown_requested'
            )
            """,
            (person_id, source_image_url),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _refresh_run_values(refresh_run: RefreshRun) -> tuple[object, ...]:
    return (
        refresh_run.id,
        refresh_run.job_key,
        refresh_run.domain,
        refresh_run.jurisdiction,
        refresh_run.data_source_names,
        refresh_run.pull_status,
        refresh_run.started_at,
        refresh_run.completed_at,
        refresh_run.inserted_count,
        refresh_run.skipped_count,
        refresh_run.quarantined_count,
        refresh_run.superseded_count,
        refresh_run.error_count,
        refresh_run.metadata_updates,
        refresh_run.message,
        refresh_run.error,
        refresh_run.created_at,
    )


def insert_refresh_run(conn: psycopg.Connection, refresh_run: RefreshRun) -> UUID:
    _insert_row(
        conn,
        "refresh_run",
        _REFRESH_RUN_COLUMNS,
        _refresh_run_values(refresh_run),
    )
    return refresh_run.id


def select_refresh_run(conn: psycopg.Connection, refresh_run_id: UUID) -> RefreshRun | None:
    row = _select_row_by_id(conn, "refresh_run", _REFRESH_RUN_COLUMNS, refresh_run_id)
    if row is None:
        return None
    return RefreshRun(**row)
