"""Shared query utilities, provenance fetchers, and SQL building blocks."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

# ---------------------------------------------------------------------------
# Slug normalization
# ---------------------------------------------------------------------------

_SLUG_NORMALIZE_EXPR = "btrim(lower(regexp_replace({value}, '[^a-zA-Z0-9]+', '-', 'g')), '-')"

# ---------------------------------------------------------------------------
# Provenance SQL
# ---------------------------------------------------------------------------

_ENTITY_PROVENANCE_SOURCE_IDS_SQL = """
    SELECT source_record_id
    FROM core.entity_source
    WHERE entity_type = %s
      AND entity_id = %s
"""

_CAMPAIGN_FINANCE_PROVENANCE_SOURCE_IDS_SQL = """
    SELECT %s::uuid AS source_record_id
    WHERE %s::uuid IS NOT NULL

    UNION

    SELECT source_record_id
    FROM core.entity_source
    WHERE entity_type = %s
      AND entity_id = %s
"""

_CAMPAIGN_FINANCE_BATCH_PROVENANCE_SQL = """
    WITH requests AS (
        SELECT *
        FROM unnest(%s::uuid[], %s::uuid[]) AS request(canonical_entity_id, row_source_record_id)
    ),
    source_ids AS (
        SELECT
            canonical_entity_id,
            row_source_record_id AS source_record_id
        FROM requests
        WHERE row_source_record_id IS NOT NULL

        UNION

        SELECT
            request.canonical_entity_id,
            entity_source.source_record_id
        FROM requests request
        JOIN core.entity_source entity_source
          ON entity_source.entity_type = %s
         AND entity_source.entity_id = request.canonical_entity_id
        WHERE request.canonical_entity_id IS NOT NULL
    ),
    dedup_source_ids AS (
        SELECT DISTINCT
            canonical_entity_id,
            source_record_id
        FROM source_ids
        WHERE source_record_id IS NOT NULL
    )
    SELECT
        ids.canonical_entity_id,
        ds.domain AS domain,
        ds.jurisdiction AS jurisdiction,
        ds.name AS data_source_name,
        ds.source_url AS data_source_url,
        sr.source_record_key AS source_record_key,
        sr.source_url AS record_url,
        sr.pull_date AS pull_date
    FROM dedup_source_ids ids
    JOIN core.source_record sr
      ON sr.id = ids.source_record_id
    JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    ORDER BY ids.canonical_entity_id, sr.pull_date DESC, sr.id ASC
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MONEY_SCALE = Decimal("0.00")

# ---------------------------------------------------------------------------
# Query-building helpers
# ---------------------------------------------------------------------------


def _build_ilike_contains_pattern(search_term: str) -> str:
    escaped_term = search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped_term}%"


def _build_optional_where_sql(
    filter_values: Sequence[tuple[object | None, str]],
) -> tuple[str, list[object]]:
    where_clauses = ["TRUE"]
    query_params: list[object] = []
    for value, clause in filter_values:
        if value is None:
            continue
        where_clauses.append(clause)
        query_params.append(value)
    return " AND ".join(where_clauses), query_params


def _fetch_filtered_rows(
    conn: psycopg.Connection,
    *,
    sql_template: str,
    filter_values: Sequence[tuple[object | None, str]],
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where_sql, query_params = _build_optional_where_sql(filter_values)
    query_params.extend([limit, offset])
    query = sql_template.format(where_sql=where_sql)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, query_params)
        return list(cursor.fetchall())


def fetch_one_row(
    conn: psycopg.Connection,
    *,
    query: str,
    row_id: UUID,
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, (row_id,))
        return cursor.fetchone()


def _build_paginated_response(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Build a pagination envelope from rows fetched with LIMIT+1 strategy."""
    has_next = len(rows) > limit
    if has_next:
        rows = rows[:limit]
    return {"items": rows, "has_next": has_next, "offset": offset, "limit": limit}


# ---------------------------------------------------------------------------
# Provenance fetchers
# ---------------------------------------------------------------------------


def _fetch_provenance_rows(
    conn: psycopg.Connection,
    *,
    source_ids_sql: str,
    query_params: Sequence[object],
) -> list[dict[str, Any]]:
    """Fetch provenance source rows by joining source IDs to data sources."""
    query = f"""
        WITH source_ids AS (
            {source_ids_sql}
        ),
        dedup_source_ids AS (
            SELECT DISTINCT source_record_id
            FROM source_ids
            WHERE source_record_id IS NOT NULL
        )
        SELECT
            ds.domain AS domain,
            ds.jurisdiction AS jurisdiction,
            ds.name AS data_source_name,
            ds.source_url AS data_source_url,
            sr.source_record_key AS source_record_key,
            sr.source_url AS record_url,
            sr.pull_date AS pull_date
        FROM dedup_source_ids ids
        JOIN core.source_record sr
          ON sr.id = ids.source_record_id
        JOIN core.data_source ds
          ON ds.id = sr.data_source_id
        ORDER BY sr.pull_date DESC, sr.id ASC
    """

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, query_params)
        return list(cursor.fetchall())


def fetch_entity_provenance(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
) -> list[dict[str, Any]]:
    return _fetch_provenance_rows(
        conn,
        source_ids_sql=_ENTITY_PROVENANCE_SOURCE_IDS_SQL,
        query_params=(entity_type, entity_id),
    )


def fetch_campaign_finance_provenance(
    conn: psycopg.Connection,
    *,
    row_source_record_id: UUID | None,
    canonical_entity_type: str,
    canonical_entity_id: UUID | None,
) -> list[dict[str, Any]]:
    """Fetch provenance for a campaign-finance record with optional entity linkage."""
    return _fetch_provenance_rows(
        conn,
        source_ids_sql=_CAMPAIGN_FINANCE_PROVENANCE_SOURCE_IDS_SQL,
        query_params=(
            row_source_record_id,
            row_source_record_id,
            canonical_entity_type,
            canonical_entity_id,
        ),
    )


def fetch_campaign_finance_provenance_batch(
    conn: psycopg.Connection,
    *,
    provenance_requests: Sequence[tuple[UUID, UUID | None]],
    canonical_entity_type: str,
) -> dict[UUID, list[dict[str, Any]]]:
    """Fetch campaign-finance provenance for many canonical entities."""
    if not provenance_requests:
        return {}

    canonical_entity_ids = [canonical_entity_id for canonical_entity_id, _row_source_id in provenance_requests]
    row_source_record_ids = [row_source_id for _canonical_entity_id, row_source_id in provenance_requests]
    provenance_by_entity = {canonical_entity_id: [] for canonical_entity_id in canonical_entity_ids}
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CAMPAIGN_FINANCE_BATCH_PROVENANCE_SQL,
            (canonical_entity_ids, row_source_record_ids, canonical_entity_type),
        )
        for row in cursor.fetchall():
            canonical_entity_id = row.pop("canonical_entity_id")
            provenance_by_entity.setdefault(canonical_entity_id, []).append(row)
    return provenance_by_entity
