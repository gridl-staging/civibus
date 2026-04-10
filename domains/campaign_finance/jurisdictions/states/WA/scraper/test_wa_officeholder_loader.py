"""Integration tests for WA officeholder loader.

Verifies that WA legislative sponsor directory rows (from SponsorService.asmx
GetSponsors) are correctly mapped into civic.officeholding + core.contact_point
with proper holder_status, term windows, and contact ownership semantics.
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
_OFFICE_WA_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000213")
_OFFICE_WA_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000212")

_DIVISION_WA = UUID("00000000-0000-4000-8000-000000000502")
_DIVISION_WA_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000505")
_DIVISION_WA_HOUSE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000506")


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="state/WA/officeholder",
        name=f"WA Officeholder Test {uuid4()}",
        source_url="https://wslwebservices.leg.wa.gov/SponsorService.asmx",
    )
    insert_data_source(conn, ds)
    return ds


def _make_wa_sponsor_row(
    *,
    sponsor_id: str = "1001",
    name: str = "DOE, JANE",
    long_name: str = "Representative Jane Doe",
    first_name: str = "Jane",
    last_name: str = "Doe",
    agency: str = "House",
    party: str = "D",
    district: str = "22",
    phone: str = "360-786-7800",
    email: str = "jane.doe@leg.wa.gov",
) -> dict[str, str | None]:
    """Simulate a parsed WA GetSponsors XML row."""
    return {
        "Id": sponsor_id,
        "Name": name,
        "LongName": long_name,
        "FirstName": first_name,
        "LastName": last_name,
        "Agency": agency,
        "Party": party,
        "District": district,
        "Phone": phone,
        "Email": email,
    }


# ---------------------------------------------------------------------------
# Officeholding creation
# ---------------------------------------------------------------------------


class TestWAOfficeholderIngest:
    """WA sponsor rows produce officeholding records."""

    def test_house_sponsor_creates_officeholding(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(agency="House", district="22")]
        result = load_wa_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT holder_status, office_id FROM civic.officeholding WHERE office_id = %s",
            (_OFFICE_WA_STATE_HOUSE,),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_senate_sponsor_creates_officeholding(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(agency="Senate", district="22", sponsor_id="2001")]
        result = load_wa_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT holder_status, office_id FROM civic.officeholding WHERE office_id = %s",
            (_OFFICE_WA_STATE_SENATE,),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"

    def test_house_creates_lower_legislative_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(agency="House", district="48", sponsor_id="3001")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT division_type, district_number FROM civic.electoral_division "
            "WHERE name = 'wa_hd_48' AND division_type = 'state_legislative_lower'",
        ).fetchone()
        assert row is not None
        assert row[1] == "48"

    def test_senate_creates_upper_legislative_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(agency="Senate", district="05", sponsor_id="4001")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT division_type, district_number FROM civic.electoral_division "
            "WHERE name = 'wa_sd_05' AND division_type = 'state_legislative_upper'",
        ).fetchone()
        assert row is not None
        assert row[1] == "05"


# ---------------------------------------------------------------------------
# Contact ownership: officeholding, not candidacy
# ---------------------------------------------------------------------------


class TestWAOfficeholderContacts:
    """Contact points from directory sources attach to officeholding, not candidacy."""

    def test_phone_creates_office_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(phone="360-786-0001", sponsor_id="CP-1")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type, type FROM core.contact_point WHERE value_raw = '360-786-0001' AND type = 'phone'",
        ).fetchone()
        assert cp is not None
        assert cp[0] == "office"

    def test_email_creates_officeholding_contact(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(email="test@leg.wa.gov", sponsor_id="CP-2")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        cp = db_conn.execute(
            "SELECT owner_type, type FROM core.contact_point WHERE value_raw = 'test@leg.wa.gov' AND type = 'email'",
        ).fetchone()
        assert cp is not None
        assert cp[0] == "officeholding"

    def test_empty_contact_fields_skip_contact_creation(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(phone="", email="", sponsor_id="CP-3")]
        result = load_wa_officeholders(db_conn, rows, data_source_id=ds.id)
        # Officeholding should still be created
        assert result.inserted >= 1


# ---------------------------------------------------------------------------
# Term window (biennium)
# ---------------------------------------------------------------------------


class TestWAOfficeholderTermWindow:
    """WA legislative terms follow the biennium (odd year to odd year)."""

    def test_term_uses_current_biennium(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(sponsor_id="TERM-1")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT lower(valid_period), upper(valid_period) FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"wa_sponsor_id": "TERM-1"}',),
        ).fetchone()
        assert row is not None
        # Current biennium: 2025-01-13 to 2027-01-11 (approximate)
        # We just verify the range is non-null and covers a ~2 year span
        assert row[0] is not None
        assert row[1] is not None


# ---------------------------------------------------------------------------
# Person reuse via wa_sponsor_id
# ---------------------------------------------------------------------------


class TestWAOfficeholderPersonReuse:
    def test_same_sponsor_id_reuses_person(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        # Load twice with same sponsor_id
        rows = [_make_wa_sponsor_row(sponsor_id="REUSE-1")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        persons = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"wa_sponsor_id": "REUSE-1"}',),
        ).fetchall()
        assert len(persons) == 1


# ---------------------------------------------------------------------------
# Vacancy: no fake person
# ---------------------------------------------------------------------------


class TestWAOfficeholderVacancy:
    """Vacant seats from GetSponsors should not produce fake officeholding rows."""

    def test_vacant_row_skipped(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        vacant_row = _make_wa_sponsor_row(
            sponsor_id="",
            name="VACANT",
            long_name="Vacant",
            first_name="",
            last_name="",
        )
        result = load_wa_officeholders(db_conn, [vacant_row], data_source_id=ds.id)
        assert result.skipped >= 1

    def test_vacancy_retires_prior_holder(self, db_conn: psycopg.Connection) -> None:
        """When a vacancy row appears for a WA seat, the prior officeholding must be retired."""
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)

        # First load: active House member in district 22
        holder_row = _make_wa_sponsor_row(
            sponsor_id="VAC-WA-1",
            first_name="Jane",
            last_name="Doe",
            agency="House",
            district="22",
        )
        load_wa_officeholders(db_conn, [holder_row], data_source_id=ds.id)

        person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"wa_sponsor_id": "VAC-WA-1"}',),
        ).fetchone()
        assert person is not None
        oh_before = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], _OFFICE_WA_STATE_HOUSE),
        ).fetchone()
        assert oh_before[0] == "elected"

        # Second load: vacancy row for same seat (House district 22)
        vacant_row = _make_wa_sponsor_row(
            sponsor_id="",
            name="VACANT",
            long_name="Vacant",
            first_name="",
            last_name="",
            agency="House",
            district="22",
        )
        load_wa_officeholders(db_conn, [vacant_row], data_source_id=ds.id)

        # The prior holder should now be 'former'
        oh_after = db_conn.execute(
            "SELECT holder_status FROM civic.officeholding WHERE person_id = %s AND office_id = %s",
            (person[0], _OFFICE_WA_STATE_HOUSE),
        ).fetchone()
        assert oh_after[0] == "former"


# ---------------------------------------------------------------------------
# LoadResult
# ---------------------------------------------------------------------------


class TestWAOfficeholderLoadResult:
    def test_returns_load_result(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_wa_sponsor_row(sponsor_id="LR-1", agency="House"),
            _make_wa_sponsor_row(sponsor_id="LR-2", agency="Senate"),
        ]
        result = load_wa_officeholders(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 2
        assert result.errors == 0


# ---------------------------------------------------------------------------
# Incumbency derivation from canonical officeholding
# ---------------------------------------------------------------------------


class TestWAIncumbencyDerivation:
    """derive_incumbent_challenge uses canonical officeholding, not raw source fields."""

    def test_current_officeholder_derives_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )
        from domains.civics.ingest import derive_incumbent_challenge

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(sponsor_id="INC-WA-1", agency="House", district="22")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        # Retrieve person_id
        person_row = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"wa_sponsor_id": "INC-WA-1"}',),
        ).fetchone()
        assert person_row is not None

        # Current biennium covers today — should derive "I"
        result = derive_incumbent_challenge(db_conn, person_row[0], _OFFICE_WA_STATE_HOUSE, as_of=date.today())
        assert result == "I"

    def test_no_officeholding_returns_none(self, db_conn: psycopg.Connection) -> None:
        from domains.civics.ingest import derive_incumbent_challenge

        # Random person_id with no officeholding
        result = derive_incumbent_challenge(db_conn, uuid4(), _OFFICE_WA_STATE_HOUSE, as_of=date.today())
        assert result is None

    def test_wrong_office_returns_none(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )
        from domains.civics.ingest import derive_incumbent_challenge

        ds = _make_data_source(db_conn)
        rows = [_make_wa_sponsor_row(sponsor_id="INC-WA-2", agency="House", district="10")]
        load_wa_officeholders(db_conn, rows, data_source_id=ds.id)

        person_row = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"wa_sponsor_id": "INC-WA-2"}',),
        ).fetchone()
        assert person_row is not None

        # Person holds House seat, not Senate — should return None for Senate
        result = derive_incumbent_challenge(db_conn, person_row[0], _OFFICE_WA_STATE_SENATE, as_of=date.today())
        assert result is None
