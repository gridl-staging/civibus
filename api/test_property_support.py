from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import psycopg

from core.db import (
    insert_address,
    insert_data_source,
    insert_organization,
    insert_person,
    insert_source_record,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
)

_PARCEL_INSERT_SQL = """
    INSERT INTO prop.parcel (
        id,
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
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_ASSESSMENT_INSERT_SQL = """
    INSERT INTO prop.assessment (
        id,
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
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_OWNERSHIP_INSERT_SQL = """
    INSERT INTO prop.ownership (
        id,
        parcel_id,
        owner_name,
        owner_mail_line1,
        owner_mail_line2,
        owner_mail_line3,
        owner_mail_city,
        owner_mail_state,
        owner_mail_zip5,
        ownership_recorded_at,
        valid_period,
        date_precision,
        owner_person_id,
        owner_organization_id,
        owner_address_id,
        source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::daterange, %s::core.date_precision, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class ParcelRowSeed:
    id: UUID
    reid: str
    pin: str
    site_address: str
    property_description: str | None = None
    city: str | None = None
    zoning_class: str | None = None
    land_class: str | None = None
    acreage: Decimal | None = None
    neighborhood: str | None = None
    fire_district: str | None = None
    is_pending: bool = False
    deed_date: date | None = None
    deed_book: str | None = None
    deed_page: str | None = None
    jurisdiction_id: UUID | None = None
    source_record_id: UUID | None = None


@dataclass(frozen=True)
class AssessmentRowSeed:
    id: UUID
    parcel_id: UUID
    tax_year: int
    source_record_id: UUID | None = None
    land_assessed_value: Decimal | None = None
    improvement_assessed_value: Decimal | None = None
    total_assessed_value: Decimal | None = None
    assessed_at: date | None = None
    heated_area: int | None = None
    exemption_description: str | None = None


@dataclass(frozen=True)
class OwnershipRowSeed:
    id: UUID
    parcel_id: UUID
    owner_name: str
    source_record_id: UUID | None = None
    owner_mail_line1: str | None = None
    owner_mail_line2: str | None = None
    owner_mail_line3: str | None = None
    owner_mail_city: str | None = None
    owner_mail_state: str | None = None
    owner_mail_zip5: str | None = None
    ownership_recorded_at: date | None = None
    valid_period: str = "[,)"
    date_precision: str = "day"
    owner_person_id: UUID | None = None
    owner_organization_id: UUID | None = None
    owner_address_id: UUID | None = None


def _execute_insert(conn: psycopg.Connection, *, query: str, params: tuple[object, ...]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(query, params)


def insert_jurisdiction_for_test(
    db_conn: psycopg.Connection,
    *,
    fips: str,
    name: str = "Durham County",
) -> UUID:
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.jurisdiction (name, jurisdiction_type, fips, state)
            VALUES (%s, 'county', %s, 'NC')
            RETURNING id
            """,
            (name, fips),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Jurisdiction insert did not return an id")
    return row[0]


def insert_property_data_source_for_test(
    db_conn: psycopg.Connection,
    *,
    jurisdiction: str,
    name_suffix: str,
) -> DataSource:
    data_source = DataSource(
        domain="property",
        jurisdiction=jurisdiction,
        name=f"Property API Source {name_suffix}",
        source_url="https://example.org/property-source",
    )
    insert_data_source(db_conn, data_source)
    return data_source


def insert_property_source_record_for_test(
    db_conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_source_id: UUID,
    source_record_key: str,
    source_url: str,
    pull_date: datetime,
) -> SourceRecord:
    raw_fields = {"source_record_key": source_record_key}
    source_record = SourceRecord(
        id=source_record_id,
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=source_url,
        raw_fields=raw_fields,
        pull_date=pull_date,
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(db_conn, source_record)
    return source_record


def insert_parcel_row(conn: psycopg.Connection, parcel: ParcelRowSeed) -> None:
    _execute_insert(
        conn,
        query=_PARCEL_INSERT_SQL,
        params=(
            parcel.id,
            parcel.reid,
            parcel.pin,
            parcel.site_address,
            parcel.property_description,
            parcel.city,
            parcel.zoning_class,
            parcel.land_class,
            parcel.acreage,
            parcel.neighborhood,
            parcel.fire_district,
            parcel.is_pending,
            parcel.deed_date,
            parcel.deed_book,
            parcel.deed_page,
            parcel.jurisdiction_id,
            parcel.source_record_id,
        ),
    )


def insert_assessment_row(conn: psycopg.Connection, assessment: AssessmentRowSeed) -> None:
    _execute_insert(
        conn,
        query=_ASSESSMENT_INSERT_SQL,
        params=(
            assessment.id,
            assessment.parcel_id,
            assessment.tax_year,
            assessment.land_assessed_value,
            assessment.improvement_assessed_value,
            assessment.total_assessed_value,
            assessment.assessed_at,
            assessment.heated_area,
            assessment.exemption_description,
            assessment.source_record_id,
        ),
    )


def insert_ownership_row(conn: psycopg.Connection, ownership: OwnershipRowSeed) -> None:
    _execute_insert(
        conn,
        query=_OWNERSHIP_INSERT_SQL,
        params=(
            ownership.id,
            ownership.parcel_id,
            ownership.owner_name,
            ownership.owner_mail_line1,
            ownership.owner_mail_line2,
            ownership.owner_mail_line3,
            ownership.owner_mail_city,
            ownership.owner_mail_state,
            ownership.owner_mail_zip5,
            ownership.ownership_recorded_at,
            ownership.valid_period,
            ownership.date_precision,
            ownership.owner_person_id,
            ownership.owner_organization_id,
            ownership.owner_address_id,
            ownership.source_record_id,
        ),
    )


def seed_parcel_detail_fixture(db_conn: psycopg.Connection) -> dict[str, object]:
    jurisdiction_id = insert_jurisdiction_for_test(db_conn, fips="37063", name="Durham County")
    data_source = insert_property_data_source_for_test(
        db_conn,
        jurisdiction="states/nc/counties/durham",
        name_suffix="detail",
    )

    parcel_source = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001001"),
        data_source_id=data_source.id,
        source_record_key="parcel-detail",
        source_url="https://example.org/property/parcel-detail",
        pull_date=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
    )
    assessment_newer_source = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001002"),
        data_source_id=data_source.id,
        source_record_key="assessment-2025",
        source_url="https://example.org/property/assessment-2025",
        pull_date=datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc),
    )
    assessment_older_source = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001003"),
        data_source_id=data_source.id,
        source_record_key="assessment-2024",
        source_url="https://example.org/property/assessment-2024",
        pull_date=datetime(2026, 3, 15, 13, 0, tzinfo=timezone.utc),
    )
    ownership_newer_source = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001004"),
        data_source_id=data_source.id,
        source_record_key="ownership-person",
        source_url="https://example.org/property/ownership-person",
        pull_date=datetime(2026, 3, 16, 14, 0, tzinfo=timezone.utc),
    )
    ownership_older_source = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001005"),
        data_source_id=data_source.id,
        source_record_key="ownership-org",
        source_url="https://example.org/property/ownership-org",
        pull_date=datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc),
    )

    owner_person = Person(canonical_name="Jane Parcel Owner")
    owner_organization = Organization(canonical_name="Parcel Holdings LLC")
    owner_address = Address(raw_address="PO BOX 100, DURHAM, NC 27701", city="Durham", state="NC", zip5="27701")
    insert_person(db_conn, owner_person)
    insert_organization(db_conn, owner_organization)
    insert_address(db_conn, owner_address)

    parcel_id = UUID("00000000-0000-0000-0000-000000001010")
    insert_parcel_row(
        db_conn,
        ParcelRowSeed(
            id=parcel_id,
            reid="200000001",
            pin="0999999999",
            site_address="123 MAIN ST",
            property_description="Single family home",
            city="Durham",
            zoning_class="R-20",
            land_class="Residential",
            acreage=Decimal("1.2500"),
            neighborhood="Northside",
            fire_district="Durham",
            is_pending=False,
            deed_date=date(2024, 1, 15),
            deed_book="1234",
            deed_page="567",
            jurisdiction_id=jurisdiction_id,
            source_record_id=parcel_source.id,
        ),
    )

    assessment_newer_id = UUID("00000000-0000-0000-0000-000000001011")
    assessment_older_id = UUID("00000000-0000-0000-0000-000000001012")
    insert_assessment_row(
        db_conn,
        AssessmentRowSeed(
            id=assessment_newer_id,
            parcel_id=parcel_id,
            tax_year=2025,
            land_assessed_value=Decimal("150000.00"),
            improvement_assessed_value=Decimal("200000.00"),
            total_assessed_value=Decimal("350000.00"),
            assessed_at=date(2025, 1, 31),
            heated_area=2500,
            exemption_description="Homestead",
            source_record_id=assessment_newer_source.id,
        ),
    )
    insert_assessment_row(
        db_conn,
        AssessmentRowSeed(
            id=assessment_older_id,
            parcel_id=parcel_id,
            tax_year=2024,
            land_assessed_value=Decimal("130000.00"),
            improvement_assessed_value=Decimal("190000.00"),
            total_assessed_value=Decimal("320000.00"),
            assessed_at=date(2024, 1, 31),
            heated_area=2400,
            exemption_description=None,
            source_record_id=assessment_older_source.id,
        ),
    )

    ownership_newer_id = UUID("00000000-0000-0000-0000-000000001013")
    ownership_older_id = UUID("00000000-0000-0000-0000-000000001014")
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=ownership_newer_id,
            parcel_id=parcel_id,
            owner_name="Jane Parcel Owner",
            owner_mail_line1="PO BOX 100",
            owner_mail_city="Durham",
            owner_mail_state="NC",
            owner_mail_zip5="27701",
            ownership_recorded_at=date(2025, 2, 1),
            valid_period="[2025-02-01,)",
            date_precision="day",
            owner_person_id=owner_person.id,
            owner_organization_id=None,
            owner_address_id=owner_address.id,
            source_record_id=ownership_newer_source.id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=ownership_older_id,
            parcel_id=parcel_id,
            owner_name="Parcel Holdings LLC",
            owner_mail_line1="PO BOX 200",
            owner_mail_line2="ATTN: TAX",
            owner_mail_line3="SUITE 10",
            owner_mail_city="Durham",
            owner_mail_state="NC",
            owner_mail_zip5="27701",
            ownership_recorded_at=date(2024, 2, 1),
            valid_period="[2024-02-01,2025-02-01)",
            date_precision="month",
            owner_person_id=None,
            owner_organization_id=owner_organization.id,
            owner_address_id=owner_address.id,
            source_record_id=ownership_older_source.id,
        ),
    )

    return {
        "parcel_id": parcel_id,
        "owner_person_id": owner_person.id,
        "owner_organization_id": owner_organization.id,
        "owner_address_id": owner_address.id,
        "assessment_ids_in_order": [assessment_newer_id, assessment_older_id],
        "ownership_ids_in_order": [ownership_newer_id, ownership_older_id],
    }


def seed_parcel_list_fixture(db_conn: psycopg.Connection) -> dict[str, UUID]:
    # Pagination assertions depend on a closed parcel set, so clear existing rows first.
    db_conn.execute("DELETE FROM prop.assessment")
    db_conn.execute("DELETE FROM prop.ownership")
    db_conn.execute("DELETE FROM prop.parcel")

    jurisdiction_id = insert_jurisdiction_for_test(db_conn, fips="37067", name="Durham City")
    data_source = insert_property_data_source_for_test(
        db_conn,
        jurisdiction="states/nc/counties/durham",
        name_suffix="list",
    )

    source_record_alpha_a = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001101"),
        data_source_id=data_source.id,
        source_record_key="parcel-alpha-a",
        source_url="https://example.org/property/parcel-alpha-a",
        pull_date=datetime(2026, 3, 16, 16, 0, tzinfo=timezone.utc),
    )
    source_record_alpha_b = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001102"),
        data_source_id=data_source.id,
        source_record_key="parcel-alpha-b",
        source_url="https://example.org/property/parcel-alpha-b",
        pull_date=datetime(2026, 3, 15, 16, 0, tzinfo=timezone.utc),
    )
    source_record_beta = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000001103"),
        data_source_id=data_source.id,
        source_record_key="parcel-beta",
        source_url="https://example.org/property/parcel-beta",
        pull_date=datetime(2026, 3, 14, 16, 0, tzinfo=timezone.utc),
    )

    parcel_alpha_a_id = UUID("00000000-0000-0000-0000-000000001110")
    parcel_alpha_b_id = UUID("00000000-0000-0000-0000-000000001111")
    parcel_beta_id = UUID("00000000-0000-0000-0000-000000001112")
    parcel_gamma_id = UUID("00000000-0000-0000-0000-000000001113")

    insert_parcel_row(
        db_conn,
        ParcelRowSeed(
            id=parcel_alpha_a_id,
            reid="300000001",
            pin="0888888801",
            site_address="100 ALPHA ST",
            city="Durham",
            zoning_class="R-20",
            acreage=Decimal("1.5000"),
            jurisdiction_id=jurisdiction_id,
            source_record_id=source_record_alpha_a.id,
        ),
    )
    insert_parcel_row(
        db_conn,
        ParcelRowSeed(
            id=parcel_alpha_b_id,
            reid="300000002",
            pin="0888888802",
            site_address="100 ALPHA ST",
            city="Durham",
            zoning_class="R-20",
            acreage=Decimal("2.0000"),
            jurisdiction_id=jurisdiction_id,
            source_record_id=source_record_alpha_b.id,
        ),
    )
    insert_parcel_row(
        db_conn,
        ParcelRowSeed(
            id=parcel_beta_id,
            reid="300000003",
            pin="0888888803",
            site_address="200 BETA ST",
            city="Raleigh",
            zoning_class="C-2",
            acreage=Decimal("3.0000"),
            jurisdiction_id=jurisdiction_id,
            source_record_id=source_record_beta.id,
        ),
    )
    insert_parcel_row(
        db_conn,
        ParcelRowSeed(
            id=parcel_gamma_id,
            reid="300000004",
            pin="0888888804",
            site_address="300 GAMMA ST",
            city="Durham",
            zoning_class="MXD",
            acreage=Decimal("0.7500"),
            jurisdiction_id=jurisdiction_id,
            source_record_id=None,
        ),
    )

    return {
        "parcel_alpha_a": parcel_alpha_a_id,
        "parcel_alpha_b": parcel_alpha_b_id,
        "parcel_beta": parcel_beta_id,
        "parcel_gamma": parcel_gamma_id,
    }
