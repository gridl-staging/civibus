"""Integration tests for civic canonical upsert helpers.

Tests run against a real PostgreSQL database to verify INSERT ... ON CONFLICT
behavior, UUID stability, and update-on-conflict semantics.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_person, insert_source_record
from core.types.python.models import DataSource, Person, SourceRecord, compute_record_hash, utc_now
from domains.civics.types.models import Candidacy, Contest, ElectoralDivision, Office, Officeholding


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=f"Civic Ingest Test {uuid4()}",
        source_url="https://example.com/test",
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


def _make_person(conn: psycopg.Connection, name: str = "Test Person") -> UUID:
    person = Person(canonical_name=name, first_name="TEST", last_name="PERSON")
    return insert_person(conn, person)


# ---------------------------------------------------------------------------
# Office upsert tests
# ---------------------------------------------------------------------------


class TestUpsertOffice:
    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office

        office = Office(name="us_house", office_level="federal", title="Representative")
        result = upsert_office(db_conn, office)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office

        office = Office(name="us_senate", office_level="federal", title="Senator")
        id1 = upsert_office(db_conn, office)

        office2 = Office(name="us_senate", office_level="federal", title="Senator")
        id2 = upsert_office(db_conn, office2)
        assert id1 == id2

    def test_update_on_conflict_changes_fields_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office

        office = Office(name="governor", office_level="state", state="WA", title="Governor")
        id1 = upsert_office(db_conn, office)

        office2 = Office(
            name="governor", office_level="state", state="WA", title="Governor of Washington", number_of_seats=1
        )
        id2 = upsert_office(db_conn, office2)
        assert id1 == id2

        row = db_conn.execute("SELECT title FROM civic.office WHERE id = %s", (id1,)).fetchone()
        assert row[0] == "Governor of Washington"

    def test_different_state_creates_different_office(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office

        wa = Office(name="governor", office_level="state", state="WA")
        fl = Office(name="governor", office_level="state", state="FL")
        id_wa = upsert_office(db_conn, wa)
        id_fl = upsert_office(db_conn, fl)
        assert id_wa != id_fl


# ---------------------------------------------------------------------------
# Electoral Division upsert tests
# ---------------------------------------------------------------------------


class TestUpsertElectoralDivision:
    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        div = ElectoralDivision(name="wa", division_type="statewide", state="WA")
        result = upsert_electoral_division(db_conn, div)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        div1 = ElectoralDivision(name="wa", division_type="statewide", state="WA")
        id1 = upsert_electoral_division(db_conn, div1)

        div2 = ElectoralDivision(name="wa", division_type="statewide", state="WA")
        id2 = upsert_electoral_division(db_conn, div2)
        assert id1 == id2

    def test_update_on_conflict_changes_fields_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        div = ElectoralDivision(
            name="wa_cd_01", division_type="congressional_district", state="WA", district_number="01"
        )
        id1 = upsert_electoral_division(db_conn, div)

        div2 = ElectoralDivision(
            name="wa_cd_01",
            division_type="congressional_district",
            state="WA",
            district_number="01",
            ocd_id="ocd-division/country:us/state:wa/cd:1",
        )
        id2 = upsert_electoral_division(db_conn, div2)
        assert id1 == id2

        row = db_conn.execute("SELECT ocd_id FROM civic.electoral_division WHERE id = %s", (id1,)).fetchone()
        assert row[0] == "ocd-division/country:us/state:wa/cd:1"

    def test_different_boundary_year_creates_different_division(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        d2020 = ElectoralDivision(
            name="wa_cd_01", division_type="congressional_district", state="WA", boundary_year=2020
        )
        d2022 = ElectoralDivision(
            name="wa_cd_01", division_type="congressional_district", state="WA", boundary_year=2022
        )
        id1 = upsert_electoral_division(db_conn, d2020)
        id2 = upsert_electoral_division(db_conn, d2022)
        assert id1 != id2


# ---------------------------------------------------------------------------
# Contest upsert tests
# ---------------------------------------------------------------------------


class TestUpsertContest:
    def _make_office(self, conn: psycopg.Connection) -> UUID:
        from domains.civics.ingest import upsert_office

        return upsert_office(conn, Office(name="us_house_test", office_level="federal"))

    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_contest

        office_id = self._make_office(db_conn)
        contest = Contest(
            name="US House General 2024",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
        )
        result = upsert_contest(db_conn, contest)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_contest

        office_id = self._make_office(db_conn)
        contest1 = Contest(
            name="US House General 2024",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
        )
        id1 = upsert_contest(db_conn, contest1)

        contest2 = Contest(
            name="US House General 2024",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
        )
        id2 = upsert_contest(db_conn, contest2)
        assert id1 == id2

    def test_update_on_conflict_changes_fields_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_contest

        office_id = self._make_office(db_conn)
        contest = Contest(
            name="US House General 2024",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
            is_partisan=True,
        )
        id1 = upsert_contest(db_conn, contest)

        contest2 = Contest(
            name="US House General 2024 — Updated",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
            is_partisan=False,
        )
        id2 = upsert_contest(db_conn, contest2)
        assert id1 == id2

        row = db_conn.execute("SELECT name, is_partisan FROM civic.contest WHERE id = %s", (id1,)).fetchone()
        assert row[0] == "US House General 2024 — Updated"
        assert row[1] is False

    def test_different_election_dates_create_distinct_contests(self, db_conn: psycopg.Connection) -> None:
        """FEC-relevant: 2022 and 2024 general elections for the same office must be distinct."""
        from domains.civics.ingest import upsert_contest

        office_id = self._make_office(db_conn)
        c2022 = Contest(
            name="US House General 2022",
            election_date=date(2022, 11, 8),
            election_type="general",
            office_id=office_id,
        )
        c2024 = Contest(
            name="US House General 2024",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
        )
        id1 = upsert_contest(db_conn, c2022)
        id2 = upsert_contest(db_conn, c2024)
        assert id1 != id2


# ---------------------------------------------------------------------------
# Candidacy upsert tests
# ---------------------------------------------------------------------------


class TestUpsertCandidacy:
    def _make_contest(self, conn: psycopg.Connection) -> tuple[UUID, UUID]:
        """Return (office_id, contest_id)."""
        from domains.civics.ingest import upsert_contest, upsert_office

        office_id = upsert_office(conn, Office(name=f"test_office_{uuid4()}", office_level="federal"))
        contest_id = upsert_contest(
            conn,
            Contest(
                name="Test General 2024",
                election_date=date(2024, 11, 5),
                election_type="general",
                office_id=office_id,
            ),
        )
        return office_id, contest_id

    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)
        candidacy = Candidacy(person_id=person_id, contest_id=contest_id, party="DEM")
        result = upsert_candidacy(db_conn, candidacy)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)

        c1 = Candidacy(person_id=person_id, contest_id=contest_id, party="DEM")
        id1 = upsert_candidacy(db_conn, c1)

        c2 = Candidacy(person_id=person_id, contest_id=contest_id, party="DEM")
        id2 = upsert_candidacy(db_conn, c2)
        assert id1 == id2

    def test_update_on_conflict_changes_fields_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)

        c1 = Candidacy(person_id=person_id, contest_id=contest_id, party="DEM", status="filed")
        id1 = upsert_candidacy(db_conn, c1)

        c2 = Candidacy(person_id=person_id, contest_id=contest_id, party="REP", status="qualified")
        id2 = upsert_candidacy(db_conn, c2)
        assert id1 == id2

        row = db_conn.execute("SELECT party, status FROM civic.candidacy WHERE id = %s", (id1,)).fetchone()
        assert row[0] == "REP"
        assert row[1] == "qualified"

    def test_same_person_different_contests_creates_distinct_candidacies(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy, upsert_contest, upsert_office

        office_id = upsert_office(db_conn, Office(name=f"test_office_{uuid4()}", office_level="federal"))
        person_id = _make_person(db_conn)

        contest_2022 = upsert_contest(
            db_conn,
            Contest(name="General 2022", election_date=date(2022, 11, 8), election_type="general", office_id=office_id),
        )
        contest_2024 = upsert_contest(
            db_conn,
            Contest(name="General 2024", election_date=date(2024, 11, 5), election_type="general", office_id=office_id),
        )

        id1 = upsert_candidacy(db_conn, Candidacy(person_id=person_id, contest_id=contest_2022))
        id2 = upsert_candidacy(db_conn, Candidacy(person_id=person_id, contest_id=contest_2024))
        assert id1 != id2


# ---------------------------------------------------------------------------
# Officeholding upsert tests
# ---------------------------------------------------------------------------


class TestUpsertOfficeholding:
    def _make_office(self, conn: psycopg.Connection) -> UUID:
        from domains.civics.ingest import upsert_office

        return upsert_office(conn, Office(name=f"officeholding_office_{uuid4()}", office_level="federal"))

    def test_insert_returns_uuid_and_persists_term_fields(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_officeholding

        office_id = self._make_office(db_conn)
        person_id = _make_person(db_conn, name=f"Officeholder {uuid4()}")
        officeholding = Officeholding(
            person_id=person_id,
            office_id=office_id,
            holder_status="appointed",
            valid_period={"start_date": date(2025, 1, 3), "end_date": date(2027, 1, 3)},
            date_precision="day",
        )
        officeholding_id = upsert_officeholding(db_conn, officeholding)
        assert isinstance(officeholding_id, UUID)

        row = db_conn.execute(
            """
            SELECT holder_status, lower(valid_period), upper(valid_period), date_precision::text
            FROM civic.officeholding
            WHERE id = %s
            """,
            (officeholding_id,),
        ).fetchone()
        assert row == ("appointed", date(2025, 1, 3), date(2027, 1, 3), "day")

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_officeholding

        office_id = self._make_office(db_conn)
        person_id = _make_person(db_conn, name=f"Officeholder {uuid4()}")
        officeholding = Officeholding(
            person_id=person_id,
            office_id=office_id,
            holder_status="elected",
            valid_period={"start_date": date(2025, 1, 3), "end_date": date(2027, 1, 3)},
        )
        id1 = upsert_officeholding(db_conn, officeholding)
        id2 = upsert_officeholding(db_conn, officeholding.model_copy(update={"id": uuid4()}))
        assert id1 == id2

    def test_update_on_conflict_changes_status_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division, upsert_officeholding

        office_id = self._make_office(db_conn)
        person_id = _make_person(db_conn, name=f"Officeholder {uuid4()}")
        officeholding = Officeholding(
            person_id=person_id,
            office_id=office_id,
            holder_status="appointed",
            valid_period={"start_date": date(2025, 1, 3), "end_date": date(2027, 1, 3)},
            date_precision="month",
        )
        id1 = upsert_officeholding(db_conn, officeholding)

        division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(name=f"wa_cd_01_{uuid4()}", division_type="congressional_district", state="WA"),
        )
        updated = officeholding.model_copy(
            update={
                "id": uuid4(),
                "holder_status": "acting",
                "date_precision": "day",
                "electoral_division_id": division_id,
            }
        )
        id2 = upsert_officeholding(db_conn, updated)
        assert id1 == id2

        row = db_conn.execute(
            "SELECT holder_status, date_precision::text, electoral_division_id FROM civic.officeholding WHERE id = %s",
            (id1,),
        ).fetchone()
        assert row == ("acting", "day", division_id)

    def test_different_term_periods_create_distinct_rows(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_officeholding

        office_id = self._make_office(db_conn)
        person_id = _make_person(db_conn, name=f"Officeholder {uuid4()}")
        first_term = Officeholding(
            person_id=person_id,
            office_id=office_id,
            holder_status="former",
            valid_period={"start_date": date(2021, 1, 3), "end_date": date(2023, 1, 3)},
        )
        current_term = Officeholding(
            person_id=person_id,
            office_id=office_id,
            holder_status="elected",
            valid_period={"start_date": date(2023, 1, 3), "end_date": date(2025, 1, 3)},
        )

        id1 = upsert_officeholding(db_conn, first_term)
        id2 = upsert_officeholding(db_conn, current_term)
        assert id1 != id2


# ---------------------------------------------------------------------------
# Provenance wiring tests
# ---------------------------------------------------------------------------


class TestProvenanceWiring:
    def test_upsert_office_with_source_record_creates_entity_source(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office

        ds = _make_data_source(db_conn)
        sr = _make_source_record(db_conn, ds.id, f"office-prov-{uuid4()}")

        office = Office(name=f"prov_office_{uuid4()}", office_level="federal", source_record_id=sr.id)
        office_id = upsert_office(db_conn, office)

        row = db_conn.execute(
            "SELECT entity_type, entity_id, source_record_id FROM core.entity_source WHERE entity_id = %s",
            (office_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "office"
        assert row[1] == office_id
        assert row[2] == sr.id

    def test_upsert_office_without_source_record_skips_provenance(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office

        office = Office(name=f"no_prov_{uuid4()}", office_level="federal")
        office_id = upsert_office(db_conn, office)

        row = db_conn.execute("SELECT id FROM core.entity_source WHERE entity_id = %s", (office_id,)).fetchone()
        assert row is None

    def test_upsert_contest_with_source_record_creates_entity_source(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_contest, upsert_office

        ds = _make_data_source(db_conn)
        sr = _make_source_record(db_conn, ds.id, f"contest-prov-{uuid4()}")

        office_id = upsert_office(db_conn, Office(name=f"prov_off_{uuid4()}", office_level="federal"))
        contest = Contest(
            name="Prov Test 2024",
            election_date=date(2024, 11, 5),
            election_type="general",
            office_id=office_id,
            source_record_id=sr.id,
        )
        contest_id = upsert_contest(db_conn, contest)

        row = db_conn.execute(
            "SELECT entity_type, entity_id FROM core.entity_source WHERE entity_id = %s",
            (contest_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "contest"

    def test_upsert_candidacy_with_source_record_creates_entity_source(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy, upsert_contest, upsert_office

        ds = _make_data_source(db_conn)
        sr = _make_source_record(db_conn, ds.id, f"candidacy-prov-{uuid4()}")

        office_id = upsert_office(db_conn, Office(name=f"prov_off_{uuid4()}", office_level="federal"))
        contest_id = upsert_contest(
            db_conn,
            Contest(name="Prov Contest", election_date=date(2024, 11, 5), election_type="general", office_id=office_id),
        )
        person_id = _make_person(db_conn)
        candidacy = Candidacy(person_id=person_id, contest_id=contest_id, source_record_id=sr.id)
        candidacy_id = upsert_candidacy(db_conn, candidacy)

        row = db_conn.execute(
            "SELECT entity_type, entity_id FROM core.entity_source WHERE entity_id = %s",
            (candidacy_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "candidacy"

    def test_upsert_officeholding_with_source_record_creates_entity_source(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office, upsert_officeholding

        ds = _make_data_source(db_conn)
        sr = _make_source_record(db_conn, ds.id, f"officeholding-prov-{uuid4()}")

        office_id = upsert_office(db_conn, Office(name=f"prov_officeholding_{uuid4()}", office_level="federal"))
        person_id = _make_person(db_conn, name=f"Holder {uuid4()}")
        officeholding_id = upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=office_id,
                holder_status="elected",
                valid_period={"start_date": date(2025, 1, 3), "end_date": date(2027, 1, 3)},
                source_record_id=sr.id,
            ),
        )

        row = db_conn.execute(
            "SELECT entity_type, entity_id, source_record_id FROM core.entity_source WHERE entity_id = %s",
            (officeholding_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "officeholding"
        assert row[1] == officeholding_id
        assert row[2] == sr.id
