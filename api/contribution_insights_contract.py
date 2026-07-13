"""Shared SQL contract for federal contribution-insights receipt filters."""

from __future__ import annotations

from datetime import date


RECEIPT_TYPE_PREFIX = "1"
CONTRIBUTION_INSIGHTS_MIN_DATE = date(2022, 1, 1)

# Canonical anti-join for excluding transactions whose backing source record has
# been superseded. This is the single owner of the superseded-source filter: it
# is spliced into the donor-search, person-insights, and committee qualifying
# CTEs so all three keep byte-identical supersession semantics.
#
# Shape: hashed ``NOT IN`` sub-select over the tiny superseded set.
# Postgres compiles this to a single hashed SubPlan built once from
# ``idx_source_record_superseded_id`` (partial index on
# ``superseded_by IS NOT NULL``), which currently contains only ~142 rows.
# Each candidate transaction then does an O(1) hash probe. The equivalent
# ``NOT EXISTS`` shape compiles to a Nested Loop Anti Join whose Materialize
# is rescanned once per candidate row (measured 78 s / 54 s warm on the
# 350k-source ``jul10_pm_7`` committee); the ``NOT IN`` shape landed the same
# probes at 331 ms warm (s25 live evidence).
#
# NULL-safety: ``core.source_record.id`` is the primary key and therefore
# never NULL, so the ``NOT IN`` right-hand side cannot fall into the standard
# NOT IN + NULL pitfall. Transactions with ``source_record_id IS NULL`` must
# still pass the filter (matching the prior ``NOT EXISTS`` semantics, where
# the join predicate ``superseded.id = NULL`` produced no matches and the row
# was kept); the leading ``IS NULL`` guard preserves that behavior.
#
# Callers must alias the transaction row as ``t``.
NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL = """
          AND (
              t.source_record_id IS NULL
              OR t.source_record_id NOT IN (
                  SELECT superseded.id
                  FROM core.source_record superseded
                  WHERE superseded.superseded_by IS NOT NULL
              )
          )
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
