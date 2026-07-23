
from __future__ import annotations

import json
from datetime import date
from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from api.portrait_policy import reusable_portrait_rights_statuses
from api.queries._common import fetch_one_row
from domains.civics.constants import CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES, LAUNCH_SCOPE_USPS_STATES

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
# Congress directory
# ---------------------------------------------------------------------------


def _sql_text_array_literal(values: Iterable[str]) -> str:
    quoted_values = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"ARRAY[{quoted_values}]::text[]"


def _current_federal_directory_office_names_sql() -> str:
    return _sql_text_array_literal(CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES)


def _current_federal_members_ctes_sql(*, office_names_sql: str) -> str:
    return f"""
    base_members AS (
        SELECT
            oh.id AS officeholding_id,
            oh.person_id,
            oh.office_id,
            oh.electoral_division_id,
            oh.source_record_id AS officeholding_source_record_id,
            p.canonical_name AS person_name,
            o.name AS canonical_office_name,
            o.title AS office_title,
            o.state AS office_state,
            ed.division_type,
            ed.state AS division_state,
            ed.district_number,
            COALESCE(ed.state, o.state) AS member_state,
            sr.raw_fields ->> 'class' AS senate_class_raw,
            sr.raw_fields ->> 'party' AS source_record_party
        FROM civic.officeholding oh
        JOIN civic.office o ON o.id = oh.office_id
        JOIN core.person p ON p.id = oh.person_id
        LEFT JOIN civic.electoral_division ed ON ed.id = oh.electoral_division_id
        LEFT JOIN core.source_record sr ON sr.id = oh.source_record_id
        WHERE oh.valid_period @> CURRENT_DATE
          AND o.office_level = 'federal'
          AND o.name = ANY({office_names_sql})
    ),
    fec_party_by_officeholding AS (
        SELECT DISTINCT ON (base.officeholding_id)
            base.officeholding_id,
            cand.party
        FROM base_members base
        JOIN cf.candidate cand
          ON cand.person_id = base.person_id
         AND cand.party IS NOT NULL
         AND cand.office = CASE
             WHEN base.canonical_office_name = 'us_senate' THEN 'S'
             WHEN base.canonical_office_name IN ('us_president', 'us_vice_president') THEN 'P'
             ELSE 'H'
         END
         AND (
             base.member_state IS NULL
             OR cand.state IS NULL
             OR cand.state = base.member_state
         )
        ORDER BY base.officeholding_id, cand.summary_coverage_end_date DESC NULLS LAST, cand.updated_at DESC, cand.id DESC
    ),
    current_members AS (
        SELECT
            base.*,
            COALESCE(
                fec_party.party,
                civic_party.party,
                NULLIF(btrim(base.source_record_party), '')
            ) AS party,
            pp.rights_status AS portrait_rights_status,
            pp.source_image_url AS raw_portrait_source_image_url
        FROM base_members base
        LEFT JOIN fec_party_by_officeholding fec_party
          ON fec_party.officeholding_id = base.officeholding_id
        LEFT JOIN LATERAL (
            SELECT c.party
            FROM civic.candidacy c
            JOIN civic.contest ct ON ct.id = c.contest_id
            WHERE c.person_id = base.person_id
              AND ct.office_id = base.office_id
              AND c.party IS NOT NULL
            ORDER BY ct.election_date DESC NULLS LAST, c.id DESC
            LIMIT 1
        ) civic_party ON TRUE
        LEFT JOIN LATERAL (
            SELECT rights_status, source_image_url
            FROM core.person_portrait
            WHERE person_id = base.person_id
              AND status = 'active'
            ORDER BY updated_at DESC, id ASC
            LIMIT 1
        ) pp ON TRUE
    ),
    derived_members AS (
        SELECT
            *,
            CASE upper(btrim(COALESCE(senate_class_raw, '')))
                WHEN '1' THEN 'Class I'
                WHEN 'CLASS I' THEN 'Class I'
                WHEN '2' THEN 'Class II'
                WHEN 'CLASS II' THEN 'Class II'
                WHEN '3' THEN 'Class III'
                WHEN 'CLASS III' THEN 'Class III'
                ELSE NULL
            END AS senate_class_label,
            CASE
                WHEN canonical_office_name = 'us_house' THEN 'U.S. Representative'
                WHEN canonical_office_name = 'us_senate' THEN 'U.S. Senator'
                WHEN canonical_office_name = 'us_house_delegate' THEN 'U.S. Delegate'
                WHEN canonical_office_name = 'us_president' THEN 'President of the United States'
                WHEN canonical_office_name = 'us_vice_president' THEN 'Vice President of the United States'
                ELSE COALESCE(office_title, canonical_office_name)
            END AS short_office_label,
            CASE
                WHEN canonical_office_name IN ('us_house', 'us_house_delegate')
                  AND COALESCE(division_state, office_state) IS NOT NULL
                  AND district_number IS NOT NULL
                    THEN COALESCE(division_state, office_state) || '-' || district_number
                WHEN canonical_office_name = 'us_senate' THEN COALESCE(division_state, office_state)
                ELSE NULL
            END AS search_geography_token
        FROM current_members
    )
    """


def _current_federal_members_with_sql(*, office_names_sql: str) -> str:
    return f"WITH {_current_federal_members_ctes_sql(office_names_sql=office_names_sql)}"


def _current_federal_officeholder_search_rows_sql(*, office_names_sql: str | None = None) -> str:
    offices_sql = office_names_sql or _current_federal_directory_office_names_sql()
    return f"""
        {_current_federal_members_with_sql(office_names_sql=offices_sql)}
        SELECT DISTINCT ON (person_id)
            person_id,
            short_office_label,
            search_geography_token,
            party
        FROM derived_members
        ORDER BY person_id, person_name, officeholding_id
    """


_CURRENT_FEDERAL_MEMBERS_SQL = f"""
    {_current_federal_members_with_sql(office_names_sql="%s")}
    SELECT
        person_id,
        person_name,
        officeholding_id,
        officeholding_source_record_id,
        office_id,
        CASE
            WHEN canonical_office_name = 'us_house'
              AND member_state IS NOT NULL
              AND district_number IS NOT NULL
                THEN 'U.S. Representative ' || member_state || '-' || district_number
            WHEN canonical_office_name = 'us_senate'
              AND member_state IS NOT NULL
              AND senate_class_label IS NOT NULL
                THEN 'U.S. Senator ' || member_state || ' ' || senate_class_label
            WHEN canonical_office_name = 'us_senate'
              AND member_state IS NOT NULL
                THEN 'U.S. Senator ' || member_state
            WHEN canonical_office_name = 'us_president' THEN 'President of the United States'
            WHEN canonical_office_name = 'us_vice_president' THEN 'Vice President of the United States'
            WHEN canonical_office_name = 'us_house_delegate'
              AND member_state IS NOT NULL
              AND district_number IS NOT NULL
                THEN short_office_label || ' ' || member_state || '-' || district_number
            WHEN canonical_office_name = 'us_house_delegate'
              AND member_state IS NOT NULL
                THEN short_office_label || ' ' || member_state
            ELSE COALESCE(office_title, canonical_office_name)
        END AS office_name,
        CASE
            WHEN canonical_office_name IN ('us_president', 'us_vice_president') THEN 'Executive'
            WHEN canonical_office_name = 'us_senate' THEN 'Senate'
            WHEN canonical_office_name IN ('us_house', 'us_house_delegate') THEN 'House'
            WHEN COALESCE(office_title, canonical_office_name) ILIKE '%%president%%' THEN 'Executive'
            WHEN COALESCE(office_title, canonical_office_name) ILIKE '%%senat%%' THEN 'Senate'
            WHEN COALESCE(office_title, canonical_office_name) ILIKE '%%delegate%%' THEN 'House'
            WHEN COALESCE(office_title, canonical_office_name) ILIKE '%%representative%%' THEN 'House'
            WHEN COALESCE(office_title, canonical_office_name) ILIKE '%%house%%' THEN 'House'
            ELSE COALESCE(office_title, canonical_office_name)
        END AS chamber,
        member_state AS state,
        CASE
            WHEN division_type = 'congressional_district' THEN district_number
            ELSE NULL
        END AS district,
        CASE
            WHEN canonical_office_name = 'us_house_delegate' THEN 'Delegate'
            WHEN division_type = 'congressional_district' THEN district_number
            WHEN canonical_office_name = 'us_senate' THEN senate_class_label
            ELSE NULL
        END AS district_or_class,
        party,
        CASE
            WHEN portrait_rights_status = ANY(%s) THEN raw_portrait_source_image_url
            ELSE NULL
        END AS portrait_source_image_url
    FROM derived_members
    ORDER BY person_name, officeholding_id
"""


def fetch_current_federal_members(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CURRENT_FEDERAL_MEMBERS_SQL,
            (
                list(CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES),
                list(reusable_portrait_rights_statuses()),
            ),
        )
        return list(cursor.fetchall())


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
