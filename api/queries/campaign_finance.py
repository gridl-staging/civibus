
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
import re
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
from api.contribution_insights_contract import (
    CONTRIBUTION_INSIGHTS_MIN_DATE,
    CONTRIBUTION_INSIGHTS_SOURCE_RECORD_JOIN_SQL,
    CONTRIBUTION_INSIGHTS_SOURCE_RECORD_WHERE_SQL,
    RECEIPT_TYPE_PREFIX,
    contribution_insights_transaction_where_sql,
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

# Stage 5: FEC per-cycle official totals for a single committee. Cycles outside the
# supported window are excluded here so top-level aggregates and ``cycle_summaries``
# share one filter definition.
COMMITTEE_CYCLE_SUMMARIES_SQL = """
    SELECT
        cycle,
        total_receipts,
        total_disbursements,
        cash_on_hand,
        coverage_start_date,
        coverage_end_date
    FROM cf.committee_summary
    WHERE committee_id = %s
      AND cycle = ANY(%s)
    ORDER BY cycle ASC
"""

COMMITTEE_NAME_SQL = """
    SELECT name
    FROM cf.committee
    WHERE id = %s
"""

# Stage 5: candidates linked to a committee via active ``cf.candidate_committee_link``
# rows. Shape mirrors the public ``CandidateListItem`` DTO; the main candidate
# list query also carries an internal provenance field used before DTO validation.
COMMITTEE_LINKED_CANDIDATES_SQL = f"""
    SELECT DISTINCT
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
    FROM cf.candidate_committee_link link
    JOIN cf.candidate c ON c.id = link.candidate_id
    WHERE link.committee_id = %s
      AND link.valid_period @> CURRENT_DATE
    ORDER BY c.name ASC, c.id ASC
"""

# Stage 3: official FEC weball candidate totals. Populated by the bulk loader from
# weball{cycle}.zip rows. NULL when no weball row has loaded for the candidate, in
# which case the summary owner falls back to transaction-derived committee aggregates.
CANDIDATE_OFFICIAL_TOTALS_SQL = """
    SELECT
        total_receipts,
        total_disbursements,
        cash_on_hand
    FROM cf.candidate
    WHERE id = %s
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
DISBURSEMENT_TYPE_PREFIX = "2"
_COUNTY_TOP_LIST_LIMIT = 5
_COMMITTEE_TOP_PARTIES_LIMIT = 5
_COMMITTEE_SPEND_CATEGORY_LIMIT = 5
_COMMITTEE_IN_KIND_RECEIPT_CODE = "15Z"
_COMMITTEE_LOAN_RECEIPT_PREFIX = "16"

# Stage 5: cycles for which ``cf.committee_summary`` official totals are considered
# authoritative. Kept in sync with ``core.refresh.job_builders._active_committee_summary_cycles``
# — the loader writes these; this owner reads them. One definition for both the
# top-level committee aggregate and the per-cycle ``cycle_summaries`` payload.
SUPPORTED_COMMITTEE_SUMMARY_CYCLES: tuple[int, ...] = (2024, 2026)
CONTRIBUTION_INSIGHTS_CYCLES: tuple[int, ...] = (2022, 2024, 2026)
DONOR_SEARCH_MIN_QUERY_LEN = 3
DONOR_SEARCH_MAX_LIMIT = 50
_DONOR_SEARCH_SUPPORTED_MODES = frozenset({"name", "employer", "zip"})
_ZIP5_SEARCH_RE = re.compile(r"^\s*(\d{5})(?:-?\d{4})?\s*$")

# The <= $200 bucket mirrors FEC itemization; $3,300 tracks the federal per-election limit.
CONTRIBUTION_INSIGHTS_SIZE_BUCKETS: tuple[tuple[str, Decimal, Decimal | None], ...] = (
    ("$1-$200", Decimal("0.01"), Decimal("200.00")),
    ("$201-$500", Decimal("200.01"), Decimal("500.00")),
    ("$501-$3,300", Decimal("500.01"), Decimal("3300.00")),
    ("$3,301+", Decimal("3300.01"), None),
)

# Documented Stage 1 fallback: this maps counties to committee-registration cities.
# It is a proxy for outflow analysis, not donor-residence truth.
_COUNTY_PROXY_CITIES_BY_STATE: dict[str, dict[str, tuple[str, ...]]] = {
    "nc": {
        "wake": ("raleigh", "wake forest"),
    }
}

_PERSON_EXISTS_SQL = "SELECT 1 FROM core.person WHERE id = %s"

_PERSON_CONTRIBUTION_INSIGHTS_LINKED_COMMITTEES_SQL = """
    SELECT DISTINCT link.committee_id
    FROM cf.candidate candidate
    JOIN cf.candidate_committee_link link
      ON link.candidate_id = candidate.id
    WHERE candidate.person_id = %s
      AND link.valid_period @> CURRENT_DATE
    ORDER BY link.committee_id
"""

_PERSON_CONTRIBUTION_INSIGHTS_OFFICE_SQL = """
    SELECT
        o.name AS office_name,
        COALESCE(ed.state, o.state) AS state,
        ed.district_number AS district
    FROM civic.officeholding oh
    JOIN civic.office o ON o.id = oh.office_id
    LEFT JOIN civic.electoral_division ed ON ed.id = oh.electoral_division_id
    WHERE oh.person_id = %s
      AND oh.valid_period @> CURRENT_DATE
      AND o.office_level = 'federal'
    ORDER BY oh.id ASC
    LIMIT 1
"""

_INDIVIDUAL_RECEIPT_TRANSACTION_WHERE_SQL = contribution_insights_transaction_where_sql()

_NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL = """
          AND NOT EXISTS (
              SELECT 1
              FROM core.source_record superseded
              WHERE superseded.id = t.source_record_id
                AND superseded.superseded_by IS NOT NULL
          )
"""

_INDIVIDUAL_RECEIPT_QUALIFYING_WHERE_SQL = (
    _INDIVIDUAL_RECEIPT_TRANSACTION_WHERE_SQL + CONTRIBUTION_INSIGHTS_SOURCE_RECORD_WHERE_SQL
)

_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE = f"""
    WITH linked_committees AS (
        SELECT unnest(%s::uuid[]) AS committee_id
    ),
    qualifying_transactions AS (
        SELECT
            t.id,
            t.amount,
            t.transaction_date,
            t.contributor_name_raw,
            t.contributor_employer,
            t.contributor_city,
            t.contributor_state,
            LEFT(regexp_replace(COALESCE(t.contributor_zip, ''), '[^0-9]', '', 'g'), 5) AS zcta5
        FROM cf.transaction t
        JOIN linked_committees linked
          ON linked.committee_id = t.committee_id
{CONTRIBUTION_INSIGHTS_SOURCE_RECORD_JOIN_SQL}
        WHERE TRUE
{_INDIVIDUAL_RECEIPT_QUALIFYING_WHERE_SQL}
    )
"""

_PERSON_CONTRIBUTION_INSIGHTS_MONTHLY_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT
        to_char(date_trunc('month', transaction_date), 'YYYY-MM') AS month,
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions
    GROUP BY date_trunc('month', transaction_date)
    ORDER BY month ASC
"""

_PERSON_CONTRIBUTION_INSIGHTS_STATE_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT
        COALESCE(NULLIF(contributor_state, ''), 'Unknown') AS label,
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions
    GROUP BY label
    ORDER BY total_amount DESC, transaction_count DESC, label ASC
"""

_PERSON_CONTRIBUTION_INSIGHTS_TOTAL_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count,
        MAX(transaction_date) AS max_transaction_date
    FROM qualifying_transactions
"""

_PERSON_CONTRIBUTION_INSIGHTS_BUCKET_TOTALS_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions
    WHERE amount >= %s
      AND (%s::numeric IS NULL OR amount <= %s)
"""

_PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT label, total_amount, transaction_count
    FROM (
        SELECT
            CASE
                WHEN z.zcta5 IS NULL THEN 'Unknown district'
                WHEN qt.contributor_state = %s AND z.district_number = %s THEN 'In district'
                ELSE 'Out of district'
            END AS label,
            COALESCE(SUM(qt.amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count
        FROM qualifying_transactions qt
        LEFT JOIN civic.zcta_district z ON z.zcta5 = qt.zcta5
        GROUP BY label
        HAVING COUNT(*) > 0
    ) district_totals
    ORDER BY
        CASE label
            WHEN 'In district' THEN 1
            WHEN 'Out of district' THEN 2
            ELSE 3
        END
"""

_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_SQL = """
    SELECT
        COALESCE(SUM(individual_unitemized_contributions), 0) AS unitemized_total,
        COUNT(*)::integer AS summary_row_count,
        COUNT(DISTINCT committee_id)::integer AS summary_committee_count,
        ARRAY_REMOVE(ARRAY_AGG(DISTINCT cycle ORDER BY cycle), NULL) AS cycles_included,
        MAX(coverage_end_date) AS coverage_end_date
    FROM cf.committee_summary
    WHERE committee_id = ANY(%s)
      AND cycle = ANY(%s)
"""

_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_COVERAGE_SQL = """
    SELECT
        cycle,
        COUNT(DISTINCT committee_id)::integer AS committee_count
    FROM cf.committee_summary
    WHERE committee_id = ANY(%s)
      AND cycle = ANY(%s)
    GROUP BY cycle
    ORDER BY cycle ASC
"""

_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_BY_CYCLE_SQL = """
    SELECT
        cycle,
        COALESCE(SUM(individual_unitemized_contributions), 0) AS unitemized_individual_contribution_amount
    FROM cf.committee_summary
    WHERE committee_id = ANY(%s)
      AND cycle = ANY(%s)
    GROUP BY cycle
    ORDER BY cycle ASC
"""

_PERSON_CONTRIBUTION_INSIGHTS_ITEMIZED_BY_CYCLE_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT
        cycle,
        COALESCE(SUM(amount), 0) AS itemized_individual_contribution_amount,
        COUNT(*)::integer AS itemized_transaction_count
    FROM (
        SELECT
            CASE
                WHEN EXTRACT(YEAR FROM transaction_date)::integer %% 2 = 0
                    THEN EXTRACT(YEAR FROM transaction_date)::integer
                ELSE EXTRACT(YEAR FROM transaction_date)::integer + 1
            END AS cycle,
            amount
        FROM qualifying_transactions
    ) cycle_transactions
    GROUP BY cycle
    ORDER BY cycle ASC
"""

_DONOR_SEARCH_DONOR_JOIN_SQL = """
    rollup.contributor_name IS NOT DISTINCT FROM dg.contributor_name
    AND rollup.contributor_employer IS NOT DISTINCT FROM dg.contributor_employer
    AND rollup.contributor_occupation IS NOT DISTINCT FROM dg.contributor_occupation
    AND rollup.contributor_city IS NOT DISTINCT FROM dg.contributor_city
    AND rollup.contributor_state IS NOT DISTINCT FROM dg.contributor_state
    AND rollup.normalized_zip5 IS NOT DISTINCT FROM dg.normalized_zip5
"""

_DONOR_SEARCH_SQL_TEMPLATE = f"""
    WITH current_federal_candidate_committees AS (
        SELECT DISTINCT ON (candidate.person_id, link.committee_id)
            candidate.person_id,
            candidate.id AS candidate_id,
            candidate.fec_candidate_id,
            candidate.name AS candidate_name,
            link.committee_id,
            committee.fec_committee_id,
            committee.name AS committee_name
        FROM civic.officeholding officeholding
        JOIN civic.office office
          ON office.id = officeholding.office_id
        JOIN cf.candidate candidate
          ON candidate.person_id = officeholding.person_id
        JOIN cf.candidate_committee_link link
          ON link.candidate_id = candidate.id
        JOIN cf.committee committee
          ON committee.id = link.committee_id
        WHERE officeholding.valid_period @> CURRENT_DATE
          AND office.office_level = 'federal'
          AND candidate.person_id IS NOT NULL
          AND link.valid_period @> CURRENT_DATE
        ORDER BY
            candidate.person_id,
            link.committee_id,
            candidate.name ASC,
            candidate.id ASC
    ),
    matching_transactions AS MATERIALIZED (
        -- This is the first materialized transaction boundary: keeping the
        -- mode predicate, current-federal committee scope, receipt filters,
        -- date window, and source-record validity together prevents broad
        -- high-frequency donor matches from being materialized before the
        -- join-and-aggregate path. Do not cap matched rows here: donor LIMIT
        -- belongs after GROUP BY so high-volume donors are counted completely
        -- before pagination. Source validity uses an anti-superseded check
        -- here; provenance details are fetched after donor rollup so the live
        -- path does not do source-record lookups for every matched row.
        SELECT
            t.id,
            t.committee_id,
            t.amount,
            t.transaction_date,
            BTRIM(t.contributor_name_raw) AS contributor_name,
            NULLIF(BTRIM(t.contributor_employer), '') AS contributor_employer,
            NULLIF(BTRIM(t.contributor_occupation), '') AS contributor_occupation,
            NULLIF(BTRIM(t.contributor_city), '') AS contributor_city,
            NULLIF(BTRIM(t.contributor_state), '') AS contributor_state,
            NULLIF(LEFT(t.contributor_zip, 5), '') AS normalized_zip5,
            t.source_record_id
        FROM cf.transaction t
        WHERE {{match_sql}}
{_INDIVIDUAL_RECEIPT_TRANSACTION_WHERE_SQL}
{_NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}
          AND t.contributor_name_raw IS NOT NULL
          AND BTRIM(t.contributor_name_raw) != ''
          AND EXISTS (
              SELECT 1
              FROM current_federal_candidate_committees scope
              WHERE scope.committee_id = t.committee_id
          )
    ),
    qualifying_transactions AS (
        SELECT
            t.id,
            t.amount,
            t.transaction_date,
            t.contributor_name,
            t.contributor_employer,
            t.contributor_occupation,
            t.contributor_city,
            t.contributor_state,
            t.normalized_zip5,
            scope.person_id,
            scope.candidate_id,
            scope.fec_candidate_id,
            scope.candidate_name,
            scope.committee_id,
            scope.fec_committee_id,
            scope.committee_name,
            t.source_record_id
        FROM matching_transactions t
        JOIN current_federal_candidate_committees scope
          ON scope.committee_id = t.committee_id
    ),
    donor_groups AS (
        SELECT
            (ARRAY_AGG(id ORDER BY id ASC))[1] AS id,
            contributor_name,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            normalized_zip5,
            COALESCE(SUM(amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count,
            MAX(transaction_date) AS latest_transaction_date
        FROM qualifying_transactions
        GROUP BY
            contributor_name,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            normalized_zip5
        ORDER BY total_amount DESC, transaction_count DESC, contributor_name ASC, id ASC
        LIMIT %s
        OFFSET %s
    ),
    recipient_rollups AS (
        SELECT
            contributor_name,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            normalized_zip5,
            person_id,
            (ARRAY_AGG(candidate_id ORDER BY candidate_name ASC, candidate_id ASC, committee_name ASC, committee_id ASC))[1]
                AS candidate_id,
            (ARRAY_AGG(fec_candidate_id ORDER BY candidate_name ASC, candidate_id ASC, committee_name ASC, committee_id ASC))[1]
                AS fec_candidate_id,
            (ARRAY_AGG(candidate_name ORDER BY candidate_name ASC, candidate_id ASC, committee_name ASC, committee_id ASC))[1]
                AS candidate_name,
            (ARRAY_AGG(committee_id ORDER BY candidate_name ASC, candidate_id ASC, committee_name ASC, committee_id ASC))[1]
                AS committee_id,
            (ARRAY_AGG(fec_committee_id ORDER BY candidate_name ASC, candidate_id ASC, committee_name ASC, committee_id ASC))[1]
                AS fec_committee_id,
            (ARRAY_AGG(committee_name ORDER BY candidate_name ASC, candidate_id ASC, committee_name ASC, committee_id ASC))[1]
                AS committee_name,
            COALESCE(SUM(amount), 0) AS recipient_total_amount,
            COUNT(*)::integer AS recipient_transaction_count
        FROM qualifying_transactions
        GROUP BY
            contributor_name,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            normalized_zip5,
            person_id
    ),
    source_rollups AS (
        SELECT DISTINCT
            source.contributor_name,
            source.contributor_employer,
            source.contributor_occupation,
            source.contributor_city,
            source.contributor_state,
            source.normalized_zip5,
            sr.id AS source_record_id,
            ds.domain,
            ds.jurisdiction,
            ds.name AS data_source_name,
            ds.source_url AS data_source_url,
            sr.source_record_key,
            sr.source_url AS record_url,
            sr.pull_date
        FROM qualifying_transactions source
        JOIN donor_groups dg
          ON {_DONOR_SEARCH_DONOR_JOIN_SQL.replace("rollup.", "source.")}
        JOIN core.source_record sr
          ON sr.id = source.source_record_id AND sr.superseded_by IS NULL
        JOIN core.data_source ds
          ON ds.id = sr.data_source_id
        WHERE source.source_record_id IS NOT NULL
    )
    SELECT
        dg.id,
        dg.contributor_name,
        dg.contributor_employer,
        dg.contributor_occupation,
        dg.contributor_city,
        dg.contributor_state,
        dg.normalized_zip5,
        dg.total_amount,
        dg.transaction_count,
        dg.latest_transaction_date,
        recipient.person_id,
        recipient.candidate_id,
        recipient.fec_candidate_id,
        recipient.candidate_name,
        recipient.committee_id,
        recipient.fec_committee_id,
        recipient.committee_name,
        recipient.recipient_total_amount,
        recipient.recipient_transaction_count,
        source.source_record_id,
        source.domain,
        source.jurisdiction,
        source.data_source_name,
        source.data_source_url,
        source.source_record_key,
        source.record_url,
        source.pull_date
    FROM donor_groups dg
    LEFT JOIN recipient_rollups recipient
      ON {_DONOR_SEARCH_DONOR_JOIN_SQL.replace("rollup.", "recipient.")}
    LEFT JOIN source_rollups source
      ON {_DONOR_SEARCH_DONOR_JOIN_SQL.replace("rollup.", "source.")}
    ORDER BY
        dg.total_amount DESC,
        dg.transaction_count DESC,
        dg.contributor_name ASC,
        dg.id ASC,
        recipient.recipient_total_amount DESC NULLS LAST,
        recipient.recipient_transaction_count DESC NULLS LAST,
        recipient.candidate_name ASC NULLS LAST,
        recipient.person_id ASC NULLS LAST,
        source.pull_date DESC NULLS LAST,
        source.source_record_key ASC NULLS LAST
"""


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
        c.source_record_id,
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

# Stage 5: single-row FEC Schedule E amounts above this ceiling are treated as
# data-quality outliers in aggregate summary owners and excluded from aggregate
# totals/counts/top spenders. Raw IE transaction lists stay source-faithful.
CANDIDATE_IE_OUTLIER_CEILING: Decimal = Decimal("100000000.00")
_IE_OUTLIER_WHERE_CLAUSE = "t.amount <= %s"

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

_STATE_TOP_IE_SPENDERS_SQL = f"""
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
      AND {_IE_OUTLIER_WHERE_CLAUSE}
    GROUP BY c.id, c.name
    ORDER BY total_amount DESC, c.id ASC
    LIMIT %s
"""

_STATE_IE_OUTLIER_COUNT_SQL = """
    SELECT COUNT(*)::integer AS excluded_outlier_count
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
      AND t.amount > %s
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


def _normalize_donor_search_input(*, q: str, by: str, limit: int, offset: int) -> tuple[str, str, int, int]:
    """Validate and normalize donor-search inputs and clamp pagination bounds.

    The query mode is lowercased and validated against the supported name,
    employer, and ZIP modes. Name and employer searches require the minimum
    searchable length, ZIP searches accept ZIP+4 but return ZIP5, limit clamps
    to the public maximum, and offset never goes below zero.
    """
    normalized_by = by.strip().lower()
    if normalized_by not in _DONOR_SEARCH_SUPPORTED_MODES:
        raise ValueError(f"Unsupported donor search mode: {by}")

    normalized_query = q.strip()
    if normalized_by in {"name", "employer"} and len(normalized_query) < DONOR_SEARCH_MIN_QUERY_LEN:
        raise ValueError(f"Donor {normalized_by} searches require at least {DONOR_SEARCH_MIN_QUERY_LEN} characters")

    if normalized_by == "zip":
        zip_match = _ZIP5_SEARCH_RE.fullmatch(normalized_query)
        if zip_match is None:
            raise ValueError("Donor ZIP searches require a 5-digit ZIP or ZIP+4 query")
        normalized_query = zip_match.group(1)

    clamped_limit = max(1, min(limit, DONOR_SEARCH_MAX_LIMIT))
    clamped_offset = max(0, offset)
    return normalized_query, normalized_by, clamped_limit, clamped_offset


def _donor_search_match_sql(by: str) -> str:
    if by == "name":
        return "t.contributor_name_raw IS NOT NULL AND LOWER(t.contributor_name_raw) LIKE '%%' || LOWER(%s) || '%%'"
    if by == "employer":
        return "t.contributor_employer IS NOT NULL AND LOWER(t.contributor_employer) LIKE '%%' || LOWER(%s) || '%%'"
    if by == "zip":
        return "t.contributor_zip IS NOT NULL AND LEFT(t.contributor_zip, 5) = %s"
    raise ValueError(f"Unsupported donor search mode: {by}")


def _build_donor_search_statement(
    *,
    q: str,
    by: str,
    limit: int,
    offset: int,
) -> tuple[str, tuple[object, ...]]:
    """Build the donor-search SQL string and ordered DB parameters.

    The selected search mode controls only the match predicate interpolated into
    the shared SQL template; the returned parameters carry the normalized query,
    contribution start date, clamped limit, and clamped offset.
    """
    normalized_query, normalized_by, clamped_limit, clamped_offset = _normalize_donor_search_input(
        q=q,
        by=by,
        limit=limit,
        offset=offset,
    )
    return (
        _DONOR_SEARCH_SQL_TEMPLATE.format(match_sql=_donor_search_match_sql(normalized_by)),
        (normalized_query, CONTRIBUTION_INSIGHTS_MIN_DATE, clamped_limit, clamped_offset),
    )


def _empty_donor_search_payload(*, q: str, by: str, limit: int, offset: int) -> dict[str, Any]:
    return {
        "query": q,
        "by": by,
        "limit": limit,
        "offset": offset,
        "results": [],
    }


def _source_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": row["domain"],
        "jurisdiction": row["jurisdiction"],
        "data_source_name": row["data_source_name"],
        "data_source_url": row["data_source_url"],
        "source_record_key": row["source_record_key"],
        "record_url": row["record_url"],
        "pull_date": row["pull_date"],
    }


def _recipient_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "person_id": row["person_id"],
        "candidate_id": row["candidate_id"],
        "fec_candidate_id": row["fec_candidate_id"],
        "candidate_name": row["candidate_name"],
        "committee_id": row["committee_id"],
        "fec_committee_id": row["fec_committee_id"],
        "committee_name": row["committee_name"],
        "total_amount": _quantize_money(row["recipient_total_amount"]),
        "transaction_count": row["recipient_transaction_count"],
    }


def _donor_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "contributor_name": row["contributor_name"],
        "contributor_employer": row["contributor_employer"],
        "contributor_occupation": row["contributor_occupation"],
        "contributor_city": row["contributor_city"],
        "contributor_state": row["contributor_state"],
        "normalized_zip5": row["normalized_zip5"],
        "total_amount": _quantize_money(row["total_amount"]),
        "transaction_count": row["transaction_count"],
        "latest_transaction_date": row["latest_transaction_date"],
        "recipients": [],
        "sources": [],
    }


def _shape_donor_search_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape joined donor rows and de-duplicate nested details.

    The flat SQL result can contain repeated donor rows for multiple recipients
    and provenance rows. This function preserves donor order, emits each donor
    once, and de-duplicates recipients by person ID and sources by source record.
    """
    donors: list[dict[str, Any]] = []
    donors_by_id: dict[UUID, dict[str, Any]] = {}
    recipient_keys_by_donor_id: dict[UUID, set[UUID]] = {}
    source_keys_by_donor_id: dict[UUID, set[UUID]] = {}

    for row in rows:
        donor_id = row["id"]
        donor = donors_by_id.get(donor_id)
        if donor is None:
            donor = _donor_payload(row)
            donors.append(donor)
            donors_by_id[donor_id] = donor
            recipient_keys_by_donor_id[donor_id] = set()
            source_keys_by_donor_id[donor_id] = set()

        if row["person_id"] is not None:
            recipient_key = row["person_id"]
            if recipient_key not in recipient_keys_by_donor_id[donor_id]:
                donor["recipients"].append(_recipient_payload(row))
                recipient_keys_by_donor_id[donor_id].add(recipient_key)

        if row["source_record_id"] is not None and row["source_record_id"] not in source_keys_by_donor_id[donor_id]:
            donor["sources"].append(_source_payload(row))
            source_keys_by_donor_id[donor_id].add(row["source_record_id"])

    return donors


def search_donors(
    conn: psycopg.Connection,
    *,
    q: str,
    by: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Public donor-search fetcher returning the API payload contract.

    Validates and normalizes request inputs, executes the shared donor SQL with
    dict rows, and returns query metadata plus shaped donor results. Empty result
    sets still include the public payload fields with the normalized mode and
    clamped pagination values.
    """
    normalized_query, normalized_by, clamped_limit, clamped_offset = _normalize_donor_search_input(
        q=q,
        by=by,
        limit=limit,
        offset=offset,
    )
    sql, params = _build_donor_search_statement(
        q=normalized_query,
        by=normalized_by,
        limit=clamped_limit,
        offset=clamped_offset,
    )

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        rows = list(cursor.fetchall())

    if not rows:
        return _empty_donor_search_payload(q=q, by=normalized_by, limit=clamped_limit, offset=clamped_offset)

    return {
        "query": q,
        "by": normalized_by,
        "limit": clamped_limit,
        "offset": clamped_offset,
        "results": _shape_donor_search_results(rows),
    }


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


def fetch_committee_linked_candidates(conn: psycopg.Connection, committee_id: UUID) -> list[dict[str, Any]]:
    """Return active candidates linked to a committee, ordered by candidate name.

    Rows are shaped like ``CandidateListItem`` so Stage 6 can route by ``person_id``
    / slug through the same detail contract already used for the candidate list.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_LINKED_CANDIDATES_SQL, (committee_id,))
        return list(cursor.fetchall())


def _fetch_committee_name(conn: psycopg.Connection, committee_id: UUID) -> str | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_NAME_SQL, (committee_id,))
        row = cursor.fetchone()
    if row is None:
        return None
    return row["name"]


def _fetch_committee_cycle_summaries(conn: psycopg.Connection, committee_id: UUID) -> list[dict[str, Any]]:
    """Load supported-cycle official rows from ``cf.committee_summary``.

    Returned in ascending cycle order with money fields quantized to the standard
    scale so the payload matches ``CommitteeCycleSummary`` without further work
    in the caller.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            COMMITTEE_CYCLE_SUMMARIES_SQL,
            (committee_id, list(SUPPORTED_COMMITTEE_SUMMARY_CYCLES)),
        )
        cycle_rows = list(cursor.fetchall())

    for cycle_row in cycle_rows:
        cycle_row["total_receipts"] = _quantize_money(cycle_row["total_receipts"] or 0)
        cycle_row["total_disbursements"] = _quantize_money(cycle_row["total_disbursements"] or 0)
        if cycle_row["cash_on_hand"] is not None:
            cycle_row["cash_on_hand"] = _quantize_money(cycle_row["cash_on_hand"])
    return cycle_rows


def _apply_committee_official_totals(payload: dict[str, Any], cycle_summaries: list[dict[str, Any]]) -> None:
    """Overwrite top-level totals with the sum of supported-cycle official rows.

    Mutates ``payload`` in place. ``transaction_count`` and the receipt breakdown
    (in-kind, loans, contribution, cash) stay derived because the committee-summary
    feed does not carry those columns row-for-row; ``itemized_transaction_count``
    mirrors ``transaction_count`` so the truthful count stays surfaced next to the
    official totals.
    """
    official_receipts = sum((row["total_receipts"] for row in cycle_summaries), start=_MONEY_SCALE)
    official_disbursements = sum((row["total_disbursements"] for row in cycle_summaries), start=_MONEY_SCALE)
    payload["total_raised"] = official_receipts
    payload["total_spent"] = official_disbursements
    payload["net"] = official_receipts - official_disbursements
    payload["summary_source"] = "fec_committee_summary"


def fetch_committee_fundraising_summary(
    conn: psycopg.Connection,
    committee_id: UUID,
) -> dict[str, Any] | None:
    """Aggregate fundraising totals for a single committee.

    Stage 5 contract:
    - Derived totals (from qualifying transactions) are always computed.
    - Supported-cycle official rows from ``cf.committee_summary`` — filtered by
      ``SUPPORTED_COMMITTEE_SUMMARY_CYCLES`` — are attached under ``cycle_summaries``.
    - When any supported-cycle row exists, top-level ``total_raised`` / ``total_spent``
      / ``net`` are overwritten with the sum of those official rows and
      ``summary_source`` becomes ``"fec_committee_summary"``. Otherwise the derived
      totals win and ``summary_source`` stays ``"derived"``.
    - ``transaction_count`` and ``itemized_transaction_count`` are always the
      derived qualifying-transaction count.
    - Returns ``None`` only when there are no qualifying transactions AND no
      supported-cycle official rows, so the caller can substitute a zero payload.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_FUNDRAISING_SUMMARY_SQL, (committee_id, committee_id))
        summary_row = cursor.fetchone()

        cursor.execute(COMMITTEE_TOP_DONORS_SQL, (committee_id, _COMMITTEE_TOP_PARTIES_LIMIT))
        top_donor_rows = list(cursor.fetchall())

        cursor.execute(COMMITTEE_TOP_VENDORS_SQL, (committee_id, _COMMITTEE_TOP_PARTIES_LIMIT))
        top_vendor_rows = list(cursor.fetchall())

        cursor.execute(COMMITTEE_SPEND_CATEGORY_SUMMARY_SQL, (committee_id, _COMMITTEE_SPEND_CATEGORY_LIMIT))
        spend_category_rows = list(cursor.fetchall())

    cycle_summaries = _fetch_committee_cycle_summaries(conn, committee_id)

    if summary_row is None and not cycle_summaries:
        return None

    if summary_row is None:
        # Official cycle rows exist but no itemized transactions — the caller
        # still needs a fully valid committee summary payload.
        committee_name = _fetch_committee_name(conn, committee_id)
        if committee_name is None:
            return None
        summary_row = {
            "committee_id": committee_id,
            "committee_name": committee_name,
            "total_raised": _MONEY_SCALE,
            "total_spent": _MONEY_SCALE,
            "net": _MONEY_SCALE,
            "cash_receipts_total": _MONEY_SCALE,
            "in_kind_receipts_total": _MONEY_SCALE,
            "loan_receipts_total": _MONEY_SCALE,
            "contribution_receipts_total": _MONEY_SCALE,
            "transaction_count": 0,
            "jurisdiction": None,
            "data_through": None,
        }
    else:
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
    summary_row["cycle_summaries"] = cycle_summaries
    summary_row["itemized_transaction_count"] = summary_row["transaction_count"]
    summary_row["summary_source"] = "derived"

    if cycle_summaries:
        _apply_committee_official_totals(summary_row, cycle_summaries)

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
        # Stage 5: parallel-empty fields so the DTO stays complete at zero.
        "itemized_transaction_count": 0,
        "cycle_summaries": [],
        "summary_source": "derived",
    }


def build_zero_candidate_fundraising_summary(*, candidate_id: UUID, candidate_name: str) -> dict[str, Any]:
    """Return the stable zero-total payload for candidates without linked committees.

    The default ``summary_source`` is ``"derived"`` because no FEC weball totals
    are known in this branch. Callers that have official totals build their own
    payload via ``fetch_candidate_summary``.
    """
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "total_raised": _MONEY_SCALE,
        "total_spent": _MONEY_SCALE,
        "net": _MONEY_SCALE,
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [],
        "cash_on_hand": None,
        "summary_source": "derived",
    }


def _has_official_candidate_totals(official_row: dict[str, Any]) -> bool:
    """True when any of the three FEC weball candidate totals are populated.

    Treating any populated column as a signal lets us surface official totals
    even on the (rare) shape where TTL_DISB is NULL in the weball feed.
    """
    return (
        official_row["total_receipts"] is not None
        or official_row["total_disbursements"] is not None
        or official_row["cash_on_hand"] is not None
    )


def fetch_candidate_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    candidate_name: str,
) -> dict[str, Any] | None:
    """Aggregate fundraising totals for a candidate.

    Stage 3 contract:
    - When the ``cf.candidate`` row has any FEC weball total populated, those
      official totals are returned with ``summary_source="fec_weball"``. Net is
      computed as ``total_receipts - total_disbursements``.
    - Otherwise, the existing derived path sums active linked committee totals
      and returns ``summary_source="derived"``.
    - Candidates with no linked committees AND no official totals return a zero
      payload (not ``None``) so callers do not need a route-level workaround.
    - ``None`` is reserved for the defensive case where the candidate row itself
      is missing; the route validates this separately, so it is unreachable in
      practice.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CANDIDATE_OFFICIAL_TOTALS_SQL, (candidate_id,))
        official_row = cursor.fetchone()

    if official_row is None:
        return None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CANDIDATE_LINKED_COMMITTEE_IDS_SQL, (candidate_id,))
        linked_committee_rows = list(cursor.fetchall())

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

    derived_transaction_count = sum(committee["transaction_count"] for committee in committee_summaries)

    if _has_official_candidate_totals(official_row):
        total_receipts = official_row["total_receipts"] or _MONEY_SCALE
        total_disbursements = official_row["total_disbursements"] or _MONEY_SCALE
        return {
            "candidate_id": candidate_id,
            "candidate_name": candidate_name,
            "total_raised": total_receipts,
            "total_spent": total_disbursements,
            "net": total_receipts - total_disbursements,
            # Transaction count remains the committee-derived count: the official
            # weball totals do not carry one, and surfacing 0 here would be
            # misleading when itemized transactions exist for linked committees.
            "transaction_count": derived_transaction_count,
            "itemized_transaction_count": derived_transaction_count,
            "committees": committee_summaries,
            "cash_on_hand": official_row["cash_on_hand"],
            "summary_source": "fec_weball",
        }

    derived_total_raised = sum((committee["total_raised"] for committee in committee_summaries), start=_MONEY_SCALE)
    derived_total_spent = sum((committee["total_spent"] for committee in committee_summaries), start=_MONEY_SCALE)
    derived_net = sum((committee["net"] for committee in committee_summaries), start=_MONEY_SCALE)
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "total_raised": derived_total_raised,
        "total_spent": derived_total_spent,
        "net": derived_net,
        "transaction_count": derived_transaction_count,
        "itemized_transaction_count": derived_transaction_count,
        "committees": committee_summaries,
        "cash_on_hand": None,
        "summary_source": "derived",
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
        filing_row["row_id"] = f"{filing_row['filing_id']}:{filing_row['amendment_indicator']}"
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
    if registry_row.tier == _STATE_SUMMARY_SUPPORTED_TIER and registry_row.ie_coverage_available is False:
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
            excluded_outlier_count = 0
        else:
            cursor.execute(_STATE_TOP_IE_SPENDERS_SQL, (state_code, CANDIDATE_IE_OUTLIER_CEILING, top_n))
            top_ie_spender_rows = list(cursor.fetchall())
            cursor.execute(_STATE_IE_OUTLIER_COUNT_SQL, (state_code, CANDIDATE_IE_OUTLIER_CEILING))
            excluded_outlier_count = cursor.fetchone()["excluded_outlier_count"]
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
        "excluded_outlier_count": excluded_outlier_count,
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
      AND {_IE_OUTLIER_WHERE_CLAUSE}
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
      AND {_IE_OUTLIER_WHERE_CLAUSE}
    GROUP BY t.committee_id, c.name, t.support_oppose
    ORDER BY SUM(t.amount) DESC, t.committee_id ASC, t.support_oppose ASC
    LIMIT %s
"""

_CANDIDATE_IE_OUTLIER_COUNT_SQL = f"""
    SELECT COUNT(*)::integer AS excluded_outlier_count
    FROM cf.transaction t
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    {_CANDIDATE_IE_QUALIFYING_WHERE_SQL}
      AND t.amount > %s
"""


def _quantize_money(value: Any) -> Decimal:
    return Decimal(value).quantize(_MONEY_SCALE)


def _quantize_money_fields(row: dict[str, Any], *field_names: str) -> None:
    for field_name in field_names:
        row[field_name] = _quantize_money(row[field_name])


def _zero_person_contribution_insights(person_id: UUID, *, excluded_geography: str) -> dict[str, Any]:
    """Return the stable empty contribution-insights payload for a known person."""
    return {
        "person_id": person_id,
        "has_data": False,
        "metadata": {
            "coverage_start_date": CONTRIBUTION_INSIGHTS_MIN_DATE,
            "coverage_end_date": None,
            "cycles_included": [],
            "committee_count": 0,
            "approximate_geography": False,
            "excluded_geography": excluded_geography,
            "caveats": [],
        },
        "monthly_totals": [],
        "itemized_size_buckets": [],
        "dollars_by_size": [],
        "cycle_totals": [],
        "career_totals": _zero_person_insights_career_totals(),
        "geography": {
            "by_state": [],
            "by_district": [],
            "district_share": _district_dollar_share([]),
        },
        "small_dollar_share": {
            "small_dollar_amount": None,
            "total_contribution_amount": None,
            "share": None,
            "available": False,
        },
    }


def _fetch_person_insights_linked_committee_ids(conn: psycopg.Connection, person_id: UUID) -> list[UUID]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_CONTRIBUTION_INSIGHTS_LINKED_COMMITTEES_SQL, (person_id,))
        return [row["committee_id"] for row in cursor.fetchall()]


def _fetch_person_insights_office(conn: psycopg.Connection, person_id: UUID) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_CONTRIBUTION_INSIGHTS_OFFICE_SQL, (person_id,))
        return cursor.fetchone()


def _fetch_person_insights_rows(
    conn: psycopg.Connection,
    query: str,
    committee_ids: list[UUID],
    *extra_params: object,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, (committee_ids, CONTRIBUTION_INSIGHTS_MIN_DATE, *extra_params))
        rows = list(cursor.fetchall())
    for row in rows:
        if "total_amount" in row:
            row["total_amount"] = _quantize_money(row["total_amount"])
    return rows


def _fetch_person_insights_one(
    conn: psycopg.Connection,
    query: str,
    committee_ids: list[UUID],
    *extra_params: object,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, (committee_ids, CONTRIBUTION_INSIGHTS_MIN_DATE, *extra_params))
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Contribution insights aggregate query returned no row")
    if "total_amount" in row:
        row["total_amount"] = _quantize_money(row["total_amount"])
    return row


def _zero_person_insights_career_totals() -> dict[str, Any]:
    return {
        "itemized_individual_contribution_amount": _quantize_money(0),
        "itemized_transaction_count": 0,
        "unitemized_individual_contribution_amount": _quantize_money(0),
        "total_individual_contribution_amount": _quantize_money(0),
        "source": "none",
    }


def _fetch_person_insights_summary(conn: psycopg.Connection, committee_ids: list[UUID]) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_SQL, (committee_ids, list(CONTRIBUTION_INSIGHTS_CYCLES)))
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Contribution insights summary query returned no row")
    row["unitemized_total"] = _quantize_money(row["unitemized_total"])
    row["cycles_included"] = list(row["cycles_included"] or [])
    return row


def _fetch_person_insights_summary_coverage(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_COVERAGE_SQL,
            (committee_ids, list(CONTRIBUTION_INSIGHTS_CYCLES)),
        )
        return list(cursor.fetchall())


def _fetch_person_insights_summary_cycle_totals(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_BY_CYCLE_SQL,
            (committee_ids, list(CONTRIBUTION_INSIGHTS_CYCLES)),
        )
        rows = list(cursor.fetchall())
    for row in rows:
        row["unitemized_individual_contribution_amount"] = _quantize_money(
            row["unitemized_individual_contribution_amount"]
        )
    return rows


def _fetch_person_insights_itemized_cycle_totals(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_ITEMIZED_BY_CYCLE_SQL,
            (committee_ids, CONTRIBUTION_INSIGHTS_MIN_DATE),
        )
        rows = list(cursor.fetchall())
    for row in rows:
        row["itemized_individual_contribution_amount"] = _quantize_money(row["itemized_individual_contribution_amount"])
    return rows


def _has_complete_person_insights_summary(
    summary_row: dict[str, Any],
    summary_coverage_rows: list[dict[str, Any]],
    committee_count: int,
) -> bool:
    if summary_row["summary_committee_count"] != committee_count:
        return False
    return all(row["committee_count"] == committee_count for row in summary_coverage_rows)


def _build_person_insights_itemized_buckets(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Build backend-owned itemized size buckets from qualifying Schedule A rows."""
    buckets: list[dict[str, Any]] = []
    for label, min_amount, max_amount in CONTRIBUTION_INSIGHTS_SIZE_BUCKETS:
        row = _fetch_person_insights_one(
            conn,
            _PERSON_CONTRIBUTION_INSIGHTS_BUCKET_TOTALS_SQL,
            committee_ids,
            min_amount,
            max_amount,
            max_amount,
        )
        buckets.append(
            {
                "label": label,
                "min_amount": _quantize_money(min_amount),
                "max_amount": _quantize_money(max_amount) if max_amount is not None else None,
                "total_amount": row["total_amount"],
                "transaction_count": row["transaction_count"],
            }
        )
    return buckets


def _dollars_by_size(
    itemized_buckets: list[dict[str, Any]],
    unitemized_total: Decimal,
    *,
    summary_available: bool,
) -> list[dict[str, Any]]:
    """Build dollars buckets, including unitemized dollars when summary totals are complete."""
    dollars: list[dict[str, Any]] = []
    if summary_available:
        dollars.append({"label": "Unitemized (<$200)", "total_amount": unitemized_total, "source": "committee_summary"})
    for bucket in itemized_buckets:
        dollars.append(
            {
                "label": f"{bucket['label']} itemized",
                "total_amount": bucket["total_amount"],
                "source": "transactions",
            }
        )
    return dollars


def _build_person_insights_cycle_totals(
    itemized_cycle_rows: list[dict[str, Any]],
    summary_cycle_rows: list[dict[str, Any]],
    *,
    summary_available: bool,
) -> list[dict[str, Any]]:
    itemized_by_cycle = {row["cycle"]: row for row in itemized_cycle_rows}
    summary_by_cycle = {row["cycle"]: row for row in summary_cycle_rows} if summary_available else {}
    cycle_values = sorted(itemized_by_cycle.keys() | summary_by_cycle.keys())

    cycle_totals: list[dict[str, Any]] = []
    for cycle in cycle_values:
        itemized_row = itemized_by_cycle.get(cycle, {})
        summary_row = summary_by_cycle.get(cycle, {})
        itemized_amount = itemized_row.get("itemized_individual_contribution_amount", _quantize_money(0))
        unitemized_amount = summary_row.get("unitemized_individual_contribution_amount", _quantize_money(0))
        source = "committee_summary" if summary_row else "itemized_transactions"
        cycle_totals.append(
            {
                "cycle": cycle,
                "itemized_individual_contribution_amount": itemized_amount,
                "itemized_transaction_count": itemized_row.get("itemized_transaction_count", 0),
                "unitemized_individual_contribution_amount": unitemized_amount,
                "total_individual_contribution_amount": _quantize_money(itemized_amount + unitemized_amount),
                "source": source,
            }
        )
    return cycle_totals


def _build_person_insights_career_totals(cycle_totals: list[dict[str, Any]]) -> dict[str, Any]:
    if not cycle_totals:
        return _zero_person_insights_career_totals()

    cycle_sources = {row["source"] for row in cycle_totals}
    itemized_amount = sum(
        (row["itemized_individual_contribution_amount"] for row in cycle_totals),
        start=_quantize_money(0),
    )
    unitemized_amount = sum(
        (row["unitemized_individual_contribution_amount"] for row in cycle_totals),
        start=_quantize_money(0),
    )
    return {
        "itemized_individual_contribution_amount": _quantize_money(itemized_amount),
        "itemized_transaction_count": sum(row["itemized_transaction_count"] for row in cycle_totals),
        "unitemized_individual_contribution_amount": _quantize_money(unitemized_amount),
        "total_individual_contribution_amount": _quantize_money(itemized_amount + unitemized_amount),
        "source": cycle_totals[0]["source"] if len(cycle_sources) == 1 else "mixed_sources",
    }


def _district_rows(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    office_row: dict[str, Any] | None,
    caveats: list[str],
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Return district geography rows or the backend-owned omission reason."""
    if office_row is None:
        return [], False, "no_current_federal_officeholding"
    if office_row["office_name"] in {"us_president", "us_vice_president"}:
        return [], False, "federal_executive"
    if office_row["office_name"] == "us_senate":
        return [], False, "statewide_office"
    if not office_row["state"] or not office_row["district"]:
        return [], False, "missing_member_district"

    rows = _fetch_person_insights_rows(
        conn,
        _PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL,
        committee_ids,
        office_row["state"],
        office_row["district"],
    )
    matched_rows = [row for row in rows if row["label"] != "Unknown district"]
    unknown_rows = [row for row in rows if row["label"] == "Unknown district"]
    if unknown_rows:
        caveats.append("missing_zcta_district")
    if not matched_rows:
        return [], True, None
    return rows, True, None


def _small_dollar_share(
    itemized_buckets: list[dict[str, Any]],
    itemized_total: Decimal,
    unitemized_total: Decimal,
    *,
    summary_available: bool,
) -> dict[str, Any]:
    """Calculate the small-dollar share only when summary totals are complete."""
    if not summary_available:
        return {
            "small_dollar_amount": None,
            "total_contribution_amount": None,
            "share": None,
            "available": False,
        }
    small_dollar_amount = _quantize_money(itemized_buckets[0]["total_amount"] + unitemized_total)
    total_contribution_amount = _quantize_money(itemized_total + unitemized_total)
    share = Decimal("0.0000")
    if total_contribution_amount != 0:
        share = (small_dollar_amount / total_contribution_amount).quantize(Decimal("0.0001"))
    return {
        "small_dollar_amount": small_dollar_amount,
        "total_contribution_amount": total_contribution_amount,
        "share": share,
        "available": True,
    }


def _district_dollar_share(district_rows: list[dict[str, Any]]) -> dict[str, Any]:
    amounts = {
        "In district": Decimal("0.00"),
        "Out of district": Decimal("0.00"),
        "Unknown district": Decimal("0.00"),
    }
    for row in district_rows:
        label = str(row["label"])
        if label not in amounts:
            raise ValueError(f"Unexpected district contribution label: {label}")
        amounts[label] = _quantize_money(amounts[label] + row["total_amount"])

    in_district_amount = amounts["In district"]
    out_of_district_amount = amounts["Out of district"]
    unknown_district_amount = amounts["Unknown district"]
    classified_amount = in_district_amount + out_of_district_amount
    if classified_amount == 0:
        return {
            "in_district_amount": None,
            "out_of_district_amount": None,
            "unknown_district_amount": None,
            "share": None,
            "available": False,
        }

    # Unknown districts are surfaced separately, but excluded from the denominator
    # so incomplete ZIP-to-district matches do not dilute the in-district headline.
    share = (in_district_amount / classified_amount).quantize(Decimal("0.0001"))
    return {
        "in_district_amount": in_district_amount,
        "out_of_district_amount": out_of_district_amount,
        "unknown_district_amount": unknown_district_amount,
        "share": share,
        "available": True,
    }


def fetch_person_contribution_insights(conn: psycopg.Connection, person_id: UUID) -> dict[str, Any] | None:
    """Return person-level contribution insights for active linked candidate committees."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_EXISTS_SQL, (person_id,))
        if cursor.fetchone() is None:
            return None

    committee_ids = _fetch_person_insights_linked_committee_ids(conn, person_id)
    if not committee_ids:
        return _zero_person_contribution_insights(person_id, excluded_geography="no_linked_candidate")

    monthly_rows = _fetch_person_insights_rows(conn, _PERSON_CONTRIBUTION_INSIGHTS_MONTHLY_SQL, committee_ids)
    state_rows = _fetch_person_insights_rows(conn, _PERSON_CONTRIBUTION_INSIGHTS_STATE_SQL, committee_ids)
    totals_row = _fetch_person_insights_one(conn, _PERSON_CONTRIBUTION_INSIGHTS_TOTAL_SQL, committee_ids)
    itemized_buckets = _build_person_insights_itemized_buckets(conn, committee_ids)
    itemized_cycle_rows = _fetch_person_insights_itemized_cycle_totals(conn, committee_ids)
    summary_row = _fetch_person_insights_summary(conn, committee_ids)
    summary_coverage_rows = _fetch_person_insights_summary_coverage(conn, committee_ids)
    summary_cycle_rows = _fetch_person_insights_summary_cycle_totals(conn, committee_ids)

    caveats: list[str] = []
    summary_available = _has_complete_person_insights_summary(
        summary_row,
        summary_coverage_rows,
        len(committee_ids),
    )
    if not summary_available:
        caveats.append("missing_committee_summary")
        caveats.append("itemized_only_cycle_totals")

    office_row = _fetch_person_insights_office(conn, person_id)
    district_rows, approximate_geography, excluded_geography = _district_rows(conn, committee_ids, office_row, caveats)
    itemized_total = totals_row["total_amount"]
    coverage_end_date = summary_row["coverage_end_date"] if summary_available else totals_row["max_transaction_date"]
    cycles_included = summary_row["cycles_included"] if summary_available else []
    cycle_totals = _build_person_insights_cycle_totals(
        itemized_cycle_rows,
        summary_cycle_rows,
        summary_available=summary_available,
    )

    return {
        "person_id": person_id,
        "has_data": bool(monthly_rows or summary_available),
        "metadata": {
            "coverage_start_date": CONTRIBUTION_INSIGHTS_MIN_DATE,
            "coverage_end_date": coverage_end_date,
            "cycles_included": cycles_included,
            "committee_count": len(committee_ids),
            "approximate_geography": approximate_geography,
            "excluded_geography": excluded_geography,
            "caveats": caveats,
        },
        "monthly_totals": monthly_rows,
        "itemized_size_buckets": itemized_buckets,
        "dollars_by_size": _dollars_by_size(
            itemized_buckets,
            summary_row["unitemized_total"],
            summary_available=summary_available,
        ),
        "cycle_totals": cycle_totals,
        "career_totals": _build_person_insights_career_totals(cycle_totals),
        "geography": {
            "by_state": state_rows,
            "by_district": district_rows,
            "district_share": _district_dollar_share(district_rows),
        },
        "small_dollar_share": _small_dollar_share(
            itemized_buckets,
            itemized_total,
            summary_row["unitemized_total"],
            summary_available=summary_available,
        ),
    }


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
    """Fetch aggregated IE support/oppose totals and top spenders for a candidate.

    Stage 5: rows above ``CANDIDATE_IE_OUTLIER_CEILING`` are excluded from totals,
    counts, and top-spender rankings; the count of excluded rows is surfaced under
    ``excluded_outlier_count``. The raw list endpoint keeps returning every row.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CANDIDATE_IE_SUMMARY_SQL, (candidate_id, CANDIDATE_IE_OUTLIER_CEILING))
        summary_row = cursor.fetchone()
        if summary_row is None:
            raise RuntimeError(f"IE summary query returned no rows for candidate: {candidate_id}")

        cursor.execute(
            _CANDIDATE_IE_TOP_SPENDERS_SQL,
            (candidate_id, CANDIDATE_IE_OUTLIER_CEILING, top_spenders_limit),
        )
        top_spender_rows = list(cursor.fetchall())

        cursor.execute(_CANDIDATE_IE_OUTLIER_COUNT_SQL, (candidate_id, CANDIDATE_IE_OUTLIER_CEILING))
        outlier_count_row = cursor.fetchone()

    for top_spender_row in top_spender_rows:
        _quantize_money_fields(top_spender_row, "total_amount")

    excluded_outlier_count = 0 if outlier_count_row is None else outlier_count_row["excluded_outlier_count"]
    return {
        "candidate_id": candidate_id,
        "support_total": _quantize_money(summary_row["support_total"]),
        "oppose_total": _quantize_money(summary_row["oppose_total"]),
        "support_count": summary_row["support_count"],
        "oppose_count": summary_row["oppose_count"],
        "top_spenders": top_spender_rows,
        "excluded_outlier_count": excluded_outlier_count,
    }


_COMMITTEE_IE_CANDIDATE_SLUG_EXPR = _SLUG_NORMALIZE_EXPR.format(value="cand.name")
_COMMITTEE_IE_CANDIDATE_SLUG_IS_UNIQUE_SUBQUERY = f"""(
        SELECT COUNT(*) FROM cf.candidate cand2
        WHERE {_SLUG_NORMALIZE_EXPR.format(value="cand2.name")}
            = {_SLUG_NORMALIZE_EXPR.format(value="cand.name")}
    ) = 1"""

_COMMITTEE_IE_TARGETS_SQL = f"""
    SELECT
        cand.id AS candidate_id,
        cand.fec_candidate_id,
        cand.name AS candidate_name,
        cand.person_id,
        cand.party,
        cand.office,
        cand.state,
        cand.district,
        {_COMMITTEE_IE_CANDIDATE_SLUG_EXPR} AS slug,
        {_COMMITTEE_IE_CANDIDATE_SLUG_IS_UNIQUE_SUBQUERY} AS slug_is_unique,
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'S'), 0) AS support_total,
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'O'), 0) AS oppose_total,
        COUNT(*)::integer AS transaction_count
    FROM cf.transaction t
    JOIN cf.candidate cand
      ON cand.id = t.recipient_candidate_id
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    WHERE t.committee_id = %s
      AND t.support_oppose IS NOT NULL
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
      AND {_IE_OUTLIER_WHERE_CLAUSE}
    GROUP BY
        cand.id,
        cand.fec_candidate_id,
        cand.name,
        cand.person_id,
        cand.party,
        cand.office,
        cand.state,
        cand.district
    ORDER BY
        COALESCE(SUM(t.amount), 0) DESC,
        COUNT(*) DESC,
        cand.name ASC,
        cand.id ASC
    LIMIT %s
"""

_COMMITTEE_IE_TOTALS_SQL = f"""
    SELECT
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'S'), 0) AS support_total,
        COALESCE(SUM(t.amount) FILTER (WHERE t.support_oppose = 'O'), 0) AS oppose_total,
        COUNT(*)::integer AS ie_transaction_count
    FROM cf.transaction t
    JOIN cf.candidate cand
      ON cand.id = t.recipient_candidate_id
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    WHERE t.committee_id = %s
      AND t.support_oppose IS NOT NULL
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
      AND {_IE_OUTLIER_WHERE_CLAUSE}
"""

_COMMITTEE_IE_OUTLIER_COUNT_SQL = f"""
    SELECT COUNT(*)::integer AS excluded_outlier_count
    FROM cf.transaction t
    JOIN cf.candidate cand
      ON cand.id = t.recipient_candidate_id
    {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
    WHERE t.committee_id = %s
      AND t.support_oppose IS NOT NULL
      AND t.is_memo = FALSE
      AND t.amendment_indicator != 'T'
      AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
      AND t.amount > %s
"""

_COMMITTEE_IE_TARGET_SOURCES_SQL = f"""
    WITH dedup_source_ids AS (
        SELECT DISTINCT
            t.recipient_candidate_id AS candidate_id,
            t.source_record_id
        FROM cf.transaction t
        JOIN cf.candidate cand
          ON cand.id = t.recipient_candidate_id
        {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
        WHERE t.committee_id = %s
          AND t.recipient_candidate_id = ANY(%s)
          AND t.support_oppose IS NOT NULL
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
          AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
          AND {_IE_OUTLIER_WHERE_CLAUSE}
          AND t.source_record_id IS NOT NULL
    )
    SELECT
        ids.candidate_id,
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
    ORDER BY ids.candidate_id ASC, sr.pull_date DESC, sr.id ASC
"""


def _fetch_committee_ie_target_sources(
    conn: psycopg.Connection,
    *,
    committee_id: UUID,
    candidate_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    if not candidate_ids:
        return {}

    sources_by_candidate_id: dict[UUID, list[dict[str, Any]]] = {candidate_id: [] for candidate_id in candidate_ids}
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _COMMITTEE_IE_TARGET_SOURCES_SQL,
            (committee_id, candidate_ids, CANDIDATE_IE_OUTLIER_CEILING),
        )
        source_rows = list(cursor.fetchall())

    for source_row in source_rows:
        candidate_id = source_row.pop("candidate_id")
        sources_by_candidate_id.setdefault(candidate_id, []).append(source_row)
    return sources_by_candidate_id


def fetch_committee_ie_activity(
    conn: psycopg.Connection,
    committee_id: UUID,
    limit: int,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_COMMITTEE_IE_TOTALS_SQL, (committee_id, CANDIDATE_IE_OUTLIER_CEILING))
        totals_row = cursor.fetchone()
        if totals_row is None:
            raise RuntimeError(f"Committee IE totals query returned no rows for committee: {committee_id}")

        cursor.execute(_COMMITTEE_IE_TARGETS_SQL, (committee_id, CANDIDATE_IE_OUTLIER_CEILING, limit))
        target_rows = list(cursor.fetchall())

        cursor.execute(_COMMITTEE_IE_OUTLIER_COUNT_SQL, (committee_id, CANDIDATE_IE_OUTLIER_CEILING))
        outlier_count_row = cursor.fetchone()

    for target_row in target_rows:
        _quantize_money_fields(target_row, "support_total", "oppose_total")

    target_candidate_ids = [target_row["candidate_id"] for target_row in target_rows]
    sources_by_candidate_id = _fetch_committee_ie_target_sources(
        conn,
        committee_id=committee_id,
        candidate_ids=target_candidate_ids,
    )
    for target_row in target_rows:
        target_row["sources"] = sources_by_candidate_id.get(target_row["candidate_id"], [])

    excluded_outlier_count = 0 if outlier_count_row is None else outlier_count_row["excluded_outlier_count"]

    return {
        "committee_id": committee_id,
        "support_total": _quantize_money(totals_row["support_total"]),
        "oppose_total": _quantize_money(totals_row["oppose_total"]),
        "ie_transaction_count": totals_row["ie_transaction_count"],
        "excluded_outlier_count": excluded_outlier_count,
        "targets": target_rows,
    }


_PERSON_TOP_DONORS_DEFAULT_LIMIT = 10

_PERSON_TOP_DONORS_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT
        BTRIM(contributor_name_raw) AS name,
        contributor_city AS city,
        contributor_state AS state,
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM qualifying_transactions
    WHERE contributor_name_raw IS NOT NULL
      AND BTRIM(contributor_name_raw) != ''
    GROUP BY BTRIM(contributor_name_raw), contributor_city, contributor_state
    ORDER BY total_amount DESC, transaction_count DESC, name ASC, city ASC, state ASC
    LIMIT %s
"""

_PERSON_TOP_EMPLOYERS_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    , normalized_employers AS (
        SELECT
            amount,
            CASE
                WHEN normalized_employer IN (
                    '',
                    'SELF',
                    'SELF-EMPLOYED',
                    'SELF EMPLOYED',
                    'N/A',
                    'NA',
                    'NONE',
                    'RETIRED',
                    'NOT EMPLOYED',
                    'UNEMPLOYED'
                )
                THEN 'Unclassified / not provided'
                ELSE normalized_employer
            END AS employer
        FROM (
            SELECT
                amount,
                UPPER(
                    regexp_replace(
                        BTRIM(COALESCE(contributor_employer, '')),
                        '[[:space:]]+',
                        ' ',
                        'g'
                    )
                ) AS normalized_employer
            FROM qualifying_transactions
        ) normalized
    )
    SELECT
        employer,
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM normalized_employers
    GROUP BY employer
    ORDER BY total_amount DESC, transaction_count DESC, employer ASC
    LIMIT %s
"""


def fetch_person_top_donors(
    conn: psycopg.Connection,
    person_id: UUID,
    limit: int = _PERSON_TOP_DONORS_DEFAULT_LIMIT,
) -> list[dict[str, Any]] | None:
    """Return ranked top donors summed across a person's active linked committees.

    Returns ``None`` only when the person does not exist, mirroring the
    contribution-insights 404 semantics; returns ``[]`` for an existing person
    with no active linked committees or no qualifying individual contributions.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_EXISTS_SQL, (person_id,))
        if cursor.fetchone() is None:
            return None

    committee_ids = _fetch_person_insights_linked_committee_ids(conn, person_id)
    if not committee_ids:
        return []

    return _fetch_person_insights_rows(conn, _PERSON_TOP_DONORS_SQL, committee_ids, limit)


def fetch_person_top_employers(
    conn: psycopg.Connection,
    person_id: UUID,
    limit: int = _PERSON_TOP_DONORS_DEFAULT_LIMIT,
) -> list[dict[str, Any]] | None:
    """Return ranked employer-name totals across a person's active linked committees."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_EXISTS_SQL, (person_id,))
        if cursor.fetchone() is None:
            return None

    committee_ids = _fetch_person_insights_linked_committee_ids(conn, person_id)
    if not committee_ids:
        return []

    return _fetch_person_insights_rows(conn, _PERSON_TOP_EMPLOYERS_SQL, committee_ids, limit)
