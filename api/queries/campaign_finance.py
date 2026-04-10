
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from api.models.campaign_finance import (
    CandidateListParams,
    CommitteeListParams,
    TransactionListParams,
)
from api.queries._common import (
    _MONEY_SCALE,
    _SLUG_NORMALIZE_EXPR,
    _build_paginated_response,
    _fetch_filtered_rows,
    fetch_one_row,
)

# ---------------------------------------------------------------------------
# Slug SQL
# ---------------------------------------------------------------------------

# Precomputed slug expressions for cf.candidate and cf.committee name columns.
_SLUG_NAME_EXPR = _SLUG_NORMALIZE_EXPR.format(value="c.name")
_SLUG_PARAM_EXPR = _SLUG_NORMALIZE_EXPR.format(value="%s")

PERSON_BY_SLUG_SQL = f"""
    SELECT
        id,
        canonical_name,
        first_name,
        last_name,
        suffix
    FROM core.person
    WHERE {_SLUG_NORMALIZE_EXPR.format(value="canonical_name")}
        = {_SLUG_NORMALIZE_EXPR.format(value="%s")}
    ORDER BY canonical_name ASC, id ASC
"""

CANDIDATE_BY_SLUG_SQL = f"""
    SELECT
        c.id,
        c.fec_candidate_id,
        c.name,
        c.party,
        c.office,
        c.state,
        c.district,
        {_SLUG_NAME_EXPR} AS slug,
        (COUNT(*) OVER (PARTITION BY {_SLUG_NAME_EXPR}) = 1) AS slug_is_unique
    FROM cf.candidate c
    WHERE {_SLUG_NAME_EXPR} = {_SLUG_PARAM_EXPR}
    ORDER BY c.name ASC, c.id ASC
"""

COMMITTEE_BY_SLUG_SQL = f"""
    SELECT
        c.id,
        c.fec_committee_id,
        c.name,
        c.committee_type,
        c.party,
        c.state,
        {_SLUG_NAME_EXPR} AS slug,
        (COUNT(*) OVER (PARTITION BY {_SLUG_NAME_EXPR}) = 1) AS slug_is_unique
    FROM cf.committee c
    WHERE {_SLUG_NAME_EXPR} = {_SLUG_PARAM_EXPR}
    ORDER BY c.name ASC, c.id ASC
"""

# Scalar subquery for slug_is_unique in detail queries — counts all rows with
# the same normalized slug across the full table.
_CANDIDATE_SLUG_IS_UNIQUE_SUBQUERY = f"""(
        SELECT COUNT(*) FROM cf.candidate c2
        WHERE {_SLUG_NORMALIZE_EXPR.format(value="c2.name")}
            = {_SLUG_NORMALIZE_EXPR.format(value="c.name")}
    ) = 1"""

_COMMITTEE_SLUG_IS_UNIQUE_SUBQUERY = f"""(
        SELECT COUNT(*) FROM cf.committee c2
        WHERE {_SLUG_NORMALIZE_EXPR.format(value="c2.name")}
            = {_SLUG_NORMALIZE_EXPR.format(value="c.name")}
    ) = 1"""

# ---------------------------------------------------------------------------
# Detail SQL
# ---------------------------------------------------------------------------

CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL = f"""
    SELECT
        c.id,
        c.fec_committee_id,
        c.name,
        {_SLUG_NAME_EXPR} AS slug,
        {_COMMITTEE_SLUG_IS_UNIQUE_SUBQUERY} AS slug_is_unique,
        c.organization_id,
        c.committee_type,
        c.committee_designation,
        c.party,
        c.state,
        c.city,
        c.zip_code,
        c.treasurer_name,
        c.source_record_id
    FROM cf.committee c
    WHERE c.id = %s
"""

CAMPAIGN_FINANCE_CANDIDATE_DETAIL_SQL = f"""
    SELECT
        c.id,
        c.fec_candidate_id,
        c.name,
        {_SLUG_NAME_EXPR} AS slug,
        {_CANDIDATE_SLUG_IS_UNIQUE_SUBQUERY} AS slug_is_unique,
        c.person_id,
        c.party,
        c.office,
        c.state,
        c.district,
        c.incumbent_challenge,
        c.principal_committee_id,
        c.source_record_id
    FROM cf.candidate c
    WHERE c.id = %s
"""

CANDIDATE_LINKED_COMMITTEE_IDS_SQL = """
    SELECT DISTINCT committee_id
    FROM cf.candidate_committee_link
    WHERE candidate_id = %s
      AND valid_period @> CURRENT_DATE
    ORDER BY committee_id ASC
"""

CAMPAIGN_FINANCE_FILING_DETAIL_SQL = """
    SELECT
        f.id,
        f.filing_fec_id,
        f.committee_id,
        f.candidate_id,
        f.election_id,
        f.report_type,
        f.amendment_indicator,
        f.filing_name,
        f.coverage_start_date,
        f.coverage_end_date,
        f.due_date,
        f.receipt_date,
        f.accepted_date,
        f.is_amended,
        f.amended_from_filing_id,
        f.days_late,
        f.source_record_id,
        c.source_record_id AS fallback_committee_source_record_id,
        c.organization_id AS fallback_committee_organization_id
    FROM cf.filing f
    JOIN cf.committee c
      ON c.id = f.committee_id
    WHERE f.id = %s
"""

# ---------------------------------------------------------------------------
# Fundraising summary SQL
# ---------------------------------------------------------------------------

# FEC transaction-type classification: the first character of transaction_type
# determines receipt vs. disbursement.
RECEIPT_TYPE_PREFIX = "1"
DISBURSEMENT_TYPE_PREFIX = "2"


def _qualifying_transactions_cte(select_columns: str) -> str:
    """Build the qualifying-transactions CTE fragment.

    Shared between committee-level summary and per-filing breakdown queries.
    Filters: non-memo, non-terminated-amendment, non-superseded source records.
    The caller must bind ``committee_id`` as the first query parameter (``%s``).
    """
    return f"""qualifying_transactions AS (
        SELECT
            {select_columns}
        FROM cf.transaction t
        LEFT JOIN core.source_record sr
          ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
        WHERE t.committee_id = %s
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
          AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
    )"""


# Shared fundraising aggregate columns for qualifying_transactions CTEs.
# Expects the CTE alias ``qt`` with columns ``amount``, ``transaction_type``, and ``id``.
_FUNDRAISING_AGGREGATE_COLUMNS = f"""COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
        ), 0) AS total_raised,
        COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'
        ), 0) AS total_spent,
        COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
        ), 0)
        - COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'
        ), 0) AS net,
        COUNT(qt.id) AS transaction_count"""

COMMITTEE_FUNDRAISING_SUMMARY_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.committee_id, t.transaction_type, t.amount, t.source_record_id")},
    latest_provenance AS (
        SELECT
            ds.jurisdiction,
            sr.pull_date AS data_through
        FROM qualifying_transactions qt
        JOIN core.source_record sr
          ON sr.id = qt.source_record_id
        LEFT JOIN core.data_source ds
          ON ds.id = sr.data_source_id
        ORDER BY sr.pull_date DESC, sr.id ASC
        LIMIT 1
    )
    SELECT
        c.id AS committee_id,
        c.name AS committee_name,
        {_FUNDRAISING_AGGREGATE_COLUMNS},
        latest_provenance.jurisdiction,
        latest_provenance.data_through
    FROM cf.committee c
    JOIN qualifying_transactions qt
      ON qt.committee_id = c.id
    LEFT JOIN latest_provenance
      ON TRUE
    WHERE c.id = %s
    GROUP BY c.id, c.name, latest_provenance.jurisdiction, latest_provenance.data_through
"""

COMMITTEE_FILING_BREAKDOWN_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.filing_id, t.transaction_type, t.amount")}
    SELECT
        f.id AS filing_id,
        f.filing_fec_id,
        f.filing_name,
        f.report_type,
        f.amendment_indicator,
        f.coverage_start_date,
        f.coverage_end_date,
        f.receipt_date,
        {_FUNDRAISING_AGGREGATE_COLUMNS}
    FROM cf.filing f
    LEFT JOIN qualifying_transactions qt
      ON qt.filing_id = f.id
    WHERE f.committee_id = %s
    GROUP BY
        f.id,
        f.filing_fec_id,
        f.filing_name,
        f.report_type,
        f.amendment_indicator,
        f.coverage_start_date,
        f.coverage_end_date,
        f.receipt_date
    ORDER BY f.coverage_end_date DESC NULLS LAST, f.receipt_date DESC NULLS LAST, f.id ASC
"""

# ---------------------------------------------------------------------------
# List SQL templates
# ---------------------------------------------------------------------------

_TRANSACTION_LIST_SQL_TEMPLATE = """
    SELECT
        t.id,
        t.filing_id,
        t.committee_id,
        t.transaction_type,
        t.transaction_identifier,
        t.transaction_date,
        t.amount,
        t.contributor_name_raw,
        t.contributor_employer,
        t.contributor_occupation,
        t.contributor_city,
        t.contributor_state,
        t.contributor_zip,
        t.contributor_person_id,
        t.contributor_organization_id,
        t.contributor_address_id,
        t.recipient_candidate_id,
        t.recipient_committee_id,
        t.memo_text,
        t.is_memo,
        t.amendment_indicator,
        t.date_is_reliable,
        t.support_oppose,
        t.dissemination_date,
        t.aggregate_amount
    FROM cf.transaction t
    LEFT JOIN core.source_record sr
      ON sr.id = t.source_record_id
    LEFT JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    WHERE {where_sql}
    ORDER BY t.transaction_date DESC NULLS LAST, t.id ASC
    LIMIT %s
    OFFSET %s
"""

_CANDIDATE_LIST_SQL_TEMPLATE = f"""
    SELECT
        c.id,
        c.fec_candidate_id,
        c.name,
        c.party,
        c.office,
        c.state,
        c.district,
        {_SLUG_NAME_EXPR} AS slug,
        {_CANDIDATE_SLUG_IS_UNIQUE_SUBQUERY} AS slug_is_unique
    FROM cf.candidate c
    WHERE {{where_sql}}
    ORDER BY c.name ASC, c.id ASC
    LIMIT %s + 1
    OFFSET %s
"""

_COMMITTEE_LIST_SQL_TEMPLATE = f"""
    SELECT
        c.id,
        c.fec_committee_id,
        c.name,
        c.committee_type,
        c.party,
        c.state,
        {_SLUG_NAME_EXPR} AS slug,
        {_COMMITTEE_SLUG_IS_UNIQUE_SUBQUERY} AS slug_is_unique
    FROM cf.committee c
    WHERE {{where_sql}}
    ORDER BY c.name ASC, c.id ASC
    LIMIT %s + 1
    OFFSET %s
"""

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def fetch_persons_by_slug(conn: psycopg.Connection, slug: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(PERSON_BY_SLUG_SQL, (slug,))
        return list(cursor.fetchall())


def fetch_candidates_by_slug(conn: psycopg.Connection, slug: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CANDIDATE_BY_SLUG_SQL, (slug,))
        return list(cursor.fetchall())


def fetch_committees_by_slug(conn: psycopg.Connection, slug: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_BY_SLUG_SQL, (slug,))
        return list(cursor.fetchall())


def fetch_committee_fundraising_summary(
    conn: psycopg.Connection,
    committee_id: UUID,
) -> dict[str, Any] | None:
    """Aggregate fundraising totals for a single committee, or return None when no qualifying transactions exist."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_FUNDRAISING_SUMMARY_SQL, (committee_id, committee_id))
        summary_row = cursor.fetchone()

    if summary_row is None:
        return None

    _quantize_money_fields(summary_row, "total_raised", "total_spent", "net")
    return summary_row


def build_zero_committee_fundraising_summary(*, committee_id: UUID, committee_name: str) -> dict[str, Any]:
    """Return the stable zero-total payload for committees without qualifying transactions."""
    return {
        "committee_id": committee_id,
        "committee_name": committee_name,
        "total_raised": _MONEY_SCALE,
        "total_spent": _MONEY_SCALE,
        "net": _MONEY_SCALE,
        "transaction_count": 0,
        "jurisdiction": None,
        "data_through": None,
    }


def build_zero_candidate_fundraising_summary(*, candidate_id: UUID, candidate_name: str) -> dict[str, Any]:
    """Return the stable zero-total payload for candidates without linked committees."""
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "total_raised": _MONEY_SCALE,
        "total_spent": _MONEY_SCALE,
        "net": _MONEY_SCALE,
        "transaction_count": 0,
        "committees": [],
    }


def fetch_candidate_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    candidate_name: str,
) -> dict[str, Any] | None:
    """Aggregate fundraising totals for a candidate across active linked committees."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CANDIDATE_LINKED_COMMITTEE_IDS_SQL, (candidate_id,))
        linked_committee_rows = list(cursor.fetchall())

    if not linked_committee_rows:
        return None

    committee_summaries: list[dict[str, Any]] = []
    for linked_committee_row in linked_committee_rows:
        committee_id = linked_committee_row["committee_id"]
        committee_summary = fetch_committee_fundraising_summary(conn, committee_id)
        if committee_summary is None:
            committee_row = fetch_one_row(conn, query=CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, row_id=committee_id)
            if committee_row is None:
                raise RuntimeError(f"Linked committee not found for candidate summary: {committee_id}")
            committee_summary = build_zero_committee_fundraising_summary(
                committee_id=committee_id,
                committee_name=committee_row["name"],
            )
        committee_summaries.append(committee_summary)

    total_raised = sum((committee["total_raised"] for committee in committee_summaries), start=_MONEY_SCALE)
    total_spent = sum((committee["total_spent"] for committee in committee_summaries), start=_MONEY_SCALE)
    net_total = sum((committee["net"] for committee in committee_summaries), start=_MONEY_SCALE)
    transaction_count = sum(committee["transaction_count"] for committee in committee_summaries)
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "total_raised": total_raised,
        "total_spent": total_spent,
        "net": net_total,
        "transaction_count": transaction_count,
        "committees": committee_summaries,
    }


def fetch_committee_filing_breakdown(
    conn: psycopg.Connection,
    committee_id: UUID,
) -> list[dict[str, Any]]:
    """Return per-filing fundraising totals for a committee."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_FILING_BREAKDOWN_SQL, (committee_id, committee_id))
        filing_rows = list(cursor.fetchall())

    for filing_row in filing_rows:
        _quantize_money_fields(filing_row, "total_raised", "total_spent", "net")
    return filing_rows


def fetch_candidate_list(
    conn: psycopg.Connection,
    params: CandidateListParams,
) -> dict[str, Any]:
    rows = _fetch_filtered_rows(
        conn,
        sql_template=_CANDIDATE_LIST_SQL_TEMPLATE,
        filter_values=(
            (params.state, "c.state = %s"),
            (params.office, "c.office = %s"),
        ),
        limit=params.limit,
        offset=params.offset,
    )
    return _build_paginated_response(rows, limit=params.limit, offset=params.offset)


def fetch_committee_list(
    conn: psycopg.Connection,
    params: CommitteeListParams,
) -> dict[str, Any]:
    rows = _fetch_filtered_rows(
        conn,
        sql_template=_COMMITTEE_LIST_SQL_TEMPLATE,
        filter_values=(
            (params.state, "c.state = %s"),
            (params.committee_type, "c.committee_type = %s"),
        ),
        limit=params.limit,
        offset=params.offset,
    )
    return _build_paginated_response(rows, limit=params.limit, offset=params.offset)


def fetch_transaction_list(
    conn: psycopg.Connection,
    params: TransactionListParams,
) -> list[dict[str, Any]]:
    """Fetch filtered transaction list for a committee."""
    return _fetch_filtered_rows(
        conn,
        sql_template=_TRANSACTION_LIST_SQL_TEMPLATE,
        filter_values=(
            (params.committee_id, "t.committee_id = %s"),
            (params.jurisdiction, "ds.jurisdiction = %s"),
            (params.min_date, "t.transaction_date >= %s"),
            (params.max_date, "t.transaction_date <= %s"),
            (params.min_amount, "t.amount >= %s"),
            (params.max_amount, "t.amount <= %s"),
        ),
        limit=params.limit,
        offset=params.offset,
    )


# ---------------------------------------------------------------------------
# Independent Expenditure SQL (FEC Schedule E)
# ---------------------------------------------------------------------------

_IE_TOP_SPENDERS_DEFAULT_LIMIT = 10

_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL = """
    LEFT JOIN core.source_record sr
      ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
"""

_CANDIDATE_IE_QUALIFYING_WHERE_SQL = """
    WHERE t.recipient_candidate_id = %s
      AND t.support_oppose IS NOT NULL
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
"""

_CANDIDATE_IE_LIST_SQL = f"""
    SELECT
        t.id,
        t.filing_id,
        t.committee_id,
        c.name AS committee_name,
        t.memo_text AS purpose,
        t.amount,
        t.transaction_date,
        t.dissemination_date,
        t.aggregate_amount,
        t.support_oppose
    FROM cf.transaction t
    JOIN cf.committee c
      ON c.id = t.committee_id
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    {_CANDIDATE_IE_QUALIFYING_WHERE_SQL}
    ORDER BY t.amount DESC NULLS LAST, t.id ASC
    LIMIT %s
    OFFSET %s
"""

_CANDIDATE_IE_SUMMARY_SQL = f"""
    SELECT
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'S'), 0) AS support_total,
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'O'), 0) AS oppose_total,
        COUNT(*) FILTER (WHERE t.support_oppose = 'S')::integer AS support_count,
        COUNT(*) FILTER (WHERE t.support_oppose = 'O')::integer AS oppose_count
    FROM cf.transaction t
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    {_CANDIDATE_IE_QUALIFYING_WHERE_SQL}
"""

_CANDIDATE_IE_TOP_SPENDERS_SQL = f"""
    SELECT
        t.committee_id,
        c.name AS committee_name,
        t.support_oppose,
        COALESCE(SUM(t.amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM cf.transaction t
    JOIN cf.committee c
      ON c.id = t.committee_id
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    {_CANDIDATE_IE_QUALIFYING_WHERE_SQL}
    GROUP BY t.committee_id, c.name, t.support_oppose
    ORDER BY SUM(t.amount) DESC, t.committee_id ASC, t.support_oppose ASC
    LIMIT %s
"""


def _quantize_money(value: Any) -> Decimal:
    return Decimal(value).quantize(_MONEY_SCALE)


def _quantize_money_fields(row: dict[str, Any], *field_names: str) -> None:
    for field_name in field_names:
        row[field_name] = _quantize_money(row[field_name])


def fetch_candidate_ie_transactions(
    conn: psycopg.Connection,
    candidate_id: UUID,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CANDIDATE_IE_LIST_SQL, (candidate_id, limit, offset))
        return list(cursor.fetchall())


def fetch_candidate_ie_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    *,
    top_spenders_limit: int = _IE_TOP_SPENDERS_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Fetch aggregated IE support/oppose totals and top spenders for a candidate."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CANDIDATE_IE_SUMMARY_SQL, (candidate_id,))
        summary_row = cursor.fetchone()
        if summary_row is None:
            raise RuntimeError(f"IE summary query returned no rows for candidate: {candidate_id}")

        cursor.execute(_CANDIDATE_IE_TOP_SPENDERS_SQL, (candidate_id, top_spenders_limit))
        top_spender_rows = list(cursor.fetchall())

    for top_spender_row in top_spender_rows:
        _quantize_money_fields(top_spender_row, "total_amount")

    return {
        "candidate_id": candidate_id,
        "support_total": _quantize_money(summary_row["support_total"]),
        "oppose_total": _quantize_money(summary_row["oppose_total"]),
        "support_count": summary_row["support_count"],
        "oppose_count": summary_row["oppose_count"],
        "top_spenders": top_spender_rows,
    }
