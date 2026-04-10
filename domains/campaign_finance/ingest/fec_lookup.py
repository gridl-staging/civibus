from __future__ import annotations

from uuid import UUID

import psycopg


def find_committee_id_by_fec_id(conn: psycopg.Connection, fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM cf.committee WHERE fec_committee_id = %s LIMIT 1", (fec_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def find_candidate_id_by_fec_id(conn: psycopg.Connection, fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM cf.candidate WHERE fec_candidate_id = %s LIMIT 1", (fec_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


__all__ = [
    "find_committee_id_by_fec_id",
    "find_candidate_id_by_fec_id",
]
