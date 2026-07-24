from __future__ import annotations

import re

import pytest

from api.queries._common import _render_filtered_rows_query
from api.queries.campaign_finance import (
    _CANDIDATE_LIST_SQL_TEMPLATE,
    _COMMITTEE_LIST_SQL_TEMPLATE,
)


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
