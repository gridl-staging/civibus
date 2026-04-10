"""Civic domain AGE graph edge loaders.

Materializes HOLDS, RUNS_IN, CANDIDACY_OF, and REPRESENTS edges from the
civic schema relational tables into the Apache AGE graph.
"""

from __future__ import annotations

from uuid import UUID

import psycopg

from core.graph.loader import (
    _fetch_dict_rows,
    _merge_edge_with_source_record_id,
    _require_nonnegative_limit,
    _serialize_date,
    _serialize_valid_period,
    merge_candidacy_node,
    merge_contest_node,
    merge_electoral_division_node,
    merge_office_node,
    merge_officeholding_node,
    merge_person_node,
)

# ---------------------------------------------------------------------------
# SQL queries — join civic relational tables for edge materialization
# ---------------------------------------------------------------------------

_HOLDS_EDGE_ROWS_QUERY = """
    SELECT
        oh.id AS officeholding_id,
        oh.person_id,
        p.canonical_name AS person_name,
        oh.office_id,
        o.name AS office_name,
        oh.holder_status,
        oh.valid_period,
        oh.source_record_id
    FROM civic.officeholding oh
    JOIN core.person p
      ON p.id = oh.person_id
    JOIN civic.office o
      ON o.id = oh.office_id
    ORDER BY oh.id
    LIMIT %s
"""

_RUNS_IN_EDGE_ROWS_QUERY = """
    SELECT
        ca.id AS candidacy_id,
        ca.person_id,
        p.canonical_name AS person_name,
        ca.contest_id,
        co.name AS contest_name,
        ca.party,
        co.election_date,
        ca.source_record_id
    FROM civic.candidacy ca
    JOIN core.person p
      ON p.id = ca.person_id
    JOIN civic.contest co
      ON co.id = ca.contest_id
    ORDER BY ca.id
    LIMIT %s
"""

_CANDIDACY_OF_EDGE_ROWS_QUERY = """
    SELECT
        ca.id AS candidacy_id,
        ca.person_id,
        p.canonical_name AS person_name,
        ca.source_record_id
    FROM civic.candidacy ca
    JOIN core.person p
      ON p.id = ca.person_id
    ORDER BY ca.id
    LIMIT %s
"""

_REPRESENTS_EDGE_ROWS_QUERY = """
    SELECT
        oh.id AS officeholding_id,
        oh.person_id,
        p.canonical_name AS person_name,
        o.name AS office_name,
        oh.electoral_division_id,
        ed.name AS electoral_division_name,
        oh.holder_status,
        oh.valid_period,
        oh.source_record_id
    FROM civic.officeholding oh
    JOIN core.person p
      ON p.id = oh.person_id
    JOIN civic.office o
      ON o.id = oh.office_id
    JOIN civic.electoral_division ed
      ON ed.id = oh.electoral_division_id
    WHERE oh.electoral_division_id IS NOT NULL
    ORDER BY oh.id
    LIMIT %s
"""


# ---------------------------------------------------------------------------
# Edge loaders
# ---------------------------------------------------------------------------


def _merge_officeholding_subject_node(
    conn: psycopg.Connection,
    *,
    officeholding_id: UUID,
    person_name: str,
    office_name: str,
) -> None:
    merge_officeholding_node(conn, officeholding_id, f"{person_name} holds {office_name}")


def load_holds_edges(conn: psycopg.Connection, *, limit: int) -> int:
    """HOLDS: Person → Office, derived from civic.officeholding."""
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _HOLDS_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        officeholding_id = row.get("officeholding_id")
        person_id = row.get("person_id")
        person_name = row.get("person_name")
        office_id = row.get("office_id")
        office_name = row.get("office_name")
        source_record_id = row.get("source_record_id")

        if not isinstance(officeholding_id, UUID):
            continue
        if not isinstance(person_id, UUID) or not isinstance(person_name, str):
            continue
        if not isinstance(office_id, UUID) or not isinstance(office_name, str):
            continue

        # Always materialize nodes — unsourced rows still need AGE backing
        merge_person_node(conn, person_id, person_name)
        merge_office_node(conn, office_id, office_name)
        _merge_officeholding_subject_node(
            conn,
            officeholding_id=officeholding_id,
            person_name=person_name,
            office_name=office_name,
        )

        # Edge creation requires source_record_id as MERGE key
        if not isinstance(source_record_id, UUID):
            continue

        _merge_edge_with_source_record_id(
            conn,
            source=("Person", str(person_id)),
            target=("Office", str(office_id)),
            edge_type="HOLDS",
            properties={
                "holder_status": row.get("holder_status"),
                "valid_period": _serialize_valid_period(row.get("valid_period")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_runs_in_edges(conn: psycopg.Connection, *, limit: int) -> int:
    """RUNS_IN: Candidacy → Contest, derived from civic.candidacy.contest_id."""
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _RUNS_IN_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        candidacy_id = row.get("candidacy_id")
        person_name = row.get("person_name")
        contest_id = row.get("contest_id")
        contest_name = row.get("contest_name")
        source_record_id = row.get("source_record_id")

        if not isinstance(candidacy_id, UUID) or not isinstance(person_name, str):
            continue
        if not isinstance(contest_id, UUID) or not isinstance(contest_name, str):
            continue

        # Always materialize nodes — unsourced rows still need AGE backing
        merge_candidacy_node(conn, candidacy_id, f"{person_name} for {contest_name}")
        merge_contest_node(conn, contest_id, contest_name)

        # Edge creation requires source_record_id as MERGE key
        if not isinstance(source_record_id, UUID):
            continue

        _merge_edge_with_source_record_id(
            conn,
            source=("Candidacy", str(candidacy_id)),
            target=("Contest", str(contest_id)),
            edge_type="RUNS_IN",
            properties={
                "party": row.get("party"),
                "election_date": _serialize_date(row.get("election_date")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_candidacy_of_edges(conn: psycopg.Connection, *, limit: int) -> int:
    """CANDIDACY_OF: Person → Candidacy, derived from civic.candidacy.person_id."""
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _CANDIDACY_OF_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        candidacy_id = row.get("candidacy_id")
        person_id = row.get("person_id")
        person_name = row.get("person_name")
        source_record_id = row.get("source_record_id")

        if not isinstance(candidacy_id, UUID) or not isinstance(person_id, UUID):
            continue
        if not isinstance(person_name, str):
            continue

        # Always materialize nodes — unsourced rows still need AGE backing
        merge_person_node(conn, person_id, person_name)
        merge_candidacy_node(conn, candidacy_id, f"candidacy-{candidacy_id}")

        # Edge creation requires source_record_id as MERGE key
        if not isinstance(source_record_id, UUID):
            continue

        _merge_edge_with_source_record_id(
            conn,
            source=("Person", str(person_id)),
            target=("Candidacy", str(candidacy_id)),
            edge_type="CANDIDACY_OF",
            properties={
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_represents_edges(conn: psycopg.Connection, *, limit: int) -> int:
    """REPRESENTS: Person → ElectoralDivision, derived from civic.officeholding where division is non-null."""
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _REPRESENTS_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        officeholding_id = row.get("officeholding_id")
        person_id = row.get("person_id")
        person_name = row.get("person_name")
        office_name = row.get("office_name")
        division_id = row.get("electoral_division_id")
        division_name = row.get("electoral_division_name")
        source_record_id = row.get("source_record_id")

        if not isinstance(officeholding_id, UUID):
            continue
        if not isinstance(person_id, UUID) or not isinstance(person_name, str):
            continue
        if not isinstance(office_name, str):
            continue
        if not isinstance(division_id, UUID) or not isinstance(division_name, str):
            continue

        # Always materialize nodes — unsourced rows still need AGE backing
        merge_person_node(conn, person_id, person_name)
        _merge_officeholding_subject_node(
            conn,
            officeholding_id=officeholding_id,
            person_name=person_name,
            office_name=office_name,
        )
        merge_electoral_division_node(conn, division_id, division_name)

        # Edge creation requires source_record_id as MERGE key
        if not isinstance(source_record_id, UUID):
            continue

        _merge_edge_with_source_record_id(
            conn,
            source=("Person", str(person_id)),
            target=("ElectoralDivision", str(division_id)),
            edge_type="REPRESENTS",
            properties={
                "holder_status": row.get("holder_status"),
                "valid_period": _serialize_valid_period(row.get("valid_period")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def load_civic_edges(conn: psycopg.Connection, *, limit: int) -> int:
    """Load all civic domain edges. Returns total edge count."""
    _require_nonnegative_limit(limit)
    return (
        load_holds_edges(conn, limit=limit)
        + load_runs_in_edges(conn, limit=limit)
        + load_candidacy_of_edges(conn, limit=limit)
        + load_represents_edges(conn, limit=limit)
    )
