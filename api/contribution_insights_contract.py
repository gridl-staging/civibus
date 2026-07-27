"""Shared SQL contract for federal contribution-insights receipt filters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from domains.campaign_finance.ingest.field_mapper import parse_fec_date
from domains.campaign_finance.types import is_fec_memo_code


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


def contribution_insights_transaction_where_sql(*, min_date_sql: str = "%s", max_date_sql: str | None = None) -> str:
    max_date_clause = "" if max_date_sql is None else f"\n          AND t.transaction_date <= {max_date_sql}"
    return f"""
          AND t.transaction_date >= {min_date_sql}
{max_date_clause}
          AND t.transaction_date IS NOT NULL
          AND t.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
          AND t.contributor_entity_type = 'IND'
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
"""


def is_contribution_insights_mapped_row(row: Mapping[str, object]) -> bool:
    transaction_date = _mapped_contribution_date(row.get("contribution_receipt_date"))
    transaction_type = _mapped_text(row.get("transaction_type"))
    entity_type = _mapped_text(row.get("entity_type"))
    amendment_indicator = _mapped_text(row.get("amendment_indicator"))
    memo_code = _mapped_text(row.get("memo_code"))

    return (
        transaction_date is not None
        and transaction_date >= CONTRIBUTION_INSIGHTS_MIN_DATE
        and transaction_type is not None
        and transaction_type.startswith(RECEIPT_TYPE_PREFIX)
        and entity_type == "IND"
        and not is_fec_memo_code(memo_code)
        and amendment_indicator is not None
        and amendment_indicator != "T"
    )


def _mapped_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapped_contribution_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = _mapped_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        parsed_fec_date = parse_fec_date(text)
        if parsed_fec_date is None:
            return None
        return date.fromisoformat(parsed_fec_date)
