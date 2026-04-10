"""Integration tests for upsert_contact_point in core/db_ingest.py.

Tests run against a real PostgreSQL database to verify INSERT ... ON CONFLICT
behavior across the two partial unique indexes on core.contact_point:
  - uq_contact_point_natural_key (owner_type, owner_id, type, value_raw, role) WHERE role IS NOT NULL
  - uq_contact_point_natural_key_null_role (owner_type, owner_id, type, value_raw) WHERE role IS NULL
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_person, insert_source_record
from core.types.python.models import (
    ContactPoint,
    DataSource,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_person(conn: psycopg.Connection) -> UUID:
    return insert_person(conn, Person(canonical_name=f"CP Test {uuid4()}", first_name="TEST", last_name="PERSON"))


def _make_office(conn: psycopg.Connection) -> UUID:
    return conn.execute(
        """
        INSERT INTO civic.office (name, office_level, state)
        VALUES (%s, 'state', 'WA')
        RETURNING id
        """,
        (f"cp-office-{uuid4()}",),
    ).fetchone()[0]


def _make_officeholding(conn: psycopg.Connection) -> UUID:
    person_id = _make_person(conn)
    office_id = _make_office(conn)
    return conn.execute(
        """
        INSERT INTO civic.officeholding (person_id, office_id, holder_status, valid_period)
        VALUES (%s, %s, 'elected', daterange('2025-01-01', '2027-01-01', '[)'))
        RETURNING id
        """,
        (person_id, office_id),
    ).fetchone()[0]


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="test/cp",
        name=f"Contact Point Test {uuid4()}",
        source_url="https://example.com/test-cp",
    )
    insert_data_source(conn, ds)
    return ds


def _make_source_record(conn: psycopg.Connection, data_source_id: UUID, key: str) -> SourceRecord:
    raw = {"key": key}
    sr = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=key,
        raw_fields=raw,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw),
    )
    insert_source_record(conn, sr)
    return sr


# ---------------------------------------------------------------------------
# Insert tests
# ---------------------------------------------------------------------------


class TestUpsertContactPointInsert:
    def test_insert_with_role_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp = ContactPoint(
            type="email",
            value_raw="test@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        result = upsert_contact_point(db_conn, cp)
        assert isinstance(result, UUID)

    def test_insert_with_null_role_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp = ContactPoint(
            type="phone",
            value_raw="555-0100",
            role=None,
            owner_type="person",
            owner_id=person_id,
        )
        result = upsert_contact_point(db_conn, cp)
        assert isinstance(result, UUID)

    def test_insert_official_directory_contact_for_office_owner(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        office_id = _make_office(db_conn)
        cp = ContactPoint(
            type="phone",
            value_raw="360-000-0000",
            role="official_directory",
            owner_type="office",
            owner_id=office_id,
        )
        result = upsert_contact_point(db_conn, cp)
        assert isinstance(result, UUID)

    def test_insert_personal_official_contact_for_officeholding_owner(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        officeholding_id = _make_officeholding(db_conn)
        cp = ContactPoint(
            type="email",
            value_raw=f"member-{uuid4()}@leg.wa.gov",
            role="official_directory",
            owner_type="officeholding",
            owner_id=officeholding_id,
        )
        result = upsert_contact_point(db_conn, cp)
        assert isinstance(result, UUID)

    @pytest.mark.parametrize("owner_type", ["organization", "candidacy"])
    def test_existing_non_office_owner_types_remain_supported(
        self, db_conn: psycopg.Connection, owner_type: str
    ) -> None:
        from core.db_ingest import upsert_contact_point

        cp = ContactPoint(
            type="email",
            value_raw=f"{owner_type}-{uuid4()}@example.com",
            role="campaign",
            owner_type=owner_type,
            owner_id=uuid4(),
        )
        result = upsert_contact_point(db_conn, cp)
        assert isinstance(result, UUID)


# ---------------------------------------------------------------------------
# Idempotent re-insert tests
# ---------------------------------------------------------------------------


class TestUpsertContactPointIdempotent:
    def test_same_natural_key_with_role_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp1 = ContactPoint(
            type="email",
            value_raw="idempotent@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        id1 = upsert_contact_point(db_conn, cp1)

        cp2 = ContactPoint(
            type="email",
            value_raw="idempotent@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        id2 = upsert_contact_point(db_conn, cp2)
        assert id1 == id2

    def test_same_natural_key_with_null_role_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp1 = ContactPoint(
            type="phone",
            value_raw="555-0200",
            role=None,
            owner_type="person",
            owner_id=person_id,
        )
        id1 = upsert_contact_point(db_conn, cp1)

        cp2 = ContactPoint(
            type="phone",
            value_raw="555-0200",
            role=None,
            owner_type="person",
            owner_id=person_id,
        )
        id2 = upsert_contact_point(db_conn, cp2)
        assert id1 == id2


# ---------------------------------------------------------------------------
# Update-on-conflict tests
# ---------------------------------------------------------------------------


class TestUpsertContactPointUpdate:
    def test_update_value_normalized_on_conflict(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp1 = ContactPoint(
            type="phone",
            value_raw="(555) 123-4567",
            value_normalized=None,
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        id1 = upsert_contact_point(db_conn, cp1)

        cp2 = ContactPoint(
            type="phone",
            value_raw="(555) 123-4567",
            value_normalized="+15551234567",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        id2 = upsert_contact_point(db_conn, cp2)
        assert id1 == id2

        row = db_conn.execute("SELECT value_normalized FROM core.contact_point WHERE id = %s", (id1,)).fetchone()
        assert row[0] == "+15551234567"

    def test_update_last_verified_at_on_conflict(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp1 = ContactPoint(
            type="email",
            value_raw="verified@example.com",
            role="office",
            owner_type="person",
            owner_id=person_id,
            last_verified_at=None,
        )
        id1 = upsert_contact_point(db_conn, cp1)

        verified_time = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        cp2 = ContactPoint(
            type="email",
            value_raw="verified@example.com",
            role="office",
            owner_type="person",
            owner_id=person_id,
            last_verified_at=verified_time,
        )
        id2 = upsert_contact_point(db_conn, cp2)
        assert id1 == id2

        row = db_conn.execute("SELECT last_verified_at FROM core.contact_point WHERE id = %s", (id1,)).fetchone()
        assert row[0] == verified_time

    def test_update_is_preferred_on_conflict(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp1 = ContactPoint(
            type="email",
            value_raw="preferred@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
            is_preferred=False,
        )
        id1 = upsert_contact_point(db_conn, cp1)

        cp2 = ContactPoint(
            type="email",
            value_raw="preferred@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
            is_preferred=True,
        )
        id2 = upsert_contact_point(db_conn, cp2)
        assert id1 == id2

        row = db_conn.execute("SELECT is_preferred FROM core.contact_point WHERE id = %s", (id1,)).fetchone()
        assert row[0] is True


# ---------------------------------------------------------------------------
# NULL vs non-NULL role partial index keying
# ---------------------------------------------------------------------------


class TestUpsertContactPointRoleKeying:
    def test_null_role_and_non_null_role_are_distinct(self, db_conn: psycopg.Connection) -> None:
        """Same (owner_type, owner_id, type, value_raw) but different role NULLness = distinct rows."""
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp_with_role = ContactPoint(
            type="email",
            value_raw="dual@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        cp_without_role = ContactPoint(
            type="email",
            value_raw="dual@example.com",
            role=None,
            owner_type="person",
            owner_id=person_id,
        )
        id_with = upsert_contact_point(db_conn, cp_with_role)
        id_without = upsert_contact_point(db_conn, cp_without_role)
        assert id_with != id_without

    def test_different_roles_are_distinct(self, db_conn: psycopg.Connection) -> None:
        """Same (owner_type, owner_id, type, value_raw) but different non-NULL roles = distinct rows."""
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp_campaign = ContactPoint(
            type="email",
            value_raw="multi@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
        )
        cp_office = ContactPoint(
            type="email",
            value_raw="multi@example.com",
            role="office",
            owner_type="person",
            owner_id=person_id,
        )
        id_campaign = upsert_contact_point(db_conn, cp_campaign)
        id_office = upsert_contact_point(db_conn, cp_office)
        assert id_campaign != id_office


# ---------------------------------------------------------------------------
# Provenance wiring tests
# ---------------------------------------------------------------------------


class TestUpsertContactPointProvenance:
    def test_with_source_record_creates_entity_source(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        ds = _make_data_source(db_conn)
        sr = _make_source_record(db_conn, ds.id, f"cp-prov-{uuid4()}")

        cp = ContactPoint(
            type="email",
            value_raw="prov@example.com",
            role="campaign",
            owner_type="person",
            owner_id=person_id,
            source_record_id=sr.id,
        )
        cp_id = upsert_contact_point(db_conn, cp)

        row = db_conn.execute(
            "SELECT entity_type, entity_id, source_record_id FROM core.entity_source WHERE entity_id = %s",
            (cp_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "contact_point"
        assert row[1] == cp_id
        assert row[2] == sr.id

    def test_without_source_record_skips_provenance(self, db_conn: psycopg.Connection) -> None:
        from core.db_ingest import upsert_contact_point

        person_id = _make_person(db_conn)
        cp = ContactPoint(
            type="email",
            value_raw="noprov@example.com",
            role=None,
            owner_type="person",
            owner_id=person_id,
        )
        cp_id = upsert_contact_point(db_conn, cp)

        row = db_conn.execute("SELECT id FROM core.entity_source WHERE entity_id = %s", (cp_id,)).fetchone()
        assert row is None
