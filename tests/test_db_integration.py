from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from core.db import (
    insert_address,
    insert_data_source,
    insert_organization,
    insert_person,
    insert_source_record,
    select_address,
    select_data_source,
    select_organization,
    select_person,
    select_source_record,
)
from core.types.python.models import Address, DataSource, Organization, Person, SourceRecord, compute_record_hash


pytestmark = pytest.mark.integration


def test_person_round_trip(db_conn: psycopg.Connection) -> None:
    linked_address = Address(raw_address="500 Link St, Durham, NC 27701")
    insert_address(db_conn, linked_address)

    person = Person(
        canonical_name="Jane Doe",
        name_variants=["J. Doe"],
        first_name="Jane",
        middle_name="A",
        last_name="Doe",
        suffix="Jr",
        date_of_birth=date(1990, 4, 3),
        year_of_birth=1990,
        identifiers={"fec_id": "P123"},
        primary_address_id=linked_address.id,
        er_cluster_id=uuid4(),
        er_confidence=0.88,
    )

    inserted_id = insert_person(db_conn, person)
    selected = select_person(db_conn, inserted_id)

    assert selected == person


def test_organization_round_trip(db_conn: psycopg.Connection) -> None:
    linked_address = Address(raw_address="700 Org Blvd, Durham, NC 27701")
    insert_address(db_conn, linked_address)

    organization = Organization(
        canonical_name="Civibus Action Fund",
        name_variants=["CAF"],
        org_type="pac",
        identifiers={"ein": "12-3456789"},
        registered_state="NC",
        formation_date=date(2011, 2, 5),
        dissolution_date=date(2020, 6, 1),
        primary_address_id=linked_address.id,
        er_cluster_id=uuid4(),
        er_confidence=0.91,
    )

    inserted_id = insert_organization(db_conn, organization)
    selected = select_organization(db_conn, inserted_id)

    assert selected == organization


def test_address_round_trip(db_conn: psycopg.Connection) -> None:
    address = Address(
        raw_address="123 Main St, Durham, NC 27701",
        normalized_address="123 MAIN ST DURHAM NC 27701",
        street_number="123",
        street_name="Main St",
        unit="Apt 4",
        city="Durham",
        state="NC",
        zip5="27701",
        zip4="1234",
        county_fips="37063",
        geometry=None,
        geocode_confidence=0.95,
        geocode_source="census",
        geocoded_at=datetime(2026, 3, 13, 13, 20, tzinfo=timezone.utc),
    )

    inserted_id = insert_address(db_conn, address)
    selected = select_address(db_conn, inserted_id)

    assert selected == address


def test_data_source_round_trip(db_conn: psycopg.Connection) -> None:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
        source_format="api",
        license="public_domain",
        update_frequency="continuous",
        last_pull_at=datetime(2026, 3, 13, 22, 30, tzinfo=timezone.utc),
        last_pull_status="success",
        record_count=240_000,
        notes="Primary source",
    )

    inserted_id = insert_data_source(db_conn, data_source)
    selected = select_data_source(db_conn, inserted_id)

    assert selected == data_source


def test_source_record_round_trip(db_conn: psycopg.Connection) -> None:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )
    insert_data_source(db_conn, data_source)

    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="A1-20260313-001",
        source_url="https://example.gov/record/A1-20260313-001",
        raw_fields={
            "amount": 2500,
            "contributor": {"name": "Jane Doe", "city": "Durham"},
            "flags": ["amended", "verified"],
        },
        pull_date=datetime(2026, 3, 13, 23, 1, tzinfo=timezone.utc),
        record_hash=compute_record_hash(
            {
                "amount": 2500,
                "contributor": {"name": "Jane Doe", "city": "Durham"},
                "flags": ["amended", "verified"],
            }
        ),
        superseded_by=None,
    )

    inserted_id = insert_source_record(db_conn, source_record)
    selected = select_source_record(db_conn, inserted_id)

    assert selected == source_record


def test_minimal_fields_round_trip_for_all_models(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Minimal Person")
    organization = Organization(canonical_name="Minimal Org")
    address = Address(raw_address="1 Minimal St, Durham, NC 27701")
    data_source = DataSource(
        domain="campaign_finance",
        name="Minimal Source",
        source_url="https://example.gov/source/minimal",
    )
    source_record = SourceRecord(
        data_source_id=data_source.id,
        raw_fields={"id": "minimal-1"},
        pull_date=datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
    )

    insert_person(db_conn, person)
    insert_organization(db_conn, organization)
    insert_address(db_conn, address)
    insert_data_source(db_conn, data_source)
    insert_source_record(db_conn, source_record)

    assert select_person(db_conn, person.id) == person
    assert select_organization(db_conn, organization.id) == organization
    assert select_address(db_conn, address.id) == address
    assert select_data_source(db_conn, data_source.id) == data_source
    assert select_source_record(db_conn, source_record.id) == source_record


def test_data_source_duplicate_domain_jurisdiction_name_raises_unique_violation(db_conn: psycopg.Connection) -> None:
    first_data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )
    duplicate_data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC Schedule A API",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )

    insert_data_source(db_conn, first_data_source)

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_data_source(db_conn, duplicate_data_source)
