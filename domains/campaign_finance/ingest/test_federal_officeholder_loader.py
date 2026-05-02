"""Integration tests for federal officeholder loader.

Verifies that House Clerk XML and Senate XML member rows are correctly mapped
into civic.officeholding + core.contact_point via the shared upsert helpers,
with proper holder_status, term windows, and contact ownership semantics.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source
from core.types.python.models import DataSource


pytestmark = pytest.mark.integration

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")
DIVISION_US_STATEWIDE = UUID("00000000-0000-4000-8000-000000000501")
DIVISION_US_CONGRESSIONAL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000504")
_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "roster"


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/officeholder",
        name=f"Federal Officeholder Test {uuid4()}",
        source_url="https://clerk.house.gov/xml/lists/MemberData.xml",
    )
    insert_data_source(conn, ds)
    return ds


def _fixture_text(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_normalize_house_xml_rows_contract() -> None:
    from domains.campaign_finance.ingest.federal_officeholder_loader import normalize_house_xml_rows

    rows = normalize_house_xml_rows(_fixture_text("us_house_member_data_sample.xml"))

    assert len(rows) == 2
    assert rows[0]["member_name"] == "Casey Brown"
    assert rows[0]["state"] == "NC"
    assert rows[0]["district"] == "12"
    assert rows[0]["sworn_date"] == "2025-01-03"


def test_normalize_senate_xml_rows_contract() -> None:
    from domains.campaign_finance.ingest.federal_officeholder_loader import normalize_senate_xml_rows

    rows = normalize_senate_xml_rows(_fixture_text("us_senate_contact_information_sample.xml"))

    assert len(rows) == 2
    assert rows[0]["member_full"] == "Pat Smith"
    assert rows[0]["state"] == "GA"
    assert rows[0]["class"] == "2"
    assert rows[0]["email"] == "pat_smith@senate.gov"


def _make_house_member_row(
    *,
    bioguide_id: str = "A000001",
    member_name: str = "DOE, Jane",
    first_name: str = "Jane",
    last_name: str = "DOE",
    state: str = "NC",
    district: str = "01",
    party: str = "D",
    phone: str = "202-225-0001",
    office_building: str = "RHOB",
    office_room: str = "1234",
    office_zip: str = "20515-3301",
    elected_date: str = "2022-11-08",
    sworn_date: str = "2023-01-03",
) -> dict[str, str | None]:
    """Simulate a parsed House Clerk XML member row."""
    return {
        "bioguide_id": bioguide_id,
        "member_name": member_name,
        "first_name": first_name,
        "last_name": last_name,
        "state": state,
        "district": district,
        "party": party,
        "phone": phone,
        "office_building": office_building,
        "office_room": office_room,
        "office_zip": office_zip,
        "elected_date": elected_date,
        "sworn_date": sworn_date,
    }


def _make_senate_member_row(
    *,
    bioguide_id: str = "S000001",
    member_full: str = "John Smith",
    first_name: str = "John",
    last_name: str = "Smith",
    state: str = "NC",
    party: str = "R",
    class_num: str = "2",
    phone: str = "202-224-0001",
    email: str = "senator@smith.senate.gov",
    website: str = "https://smith.senate.gov",
    address: str = "123 Hart Senate Office Building",
) -> dict[str, str | None]:
    """Simulate a parsed Senate XML member row."""
    return {
        "bioguide_id": bioguide_id,
        "member_full": member_full,
        "first_name": first_name,
        "last_name": last_name,
        "state": state,
        "party": party,
        "class": class_num,
        "phone": phone,
        "email": email,
        "website": website,
        "address": address,
    }


# ---------------------------------------------------------------------------
# House officeholder ingestion
# ---------------------------------------------------------------------------


class TestFederalHouseOfficeholderIngest:
    """House Clerk XML members produce officeholding + contact records."""

    def test_house_member_creates_officeholding(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_house_member_row()]
        result = load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT holder_status, office_id FROM civic.officeholding WHERE office_id = %s",
            (OFFICE_US_HOUSE,),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_house_member_creates_congressional_district_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_house_member_row(state="WA", district="07")]
        load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT oh.electoral_division_id FROM civic.officeholding oh "
            "JOIN civic.electoral_division ed ON ed.id = oh.electoral_division_id "
            "WHERE ed.name = 'wa_cd_07' AND ed.division_type = 'congressional_district'",
        ).fetchone()
        assert row is not None

    def test_house_member_phone_creates_office_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_house_member_row(phone="202-225-9999", bioguide_id="H-PHONE-1")]
        load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type, type, value_raw FROM core.contact_point "
            "WHERE value_raw = '202-225-9999' AND type = 'phone'",
        ).fetchone()
        assert cp is not None
        # Directory phone is institutional — attaches to office, not officeholding
        assert cp[0] == "office"

    def test_house_member_term_window_from_sworn_date(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_house_member_row(sworn_date="2023-01-03", bioguide_id="H-TERM-1")]
        load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT lower(valid_period), upper(valid_period) FROM civic.officeholding "
            "JOIN core.person p ON p.id = civic.officeholding.person_id "
            "WHERE p.identifiers @> %s",
            ('{"bioguide_id": "H-TERM-1"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == date(2023, 1, 3)
        # House terms end at start of next Congress (Jan 3, odd year + 2)
        assert row[1] == date(2025, 1, 3)


# ---------------------------------------------------------------------------
# Senate officeholder ingestion
# ---------------------------------------------------------------------------


class TestFederalSenateOfficeholderIngest:
    """Senate XML members produce officeholding + contact records."""

    def test_senate_member_creates_officeholding(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_senate_member_row()]
        result = load_federal_senate_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT holder_status, office_id FROM civic.officeholding WHERE office_id = %s",
            (OFFICE_US_SENATE,),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_senate_member_creates_statewide_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_senate_member_row(state="GA", bioguide_id="S-GA-1")]
        load_federal_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT ed.division_type FROM civic.officeholding oh "
            "JOIN civic.electoral_division ed ON ed.id = oh.electoral_division_id "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"bioguide_id": "S-GA-1"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == "statewide"

    def test_senate_member_email_creates_officeholding_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_senate_member_row(email="test@senate.gov", bioguide_id="S-EMAIL-1")]
        load_federal_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type, type, value_raw FROM core.contact_point "
            "WHERE value_raw = 'test@senate.gov' AND type = 'email'",
        ).fetchone()
        assert cp is not None
        assert cp[0] == "officeholding"

    def test_senate_member_phone_creates_office_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_senate_member_row(phone="202-224-9999", bioguide_id="S-PHONE-1")]
        load_federal_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = '202-224-9999' AND type = 'phone'",
        ).fetchone()
        assert cp is not None
        assert cp[0] == "office"


# ---------------------------------------------------------------------------
# Holder status variants
# ---------------------------------------------------------------------------


class TestFederalHolderStatus:
    """Verify elected/appointed/acting/former status handling."""

    def test_elected_is_default_status(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        rows = [_make_house_member_row(bioguide_id="STATUS-ELECTED")]
        load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"bioguide_id": "STATUS-ELECTED"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_appointed_member_gets_appointed_status(self, db_conn: psycopg.Connection) -> None:
        """Senate appointments (e.g. gubernatorial) should be marked 'appointed'."""
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)
        row = _make_senate_member_row(bioguide_id="STATUS-APPT")
        # Source indicates appointment via missing elected_date / explicit flag
        row["appointed"] = "true"
        load_federal_senate_officeholders(db_conn, [row], data_source_id=ds.id)

        result = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"bioguide_id": "STATUS-APPT"}',),
        ).fetchone()
        assert result is not None
        assert result[0] == "appointed"


# ---------------------------------------------------------------------------
# Person reuse via bioguide_id
# ---------------------------------------------------------------------------


class TestFederalPersonReuse:
    """Same bioguide_id across House and Senate should reuse the same person."""

    def test_same_bioguide_reuses_person(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import (
            load_federal_house_officeholders,
            load_federal_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        house_row = _make_house_member_row(bioguide_id="REUSE-BIO-1", state="NC", district="01")
        senate_row = _make_senate_member_row(bioguide_id="REUSE-BIO-1", state="NC")
        load_federal_house_officeholders(db_conn, [house_row], data_source_id=ds.id)
        load_federal_senate_officeholders(db_conn, [senate_row], data_source_id=ds.id)

        persons = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "REUSE-BIO-1"}',),
        ).fetchall()
        assert len(persons) == 1

        # Two officeholdings for different offices
        holdings = db_conn.execute(
            "SELECT office_id FROM civic.officeholding WHERE person_id = %s ORDER BY office_id",
            (persons[0][0],),
        ).fetchall()
        assert len(holdings) == 2


# ---------------------------------------------------------------------------
# Vacancy: no fake person record
# ---------------------------------------------------------------------------


class TestFederalVacancy:
    """Vacant seats should NOT produce fake person-backed officeholding rows."""

    def test_vacant_seat_not_encoded_as_person(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        # A vacant row might come from the House Clerk XML with "VACANT" as member name
        vacant_row = _make_house_member_row(
            bioguide_id="",
            member_name="VACANT",
            first_name="",
            last_name="VACANT",
            state="NC",
            district="02",
        )
        result = load_federal_house_officeholders(db_conn, [vacant_row], data_source_id=ds.id)
        # Vacant rows should be skipped, not inserted
        assert result.skipped >= 1

        # No person named "VACANT" should exist
        row = db_conn.execute(
            "SELECT id FROM core.person WHERE canonical_name = 'VACANT'",
        ).fetchone()
        assert row is None

    def test_vacancy_retires_prior_house_holder(self, db_conn: psycopg.Connection) -> None:
        """When a vacancy row appears for a House seat, the prior officeholding must be retired."""
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)

        # First load: active holder in NC-02
        holder_row = _make_house_member_row(
            bioguide_id="VAC-RETIRE-1",
            first_name="Jane",
            last_name="DOE",
            state="NC",
            district="02",
            sworn_date="2023-01-03",
        )
        load_federal_house_officeholders(db_conn, [holder_row], data_source_id=ds.id)

        person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "VAC-RETIRE-1"}',),
        ).fetchone()
        assert person is not None
        oh_before = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], OFFICE_US_HOUSE),
        ).fetchone()
        assert oh_before[0] == "elected"

        # Second load: vacancy row for same district
        vacant_row = _make_house_member_row(
            bioguide_id="",
            member_name="VACANT",
            first_name="",
            last_name="VACANT",
            state="NC",
            district="02",
        )
        load_federal_house_officeholders(db_conn, [vacant_row], data_source_id=ds.id)

        # The prior holder's officeholding should now be 'former'
        oh_after = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], OFFICE_US_HOUSE),
        ).fetchone()
        assert oh_after[0] == "former"

    def test_vacancy_retires_prior_senate_holder(self, db_conn: psycopg.Connection) -> None:
        """When a vacancy row appears for a Senate seat, the prior officeholding must be retired."""
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)

        # First load: active senator in GA
        holder_row = _make_senate_member_row(
            bioguide_id="VAC-SEN-1",
            first_name="John",
            last_name="Smith",
            state="GA",
        )
        load_federal_senate_officeholders(db_conn, [holder_row], data_source_id=ds.id)

        person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "VAC-SEN-1"}',),
        ).fetchone()
        assert person is not None

        # Second load: vacancy row for same state
        vacant_row = _make_senate_member_row(
            bioguide_id="",
            member_full="VACANT",
            first_name="",
            last_name="",
            state="GA",
        )
        load_federal_senate_officeholders(db_conn, [vacant_row], data_source_id=ds.id)

        # The prior holder should now be 'former'
        oh_after = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], OFFICE_US_SENATE),
        ).fetchone()
        assert oh_after[0] == "former"

    def test_vacancy_retires_only_matching_senate_class(self, db_conn: psycopg.Connection) -> None:
        """Vacancy retirement must only affect the vacated Senate class seat."""
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = _make_data_source(db_conn)

        class_two_holder = _make_senate_member_row(
            bioguide_id="VAC-SEN-C2",
            first_name="Alice",
            last_name="ClassTwo",
            state="GA",
            class_num="2",
        )
        class_three_holder = _make_senate_member_row(
            bioguide_id="VAC-SEN-C3",
            first_name="Bob",
            last_name="ClassThree",
            state="GA",
            class_num="3",
        )
        load_federal_senate_officeholders(
            db_conn,
            [class_two_holder, class_three_holder],
            data_source_id=ds.id,
        )

        class_two_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "VAC-SEN-C2"}',),
        ).fetchone()
        class_three_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "VAC-SEN-C3"}',),
        ).fetchone()
        assert class_two_person is not None
        assert class_three_person is not None

        vacant_class_two_row = _make_senate_member_row(
            bioguide_id="",
            member_full="VACANT",
            first_name="",
            last_name="",
            state="GA",
            class_num="2",
        )
        load_federal_senate_officeholders(db_conn, [vacant_class_two_row], data_source_id=ds.id)

        class_two_status = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (class_two_person[0], OFFICE_US_SENATE),
        ).fetchone()
        class_three_status = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (class_three_person[0], OFFICE_US_SENATE),
        ).fetchone()
        assert class_two_status is not None
        assert class_three_status is not None
        assert class_two_status[0] == "former"
        assert class_three_status[0] == "elected"


# ---------------------------------------------------------------------------
# LoadResult
# ---------------------------------------------------------------------------


class TestFederalLoadResult:
    def test_returns_load_result_with_counts(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = _make_data_source(db_conn)
        rows = [
            _make_house_member_row(bioguide_id="LR-1"),
            _make_house_member_row(bioguide_id="LR-2", state="WA", district="07"),
        ]
        result = load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 2
        assert result.errors == 0

    def test_db_error_rolls_back_failed_row_and_continues_batch(
        self,
        db_conn: psycopg.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import domains.campaign_finance.ingest.federal_officeholder_loader as loader

        ds = _make_data_source(db_conn)
        original = loader._resolve_house_division
        should_fail_once = True

        def _flaky_resolve_house_division(
            conn: psycopg.Connection,
            state: str | None,
            district: str | None,
        ) -> UUID | None:
            nonlocal should_fail_once
            if should_fail_once:
                should_fail_once = False
                conn.execute("SELECT * FROM missing_stage_review_table")
            return original(conn, state, district)

        monkeypatch.setattr(loader, "_resolve_house_division", _flaky_resolve_house_division)

        result = loader.load_federal_house_officeholders(
            db_conn,
            [
                _make_house_member_row(bioguide_id="ERR-HOUSE-1", district="01"),
                _make_house_member_row(bioguide_id="GOOD-HOUSE-2", district="02"),
            ],
            data_source_id=ds.id,
        )

        assert result.errors == 1
        assert result.inserted == 1
        failed_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "ERR-HOUSE-1"}',),
        ).fetchone()
        successful_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "GOOD-HOUSE-2"}',),
        ).fetchone()
        assert failed_person is None
        assert successful_person is not None


# ---------------------------------------------------------------------------
# Incumbency derivation from canonical officeholding
# ---------------------------------------------------------------------------


class TestFederalIncumbencyDerivation:
    """Derived incumbency comes from canonical officeholding, not a second flag."""

    def test_current_officeholder_derives_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders
        from domains.civics.ingest import derive_incumbent_challenge

        ds = _make_data_source(db_conn)
        rows = [_make_house_member_row(bioguide_id="INC-1", sworn_date="2023-01-03")]
        load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)

        # Look up the person
        person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "INC-1"}',),
        ).fetchone()
        assert person is not None

        # Current officeholder should derive "I" for the same office
        result = derive_incumbent_challenge(db_conn, person[0], OFFICE_US_HOUSE, as_of=date(2024, 6, 1))
        assert result == "I"

    def test_former_officeholder_not_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders
        from domains.civics.ingest import derive_incumbent_challenge

        ds = _make_data_source(db_conn)
        # Sworn in 2021 → term ends 2023-01-03 → checking as_of 2024 should NOT be incumbent
        rows = [_make_house_member_row(bioguide_id="INC-2", sworn_date="2021-01-03")]
        load_federal_house_officeholders(db_conn, rows, data_source_id=ds.id)

        person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"bioguide_id": "INC-2"}',),
        ).fetchone()
        assert person is not None

        result = derive_incumbent_challenge(db_conn, person[0], OFFICE_US_HOUSE, as_of=date(2024, 6, 1))
        assert result is None

    def test_no_officeholding_returns_none(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import derive_incumbent_challenge

        # Random person_id with no officeholding
        result = derive_incumbent_challenge(db_conn, uuid4(), OFFICE_US_HOUSE, as_of=date(2024, 6, 1))
        assert result is None

    def test_source_incumbent_challenge_not_overwritten(self, db_conn: psycopg.Connection) -> None:
        """FEC raw incumbent_challenge should remain authoritative — no second flag."""
        # Verify the candidacy table has incumbent_challenge but no derived_incumbent column
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'civic' AND table_name = 'candidacy' "
            "ORDER BY ordinal_position",
        ).fetchall()
        col_names = [c[0] for c in cols]
        assert "incumbent_challenge" in col_names
        # No second derived incumbent flag
        assert "is_incumbent" not in col_names
        assert "derived_incumbent" not in col_names
