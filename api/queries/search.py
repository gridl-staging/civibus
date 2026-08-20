"""Search SQL constants and database fetchers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

import psycopg
from psycopg.rows import dict_row

from api.models.search import SearchParams
from api.queries._common import _build_ilike_contains_pattern
from api.queries.civics import _current_federal_officeholder_search_rows_sql, _current_office_selection_sql

_SEARCH_TRIGRAM_MIN_SIMILARITY = 0.3


class ContextExprs(NamedTuple):
    """SQL expressions for optional context columns in search result projection."""

    state: str = "NULL::text"
    party: str = "NULL::text"
    office_name: str = "NULL::text"
    committee_type: str = "NULL::text"


def _build_ranked_entity_search_sql(
    *,
    entity_type: str,
    table_name: str,
    table_alias: str,
    name_column: str,
    context: ContextExprs = ContextExprs(),
) -> str:
    """Build a SQL fragment that selects and ranks entities by name similarity.

    Emits entity_type, entity_id, name, optional context columns, and ranking
    columns. Filters via ILIKE pattern or trigram similarity >= threshold.
    """
    return f"""
        SELECT
            '{entity_type}'::text AS entity_type,
            {table_alias}.id AS entity_id,
            {table_alias}.{name_column} AS name,
            {context.state} AS state,
            {context.party} AS party,
            {context.office_name} AS office_name,
            {context.committee_type} AS committee_type,
            NULL::numeric AS total_raised,
            FALSE AS is_current_federal_officeholder,
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
            ranked_results.name AS name,
            ranked_results.state AS state,
            ranked_results.party AS party,
            ranked_results.office_name AS office_name,
            ranked_results.committee_type AS committee_type,
            ranked_results.total_raised AS total_raised
        FROM ranked_results
        ORDER BY
            ranked_results.contains_match DESC,
            CASE WHEN ranked_results.contains_match THEN 1.0 ELSE ranked_results.similarity_score END DESC,
            ranked_results.is_current_federal_officeholder DESC,
            ranked_results.name ASC,
            ranked_results.entity_id ASC
        LIMIT %s
        OFFSET %s
    """


_CURRENT_FEDERAL_OFFICEHOLDER_SEARCH_ROWS_SQL = _current_federal_officeholder_search_rows_sql()
_CURRENT_OFFICE_SEARCH_SQL = _current_office_selection_sql("p.id")

# One owner for the candidacy → contest → office context chain. Two surfaces read
# a candidate's state / party / sought-office through it: the explicit
# `entity_type=candidate` lane, and the person lane's context fallback below.
# Keeping a single FROM clause and a single ContextExprs stops the two from
# drifting apart — a person searched with and without the filter must describe
# the same candidacy the same way.
_CANDIDACY_CONTEXT_JOIN_SQL = """
    FROM civic.candidacy cand
    LEFT JOIN civic.contest cont ON cand.contest_id = cont.id
    LEFT JOIN civic.office off ON cont.office_id = off.id
"""
_CANDIDACY_CONTEXT = ContextExprs(state="off.state", party="cand.party", office_name="off.name")

# Best-candidacy context for one person, correlated on the outer `p` alias.
# A person can hold several candidacies (re-election, a chamber switch, a primary
# plus a general). The most recent contest wins, because that is the race a
# searcher is most likely looking for; `cand.id` breaks ties so the projection
# stays deterministic under LIMIT/OFFSET pagination.
_SEARCH_PERSON_CANDIDACY_CONTEXT_SQL = f"""
    SELECT
        {_CANDIDACY_CONTEXT.state} AS state,
        {_CANDIDACY_CONTEXT.party} AS party,
        {_CANDIDACY_CONTEXT.office_name} AS office_name
    {_CANDIDACY_CONTEXT_JOIN_SQL}
    WHERE cand.person_id = p.id
    ORDER BY cont.election_date DESC NULLS LAST, cand.id ASC
    LIMIT 1
"""

# The person lane is the canonical lane for a human: it emits exactly one row per
# core.person, and it is the only lane that carries
# `is_current_federal_officeholder`, the ranking signal that floats a sitting
# member above an identically named challenger. Context is layered
# officeholder → current office → best candidacy, i.e. office actually held wins
# over office merely sought. The candidacy fallback is what lets the union drop
# the separate candidate lane without losing anything a user could read; see the
# comment on _SEARCH_ALL_ENTITIES_SQL.
_SEARCH_PERSON_ROWS_SQL = f"""
    SELECT
        'person'::text AS entity_type,
        p.id AS entity_id,
        p.canonical_name AS name,
        COALESCE(officeholder.search_geography_token, current_office.state, candidacy.state) AS state,
        COALESCE(officeholder.party, candidacy.party) AS party,
        COALESCE(
            officeholder.short_office_label,
            current_office.office_name,
            candidacy.office_name
        ) AS office_name,
        NULL::text AS committee_type,
        NULL::numeric AS total_raised,
        (officeholder.person_id IS NOT NULL) AS is_current_federal_officeholder,
        (p.canonical_name ILIKE params.like_pattern ESCAPE '\\') AS contains_match,
        similarity(p.canonical_name, params.query_text) AS similarity_score
    FROM core.person p
    LEFT JOIN (
        {_CURRENT_FEDERAL_OFFICEHOLDER_SEARCH_ROWS_SQL}
    ) officeholder ON officeholder.person_id = p.id
    LEFT JOIN LATERAL (
        {_CURRENT_OFFICE_SEARCH_SQL}
    ) current_office ON TRUE
    LEFT JOIN LATERAL (
        {_SEARCH_PERSON_CANDIDACY_CONTEXT_SQL}
    ) candidacy ON TRUE
    CROSS JOIN search_params params
    WHERE (
        p.canonical_name ILIKE params.like_pattern ESCAPE '\\'
        OR similarity(p.canonical_name, params.query_text) >= params.min_similarity
    )
"""
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
    context=ContextExprs(state="c.state", party="c.party", committee_type="c.committee_type"),
)
_SEARCH_OFFICE_ROWS_SQL = _build_ranked_entity_search_sql(
    entity_type="office",
    table_name="civic.office",
    table_alias="off",
    name_column="name",
    context=ContextExprs(state="off.state"),
)

# Candidate search requires a JOIN: candidacy → person for the searchable name.
# The entity_id returned is the person_id (the entity the user cares about).
#
# This lane serves `entity_type=candidate` ONLY. It is deliberately absent from
# the cross-entity union — see the comment on _SEARCH_ALL_ENTITIES_SQL. It emits
# one row per candidacy, so a person with three candidacies yields three rows;
# under an explicit candidate filter that is the documented contract ("which
# races is this person in"), but in the union it was pure duplication.
_SEARCH_CANDIDATE_ROWS_SQL = f"""
    SELECT
        'candidate'::text AS entity_type,
        p.id AS entity_id,
        p.canonical_name AS name,
        {_CANDIDACY_CONTEXT.state} AS state,
        {_CANDIDACY_CONTEXT.party} AS party,
        {_CANDIDACY_CONTEXT.office_name} AS office_name,
        NULL::text AS committee_type,
        NULL::numeric AS total_raised,
        FALSE AS is_current_federal_officeholder,
        (p.canonical_name ILIKE params.like_pattern ESCAPE '\\') AS contains_match,
        similarity(p.canonical_name, params.query_text) AS similarity_score
    {_CANDIDACY_CONTEXT_JOIN_SQL}
    JOIN core.person p ON cand.person_id = p.id
    CROSS JOIN search_params params
    WHERE (
        p.canonical_name ILIKE params.like_pattern ESCAPE '\\'
        OR similarity(p.canonical_name, params.query_text) >= params.min_similarity
    )
"""

# Contest search supports contest-name matching and office-name matching while
# still returning contest identifiers and labels for result routing/display.
_SEARCH_CONTEST_ROWS_SQL = """
    SELECT
        'contest'::text AS entity_type,
        cont.id AS entity_id,
        cont.name AS name,
        off.state AS state,
        NULL::text AS party,
        off.name AS office_name,
        NULL::text AS committee_type,
        NULL::numeric AS total_raised,
        FALSE AS is_current_federal_officeholder,
        (
            cont.name ILIKE params.like_pattern ESCAPE '\\'
            OR off.name ILIKE params.like_pattern ESCAPE '\\'
        ) AS contains_match,
        GREATEST(
            similarity(cont.name, params.query_text),
            similarity(off.name, params.query_text)
        ) AS similarity_score
    FROM civic.contest cont
    JOIN civic.office off ON cont.office_id = off.id
    CROSS JOIN search_params params
    WHERE (
        cont.name ILIKE params.like_pattern ESCAPE '\\'
        OR off.name ILIKE params.like_pattern ESCAPE '\\'
        OR similarity(cont.name, params.query_text) >= params.min_similarity
        OR similarity(off.name, params.query_text) >= params.min_similarity
    )
"""

# The cross-entity union deliberately omits the candidate lane (civibus-9hv).
#
# Why: _SEARCH_CANDIDATE_ROWS_SQL projects `p.id AS entity_id` — the very same
# identifier the person lane projects — and the frontend routes both `person` and
# `candidate` rows to `/person/<id>` (SEARCH_ROUTE_SEGMENT_BY_ENTITY_TYPE in
# web/src/lib/search/contract.ts). The two lanes also share a byte-identical name
# predicate over `p.canonical_name`, so *every* candidate row the union could
# produce was provably a second copy — a third and fourth, for a person with
# several candidacies — of a person row already in the result set, differing only
# in badge. Measured on production 2026-08-19: `?q=ossoff` returned three rows for
# one senator, two of them with a byte-identical href.
#
# Which lane wins, and why the person lane: it is the canonical lane for the
# destination (a `/person/` page is a person), it exists for every human rather
# than only for those carrying a civic.candidacy (so the badge cannot flip as
# candidacy data loads), and it is the sole carrier of
# `is_current_federal_officeholder`, which the ORDER BY uses to float a sitting
# member above an identically named challenger — a signal the candidate lane
# hardcodes to FALSE. Nothing is lost by dropping the candidate row: its only
# distinct payload was context columns, and the person lane now COALESCEs those
# in from the same candidacy join.
#
# This is not a dedupe-by-href filter. Removing the arm is cheaper (one fewer
# scan of civic.candidacy per query) and it keeps LIMIT/OFFSET honest, because a
# post-hoc DISTINCT would shrink pages after the window had already been taken.
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
    {_SEARCH_CONTEST_ROWS_SQL}
    """.strip()
)

_SEARCH_SINGLE_ENTITY_SQL: dict[str, str] = {
    "person": _build_search_sql(_SEARCH_PERSON_ROWS_SQL),
    "org": _build_search_sql(_SEARCH_ORG_ROWS_SQL),
    "committee": _build_search_sql(_SEARCH_COMMITTEE_ROWS_SQL),
    "candidate": _build_search_sql(_SEARCH_CANDIDATE_ROWS_SQL),
    "office": _build_search_sql(_SEARCH_OFFICE_ROWS_SQL),
    "contest": _build_search_sql(_SEARCH_CONTEST_ROWS_SQL),
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
