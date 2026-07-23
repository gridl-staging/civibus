from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

_DATA_SOURCES_METADATA_SQL = """
    SELECT
        ds.id AS data_source_id,
        ds.domain,
        ds.jurisdiction,
        ds.name,
        ds.source_url,
        ds.update_frequency,
        ds.last_pull_at,
        ds.last_pull_status,
        ds.record_count,
        NULL::uuid AS latest_source_record_id,
        NULL::text AS latest_source_record_key,
        NULL::text AS latest_source_record_url,
        ds.last_pull_at AS latest_source_pull_date
    FROM core.data_source ds
    ORDER BY ds.domain, ds.jurisdiction NULLS LAST, ds.name, ds.id
"""

_COVERAGE_REGISTRY_SQL = """
    SELECT
        ds.domain,
        ds.jurisdiction,
        COUNT(ds.id)::integer AS data_source_count,
        MAX(ds.last_pull_at) AS latest_data_source_pull_at,
        MAX(ds.last_pull_at) AS latest_source_pull_date
    FROM core.data_source ds
    WHERE COALESCE(ds.record_count, 0) > 0
    GROUP BY ds.domain, ds.jurisdiction
    ORDER BY ds.domain, ds.jurisdiction NULLS LAST
"""


def fetch_data_sources_metadata(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_DATA_SOURCES_METADATA_SQL)
        return list(cursor.fetchall())


def fetch_runtime_coverage_registry(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_COVERAGE_REGISTRY_SQL)
        return list(cursor.fetchall())
