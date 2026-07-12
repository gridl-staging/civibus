"""Integration tests for civic canonical upsert helpers.

Tests run against a real PostgreSQL database to verify INSERT ... ON CONFLICT
behavior, UUID stability, and update-on-conflict semantics.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_person, insert_source_record
from core.types.python.models import DataSource, Person, SourceRecord, compute_record_hash, utc_now
from domains.civics.types.models import (
    Candidacy,
    Contest,
    Election,
    ElectoralDivision,
    FilingDeadline,
    Office,
    OfficeRosterLink,
    Officeholding,
    ReportingPeriod,
)


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
    def _make_division(self, conn: psycopg.Connection, *, district_number: str = "01") -> UUID:
        from domains.civics.ingest import upsert_electoral_division

        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"nc_house_district_{district_number}",
                division_type="state_legislative_lower",
                state="NC",
                district_number=district_number,
            ),
        )

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

    def test_late_arriving_division_updates_existing_office_without_duplicate(
        self, db_conn: psycopg.Connection
    ) -> None:
        from domains.civics.ingest import upsert_office

        division_id = self._make_division(db_conn)
        office_id = upsert_office(
            db_conn,
            Office(
                name="nc_house_member",
                office_level="state",
                title="State Representative",
                state="NC",
                number_of_seats=120,
            ),
        )

        updated_id = upsert_office(
            db_conn,
            Office(
                id=uuid4(),
                name="nc_house_member",
                office_level="state",
                title="State Representative",
                state="NC",
                number_of_seats=120,
                electoral_division_id=division_id,
            ),
        )
        assert updated_id == office_id

        row = db_conn.execute(
            """
            SELECT electoral_division_id, COUNT(*) OVER () AS office_row_count
            FROM civic.office
            WHERE office_level = 'state'
              AND state = 'NC'
              AND name = 'nc_house_member'
            """,
        ).fetchone()
        assert row is not None
        assert row[0] == division_id
        assert row[1] == 1


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

        initial_geometry = {
            "type": "Polygon",
            "coordinates": [[[-123.5, 47.0], [-123.4, 47.0], [-123.4, 47.1], [-123.5, 47.1], [-123.5, 47.0]]],
        }
        updated_geometry = {
            "type": "Polygon",
            "coordinates": [[[-123.6, 47.1], [-123.45, 47.1], [-123.45, 47.25], [-123.6, 47.25], [-123.6, 47.1]]],
        }
        div = ElectoralDivision(
            name="wa_cd_01",
            division_type="congressional_district",
            state="WA",
            district_number="01",
            geometry=initial_geometry,
        )
        id1 = upsert_electoral_division(db_conn, div)

        div2 = ElectoralDivision(
            name="wa_cd_01",
            division_type="congressional_district",
            state="WA",
            district_number="01",
            ocd_id="ocd-division/country:us/state:wa/cd:1",
            geometry=updated_geometry,
        )
        id2 = upsert_electoral_division(db_conn, div2)
        assert id1 == id2

        row = db_conn.execute(
            "SELECT ocd_id, ST_AsText(geometry) FROM civic.electoral_division WHERE id = %s",
            (id1,),
        ).fetchone()
        assert row[0] == "ocd-division/country:us/state:wa/cd:1"
        assert row[1] == ("MULTIPOLYGON(((-123.6 47.1,-123.45 47.1,-123.45 47.25,-123.6 47.25,-123.6 47.1)))")

    def test_insert_persists_geometry(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        geometry = {
            "type": "Polygon",
            "coordinates": [[[-122.5, 47.5], [-122.3, 47.5], [-122.3, 47.7], [-122.5, 47.7], [-122.5, 47.5]]],
        }
        division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="wa_county_king",
                division_type="county",
                state="WA",
                geometry=geometry,
            ),
        )

        row = db_conn.execute(
            "SELECT ST_AsText(geometry) FROM civic.electoral_division WHERE id = %s",
            (division_id,),
        ).fetchone()
        assert row[0] == "MULTIPOLYGON(((-122.5 47.5,-122.3 47.5,-122.3 47.7,-122.5 47.7,-122.5 47.5)))"

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

    def test_geometry_is_persisted_as_wgs84_multipolygon(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_county_durham",
                division_type="county",
                state="NC",
                geometry={
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-78.95, 35.86],
                            [-78.73, 35.86],
                            [-78.73, 36.07],
                            [-78.95, 36.07],
                            [-78.95, 35.86],
                        ]
                    ],
                },
            ),
        )
        row = db_conn.execute(
            """
            SELECT ST_GeometryType(geometry), ST_SRID(geometry)
            FROM civic.electoral_division
            WHERE id = %s
            """,
            (division_id,),
        ).fetchone()
        assert row == ("ST_MultiPolygon", 4326)

    def test_upsert_updates_geometry_without_changing_canonical_id(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_electoral_division

        initial = ElectoralDivision(
            name="nc_cd_01",
            division_type="congressional_district",
            state="NC",
            boundary_year=2024,
            geometry={
                "type": "Polygon",
                "coordinates": [[[-78.0, 35.0], [-77.8, 35.0], [-77.8, 35.2], [-78.0, 35.2], [-78.0, 35.0]]],
            },
        )
        division_id = upsert_electoral_division(db_conn, initial)
        before_geometry_wkt = db_conn.execute(
            """
            SELECT ST_AsText(geometry)
            FROM civic.electoral_division
            WHERE id = %s
            """,
            (division_id,),
        ).fetchone()
        assert before_geometry_wkt is not None

        updated_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_cd_01",
                division_type="congressional_district",
                state="NC",
                boundary_year=2024,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[-77.9, 35.1], [-77.7, 35.1], [-77.7, 35.3], [-77.9, 35.3], [-77.9, 35.1]]],
                },
            ),
        )
        assert updated_id == division_id

        after_geometry = db_conn.execute(
            """
            SELECT ST_AsText(geometry), ROUND(ST_Area(geometry::geography)::numeric, 0)
            FROM civic.electoral_division
            WHERE id = %s
            """,
            (division_id,),
        ).fetchone()
        assert after_geometry is not None
        assert after_geometry[1] > 0
        assert after_geometry[0] != before_geometry_wkt[0]


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

    def test_update_on_conflict_sets_election_id_when_present(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_contest

        office_id = self._make_office(db_conn)
        election_id = uuid4()
        db_conn.execute(
            """
            INSERT INTO civic.election (
                id, jurisdiction_scope, state, election_date, election_type, office_id
            ) VALUES (%s, 'state', 'WA', %s, 'general', %s)
            """,
            (election_id, date(2024, 11, 5), office_id),
        )

        id1 = upsert_contest(
            db_conn,
            Contest(
                name="US House General 2024",
                election_date=date(2024, 11, 5),
                election_type="general",
                office_id=office_id,
            ),
        )
        id2 = upsert_contest(
            db_conn,
            Contest(
                name="US House General 2024",
                election_date=date(2024, 11, 5),
                election_type="general",
                office_id=office_id,
                election_id=election_id,
            ),
        )
        assert id1 == id2

        row = db_conn.execute("SELECT election_id FROM civic.contest WHERE id = %s", (id1,)).fetchone()
        assert row[0] == election_id

    def test_late_arriving_division_updates_existing_contest_without_duplicate(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from domains.civics.ingest import upsert_contest, upsert_electoral_division

        office_id = self._make_office(db_conn)
        division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_house_district_03",
                division_type="state_legislative_lower",
                state="NC",
                district_number="03",
            ),
        )

        contest_id = upsert_contest(
            db_conn,
            Contest(
                name="NC House District 3 General 2026",
                election_date=date(2026, 11, 3),
                election_type="general",
                office_id=office_id,
            ),
        )
        updated_id = upsert_contest(
            db_conn,
            Contest(
                id=uuid4(),
                name="NC House District 3 General 2026",
                election_date=date(2026, 11, 3),
                election_type="general",
                office_id=office_id,
                electoral_division_id=division_id,
            ),
        )
        assert updated_id == contest_id

        row = db_conn.execute(
            """
            SELECT electoral_division_id, COUNT(*) OVER () AS contest_row_count
            FROM civic.contest
            WHERE office_id = %s
              AND election_date = %s
              AND election_type = 'general'
            """,
            (office_id, date(2026, 11, 3)),
        ).fetchone()
        assert row is not None
        assert row[0] == division_id
        assert row[1] == 1


# ---------------------------------------------------------------------------
# Election upsert tests
# ---------------------------------------------------------------------------


class TestUpsertElection:
    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_election

        election = Election(
            jurisdiction_scope="state",
            state="NC",
            election_date=date(2026, 3, 3),
            election_type="primary",
            is_special=False,
        )
        result = upsert_election(db_conn, election)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_election

        election = Election(
            jurisdiction_scope="state",
            state="NC",
            election_date=date(2026, 3, 3),
            election_type="primary",
            is_special=False,
        )
        id1 = upsert_election(db_conn, election)
        id2 = upsert_election(db_conn, election.model_copy(update={"id": uuid4()}))
        assert id1 == id2

    def test_county_or_municipality_change_creates_distinct_election_identity(
        self, db_conn: psycopg.Connection
    ) -> None:
        from domains.civics.ingest import upsert_election

        election = Election(
            jurisdiction_scope="county",
            state="NC",
            county="Wake",
            election_date=date(2026, 3, 3),
            election_type="primary",
            is_special=False,
        )
        election_id = upsert_election(db_conn, election)

        updated_id = upsert_election(
            db_conn,
            election.model_copy(
                update={
                    "id": uuid4(),
                    "county": "Durham",
                    "municipality": "Durham",
                }
            ),
        )
        assert updated_id != election_id

        original_row = db_conn.execute(
            "SELECT county, municipality FROM civic.election WHERE id = %s", (election_id,)
        ).fetchone()
        updated_row = db_conn.execute(
            "SELECT county, municipality FROM civic.election WHERE id = %s", (updated_id,)
        ).fetchone()
        assert original_row == ("Wake", None)
        assert updated_row == ("Durham", "Durham")

    def test_late_arriving_division_updates_existing_election_without_duplicate(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        from domains.civics.ingest import upsert_electoral_division, upsert_election

        division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_house_district_03",
                division_type="state_legislative_lower",
                state="NC",
                district_number="03",
            ),
        )

        election_id = upsert_election(
            db_conn,
            Election(
                jurisdiction_scope="state",
                state="NC",
                election_date=date(2026, 11, 3),
                election_type="general",
                is_special=False,
            ),
        )
        updated_id = upsert_election(
            db_conn,
            Election(
                id=uuid4(),
                jurisdiction_scope="state",
                state="NC",
                election_date=date(2026, 11, 3),
                election_type="general",
                is_special=False,
                electoral_division_id=division_id,
            ),
        )
        assert updated_id == election_id

        row = db_conn.execute(
            """
            SELECT electoral_division_id, COUNT(*) OVER () AS election_row_count
            FROM civic.election
            WHERE jurisdiction_scope = 'state'
              AND state = 'NC'
              AND election_date = %s
              AND election_type = 'general'
              AND is_special = FALSE
            """,
            (date(2026, 11, 3),),
        ).fetchone()
        assert row is not None
        assert row[0] == division_id
        assert row[1] == 1


# ---------------------------------------------------------------------------
# Filing Deadline upsert tests
# ---------------------------------------------------------------------------


class TestUpsertFilingDeadline:
    def _make_primary_election(self, conn: psycopg.Connection) -> tuple[UUID, UUID]:
        from domains.civics.ingest import upsert_election, upsert_office

        office_id = upsert_office(conn, Office(name=f"nc_gov_{uuid4()}", office_level="state", state="NC"))
        election_id = upsert_election(
            conn,
            Election(
                jurisdiction_scope="state",
                state="NC",
                election_date=date(2026, 3, 3),
                election_type="primary",
                office_id=office_id,
            ),
        )
        return office_id, election_id

    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_filing_deadline

        office_id, election_id = self._make_primary_election(db_conn)
        deadline = FilingDeadline(
            election_id=election_id,
            office_id=office_id,
            jurisdiction_scope="state",
            state="NC",
            deadline_date=date(2025, 12, 19),
            deadline_kind="candidate_filing",
        )
        result = upsert_filing_deadline(db_conn, deadline)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_filing_deadline

        office_id, election_id = self._make_primary_election(db_conn)
        deadline = FilingDeadline(
            election_id=election_id,
            office_id=office_id,
            jurisdiction_scope="state",
            state="NC",
            deadline_date=date(2025, 12, 19),
            deadline_kind="candidate_filing",
        )
        id1 = upsert_filing_deadline(db_conn, deadline)
        id2 = upsert_filing_deadline(db_conn, deadline.model_copy(update={"id": uuid4()}))
        assert id1 == id2

    def test_update_on_conflict_changes_fields_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_filing_deadline

        office_id, election_id = self._make_primary_election(db_conn)
        deadline = FilingDeadline(
            election_id=election_id,
            office_id=office_id,
            jurisdiction_scope="state",
            state="NC",
            deadline_date=date(2025, 12, 19),
            deadline_kind="candidate_filing",
        )
        deadline_id = upsert_filing_deadline(db_conn, deadline)

        updated_id = upsert_filing_deadline(
            db_conn,
            deadline.model_copy(
                update={
                    "id": uuid4(),
                    "deadline_date": date(2025, 12, 20),
                    "county": "Wake",
                }
            ),
        )
        assert updated_id == deadline_id

        row = db_conn.execute(
            "SELECT deadline_date, county FROM civic.filing_deadline WHERE id = %s",
            (deadline_id,),
        ).fetchone()
        assert row == (date(2025, 12, 20), "Wake")


# ---------------------------------------------------------------------------
# Reporting Period upsert tests
# ---------------------------------------------------------------------------


class TestUpsertReportingPeriod:
    def _make_general_election(self, conn: psycopg.Connection) -> UUID:
        from domains.civics.ingest import upsert_election

        return upsert_election(
            conn,
            Election(
                jurisdiction_scope="state",
                state="NC",
                election_date=date(2026, 11, 3),
                election_type="general",
            ),
        )

    def test_insert_returns_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_reporting_period

        election_id = self._make_general_election(db_conn)
        period = ReportingPeriod(
            election_id=election_id,
            period_name="2026 Third Quarter",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 10, 17),
            report_due_date=date(2026, 10, 27),
            is_pre_election=True,
            disclosure_kind="periodic",
        )
        result = upsert_reporting_period(db_conn, period)
        assert isinstance(result, UUID)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_reporting_period

        election_id = self._make_general_election(db_conn)
        period = ReportingPeriod(
            election_id=election_id,
            period_name="2026 Third Quarter",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 10, 17),
            report_due_date=date(2026, 10, 27),
            is_pre_election=True,
            disclosure_kind="periodic",
        )
        id1 = upsert_reporting_period(db_conn, period)
        id2 = upsert_reporting_period(db_conn, period.model_copy(update={"id": uuid4()}))
        assert id1 == id2

    def test_update_on_conflict_changes_fields_keeps_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_reporting_period

        election_id = self._make_general_election(db_conn)
        period = ReportingPeriod(
            election_id=election_id,
            period_name="2026 Third Quarter",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 10, 17),
            report_due_date=date(2026, 10, 27),
            is_pre_election=True,
            disclosure_kind="periodic",
        )
        period_id = upsert_reporting_period(db_conn, period)

        updated_id = upsert_reporting_period(
            db_conn,
            period.model_copy(
                update={
                    "id": uuid4(),
                    "report_due_date": date(2026, 10, 28),
                    "is_post_election": True,
                }
            ),
        )
        assert updated_id == period_id

        row = db_conn.execute(
            "SELECT report_due_date, is_post_election FROM civic.reporting_period WHERE id = %s",
            (period_id,),
        ).fetchone()
        assert row == (date(2026, 10, 28), True)

    def test_update_on_conflict_keeps_disclosure_kind_when_new_value_is_null(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_reporting_period

        election_id = self._make_general_election(db_conn)
        period = ReportingPeriod(
            election_id=election_id,
            period_name="2026 Third Quarter",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 10, 17),
            report_due_date=date(2026, 10, 27),
            is_pre_election=True,
            disclosure_kind="periodic",
        )
        period_id = upsert_reporting_period(db_conn, period)

        updated_id = upsert_reporting_period(
            db_conn,
            period.model_copy(
                update={
                    "id": uuid4(),
                    "disclosure_kind": None,
                }
            ),
        )
        assert updated_id == period_id

        row = db_conn.execute(
            "SELECT disclosure_kind FROM civic.reporting_period WHERE id = %s",
            (period_id,),
        ).fetchone()
        assert row == ("periodic",)

    def test_update_query_coalesces_disclosure_kind(self) -> None:
        from domains.civics.ingest import upsert_reporting_period

        cursor = MagicMock()
        cursor.fetchone.return_value = (uuid4(),)
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor

        period = ReportingPeriod(
            election_id=uuid4(),
            period_name="2026 Third Quarter",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 10, 17),
            report_due_date=date(2026, 10, 27),
            is_pre_election=True,
            disclosure_kind="periodic",
        )
        upsert_reporting_period(connection, period)

        executed_sql = cursor.execute.call_args.args[0]
        assert (
            "disclosure_kind = COALESCE(EXCLUDED.disclosure_kind, civic.reporting_period.disclosure_kind)"
            in executed_sql
        )


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

    def _make_committee(self, conn: psycopg.Connection) -> UUID:
        committee_id = uuid4()
        committee_number = f"C{committee_id.int % 100_000_000:08d}"
        conn.execute(
            """
            INSERT INTO cf.committee (id, fec_committee_id, name, state)
            VALUES (%s, %s, %s, 'NC')
            """,
            (committee_id, committee_number, f"Test Committee {uuid4().hex[:12]}"),
        )
        return committee_id

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

    def test_update_on_conflict_sets_name_on_ballot_and_committee_id(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)
        committee_id = self._make_committee(db_conn)

        initial_id = upsert_candidacy(
            db_conn,
            Candidacy(person_id=person_id, contest_id=contest_id),
        )
        updated_id = upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                name_on_ballot="JANE Q PUBLIC",
                committee_id=committee_id,
            ),
        )

        assert updated_id == initial_id

        row = db_conn.execute(
            "SELECT name_on_ballot, committee_id FROM civic.candidacy WHERE id = %s",
            (initial_id,),
        ).fetchone()
        assert row == ("JANE Q PUBLIC", committee_id)

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

    def test_insert_persists_mvp_fields(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)
        committee_id = self._make_committee(db_conn)
        raw_fields = {"native_candidate_id": "N-1234", "district": "01"}
        candidacy_id = upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                name_on_ballot="ALEX EXAMPLE",
                is_unexpired_term=True,
                raw_fields=raw_fields,
                committee_id=committee_id,
            ),
        )

        row = db_conn.execute(
            """
            SELECT name_on_ballot, is_unexpired_term, raw_fields, committee_id
            FROM civic.candidacy
            WHERE id = %s
            """,
            (candidacy_id,),
        ).fetchone()
        assert row == ("ALEX EXAMPLE", True, raw_fields, committee_id)

    def test_update_on_conflict_updates_mvp_fields(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)
        initial_committee_id = self._make_committee(db_conn)
        replacement_committee_id = self._make_committee(db_conn)

        candidacy_id = upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                name_on_ballot="ALEX EXAMPLE",
                is_unexpired_term=False,
                raw_fields={"source": "initial"},
                committee_id=initial_committee_id,
            ),
        )
        updated_id = upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                name_on_ballot="A. EXAMPLE",
                is_unexpired_term=True,
                raw_fields={"source": "updated"},
                committee_id=replacement_committee_id,
            ),
        )
        assert updated_id == candidacy_id

        row = db_conn.execute(
            """
            SELECT name_on_ballot, is_unexpired_term, raw_fields, committee_id
            FROM civic.candidacy
            WHERE id = %s
            """,
            (candidacy_id,),
        ).fetchone()
        assert row == ("A. EXAMPLE", True, {"source": "updated"}, replacement_committee_id)

    def test_update_on_conflict_preserves_omitted_stage1_fields(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_candidacy

        _, contest_id = self._make_contest(db_conn)
        person_id = _make_person(db_conn)
        committee_id = self._make_committee(db_conn)

        candidacy_id = upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                party="DEM",
                is_unexpired_term=True,
                raw_fields={"source": "initial"},
                committee_id=committee_id,
            ),
        )

        upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                party="REP",
            ),
        )

        row = db_conn.execute(
            """
            SELECT party, is_unexpired_term, raw_fields, committee_id
            FROM civic.candidacy
            WHERE id = %s
            """,
            (candidacy_id,),
        ).fetchone()
        assert row == ("REP", True, {"source": "initial"}, committee_id)

    def test_query_includes_mvp_columns_on_insert_and_update(self) -> None:
        from domains.civics.ingest import upsert_candidacy

        cursor = MagicMock()
        cursor.fetchone.return_value = (uuid4(),)
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        upsert_candidacy(
            connection,
            Candidacy(
                person_id=uuid4(),
                contest_id=uuid4(),
                name_on_ballot="ALEX EXAMPLE",
                is_unexpired_term=True,
                raw_fields={"source": "contract"},
                committee_id=uuid4(),
            ),
        )

        executed_sql = cursor.execute.call_args.args[0]
        for sql_fragment in (
            "name_on_ballot",
            "is_unexpired_term",
            "raw_fields",
            "committee_id",
            "name_on_ballot = COALESCE(EXCLUDED.name_on_ballot, civic.candidacy.name_on_ballot)",
            "is_unexpired_term = CASE WHEN %s THEN EXCLUDED.is_unexpired_term ELSE civic.candidacy.is_unexpired_term END",
            "raw_fields = CASE WHEN %s THEN EXCLUDED.raw_fields ELSE civic.candidacy.raw_fields END",
            "committee_id = COALESCE(EXCLUDED.committee_id, civic.candidacy.committee_id)",
        ):
            assert sql_fragment in executed_sql


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

    def test_rerun_same_natural_key_keeps_single_officeholding_row(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_officeholding

        office_id = self._make_office(db_conn)
        person_id = _make_person(db_conn, name=f"Officeholder {uuid4()}")
        source = _make_data_source(db_conn)
        first_source_record = _make_source_record(db_conn, source.id, f"officeholding-rerun-1-{uuid4()}")
        second_source_record = _make_source_record(db_conn, source.id, f"officeholding-rerun-2-{uuid4()}")

        first = Officeholding(
            person_id=person_id,
            office_id=office_id,
            holder_status="elected",
            valid_period={"start_date": date(2025, 1, 3), "end_date": date(2027, 1, 3)},
            source_record_id=first_source_record.id,
        )
        rerun = first.model_copy(update={"id": uuid4(), "source_record_id": second_source_record.id})

        first_id = upsert_officeholding(db_conn, first)
        second_id = upsert_officeholding(db_conn, rerun)
        assert first_id == second_id

        row = db_conn.execute(
            """
            SELECT COUNT(*), source_record_id
            FROM civic.officeholding
            WHERE person_id = %s
              AND office_id = %s
              AND valid_period IS NOT DISTINCT FROM daterange(%s, %s)
            GROUP BY source_record_id
            """,
            (person_id, office_id, date(2025, 1, 3), date(2027, 1, 3)),
        ).fetchone()
        assert row == (1, second_source_record.id)

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

    def test_bounded_former_officeholding_does_not_derive_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import derive_incumbent_challenge, upsert_officeholding

        office_id = self._make_office(db_conn)
        person_id = _make_person(db_conn, name=f"Former Officeholder {uuid4()}")
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=office_id,
                holder_status="former",
                valid_period={"start_date": date(2021, 1, 3), "end_date": date(2025, 1, 3)},
            ),
        )

        result = derive_incumbent_challenge(db_conn, person_id, office_id, as_of=date(2024, 6, 1))
        assert result is None


# ---------------------------------------------------------------------------
# Office roster link upsert tests
# ---------------------------------------------------------------------------


class TestUpsertOfficeRosterLink:
    def test_insert_returns_uuid_and_persists_row(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office, upsert_office_roster_link

        office_id = upsert_office(
            db_conn, Office(name=f"durham_nc_mayor_{uuid4()}", office_level="municipal", state="NC")
        )
        data_source = _make_data_source(db_conn)

        link_id = upsert_office_roster_link(
            db_conn,
            OfficeRosterLink(office_id=office_id, data_source_id=data_source.id),
        )
        assert isinstance(link_id, UUID)

        row = db_conn.execute(
            "SELECT office_id, data_source_id FROM civic.office_roster_link WHERE id = %s",
            (link_id,),
        ).fetchone()
        assert row == (office_id, data_source.id)

    def test_idempotent_reinsert_returns_same_uuid(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office, upsert_office_roster_link

        office_id = upsert_office(db_conn, Office(name=f"nc_house_member_{uuid4()}", office_level="state", state="NC"))
        data_source = _make_data_source(db_conn)
        first_link_id = upsert_office_roster_link(
            db_conn,
            OfficeRosterLink(office_id=office_id, data_source_id=data_source.id),
        )
        second_link_id = upsert_office_roster_link(
            db_conn,
            OfficeRosterLink(id=uuid4(), office_id=office_id, data_source_id=data_source.id),
        )
        assert first_link_id == second_link_id

        row = db_conn.execute(
            "SELECT COUNT(*) FROM civic.office_roster_link WHERE office_id = %s AND data_source_id = %s",
            (office_id, data_source.id),
        ).fetchone()
        assert row[0] == 1

    def test_upsert_has_no_entity_source_or_officeholding_side_effects(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import upsert_office, upsert_office_roster_link

        office_id = upsert_office(
            db_conn,
            Office(name=f"durham_nc_city_council_member_{uuid4()}", office_level="municipal", state="NC"),
        )
        data_source = _make_data_source(db_conn)
        entity_source_count_before = db_conn.execute("SELECT COUNT(*) FROM core.entity_source").fetchone()[0]
        officeholding_count_before = db_conn.execute("SELECT COUNT(*) FROM civic.officeholding").fetchone()[0]

        upsert_office_roster_link(
            db_conn,
            OfficeRosterLink(office_id=office_id, data_source_id=data_source.id),
        )

        entity_source_count_after = db_conn.execute("SELECT COUNT(*) FROM core.entity_source").fetchone()[0]
        officeholding_count_after = db_conn.execute("SELECT COUNT(*) FROM civic.officeholding").fetchone()[0]
        assert entity_source_count_after == entity_source_count_before
        assert officeholding_count_after == officeholding_count_before


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

    def test_repoint_candidacy_person_merge_preserves_candidacy_entity_source(
        self, db_conn: psycopg.Connection
    ) -> None:
        from domains.civics.ingest import repoint_candidacy_person, upsert_candidacy, upsert_contest, upsert_office

        data_source = _make_data_source(db_conn)
        target_source_record = _make_source_record(db_conn, data_source.id, f"target-candidacy-source-{uuid4()}")
        source_source_record = _make_source_record(db_conn, data_source.id, f"source-candidacy-source-{uuid4()}")

        office_id = upsert_office(
            db_conn, Office(name=f"merge-prov-office-{uuid4()}", office_level="state", state="NC")
        )
        contest_id = upsert_contest(
            db_conn,
            Contest(
                name=f"Merge Prov Contest {uuid4()}",
                election_date=date(2024, 11, 5),
                election_type="general",
                office_id=office_id,
            ),
        )
        target_person_id = _make_person(db_conn, name=f"Target Person {uuid4()}")
        source_person_id = _make_person(db_conn, name=f"Source Person {uuid4()}")
        target_candidacy_id = upsert_candidacy(
            db_conn,
            Candidacy(person_id=target_person_id, contest_id=contest_id, source_record_id=target_source_record.id),
        )
        source_candidacy_id = upsert_candidacy(
            db_conn,
            Candidacy(person_id=source_person_id, contest_id=contest_id, source_record_id=source_source_record.id),
        )

        repointed = repoint_candidacy_person(
            db_conn,
            candidacy_id=source_candidacy_id,
            expected_person_id=source_person_id,
            target_person_id=target_person_id,
        )

        assert repointed is True

        merged_candidacy_rows = db_conn.execute(
            "SELECT id FROM civic.candidacy WHERE person_id = %s AND contest_id = %s",
            (target_person_id, contest_id),
        ).fetchall()
        assert merged_candidacy_rows == [(target_candidacy_id,)]

        source_row = db_conn.execute(
            "SELECT id FROM civic.candidacy WHERE id = %s",
            (source_candidacy_id,),
        ).fetchone()
        assert source_row is None

        source_record_ids = db_conn.execute(
            """
            SELECT source_record_id
            FROM core.entity_source
            WHERE entity_type = 'candidacy'
              AND entity_id = %s
            ORDER BY source_record_id
            """,
            (target_candidacy_id,),
        ).fetchall()
        assert source_record_ids == sorted(
            [(target_source_record.id,), (source_source_record.id,)],
            key=lambda row: row[0],
        )
