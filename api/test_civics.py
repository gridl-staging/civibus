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
        electoral_division_id, is_elected, number_of_seats, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

_ELECTORAL_DIVISION_INSERT_SQL = """
    INSERT INTO civic.electoral_division (
        id, name, division_type, state, district_number, ocd_id,
        is_container, parent_id, boundary_year, geometry, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 4326), %s)
"""

_JURISDICTION_INSERT_SQL = """
    INSERT INTO core.jurisdiction (id, name, jurisdiction_type, fips, state)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""

_ELECTORAL_DIVISION_INSERT_SQL = """
    INSERT INTO civic.electoral_division (
        id, name, division_type, state, district_number, ocd_id,
        is_container, parent_id, boundary_year, geometry, source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 4326), %s)
"""


def _insert_office(conn: psycopg.Connection, **kwargs) -> UUID:
    oid = kwargs.pop("id", uuid4())
    defaults = {
        "name": "Test Office",
        "office_level": "federal",
        "title": None,
        "jurisdiction_id": None,
        "state": None,
        "electoral_division_id": None,
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
            defaults["electoral_division_id"],
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


def _insert_electoral_division(conn: psycopg.Connection, **kwargs) -> UUID:
    division_id = kwargs.pop("id", uuid4())
    defaults = {
        "name": "nc_county_durham",
        "division_type": "county",
        "state": "NC",
        "district_number": None,
        "ocd_id": None,
        "is_container": False,
        "parent_id": None,
        "boundary_year": 2024,
        "geometry_wkt": "MULTIPOLYGON(((-78.95 35.86,-78.73 35.86,-78.73 36.07,-78.95 36.07,-78.95 35.86)))",
        "source_record_id": None,
    }
    defaults.update(kwargs)
    conn.execute(
        _ELECTORAL_DIVISION_INSERT_SQL,
        (
            division_id,
            defaults["name"],
            defaults["division_type"],
            defaults["state"],
            defaults["district_number"],
            defaults["ocd_id"],
            defaults["is_container"],
            defaults["parent_id"],
            defaults["boundary_year"],
            defaults["geometry_wkt"],
            defaults["source_record_id"],
        ),
    )
    return division_id


# ---------------------------------------------------------------------------
# Sprint 1: Detail endpoints
# ---------------------------------------------------------------------------


class TestMapContextHelpers:
    def test_extracts_map_context_from_first_complete_row(self) -> None:
        from api.routes.civics import _map_context_from_row

        assert _map_context_from_row(
            {
                "electoral_division_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                "electoral_division_type": "county",
                "electoral_division_state": "NC",
            }
        ) == {
            "selected_electoral_division_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            "selected_electoral_division_type": "county",
            "selected_electoral_division_state": "NC",
        }

    def test_returns_none_map_context_for_incomplete_row(self) -> None:
        from api.routes.civics import _map_context_from_row

        assert (
            _map_context_from_row(
                {
                    "electoral_division_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                    "electoral_division_type": "county",
                    "electoral_division_state": None,
                }
            )
            is None
        )

    def test_falls_back_to_timeline_rows_when_contests_and_current_holders_lack_map_context(self) -> None:
        from api.routes.civics import _first_map_context

        assert _first_map_context(
            [{"electoral_division_id": None, "electoral_division_type": None, "electoral_division_state": None}],
            [{"electoral_division_id": None, "electoral_division_type": None, "electoral_division_state": None}],
            [
                {
                    "electoral_division_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                    "electoral_division_type": "county",
                    "electoral_division_state": "NC",
                }
            ],
        ) == {
            "selected_electoral_division_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            "selected_electoral_division_type": "county",
            "selected_electoral_division_state": "NC",
        }


class TestOfficeDetail:
    def test_returns_office_with_officeholders(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        person = Person(canonical_name="Jane Governor")
        insert_person(db_conn, person)
        division_id = _insert_electoral_division(
            db_conn,
            name="wa_statewide",
            division_type="statewide",
            state="WA",
        )

        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000001"),
            name="test_governor_wa",
            office_level="state",
            title="Governor",
            state="WA",
            electoral_division_id=division_id,
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
        assert payload["electoral_division_id"] == str(division_id)
        assert payload["is_elected"] is True
        assert payload["number_of_seats"] == 1
        assert len(payload["current_officeholders"]) == 1
        assert payload["current_officeholders"][0]["person_name"] == "Jane Governor"
        assert payload["current_officeholders"][0]["holder_status"] == "elected"
        assert payload["current_holder_card"]["person_name"] == "Jane Governor"
        assert payload["current_holder_card"]["valid_period_lower"] == "2025-01-01"
        assert payload["current_holder_card"]["valid_period_upper"] is None
        assert payload["current_holder_card"]["date_precision"] == "day"
        assert payload["current_holder_card"]["electoral_division_id"] is None
        assert payload["current_holder_card"]["electoral_division_type"] is None
        assert payload["current_holder_card"]["electoral_division_state"] is None
        assert payload["officeholding_timeline"] == [
            {
                "officeholding_id": payload["current_officeholders"][0]["officeholding_id"],
                "person_id": str(person.id),
                "person_name": "Jane Governor",
                "holder_status": "elected",
                "electoral_division_id": None,
                "electoral_division_type": None,
                "electoral_division_state": None,
                "valid_period_lower": "2025-01-01",
                "valid_period_upper": None,
                "date_precision": "day",
                "is_active": True,
                "term_ended": False,
            }
        ]
        assert payload["recent_contests"] == []
        assert payload["selected_electoral_division_id"] is None
        assert payload["selected_electoral_division_type"] is None
        assert payload["selected_electoral_division_state"] is None

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
        assert "no_active_contest" in payload["incomplete_data_states"]

    def test_returns_404_for_missing_office(self, api_client: TestClient) -> None:
        response = api_client.get(f"/v1/offices/{uuid4()}")
        assert response.status_code == 404

    def test_current_officeholders_use_active_period_rule_and_exclude_future_open_ranges(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        active_person = Person(canonical_name="Active Holder")
        future_person = Person(canonical_name="Future Holder")
        insert_person(db_conn, active_person)
        insert_person(db_conn, future_person)

        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000004"),
            name="test_active_semantics_office",
            office_level="state",
            state="NC",
        )
        _insert_officeholding(
            db_conn,
            person_id=active_person.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2000-01-01,2100-01-01)",
        )
        _insert_officeholding(
            db_conn,
            person_id=future_person.id,
            office_id=office_id,
            holder_status="appointed",
            valid_period="[2100-01-01,)",
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        holder_names = [holder["person_name"] for holder in payload["current_officeholders"]]
        assert holder_names == ["Active Holder"]
        timeline_names = [row["person_name"] for row in payload["officeholding_timeline"]]
        assert timeline_names == ["Future Holder", "Active Holder"]
        assert payload["current_holder_card"]["person_name"] == "Active Holder"

    def test_returns_timeline_recent_contests_and_map_context_for_office(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        incumbent = Person(canonical_name="Incumbent Holder")
        former = Person(canonical_name="Former Holder")
        insert_person(db_conn, incumbent)
        insert_person(db_conn, former)

        division_id = _insert_electoral_division(
            db_conn,
            id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            name="nc_county_durham",
            division_type="county",
            state="NC",
            source_record_id=None,
        )
        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000005"),
            name="test_office_with_timeline_and_contests",
            office_level="state",
            state="NC",
        )
        _insert_officeholding(
            db_conn,
            id=UUID("00000000-0000-0000-0000-400000000001"),
            person_id=incumbent.id,
            office_id=office_id,
            electoral_division_id=division_id,
            holder_status="elected",
            valid_period="[2024-01-01,)",
            date_precision="day",
        )
        _insert_officeholding(
            db_conn,
            id=UUID("00000000-0000-0000-0000-400000000002"),
            person_id=former.id,
            office_id=office_id,
            electoral_division_id=division_id,
            holder_status="former",
            valid_period="[2020-01-01,2023-12-31)",
            date_precision="day",
        )

        _insert_contest(
            db_conn,
            id=UUID("00000000-0000-0000-0000-200000000010"),
            name="Governor 2026 General",
            office_id=office_id,
            election_date=date(2026, 11, 3),
            election_type="general",
            electoral_division_id=division_id,
            filing_deadline=date(2026, 9, 1),
            is_partisan=True,
            candidate_list_incomplete=False,
        )
        _insert_contest(
            db_conn,
            id=UUID("00000000-0000-0000-0000-200000000011"),
            name="Governor 2024 General",
            office_id=office_id,
            election_date=date(2024, 11, 5),
            election_type="general",
            electoral_division_id=division_id,
            filing_deadline=date(2024, 9, 1),
            is_partisan=True,
            candidate_list_incomplete=True,
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        assert [row["person_name"] for row in payload["officeholding_timeline"]] == [
            "Incumbent Holder",
            "Former Holder",
        ]
        assert [row["valid_period_lower"] for row in payload["officeholding_timeline"]] == [
            "2024-01-01",
            "2020-01-01",
        ]
        assert [contest["contest_name"] for contest in payload["recent_contests"]] == [
            "Governor 2026 General",
            "Governor 2024 General",
        ]
        assert payload["recent_contests"][0]["electoral_division_type"] == "county"
        assert payload["recent_contests"][0]["electoral_division_state"] == "NC"
        assert payload["selected_electoral_division_id"] == str(division_id)
        assert payload["selected_electoral_division_type"] == "county"
        assert payload["selected_electoral_division_state"] == "NC"
        assert "no_active_contest" not in payload["incomplete_data_states"]

    def test_marks_no_active_contest_when_only_historical_contests_exist(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000006"),
            name="test_office_historical_contests_only",
            office_level="state",
            state="NC",
        )
        _insert_contest(
            db_conn,
            id=UUID("00000000-0000-0000-0000-200000000012"),
            name="Historical Contest",
            office_id=office_id,
            election_date=date(2020, 11, 3),
            election_type="general",
            candidate_list_incomplete=False,
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["recent_contests"] != []
        assert "no_active_contest" in payload["incomplete_data_states"]

    def test_omits_singular_current_holder_card_when_multiple_active_holders(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        person_a = Person(canonical_name="Seat A Holder")
        person_b = Person(canonical_name="Seat B Holder")
        insert_person(db_conn, person_a)
        insert_person(db_conn, person_b)

        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000007"),
            name="test_multiseat_office",
            office_level="state",
            state="NC",
            number_of_seats=2,
        )
        _insert_officeholding(
            db_conn,
            person_id=person_a.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2024-01-01,)",
        )
        _insert_officeholding(
            db_conn,
            person_id=person_b.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2024-01-01,)",
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["current_officeholders"]) == 2
        assert payload["current_holder_card"] is None

    def test_timeline_term_ended_is_independent_of_holder_status(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        """Backend ended-state must derive from valid_period upper bound, not holder_status.

        Some pipelines retire bounded officeholdings without rewriting holder_status to
        'former' (e.g. an 'elected' holder whose term simply ran out). The presenter relies
        on a backend-owned ended flag so historical bounded rows show ended copy regardless
        of the status string the source system left in place.
        """
        ended_elected = Person(canonical_name="Ended Elected Holder")
        future_appointed = Person(canonical_name="Future Appointed Holder")
        active_holder = Person(canonical_name="Active Holder")
        insert_person(db_conn, ended_elected)
        insert_person(db_conn, future_appointed)
        insert_person(db_conn, active_holder)

        office_id = _insert_office(
            db_conn,
            id=UUID("00000000-0000-0000-0000-100000000008"),
            name="test_term_ended_independent_of_status",
            office_level="state",
            state="NC",
        )
        # Bounded historical row that retains holder_status='elected'.
        _insert_officeholding(
            db_conn,
            person_id=ended_elected.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2018-01-01,2022-01-01)",
        )
        # Future bounded row.
        _insert_officeholding(
            db_conn,
            person_id=future_appointed.id,
            office_id=office_id,
            holder_status="appointed",
            valid_period="[2100-01-01,2104-01-01)",
        )
        # Active row (open-ended).
        _insert_officeholding(
            db_conn,
            person_id=active_holder.id,
            office_id=office_id,
            holder_status="elected",
            valid_period="[2024-01-01,)",
        )

        response = api_client.get(f"/v1/offices/{office_id}")

        assert response.status_code == 200
        payload = response.json()
        rows_by_name = {row["person_name"]: row for row in payload["officeholding_timeline"]}
        assert rows_by_name["Ended Elected Holder"]["term_ended"] is True
        assert rows_by_name["Ended Elected Holder"]["is_active"] is False
        assert rows_by_name["Ended Elected Holder"]["holder_status"] == "elected"
        assert rows_by_name["Future Appointed Holder"]["term_ended"] is False
        assert rows_by_name["Future Appointed Holder"]["is_active"] is False
        assert rows_by_name["Active Holder"]["term_ended"] is False
        assert rows_by_name["Active Holder"]["is_active"] is True

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
        assert payload["sources"] == [
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/wa",
                "data_source_name": data_source.name,
                "data_source_url": data_source.source_url,
                "source_record_key": "office-wa-gov",
                "record_url": "https://example.org/office-wa-gov",
                "pull_date": "2026-03-20T10:00:00Z",
            }
        ]


class TestContestDetail:
    def test_returns_contest_with_candidacy_list(self, api_client: TestClient, db_conn: psycopg.Connection) -> None:
        person_a = Person(canonical_name="Alice Candidate")
        person_b = Person(canonical_name="Bob Challenger")
        insert_person(db_conn, person_a)
        insert_person(db_conn, person_b)
        division_id = _insert_electoral_division(
            db_conn,
            name="nc_house_district_1",
            division_type="state_legislative_lower",
            state="NC",
            district_number="01",
        )

        office_id = _insert_office(db_conn, name="test_us_house_contest", office_level="federal")
        contest_id = _insert_contest(
            db_conn,
            id=UUID("00000000-0000-0000-0000-200000000001"),
            name="NC-01 General 2026",
            office_id=office_id,
            election_date=date(2026, 11, 3),
            election_type="general",
            electoral_division_id=division_id,
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
        assert payload["electoral_division_id"] == str(division_id)
        assert payload["candidate_list_incomplete"] is True
        assert payload["result_winner_candidacy_id"] is None
        assert payload["result_winner_person_id"] is None
        assert payload["result_winner_person_name"] is None
        assert len(payload["candidacies"]) == 2
        candidate_names = {c["person_name"] for c in payload["candidacies"]}
        assert candidate_names == {"Alice Candidate", "Bob Challenger"}

    def test_populates_normalized_result_fields_when_winner_status_exists(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        winner = Person(canonical_name="Winner Person")
        challenger = Person(canonical_name="Challenger Person")
        insert_person(db_conn, winner)
        insert_person(db_conn, challenger)

        office_id = _insert_office(db_conn, name="test_result_contest", office_level="state")
        contest_id = _insert_contest(
            db_conn,
            id=UUID("00000000-0000-0000-0000-200000000099"),
            name="Statewide General 2026",
            office_id=office_id,
        )
        winner_candidacy_id = _insert_candidacy(
            db_conn,
            id=UUID("00000000-0000-0000-0000-210000000001"),
            person_id=winner.id,
            contest_id=contest_id,
            status="elected",
        )
        _insert_candidacy(
            db_conn,
            id=UUID("00000000-0000-0000-0000-210000000002"),
            person_id=challenger.id,
            contest_id=contest_id,
            status="filed",
        )

        response = api_client.get(f"/v1/contests/{contest_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["result_winner_candidacy_id"] == str(winner_candidacy_id)
        assert payload["result_winner_person_id"] == str(winner.id)
        assert payload["result_winner_person_name"] == "Winner Person"

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


class TestElectionContracts:
    def test_election_date_rejects_invalid_date_format(self, api_client: TestClient) -> None:
        response = api_client.get("/v1/elections/not-a-date")
        assert response.status_code == 422

    def test_election_date_returns_exact_date_aggregate(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        office_wa = _insert_office(
            db_conn,
            name="test_governor_wa",
            office_level="state",
            title="Governor",
            state="WA",
        )
        office_or = _insert_office(
            db_conn,
            name="test_governor_or",
            office_level="state",
            title="Governor",
            state="OR",
        )
        contest_wa = _insert_contest(
            db_conn,
            name="test_wa_general",
            office_id=office_wa,
            election_date=date(2026, 11, 3),
            election_type="general",
        )
        contest_or = _insert_contest(
            db_conn,
            name="test_or_general",
            office_id=office_or,
            election_date=date(2026, 11, 3),
            election_type="general",
        )

        person_one = Person(canonical_name="Candidate One")
        person_two = Person(canonical_name="Candidate Two")
        insert_person(db_conn, person_one)
        insert_person(db_conn, person_two)
        _insert_candidacy(db_conn, contest_id=contest_wa, person_id=person_one.id)
        _insert_candidacy(db_conn, contest_id=contest_wa, person_id=person_two.id)
        _insert_candidacy(db_conn, contest_id=contest_or, person_id=person_one.id)

        response = api_client.get("/v1/elections/2026-11-03")

        assert response.status_code == 200
        payload = response.json()
        assert payload["date"] == "2026-11-03"
        assert payload["total_contests"] == 2
        assert payload["total_candidacies"] == 3
        assert len(payload["contests"]) == 2
        by_name = {contest["name"]: contest for contest in payload["contests"]}
        assert set(by_name) == {"test_wa_general", "test_or_general"}
        assert by_name["test_wa_general"]["state"] == "WA"
        assert by_name["test_wa_general"]["candidate_count"] == 2
        assert by_name["test_or_general"]["state"] == "OR"
        assert by_name["test_or_general"]["candidate_count"] == 1

    def test_elections_timeline_upcoming_returns_ordered_dates_without_cross_jurisdiction_collapsing(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        office_wa = _insert_office(db_conn, name="test_attorney_general_wa", office_level="state", state="WA")
        office_or = _insert_office(db_conn, name="test_attorney_general_or", office_level="state", state="OR")
        office_ca = _insert_office(db_conn, name="test_attorney_general_ca", office_level="state", state="CA")

        _insert_contest(
            db_conn,
            name="test_wa_primary",
            office_id=office_wa,
            election_date=date(2026, 8, 1),
            election_type="primary",
        )
        _insert_contest(
            db_conn,
            name="test_or_primary",
            office_id=office_or,
            election_date=date(2026, 8, 1),
            election_type="primary",
        )
        _insert_contest(
            db_conn,
            name="test_ca_general",
            office_id=office_ca,
            election_date=date(2026, 11, 3),
            election_type="general",
        )

        response = api_client.get("/v1/elections/timeline/upcoming")

        assert response.status_code == 200
        payload = response.json()
        assert [entry["date"] for entry in payload] == ["2026-08-01", "2026-11-03"]
        assert len(payload[0]["contests"]) == 2
        assert {contest["state"] for contest in payload[0]["contests"]} == {"WA", "OR"}
        assert payload[1]["contests"][0]["state"] == "CA"


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


class TestCivicsGeometryEndpoint:
    @pytest.mark.parametrize(
        ("level", "name", "division_type", "district_number"),
        [
            ("county", "nc_county_durham", "county", None),
            ("congressional_district", "nc_cd_01", "congressional_district", "01"),
        ],
    )
    def test_returns_feature_collection_with_nonzero_features(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
        level: str,
        name: str,
        division_type: str,
        district_number: str | None,
    ) -> None:
        _insert_electoral_division(
            db_conn,
            id=uuid4(),
            name=name,
            division_type=division_type,
            district_number=district_number,
        )

        response = api_client.get("/v1/civics/geometry", params={"level": level, "state": "NC"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["type"] == "FeatureCollection"
        assert len(payload["features"]) > 0

        first_feature = payload["features"][0]
        assert first_feature["type"] == "Feature"
        assert first_feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
        assert first_feature["properties"]["state"] == "NC"
        assert first_feature["properties"]["division_type"] == division_type

    def test_returns_only_latest_boundary_year_for_level_and_state(
        self,
        api_client: TestClient,
        db_conn: psycopg.Connection,
    ) -> None:
        _insert_electoral_division(
            db_conn,
            id=uuid4(),
            name="nc_county_old",
            division_type="county",
            boundary_year=2022,
        )
        _insert_electoral_division(
            db_conn,
            id=uuid4(),
            name="nc_county_new",
            division_type="county",
            boundary_year=2024,
        )

        response = api_client.get("/v1/civics/geometry", params={"level": "county", "state": "NC"})

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["features"]) > 0
        boundary_years = {feature["properties"]["boundary_year"] for feature in payload["features"]}
        assert boundary_years == {2024}

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


class TestGeometryEndpoint:
    def test_country_returns_feature_collection_sorted_with_launch_scope_states_only(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000001"),
            name="nc",
            division_type="statewide",
            state="NC",
            boundary_year=2024,
            geometry_wkt="MULTIPOLYGON(((-79.0 35.0,-78.0 35.0,-78.0 36.0,-79.0 36.0,-79.0 35.0)))",
        )
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000002"),
            name="wa",
            division_type="statewide",
            state="WA",
            boundary_year=2022,
            geometry_wkt="MULTIPOLYGON(((-123.0 47.0,-122.0 47.0,-122.0 48.0,-123.0 48.0,-123.0 47.0)))",
        )
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000003"),
            name="dc",
            division_type="statewide",
            state="DC",
            boundary_year=2020,
            geometry_wkt="MULTIPOLYGON(((-77.1 38.8,-76.9 38.8,-76.9 39.0,-77.1 39.0,-77.1 38.8)))",
        )
        # Non-launch state/territory must not appear.
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000004"),
            name="pr",
            division_type="statewide",
            state="PR",
            boundary_year=2024,
            geometry_wkt="MULTIPOLYGON(((-67.3 17.8,-65.2 17.8,-65.2 18.6,-67.3 18.6,-67.3 17.8)))",
        )

        response = api_client.get("/v1/geometry", params={"level": "country"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["type"] == "FeatureCollection"
        states = [feature["properties"]["state"] for feature in payload["features"]]
        assert states == ["DC", "NC", "WA"]
        for feature in payload["features"]:
            assert feature["type"] == "Feature"
            assert set(feature["properties"]) == {"state", "name", "division_type", "boundary_year"}
            assert feature["properties"]["division_type"] == "statewide"
            assert isinstance(feature["geometry"], dict)
            assert feature["geometry"]["type"] == "MultiPolygon"

    def test_country_returns_latest_boundary_per_state_when_multiple_vintages_exist(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000020"),
            name="north carolina 2020",
            division_type="statewide",
            state="NC",
            boundary_year=2020,
            geometry_wkt="MULTIPOLYGON(((-79.0 35.0,-78.0 35.0,-78.0 36.0,-79.0 36.0,-79.0 35.0)))",
        )
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000021"),
            name="north carolina 2024",
            division_type="statewide",
            state="NC",
            boundary_year=2024,
            geometry_wkt="MULTIPOLYGON(((-79.1 35.1,-78.1 35.1,-78.1 36.1,-79.1 36.1,-79.1 35.1)))",
        )

        response = api_client.get("/v1/geometry", params={"level": "country"})

        assert response.status_code == 200
        payload = response.json()
        nc_features = [feature for feature in payload["features"] if feature["properties"]["state"] == "NC"]
        assert len(nc_features) == 1
        assert nc_features[0]["properties"]["boundary_year"] == 2024
        assert nc_features[0]["properties"]["name"] == "north carolina 2024"

    def test_state_returns_feature_for_uppercase_usps_state(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000005"),
            name="nc",
            division_type="statewide",
            state="NC",
            boundary_year=2024,
            geometry_wkt="MULTIPOLYGON(((-79.0 35.0,-78.0 35.0,-78.0 36.0,-79.0 36.0,-79.0 35.0)))",
        )

        response = api_client.get("/v1/geometry", params={"level": "state", "state": "NC"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["type"] == "FeatureCollection"
        assert len(payload["features"]) == 1
        feature = payload["features"][0]
        assert feature["type"] == "Feature"
        assert feature["properties"] == {
            "state": "NC",
            "name": "nc",
            "division_type": "statewide",
            "boundary_year": 2024,
        }
        assert feature["geometry"]["type"] == "MultiPolygon"

    def test_state_returns_latest_boundary_when_multiple_vintages_exist(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000030"),
            name="north carolina 2020",
            division_type="statewide",
            state="NC",
            boundary_year=2020,
            geometry_wkt="MULTIPOLYGON(((-79.0 35.0,-78.0 35.0,-78.0 36.0,-79.0 36.0,-79.0 35.0)))",
        )
        _insert_electoral_division(
            db_conn,
            id=UUID("00000000-0000-0000-0000-600000000031"),
            name="north carolina 2024",
            division_type="statewide",
            state="NC",
            boundary_year=2024,
            geometry_wkt="MULTIPOLYGON(((-79.1 35.1,-78.1 35.1,-78.1 36.1,-79.1 36.1,-79.1 35.1)))",
        )

        response = api_client.get("/v1/geometry", params={"level": "state", "state": "NC"})

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["features"]) == 1
        assert payload["features"][0]["properties"]["boundary_year"] == 2024
        assert payload["features"][0]["properties"]["name"] == "north carolina 2024"

    def test_state_returns_404_for_valid_uppercase_state_without_launch_scope_geometry(
        self, api_client: TestClient
    ) -> None:
        response = api_client.get("/v1/geometry", params={"level": "state", "state": "TX"})

        assert response.status_code == 404
        assert response.json()["detail"] == "Geometry not found for state TX"

    @pytest.mark.parametrize(
        ("params", "error_fragment"),
        [
            ({"level": "state"}, "state"),
            ({"level": "state", "state": "nc"}, "string_pattern_mismatch"),
            ({"level": "state", "state": "N1"}, "string_pattern_mismatch"),
            ({"level": "county"}, "literal_error"),
        ],
    )
    def test_geometry_validation_returns_422_for_invalid_query_params(
        self, api_client: TestClient, params: dict[str, str], error_fragment: str
    ) -> None:
        response = api_client.get("/v1/geometry", params=params)

        assert response.status_code == 422
        assert error_fragment in response.text
