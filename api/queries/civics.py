"""SQL query helpers for civic domain endpoints."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from api.queries._common import fetch_one_row

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
        oh.holder_status
    FROM civic.officeholding oh
    JOIN core.person p ON p.id = oh.person_id
    WHERE oh.office_id = %s
      AND upper_inf(oh.valid_period)
    ORDER BY p.canonical_name, oh.id
"""


def fetch_office_detail(conn: psycopg.Connection, office_id: UUID) -> dict[str, Any] | None:
    return fetch_one_row(conn, query=CIVIC_OFFICE_DETAIL_SQL, row_id=office_id)


def fetch_office_officeholders(conn: psycopg.Connection, office_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_OFFICE_CURRENT_OFFICEHOLDERS_SQL, (office_id,))
        return list(cursor.fetchall())


# ---------------------------------------------------------------------------
# Contest
# ---------------------------------------------------------------------------

CIVIC_CONTEST_DETAIL_SQL = """
    SELECT
        id,
        name,
        election_date,
        election_type,
        office_id,
        electoral_division_id,
        number_of_seats,
        filing_deadline,
        is_partisan,
        candidate_list_incomplete
    FROM civic.contest
    WHERE id = %s
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
