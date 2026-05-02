
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistryRow,
    load_registry,
)
from domains.civics.constants import LAUNCH_SCOPE_USPS_STATES

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
_COUNTY_TOP_LIST_LIMIT = 5
_COMMITTEE_TOP_PARTIES_LIMIT = 5
_COMMITTEE_SPEND_CATEGORY_LIMIT = 5
_COMMITTEE_IN_KIND_RECEIPT_CODE = "15Z"
_COMMITTEE_LOAN_RECEIPT_PREFIX = "16"

# Documented Stage 1 fallback: this maps counties to committee-registration cities.
# It is a proxy for outflow analysis, not donor-residence truth.
_COUNTY_PROXY_CITIES_BY_STATE: dict[str, dict[str, tuple[str, ...]]] = {
    "nc": {
        "wake": ("raleigh", "wake forest"),
    }
}


class UnknownCountySlugError(ValueError):
    """Raised when a county slug has no proxy-city mapping for the given state."""

    def __init__(self, *, state: str, county_slug: str) -> None:
        self.state = state
        self.county_slug = county_slug
        super().__init__(f"Unknown county slug for state: {state}/{county_slug}")


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
        COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
              AND qt.transaction_type LIKE '{_COMMITTEE_LOAN_RECEIPT_PREFIX}%%'
        ), 0) AS loan_receipts_total,
        COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type = '{_COMMITTEE_IN_KIND_RECEIPT_CODE}'
        ), 0) AS in_kind_receipts_total,
        COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
        ), 0)
        - COALESCE(SUM(qt.amount) FILTER (
            WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
              AND qt.transaction_type LIKE '{_COMMITTEE_LOAN_RECEIPT_PREFIX}%%'
        ), 0) AS contribution_receipts_total,
        GREATEST(
            COALESCE(SUM(qt.amount) FILTER (
                WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
            ), 0)
            - COALESCE(SUM(qt.amount) FILTER (
                WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
                  AND qt.transaction_type LIKE '{_COMMITTEE_LOAN_RECEIPT_PREFIX}%%'
            ), 0)
            - COALESCE(SUM(qt.amount) FILTER (
                WHERE qt.transaction_type = '{_COMMITTEE_IN_KIND_RECEIPT_CODE}'
            ), 0),
            0
        ) AS cash_receipts_total,
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

COMMITTEE_TOP_DONORS_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.transaction_type, t.amount, t.contributor_name_raw")}
    SELECT
        BTRIM(qt.contributor_name_raw) AS name,
        COALESCE(SUM(qt.amount), 0) AS total_amount,
        COUNT(qt.id)::integer AS transaction_count
    FROM qualifying_transactions qt
    WHERE qt.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
      AND qt.contributor_name_raw IS NOT NULL
      AND BTRIM(qt.contributor_name_raw) != ''
    GROUP BY BTRIM(qt.contributor_name_raw)
    ORDER BY total_amount DESC, transaction_count DESC, name ASC
    LIMIT %s
"""

COMMITTEE_TOP_VENDORS_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.transaction_type, t.amount, t.contributor_name_raw")}
    SELECT
        BTRIM(qt.contributor_name_raw) AS name,
        COALESCE(SUM(qt.amount), 0) AS total_amount,
        COUNT(qt.id)::integer AS transaction_count
    FROM qualifying_transactions qt
    WHERE qt.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'
      AND qt.contributor_name_raw IS NOT NULL
      AND BTRIM(qt.contributor_name_raw) != ''
    GROUP BY BTRIM(qt.contributor_name_raw)
    ORDER BY total_amount DESC, transaction_count DESC, name ASC
    LIMIT %s
"""

COMMITTEE_SPEND_CATEGORY_SUMMARY_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.transaction_type, t.amount, t.memo_text")}
    SELECT
        LOWER(BTRIM(qt.memo_text)) AS category,
        COALESCE(SUM(qt.amount), 0) AS total_amount,
        COUNT(qt.id)::integer AS transaction_count
    FROM qualifying_transactions qt
    WHERE qt.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'
      AND qt.memo_text IS NOT NULL
      AND BTRIM(qt.memo_text) != ''
    GROUP BY LOWER(BTRIM(qt.memo_text))
    ORDER BY total_amount DESC, transaction_count DESC, category ASC
    LIMIT %s
"""

COMMITTEE_FILING_BREAKDOWN_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.filing_id, t.transaction_type, t.amount")},
    filing_totals AS (
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
    ),
    filing_cash_on_hand AS (
        SELECT
            ft.*,
            SUM(ft.net) OVER (
                ORDER BY
                    ft.coverage_end_date ASC NULLS LAST,
                    ft.receipt_date ASC NULLS LAST,
                    ft.filing_id ASC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS cash_on_hand
        FROM filing_totals ft
    )
    SELECT
        filing_id,
        filing_fec_id,
        filing_name,
        report_type,
        amendment_indicator,
        coverage_start_date,
        coverage_end_date,
        receipt_date,
        total_raised,
        total_spent,
        net,
        transaction_count,
        cash_on_hand
    FROM filing_cash_on_hand
    ORDER BY coverage_end_date DESC NULLS LAST, receipt_date DESC NULLS LAST, filing_id ASC
"""

# ---------------------------------------------------------------------------
# County summary SQL (committee-city proxy)
# ---------------------------------------------------------------------------

_COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE = f"""
    WITH qualifying_transactions AS (
        SELECT
            t.id,
            t.committee_id,
            t.amount,
            t.recipient_committee_id,
            t.source_record_id
        FROM cf.transaction t
        JOIN cf.committee c
          ON c.id = t.committee_id
        LEFT JOIN core.source_record sr
          ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
        WHERE LOWER(c.state) = %s
          AND LOWER(BTRIM(c.city)) = ANY(%s)
          AND t.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
          AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
    )
"""

_COUNTY_SUMMARY_TOTALS_SQL = f"""
    {_COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE}
    SELECT
        CAST(ROUND(COALESCE(SUM(qt.amount), 0) * 100, 0) AS BIGINT) AS donor_total_cents,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions qt
"""

_COUNTY_SUMMARY_TOP_RECIPIENT_COMMITTEES_SQL = f"""
    {_COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE}
    SELECT
        qt.recipient_committee_id AS committee_id,
        rc.name AS committee_name,
        CAST(ROUND(COALESCE(SUM(qt.amount), 0) * 100, 0) AS BIGINT) AS donor_total_cents,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions qt
    JOIN cf.committee rc
      ON rc.id = qt.recipient_committee_id
    WHERE qt.recipient_committee_id IS NOT NULL
    GROUP BY qt.recipient_committee_id, rc.name
    ORDER BY donor_total_cents DESC, transaction_count DESC, rc.name ASC, qt.recipient_committee_id ASC
    LIMIT %s
"""

_COUNTY_SUMMARY_TOP_LINKED_CANDIDATES_SQL = f"""
    {_COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE},
    active_links AS (
        SELECT DISTINCT candidate_id, committee_id
        FROM cf.candidate_committee_link
        WHERE valid_period @> CURRENT_DATE
    )
    SELECT
        candidate.id AS candidate_id,
        candidate.name AS candidate_name,
        CAST(ROUND(COALESCE(SUM(qt.amount), 0) * 100, 0) AS BIGINT) AS donor_total_cents,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions qt
    JOIN active_links link
      ON link.committee_id = qt.recipient_committee_id
    JOIN cf.candidate candidate
      ON candidate.id = link.candidate_id
    GROUP BY candidate.id, candidate.name
    ORDER BY donor_total_cents DESC, transaction_count DESC, candidate.name ASC, candidate.id ASC
    LIMIT %s
"""

_COUNTY_SUMMARY_PROVENANCE_SQL = f"""
    {_COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE},
    dedup_source_ids AS (
        SELECT DISTINCT qt.source_record_id
        FROM qualifying_transactions qt
        WHERE qt.source_record_id IS NOT NULL
    )
    SELECT
        ds.domain AS domain,
        ds.jurisdiction AS jurisdiction,
        ds.name AS data_source_name,
        ds.source_url AS data_source_url,
        sr.source_record_key AS source_record_key,
        sr.source_url AS record_url,
        sr.pull_date AS pull_date
    FROM dedup_source_ids ids
    JOIN core.source_record sr
      ON sr.id = ids.source_record_id
    JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    ORDER BY sr.pull_date DESC, sr.id ASC
"""


def _resolve_county_proxy_cities(*, state: str, county_slug: str) -> tuple[str, tuple[str, ...]]:
    normalized_state = state.strip().lower()
    normalized_county_slug = county_slug.strip().lower()
    state_mapping = _COUNTY_PROXY_CITIES_BY_STATE.get(normalized_state, {})
    proxy_cities = state_mapping.get(normalized_county_slug)
    if proxy_cities is None:
        raise UnknownCountySlugError(state=normalized_state, county_slug=normalized_county_slug)
    return normalized_county_slug, proxy_cities


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
        c.person_id,
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
# State summary/detail SQL
# ---------------------------------------------------------------------------

_LAUNCH_SCOPE_STATE_CODES: tuple[str, ...] = LAUNCH_SCOPE_USPS_STATES
_LAUNCH_SCOPE_STATE_CODE_SET: frozenset[str] = frozenset(_LAUNCH_SCOPE_STATE_CODES)
_STATE_SUMMARY_SUPPORTED_TIER = "launch-support candidate"
_STATE_SUMMARY_WARNING_TIERS: frozenset[str] = frozenset({"freshness-limited", "implemented but unproven"})

_STATE_TRANSACTION_AGGREGATES_SQL = f"""
    SELECT
        c.state AS state_code,
        COALESCE(SUM(t.amount) FILTER (
            WHERE t.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
        ), 0) AS total_raised,
        COALESCE(SUM(t.amount) FILTER (
            WHERE t.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'
        ), 0) AS total_spent,
        COUNT(t.id)::integer AS transaction_count,
        MAX(sr.pull_date) AS data_through,
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'S'), 0) AS ie_support_total,
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'O'), 0) AS ie_oppose_total,
        COUNT(*) FILTER (WHERE t.support_oppose = 'S')::integer AS ie_support_count,
        COUNT(*) FILTER (WHERE t.support_oppose = 'O')::integer AS ie_oppose_count
    FROM cf.committee c
    LEFT JOIN cf.transaction t
      ON t.committee_id = c.id
    LEFT JOIN core.source_record sr
      ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
    WHERE c.state = ANY(%s)
      AND (
        t.id IS NULL
        OR (
            t.is_memo = FALSE
            AND t.amendment_indicator != 'T'
            AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
        )
      )
    GROUP BY c.state
"""

_STATE_COMMITTEE_COUNTS_SQL = """
    SELECT
        c.state AS state_code,
        COUNT(*)::integer AS committee_count
    FROM cf.committee c
    WHERE c.state = ANY(%s)
    GROUP BY c.state
"""

_STATE_CANDIDATE_COUNTS_SQL = """
    SELECT
        cand.state AS state_code,
        COUNT(*)::integer AS federal_candidate_count
    FROM cf.candidate cand
    WHERE cand.state = ANY(%s)
      AND cand.office IN ('H', 'S', 'P')
    GROUP BY cand.state
"""

_STATE_TOP_CANDIDATES_SQL = f"""
    SELECT
        cand.id AS candidate_id,
        cand.name AS candidate_name,
        COALESCE(SUM(t.amount) FILTER (
            WHERE t.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
        ), 0) AS total_raised
    FROM cf.candidate cand
    JOIN cf.transaction t
      ON t.recipient_candidate_id = cand.id
    JOIN cf.committee c
      ON c.id = t.committee_id
    LEFT JOIN core.source_record sr
      ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
    WHERE cand.state = %s
      AND cand.office IN ('H', 'S', 'P')
      AND c.state = %s
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
    GROUP BY cand.id, cand.name
    ORDER BY total_raised DESC, cand.id ASC
    LIMIT %s
"""

_STATE_TOP_COMMITTEES_SQL = f"""
    SELECT
        c.id AS committee_id,
        c.name AS committee_name,
        COALESCE(SUM(t.amount) FILTER (
            WHERE t.transaction_type LIKE '{RECEIPT_TYPE_PREFIX}%%'
        ), 0) AS total_raised
    FROM cf.committee c
    JOIN cf.transaction t
      ON t.committee_id = c.id
    LEFT JOIN core.source_record sr
      ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
    WHERE c.state = %s
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
    GROUP BY c.id, c.name
    ORDER BY total_raised DESC, c.id ASC
    LIMIT %s
"""

_STATE_TOP_IE_SPENDERS_SQL = """
    SELECT
        c.id AS committee_id,
        c.name AS committee_name,
        COALESCE(SUM(t.amount), 0) AS total_amount
    FROM cf.transaction t
    JOIN cf.committee c
      ON c.id = t.committee_id
    LEFT JOIN core.source_record sr
      ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
    WHERE c.state = %s
      AND t.support_oppose IS NOT NULL
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
    GROUP BY c.id, c.name
    ORDER BY total_amount DESC, c.id ASC
    LIMIT %s
"""

_STATE_PROVENANCE_SQL = """
    WITH dedup_source_ids AS (
        SELECT DISTINCT t.source_record_id
        FROM cf.transaction t
        JOIN cf.committee c
          ON c.id = t.committee_id
        LEFT JOIN core.source_record sr
          ON sr.id = t.source_record_id AND sr.superseded_by IS NULL
        WHERE c.state = %s
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
          AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
          AND t.source_record_id IS NOT NULL
    )
    SELECT
        ds.domain AS domain,
        ds.jurisdiction AS jurisdiction,
        ds.name AS data_source_name,
        ds.source_url AS data_source_url,
        sr.source_record_key AS source_record_key,
        sr.source_url AS record_url,
        sr.pull_date AS pull_date
    FROM dedup_source_ids ids
    JOIN core.source_record sr
      ON sr.id = ids.source_record_id
    JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    ORDER BY sr.pull_date DESC, sr.id ASC
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

        cursor.execute(COMMITTEE_TOP_DONORS_SQL, (committee_id, _COMMITTEE_TOP_PARTIES_LIMIT))
        top_donor_rows = list(cursor.fetchall())

        cursor.execute(COMMITTEE_TOP_VENDORS_SQL, (committee_id, _COMMITTEE_TOP_PARTIES_LIMIT))
        top_vendor_rows = list(cursor.fetchall())

        cursor.execute(COMMITTEE_SPEND_CATEGORY_SUMMARY_SQL, (committee_id, _COMMITTEE_SPEND_CATEGORY_LIMIT))
        spend_category_rows = list(cursor.fetchall())

    _quantize_money_fields(
        summary_row,
        "total_raised",
        "total_spent",
        "net",
        "cash_receipts_total",
        "in_kind_receipts_total",
        "loan_receipts_total",
        "contribution_receipts_total",
    )
    for top_donor_row in top_donor_rows:
        _quantize_money_fields(top_donor_row, "total_amount")
    for top_vendor_row in top_vendor_rows:
        _quantize_money_fields(top_vendor_row, "total_amount")
    for spend_category_row in spend_category_rows:
        _quantize_money_fields(spend_category_row, "total_amount")

    summary_row["top_donors"] = top_donor_rows
    summary_row["top_vendors"] = top_vendor_rows
    summary_row["spend_categories"] = spend_category_rows or None
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
        "cash_receipts_total": _MONEY_SCALE,
        "in_kind_receipts_total": _MONEY_SCALE,
        "loan_receipts_total": _MONEY_SCALE,
        "contribution_receipts_total": _MONEY_SCALE,
        "top_donors": [],
        "top_vendors": [],
        "spend_categories": None,
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
        _quantize_money_fields(filing_row, "total_raised", "total_spent", "net", "cash_on_hand")
        filing_row["row_id"] = f'{filing_row["filing_id"]}:{filing_row["amendment_indicator"]}'
    return filing_rows


def fetch_cf_summary_by_county(
    conn: psycopg.Connection,
    state: str,
    county_slug: str,
) -> dict[str, Any]:
    normalized_state = state.strip().lower()
    normalized_county_slug, proxy_cities = _resolve_county_proxy_cities(state=state, county_slug=county_slug)
    query_params = (normalized_state, list(proxy_cities))

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_COUNTY_SUMMARY_TOTALS_SQL, query_params)
        totals_row = cursor.fetchone()
        if totals_row is None:
            raise RuntimeError("County summary totals query returned no row")

        cursor.execute(
            _COUNTY_SUMMARY_TOP_RECIPIENT_COMMITTEES_SQL,
            (*query_params, _COUNTY_TOP_LIST_LIMIT),
        )
        top_recipients = list(cursor.fetchall())

        cursor.execute(
            _COUNTY_SUMMARY_TOP_LINKED_CANDIDATES_SQL,
            (*query_params, _COUNTY_TOP_LIST_LIMIT),
        )
        top_linked_candidates = list(cursor.fetchall())

        cursor.execute(_COUNTY_SUMMARY_PROVENANCE_SQL, query_params)
        sources = list(cursor.fetchall())

    return {
        "state": normalized_state,
        "county_slug": normalized_county_slug,
        "donor_total_cents": int(totals_row["donor_total_cents"]),
        "transaction_count": totals_row["transaction_count"],
        "top_recipient_committees": top_recipients,
        "top_linked_candidates": top_linked_candidates,
        "sources": sources,
    }


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
            (params.person_id, "c.person_id = %s"),
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


def _warning_text_for_registry_row(registry_row: CoverageRegistryRow) -> str | None:
    if (
        registry_row.tier == _STATE_SUMMARY_SUPPORTED_TIER
        and registry_row.ie_coverage_available is False
    ):
        # Launch-support states can still lack an IE lane in the source bulk
        # export. Surface an explicit caveat so the frontend can explain why IE
        # totals are null without downgrading the overall state support status.
        return "Independent expenditure data is incomplete for this state."
    if registry_row.tier == _STATE_SUMMARY_SUPPORTED_TIER:
        return None
    return registry_row.operational_reason or registry_row.next_action


def _state_support_status(registry_row: CoverageRegistryRow | None) -> str:
    if registry_row is None:
        return "unsupported"
    if registry_row.tier == _STATE_SUMMARY_SUPPORTED_TIER:
        return "supported"
    if registry_row.tier in _STATE_SUMMARY_WARNING_TIERS:
        return "warning"
    return "unsupported"


def _ie_coverage_available(registry_row: CoverageRegistryRow | None) -> bool:
    """Return True only when registry evidence supports honest IE totals.

    A launch-support state may still be missing outside-spending coverage
    (e.g. its bulk export carries no IE schedule), so the registry's explicit
    `ie_coverage_available=False` overrides the tier-based default. Returning
    False here causes the API to serialize null IE totals/counts instead of
    misleading zeroes.
    """
    if registry_row is None:
        return False
    if registry_row.tier != _STATE_SUMMARY_SUPPORTED_TIER:
        return False
    if registry_row.ie_coverage_available is False:
        return False
    return True


@lru_cache(maxsize=1)
def _coverage_rows_by_state() -> dict[str, CoverageRegistryRow]:
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    return {
        row.jurisdiction_code: row
        for row in registry.rows
        if row.jurisdiction_type == "state" and row.jurisdiction_code in _LAUNCH_SCOPE_STATE_CODE_SET
    }


def fetch_state_campaign_finance_summaries(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        launch_scope_state_codes = list(_LAUNCH_SCOPE_STATE_CODES)
        cursor.execute(_STATE_TRANSACTION_AGGREGATES_SQL, (launch_scope_state_codes,))
        transaction_rows = list(cursor.fetchall())
        cursor.execute(_STATE_COMMITTEE_COUNTS_SQL, (launch_scope_state_codes,))
        committee_count_rows = list(cursor.fetchall())
        cursor.execute(_STATE_CANDIDATE_COUNTS_SQL, (launch_scope_state_codes,))
        candidate_count_rows = list(cursor.fetchall())

    transaction_rows_by_state = {row["state_code"]: row for row in transaction_rows}
    committee_count_by_state = {row["state_code"]: row["committee_count"] for row in committee_count_rows}
    candidate_count_by_state = {row["state_code"]: row["federal_candidate_count"] for row in candidate_count_rows}
    registry_rows_by_state = _coverage_rows_by_state()

    summary_rows: list[dict[str, Any]] = []
    for state_code in _LAUNCH_SCOPE_STATE_CODES:
        transaction_row = transaction_rows_by_state.get(state_code)
        registry_row = registry_rows_by_state.get(state_code)
        support_status = _state_support_status(registry_row)

        if transaction_row is None:
            total_raised = _MONEY_SCALE
            total_spent = _MONEY_SCALE
            transaction_count = 0
            data_through = None
            ie_support_total = _MONEY_SCALE
            ie_oppose_total = _MONEY_SCALE
            ie_support_count = 0
            ie_oppose_count = 0
        else:
            total_raised = _quantize_money(transaction_row["total_raised"])
            total_spent = _quantize_money(transaction_row["total_spent"])
            transaction_count = transaction_row["transaction_count"]
            data_through = transaction_row["data_through"]
            ie_support_total = _quantize_money(transaction_row["ie_support_total"])
            ie_oppose_total = _quantize_money(transaction_row["ie_oppose_total"])
            ie_support_count = transaction_row["ie_support_count"]
            ie_oppose_count = transaction_row["ie_oppose_count"]

        if _ie_coverage_available(registry_row):
            ie_support_total_value: Decimal | None = ie_support_total
            ie_oppose_total_value: Decimal | None = ie_oppose_total
            ie_support_count_value: int | None = ie_support_count
            ie_oppose_count_value: int | None = ie_oppose_count
        else:
            ie_support_total_value = None
            ie_oppose_total_value = None
            ie_support_count_value = None
            ie_oppose_count_value = None

        summary_rows.append(
            {
                "state_code": state_code,
                "total_raised": total_raised,
                "total_spent": total_spent,
                "net": _quantize_money(total_raised - total_spent),
                "committee_count": committee_count_by_state.get(state_code, 0),
                "transaction_count": transaction_count,
                "federal_candidate_count": candidate_count_by_state.get(state_code, 0),
                "ie_support_total": ie_support_total_value,
                "ie_oppose_total": ie_oppose_total_value,
                "ie_support_count": ie_support_count_value,
                "ie_oppose_count": ie_oppose_count_value,
                "coverage_tier": registry_row.tier if registry_row is not None else None,
                "support_status": support_status,
                "supported": support_status == "supported",
                "warning_text": (
                    _warning_text_for_registry_row(registry_row)
                    if registry_row is not None
                    else "Coverage registry row missing."
                ),
                "data_through": data_through,
            }
        )

    summary_rows.sort(key=lambda row: (-row["total_raised"], row["state_code"]))
    return summary_rows


def fetch_state_campaign_finance_detail(
    conn: psycopg.Connection,
    state_code: str,
    *,
    top_n: int = 5,
) -> dict[str, Any] | None:
    if state_code not in _LAUNCH_SCOPE_STATE_CODE_SET:
        return None

    summary_row = next(
        (row for row in fetch_state_campaign_finance_summaries(conn) if row["state_code"] == state_code),
        None,
    )
    if summary_row is None:
        return None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_STATE_TOP_CANDIDATES_SQL, (state_code, state_code, top_n))
        top_candidate_rows = list(cursor.fetchall())
        cursor.execute(_STATE_TOP_COMMITTEES_SQL, (state_code, top_n))
        top_committee_rows = list(cursor.fetchall())

        if summary_row["ie_support_total"] is None and summary_row["ie_oppose_total"] is None:
            top_ie_spender_rows: list[dict[str, Any]] = []
        else:
            cursor.execute(_STATE_TOP_IE_SPENDERS_SQL, (state_code, top_n))
            top_ie_spender_rows = list(cursor.fetchall())
        cursor.execute(_STATE_PROVENANCE_SQL, (state_code,))
        source_rows = list(cursor.fetchall())

    for top_candidate_row in top_candidate_rows:
        _quantize_money_fields(top_candidate_row, "total_raised")
    for top_committee_row in top_committee_rows:
        _quantize_money_fields(top_committee_row, "total_raised")
    for top_ie_spender_row in top_ie_spender_rows:
        _quantize_money_fields(top_ie_spender_row, "total_amount")

    return {
        **summary_row,
        "sources": source_rows,
        "top_candidates": top_candidate_rows,
        "top_committees": top_committee_rows,
        "top_ie_spenders": top_ie_spender_rows,
    }


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
