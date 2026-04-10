"""Integration tests for FL officeholder loader.

Verifies that FL Senate directory rows (from flsenate.gov/Senators/) are
correctly mapped into civic.officeholding + core.contact_point with proper
holder_status, term windows, and contact ownership semantics.

Note: FL House is ENV-BLOCKED (flhouse.gov returns Request Rejected). Only
FL Senate is covered in this loader.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source
from core.types.python.models import DataSource


pytestmark = pytest.mark.integration

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
_OFFICE_FL_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000311")
_OFFICE_FL_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000310")

_DIVISION_FL = UUID("00000000-0000-4000-8000-000000000503")
_DIVISION_FL_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000511")


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="state/FL/officeholder",
        name=f"FL Officeholder Test {uuid4()}",
        source_url="https://www.flsenate.gov/Senators/",
    )
    insert_data_source(conn, ds)
    return ds


def _make_fl_senator_row(
    *,
    senator_id: str = "S27",
    name: str = "DOE, JANE",
    first_name: str = "Jane",
    last_name: str = "Doe",
    party: str = "R",
    district: str = "27",
    term_start: str = "2024",
    term_end: str = "2026",
    status: str = "active",
    district_address: str = "100 Local Ave, Miami FL 33101",
    district_phone: str = "305-555-0100",
    tallahassee_address: str = "404 S. Monroe St, Tallahassee FL 32399",
    tallahassee_phone: str = "850-487-5027",
) -> dict[str, str | None]:
    """Simulate a parsed FL Senate directory row."""
    return {
        "senator_id": senator_id,
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "party": party,
        "district": district,
        "term_start": term_start,
        "term_end": term_end,
        "status": status,
        "district_address": district_address,
        "district_phone": district_phone,
        "tallahassee_address": tallahassee_address,
        "tallahassee_phone": tallahassee_phone,
    }


# ---------------------------------------------------------------------------
# Officeholding creation
# ---------------------------------------------------------------------------


class TestFLSenateOfficeholderIngest:
    """FL Senate directory rows produce officeholding records."""

    def test_senator_creates_officeholding(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row()]
        result = load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT oh.holder_status, oh.office_id FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE oh.office_id = %s AND p.identifiers @> %s",
            (_OFFICE_FL_STATE_SENATE, '{"fl_senator_id": "S27"}'),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_senator_creates_upper_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(district="14", senator_id="S14")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT division_type, district_number FROM civic.electoral_division "
            "WHERE name = 'fl_sd_14' AND division_type = 'state_legislative_upper'",
        ).fetchone()
        assert row is not None
        assert row[1] == "14"

    def test_senator_term_window(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(term_start="2024", term_end="2026", senator_id="TERM-1")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT lower(valid_period), upper(valid_period) FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"fl_senator_id": "TERM-1"}',),
        ).fetchone()
        assert row is not None
        # FL senate terms typically start in November of start year
        assert row[0] is not None
        assert row[1] is not None


# ---------------------------------------------------------------------------
# Contact ownership: officeholding, not candidacy
# ---------------------------------------------------------------------------


class TestFLSenateOfficeholderContacts:
    """Directory contacts attach to officeholding with appropriate roles."""

    def test_district_phone_creates_office_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(district_phone="305-555-9999", senator_id="CP-DIST")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type, role FROM core.contact_point WHERE value_raw = '305-555-9999' AND type = 'phone'",
        ).fetchone()
        assert cp is not None
        assert cp[0] == "office"
        assert cp[1] == "district"

    def test_tallahassee_phone_creates_office_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(tallahassee_phone="850-487-9999", senator_id="CP-TLH")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type, role FROM core.contact_point WHERE value_raw = '850-487-9999' AND type = 'phone'",
        ).fetchone()
        assert cp is not None
        assert cp[0] == "office"
        assert cp[1] == "capitol"

    def test_empty_phones_skip_contact_creation(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(district_phone="", tallahassee_phone="", senator_id="CP-NONE")]
        result = load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1


# ---------------------------------------------------------------------------
# Holder status: resigned/died senators
# ---------------------------------------------------------------------------


class TestFLSenateHolderStatus:
    """FL Senate roster marks resigned/died senators — should get 'former' status."""

    def test_resigned_senator_gets_former_status(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(status="resigned", senator_id="STATUS-R")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"fl_senator_id": "STATUS-R"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == "former"

    def test_active_senator_gets_elected_status(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(status="active", senator_id="STATUS-A")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"fl_senator_id": "STATUS-A"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_appointed_senator_gets_appointed_status(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(status="appointed", senator_id="STATUS-AP")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"fl_senator_id": "STATUS-AP"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == "appointed"


# ---------------------------------------------------------------------------
# Vacancy
# ---------------------------------------------------------------------------


class TestFLSenateVacancy:
    """Vacant seats should not produce fake person-backed officeholding rows."""

    def test_vacant_row_skipped(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        vacant_row = _make_fl_senator_row(
            senator_id="",
            name="VACANT",
            first_name="",
            last_name="",
            status="vacant",
        )
        result = load_fl_senate_officeholders(db_conn, [vacant_row], data_source_id=ds.id)
        assert result.skipped >= 1

    def test_vacancy_retires_prior_holder(self, db_conn: psycopg.Connection) -> None:
        """When a vacancy row appears for a FL Senate seat, the prior officeholding must be retired."""
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)

        # First load: active senator in district 27
        holder_row = _make_fl_senator_row(
            senator_id="VAC-FL-1",
            first_name="Jane",
            last_name="Doe",
            district="27",
            status="active",
            term_start="2024",
            term_end="2028",
        )
        load_fl_senate_officeholders(db_conn, [holder_row], data_source_id=ds.id)

        person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fl_senator_id": "VAC-FL-1"}',),
        ).fetchone()
        assert person is not None
        oh_before = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], _OFFICE_FL_STATE_SENATE),
        ).fetchone()
        assert oh_before[0] == "elected"

        # Second load: vacancy row for same district
        vacant_row = _make_fl_senator_row(
            senator_id="",
            name="VACANT",
            first_name="",
            last_name="",
            district="27",
            status="vacant",
        )
        load_fl_senate_officeholders(db_conn, [vacant_row], data_source_id=ds.id)

        # The prior holder should now be 'former'
        oh_after = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], _OFFICE_FL_STATE_SENATE),
        ).fetchone()
        assert oh_after[0] == "former"


# ---------------------------------------------------------------------------
# Person reuse and LoadResult
# ---------------------------------------------------------------------------


class TestFLSenatePersonReuse:
    def test_same_senator_id_reuses_person(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_fl_senator_row(senator_id="REUSE-1")]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        persons = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fl_senator_id": "REUSE-1"}',),
        ).fetchall()
        assert len(persons) == 1


class TestFLSenateLoadResult:
    def test_returns_load_result(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_senator_row(senator_id="LR-1"),
            _make_fl_senator_row(senator_id="LR-2", district="14"),
        ]
        result = load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 2
        assert result.errors == 0

    def test_db_error_rolls_back_failed_row_and_continues_batch(
        self,
        db_conn: psycopg.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader as loader

        ds = _make_data_source(db_conn)
        original = loader._resolve_fl_senate_division
        should_fail_once = True

        def _flaky_resolve_fl_senate_division(conn: psycopg.Connection, district: str) -> UUID | None:
            nonlocal should_fail_once
            if should_fail_once:
                should_fail_once = False
                conn.execute("SELECT * FROM missing_stage_review_table")
            return original(conn, district)

        monkeypatch.setattr(loader, "_resolve_fl_senate_division", _flaky_resolve_fl_senate_division)

        result = loader.load_fl_senate_officeholders(
            db_conn,
            [
                _make_fl_senator_row(senator_id="ERR-FL-1", district="11"),
                _make_fl_senator_row(senator_id="GOOD-FL-2", district="12"),
            ],
            data_source_id=ds.id,
        )

        assert result.errors == 1
        assert result.inserted == 1
        failed_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fl_senator_id": "ERR-FL-1"}',),
        ).fetchone()
        successful_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fl_senator_id": "GOOD-FL-2"}',),
        ).fetchone()
        assert failed_person is None
        assert successful_person is not None


# ---------------------------------------------------------------------------
# Incumbency derivation from canonical officeholding
# ---------------------------------------------------------------------------


class TestFLIncumbencyDerivation:
    """derive_incumbent_challenge uses canonical officeholding, not raw source fields."""

    def test_active_senator_derives_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )
        from domains.civics.ingest import derive_incumbent_challenge

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_senator_row(
                senator_id="INC-FL-1",
                status="active",
                term_start="2024",
                term_end="2028",
            )
        ]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        person_row = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fl_senator_id": "INC-FL-1"}',),
        ).fetchone()
        assert person_row is not None

        # Term 2024-11-01 to 2028-11-01 covers today — should derive "I"
        result = derive_incumbent_challenge(db_conn, person_row[0], _OFFICE_FL_STATE_SENATE, as_of=date(2026, 3, 30))
        assert result == "I"

    def test_former_senator_not_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.FL.scraper.fl_officeholder_loader import (
            load_fl_senate_officeholders,
        )
        from domains.civics.ingest import derive_incumbent_challenge

        ds = _make_data_source(db_conn)
        rows = [
            _make_fl_senator_row(
                senator_id="INC-FL-2",
                status="resigned",
                term_start="2022",
                term_end="2026",
            )
        ]
        load_fl_senate_officeholders(db_conn, rows, data_source_id=ds.id)

        person_row = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fl_senator_id": "INC-FL-2"}',),
        ).fetchone()
        assert person_row is not None

        # Resigned senator has holder_status="former" — should NOT derive "I"
        result = derive_incumbent_challenge(db_conn, person_row[0], _OFFICE_FL_STATE_SENATE, as_of=date(2025, 6, 1))
        assert result is None

    def test_no_officeholding_returns_none(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import derive_incumbent_challenge

        result = derive_incumbent_challenge(db_conn, uuid4(), _OFFICE_FL_STATE_SENATE, as_of=date.today())
        assert result is None
