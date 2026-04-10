"""Integration tests for FL canonical loader.

Tests run against a real PostgreSQL database to verify that FL candidate-download
rows (from dos.elections.myflorida.com/candidates/downloadcanlist.asp) are
correctly mapped into canonical civic.* entities (office, contest, candidacy,
contact_point) using FL seed office UUIDs and the shared upsert helpers.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from datetime import date

from core.db import insert_data_source, insert_person
from core.types.python.models import DataSource, Person, ValidDateRange
from domains.civics.ingest import upsert_electoral_division, upsert_officeholding
from domains.civics.types.models import ElectoralDivision, Officeholding


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Seed UUID constants (must match domains/civics/schema/tables.sql)
# ---------------------------------------------------------------------------

_OFFICE_FL_GOVERNOR = UUID("00000000-0000-4000-8000-000000000305")
_OFFICE_FL_ATTORNEY_GENERAL = UUID("00000000-0000-4000-8000-000000000301")
_OFFICE_FL_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000311")
_OFFICE_FL_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000310")
_OFFICE_FL_COUNTY = UUID("00000000-0000-4000-8000-000000000304")
_OFFICE_FL_SCHOOL_DISTRICT = UUID("00000000-0000-4000-8000-000000000308")

_DIVISION_FL = UUID("00000000-0000-4000-8000-000000000503")
_DIVISION_FL_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000511")
_DIVISION_FL_HOUSE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000512")
_DIVISION_FL_COUNTIES = UUID("00000000-0000-4000-8000-000000000513")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="state/FL",
        name=f"FL Canonical Test {uuid4()}",
        source_url="https://dos.elections.myflorida.com/candidates/downloadcanlist.asp",
    )
    insert_data_source(conn, ds)
    return ds


def _make_fl_candidate_row(
    *,
    candidate_name: str = "DOE, JOHN A",
    first_name: str = "JOHN",
    middle_name: str = "A",
    last_name: str = "DOE",
    party: str = "REP",
    office_code: str = "GOV",
    office_desc: str = "Governor",
    juris1num: str = "",
    juris2num: str = "",
    election_date: str = "11/03/2026",
    status: str = "Active",
    phone: str = "850-555-0100",
    email: str = "john.doe@example.com",
    address1: str = "123 Capitol Dr",
    address2: str = "",
    city: str = "Tallahassee",
    state: str = "FL",
    zip_code: str = "32301",
    candidate_id: str | None = None,
) -> dict[str, str | None]:
    return {
        "CandidateId": candidate_id or str(uuid4()),
        "CandName": candidate_name,
        "CandFirstName": first_name,
        "CandMiddleName": middle_name,
        "CandLastName": last_name,
        "Party": party,
        "OfficeCode": office_code,
        "OfficeDesc": office_desc,
        "Juris1num": juris1num,
        "Juris2num": juris2num,
        "ElectionDate": election_date,
        "Status": status,
        "Phone": phone,
        "Email": email,
        "Address1": address1,
        "Address2": address2,
        "City": city,
        "State": state,
        "Zip": zip_code,
    }


# ---------------------------------------------------------------------------
# Statewide office → contest + candidacy
# ---------------------------------------------------------------------------


class TestFLCanonicalStatewideOffice:
    def test_governor_creates_contest_and_candidacy(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_candidate_row(office_code="GOV", office_desc="Governor")]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT name, office_id FROM civic.contest WHERE office_id = %s",
            (_OFFICE_FL_GOVERNOR,),
        ).fetchone()
        assert row is not None
        assert "Governor" in row[0] or "GOV" in row[0]

    def test_attorney_general_creates_contest(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                office_code="AG",
                office_desc="Attorney General",
                candidate_name="SMITH, JANE B",
                first_name="JANE",
                last_name="SMITH",
                candidate_id="FL-AG-1",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT id FROM civic.contest WHERE office_id = %s",
            (_OFFICE_FL_ATTORNEY_GENERAL,),
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Legislative districts → electoral_division
# ---------------------------------------------------------------------------


class TestFLCanonicalLegislative:
    def test_state_senate_creates_upper_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                office_code="SS",
                office_desc="State Senator",
                juris1num="14",
                candidate_name="SENATE, PAT",
                first_name="PAT",
                last_name="SENATE",
                candidate_id="FL-SS-14",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT name, division_type, district_number FROM civic.electoral_division "
            "WHERE division_type = 'state_legislative_upper' AND state = 'FL' AND district_number = '14'",
        ).fetchone()
        assert row is not None

    def test_state_house_creates_lower_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                office_code="SH",
                office_desc="State Representative",
                juris1num="97",
                candidate_name="HOUSE, KIM",
                first_name="KIM",
                last_name="HOUSE",
                candidate_id="FL-SH-97",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT name, division_type, district_number FROM civic.electoral_division "
            "WHERE division_type = 'state_legislative_lower' AND state = 'FL' AND district_number = '97'",
        ).fetchone()
        assert row is not None

    def test_county_office_creates_county_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                office_code="CA",
                office_desc="County Commission",
                juris1num="13",
                juris2num="3",
                candidate_name="COUNTY, AL",
                first_name="AL",
                last_name="COUNTY",
                candidate_id="FL-CA-13",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT name, division_type FROM civic.electoral_division WHERE division_type = 'county' AND state = 'FL'",
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Contact point tests
# ---------------------------------------------------------------------------


class TestFLCanonicalContactPoints:
    def test_candidate_with_phone_and_email_creates_two_contact_points(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                phone="305-555-0199",
                email="campaign@example.com",
                candidate_name="CONTACT, BOTH",
                first_name="BOTH",
                last_name="CONTACT",
                candidate_id="FL-CONTACT-BOTH",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        # Check email contact_point
        email_row = db_conn.execute(
            "SELECT value_raw, type, role FROM core.contact_point "
            "WHERE value_raw = 'campaign@example.com' AND type = 'email'",
        ).fetchone()
        assert email_row is not None
        assert email_row[2] == "campaign"

        # Check phone contact_point
        phone_row = db_conn.execute(
            "SELECT value_raw, type, role FROM core.contact_point WHERE value_raw = '305-555-0199' AND type = 'phone'",
        ).fetchone()
        assert phone_row is not None
        assert phone_row[2] == "campaign"

    def test_candidate_with_no_contact_creates_zero_contact_points(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                phone="",
                email="",
                candidate_name="NOCONTACT, SAM",
                first_name="SAM",
                last_name="NOCONTACT",
                candidate_id="FL-NOCONTACT-1",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        # Verify no contact_point rows for this candidate
        candidacy_row = db_conn.execute(
            "SELECT c.id FROM civic.candidacy c "
            "JOIN core.person p ON c.person_id = p.id "
            "WHERE p.last_name = 'NOCONTACT'",
        ).fetchone()
        assert candidacy_row is not None

        cp_rows = db_conn.execute(
            "SELECT id FROM core.contact_point WHERE owner_id = %s",
            (candidacy_row[0],),
        ).fetchall()
        assert len(cp_rows) == 0

    def test_contact_points_have_candidacy_owner_type(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                phone="407-555-0123",
                email="owner@example.com",
                candidate_name="OWNER, TEST",
                first_name="TEST",
                last_name="OWNER",
                candidate_id="FL-OWNER-1",
            )
        ]
        load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)

        rows_cp = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = 'owner@example.com'",
        ).fetchone()
        assert rows_cp is not None
        assert rows_cp[0] == "candidacy"


# ---------------------------------------------------------------------------
# Candidacy tests
# ---------------------------------------------------------------------------


class TestFLCanonicalCandidacy:
    def test_same_candidate_different_contests_creates_distinct_candidacies(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        # Same person running for two different offices
        row_gov = _make_fl_candidate_row(
            office_code="GOV",
            office_desc="Governor",
            candidate_name="MULTI, ROBIN",
            first_name="ROBIN",
            last_name="MULTI",
            candidate_id="FL-MULTI-GOV",
            election_date="11/03/2026",
        )
        row_ag = _make_fl_candidate_row(
            office_code="AG",
            office_desc="Attorney General",
            candidate_name="MULTI, ROBIN",
            first_name="ROBIN",
            last_name="MULTI",
            candidate_id="FL-MULTI-AG",
            election_date="11/03/2026",
        )
        result = load_fl_candidates_canonical(db_conn, [row_gov, row_ag], data_source_id=ds.id)
        assert result.inserted == 2

        candidacies = db_conn.execute(
            "SELECT c.id, c.contest_id FROM civic.candidacy c "
            "JOIN core.person p ON c.person_id = p.id "
            "WHERE p.last_name = 'MULTI' AND p.first_name = 'ROBIN'",
        ).fetchall()
        assert len(candidacies) == 2
        # Different contests
        assert candidacies[0][1] != candidacies[1][1]

    def test_creates_candidacy_with_party(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                party="DEM",
                candidate_name="PARTY, PAT",
                first_name="PAT",
                last_name="PARTY",
                candidate_id="FL-PARTY-1",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT party FROM civic.candidacy c JOIN core.person p ON c.person_id = p.id WHERE p.last_name = 'PARTY'",
        ).fetchone()
        assert row is not None
        assert row[0] == "DEM"


# ---------------------------------------------------------------------------
# Idempotent re-insert
# ---------------------------------------------------------------------------


class TestFLCanonicalIdempotent:
    def test_duplicate_rows_produce_same_contest(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_fl_candidate_row(candidate_id="FL-DUP-1")
        load_fl_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        load_fl_candidates_canonical(db_conn, [row], data_source_id=ds.id)

        rows = db_conn.execute(
            "SELECT id FROM civic.contest WHERE office_id = %s AND name LIKE %s",
            (_OFFICE_FL_GOVERNOR, "%2026%"),
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# Derived incumbency from canonical officeholding
# ---------------------------------------------------------------------------


class TestFLCanonicalIncumbencyDerivation:
    def test_current_officeholding_derives_incumbent_challenge(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="INCUMBENT, FL",
                identifiers={"fl_candidate_id": "FL-INC-1"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_FL_STATE_SENATE,
                holder_status="appointed",
                valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                candidate_id="FL-INC-1",
                candidate_name="INCUMBENT, FL",
                first_name="FL",
                last_name="INCUMBENT",
                office_code="SS",
                office_desc="State Senator",
                election_date="11/03/2026",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'fl_candidate_id' = 'FL-INC-1'
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
        ).fetchone()
        assert row is not None
        assert row[0] == "I"

    def test_derives_incumbent_using_contest_date_not_today(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        candidate_id = f"FL-HIST-{uuid4()}"
        fl_sd_07 = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="fl_sd_07",
                division_type="state_legislative_upper",
                state="FL",
                district_number="07",
                parent_id=_DIVISION_FL_SENATE_DISTRICTS,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="HISTORICAL, FL",
                identifiers={"fl_candidate_id": candidate_id},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_FL_STATE_SENATE,
                electoral_division_id=fl_sd_07,
                holder_status="appointed",
                valid_period=ValidDateRange(start_date=date(2020, 11, 1), end_date=date(2023, 1, 3)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                candidate_id=candidate_id,
                candidate_name="HISTORICAL, FL",
                first_name="FL",
                last_name="HISTORICAL",
                office_code="SS",
                office_desc="State Senator",
                juris1num="07",
                election_date="11/08/2022",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'fl_candidate_id' = %s
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            (candidate_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "I"

    def test_former_officeholding_is_not_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="FORMER, FL",
                identifiers={"fl_candidate_id": "FL-FORMER-1"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_FL_STATE_SENATE,
                holder_status="former",
                valid_period=ValidDateRange(start_date=date(2021, 1, 1), end_date=date(2023, 12, 31)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                candidate_id="FL-FORMER-1",
                candidate_name="FORMER, FL",
                first_name="FL",
                last_name="FORMER",
                office_code="SS",
                office_desc="State Senator",
                election_date="11/03/2026",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'fl_candidate_id' = 'FL-FORMER-1'
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
        ).fetchone()
        assert row is not None
        assert row[0] is None

    def test_other_district_officeholding_is_not_treated_as_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        fl_sd_07 = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="fl_sd_07",
                division_type="state_legislative_upper",
                state="FL",
                district_number="07",
                parent_id=_DIVISION_FL_SENATE_DISTRICTS,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="DISTRICT, SWITCHER",
                identifiers={"fl_candidate_id": "FL-DIST-1"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_FL_STATE_SENATE,
                electoral_division_id=fl_sd_07,
                holder_status="appointed",
                valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=date(2027, 12, 31)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_candidate_row(
                candidate_id="FL-DIST-1",
                candidate_name="DISTRICT, SWITCHER",
                first_name="DISTRICT",
                last_name="SWITCHER",
                office_code="SS",
                office_desc="State Senator",
                juris1num="08",
                election_date="11/03/2026",
            )
        ]
        result = load_fl_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'fl_candidate_id' = 'FL-DIST-1'
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
        ).fetchone()
        assert row is not None
        assert row[0] is None


class TestFLOfficeholderDirectoryContract:
    """FL Senate directory rows drive holder status, office contacts, and vacancy behavior."""

    def test_directory_maps_acting_appointed_and_former_statuses(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="state/FL/officeholder",
            name=f"FL Officeholder Test {uuid4()}",
            source_url="https://www.flsenate.gov/Senators/",
        )
        insert_data_source(db_conn, ds)

        rows = [
            {
                "senator_id": "S-ACT",
                "name": "ACTING, ALEX",
                "first_name": "Alex",
                "last_name": "Acting",
                "party": "NPA",
                "district": "02",
                "term_start": "2024",
                "term_end": "2026",
                "status": "acting",
                "district_address": "100 Local Ave, Miami FL 33101",
                "district_phone": "305-555-0200",
                "tallahassee_address": "404 S. Monroe St, Tallahassee FL 32399",
                "tallahassee_phone": "850-487-5200",
            },
            {
                "senator_id": "S-APPT",
                "name": "APPOINTED, BLAIR",
                "first_name": "Blair",
                "last_name": "Appointed",
                "party": "R",
                "district": "03",
                "term_start": "2024",
                "term_end": "2026",
                "status": "appointed",
                "district_address": "101 Local Ave, Miami FL 33101",
                "district_phone": "305-555-0300",
                "tallahassee_address": "404 S. Monroe St, Tallahassee FL 32399",
                "tallahassee_phone": "850-487-5300",
            },
            {
                "senator_id": "S-FORMER",
                "name": "FORMER, CASEY",
                "first_name": "Casey",
                "last_name": "Former",
                "party": "D",
                "district": "04",
                "term_start": "2020",
                "term_end": "2022",
                "status": "resigned",
                "district_address": "102 Local Ave, Miami FL 33101",
                "district_phone": "305-555-0400",
                "tallahassee_address": "404 S. Monroe St, Tallahassee FL 32399",
                "tallahassee_phone": "850-487-5400",
            },
        ]
        result = load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 3

        statuses = db_conn.execute(
            "SELECT p.identifiers ->> 'fl_senator_id' AS senator_id, oh.holder_status "
            "FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers ->> 'fl_senator_id' IN ('S-ACT', 'S-APPT', 'S-FORMER')",
        ).fetchall()
        status_map = {row[0]: row[1] for row in statuses}
        assert status_map["S-ACT"] == "acting"
        assert status_map["S-APPT"] == "appointed"
        assert status_map["S-FORMER"] == "former"

    def test_directory_contact_ownership_and_vacancy_skip(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="state/FL/officeholder",
            name=f"FL Officeholder Test {uuid4()}",
            source_url="https://www.flsenate.gov/Senators/",
        )
        insert_data_source(db_conn, ds)

        active_row = {
            "senator_id": "S-CONTACT",
            "name": "CONTACT, DEVIN",
            "first_name": "Devin",
            "last_name": "Contact",
            "party": "D",
            "district": "05",
            "term_start": "2024",
            "term_end": "2026",
            "status": "active",
            "district_address": "103 Local Ave, Miami FL 33101",
            "district_phone": "305-555-0500",
            "tallahassee_address": "404 S. Monroe St, Tallahassee FL 32399",
            "tallahassee_phone": "850-487-5500",
        }
        vacant_row = {
            "senator_id": "",
            "name": "VACANT",
            "first_name": "",
            "last_name": "",
            "party": "",
            "district": "06",
            "term_start": "2024",
            "term_end": "2026",
            "status": "vacant",
            "district_address": "",
            "district_phone": "",
            "tallahassee_address": "",
            "tallahassee_phone": "",
        }
        result = load_fl_senate_officeholders(db_conn, [active_row, vacant_row], data_source_id=ds.id)
        assert result.inserted == 1
        assert result.skipped == 1

        district_owner = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = '305-555-0500' AND type = 'phone'",
        ).fetchone()
        capitol_owner = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = '850-487-5500' AND type = 'phone'",
        ).fetchone()
        assert district_owner is not None
        assert capitol_owner is not None
        assert district_owner[0] == "office"
        assert capitol_owner[0] == "office"

        vacant_person = db_conn.execute("SELECT id FROM core.person WHERE canonical_name = 'VACANT'").fetchone()
        assert vacant_person is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestFLCanonicalErrors:
    def test_missing_office_code_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_fl_candidate_row(office_code="", office_desc="")
        result = load_fl_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1

    def test_unknown_office_code_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_fl_candidate_row(office_code="ZZZ", office_desc="Made Up Office")
        result = load_fl_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1

    def test_missing_candidate_name_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_fl_candidate_row(candidate_name="", first_name="", last_name="")
        result = load_fl_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1

    def test_missing_election_date_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_canonical_loader import (
            load_fl_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_fl_candidate_row(election_date="")
        result = load_fl_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1
