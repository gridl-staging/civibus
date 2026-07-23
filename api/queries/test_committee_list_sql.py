from __future__ import annotations

import re

from api.queries.campaign_finance import _COMMITTEE_LIST_SQL_TEMPLATE


def test_committee_list_sql_does_not_use_correlated_slug_count_per_row() -> None:
    normalized_sql = re.sub(r"\s+", " ", _COMMITTEE_LIST_SQL_TEMPLATE).lower()

    assert "select count(*) from cf.committee c2" not in normalized_sql
    assert "partition by" in normalized_sql or "group by" in normalized_sql
