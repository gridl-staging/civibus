
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
from core.types.python.models import Address, DataSource, Organization, Person, SourceRecord

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
    "date_of_birth",
    "year_of_birth",
    "identifiers",
    "primary_address_id",
    "er_cluster_id",
    "er_confidence",
    "created_at",
    "updated_at",
)

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

upsert_address = db_ingest.upsert_address
find_organization_by_canonical_name = db_ingest.find_organization_by_canonical_name
find_organization_by_identifier = db_ingest.find_organization_by_identifier
find_person_by_identifier = db_ingest.find_person_by_identifier
find_person_by_name_and_zip = db_ingest.find_person_by_name_and_zip
insert_entity_source = db_ingest.insert_entity_source
insert_field_provenance = db_ingest.insert_field_provenance
insert_entity_address = db_ingest.insert_entity_address
try_insert_source_record = db_ingest.try_insert_source_record


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
    # Remap Docker-internal hostname "db" to localhost for host-level execution.
    # Mirrors env_lib.sh:load_civibus_env() which does the same for shell scripts.
    raw_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_host = "127.0.0.1" if raw_host == "db" else raw_host

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
    _insert_row(
        conn,
        "person",
        _PERSON_COLUMNS,
        (
            person.id,
            person.canonical_name,
            person.name_variants,
            person.first_name,
            person.middle_name,
            person.last_name,
            person.suffix,
            person.date_of_birth,
            person.year_of_birth,
            Jsonb(person.identifiers),
            person.primary_address_id,
            person.er_cluster_id,
            person.er_confidence,
            person.created_at,
            person.updated_at,
        ),
    )
    return person.id


def select_person(conn: psycopg.Connection, person_id: UUID) -> Person | None:
    row = _select_row_by_id(conn, "person", _PERSON_COLUMNS, person_id)
    if row is None:
        return None

    row["identifiers"] = _normalize_json_dictionary(row["identifiers"], field_name="person.identifiers")
    return Person(**row)


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
