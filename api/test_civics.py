"""Tests for civic domain API endpoints (offices, contests, candidacies, officeholdings)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import insert_data_source_for_test, insert_source_record_for_test
from core.db import insert_entity_source, insert_person
from core.types.python.models import Person

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Seed helpers — direct SQL inserts for civic.* tables
# ---------------------------------------------------------------------------

_OFFICE_INSERT_SQL = """
    INSERT INTO civic.office (
        id, name, office_level, title, jurisdiction_id, state,
        is_elected, number_of_seats, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CONTEST_INSERT_SQL = """
    INSERT INTO civic.contest (
        id, name, election_date, election_type, office_id,
        electoral_division_id, number_of_seats, filing_deadline,
        is_partisan, candidate_list_incomplete, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CANDIDACY_INSERT_SQL = """
    INSERT INTO civic.candidacy (
        id, person_id, contest_id, party, filing_date,
        status, incumbent_challenge, candidate_number, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_OFFICEHOLDING_INSERT_SQL = """
    INSERT INTO civic.officeholding (
        id, person_id, office_id, electoral_division_id,
        holder_status, valid_period, date_precision, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_CONTACT_POINT_INSERT_SQL = """
    INSERT INTO core.contact_point (
        id, type, value_raw, value_normalized, role,
        owner_type, owner_id, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_JURISDICTION_INSERT_SQL = """
    INSERT INTO core.jurisdiction (id, name, jurisdiction_type, fips, state)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""


def _insert_office(conn: psycopg.Connection, **kwargs) -> UUID:
    oid = kwargs.pop("id", uuid4())
    defaults = {
        "name": "Test Office",
        "office_level": "federal",
        "title": None,
        "jurisdiction_id": None,
        "state": None,
        "is_elected": True,
        "number_of_seats": 1,
        "source_record_id": None,
    }
    defaults.update(kwargs)
    conn.execute(
        _OFFICE_INSERT_SQL,
        (
            oid,
            defaults["name"],
            defaults["office_level"],
            defaults["title"],
            defaults["jurisdiction_id"],
            defaults["state"],
            defaults["is_elected"],
            defaults["number_of_seats"],
            defaults["source_record_id"],
        ),
    )
    return oid


def _insert_contest(conn: psycopg.Connection, **kwargs) -> UUID:
    cid = kwargs.pop("id", uuid4())
    defaults = {
        "name": "Test Contest",
        "election_date": date(2026, 11, 3),
        "election_type": "general",
        "office_id": None,
        "electoral_division_id": None,
        "number_of_seats": 1,
        "filing_deadline": None,
        "is_partisan": True,
        "candidate_list_incomplete": False,
        "source_record_id": None,
    }
    defaults.update(kwargs)
    conn.execute(
        _CONTEST_INSERT_SQL,
        (
            cid,
            defaults["name"],
            defaults["election_date"],
            defaults["election_type"],
            defaults["office_id"],
            defaults["electoral_division_id"],
            defaults["number_of_seats"],
            defaults["filing_deadline"],
            defaults["is_partisan"],
            defaults["candidate_list_incomplete"],
            defaults["source_record_id"],
        ),
    )
    return cid


def _insert_candidacy(conn: psycopg.Connection, **kwargs) -> UUID:
    cid = kwargs.pop("id", uuid4())
    defaults = {
        "person_id": None,
        "contest_id": None,
        "party": None,
        "filing_date": None,
        "status": None,
        "incumbent_challenge": None,
        "candidate_number": None,
        "source_record_id": None,
    }
    defaults.update(kwargs)
    conn.execute(
        _CANDIDACY_INSERT_SQL,
        (
            cid,
            defaults["person_id"],
            defaults["contest_id"],
            defaults["party"],
            defaults["filing_date"],
            defaults["status"],
            defaults["incumbent_challenge"],
            defaults["candidate_number"],
            defaults["source_record_id"],
        ),
    )
    return cid


def _insert_officeholding(conn: psycopg.Connection, **kwargs) -> UUID:
    oid = kwargs.pop("id", uuid4())
    defaults = {
        "person_id": None,
        "office_id": None,
        "electoral_division_id": None,
        "holder_status": "elected",
        "valid_period": "[2025-01-01,)",
        "date_precision": "day",
        "source_record_id": None,
    }
    defaults.update(kwargs)
    conn.execute(
        _OFFICEHOLDING_INSERT_SQL,
        (
            oid,
            defaults["person_id"],
            defaults["office_id"],
            defaults["electoral_division_id"],
            defaults["holder_status"],
            defaults["valid_period"],
            defaults["date_precision"],
            defaults["source_record_id"],
        ),
    )
    return oid


def _insert_contact_point(conn: psycopg.Connection, **kwargs) -> UUID:
    cpid = kwargs.pop("id", uuid4())
    defaults = {
        "type": "email",
        "value_raw": "test@example.com",
        "value_normalized": "test@example.com",
        "role": None,
        "owner_type": "person",
        "owner_id": None,
        "source_record_id": None,
    }
    defaults.update(kwargs)
    conn.execute(
        _CONTACT_POINT_INSERT_SQL,
        (
            cpid,
            defaults["type"],
            defaults["value_raw"],
            defaults["value_normalized"],
            defaults["role"],
            defaults["owner_type"],
            defaults["owner_id"],
            defaults["source_record_id"],
        ),
    )
    return cpid


# ---------------------------------------------------------------------------
# Sprint 1: Detail endpoints
# ---------------------------------------------------------------------------


class TestOfficeDetail:
    def test_returns_office_with_officeholders(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        person = Person(canonical_name="Jane Governor")
        insert_person(db_conn, person)

        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000001"),
            name="test_governor_wa",
            office_level="state",
            title="Governor",
            state="WA",
        )
        _insert_officeholding(
            db_conn,
            person_id=person.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2025-01-01,)",
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(office_id)
        assert payload["name"] == "test_governor_wa"
        assert payload["office_level"] == "state"
        assert payload["title"] == "Governor"
        assert payload["state"] == "WA"
        assert payload["is_elected"] is True
        assert payload["number_of_seats"] == 1
        assert len(payload["current_officeholders"]) == 1
        assert payload["current_officeholders"][0]["person_name"] == "Jane Governor"
        assert payload["current_officeholders"][0]["holder_status"] == "elected"

    def test_returns_incomplete_data_states_when_no_officeholder(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000002"),
            name="test_vacant_office",
            office_level="state",
            state="FL",
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        assert "no_officeholder" in payload["incomplete_data_states"]

    def test_returns_404_for_missing_office(self, api_client: TestClient) -> None:
        response = api_client.get(f"/v1/offices/{uuid4()}")
        assert response.status_code == 404

    def test_returns_provenance_sources(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        data_source = insert_data_source_for_test(db_conn, jurisdiction="state/wa", name_suffix=str(uuid4()))
        source_record = insert_source_record_for_test(
            db_conn,
            source_record_id=UUID("00000000-0000-0000-0000-100000000099"),
            data_source_id=data_source.id,
            source_record_key="office-wa-gov",
            source_url="https://example.org/office-wa-gov",
            pull_date=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        )
        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000003"),
            name="test_governor_prov",
            office_level="state",
            state="WA",
            source_record_id=source_record.id,
        )
        insert_entity_source(db_conn, "office", office_id, source_record.id, "office")

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["sources"]) >= 1
        assert payload["sources"][0]["source_record_key"] == "office-wa-gov"


class TestContestDetail:
    def test_returns_contest_with_candidacy_list(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        person_a = Person(canonical_name="Alice Candidate")
        person_b = Person(canonical_name="Bob Challenger")
        insert_person(db_conn, person_a)
        insert_person(db_conn, person_b)

        office_id = _insert_office(db_conn, name="test_us_house_contest", office_level="federal")
        contest_id = _insert_contest(
            db_conn,
            id=UUID("00000000-0000-0000-0000-200000000001"),
            name="NC-01 General 2026",
            office_id=office_id,
            election_date=date(2026, 11, 3),
            election_type="general",
            candidate_list_incomplete=True,
        )
        _insert_candidacy(
            db_conn,
            person_id=person_a.id,
            contest_id=contest_id,
            party="DEM",
            status="qualified",
            incumbent_challenge="I",
        )
        _insert_candidacy(
            db_conn,
            person_id=person_b.id,
            contest_id=contest_id,
            party="REP",
            status="filed",
            incumbent_challenge="C",
        )

        response = api_client.get(f"/v1/contests/{contest_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(contest_id)
        assert payload["name"] == "NC-01 General 2026"
        assert payload["election_date"] == "2026-11-03"
        assert payload["election_type"] == "general"
        assert payload["candidate_list_incomplete"] is True
        assert len(payload["candidacies"]) == 2
        candidate_names = {c["person_name"] for c in payload["candidacies"]}
        assert candidate_names == {"Alice Candidate", "Bob Challenger"}

    def test_returns_404_for_missing_contest(self, api_client: TestClient) -> None:
        response = api_client.get(f"/v1/contests/{uuid4()}")
        assert response.status_code == 404


class TestCandidacyDetail:
    def test_returns_candidacy_with_person_name(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        person = Person(canonical_name="Carol Runner")
        insert_person(db_conn, person)

        office_id = _insert_office(db_conn, name="test_us_senate_candidacy", office_level="federal")
        contest_id = _insert_contest(
            db_conn,
            name="Senate General 2026",
            office_id=office_id,
        )
        candidacy_id = _insert_candidacy(
            db_conn,
            id=UUID("00000000-0000-0000-0000-300000000001"),
            person_id=person.id,
            contest_id=contest_id,
            party="IND",
            status="filed",
            incumbent_challenge="O",
        )

        response = api_client.get(f"/v1/candidacies/{candidacy_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(candidacy_id)
        assert payload["person_name"] == "Carol Runner"
        assert payload["party"] == "IND"
        assert payload["status"] == "filed"
        assert payload["incumbent_challenge"] == "O"
        assert payload["contest_id"] == str(contest_id)

    def test_returns_404_for_missing_candidacy(self, api_client: TestClient) -> None:
        response = api_client.get(f"/v1/candidacies/{uuid4()}")
        assert response.status_code == 404


class TestOfficeholdingDetail:
    def test_returns_officeholding_with_person_name_and_period(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        person = Person(canonical_name="Doug Holder")
        insert_person(db_conn, person)

        office_id = _insert_office(db_conn, name="test_governor_holding", office_level="state", state="FL")
        holding_id = _insert_officeholding(
            db_conn,
            id=UUID("00000000-0000-0000-0000-400000000001"),
            person_id=person.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2023-01-01,2027-01-01)",
            date_precision="day",
        )

        response = api_client.get(f"/v1/officeholdings/{holding_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(holding_id)
        assert payload["person_name"] == "Doug Holder"
        assert payload["holder_status"] == "elected"
        assert payload["date_precision"] == "day"
        assert payload["office_id"] == str(office_id)
        assert payload["valid_period_lower"] == "2023-01-01"
        assert payload["valid_period_upper"] == "2027-01-01"

    def test_returns_404_for_missing_officeholding(self, api_client: TestClient) -> None:
        response = api_client.get(f"/v1/officeholdings/{uuid4()}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Sprint 3: Geography browse and contacts
# ---------------------------------------------------------------------------

_JURISDICTION_WA_ID = UUID("00000000-0000-4000-8000-000000000901")


class TestJurisdictionOfficesBrowse:
    def test_returns_offices_linked_to_jurisdiction(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        """Offices seeded with WA jurisdiction should be returned."""
        response = api_client.get(f"/v1/jurisdictions/{_JURISDICTION_WA_ID}/offices")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 1
        # All returned offices should belong to WA jurisdiction
        office_names = {o["name"] for o in payload}
        assert "governor" in office_names

    def test_returns_empty_list_for_jurisdiction_with_no_offices(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        jid = uuid4()
        db_conn.execute(
            _JURISDICTION_INSERT_SQL,
            (jid, "Test Empty Jurisdiction", "state", "99", "ZZ"),
        )

        response = api_client.get(f"/v1/jurisdictions/{jid}/offices")

        assert response.status_code == 200
        assert response.json() == []

    def test_returns_404_for_missing_jurisdiction(self, api_client: TestClient) -> None:
        response = api_client.get(f"/v1/jurisdictions/{uuid4()}/offices")
        assert response.status_code == 404


class TestContactEndpoint:
    def test_returns_contacts_for_office(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-500000000001"),
            name="test_contact_office",
            office_level="state",
            state="WA",
        )
        _insert_contact_point(
            db_conn,
            owner_type="office",
            owner_id=office_id,
            type="email",
            value_raw="gov@wa.gov",
            value_normalized="gov@wa.gov",
            role="office",
        )
        _insert_contact_point(
            db_conn,
            owner_type="office",
            owner_id=office_id,
            type="phone",
            value_raw="555-1234",
            value_normalized="+15551234",
            role="office",
        )

        response = api_client.get(
            "/v1/contacts",
            params={"owner_type": "office", "owner_id": str(office_id)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        types = {c["type"] for c in payload}
        assert types == {"email", "phone"}
        assert all(c["owner_type"] == "office" for c in payload)

    def test_returns_empty_list_when_no_contacts(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-500000000002"),
            name="test_no_contacts_office",
            office_level="federal",
        )

        response = api_client.get(
            "/v1/contacts",
            params={"owner_type": "office", "owner_id": str(office_id)},
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_office_contacts_do_not_leak_into_candidacy_contacts(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        """Official office contacts must not appear when querying candidacy contacts."""
        person = Person(canonical_name="Contact Guard Person")
        insert_person(db_conn, person)

        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-500000000010"),
            name="test_guard_office",
            office_level="state",
            state="WA",
        )
        contest_id = _insert_contest(db_conn, name="Test Guard Contest", office_id=office_id)
        candidacy_id = _insert_candidacy(
            db_conn,
            id=UUID("00000000-0000-0000-0000-500000000011"),
            person_id=person.id,
            contest_id=contest_id,
        )

        # Attach a contact to the office (not the candidacy)
        _insert_contact_point(
            db_conn,
            owner_type="office",
            owner_id=office_id,
            type="email",
            value_raw="office@guard.gov",
            value_normalized="office@guard.gov",
            role="office",
        )

        # Query contacts for the candidacy — should be empty
        response = api_client.get(
            "/v1/contacts",
            params={"owner_type": "candidacy", "owner_id": str(candidacy_id)},
        )

        assert response.status_code == 200
        assert response.json() == []
