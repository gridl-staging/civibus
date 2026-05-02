from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

_ACTIVE_SOURCE_RECORD_SNAPSHOT_CTE = """
    WITH active_source_records AS (
        SELECT
            sr.data_source_id,
            sr.id,
            sr.source_record_key,
            sr.source_url,
            sr.pull_date
        FROM core.source_record sr
        WHERE sr.superseded_by IS NULL
    ),
    active_source_record_snapshot AS (
        SELECT DISTINCT ON (sr.data_source_id)
            sr.data_source_id,
            sr.id AS latest_source_record_id,
            sr.source_record_key AS latest_source_record_key,
            sr.source_url AS latest_source_record_url,
            sr.pull_date AS latest_source_pull_date
        FROM active_source_records sr
        ORDER BY sr.data_source_id, sr.pull_date DESC, sr.id ASC
    )
"""

_DATA_SOURCES_METADATA_SQL = f"""
    {_ACTIVE_SOURCE_RECORD_SNAPSHOT_CTE}
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
        snapshot.latest_source_record_id,
        snapshot.latest_source_record_key,
        snapshot.latest_source_record_url,
        snapshot.latest_source_pull_date
    FROM core.data_source ds
    LEFT JOIN active_source_record_snapshot snapshot
      ON snapshot.data_source_id = ds.id
    ORDER BY ds.domain, ds.jurisdiction NULLS LAST, ds.name, ds.id
"""

_COVERAGE_REGISTRY_SQL = f"""
    {_ACTIVE_SOURCE_RECORD_SNAPSHOT_CTE},
    runtime_evidence_source_records AS (
        SELECT DISTINCT entity_source.source_record_id
        FROM core.entity_source entity_source

        UNION

        SELECT DISTINCT transaction.source_record_id
        FROM cf.transaction transaction
        WHERE transaction.source_record_id IS NOT NULL

        UNION

        SELECT DISTINCT filing.source_record_id
        FROM cf.filing filing
        WHERE filing.source_record_id IS NOT NULL

        UNION

        SELECT DISTINCT committee.source_record_id
        FROM cf.committee committee
        WHERE committee.source_record_id IS NOT NULL

        UNION

        SELECT DISTINCT candidate.source_record_id
        FROM cf.candidate candidate
        WHERE candidate.source_record_id IS NOT NULL

        UNION

        SELECT DISTINCT candidate_committee_link.source_record_id
        FROM cf.candidate_committee_link candidate_committee_link
        WHERE candidate_committee_link.source_record_id IS NOT NULL
    ),
    runtime_source_record_summary AS (
        SELECT
            active_record.data_source_id,
            MAX(active_record.pull_date) AS latest_source_pull_date
        FROM active_source_records active_record
        JOIN runtime_evidence_source_records runtime_evidence
          ON runtime_evidence.source_record_id = active_record.id
        GROUP BY active_record.data_source_id
    )
    SELECT
        ds.domain,
        ds.jurisdiction,
        COUNT(ds.id)::integer AS data_source_count,
        MAX(ds.last_pull_at) AS latest_data_source_pull_at,
        MAX(runtime.latest_source_pull_date) AS latest_source_pull_date
    FROM core.data_source ds
    JOIN runtime_source_record_summary runtime
      ON runtime.data_source_id = ds.id
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
