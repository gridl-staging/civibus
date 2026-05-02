"""SQL query helpers for civic domain endpoints."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from api.queries._common import fetch_one_row
from domains.civics.constants import LAUNCH_SCOPE_USPS_STATES

# ---------------------------------------------------------------------------
# Office
# ---------------------------------------------------------------------------

CIVIC_OFFICE_DETAIL_SQL = """
    SELECT
        id,
        name,
        office_level,
        title,
        jurisdiction_id,
        state,
        electoral_division_id,
        is_elected,
        number_of_seats
    FROM civic.office
    WHERE id = %s
"""

_OFFICE_CURRENT_OFFICEHOLDERS_SQL = """
    SELECT
        oh.id AS officeholding_id,
        oh.person_id,
        p.canonical_name AS person_name,
        oh.holder_status,
        oh.electoral_division_id,
        ed.division_type AS electoral_division_type,
        ed.state AS electoral_division_state,
        lower(oh.valid_period) AS valid_period_lower,
        upper(oh.valid_period) AS valid_period_upper,
        oh.date_precision
    FROM civic.officeholding oh
    JOIN core.person p ON p.id = oh.person_id
    LEFT JOIN civic.electoral_division ed ON ed.id = oh.electoral_division_id
    WHERE oh.office_id = %s
      AND oh.valid_period @> CURRENT_DATE
    ORDER BY lower(oh.valid_period) DESC NULLS LAST, p.canonical_name, oh.id
"""

_OFFICE_TIMELINE_SQL = """
    SELECT
        oh.id AS officeholding_id,
        oh.person_id,
        p.canonical_name AS person_name,
        oh.holder_status,
        oh.electoral_division_id,
        ed.division_type AS electoral_division_type,
        ed.state AS electoral_division_state,
        lower(oh.valid_period) AS valid_period_lower,
        upper(oh.valid_period) AS valid_period_upper,
        oh.date_precision,
        (oh.valid_period @> CURRENT_DATE) AS is_active,
        (
            upper(oh.valid_period) IS NOT NULL
            AND upper(oh.valid_period) <= CURRENT_DATE
        ) AS term_ended
    FROM civic.officeholding oh
    JOIN core.person p ON p.id = oh.person_id
    LEFT JOIN civic.electoral_division ed ON ed.id = oh.electoral_division_id
    WHERE oh.office_id = %s
    ORDER BY
        lower(oh.valid_period) DESC NULLS LAST,
        upper(oh.valid_period) DESC NULLS LAST,
        p.canonical_name,
        oh.id
"""

_OFFICE_RECENT_CONTESTS_SQL = """
    SELECT
        c.id AS contest_id,
        c.name AS contest_name,
        c.election_date,
        c.election_type,
        c.filing_deadline,
        c.electoral_division_id,
        ed.division_type AS electoral_division_type,
        ed.state AS electoral_division_state,
        c.is_partisan,
        c.candidate_list_incomplete
    FROM civic.contest c
    LEFT JOIN civic.electoral_division ed ON ed.id = c.electoral_division_id
    WHERE c.office_id = %s
    ORDER BY c.election_date DESC NULLS LAST, c.id DESC
    LIMIT 5
"""

_OFFICE_ACTIVE_CONTEST_COUNT_SQL = """
    SELECT COUNT(*)::int AS active_contest_count
    FROM civic.contest c
    WHERE c.office_id = %s
      AND c.election_date IS NOT NULL
      AND c.election_date >= CURRENT_DATE
"""


def fetch_office_detail(conn: psycopg.Connection, office_id: UUID) -> dict[str, Any] | None:
    return fetch_one_row(conn, query=CIVIC_OFFICE_DETAIL_SQL, row_id=office_id)


def fetch_office_officeholders(conn: psycopg.Connection, office_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_OFFICE_CURRENT_OFFICEHOLDERS_SQL, (office_id,))
        return list(cursor.fetchall())


def fetch_officeholding_timeline(conn: psycopg.Connection, office_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_OFFICE_TIMELINE_SQL, (office_id,))
        return list(cursor.fetchall())


def fetch_office_recent_contests(conn: psycopg.Connection, office_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_OFFICE_RECENT_CONTESTS_SQL, (office_id,))
        return list(cursor.fetchall())


def fetch_office_active_contest_count(conn: psycopg.Connection, office_id: UUID) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_OFFICE_ACTIVE_CONTEST_COUNT_SQL, (office_id,))
        row = cursor.fetchone()
    if row is None:
        return 0
    return int(row["active_contest_count"])


# ---------------------------------------------------------------------------
# Contest
# ---------------------------------------------------------------------------

CIVIC_CONTEST_DETAIL_SQL = """
    SELECT
        c.id,
        c.name,
        c.election_date,
        c.election_type,
        c.office_id,
        c.electoral_division_id,
        ed.division_type AS electoral_division_type,
        ed.state AS electoral_division_state,
        c.number_of_seats,
        c.filing_deadline,
        c.is_partisan,
        c.candidate_list_incomplete
    FROM civic.contest c
    LEFT JOIN civic.electoral_division ed ON ed.id = c.electoral_division_id
    WHERE c.id = %s
"""

_CONTEST_CANDIDACIES_SQL = """
    SELECT
        c.id AS candidacy_id,
        c.person_id,
        p.canonical_name AS person_name,
        c.party,
        c.status,
        c.incumbent_challenge
    FROM civic.candidacy c
    JOIN core.person p ON p.id = c.person_id
    WHERE c.contest_id = %s
    ORDER BY p.canonical_name, c.id
"""


def fetch_contest_detail(conn: psycopg.Connection, contest_id: UUID) -> dict[str, Any] | None:
    return fetch_one_row(conn, query=CIVIC_CONTEST_DETAIL_SQL, row_id=contest_id)


def fetch_contest_candidacies(conn: psycopg.Connection, contest_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CONTEST_CANDIDACIES_SQL, (contest_id,))
        return list(cursor.fetchall())


_ELECTION_CONTESTS_BY_DATE_SQL = """
    SELECT
        c.id AS contest_id,
        c.office_id,
        c.name,
        c.election_type,
        o.name AS office_name,
        o.office_level,
        o.state,
        o.jurisdiction_id,
        c.electoral_division_id,
        COUNT(cd.id)::int AS candidate_count
    FROM civic.contest c
    JOIN civic.office o ON o.id = c.office_id
    LEFT JOIN civic.candidacy cd ON cd.contest_id = c.id
    WHERE c.election_date = %s
    GROUP BY
        c.id,
        c.office_id,
        c.name,
        c.election_type,
        o.name,
        o.office_level,
        o.state,
        o.jurisdiction_id,
        c.electoral_division_id
    ORDER BY o.state NULLS LAST, o.name, c.name, c.id
"""

_UPCOMING_ELECTION_CONTESTS_SQL = """
    SELECT
        c.election_date,
        c.id AS contest_id,
        c.office_id,
        c.name,
        c.election_type,
        o.name AS office_name,
        o.office_level,
        o.state,
        o.jurisdiction_id,
        c.electoral_division_id,
        COUNT(cd.id)::int AS candidate_count
    FROM civic.contest c
    JOIN civic.office o ON o.id = c.office_id
    LEFT JOIN civic.candidacy cd ON cd.contest_id = c.id
    WHERE c.election_date >= CURRENT_DATE
    GROUP BY
        c.election_date,
        c.id,
        c.office_id,
        c.name,
        c.election_type,
        o.name,
        o.office_level,
        o.state,
        o.jurisdiction_id,
        c.electoral_division_id
    ORDER BY c.election_date, o.state NULLS LAST, o.name, c.name, c.id
"""


def fetch_election_contests_by_date(conn: psycopg.Connection, election_date: date) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_ELECTION_CONTESTS_BY_DATE_SQL, (election_date,))
        return list(cursor.fetchall())


def fetch_upcoming_election_contests(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_UPCOMING_ELECTION_CONTESTS_SQL)
        return list(cursor.fetchall())


# ---------------------------------------------------------------------------
# Candidacy
# ---------------------------------------------------------------------------

CIVIC_CANDIDACY_DETAIL_SQL = """
    SELECT
        c.id,
        c.person_id,
        p.canonical_name AS person_name,
        c.contest_id,
        c.party,
        c.filing_date,
        c.status,
        c.incumbent_challenge,
        c.candidate_number
    FROM civic.candidacy c
    JOIN core.person p ON p.id = c.person_id
    WHERE c.id = %s
"""


def fetch_candidacy_detail(conn: psycopg.Connection, candidacy_id: UUID) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CIVIC_CANDIDACY_DETAIL_SQL, (candidacy_id,))
        return cursor.fetchone()


# ---------------------------------------------------------------------------
# Officeholding
# ---------------------------------------------------------------------------

CIVIC_OFFICEHOLDING_DETAIL_SQL = """
    SELECT
        oh.id,
        oh.person_id,
        p.canonical_name AS person_name,
        oh.office_id,
        oh.electoral_division_id,
        oh.holder_status,
        lower(oh.valid_period) AS valid_period_lower,
        upper(oh.valid_period) AS valid_period_upper,
        oh.date_precision
    FROM civic.officeholding oh
    JOIN core.person p ON p.id = oh.person_id
    WHERE oh.id = %s
"""


def fetch_officeholding_detail(conn: psycopg.Connection, officeholding_id: UUID) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CIVIC_OFFICEHOLDING_DETAIL_SQL, (officeholding_id,))
        return cursor.fetchone()


# ---------------------------------------------------------------------------
# Jurisdiction browse
# ---------------------------------------------------------------------------

_JURISDICTION_EXISTS_SQL = """
    SELECT 1 FROM core.jurisdiction WHERE id = %s
"""

_OFFICES_BY_JURISDICTION_SQL = """
    SELECT
        id,
        name,
        office_level,
        title,
        state,
        is_elected,
        number_of_seats
    FROM civic.office
    WHERE jurisdiction_id = %s
    ORDER BY name, id
"""


def fetch_jurisdiction_exists(conn: psycopg.Connection, jurisdiction_id: UUID) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(_JURISDICTION_EXISTS_SQL, (jurisdiction_id,))
        return cursor.fetchone() is not None


def fetch_offices_by_jurisdiction(conn: psycopg.Connection, jurisdiction_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_OFFICES_BY_JURISDICTION_SQL, (jurisdiction_id,))
        return list(cursor.fetchall())


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

GeometryLevelLiteral = Literal["state", "county", "congressional_district"]
_GEOMETRY_LEVEL_TO_DIVISION_TYPE: dict[GeometryLevelLiteral, str] = {
    "state": "statewide",
    "county": "county",
    "congressional_district": "congressional_district",
}

_ELECTORAL_DIVISION_GEOMETRY_SQL = """
    WITH latest_boundary_year AS (
        SELECT MAX(boundary_year) AS boundary_year
        FROM civic.electoral_division
        WHERE division_type = %s
          AND state = %s
          AND geometry IS NOT NULL
    )
    SELECT
        ed.id,
        ed.name,
        ed.division_type,
        ed.state,
        ed.district_number,
        ed.boundary_year,
        ST_AsGeoJSON(ed.geometry)::jsonb AS geometry
    FROM civic.electoral_division ed
    CROSS JOIN latest_boundary_year lby
    WHERE ed.division_type = %s
      AND ed.state = %s
      AND ed.geometry IS NOT NULL
      AND ed.boundary_year IS NOT DISTINCT FROM lby.boundary_year
    ORDER BY ed.name, ed.id
"""


def fetch_electoral_division_geometries(
    conn: psycopg.Connection,
    *,
    level: GeometryLevelLiteral,
    state: str,
) -> list[dict[str, Any]]:
    division_type = _GEOMETRY_LEVEL_TO_DIVISION_TYPE[level]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_ELECTORAL_DIVISION_GEOMETRY_SQL, (division_type, state, division_type, state))
        return [_row_with_geometry_json(dict(row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

_CONTACTS_BY_OWNER_SQL = """
    SELECT
        id,
        type,
        value_normalized,
        role,
        owner_type,
        owner_id
    FROM core.contact_point
    WHERE owner_type = %s AND owner_id = %s
    ORDER BY type, id
"""


def fetch_contacts_by_owner(conn: psycopg.Connection, owner_type: str, owner_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CONTACTS_BY_OWNER_SQL, (owner_type, owner_id))
        return list(cursor.fetchall())


# ---------------------------------------------------------------------------
# Geometry browse (civic.electoral_division is the sole geometry read owner)
# ---------------------------------------------------------------------------

_COUNTRY_STATE_GEOMETRIES_SQL = """
    SELECT DISTINCT ON (state)
        state,
        name,
        division_type,
        boundary_year,
        ST_AsGeoJSON(geometry)::jsonb AS geometry
    FROM civic.electoral_division
    WHERE division_type = 'statewide'
      AND state = ANY(%s)
      AND geometry IS NOT NULL
    ORDER BY state, boundary_year DESC NULLS LAST, id DESC
"""

_STATE_GEOMETRY_SQL = """
    SELECT
        state,
        name,
        division_type,
        boundary_year,
        ST_AsGeoJSON(geometry)::jsonb AS geometry
    FROM civic.electoral_division
    WHERE division_type = 'statewide'
      AND state = %s
      AND state = ANY(%s)
      AND geometry IS NOT NULL
    ORDER BY boundary_year DESC NULLS LAST, id DESC
    LIMIT 1
"""


def _row_with_geometry_json(row: dict[str, Any]) -> dict[str, Any]:
    geometry = row.get("geometry")
    if isinstance(geometry, str):
        row["geometry"] = json.loads(geometry)
    return row


def fetch_country_state_geometries(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_COUNTRY_STATE_GEOMETRIES_SQL, (list(LAUNCH_SCOPE_USPS_STATES),))
        return [_row_with_geometry_json(dict(row)) for row in cursor.fetchall()]


def fetch_state_geometry(conn: psycopg.Connection, state: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_STATE_GEOMETRY_SQL, (state, list(LAUNCH_SCOPE_USPS_STATES)))
        row = cursor.fetchone()
    if row is None:
        return None
    return _row_with_geometry_json(dict(row))
