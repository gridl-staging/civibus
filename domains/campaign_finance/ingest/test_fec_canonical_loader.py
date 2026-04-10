"""Integration tests for FEC canonical loader.

Verifies that FEC candidate-master rows are correctly mapped into canonical
civic.* tables via the shared upsert helpers, including office resolution,
electoral division creation, contest keying by election_date, and person reuse.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_person
from core.types.python.models import DataSource, Person, ValidDateRange
from domains.civics.ingest import upsert_electoral_division, upsert_officeholding
from domains.civics.types.models import ElectoralDivision, Officeholding


pytestmark = pytest.mark.integration

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")
OFFICE_US_PRESIDENT = UUID("00000000-0000-4000-8000-000000000103")
DIVISION_US_STATEWIDE = UUID("00000000-0000-4000-8000-000000000501")
DIVISION_US_CONGRESSIONAL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000504")


def _make_data_source(conn: psycopg.Connection) -> DataSource:
    ds = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=f"FEC Canonical Loader Test {uuid4()}",
        source_url="https://www.fec.gov/data/browse-data/?tab=bulk-data",
    )
    insert_data_source(conn, ds)
    return ds


def _write_cn_file(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a pipe-delimited FEC candidate master file."""
    # CN file columns (from bulk_parser.py CN_COLUMNS):
    # CAND_ID|CAND_NAME|CAND_PTY_AFFILIATION|CAND_ELECTION_YR|CAND_OFFICE_ST|
    # CAND_OFFICE|CAND_OFFICE_DISTRICT|CAND_ICI|CAND_STATUS|CAND_PCC|
    # CAND_ST1|CAND_ST2|CAND_CITY|CAND_ST|CAND_ZIP
    columns = [
        "CAND_ID",
        "CAND_NAME",
        "CAND_PTY_AFFILIATION",
        "CAND_ELECTION_YR",
        "CAND_OFFICE_ST",
        "CAND_OFFICE",
        "CAND_OFFICE_DISTRICT",
        "CAND_ICI",
        "CAND_STATUS",
        "CAND_PCC",
        "CAND_ST1",
        "CAND_ST2",
        "CAND_CITY",
        "CAND_ST",
        "CAND_ZIP",
    ]
    filepath = tmp_path / "cn.txt"
    lines = []
    for row in rows:
        line = "|".join(row.get(col, "") for col in columns)
        lines.append(line)
    filepath.write_text("\n".join(lines) + "\n")
    return filepath


def _house_row(
    cand_id: str = "H4NC01234",
    name: str = "DOE, JANE",
    state: str = "NC",
    district: str = "01",
    year: str = "2024",
    party: str = "DEM",
    ici: str = "C",
) -> dict[str, str]:
    return {
        "CAND_ID": cand_id,
        "CAND_NAME": name,
        "CAND_PTY_AFFILIATION": party,
        "CAND_ELECTION_YR": year,
        "CAND_OFFICE_ST": state,
        "CAND_OFFICE": "H",
        "CAND_OFFICE_DISTRICT": district,
        "CAND_ICI": ici,
        "CAND_STATUS": "C",
        "CAND_PCC": "",
    }


def _senate_row(
    cand_id: str = "S4NC00567",
    name: str = "SMITH, JOHN",
    state: str = "NC",
    year: str = "2024",
    party: str = "REP",
    ici: str = "I",
) -> dict[str, str]:
    return {
        "CAND_ID": cand_id,
        "CAND_NAME": name,
        "CAND_PTY_AFFILIATION": party,
        "CAND_ELECTION_YR": year,
        "CAND_OFFICE_ST": state,
        "CAND_OFFICE": "S",
        "CAND_OFFICE_DISTRICT": "00",
        "CAND_ICI": ici,
        "CAND_STATUS": "C",
        "CAND_PCC": "",
    }


def _president_row(
    cand_id: str = "P40000001",
    name: str = "JONES, BOB",
    year: str = "2024",
    party: str = "DEM",
    ici: str = "C",
) -> dict[str, str]:
    return {
        "CAND_ID": cand_id,
        "CAND_NAME": name,
        "CAND_PTY_AFFILIATION": party,
        "CAND_ELECTION_YR": year,
        "CAND_OFFICE_ST": "US",
        "CAND_OFFICE": "P",
        "CAND_OFFICE_DISTRICT": "00",
        "CAND_ICI": ici,
        "CAND_STATUS": "C",
        "CAND_PCC": "",
    }


class TestFECOfficeResolution:
    """(a) FEC H/S/P codes resolve to seed office UUIDs."""

    def test_house_resolves_to_seed_office(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_house_row()])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute("SELECT office_id FROM civic.contest WHERE office_id = %s", (OFFICE_US_HOUSE,)).fetchone()
        assert row is not None

    def test_senate_resolves_to_seed_office(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_senate_row()])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT office_id FROM civic.contest WHERE office_id = %s", (OFFICE_US_SENATE,)
        ).fetchone()
        assert row is not None

    def test_president_resolves_to_seed_office(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_president_row()])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT office_id FROM civic.contest WHERE office_id = %s", (OFFICE_US_PRESIDENT,)
        ).fetchone()
        assert row is not None


class TestElectoralDivisionResolution:
    """(b) House creates congressional district; Senate creates statewide; President reuses US."""

    def test_house_creates_congressional_district(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_house_row(state="NC", district="01")])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT division_type, state, district_number, parent_id
            FROM civic.electoral_division
            WHERE name = 'nc_cd_01' AND division_type = 'congressional_district'
            """,
        ).fetchone()
        assert row is not None
        assert row[0] == "congressional_district"
        assert row[1] == "NC"
        assert row[2] == "01"
        assert row[3] == DIVISION_US_CONGRESSIONAL_DISTRICTS

    def test_senate_creates_statewide_division(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_senate_row(state="NC")])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT division_type, state, parent_id
            FROM civic.electoral_division
            WHERE name = 'nc' AND division_type = 'statewide'
            """,
        ).fetchone()
        assert row is not None
        assert row[0] == "statewide"
        assert row[1] == "NC"
        assert row[2] == DIVISION_US_STATEWIDE

    def test_president_reuses_us_statewide(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_president_row()])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            "SELECT electoral_division_id FROM civic.contest WHERE office_id = %s",
            (OFFICE_US_PRESIDENT,),
        ).fetchone()
        assert row is not None
        assert row[0] == DIVISION_US_STATEWIDE

    def test_house_reuses_existing_district(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        """Two House candidates in same district should reuse the same division."""
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [
            _house_row(cand_id="H4NC01001", name="ALPHA, ANN", state="NC", district="01"),
            _house_row(cand_id="H4NC01002", name="BRAVO, BOB", state="NC", district="01"),
        ]
        filepath = _write_cn_file(tmp_path, rows)
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        count = db_conn.execute(
            """
            SELECT COUNT(DISTINCT d.id)
            FROM civic.electoral_division d
            JOIN civic.contest c
              ON c.electoral_division_id = d.id
            JOIN core.source_record sr ON sr.id = c.source_record_id
            WHERE d.name = 'nc_cd_01'
              AND d.boundary_year = 2022
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()[0]
        assert count == 1

    def test_house_distinguishes_redistricting_eras_by_boundary_year(
        self, db_conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [
            _house_row(cand_id="H8NC01001", name="ALPHA, ANN", state="NC", district="01", year="2018"),
            _house_row(cand_id="H4NC01001", name="BRAVO, BOB", state="NC", district="01", year="2024"),
        ]
        filepath = _write_cn_file(tmp_path, rows)
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        boundary_years = db_conn.execute(
            """
            SELECT DISTINCT d.boundary_year
            FROM civic.electoral_division d
            JOIN civic.contest c
              ON c.electoral_division_id = d.id
            JOIN core.source_record sr ON sr.id = c.source_record_id
            WHERE d.name = 'nc_cd_01'
              AND d.division_type = 'congressional_district'
              AND d.boundary_year IS NOT NULL
              AND sr.data_source_id = %s
            ORDER BY boundary_year
            """,
            (ds.id,),
        ).fetchall()
        assert [row[0] for row in boundary_years] == [2012, 2022]


class TestContestElectionDateKeying:
    """(c) CAND_ELECTION_YR -> deterministic election_date; 2022 vs 2024 distinct."""

    def test_2024_election_date(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_house_row(year="2024")])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT c.election_date, c.election_type
            FROM civic.contest c
            JOIN core.source_record sr ON sr.id = c.source_record_id
            WHERE c.office_id = %s
              AND c.name = 'H NC General 2024'
              AND sr.data_source_id = %s
            """,
            (OFFICE_US_HOUSE, ds.id),
        ).fetchone()
        assert row is not None
        # First Tuesday after the first Monday in November 2024 = Nov 5, 2024
        assert row[0] == date(2024, 11, 5)
        assert row[1] == "general"

    def test_2022_election_date(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(tmp_path, [_house_row(year="2022")])
        load_fec_candidates_canonical(db_conn, filepath, cycle=2022, data_source_id=ds.id)

        # Filter by contest name to avoid picking up committed data from other tests
        row = db_conn.execute(
            """
            SELECT c.election_date
            FROM civic.contest c
            JOIN core.source_record sr ON sr.id = c.source_record_id
            WHERE c.name = %s
              AND sr.data_source_id = %s
            """,
            ("H NC General 2022", ds.id),
        ).fetchone()
        assert row is not None
        # First Tuesday after the first Monday in November 2022 = Nov 8, 2022
        assert row[0] == date(2022, 11, 8)

    def test_2022_and_2024_create_distinct_contests(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [
            _house_row(cand_id="H4NC01001", year="2022"),
            _house_row(cand_id="H4NC01002", year="2024"),
        ]
        filepath = _write_cn_file(tmp_path, rows)
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        # Filter by contest name pattern to avoid picking up committed data from other tests
        count = db_conn.execute(
            """
            SELECT COUNT(*)
            FROM civic.contest c
            JOIN core.source_record sr ON sr.id = c.source_record_id
            WHERE c.name IN ('H NC General 2022', 'H NC General 2024')
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()[0]
        assert count == 2


class TestPersonReuseAcrossCycles:
    """(d) Same fec_candidate_id across cycles -> same person_id, different candidacies."""

    def test_same_person_two_cycles_two_candidacies(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [
            _house_row(cand_id="H4NC01099", name="DOE, JANE", year="2022"),
            _house_row(cand_id="H4NC01099", name="DOE, JANE", year="2024"),
        ]
        filepath = _write_cn_file(tmp_path, rows)
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        # Should have exactly one person
        person_rows = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fec_candidate_id": "H4NC01099"}',),
        ).fetchall()
        assert len(person_rows) == 1
        person_id = person_rows[0][0]

        # Should have two candidacies, both for the same person
        candidacy_rows = db_conn.execute(
            """
            SELECT ca.contest_id
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.person_id = %s
              AND sr.data_source_id = %s
            ORDER BY ca.contest_id
            """,
            (person_id, ds.id),
        ).fetchall()
        assert len(candidacy_rows) == 2
        # Two distinct contests
        assert candidacy_rows[0][0] != candidacy_rows[1][0]


class TestNonContiguousCycles:
    """(e) Non-contiguous cycles (2018, 2024) produce separate candidacies without false dedup."""

    def test_non_contiguous_cycles(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [
            _house_row(cand_id="H4NC01077", name="ALPHA, ANN", year="2018"),
            _house_row(cand_id="H4NC01077", name="ALPHA, ANN", year="2024"),
        ]
        filepath = _write_cn_file(tmp_path, rows)
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        person_rows = db_conn.execute(
            "SELECT id FROM core.person WHERE identifiers @> %s",
            ('{"fec_candidate_id": "H4NC01077"}',),
        ).fetchall()
        assert len(person_rows) == 1

        candidacies = db_conn.execute(
            """
            SELECT c.election_date
            FROM civic.candidacy ca
            JOIN civic.contest c ON c.id = ca.contest_id
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.person_id = %s
              AND sr.data_source_id = %s
            ORDER BY c.election_date
            """,
            (person_rows[0][0], ds.id),
        ).fetchall()
        assert len(candidacies) == 2
        # First Tuesday after first Monday in Nov 2018 = Nov 6, 2018
        assert candidacies[0][0] == date(2018, 11, 6)
        assert candidacies[1][0] == date(2024, 11, 5)


class TestIncumbentChallengeMapping:
    """FEC I/C/O codes pass through to Candidacy.incumbent_challenge."""

    def test_incumbent_challenge_codes(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [
            _house_row(cand_id="H4NC01010", ici="I"),
            _house_row(cand_id="H4NC01011", ici="C"),
            _house_row(cand_id="H4NC01012", ici="O"),
        ]
        filepath = _write_cn_file(tmp_path, rows)
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        # Filter by candidate_number to avoid picking up committed data from other tests
        ici_values = db_conn.execute(
            """
            SELECT ca.incumbent_challenge
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.candidate_number IN ('H4NC01010', 'H4NC01011', 'H4NC01012')
              AND sr.data_source_id = %s
            ORDER BY ca.incumbent_challenge
            """,
            (ds.id,),
        ).fetchall()
        assert [r[0] for r in ici_values] == ["C", "I", "O"]


class TestFederalOfficeholderDirectoryContract:
    """Federal directory rows populate officeholding status, vacancy, and contact ownership."""

    def test_house_directory_ingest_tracks_current_holder_and_vacancy(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_house_officeholders

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="federal/officeholder",
            name=f"Federal Officeholder Test {uuid4()}",
            source_url="https://clerk.house.gov/xml/lists/MemberData.xml",
        )
        insert_data_source(db_conn, ds)

        current_holder = {
            "member_name": "SMITH, ALICE",
            "first_name": "Alice",
            "last_name": "Smith",
            "bioguide_id": "H-STATUS-1",
            "state": "NC",
            "district": "01",
            "phone": "202-225-0101",
            "sworn_date": "2025-01-03",
        }
        vacant_seat = {
            "member_name": "VACANT",
            "first_name": "",
            "last_name": "",
            "bioguide_id": "",
            "state": "NC",
            "district": "02",
            "phone": "",
            "sworn_date": "",
        }
        result = load_federal_house_officeholders(db_conn, [current_holder, vacant_seat], data_source_id=ds.id)
        assert result.inserted == 1
        assert result.skipped == 1

        row = db_conn.execute(
            "SELECT holder_status, lower(valid_period), upper(valid_period) "
            "FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"bioguide_id": "H-STATUS-1"}',),
        ).fetchone()
        assert row is not None
        assert row[0] == "elected"
        assert row[1] == date(2025, 1, 3)
        assert row[2] == date(2027, 1, 3)

        vacant_person = db_conn.execute(
            "SELECT id FROM core.person WHERE canonical_name = 'VACANT'",
        ).fetchone()
        assert vacant_person is None

    def test_senate_directory_sets_appointed_and_contact_ownership(self, db_conn: psycopg.Connection) -> None:
        from domains.campaign_finance.ingest.federal_officeholder_loader import load_federal_senate_officeholders

        ds = DataSource(
            domain="campaign_finance",
            jurisdiction="federal/officeholder",
            name=f"Federal Officeholder Test {uuid4()}",
            source_url="https://www.senate.gov/general/contact_information/senators_cfm.xml",
        )
        insert_data_source(db_conn, ds)

        row = {
            "member_full": "SMITH, ALICE",
            "first_name": "Alice",
            "last_name": "Smith",
            "bioguide_id": "S-STATUS-1",
            "state": "NC",
            "class": "II",
            "phone": "202-224-0101",
            "email": "alice_smith@senate.gov",
            "appointed": "true",
        }
        result = load_federal_senate_officeholders(db_conn, [row], data_source_id=ds.id)
        assert result.inserted == 1

        status_row = db_conn.execute(
            "SELECT holder_status "
            "FROM civic.officeholding oh "
            "JOIN core.person p ON p.id = oh.person_id "
            "WHERE p.identifiers @> %s",
            ('{"bioguide_id": "S-STATUS-1"}',),
        ).fetchone()
        assert status_row is not None
        assert status_row[0] == "appointed"

        phone_owner = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = '202-224-0101' AND type = 'phone'",
        ).fetchone()
        email_owner = db_conn.execute(
            "SELECT owner_type FROM core.contact_point WHERE value_raw = 'alice_smith@senate.gov' AND type = 'email'",
        ).fetchone()
        assert phone_owner is not None
        assert email_owner is not None
        assert phone_owner[0] == "office"
        assert email_owner[0] == "officeholding"


class TestDerivedIncumbencyFromOfficeholding:
    """Derived incumbency uses canonical officeholding when source flag is absent."""

    def test_derives_incumbent_when_fec_ici_missing(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        nc01_division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_cd_01",
                division_type="congressional_district",
                state="NC",
                district_number="01",
                parent_id=DIVISION_US_CONGRESSIONAL_DISTRICTS,
                boundary_year=2022,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="INCUMBENT, CASEY",
                identifiers={"fec_candidate_id": "H4NC01999"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_HOUSE,
                electoral_division_id=nc01_division_id,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2025, 1, 3), end_date=date(2027, 1, 3)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(
            tmp_path,
            [_house_row(cand_id="H4NC01999", name="INCUMBENT, CASEY", year="2026", ici="")],
        )
        load_fec_candidates_canonical(db_conn, filepath, cycle=2026, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT ca.incumbent_challenge
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.candidate_number = 'H4NC01999'
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "I"

    def test_derives_house_incumbent_using_contest_date_not_today(
        self,
        db_conn: psycopg.Connection,
        tmp_path: Path,
    ) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        nc01_division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_cd_01",
                division_type="congressional_district",
                state="NC",
                district_number="01",
                parent_id=DIVISION_US_CONGRESSIONAL_DISTRICTS,
                boundary_year=2022,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="HISTORICAL, HOUSE",
                identifiers={"fec_candidate_id": "H4NC01996"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_HOUSE,
                electoral_division_id=nc01_division_id,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2023, 1, 3), end_date=date(2025, 1, 3)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(
            tmp_path,
            [_house_row(cand_id="H4NC01996", name="HISTORICAL, HOUSE", year="2024", ici="")],
        )
        load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT ca.incumbent_challenge
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.candidate_number = 'H4NC01996'
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "I"

    def test_missing_senate_ici_does_not_guess_from_statewide_officeholding(
        self,
        db_conn: psycopg.Connection,
        tmp_path: Path,
    ) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ga_statewide_division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="ga",
                division_type="statewide",
                state="GA",
                parent_id=DIVISION_US_STATEWIDE,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="AMBIGUOUS, SENATE",
                identifiers={"fec_candidate_id": "S6GA00001"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_SENATE,
                electoral_division_id=ga_statewide_division_id,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2023, 1, 3), end_date=date(2029, 1, 3)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(
            tmp_path,
            [_senate_row(cand_id="S6GA00001", name="AMBIGUOUS, SENATE", state="GA", year="2026", ici="")],
        )
        load_fec_candidates_canonical(db_conn, filepath, cycle=2026, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT ca.incumbent_challenge
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.candidate_number = 'S6GA00001'
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()
        assert row is not None
        assert row[0] is None

    def test_fec_source_flag_remains_authoritative(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="CHALLENGER, AVERY",
                identifiers={"fec_candidate_id": "H4NC01998"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_HOUSE,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2025, 1, 3), end_date=date(2027, 1, 3)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(
            tmp_path,
            [_house_row(cand_id="H4NC01998", name="CHALLENGER, AVERY", year="2026", ici="C")],
        )
        load_fec_candidates_canonical(db_conn, filepath, cycle=2026, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT ca.incumbent_challenge
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.candidate_number = 'H4NC01998'
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "C"

    def test_house_officeholding_in_other_district_is_not_treated_as_incumbent(
        self,
        db_conn: psycopg.Connection,
        tmp_path: Path,
    ) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        nc01_division_id = upsert_electoral_division(
            db_conn,
            ElectoralDivision(
                name="nc_cd_01",
                division_type="congressional_district",
                state="NC",
                district_number="01",
                parent_id=DIVISION_US_CONGRESSIONAL_DISTRICTS,
                boundary_year=2022,
            ),
        )
        person_id = insert_person(
            db_conn,
            Person(
                canonical_name="SWITCHED, DISTRICT",
                identifiers={"fec_candidate_id": "H4NC01997"},
            ),
        )
        upsert_officeholding(
            db_conn,
            Officeholding(
                person_id=person_id,
                office_id=OFFICE_US_HOUSE,
                electoral_division_id=nc01_division_id,
                holder_status="elected",
                valid_period=ValidDateRange(start_date=date(2025, 1, 3), end_date=date(2027, 1, 3)),
                date_precision="day",
            ),
        )

        ds = _make_data_source(db_conn)
        filepath = _write_cn_file(
            tmp_path,
            [_house_row(cand_id="H4NC01997", name="SWITCHED, DISTRICT", year="2026", district="02", ici="")],
        )
        load_fec_candidates_canonical(db_conn, filepath, cycle=2026, data_source_id=ds.id)

        row = db_conn.execute(
            """
            SELECT ca.incumbent_challenge
            FROM civic.candidacy ca
            JOIN core.source_record sr ON sr.id = ca.source_record_id
            WHERE ca.candidate_number = 'H4NC01997'
              AND sr.data_source_id = %s
            """,
            (ds.id,),
        ).fetchone()
        assert row is not None
        assert row[0] is None

    def test_no_second_persisted_incumbency_field(self, db_conn: psycopg.Connection) -> None:
        columns = db_conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'civic' AND table_name = 'candidacy'
            ORDER BY ordinal_position
            """,
        ).fetchall()
        column_names = {column[0] for column in columns}
        assert "incumbent_challenge" in column_names
        assert "derived_incumbent" not in column_names
        assert "is_incumbent" not in column_names


class TestLoadResult:
    """Load result tracking."""

    def test_returns_load_result_with_counts(self, db_conn: psycopg.Connection, tmp_path: Path) -> None:
        from domains.campaign_finance.ingest.fec_canonical_loader import load_fec_candidates_canonical

        ds = _make_data_source(db_conn)
        rows = [_house_row(), _senate_row(), _president_row()]
        filepath = _write_cn_file(tmp_path, rows)
        result = load_fec_candidates_canonical(db_conn, filepath, cycle=2024, data_source_id=ds.id)
        assert result.inserted == 3
        assert result.errors == 0
