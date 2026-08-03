"""Placeholder/parameter arity contract for the donor-search statement builder.

This file exists because of a real ten-day production outage. On 2026-07-13,
commit ``947dc9df3`` changed the shared receipt fragment to
``contribution_insights_transaction_where_sql(max_date_sql="%s")`` so the
person *cycle* path could bind a coverage-end date. Donor search splices the
same fragment but never bound the new parameter, so every ``/donors`` query
raised ``psycopg.ProgrammingError: the query has 5 placeholders but 4
parameters were passed`` and returned HTTP 500.

Nothing caught it: ``api/queries/test_donor_search.py`` is
``pytest.mark.integration`` (deselected by ``make test``) and skips outright
when no Postgres is reachable, and the production smoke gate never visits
``/donors``. So this module is deliberately DB-free and un-marked — it runs in
the default suite on every machine, with no fixtures and no services.

See ``docs/live-state/2026_07_23_public_surface_audit.md``.
"""

from __future__ import annotations

import re

import pytest

from api.queries import campaign_finance as campaign_finance_queries


# psycopg substitutes exactly one parameter per ``%s``. A doubled ``%%`` is an
# escaped literal percent sign — the donor SQL uses those for LIKE wildcards
# (``'%%' || LOWER(%s) || '%%'``) and for the ``LIKE '1%%'`` receipt-type
# prefix — and consumes no parameter. Matching ``%s`` that is NOT preceded by
# another ``%`` therefore reproduces psycopg's own arity rule exactly.
_PLACEHOLDER_PATTERN = re.compile(r"(?<!%)%s")
_CTE_HEADER_RE = re.compile(r"\s*(?P<name>[a-z_][a-z0-9_]*)\s+AS(?:\s+MATERIALIZED)?\s*\(", re.IGNORECASE)

# One parameter per placeholder, in textual bind order: the mode-specific
# rollup search terms, LIMIT/OFFSET for the rollup donor page, then the
# CONTRIBUTION_INSIGHTS_MIN_DATE lower bound for bounded transaction details.
# Donor search has no upper date bound (see the screen spec at
# docs/reference/screen_specs/donor_lookup.md, which scopes results by
# officeholder currency and itemization, never by a date ceiling).
_EXPECTED_DONOR_SEARCH_PARAMETER_COUNTS = {"name": 5, "employer": 5, "zip": 4}


def _matching_close_paren(sql: str, open_paren: int) -> int:
    depth = 0
    for index, char in enumerate(sql[open_paren:], start=open_paren):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("CTE body has no closing parenthesis")


def _cte_bodies(sql: str) -> dict[str, str]:
    with_start = sql.upper().index("WITH") + len("WITH")
    ctes: dict[str, str] = {}
    cursor = with_start
    while match := _CTE_HEADER_RE.match(sql, cursor):
        open_paren = match.end() - 1
        close_paren = _matching_close_paren(sql, open_paren)
        ctes[match.group("name")] = sql[open_paren + 1 : close_paren]
        cursor = close_paren + 1
        while cursor < len(sql) and sql[cursor].isspace():
            cursor += 1
        if cursor >= len(sql) or sql[cursor] != ",":
            break
        cursor += 1
    return ctes


@pytest.mark.parametrize(
    ("search_mode", "search_query"),
    [
        ("name", "smith"),
        ("employer", "acme industries"),
        ("zip", "27701"),
    ],
)
def test_donor_search_statement_binds_one_parameter_per_placeholder(
    search_mode: str,
    search_query: str,
) -> None:
    """Every rendered donor-search mode must bind exactly its own placeholders.

    Both assertions matter and neither subsumes the other: the arity assertion
    pins the known answer for each mode so a silently-dropped bind cannot
    pass, and the placeholder assertion pins the statement to that answer so a
    newly-spliced ``%s`` from a shared fragment cannot pass either. The
    2026-07-13 regression changed only the second of those.
    """
    statement, parameters = campaign_finance_queries._build_donor_search_statement(
        q=search_query,
        by=search_mode,
        limit=20,
        offset=0,
    )

    assert len(parameters) == _EXPECTED_DONOR_SEARCH_PARAMETER_COUNTS[search_mode]
    assert len(_PLACEHOLDER_PATTERN.findall(statement)) == len(parameters)


@pytest.mark.parametrize(
    ("search_mode", "search_query", "expected_escaped_query"),
    [
        ("name", r"sm%_i\th", r"sm\%\_i\\th"),
        ("employer", r"ac%_me\labs", r"ac\%\_me\\labs"),
    ],
)
def test_donor_search_statement_escapes_like_wildcards_for_text_modes(
    search_mode: str,
    search_query: str,
    expected_escaped_query: str,
) -> None:
    statement, parameters = campaign_finance_queries._build_donor_search_statement(
        q=search_query,
        by=search_mode,
        limit=20,
        offset=0,
    )

    assert parameters[:2] == (expected_escaped_query, expected_escaped_query)
    assert statement.count("ESCAPE '\\'") == 2


def test_donor_search_statement_groups_by_active_donor_identity_cluster_or_fallback() -> None:
    statement, _parameters = campaign_finance_queries._build_donor_search_statement(
        q="smith",
        by="name",
        limit=20,
        offset=0,
    )

    expected_grouping_key = "COALESCE(resolution.resolved_donor_identity_id::text, record.raw_donor_key)"

    assert expected_grouping_key in statement
    assert "active_cluster.entity_type = 'donor_identity'" in statement
    assert "active_member.entity_type = 'donor_identity'" in statement
    assert statement.index("LEFT JOIN core.donor_identity identity_record") < statement.index(
        "matching_donor_keys AS MATERIALIZED"
    )
    assert "t.contributor_person_id" not in statement


def test_donor_search_statement_resolves_identity_from_raw_variants_before_pagination() -> None:
    statement, _parameters = campaign_finance_queries._build_donor_search_statement(
        q="smith",
        by="name",
        limit=20,
        offset=0,
    )
    ctes = _cte_bodies(statement)
    variant_sql = ctes["resolved_identity_variants"]
    variant_count_sql = ctes["variant_resolution_counts"]
    donor_resolution_sql = ctes["donor_resolution"]
    detail_sql = ctes["qualifying_transactions"]

    assert "JOIN cf.donor_search_rollup_identity_variant variant" in variant_sql
    assert "identity_record.contributor_name_raw = variant.contributor_name_raw" in variant_sql
    assert "COALESCE(identity_record.contributor_zip, '') = variant.contributor_zip" in variant_sql
    assert "active_canonical_member.entity_id = active_cluster.canonical_entity_id" in variant_sql
    assert "active_canonical_member.is_canonical" in variant_sql
    assert "active_canonical_member.split_at IS NULL" in variant_sql
    assert "active_canonical_identity.id AS resolved_donor_identity_id" in variant_sql
    assert "normalized_zip5" not in variant_sql
    assert "COUNT(DISTINCT variant.resolved_donor_identity_id) AS canonical_identity_count" in variant_count_sql
    assert "COUNT(*) = COUNT(*) FILTER (WHERE variant.canonical_identity_count = 1)" in donor_resolution_sql
    assert statement.index("resolved_identity_variants AS MATERIALIZED") < statement.index(
        "matching_donor_keys AS MATERIALIZED"
    )
    assert "LEFT JOIN resolved_identity_variants identity_variant" in detail_sql
    assert "COALESCE(transaction_row.contributor_zip, '') AS identity_zip" in detail_sql
    assert "identity_record.contributor_zip = record.identity_zip" not in statement
    donor_group_sql = ctes["donor_groups"]
    assert "page_key.total_amount" in donor_group_sql
    assert "page_key.transaction_count" in donor_group_sql
    assert "SUM(amount)" not in donor_group_sql
    assert "COUNT(*)" not in donor_group_sql


def test_donor_search_statement_drives_scope_from_current_officeholders() -> None:
    statement, _parameters = campaign_finance_queries._build_donor_search_statement(
        q="smith",
        by="name",
        limit=20,
        offset=0,
    )

    assert "current_federal_officeholders AS MATERIALIZED" in statement
    assert statement.index("current_federal_officeholders AS MATERIALIZED") < statement.index(
        "current_federal_candidate_committees AS MATERIALIZED"
    )
    assert "FROM current_federal_officeholders current_officeholder" in statement
    assert "candidate.person_id = current_officeholder.person_id" in statement
    assert statement.index("matching_donor_records AS MATERIALIZED") < statement.index(
        "matching_donor_keys AS MATERIALIZED"
    )


@pytest.mark.parametrize(
    ("search_mode", "search_query", "expected_search_field", "expected_mode_field"),
    [
        ("name", "smith", "rollup.search_text", "LOWER(rollup.contributor_name) LIKE"),
        ("employer", "acme industries", "rollup.search_text", "LOWER(rollup.contributor_employer) LIKE"),
        ("zip", "27701", "rollup.normalized_zip5", "rollup.normalized_zip5 ="),
    ],
)
def test_donor_search_statement_discovers_page_from_refresh_rollup(
    search_mode: str,
    search_query: str,
    expected_search_field: str,
    expected_mode_field: str,
) -> None:
    statement, _parameters = campaign_finance_queries._build_donor_search_statement(
        q=search_query,
        by=search_mode,
        limit=20,
        offset=0,
    )
    ctes = _cte_bodies(statement)
    donor_grain_sql = ctes["matching_donor_records"]

    assert "FROM cf.donor_search_rollup rollup" in donor_grain_sql
    assert expected_search_field in donor_grain_sql
    assert expected_mode_field in donor_grain_sql
    assert "cf.transaction" not in donor_grain_sql
    assert statement.index("matching_donor_keys AS MATERIALIZED") < statement.index(
        "qualifying_transactions AS MATERIALIZED"
    )


def test_donor_search_statement_pushes_committee_scope_into_transaction_detail_probe() -> None:
    statement, _parameters = campaign_finance_queries._build_donor_search_statement(
        q="johnson",
        by="name",
        limit=20,
        offset=0,
    )
    ctes = _cte_bodies(statement)
    donor_discovery_sql = ctes["matching_donor_records"]
    transaction_detail_sql = ctes["qualifying_transactions"]
    scoped_committee_join = "JOIN current_federal_committee_scope scope_filter"

    assert "FROM cf.donor_search_rollup rollup" in donor_discovery_sql
    assert statement.index("matching_donor_keys AS MATERIALIZED") < statement.index(
        "qualifying_transactions AS MATERIALIZED"
    )
    assert transaction_detail_sql.count(scoped_committee_join) == 1
    transaction_probe_start = transaction_detail_sql.index("FROM cf.transaction transaction_row")
    transaction_probe_end = transaction_detail_sql.index(") transaction_detail")
    assert transaction_probe_start < transaction_detail_sql.index(scoped_committee_join) < transaction_probe_end
    assert transaction_detail_sql.index(scoped_committee_join) < transaction_detail_sql.index(
        "WHERE transaction_row.contributor_name_raw IS NOT NULL"
    )

    # The full-scope skew fixture has only 827 candidate_committee_link rows;
    # it cannot reproduce production's candidate-link plan, so this contract
    # pins the repaired SQL boundary rather than asserting that fixture's plan.


def test_donor_search_statement_keeps_only_bounded_transaction_detail_sites() -> None:
    statement, _parameters = campaign_finance_queries._build_donor_search_statement(
        q="smith",
        by="name",
        limit=20,
        offset=0,
    )

    # Remaining transaction site 1: post-pagination transaction detail and
    # provenance access for only the selected rollup donor keys.
    assert "FROM cf.transaction transaction_row" in _cte_bodies(statement)["qualifying_transactions"]
    # Remaining transaction site 2: possible-match evidence access for identity
    # transparency candidates that are not part of the combined donor cluster.
    assert "JOIN cf.transaction t" in _cte_bodies(statement)["not_combined_candidate_rollups"]
    assert statement.count("cf.transaction") == 2
