"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_cross_domain_er_and_property_graph/civibus_dev/domains/property/ingest/loader.py.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_canonical_name,
    find_organization_by_identifier,
    find_person_by_identifier,
    insert_entity_address,
    insert_entity_source,
    insert_organization,
    insert_person,
    try_insert_data_source,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.property.entity_extractors.extract import extract_owner
from domains.property.ingest.durham_source import (
    _optional_date,
    _optional_decimal,
    _optional_int,
    _optional_text,
    _required_nested_text,
    _required_text,
    build_durham_source_url,
    load_durham_config,
)

_DURHAM_DOMAIN = "property"


@dataclass(frozen=True)
class _OwnershipInsertPayload:
    parcel_id: UUID
    owner_name: str
    owner_mail_line1: str | None
    owner_mail_line2: str | None
    owner_mail_line3: str | None
    owner_mail_city: str | None
    owner_mail_state: str | None
    owner_mail_zip5: str | None
    ownership_recorded_at: date | None
    owner_person_id: UUID | None
    owner_organization_id: UUID | None
    owner_address_id: UUID | None
    source_record_id: UUID


@dataclass(frozen=True)
class _OwnershipInsertContext:

    parcel_id: UUID
    owner_mail_line1: str | None
    owner_mail_line2: str | None
    owner_mail_line3: str | None
    owner_mail_city: str | None
    owner_mail_state: str | None
    owner_mail_zip5: str | None
    ownership_recorded_at: date | None
    owner_address_id: UUID | None
    source_record_id: UUID

    @classmethod
    def from_normalized_record(
        cls,
        normalized_record: Mapping[str, object],
        parcel_id: UUID,
        owner_address_id: UUID | None,
        source_record_id: UUID,
    ) -> _OwnershipInsertContext:
        return cls(
            parcel_id=parcel_id,
            owner_mail_line1=_optional_text(normalized_record.get("owner_mail_line1")),
            owner_mail_line2=_optional_text(normalized_record.get("owner_mail_line2")),
            owner_mail_line3=_optional_text(normalized_record.get("owner_mail_line3")),
            owner_mail_city=_optional_text(normalized_record.get("owner_mail_city")),
            owner_mail_state=_optional_text(normalized_record.get("owner_mail_state")),
            owner_mail_zip5=_optional_text(normalized_record.get("owner_mail_zip5")),
            ownership_recorded_at=_optional_date(normalized_record.get("deed_date")),
            owner_address_id=owner_address_id,
            source_record_id=source_record_id,
        )

    def payload_for_owner(
        self,
        owner_name: str,
        owner_person_id: UUID | None,
        owner_organization_id: UUID | None,
    ) -> _OwnershipInsertPayload:
        return _OwnershipInsertPayload(
            parcel_id=self.parcel_id,
            owner_name=owner_name,
            owner_mail_line1=self.owner_mail_line1,
            owner_mail_line2=self.owner_mail_line2,
            owner_mail_line3=self.owner_mail_line3,
            owner_mail_city=self.owner_mail_city,
            owner_mail_state=self.owner_mail_state,
            owner_mail_zip5=self.owner_mail_zip5,
            ownership_recorded_at=self.ownership_recorded_at,
            owner_person_id=owner_person_id,
            owner_organization_id=owner_organization_id,
            owner_address_id=self.owner_address_id,
            source_record_id=self.source_record_id,
        )


@dataclass(frozen=True)
class _ActiveSourceRecord:
    id: UUID
    source_url: str | None
    record_hash: str | None


def _select_durham_data_source_id(conn: psycopg.Connection, jurisdiction_slug: str, source_name: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (_DURHAM_DOMAIN, jurisdiction_slug, source_name),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _select_active_source_record(
    conn: psycopg.Connection,
    data_source_id: UUID,
    source_record_key: str,
) -> _ActiveSourceRecord | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, source_url, record_hash
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
    return _ActiveSourceRecord(id=row[0], source_url=row[1], record_hash=row[2])


def _sync_durham_data_source_metadata(
    conn: psycopg.Connection,
    data_source_id: UUID,
    source_payload: Mapping[str, object],
    source_url: str,
) -> None:
    source_format = _optional_text(source_payload.get("source_format"))
    license_name = _optional_text(source_payload.get("license"))
    update_frequency = _optional_text(source_payload.get("update_frequency"))

    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.data_source
            SET source_url = %s,
                source_format = %s,
                license = %s,
                update_frequency = %s
            WHERE id = %s
              AND (
                    source_url IS DISTINCT FROM %s
                 OR source_format IS DISTINCT FROM %s
                 OR license IS DISTINCT FROM %s
                 OR update_frequency IS DISTINCT FROM %s
              )
            """,
            (
                source_url,
                source_format,
                license_name,
                update_frequency,
                data_source_id,
                source_url,
                source_format,
                license_name,
                update_frequency,
            ),
        )


def ensure_durham_data_source(
    conn: psycopg.Connection,
    config: Mapping[str, object] | None = None,
) -> UUID:
    config_payload = config if config is not None else load_durham_config()
    source_payload = config_payload.get("source")
    if not isinstance(source_payload, Mapping):
        raise ValueError("Durham config must include a source mapping")
    jurisdiction_slug = _required_nested_text(config_payload, "jurisdiction", "slug")
    source_name = _required_nested_text(config_payload, "source", "name")
    source_url = _required_nested_text(config_payload, "source", "arcgis_query_url")

    existing_id = _select_durham_data_source_id(conn, jurisdiction_slug, source_name)
    if existing_id is not None:
        _sync_durham_data_source_metadata(conn, existing_id, source_payload, source_url)
        return existing_id

    data_source = DataSource(
        domain=_DURHAM_DOMAIN,
        jurisdiction=jurisdiction_slug,
        name=source_name,
        source_url=source_url,
        source_format=_optional_text(source_payload.get("source_format")),
        license=_optional_text(source_payload.get("license")),
        update_frequency=_optional_text(source_payload.get("update_frequency")),
    )
    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id

    existing_id = _select_durham_data_source_id(conn, jurisdiction_slug, source_name)
    if existing_id is not None:
        _sync_durham_data_source_metadata(conn, existing_id, source_payload, source_url)
        return existing_id

    raise RuntimeError("Durham data source insert reported a conflict, but the existing row could not be selected")


def ensure_durham_jurisdiction(conn: psycopg.Connection, config: Mapping[str, object] | None = None) -> UUID:
    config_payload = config if config is not None else load_durham_config()
    name = _required_nested_text(config_payload, "jurisdiction", "name")
    jurisdiction_type = _required_nested_text(config_payload, "jurisdiction", "type")
    fips = _required_nested_text(config_payload, "jurisdiction", "fips")
    state = _required_nested_text(config_payload, "jurisdiction", "state")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.jurisdiction (name, jurisdiction_type, fips, state)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fips) WHERE fips IS NOT NULL
            DO UPDATE SET
                name = EXCLUDED.name,
                jurisdiction_type = EXCLUDED.jurisdiction_type,
                state = EXCLUDED.state
            RETURNING id
            """,
            (name, jurisdiction_type, fips, state),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Durham jurisdiction insert did not return an id")
    return row[0]


def _build_source_record(data_source_id: UUID, normalized_record: Mapping[str, object]) -> SourceRecord:
    reid = _required_text(normalized_record.get("reid"), field_name="reid")
    pin = _required_text(normalized_record.get("pin"), field_name="pin")
    source_url = build_durham_source_url(pin)
    provided_source_url = _optional_text(normalized_record.get("source_url"))
    if provided_source_url is not None and provided_source_url != source_url:
        raise ValueError("normalized_record.source_url must match the PIN-derived Durham source URL")
    raw_record = normalized_record.get("raw_record")
    if not isinstance(raw_record, Mapping):
        raise ValueError("normalized_record.raw_record must be a mapping")
    raw_fields = {str(key): value for key, value in raw_record.items()}

    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=reid,
        source_url=source_url,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )


def load_durham_record(
    conn: psycopg.Connection,
    data_source_id: UUID,
    jurisdiction_id: UUID,
    normalized_record: Mapping[str, object],
) -> bool:
    source_record = _build_source_record(data_source_id, normalized_record)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        existing_source_record = _select_active_source_record(conn, data_source_id, source_record.source_record_key)
        if existing_source_record is None:
            raise RuntimeError(
                "Source record insert reported a conflict, but the active core.source_record row could not be found"
            )

        if (
            existing_source_record.record_hash == source_record.record_hash
            and existing_source_record.source_url == source_record.source_url
        ):
            return False

        raise ValueError(
            "Source record key conflict with conflicting source payload: "
            f"key={source_record.source_record_key} "
            f"existing_hash={existing_source_record.record_hash} incoming_hash={source_record.record_hash} "
            f"existing_source_url={existing_source_record.source_url} incoming_source_url={source_record.source_url}"
        )

    owner_record = normalized_record.get("owner_record")
    if not isinstance(owner_record, Mapping):
        raise ValueError("normalized_record.owner_record must be a mapping")
    owner_extraction = extract_owner(dict(owner_record))

    _persist_durham_property_record(
        conn=conn,
        normalized_record=normalized_record,
        owner_extraction=owner_extraction,
        source_record_id=source_record_id,
        jurisdiction_id=jurisdiction_id,
    )
    return True


def load_durham_records(
    conn: psycopg.Connection,
    data_source_id: UUID,
    jurisdiction_id: UUID,
    normalized_records: Sequence[Mapping[str, object]],
    *,
    per_record_savepoints: bool = False,
) -> tuple[int, int, int]:
    inserted_count = 0
    skipped_count = 0
    error_count = 0
    for normalized_record in normalized_records:
        if per_record_savepoints:
            try:
                with conn.transaction():
                    inserted = load_durham_record(conn, data_source_id, jurisdiction_id, normalized_record)
            except Exception:  # noqa: BLE001
                error_count += 1
                continue
        else:
            inserted = load_durham_record(conn, data_source_id, jurisdiction_id, normalized_record)

        if inserted:
            inserted_count += 1
        else:
            skipped_count += 1
    return inserted_count, skipped_count, error_count


def _persist_durham_property_record(
    *,
    conn: psycopg.Connection,
    normalized_record: Mapping[str, object],
    owner_extraction: Mapping[str, object],
    source_record_id: UUID,
    jurisdiction_id: UUID,
) -> None:
    parcel_id = _upsert_parcel(conn, normalized_record, source_record_id, jurisdiction_id)
    _upsert_assessment(conn, parcel_id, normalized_record, source_record_id)
    _insert_ownership_rows(conn, parcel_id, normalized_record, owner_extraction, source_record_id)


def _upsert_parcel(
    conn: psycopg.Connection,
    normalized_record: Mapping[str, object],
    source_record_id: UUID,
    jurisdiction_id: UUID,
) -> UUID:
    reid = _required_text(normalized_record.get("reid"), field_name="reid")
    pin = _required_text(normalized_record.get("pin"), field_name="pin")
    site_address = _required_text(normalized_record.get("site_address"), field_name="site_address")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO prop.parcel (
                reid,
                pin,
                site_address,
                property_description,
                city,
                zoning_class,
                land_class,
                acreage,
                neighborhood,
                fire_district,
                is_pending,
                deed_date,
                deed_book,
                deed_page,
                jurisdiction_id,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (reid)
            DO UPDATE SET
                pin = EXCLUDED.pin,
                site_address = EXCLUDED.site_address,
                property_description = EXCLUDED.property_description,
                city = EXCLUDED.city,
                zoning_class = EXCLUDED.zoning_class,
                land_class = EXCLUDED.land_class,
                acreage = EXCLUDED.acreage,
                neighborhood = EXCLUDED.neighborhood,
                fire_district = EXCLUDED.fire_district,
                is_pending = EXCLUDED.is_pending,
                deed_date = EXCLUDED.deed_date,
                deed_book = EXCLUDED.deed_book,
                deed_page = EXCLUDED.deed_page,
                jurisdiction_id = EXCLUDED.jurisdiction_id,
                source_record_id = EXCLUDED.source_record_id
            RETURNING id
            """,
            (
                reid,
                pin,
                site_address,
                _optional_text(normalized_record.get("property_description")),
                _optional_text(normalized_record.get("city")),
                _optional_text(normalized_record.get("zoning_class")),
                _optional_text(normalized_record.get("land_class")),
                _optional_decimal(normalized_record.get("acreage")),
                _optional_text(normalized_record.get("neighborhood")),
                _optional_text(normalized_record.get("fire_district")),
                bool(normalized_record.get("is_pending")),
                _optional_date(normalized_record.get("deed_date")),
                _optional_text(normalized_record.get("deed_book")),
                _optional_text(normalized_record.get("deed_page")),
                jurisdiction_id,
                source_record_id,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Parcel upsert did not return an id")
    return row[0]


def _should_persist_assessment(normalized_record: Mapping[str, object]) -> bool:
    if bool(normalized_record.get("is_pending")):
        return False

    tax_year = _optional_int(normalized_record.get("tax_year"))
    if tax_year is None:
        return False

    return any(
        value is not None
        for value in (
            _optional_decimal(normalized_record.get("land_assessed_value")),
            _optional_decimal(normalized_record.get("improvement_assessed_value")),
            _optional_decimal(normalized_record.get("total_assessed_value")),
            _optional_date(normalized_record.get("assessed_at")),
            _optional_int(normalized_record.get("heated_area")),
        )
    )


def _upsert_assessment(
    conn: psycopg.Connection,
    parcel_id: UUID,
    normalized_record: Mapping[str, object],
    source_record_id: UUID,
) -> None:
    if not _should_persist_assessment(normalized_record):
        return

    tax_year = _optional_int(normalized_record.get("tax_year"))
    if tax_year is None:
        return

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO prop.assessment (
                parcel_id,
                tax_year,
                land_assessed_value,
                improvement_assessed_value,
                total_assessed_value,
                assessed_at,
                heated_area,
                exemption_description,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (parcel_id, tax_year)
            DO UPDATE SET
                land_assessed_value = EXCLUDED.land_assessed_value,
                improvement_assessed_value = EXCLUDED.improvement_assessed_value,
                total_assessed_value = EXCLUDED.total_assessed_value,
                assessed_at = EXCLUDED.assessed_at,
                heated_area = EXCLUDED.heated_area,
                exemption_description = EXCLUDED.exemption_description,
                source_record_id = EXCLUDED.source_record_id
            """,
            (
                parcel_id,
                tax_year,
                _optional_decimal(normalized_record.get("land_assessed_value")),
                _optional_decimal(normalized_record.get("improvement_assessed_value")),
                _optional_decimal(normalized_record.get("total_assessed_value")),
                _optional_date(normalized_record.get("assessed_at")),
                _optional_int(normalized_record.get("heated_area")),
                _optional_text(normalized_record.get("exemption_description")),
                source_record_id,
            ),
        )


def _insert_ownership_rows(
    conn: psycopg.Connection,
    parcel_id: UUID,
    normalized_record: Mapping[str, object],
    owner_extraction: Mapping[str, object],
    source_record_id: UUID,
) -> None:
    # Clear stale ownership rows so re-ingest is idempotent (mirrors parcel/assessment upsert)
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM prop.ownership WHERE parcel_id = %s", (parcel_id,))

    owner_address_id = _resolve_owner_address_id(conn, owner_extraction, source_record_id)
    ownership_context = _OwnershipInsertContext.from_normalized_record(
        normalized_record,
        parcel_id,
        owner_address_id,
        source_record_id,
    )
    organization = owner_extraction.get("organization")
    persons = owner_extraction.get("persons")

    if isinstance(organization, Organization):
        organization_id = _resolve_owner_organization_id(conn, organization)
        _link_owner_entity(conn, "organization", organization_id, owner_address_id, source_record_id)
        _insert_ownership_row(
            conn,
            ownership_context.payload_for_owner(_owner_name_as_filed(organization), None, organization_id),
        )
        return

    if isinstance(persons, list) and persons:
        for person in persons:
            if not isinstance(person, Person):
                continue
            person_id = _resolve_owner_person_id(conn, person)
            _link_owner_entity(conn, "person", person_id, owner_address_id, source_record_id)
            owner_name = _owner_name_as_filed(person)
            _insert_ownership_row(
                conn,
                ownership_context.payload_for_owner(owner_name, person_id, None),
            )
        return

    owner_name = _required_text(normalized_record.get("owner_name_as_filed"), field_name="owner_name_as_filed")
    _insert_ownership_row(conn, ownership_context.payload_for_owner(owner_name, None, None))


def _resolve_owner_person_id(conn: psycopg.Connection, person: Person) -> UUID:
    owner_name_as_filed = person.identifiers.get("owner_name_as_filed")
    if owner_name_as_filed is not None:
        existing_id = find_person_by_identifier(conn, "owner_name_as_filed", owner_name_as_filed)
        if existing_id is not None:
            return existing_id
    return insert_person(conn, person)


def _resolve_owner_organization_id(conn: psycopg.Connection, organization: Organization) -> UUID:
    owner_name_as_filed = organization.identifiers.get("owner_name_as_filed")
    if owner_name_as_filed is not None:
        existing_by_identifier = find_organization_by_identifier(conn, "owner_name_as_filed", owner_name_as_filed)
        if existing_by_identifier is not None:
            return existing_by_identifier

    existing_by_name = find_organization_by_canonical_name(conn, organization.canonical_name)
    if existing_by_name is not None:
        return existing_by_name

    return insert_organization(conn, organization)


def _resolve_owner_address_id(
    conn: psycopg.Connection,
    owner_extraction: Mapping[str, object],
    source_record_id: UUID,
) -> UUID | None:
    address = owner_extraction.get("address")
    if not isinstance(address, Address):
        return None
    address_id = upsert_address(conn, address)
    insert_entity_source(conn, "address", address_id, source_record_id, "owner_mailing_address")
    return address_id


def _link_owner_entity(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
    owner_address_id: UUID | None,
    source_record_id: UUID,
) -> None:
    insert_entity_source(conn, entity_type, entity_id, source_record_id, "owner")
    if owner_address_id is None:
        return
    insert_entity_address(conn, entity_type, entity_id, owner_address_id, source_record_id, "mailing")


def _owner_name_as_filed(entity: Person | Organization) -> str:
    return entity.identifiers.get("owner_name_as_filed") or entity.canonical_name


def _insert_ownership_row(
    conn: psycopg.Connection,
    ownership: _OwnershipInsertPayload,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO prop.ownership (
                parcel_id,
                owner_name,
                owner_mail_line1,
                owner_mail_line2,
                owner_mail_line3,
                owner_mail_city,
                owner_mail_state,
                owner_mail_zip5,
                ownership_recorded_at,
                owner_person_id,
                owner_organization_id,
                owner_address_id,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ownership.parcel_id,
                ownership.owner_name,
                ownership.owner_mail_line1,
                ownership.owner_mail_line2,
                ownership.owner_mail_line3,
                ownership.owner_mail_city,
                ownership.owner_mail_state,
                ownership.owner_mail_zip5,
                ownership.ownership_recorded_at,
                ownership.owner_person_id,
                ownership.owner_organization_id,
                ownership.owner_address_id,
                ownership.source_record_id,
            ),
        )
