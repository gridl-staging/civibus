"""Search SQL constants and database fetchers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from api.models.search import SearchParams
from api.queries._common import _build_ilike_contains_pattern

_SEARCH_TRIGRAM_MIN_SIMILARITY = 0.3


def _build_ranked_entity_search_sql(
    *,
    entity_type: str,
    table_name: str,
    table_alias: str,
    name_column: str,
) -> str:
    """Build a SQL fragment that selects and ranks entities by name similarity.

    Emits entity_type, entity_id, name, contains_match, and similarity_score
    columns. Filters via ILIKE pattern or trigram similarity >= threshold.
    """
    return f"""
        SELECT
            '{entity_type}'::text AS entity_type,
            {table_alias}.id AS entity_id,
            {table_alias}.{name_column} AS name,
            ({table_alias}.{name_column} ILIKE params.like_pattern ESCAPE '\\') AS contains_match,
            similarity({table_alias}.{name_column}, params.query_text) AS similarity_score
        FROM {table_name} {table_alias}
        CROSS JOIN search_params params
        WHERE (
            {table_alias}.{name_column} ILIKE params.like_pattern ESCAPE '\\'
            OR similarity({table_alias}.{name_column}, params.query_text) >= params.min_similarity
        )
    """


def _build_search_sql(entity_rows_sql: str) -> str:
    """Build a complete search query that orders results by match type then similarity."""
    return f"""
        WITH search_params AS (
            SELECT
                %s::text AS query_text,
                %s::text AS like_pattern,
                %s::real AS min_similarity
        ),
        ranked_results AS (
            {entity_rows_sql}
        )
        SELECT
            ranked_results.entity_type AS entity_type,
            ranked_results.entity_id AS entity_id,
            ranked_results.name AS name
        FROM ranked_results
        ORDER BY
            ranked_results.contains_match DESC,
            CASE WHEN ranked_results.contains_match THEN 1.0 ELSE ranked_results.similarity_score END DESC,
            ranked_results.name ASC,
            ranked_results.entity_id ASC
        LIMIT %s
        OFFSET %s
    """


_SEARCH_PERSON_ROWS_SQL = _build_ranked_entity_search_sql(
    entity_type="person",
    table_name="core.person",
    table_alias="p",
    name_column="canonical_name",
)
_SEARCH_ORG_ROWS_SQL = _build_ranked_entity_search_sql(
    entity_type="org",
    table_name="core.organization",
    table_alias="o",
    name_column="canonical_name",
)
_SEARCH_COMMITTEE_ROWS_SQL = _build_ranked_entity_search_sql(
    entity_type="committee",
    table_name="cf.committee",
    table_alias="c",
    name_column="name",
)
_SEARCH_OFFICE_ROWS_SQL = _build_ranked_entity_search_sql(
    entity_type="office",
    table_name="civic.office",
    table_alias="off",
    name_column="name",
)

# Candidate search requires a JOIN: candidacy → person for the searchable name.
# The entity_id returned is the person_id (the entity the user cares about).
_SEARCH_CANDIDATE_ROWS_SQL = """
    SELECT
        'candidate'::text AS entity_type,
        p.id AS entity_id,
        p.canonical_name AS name,
        (p.canonical_name ILIKE params.like_pattern ESCAPE '\\') AS contains_match,
        similarity(p.canonical_name, params.query_text) AS similarity_score
    FROM civic.candidacy cand
    JOIN core.person p ON cand.person_id = p.id
    CROSS JOIN search_params params
    WHERE (
        p.canonical_name ILIKE params.like_pattern ESCAPE '\\'
        OR similarity(p.canonical_name, params.query_text) >= params.min_similarity
    )
"""

_SEARCH_ALL_ENTITIES_SQL = _build_search_sql(
    f"""
    {_SEARCH_PERSON_ROWS_SQL}
    UNION ALL
    {_SEARCH_ORG_ROWS_SQL}
    UNION ALL
    {_SEARCH_COMMITTEE_ROWS_SQL}
    UNION ALL
    {_SEARCH_OFFICE_ROWS_SQL}
    UNION ALL
    {_SEARCH_CANDIDATE_ROWS_SQL}
    """.strip()
)

_SEARCH_SINGLE_ENTITY_SQL: dict[str, str] = {
    "person": _build_search_sql(_SEARCH_PERSON_ROWS_SQL),
    "org": _build_search_sql(_SEARCH_ORG_ROWS_SQL),
    "committee": _build_search_sql(_SEARCH_COMMITTEE_ROWS_SQL),
    "candidate": _build_search_sql(_SEARCH_CANDIDATE_ROWS_SQL),
    "office": _build_search_sql(_SEARCH_OFFICE_ROWS_SQL),
}

# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


def fetch_search_results(conn: psycopg.Connection, params: SearchParams) -> list[dict[str, Any]]:
    """Fetch ranked search results across entity types."""
    like_pattern = _build_ilike_contains_pattern(params.q)
    shared_params: Sequence[object] = (
        params.q,
        like_pattern,
        _SEARCH_TRIGRAM_MIN_SIMILARITY,
        params.limit,
        params.offset,
    )

    if params.entity_type is None:
        query = _SEARCH_ALL_ENTITIES_SQL
        query_params = shared_params
    else:
        query = _SEARCH_SINGLE_ENTITY_SQL[params.entity_type]
        query_params = shared_params

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, query_params)
        return list(cursor.fetchall())
