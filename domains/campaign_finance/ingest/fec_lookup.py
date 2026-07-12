"""Lookup helpers for FEC committee and candidate identifiers."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import psycopg

from core.people.federal_officeholders import active_federal_candidate_scope_cte
from domains.campaign_finance.ingest.text_utils import normalize_optional_text


def find_committee_id_by_fec_id(conn: psycopg.Connection, fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM cf.committee WHERE fec_committee_id = %s LIMIT 1", (fec_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def find_committee_ids_by_fec_ids(
    conn: psycopg.Connection,
    fec_ids: Iterable[str],
) -> dict[str, UUID]:
    """Resolve committee UUIDs for unique, non-empty FEC committee IDs."""
    committee_fec_ids: list[str] = []
    seen_committee_fec_ids: set[str] = set()
    for fec_id in fec_ids:
        normalized_fec_id = normalize_optional_text(fec_id)
        if normalized_fec_id is None or normalized_fec_id in seen_committee_fec_ids:
            continue
        seen_committee_fec_ids.add(normalized_fec_id)
        committee_fec_ids.append(normalized_fec_id)
    if not committee_fec_ids:
        return {}

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT fec_committee_id, id
            FROM cf.committee
            WHERE fec_committee_id = ANY(%s)
            """,
            (committee_fec_ids,),
        )
        rows: Iterable[tuple[str, UUID]] = cursor.fetchall()
    return {fec_committee_id: committee_id for fec_committee_id, committee_id in rows}


def find_candidate_id_by_fec_id(conn: psycopg.Connection, fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM cf.candidate WHERE fec_candidate_id = %s LIMIT 1", (fec_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def current_federal_officeholder_committee_fec_ids(conn: psycopg.Connection) -> frozenset[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            WITH {active_federal_candidate_scope_cte()},
            linked_committees AS (
                SELECT cm.fec_committee_id
                FROM active_federal_candidates active
                JOIN cf.candidate_committee_link ccl ON ccl.candidate_id = active.id
                JOIN cf.committee cm ON cm.id = ccl.committee_id
                WHERE ccl.designation IN ('P', 'A')
                  AND cm.committee_designation IS DISTINCT FROM 'J'
            ),
            principal_committees AS (
                SELECT cm.fec_committee_id
                FROM active_federal_candidates active
                JOIN cf.committee cm ON cm.id = active.principal_committee_id
                WHERE cm.committee_designation IS DISTINCT FROM 'J'
            )
            SELECT DISTINCT fec_committee_id
            FROM (
                SELECT fec_committee_id FROM linked_committees
                UNION ALL
                SELECT fec_committee_id FROM principal_committees
            ) committees
            WHERE fec_committee_id IS NOT NULL
            """,
        )
        rows: Iterable[tuple[str]] = cursor.fetchall()
    return frozenset(row[0] for row in rows if row[0])


__all__ = [
    "current_federal_officeholder_committee_fec_ids",
    "find_committee_id_by_fec_id",
    "find_committee_ids_by_fec_ids",
    "find_candidate_id_by_fec_id",
]
