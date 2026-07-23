from __future__ import annotations

import re

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
