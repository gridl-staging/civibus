"""Search SQL constants and database fetchers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

import psycopg
from psycopg.rows import dict_row

from api.models.search import SearchParams
from api.queries._common import _build_ilike_contains_pattern
from api.queries.campaign_finance import _CANDIDATE_IDENTITY_IS_SAFE_EXPR
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


# Candidate search reads cf.candidate — the dataset `/candidates` browses
# (civibus-x9d). The pre-fix lane read `civic.candidacy JOIN core.person`, so an
# FEC candidate with no civic candidacy (most of the 30k+ cf.candidate rows) was
# invisible under the explicit filter, and for `ossoff` it returned only the
# unmerged FEC duplicate while hiding the sitting senator.
#
# Design decisions, in order of consequence:
#
# - **Row unit and link target.** One row per cf.candidate record, keyed by
#   `c.id`, which the frontend routes to `/candidate/<uuid>`
#   (SEARCH_ROUTE_SEGMENT_BY_ENTITY_TYPE in web/src/lib/search/contract.ts).
#   That matches the browse list's unit exactly: filtering search to
#   "Candidate" answers "which FEC candidate records match", the same question
#   `/candidates` answers. The candidate detail route already canonicalizes a
#   UUID to its slug URL when one exists, so the UUID href is always durable.
#   A human whose only trace is a civic.candidacy is served by the person lane
#   (union and `entity_type=person`), which carries their candidacy context —
#   they are people, and their record lives on their person page.
#
# - **Identity safety.** `_CANDIDATE_IDENTITY_IS_SAFE_EXPR` is imported from
#   api/queries/campaign_finance.py — the same predicate, same owner, that trims
#   the `/candidates` browse. Search is a browse surface: an address-like FEC
#   source string ("212 N HALF W. JOHN...") must not be promoted into a result
#   card here any more than into a browse row. The expression is prebuilt for
#   alias `c`, which is why this lane aliases cf.candidate as `c`.
#
# - **Context columns.** `office_name` carries the raw FEC office code
#   (H/S/P); the web layer expands it through its existing
#   FEC_CANDIDATE_OFFICE_OPTIONS owner, exactly as it already expands party
#   codes, so no second code→label map exists on the backend. `total_raised`
#   carries the official FEC total (NULL stays NULL — unknown money is never
#   zero), giving same-named candidates a real discriminator in results.
def _build_cf_candidate_rows_sql(*, spine_orphans_only: bool) -> str:
    """Build the cf.candidate search lane.

    ``spine_orphans_only=True`` is the cross-entity union's variant: it keeps
    only rows with no ``person_id``, because a spine-linked candidate's human
    already surfaces through the person lane and a second row for the same
    human is the duplication civibus-9hv removed. The explicit
    ``entity_type=candidate`` filter serves every identity-safe record,
    linked or not — there it is the FEC record itself being asked for.
    """
    spine_scope_sql = "\n          AND c.person_id IS NULL" if spine_orphans_only else ""
    return f"""
        SELECT
            'candidate'::text AS entity_type,
            c.id AS entity_id,
            c.name AS name,
            c.state AS state,
            c.party AS party,
            c.office AS office_name,
            NULL::text AS committee_type,
            c.total_receipts AS total_raised,
            FALSE AS is_current_federal_officeholder,
            (c.name ILIKE params.like_pattern ESCAPE '\\') AS contains_match,
            similarity(c.name, params.query_text) AS similarity_score
        FROM cf.candidate c
        CROSS JOIN search_params params
        WHERE (
            c.name ILIKE params.like_pattern ESCAPE '\\'
            OR similarity(c.name, params.query_text) >= params.min_similarity
        )
          AND {_CANDIDATE_IDENTITY_IS_SAFE_EXPR}{spine_scope_sql}
    """


# No trigram index exists on cf.candidate.name (unlike person/org/committee).
# Deliberate: at federal-first scale (~16-30k rows) the browse list's measured
# seq-scan cost is ~20ms and the identity regex, not the scan, dominates —
# see candidate_list.md -> "Sort index coverage". Revisit past that scale.
_SEARCH_CANDIDATE_ROWS_SQL = _build_cf_candidate_rows_sql(spine_orphans_only=False)
_SEARCH_UNION_CANDIDATE_ROWS_SQL = _build_cf_candidate_rows_sql(spine_orphans_only=True)

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

# The cross-entity union carries the candidate lane in its SPINE-ORPHAN variant
# only (civibus-9hv, then civibus-x9d).
#
# History: the old candidacy-based candidate arm was removed outright by 9hv
# because it projected `p.id AS entity_id` with a name predicate byte-identical
# to the person lane's — every row it emitted was a second copy of a person row
# already in the result set (measured on production 2026-08-19: three rows for
# one senator, two with a byte-identical href). The person lane won because it
# is canonical for the `/person/` destination, exists for every human, and is
# the sole carrier of `is_current_federal_officeholder`, the ORDER BY signal
# that floats a sitting member above a namesake challenger.
#
# The x9d lane is different data: cf.candidate rows, most of which have NO
# core.person row at all. For those spine-orphan records the union previously
# had no lane that could find them — the default search simply missed most of
# the dataset `/candidates` lists. They are new reach, not duplication, so they
# belong here. The `person_id IS NULL` scope is what keeps 9hv's one-row-per-
# human rule intact: a spine-LINKED candidate's human already surfaces through
# the person lane (by canonical name), so their FEC record stays out of the
# union and remains reachable under the explicit `entity_type=candidate`
# filter. Known edge, accepted and documented: a linked record whose FEC name
# matches a query its person's canonical_name does not match will surface under
# the explicit filter but not in the union — rarer and cheaper than rendering
# most linked humans twice.
#
# The scope is a WHERE inside the arm, not a post-hoc DISTINCT, for the same
# reason 9hv removed the old arm instead of deduping: filtering after
# LIMIT/OFFSET would shrink pages after the window had already been taken.
_SEARCH_ALL_ENTITIES_SQL = _build_search_sql(
    f"""
    {_SEARCH_PERSON_ROWS_SQL}
    UNION ALL
    {_SEARCH_ORG_ROWS_SQL}
    UNION ALL
    {_SEARCH_COMMITTEE_ROWS_SQL}
    UNION ALL
    {_SEARCH_UNION_CANDIDATE_ROWS_SQL}
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
