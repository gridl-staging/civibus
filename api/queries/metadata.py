from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

# Shared column projection so the full snapshot and the bounded public-federal
# snapshot cannot drift apart or grow a second freshness computation.
_DATA_SOURCES_METADATA_COLUMNS = """
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
"""

_DATA_SOURCES_METADATA_ORDER_BY = "ORDER BY ds.domain, ds.jurisdiction NULLS LAST, ds.name, ds.id"

_DATA_SOURCES_METADATA_SQL = f"""
    SELECT{_DATA_SOURCES_METADATA_COLUMNS}
    FROM core.data_source ds
    {_DATA_SOURCES_METADATA_ORDER_BY}
"""

# Public-federal scope: campaign-finance ``federal/fec`` plus civics
# ``federal/officeholder/%``. Any other jurisdiction stays off the authless
# surface. Executed without bound parameters, so the ``%`` in the LIKE pattern
# is a literal SQL wildcard, not a psycopg placeholder.
_PUBLIC_FEDERAL_DATA_SOURCES_SQL = f"""
    SELECT{_DATA_SOURCES_METADATA_COLUMNS}
    FROM core.data_source ds
    WHERE (ds.domain = 'campaign_finance' AND ds.jurisdiction = 'federal/fec')
       OR (ds.domain = 'civics' AND ds.jurisdiction LIKE 'federal/officeholder/%')
    {_DATA_SOURCES_METADATA_ORDER_BY}
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


def fetch_public_federal_data_sources(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Return the bounded federal-first ``core.data_source`` snapshot.

    Scoped to the campaign-finance FEC source and civics federal officeholder
    sources — the only data sources the authless public surface discloses.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PUBLIC_FEDERAL_DATA_SOURCES_SQL)
        return list(cursor.fetchall())


def fetch_runtime_coverage_registry(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_COVERAGE_REGISTRY_SQL)
        return list(cursor.fetchall())
