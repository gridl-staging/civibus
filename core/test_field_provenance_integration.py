from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import (
    insert_data_source,
    insert_entity_source,
    insert_field_provenance,
    insert_person,
    insert_source_record,
)
from core.types.python.models import DataSource, Person, SourceRecord, compute_record_hash, utc_now


pytestmark = pytest.mark.integration


def _insert_test_data_source(conn: psycopg.Connection) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="states/wa",
        name=f"Field Provenance Integration {uuid4()}",
        source_url="https://example.com/source",
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_test_source_record(conn: psycopg.Connection, data_source_id: UUID, source_record_key: str) -> SourceRecord:
    raw_fields = {"source_record_key": source_record_key}
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(conn, source_record)
    return source_record


def _insert_office(conn: psycopg.Connection, *, office_name: str) -> UUID:
    return conn.execute(
        """
        INSERT INTO civic.office (name, office_level, state)
        VALUES (%s, 'municipal', 'NC')
        RETURNING id
        """,
        (office_name,),
    ).fetchone()[0]


def _insert_contest(conn: psycopg.Connection, office_id: UUID, *, contest_name: str) -> UUID:
    return conn.execute(
        """
        INSERT INTO civic.contest (name, election_type, office_id, is_partisan)
        VALUES (%s, 'general', %s, TRUE)
        RETURNING id
        """,
        (contest_name, office_id),
    ).fetchone()[0]


def _insert_officeholding(conn: psycopg.Connection, person_id: UUID, office_id: UUID) -> UUID:
    return conn.execute(
        """
        INSERT INTO civic.officeholding (person_id, office_id, valid_period)
        VALUES (%s, %s, daterange('2025-01-01', '2027-01-01', '[)'))
        RETURNING id
        """,
        (person_id, office_id),
    ).fetchone()[0]


def _insert_contact_point(conn: psycopg.Connection, office_id: UUID) -> UUID:
    return conn.execute(
        """
        INSERT INTO core.contact_point (type, value_raw, role, owner_type, owner_id)
        VALUES ('email', %s, 'office', 'office', %s)
        RETURNING id
        """,
        (f"info-{uuid4()}@example.com", office_id),
    ).fetchone()[0]


def _insert_contact_point_for_officeholding(conn: psycopg.Connection, officeholding_id: UUID) -> UUID:
    return conn.execute(
        """
        INSERT INTO core.contact_point (type, value_raw, role, owner_type, owner_id)
        VALUES ('email', %s, 'official_directory', 'officeholding', %s)
        RETURNING id
        """,
        (f"holder-{uuid4()}@example.com", officeholding_id),
    ).fetchone()[0]


def test_insert_field_provenance_records_office_name_with_source_attribution(db_conn: psycopg.Connection) -> None:
    data_source = _insert_test_data_source(db_conn)
    source_record = _insert_test_source_record(db_conn, data_source.id, f"office-source-{uuid4()}")
    office_id = _insert_office(db_conn, office_name=f"City Council Seat {uuid4()}")

    link_id = insert_entity_source(db_conn, "office", office_id, source_record.id, "office")
    provenance_id = insert_field_provenance(db_conn, "office", office_id, "name", "City Council", source_record.id)

    row = db_conn.execute(
        """
        SELECT id, entity_type, entity_id, field_name, field_value, source_record_id, is_current
        FROM core.field_provenance
        WHERE id = %s
        """,
        (provenance_id,),
    ).fetchone()

    assert link_id is not None
    assert row == (provenance_id, "office", office_id, "name", "City Council", source_record.id, True)


def test_insert_field_provenance_contest_conflict_keeps_exactly_one_current_row(db_conn: psycopg.Connection) -> None:
    data_source = _insert_test_data_source(db_conn)
    source_record_a = _insert_test_source_record(db_conn, data_source.id, f"contest-source-a-{uuid4()}")
    source_record_b = _insert_test_source_record(db_conn, data_source.id, f"contest-source-b-{uuid4()}")

    office_id = _insert_office(db_conn, office_name=f"Mayor {uuid4()}")
    contest_id = _insert_contest(db_conn, office_id, contest_name=f"Mayor General {uuid4()}")

    insert_field_provenance(db_conn, "contest", contest_id, "status", "scheduled", source_record_a.id)
    insert_field_provenance(db_conn, "contest", contest_id, "status", "certified", source_record_b.id)

    rows = db_conn.execute(
        """
        SELECT field_value, is_current
        FROM core.field_provenance
        WHERE entity_type = 'contest'
          AND entity_id = %s
          AND field_name = 'status'
        ORDER BY field_value
        """,
        (contest_id,),
    ).fetchall()

    assert rows == [("certified", True), ("scheduled", False)]


def test_insert_field_provenance_tracks_officeholding_term_as_text(db_conn: psycopg.Connection) -> None:
    data_source = _insert_test_data_source(db_conn)
    source_record = _insert_test_source_record(db_conn, data_source.id, f"officeholding-source-{uuid4()}")

    person = Person(canonical_name="Taylor Morgan", first_name="TAYLOR", last_name="MORGAN")
    insert_person(db_conn, person)
    office_id = _insert_office(db_conn, office_name=f"School Board Seat {uuid4()}")
    officeholding_id = _insert_officeholding(db_conn, person.id, office_id)

    term_value = "[2025-01-01,2027-01-01)"
    provenance_id = insert_field_provenance(
        db_conn,
        "officeholding",
        officeholding_id,
        "valid_period",
        term_value,
        source_record.id,
    )

    row = db_conn.execute(
        """
        SELECT id, field_value, is_current
        FROM core.field_provenance
        WHERE id = %s
        """,
        (provenance_id,),
    ).fetchone()

    assert row == (provenance_id, term_value, True)


def test_insert_field_provenance_records_contact_point_value_raw(db_conn: psycopg.Connection) -> None:
    data_source = _insert_test_data_source(db_conn)
    source_record = _insert_test_source_record(db_conn, data_source.id, f"contact-point-source-{uuid4()}")

    office_id = _insert_office(db_conn, office_name=f"City Clerk {uuid4()}")
    contact_point_id = _insert_contact_point(db_conn, office_id)

    value_raw = f"clerk-{uuid4()}@example.com"
    provenance_id = insert_field_provenance(
        db_conn,
        "contact_point",
        contact_point_id,
        "value_raw",
        value_raw,
        source_record.id,
    )

    row = db_conn.execute(
        """
        SELECT id, field_name, field_value, source_record_id, is_current
        FROM core.field_provenance
        WHERE id = %s
        """,
        (provenance_id,),
    ).fetchone()

    assert row == (provenance_id, "value_raw", value_raw, source_record.id, True)


def test_insert_field_provenance_records_officeholding_contact_value_raw(db_conn: psycopg.Connection) -> None:
    data_source = _insert_test_data_source(db_conn)
    source_record = _insert_test_source_record(db_conn, data_source.id, f"officeholding-contact-source-{uuid4()}")

    person = Person(canonical_name="Casey Rivera", first_name="CASEY", last_name="RIVERA")
    insert_person(db_conn, person)
    office_id = _insert_office(db_conn, office_name=f"County Commissioner {uuid4()}")
    officeholding_id = _insert_officeholding(db_conn, person.id, office_id)
    contact_point_id = _insert_contact_point_for_officeholding(db_conn, officeholding_id)

    value_raw = f"holder-{uuid4()}@example.com"
    provenance_id = insert_field_provenance(
        db_conn,
        "contact_point",
        contact_point_id,
        "value_raw",
        value_raw,
        source_record.id,
    )

    row = db_conn.execute(
        """
        SELECT id, field_name, field_value, source_record_id, is_current
        FROM core.field_provenance
        WHERE id = %s
        """,
        (provenance_id,),
    ).fetchone()

    assert row == (provenance_id, "value_raw", value_raw, source_record.id, True)
