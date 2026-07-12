from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
import pytest

from api.queries.civics import fetch_contest_candidacies, fetch_electoral_division_geometries
from core.db import insert_person
from core.types.python.models import Person
from domains.civics.ingest import upsert_candidacy, upsert_contest, upsert_electoral_division, upsert_office
from domains.civics.loaders.official_rosters.loader import harvest_official_roster
from domains.civics.types.models import Candidacy, Contest, ElectoralDivision, Office
from scripts.register_roster_pilot_sources import register_roster_pilot_sources


pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "roster"
_DURHAM_SOURCE_ID = "nc_durham_city_council_roster"

# Canonical NC launch counts are fixed in production evidence:
# docs/reference/research/2026_04_27_nc_drilldown_showcase_closeout.md
_NC_GEOMETRY_EXPECTED_COUNTS = {
    "state": 1,
    "county": 100,
    "congressional_district": 14,
}


def _fixture_path(name: str) -> Path:
    return _FIXTURE_DIR / name


def _seed_roster_fixture_people(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES
                (gen_random_uuid(), 'Leonardo Williams', 'Leonardo', 'Williams', '{}'::jsonb),
                (gen_random_uuid(), 'Javiera Caballero', 'Javiera', 'Caballero', '{}'::jsonb),
                (gen_random_uuid(), 'Shanetta Burris', 'Shanetta', 'Burris', '{}'::jsonb),
                (gen_random_uuid(), 'Julia C. Howard', 'Julia', 'Howard', '{}'::jsonb),
                (gen_random_uuid(), 'Mitchell S. Setzer', 'Mitchell', 'Setzer', '{}'::jsonb),
                (gen_random_uuid(), 'Becky Carney', 'Becky', 'Carney', '{}'::jsonb)
            ON CONFLICT DO NOTHING
            """
        )


def _active_snapshot_source_record_id(conn: psycopg.Connection, source_id: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT sr.id::text
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = %s
              AND sr.source_record_key = %s
              AND sr.superseded_by IS NULL
            """,
            (source_id, f"official_roster:{source_id}:snapshot"),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def _seat_coverage_for_source_snapshot(conn: psycopg.Connection, source_record_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(SUM(o.number_of_seats), 0)::int
            FROM civic.office o
            JOIN core.entity_source es
              ON es.entity_type = 'office'
             AND es.entity_id = o.id
            WHERE es.source_record_id = %s::uuid
            """,
            (source_record_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def _officeholding_count_for_source_snapshot(conn: psycopg.Connection, source_record_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::int
            FROM civic.officeholding
            WHERE source_record_id = %s::uuid
            """,
            (source_record_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def _square_multipolygon(min_x: float, min_y: float, size: float = 0.05) -> dict[str, object]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [min_x, min_y],
                    [min_x + size, min_y],
                    [min_x + size, min_y + size],
                    [min_x, min_y + size],
                    [min_x, min_y],
                ]
            ]
        ],
    }


def _seed_nc_geometry_rows_for_exact_gate_counts(conn: psycopg.Connection) -> None:
    boundary_year = 2099

    upsert_electoral_division(
        conn,
        ElectoralDivision(
            name="nc_dwo_gate_statewide",
            division_type="statewide",
            state="NC",
            boundary_year=boundary_year,
            geometry=_square_multipolygon(-80.0, 34.0),
        ),
    )

    for county_index in range(1, 101):
        upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"nc_dwo_gate_county_{county_index:03d}",
                division_type="county",
                state="NC",
                boundary_year=boundary_year,
                geometry=_square_multipolygon(-81.0 + county_index * 0.01, 35.0),
            ),
        )

    for district_index in range(1, 15):
        upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"nc_dwo_gate_cd_{district_index:02d}",
                division_type="congressional_district",
                state="NC",
                district_number=f"{district_index:02d}",
                boundary_year=boundary_year,
                geometry=_square_multipolygon(-79.0 + district_index * 0.02, 36.0),
            ),
        )


def test_roster_gate_enforces_exact_source_scoped_counts(db_conn: psycopg.Connection) -> None:
    register_roster_pilot_sources(db_conn)
    _seed_roster_fixture_people(db_conn)

    result = harvest_official_roster(
        db_conn,
        source_id=_DURHAM_SOURCE_ID,
        fixture_path=_fixture_path("nc_durham_city_council.html"),
        dry_run=False,
        fetch_bytes=lambda _url, *, timeout_seconds: None,
    )

    assert result.member_count == 3
    assert result.resolved_member_count == 3
    assert result.unresolved_member_count == 0

    source_record_id = _active_snapshot_source_record_id(db_conn, _DURHAM_SOURCE_ID)
    officeholding_count = _officeholding_count_for_source_snapshot(db_conn, source_record_id)
    assert officeholding_count == 3

    # _resolve_target encodes the Durham seat model as one mayor seat plus six council seats.
    seat_coverage = _seat_coverage_for_source_snapshot(db_conn, source_record_id)
    assert seat_coverage == 7


def test_candidacy_gate_enforces_exact_seed_plan_count(db_conn: psycopg.Connection) -> None:
    office_id = upsert_office(
        db_conn,
        Office(
            name="nc_state_senate_member_dwo_count_gate",
            office_level="state",
            title="State Senator",
            state="NC",
            number_of_seats=1,
        ),
    )
    contest_id = upsert_contest(
        db_conn,
        Contest(
            name="NC State Senate General 2026 DWO Count Gate",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_id,
            number_of_seats=1,
        ),
    )

    seeded_candidates = (
        ("Alice Exact", "DEM"),
        ("Brian Exact", "REP"),
        ("Casey Exact", "UNA"),
    )
    for candidate_name, party in seeded_candidates:
        person_id = insert_person(
            db_conn, Person(canonical_name=candidate_name, first_name=candidate_name.split()[0], last_name="Exact")
        )
        upsert_candidacy(
            db_conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                party=party,
                status="qualified",
            ),
        )

    expected_candidacy_count = len(seeded_candidates)
    candidacies = fetch_contest_candidacies(db_conn, contest_id)
    assert len(candidacies) == expected_candidacy_count
    assert {row["person_name"] for row in candidacies} == {candidate_name for candidate_name, _ in seeded_candidates}


def test_geometry_gate_pins_nc_launch_exact_counts(db_conn: psycopg.Connection) -> None:
    _seed_nc_geometry_rows_for_exact_gate_counts(db_conn)

    for level, expected_count in _NC_GEOMETRY_EXPECTED_COUNTS.items():
        rows = fetch_electoral_division_geometries(db_conn, level=level, state="NC")
        assert len(rows) == expected_count
