"""Shared SQL contract for federal contribution-insights receipt filters."""

from __future__ import annotations

from datetime import date


RECEIPT_TYPE_PREFIX = "1"
CONTRIBUTION_INSIGHTS_MIN_DATE = date(2022, 1, 1)
CONTRIBUTION_INSIGHTS_SOURCE_RECORD_JOIN_SQL = """
        LEFT JOIN core.source_record sr
          ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
"""
CONTRIBUTION_INSIGHTS_SOURCE_RECORD_WHERE_SQL = """
          AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
"""


def contribution_insights_transaction_where_sql(*, min_date_sql: str = "%s") -> str:
    return f"""
          AND t.transaction_date >= {min_date_sql}
          AND t.transaction_date IS NOT NULL
          AND t.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
          AND t.contributor_entity_type = 'IND'
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
"""
