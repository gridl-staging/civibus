"""
Stub summary for MAR18_cross_domain_er_and_property_graph/civibus_dev/domains/property/ingest/ingest_test_helpers.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row

DURHAM_EXPECTED_OWNER_ROWS = frozenset(
    {
        ("100000001", "person", "SMITH JOHN"),
        ("100000002", "person", "DOE JANE"),
        ("100000003", "organization", "DUKE UNIVERSITY"),
    }
)


def fixture_reids(records: Sequence[dict[str, object]]) -> list[str]:
    return [str(record["reid"]) for record in records]


def fixture_row_counts(
    conn: psycopg.Connection,
    data_source_id: object,
    reids: Sequence[str],
) -> dict[str, int]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::int AS count
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
            """,
            (data_source_id, reids),
        )
        source_record_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*)::int AS count
            FROM prop.parcel
            WHERE reid = ANY(%s)
            """,
            (reids,),
        )
        parcel_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*)::int AS count
            FROM prop.assessment a
            JOIN prop.parcel p ON p.id = a.parcel_id
            WHERE p.reid = ANY(%s)
            """,
            (reids,),
        )
        assessment_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*)::int AS count
            FROM prop.ownership o
            JOIN prop.parcel p ON p.id = o.parcel_id
            WHERE p.reid = ANY(%s)
            """,
            (reids,),
        )
        ownership_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*)::int AS count
            FROM core.entity_source es
            WHERE es.source_record_id IN (
                SELECT id
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key = ANY(%s)
            )
            """,
            (data_source_id, reids),
        )
        entity_source_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*)::int AS count
            FROM core.entity_address ea
            WHERE ea.source_record_id IN (
                SELECT id
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key = ANY(%s)
            )
            """,
            (data_source_id, reids),
        )
        entity_address_row = cursor.fetchone()

    assert source_record_row is not None
    assert parcel_row is not None
    assert assessment_row is not None
    assert ownership_row is not None
    assert entity_source_row is not None
    assert entity_address_row is not None

    return {
        "core.source_record": source_record_row["count"],
        "prop.parcel": parcel_row["count"],
        "prop.assessment": assessment_row["count"],
        "prop.ownership": ownership_row["count"],
        "core.entity_source": entity_source_row["count"],
        "core.entity_address": entity_address_row["count"],
    }


def owner_rows_from_er_views_by_source_record_keys(
    conn: psycopg.Connection,
    data_source_id: object,
    source_record_keys: Sequence[str],
) -> list[dict[str, object]]:
    """Fetch owner-linked ER view rows for one source's active source_record keys."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            WITH scoped_source_records AS (
                SELECT id, source_record_key
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key = ANY(%s)
                  AND superseded_by IS NULL
            )
            SELECT
                sr.source_record_key,
                'person'::text AS entity_type,
                pev.id AS entity_id,
                pev.canonical_name,
                SUBSTRING(pev.identifier_key FROM '^owner_name_as_filed:(.*)$') AS owner_name_as_filed
            FROM scoped_source_records sr
            JOIN core.entity_source es ON es.source_record_id = sr.id
            JOIN core.person_er_view pev ON es.entity_type = 'person' AND es.entity_id = pev.id
            WHERE es.extraction_role = 'owner'
              AND pev.identifier_key LIKE 'owner_name_as_filed:%%'

            UNION ALL

            SELECT
                sr.source_record_key,
                'organization'::text AS entity_type,
                oev.id AS entity_id,
                oev.canonical_name,
                oev.identifiers->>'owner_name_as_filed' AS owner_name_as_filed
            FROM scoped_source_records sr
            JOIN core.entity_source es ON es.source_record_id = sr.id
            JOIN core.organization_er_view oev ON es.entity_type = 'organization' AND es.entity_id = oev.id
            WHERE es.extraction_role = 'owner'
              AND oev.identifiers ? 'owner_name_as_filed'
            ORDER BY source_record_key, entity_type, owner_name_as_filed
            """,
            (data_source_id, source_record_keys),
        )
        rows = cursor.fetchall()

    return list(rows)
