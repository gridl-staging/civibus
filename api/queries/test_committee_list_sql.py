from __future__ import annotations

import re
from typing import Any

import psycopg
import pytest

from api.queries._common import _render_filtered_rows_query
from api.queries.campaign_finance import (
    _CANDIDATE_LIST_SQL_TEMPLATE,
    _COMMITTEE_LIST_SQL_TEMPLATE,
)
from test_support.donor_search_fixture import seed_full_scope_skewed_donor_search_fixture


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


def _explain_analyze_list_query(
    db_conn: psycopg.Connection,
    sql_template: str,
) -> dict[str, Any]:
    rendered_sql = _render_filtered_rows_query(sql_template, where_sql="TRUE")
    with db_conn.cursor() as cursor:
        cursor.execute(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {rendered_sql}",
            (50, 0),
        )
        return cursor.fetchone()[0][0]["Plan"]


def test_committee_list_sql_does_not_use_correlated_slug_count_per_row() -> None:
    normalized_sql = re.sub(r"\s+", " ", _COMMITTEE_LIST_SQL_TEMPLATE).lower()

    assert "select count(*) from cf.committee c2" not in normalized_sql
    assert "partition by" in normalized_sql or "group by" in normalized_sql


def test_candidate_list_sql_does_not_use_correlated_slug_count_per_row() -> None:
    normalized_sql = re.sub(r"\s+", " ", _CANDIDATE_LIST_SQL_TEMPLATE).lower()

    assert "select count(*) from cf.candidate c2" not in normalized_sql
    assert "filtered_candidates as materialized" in normalized_sql
    assert "page_slugs" in normalized_sql
    assert "slug_counts" in normalized_sql
    assert "join slug_counts" in normalized_sql
    assert "limit %s + 1" in normalized_sql
    assert "offset %s" in normalized_sql


def test_candidate_list_sql_renderer_preserves_regex_quantifiers() -> None:
    rendered_sql = _render_filtered_rows_query(
        _CANDIDATE_LIST_SQL_TEMPLATE,
        where_sql="c.state = %s",
    )

    assert "{where_sql}" not in rendered_sql
    assert "WHERE c.state = %s" in rendered_sql
    assert r"(?:\s+\S+){0,6}\s+" in rendered_sql


@pytest.mark.integration
def test_list_slug_projection_reads_only_the_materialized_page(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)
    observed_page_scans: dict[str, list[tuple[int, int]]] = {}

    for label, sql_template, relation_name in (
        ("candidate", _CANDIDATE_LIST_SQL_TEMPLATE, "candidate"),
        ("committee", _COMMITTEE_LIST_SQL_TEMPLATE, "committee"),
    ):
        nodes = _plan_nodes(_explain_analyze_list_query(db_conn, sql_template))
        base_scans = [node for node in nodes if node.get("Relation Name") == relation_name]
        assert max(node["Actual Rows"] for node in base_scans) >= fixture.counts.linked_people
        observed_page_scans[label] = [
            (node["Actual Loops"], node["Actual Rows"])
            for node in nodes
            if node.get("Node Type") == "CTE Scan" and node.get("Alias") == "page"
        ]

    assert observed_page_scans == {
        "candidate": [(1, 51)],
        "committee": [(1, 51)],
    }


@pytest.mark.parametrize(
    "sql_template",
    [
        "SELECT TRUE",
        "SELECT TRUE WHERE {where_sql} OR {where_sql}",
    ],
)
def test_filtered_rows_sql_renderer_requires_one_filter_token(sql_template: str) -> None:
    with pytest.raises(
        ValueError,
        match=r"must contain exactly one \{where_sql\} token",
    ):
        _render_filtered_rows_query(sql_template, where_sql="TRUE")
