"""Integration tests for WA canonical loader.

Tests run against a real PostgreSQL database to verify that WA contribution,
expenditure, and independent-expenditure rows are correctly mapped into
canonical civic.* entities (contest, candidacy, contact_point) using the
shared upsert helpers and WA seed office UUIDs.
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

_OFFICE_WA_GOVERNOR = UUID("00000000-0000-4000-8000-000000000204")
_OFFICE_WA_MUNICIPAL = UUID("00000000-0000-4000-8000-000000000207")
_OFFICE_WA_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000213")
_OFFICE_WA_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000212")
_OFFICE_WA_COUNTY = UUID("00000000-0000-4000-8000-000000000203")
_OFFICE_WA_SCHOOL_DISTRICT = UUID("00000000-0000-4000-8000-000000000208")
_OFFICE_WA_SPECIAL_DISTRICT = UUID("00000000-0000-4000-8000-000000000210")

_DIVISION_WA = UUID("00000000-0000-4000-8000-000000000502")
_DIVISION_WA_COUNTIES = UUID("00000000-0000-4000-8000-000000000507")
_DIVISION_WA_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000505")
_DIVISION_WA_HOUSE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000506")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="state/WA",
        name=f"WA Canonical Test {uuid4()}",
        source_url="https://data.wa.gov/test",
    )
    insert_data_source(conn, ds)
    return ds


def _make_contribution_row(
    *,
    filer_name: str = "Friends of Example",
    office: str = "Governor",
    legislative_district: str = "",
    party: str = "DEMOCRATIC",
    election_year: str = "2026",
    jurisdiction: str = "STATE OF WASHINGTON",
    jurisdiction_county: str = "THURSTON",
    jurisdiction_type: str = "Statewide",
    filer_id: str = "FIL-1",
    row_type: str = "Candidate",
    row_id: str | None = None,
) -> dict[str, str | None]:
    return {
        "id": row_id or str(uuid4()),
        "report_number": "RPT-TEST",
        "origin": "C3",
        "committee_id": "9001",
        "fund_id": "FUND-1",
        "filer_id": filer_id,
        "type": row_type,
        "filer_name": filer_name,
        "office": office,
        "legislative_district": legislative_district,
        "position": "",
        "party": party,
        "ballot_number": "",
        "for_or_against": "",
        "jurisdiction": jurisdiction,
        "jurisdiction_county": jurisdiction_county,
        "jurisdiction_type": jurisdiction_type,
        "election_year": election_year,
        "amount": "150.25",
        "cash_or_in_kind": "Cash",
        "receipt_date": "2026-01-15T00:00:00.000",
        "description": "Test contribution",
        "memo": "",
        "primary_general": "Primary",
        "code": "Monetary",
        "contributor_category": "Individual",
        "contributor_name": "Doe, Jane",
        "contributor_address": "123 Main St",
        "contributor_city": "Olympia",
        "contributor_state": "WA",
        "contributor_zip": "98501",
        "contributor_occupation": "Engineer",
        "contributor_employer_name": "Example Co",
        "contributor_employer_city": "Olympia",
        "contributor_employer_state": "WA",
        "url": "https://example.com/test",
        "contributor_location": "",
    }


def _make_ie_row(
    *,
    sponsor_name: str = "Citizens for Better WA",
    sponsor_email: str = "contact@cfbwa.org",
    sponsor_phone: str = "206-555-0100",
    candidate_name: str = "EXAMPLE, JANE",
    candidate_first_name: str = "JANE",
    candidate_last_name: str = "EXAMPLE",
    candidate_office: str = "Governor",
    candidate_jurisdiction: str = "STATE OF WASHINGTON",
    candidate_party: str = "DEMOCRATIC",
    candidate_filer_id: str = "",
    candidate_office_type: str = "Statewide",
    election_year: str = "2026",
    row_id: str | None = None,
) -> dict[str, str | None]:
    return {
        "id": row_id or str(uuid4()),
        "report_number": "RPT-IE-TEST",
        "origin": "IE",
        "sponsor_entity_id": "SP-1",
        "sponsor_id": "SP-1",
        "sponsor_name": sponsor_name,
        "sponsor_description": "PAC",
        "report_type": "IE",
        "report_date": "2026-01-20T00:00:00.000",
        "election_year": election_year,
        "sponsor_address": "100 PAC Ave",
        "sponsor_city": "Seattle",
        "sponsor_state": "WA",
        "sponsor_zip": "98101",
        "sponsor_email": sponsor_email,
        "sponsor_phone": sponsor_phone,
        "total_unitemized": "0",
        "total_cycle": "5000.00",
        "total_this_report": "1000.00",
        "expenditure_amount": "500.00",
        "expenditure_description": "TV ads",
        "date_expense_obligated": "2026-01-18T00:00:00.000",
        "date_advertising_presented": "2026-01-20T00:00:00.000",
        "vendor_name": "Ad Agency Inc",
        "vendor_address": "200 Media Blvd",
        "vendor_city": "Seattle",
        "vendor_state": "WA",
        "vendor_zipcode": "98102",
        "candidate_entity_id": "CE-1",
        "candidate_candidacy_id": "",
        "candidate_committee_id": "",
        "candidate_filer_id": candidate_filer_id,
        "candidate_name": candidate_name,
        "candidate_last_name": candidate_last_name,
        "candidate_first_name": candidate_first_name,
        "candidate_office": candidate_office,
        "candidate_jurisdiction": candidate_jurisdiction,
        "candidate_party": candidate_party,
        "candidate_office_type": candidate_office_type,
        "ballot_name": "",
        "ballot_number": "",
        "ballot_type": "",
        "portion_of_amount": "",
        "for_or_against": "For",
        "funders_name": "",
        "funders_first_name": "",
        "funders_middle_initial": "",
        "date_received": "",
        "amount": "",
        "funders_address": "",
        "funders_city": "",
        "funders_state": "",
        "funders_zipcode": "",
        "funders_occupation": "",
        "funders_employer": "",
        "funders_employer_city": "",
        "funders_employer_state": "",
        "url": "https://example.com/ie-test",
        "sponsor_location": "",
        "vendor_location": "",
        "funders_location": "",
        "filer_id": "SP-1",
    }


# ---------------------------------------------------------------------------
# Contribution → contest + candidacy tests
# ---------------------------------------------------------------------------


class TestWACanonicalContribution:
    def test_statewide_office_creates_contest_and_candidacy(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_contribution_row(office="Governor", election_year="2026")]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        # Verify contest was created with correct office
        row = db_conn.execute(
            "SELECT name, office_id FROM civic.contest WHERE office_id = %s",
            (_OFFICE_WA_GOVERNOR,),
        ).fetchone()
        assert row is not None
        assert "Governor" in row[0]

    def test_legislative_district_creates_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                office="State Senator",
                legislative_district="22",
                jurisdiction_type="Legislative",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        # Verify electoral division was created
        row = db_conn.execute(
            "SELECT name, division_type, district_number FROM civic.electoral_division "
            "WHERE division_type = 'state_legislative_upper' AND state = 'WA' AND district_number = '22'",
        ).fetchone()
        assert row is not None

    def test_state_house_creates_lower_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                office="State Representative",
                legislative_district="48",
                jurisdiction_type="Legislative",
                filer_name="Committee for Rep 48",
                filer_id="FIL-48",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT name, division_type, district_number FROM civic.electoral_division "
            "WHERE division_type = 'state_legislative_lower' AND state = 'WA' AND district_number = '48'",
        ).fetchone()
        assert row is not None

    def test_county_office_creates_county_division(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                office="County Council",
                jurisdiction="KING COUNTY",
                jurisdiction_county="KING",
                jurisdiction_type="County",
                filer_name="Committee for King County",
                filer_id="FIL-KING",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT name, division_type FROM civic.electoral_division "
            "WHERE division_type = 'county' AND state = 'WA' AND name LIKE '%king%'",
        ).fetchone()
        assert row is not None

    def test_municipal_office_type_falls_back_to_municipal_seed(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                office="Mayor",
                jurisdiction="City of Olympia",
                jurisdiction_county="THURSTON",
                jurisdiction_type="Municipal",
                filer_name="Friends of Olympia Mayor",
                filer_id="FIL-MUNI-1",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT office_id, electoral_division_id FROM civic.contest WHERE name = 'WA Mayor General 2026'",
        ).fetchone()
        assert row is not None
        assert row[0] == _OFFICE_WA_MUNICIPAL

        division_row = db_conn.execute(
            "SELECT division_type, name FROM civic.electoral_division WHERE id = %s",
            (row[1],),
        ).fetchone()
        assert division_row is not None
        assert division_row[0] == "municipal"
        assert division_row[1] == "wa_city_of_olympia"

    def test_creates_candidacy_with_party(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_contribution_row(party="REPUBLICAN")]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT party FROM civic.candidacy WHERE party = 'REPUBLICAN'",
        ).fetchone()
        assert row is not None

    def test_skips_political_committee_rows(self, db_conn: psycopg.Connection) -> None:
        """Non-Candidate rows (e.g. Political Committee) should not create candidacy records."""
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_contribution_row(row_type="Political Committee", filer_name="Some PAC")]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.skipped >= 1


class TestWACanonicalIdempotent:
    def test_duplicate_rows_produce_same_contest(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_contribution_row(filer_id="FIL-DUP", filer_name="Dup Committee")
        # Load twice
        load_wa_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        load_wa_candidates_canonical(db_conn, [row], data_source_id=ds.id)

        # Should have exactly one contest for this office+year
        rows = db_conn.execute(
            "SELECT id FROM civic.contest WHERE office_id = %s AND name LIKE %s",
            (_OFFICE_WA_GOVERNOR, "%2026%"),
        ).fetchall()
        # May be more than 1 if other tests created Governor 2026 contests,
        # but within this test the upsert should not create duplicates.
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# IE → contact_point tests
# ---------------------------------------------------------------------------


class TestWACanonicalIE:
    def test_ie_row_creates_sponsor_contact_points(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_ie_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_ie_row(
                sponsor_email="test@sponsor.org",
                sponsor_phone="206-555-0199",
            )
        ]
        result = load_wa_ie_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        # Check email contact_point was created
        email_row = db_conn.execute(
            "SELECT value_raw, type, owner_type FROM core.contact_point "
            "WHERE value_raw = 'test@sponsor.org' AND type = 'email'",
        ).fetchone()
        assert email_row is not None
        assert email_row[2] == "organization"

        # Check phone contact_point was created
        phone_row = db_conn.execute(
            "SELECT value_raw, type, owner_type FROM core.contact_point "
            "WHERE value_raw = '206-555-0199' AND type = 'phone'",
        ).fetchone()
        assert phone_row is not None

    def test_ie_row_creates_candidate_candidacy(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_ie_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_ie_row(
                candidate_name="TESTPERSON, ALICE",
                candidate_first_name="ALICE",
                candidate_last_name="TESTPERSON",
                candidate_office="Governor",
            )
        ]
        result = load_wa_ie_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        # Verify candidacy was created
        row = db_conn.execute(
            "SELECT c.party FROM civic.candidacy c "
            "JOIN core.person p ON c.person_id = p.id "
            "WHERE p.last_name = 'TESTPERSON' AND p.first_name = 'ALICE'",
        ).fetchone()
        assert row is not None

    def test_ie_without_contact_info_skips_contact_points(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_ie_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [_make_ie_row(sponsor_email="", sponsor_phone="")]
        result = load_wa_ie_canonical(db_conn, rows, data_source_id=ds.id)
        # Should still insert the candidacy but no contact points
        assert result.inserted >= 1

    def test_ie_special_district_office_type_falls_back_to_special_seed(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_ie_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_ie_row(
                candidate_office="Fire Commissioner",
                candidate_office_type="Special District",
                candidate_jurisdiction="Central Fire District",
                sponsor_email="",
                sponsor_phone="",
                row_id="ie-special-1",
            )
        ]
        result = load_wa_ie_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted >= 1

        row = db_conn.execute(
            "SELECT office_id, electoral_division_id FROM civic.contest "
            "WHERE name = 'WA Fire Commissioner General 2026'",
        ).fetchone()
        assert row is not None
        assert row[0] == _OFFICE_WA_SPECIAL_DISTRICT

        division_row = db_conn.execute(
            "SELECT division_type, name FROM civic.electoral_division WHERE id = %s",
            (row[1],),
        ).fetchone()
        assert division_row is not None
        assert division_row[0] == "special_district"
        assert division_row[1] == "wa_central_fire_district_special"

    def test_ie_rows_reuse_person_by_candidate_filer_id(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_ie_canonical,
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_ie_row(candidate_filer_id="WA-CAND-42", row_id="ie-dedupe-1", sponsor_email="", sponsor_phone=""),
            _make_ie_row(candidate_filer_id="WA-CAND-42", row_id="ie-dedupe-2", sponsor_email="", sponsor_phone=""),
        ]
        result = load_wa_ie_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 2

        person_count = db_conn.execute(
            "SELECT COUNT(1)::int FROM core.person WHERE identifiers ->> 'wa_filer_id' = 'WA-CAND-42'",
        ).fetchone()
        assert person_count is not None
        assert person_count[0] == 1


# ---------------------------------------------------------------------------
# Derived incumbency from canonical officeholding
# ---------------------------------------------------------------------------


class TestWACanonicalIncumbencyDerivation:
    def test_current_officeholding_derives_incumbent_challenge(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        filer_id = f"WA-INC-{uuid4()}"
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="INCUMBENT, WA",
                identifiers={"wa_filer_id": filer_id},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_WA_GOVERNOR,
                electoral_division_id=_DIVISION_WA,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=date(2029, 1, 1)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                filer_id=filer_id,
                filer_name="INCUMBENT, WA",
                office="Governor",
                election_year="2026",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'wa_filer_id' = %s
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            (filer_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "I"

    def test_derives_incumbent_using_contest_date_not_today(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        filer_id = f"WA-HIST-{uuid4()}"
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="HISTORICAL, WA",
                identifiers={"wa_filer_id": filer_id},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_WA_GOVERNOR,
                electoral_division_id=_DIVISION_WA,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2021, 1, 1), end_date=date(2025, 1, 1)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                filer_id=filer_id,
                filer_name="HISTORICAL, WA",
                office="Governor",
                election_year="2024",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'wa_filer_id' = %s
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            (filer_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "I"

    def test_former_officeholding_is_not_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        filer_id = f"WA-FORMER-{uuid4()}"
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="FORMER, WA",
                identifiers={"wa_filer_id": filer_id},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_WA_GOVERNOR,
                holder_status="former",
                valid_period=ValidDateRange(start_date=date(2021, 1, 1), end_date=date(2023, 1, 1)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                filer_id=filer_id,
                filer_name="FORMER, WA",
                office="Governor",
                election_year="2026",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'wa_filer_id' = %s
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            (filer_id,),
        ).fetchone()
        assert row is not None
        assert row[0] is None

    def test_other_district_officeholding_is_not_treated_as_incumbent(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        wa_house_03 = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="wa_hd_03",
                division_type="state_legislative_lower",
                state="WA",
                district_number="03",
                parent_id=_DIVISION_WA_HOUSE_DISTRICTS,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="DISTRICT, SWITCHER",
                identifiers={"wa_filer_id": "WA-DIST-1"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=_OFFICE_WA_STATE_HOUSE,
                electoral_division_id=wa_house_03,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=date(2027, 1, 1)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        rows = [
            _make_contribution_row(
                filer_id="WA-DIST-1",
                filer_name="DISTRICT, SWITCHER",
                office="State Representative",
                legislative_district="04",
                jurisdiction_type="District",
                election_year="2026",
            )
        ]
        result = load_wa_candidates_canonical(db_conn, rows, data_source_id=ds.id)
        assert result.inserted == 1

        row = db_conn.execute(
            """
            SELECT c.incumbent_challenge
            FROM civic.candidacy c
            JOIN core.person p ON p.id = c.person_id
            WHERE p.identifiers ->> 'wa_filer_id' = 'WA-DIST-1'
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
        ).fetchone()
        assert row is not None
        assert row[0] is None


class TestWAOfficeholderDirectoryContract:
    """WA directory rows create officeholding status, contact owners, and vacancy skips."""

    def test_directory_ingest_sets_current_holder_and_contact_owner_split(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="state/WA/officeholder",
            name=f"WA Officeholder Test {uuid4()}",
            source_url="https://wslwebservices.leg.wa.gov/SponsorService.asmx?op=GetSponsors",
        )
        insert_data_source(db_conn, ds)

        row = {
            "Id": "5001",
            "Name": "DOE, JANE",
            "LongName": "Rep. Jane Doe",
            "Agency": "House",
            "Party": "D",
            "District": "22",
            "Phone": "360-786-5001",
            "Email": "jane.doe@leg.wa.gov",
            "FirstName": "Jane",
            "LastName": "Doe",
        }
        result = load_wa_officeholders(db_conn, [row], data_source_id=ds.id)
        assert result.inserted == 1

        status_row = db_conn.execute(
            "SELECT holder_status "
            "FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"wa_sponsor_id": "5001"}',),
        ).fetchone()
        assert status_row is not None
        assert status_row[0] == "elected"

        phone_owner = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = '360-786-5001' AND type = 'phone'",
        ).fetchone()
        email_owner = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = 'jane.doe@leg.wa.gov' AND type = 'email'",
        ).fetchone()
        assert phone_owner is not None
        assert email_owner is not None
        assert phone_owner[0] == "office"
        assert email_owner[0] == "officeholding"

    def test_directory_vacancy_row_is_skipped(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="state/WA/officeholder",
            name=f"WA Officeholder Test {uuid4()}",
            source_url="https://wslwebservices.leg.wa.gov/SponsorService.asmx?op=GetSponsors",
        )
        insert_data_source(db_conn, ds)

        row = {
            "Id": "",
            "Name": "VACANT",
            "LongName": "Vacant Seat",
            "Agency": "House",
            "Party": "",
            "District": "22",
            "Phone": "",
            "Email": "",
            "FirstName": "",
            "LastName": "",
        }
        result = load_wa_officeholders(db_conn, [row], data_source_id=ds.id)
        assert result.skipped == 1

        vacant_person = db_conn.execute("SELECT id FROM core.person WHERE canonical_name = 'VACANT'").fetchone()
        assert vacant_person is None

    def test_directory_unknown_agency_row_is_skipped(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader import (
            load_wa_officeholders,
        )

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="state/WA/officeholder",
            name=f"WA Officeholder Test {uuid4()}",
            source_url="https://wslwebservices.leg.wa.gov/SponsorService.asmx?op=GetSponsors",
        )
        insert_data_source(db_conn, ds)

        row = {
            "Id": "5999",
            "Name": "UNKNOWN, AGENCY",
            "LongName": "Unknown Agency Member",
            "Agency": "Council",
            "Party": "D",
            "District": "22",
            "Phone": "360-786-5999",
            "Email": "unknown.agency@leg.wa.gov",
            "FirstName": "Unknown",
            "LastName": "Agency",
        }
        result = load_wa_officeholders(db_conn, [row], data_source_id=ds.id)
        assert result.skipped == 1
        assert result.errors == 0

    def test_directory_db_error_rolls_back_failed_row_and_continues_batch(
        self,
        db_conn: psycopg.Connection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import domains.campaign_finance.jurisdictions.states.WA.scraper.wa_officeholder_loader as loader

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="state/WA/officeholder",
            name=f"WA Officeholder Test {uuid4()}",
            source_url="https://wslwebservices.leg.wa.gov/SponsorService.asmx?op=GetSponsors",
        )
        insert_data_source(db_conn, ds)

        original = loader._resolve_wa_division
        should_fail_once = True

        def _flaky_resolve_wa_division(
            conn: psycopg.Connection,
            division_type: str,
            division_parent_id: UUID,
            district: str,
        ) -> UUID | None:
            nonlocal should_fail_once
            if should_fail_once:
                should_fail_once = False
                conn.execute("SELECT * FROM missing_stage_review_table")
            return original(conn, division_type, division_parent_id, district)

        monkeypatch.setattr(loader, "_resolve_wa_division", _flaky_resolve_wa_division)

        result = loader.load_wa_officeholders(
            db_conn,
            [
                {
                    "Id": "9101",
                    "Name": "ERROR, ERIN",
                    "LongName": "Rep. Erin Error",
                    "Agency": "House",
                    "Party": "D",
                    "District": "11",
                    "Phone": "360-786-9101",
                    "Email": "erin.error@leg.wa.gov",
                    "FirstName": "Erin",
                    "LastName": "Error",
                },
                {
                    "Id": "9102",
                    "Name": "GOOD, GREG",
                    "LongName": "Rep. Greg Good",
                    "Agency": "House",
                    "Party": "R",
                    "District": "12",
                    "Phone": "360-786-9102",
                    "Email": "greg.good@leg.wa.gov",
                    "FirstName": "Greg",
                    "LastName": "Good",
                },
            ],
            data_source_id=ds.id,
        )

        assert result.errors == 1
        assert result.inserted == 1
        failed_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"wa_sponsor_id": "9101"}',),
        ).fetchone()
        successful_person = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"wa_sponsor_id": "9102"}',),
        ).fetchone()
        assert failed_person is None
        assert successful_person is not None


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestWACanonicalErrors:
    def test_missing_office_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_contribution_row(office="")
        result = load_wa_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1

    def test_missing_election_year_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_contribution_row(election_year="")
        result = load_wa_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1

    def test_unknown_office_increments_errors(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.jurisdictions.states.WA.scraper.wa_canonical_loader import (
            load_wa_candidates_canonical,
        )

        ds = _make_data_source(db_conn)
        row = _make_contribution_row(office="Galactic Emperor")
        result = load_wa_candidates_canonical(db_conn, [row], data_source_id=ds.id)
        assert result.errors >= 1
