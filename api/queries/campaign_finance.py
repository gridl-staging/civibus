
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
import json
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
    NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL,
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
      AND valid_period && daterange(%s, %s, '[]')
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
      AND cycle = %s
    ORDER BY cycle ASC
"""

COMMITTEE_RECEIPT_SOURCE_ROWS_SQL = """
    SELECT
        committee_id,
        total_receipts,
        individual_contributions,
        other_committee_contributions,
        party_committee_contributions,
        candidate_contributions,
        candidate_loans,
        transfers_from_other_authorized_committees,
        debts_owed_by_committee,
        coverage_start_date,
        coverage_end_date
    FROM cf.committee_summary
    WHERE committee_id = ANY(%s)
      AND cycle = %s
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
      AND link.valid_period && daterange(%s, %s, '[]')
    ORDER BY c.name ASC, c.id ASC
"""

# Stage 3: official FEC weball candidate totals. Populated by the bulk loader from
# weball{cycle}.zip rows. NULL when no weball row has loaded for the candidate, in
# which case the summary owner falls back to transaction-derived committee aggregates.
CANDIDATE_OFFICIAL_TOTALS_SQL = """
    SELECT
        total_receipts,
        total_disbursements,
        cash_on_hand,
        candidate_contrib,
        candidate_loans,
        candidate_loan_repay,
        summary_coverage_end_date
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
_RECEIPT_RECONCILIATION_TOLERANCE = Decimal("0.01")
_RECEIPT_COMPONENT_LABELS = {
    "individual_contributions": "Individual contributions",
    "other_committee_contributions": "PAC/other committee contributions",
    "party_committee_contributions": "Party committee contributions",
    "candidate_funding": "Candidate funding",
    "transfers_from_other_authorized_committees": "Transfers from other authorized committees",
    "other_receipts": "Other receipts",
}

# Stage 5: cycles for which ``cf.committee_summary`` official totals are considered
# authoritative. Kept in sync with ``core.refresh.job_builders._active_committee_summary_cycles``
# — the loader writes these; this owner reads them. One definition for both the
# top-level committee aggregate and the per-cycle ``cycle_summaries`` payload.
SUPPORTED_COMMITTEE_SUMMARY_CYCLES: tuple[int, ...] = (2022, 2024, 2026)
CONTRIBUTION_INSIGHTS_CYCLES: tuple[int, ...] = (2022, 2024, 2026)


@dataclass(frozen=True)
class SelectedCycle:
    selected_cycle: int
    coverage_start_date: date
    coverage_end_date: date
    available_cycles: tuple[int, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "selected_cycle": self.selected_cycle,
            "coverage_start_date": self.coverage_start_date,
            "coverage_end_date": self.coverage_end_date,
            "available_cycles": list(self.available_cycles),
        }


def resolve_selected_cycle(cycle: int | None = None) -> SelectedCycle:
    """Resolve and validate the selected federal campaign-finance cycle."""
    available_cycles = SUPPORTED_COMMITTEE_SUMMARY_CYCLES
    selected_cycle = max(available_cycles) if cycle is None else cycle
    if selected_cycle not in available_cycles:
        supported = ", ".join(str(value) for value in available_cycles)
        raise ValueError(f"Unsupported cycle {selected_cycle}; supported cycles: {supported}")
    return SelectedCycle(
        selected_cycle=selected_cycle,
        coverage_start_date=date(selected_cycle - 1, 1, 1),
        coverage_end_date=date(selected_cycle, 12, 31),
        available_cycles=available_cycles,
    )


def _coerce_selected_cycle(cycle: SelectedCycle | int | None = None) -> SelectedCycle:
    if isinstance(cycle, SelectedCycle):
        return cycle
    return resolve_selected_cycle(cycle)


DONOR_SEARCH_MIN_QUERY_LEN = 3
DONOR_SEARCH_MAX_LIMIT = 50
_DONOR_SEARCH_NESTED_DETAIL_LIMIT = 5
_DONOR_SEARCH_SUPPORTED_MODES = frozenset({"name", "employer", "zip"})
_ZIP5_SEARCH_RE = re.compile(r"^\s*(\d{5})(?:-?\d{4})?\s*$")

# FEC comparison buckets use absolute amount for membership while signed amounts
# remain authoritative for totals, so correction-like rows reduce dollars.
CONTRIBUTION_INSIGHTS_SIZE_BUCKETS: tuple[tuple[str, Decimal, Decimal | None], ...] = (
    ("$200 and under", Decimal("0.01"), Decimal("200.00")),
    ("$200.01-$499.99", Decimal("200.01"), Decimal("499.99")),
    ("$500-$999.99", Decimal("500.00"), Decimal("999.99")),
    ("$1,000-$1,999.99", Decimal("1000.00"), Decimal("1999.99")),
    ("$2,000 and over", Decimal("2000.00"), None),
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
      AND link.valid_period && daterange(%s, %s, '[]')
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

_INDIVIDUAL_RECEIPT_TRANSACTION_WHERE_SQL = contribution_insights_transaction_where_sql(max_date_sql="%s")

_INDIVIDUAL_RECEIPT_QUALIFYING_WHERE_SQL = (
    _INDIVIDUAL_RECEIPT_TRANSACTION_WHERE_SQL + NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL
)

_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE = f"""
    WITH linked_committees AS (
        SELECT unnest(%s::uuid[]) AS committee_id
    ),
    qualifying_transactions AS MATERIALIZED (
        SELECT
            t.id,
            t.amount,
            t.transaction_date,
            t.contributor_name_raw,
            t.contributor_employer,
            t.contributor_city,
            t.contributor_state,
            LEFT(regexp_replace(COALESCE(t.contributor_zip, ''), '[^0-9]', '', 'g'), 5) AS zcta5,
            LENGTH(regexp_replace(COALESCE(t.contributor_zip, ''), '[^0-9]', '', 'g')) >= 5 AS has_valid_zip
        FROM cf.transaction t
        JOIN linked_committees linked
          ON linked.committee_id = t.committee_id
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
        CASE
            WHEN NULLIF(contributor_state, '') IS NULL OR NOT has_valid_zip THEN 'Unknown'
            ELSE contributor_state
        END AS label,
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
    WHERE ABS(amount) >= %s
      AND (%s::numeric IS NULL OR ABS(amount) <= %s)
"""

_PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE}
    SELECT label, total_amount, transaction_count
    FROM (
        SELECT
            CASE
                WHEN %s = 'us_senate' AND (NULLIF(qt.contributor_state, '') IS NULL OR NOT qt.has_valid_zip) THEN 'Unknown'
                WHEN %s = 'us_senate' AND qt.contributor_state = %s THEN 'In state'
                WHEN %s = 'us_senate' THEN 'Out of state'
                WHEN NULLIF(qt.contributor_state, '') IS NULL OR NOT qt.has_valid_zip OR z.zcta5 IS NULL THEN 'Unknown'
                WHEN qt.contributor_state = %s AND z.district_number = %s THEN 'In district'
                WHEN qt.contributor_state = %s THEN 'Elsewhere in state'
                ELSE 'Out of state'
            END AS label,
            COALESCE(SUM(qt.amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count
        FROM qualifying_transactions qt
        LEFT JOIN civic.zcta_district z
          ON z.zcta5 = qt.zcta5
         AND z.boundary_year = (
             SELECT MAX(boundary_year)
             FROM civic.zcta_district
         )
        GROUP BY label
        HAVING COUNT(*) > 0
    ) district_totals
    ORDER BY
        CASE label
            WHEN 'In district' THEN 1
            WHEN 'Elsewhere in state' THEN 2
            WHEN 'Out of state' THEN 3
            WHEN 'In state' THEN 1
            WHEN 'Unknown' THEN 4
            ELSE 5
        END
"""

_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_SQL = """
    SELECT
        COALESCE(SUM(individual_unitemized_contributions), 0) AS unitemized_total,
        SUM(individual_itemized_contributions) AS itemized_total,
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
        COUNT(DISTINCT committee_id)::integer AS committee_count,
        COUNT(DISTINCT committee_id) FILTER (
            WHERE coverage_start_date <= %s
              AND coverage_end_date >= %s
        )::integer AS complete_committee_count,
        MIN(coverage_start_date) AS coverage_start_date,
        MAX(coverage_end_date) AS coverage_end_date
    FROM cf.committee_summary
    WHERE committee_id = ANY(%s)
      AND cycle = ANY(%s)
    GROUP BY cycle
    ORDER BY cycle ASC
"""

_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_ROLLUPS_SQL = """
    WITH summary_rows AS MATERIALIZED (
        SELECT *
        FROM cf.committee_summary
        WHERE committee_id = ANY(%s)
          AND cycle = ANY(%s)
    ),
    coverage_rows AS (
        SELECT
            cycle,
            COUNT(DISTINCT committee_id)::integer AS committee_count,
            COUNT(DISTINCT committee_id) FILTER (
                WHERE coverage_start_date <= %s
                  AND coverage_end_date >= %s
            )::integer AS complete_committee_count,
            MIN(coverage_start_date) AS coverage_start_date,
            MAX(coverage_end_date) AS coverage_end_date
        FROM summary_rows
        GROUP BY cycle
    ),
    summary_cycle_rows AS (
        SELECT
            cycle,
            COALESCE(SUM(individual_unitemized_contributions), 0)
                AS unitemized_individual_contribution_amount
        FROM summary_rows
        GROUP BY cycle
    )
    SELECT
        COALESCE(SUM(individual_unitemized_contributions), 0) AS unitemized_total,
        SUM(individual_itemized_contributions) AS itemized_total,
        COUNT(*)::integer AS summary_row_count,
        COUNT(DISTINCT committee_id)::integer AS summary_committee_count,
        ARRAY_REMOVE(ARRAY_AGG(DISTINCT cycle ORDER BY cycle), NULL) AS cycles_included,
        MAX(coverage_end_date) AS coverage_end_date,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'cycle', cycle,
                    'committee_count', committee_count,
                    'complete_committee_count', complete_committee_count,
                    'coverage_start_date', coverage_start_date,
                    'coverage_end_date', coverage_end_date
                )
                ORDER BY cycle ASC
            )
            FROM coverage_rows
        ), '[]'::jsonb) AS coverage_rows,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'cycle', cycle,
                    'unitemized_individual_contribution_amount',
                    unitemized_individual_contribution_amount::text
                )
                ORDER BY cycle ASC
            )
            FROM summary_cycle_rows
        ), '[]'::jsonb) AS summary_cycle_rows
    FROM summary_rows
"""

_PERSON_CONTRIBUTION_INSIGHTS_BUCKET_VALUES_SQL = ",\n        ".join(
    f"({index}, '{label}', {min_amount}, {'NULL' if max_amount is None else max_amount})"
    for index, (label, min_amount, max_amount) in enumerate(CONTRIBUTION_INSIGHTS_SIZE_BUCKETS, start=1)
)

_PERSON_CONTRIBUTION_INSIGHTS_ITEMIZED_ROLLUPS_SQL = f"""
    {_PERSON_CONTRIBUTION_INSIGHTS_QUALIFYING_CTE},
    bucket_specs(ordinal, label, min_amount, max_amount) AS (
        VALUES
        {_PERSON_CONTRIBUTION_INSIGHTS_BUCKET_VALUES_SQL}
    ),
    coverage_bounds AS (
        SELECT
            CASE
                WHEN %s::boolean THEN %s::date
                ELSE date_trunc('month', MIN(transaction_date))::date
            END AS start_month,
            CASE
                WHEN %s::boolean THEN date_trunc('month', LEAST(%s::date, CURRENT_DATE))::date
                ELSE date_trunc('month', MAX(transaction_date))::date
            END AS end_month
        FROM qualifying_transactions
    ),
    coverage_months AS (
        SELECT to_char(month_value, 'YYYY-MM') AS month
        FROM coverage_bounds bounds
        CROSS JOIN LATERAL generate_series(bounds.start_month, bounds.end_month, interval '1 month') AS month_value
        WHERE bounds.start_month IS NOT NULL
          AND bounds.end_month IS NOT NULL
    ),
    transaction_month_totals AS (
        SELECT
            to_char(date_trunc('month', transaction_date), 'YYYY-MM') AS month,
            COALESCE(SUM(amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count
        FROM qualifying_transactions
        GROUP BY date_trunc('month', transaction_date)
    ),
    monthly_totals AS (
        SELECT
            coverage_months.month,
            COALESCE(transaction_month_totals.total_amount, 0) AS total_amount,
            COALESCE(transaction_month_totals.transaction_count, 0)::integer AS transaction_count
        FROM coverage_months
        LEFT JOIN transaction_month_totals
          ON transaction_month_totals.month = coverage_months.month
    ),
    state_totals AS (
        SELECT
            CASE
                WHEN NULLIF(contributor_state, '') IS NULL OR NOT has_valid_zip THEN 'Unknown'
                ELSE contributor_state
            END AS label,
            COALESCE(SUM(amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count
        FROM qualifying_transactions
        GROUP BY label
    ),
    ranked_known_state_totals AS (
        SELECT
            label,
            total_amount,
            transaction_count,
            ROW_NUMBER() OVER (
                ORDER BY total_amount DESC, transaction_count DESC, label ASC
            ) AS state_rank
        FROM state_totals
        WHERE label != 'Unknown'
    ),
    bounded_state_totals AS (
        SELECT
            state_rank AS ordinal,
            label,
            total_amount,
            transaction_count
        FROM ranked_known_state_totals
        WHERE state_rank <= 5
        UNION ALL
        SELECT
            6 AS ordinal,
            'Other states' AS label,
            COALESCE(SUM(total_amount), 0) AS total_amount,
            COALESCE(SUM(transaction_count), 0)::integer AS transaction_count
        FROM ranked_known_state_totals
        WHERE state_rank > 5
        HAVING COUNT(*) > 0
        UNION ALL
        SELECT
            7 AS ordinal,
            'Unknown' AS label,
            total_amount,
            transaction_count
        FROM state_totals
        WHERE label = 'Unknown'
    ),
    totals AS (
        SELECT
            COALESCE(SUM(amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count,
            MAX(transaction_date) AS max_transaction_date
        FROM qualifying_transactions
    ),
    itemized_size_buckets AS (
        SELECT
            bucket.ordinal,
            bucket.label,
            bucket.min_amount,
            bucket.max_amount,
            COALESCE(SUM(qt.amount), 0) AS total_amount,
            COUNT(qt.id)::integer AS transaction_count
        FROM bucket_specs bucket
        LEFT JOIN qualifying_transactions qt
          ON ABS(qt.amount) >= bucket.min_amount
         AND (bucket.max_amount IS NULL OR ABS(qt.amount) <= bucket.max_amount)
        GROUP BY bucket.ordinal, bucket.label, bucket.min_amount, bucket.max_amount
    ),
    itemized_cycle_totals AS (
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
    ),
    district_totals AS (
        SELECT label, total_amount, transaction_count
        FROM (
            SELECT
                CASE
                    WHEN NOT %s::boolean THEN NULL
                    WHEN %s = 'us_senate' AND (NULLIF(qt.contributor_state, '') IS NULL OR NOT qt.has_valid_zip) THEN 'Unknown'
                    WHEN %s = 'us_senate' AND qt.contributor_state = %s THEN 'In state'
                    WHEN %s = 'us_senate' THEN 'Out of state'
                    WHEN NULLIF(qt.contributor_state, '') IS NULL OR NOT qt.has_valid_zip OR z.zcta5 IS NULL THEN 'Unknown'
                    WHEN qt.contributor_state = %s AND z.district_number = %s THEN 'In district'
                    WHEN qt.contributor_state = %s THEN 'Elsewhere in state'
                    ELSE 'Out of state'
                END AS label,
                COALESCE(SUM(qt.amount), 0) AS total_amount,
                COUNT(*)::integer AS transaction_count
            FROM qualifying_transactions qt
            LEFT JOIN civic.zcta_district z
              ON %s::boolean AND z.zcta5 = qt.zcta5
            WHERE %s::boolean
            GROUP BY label
            HAVING COUNT(*) > 0
        ) district_totals
        ORDER BY
            CASE label
                WHEN 'In district' THEN 1
                WHEN 'Elsewhere in state' THEN 2
                WHEN 'Out of state' THEN 3
                WHEN 'In state' THEN 1
                WHEN 'Unknown' THEN 4
                ELSE 5
            END
    )
    SELECT
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'month', month,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY month ASC
            )
            FROM monthly_totals
        ), '[]'::jsonb) AS monthly_totals,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', label,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY ordinal ASC
            )
            FROM bounded_state_totals
        ), '[]'::jsonb) AS state_totals,
        (
            SELECT jsonb_build_object(
                'total_amount', total_amount::text,
                'transaction_count', transaction_count,
                'max_transaction_date', max_transaction_date
            )
            FROM totals
        ) AS totals,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', label,
                    'min_amount', min_amount::text,
                    'max_amount', CASE WHEN max_amount IS NULL THEN NULL ELSE max_amount::text END,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY ordinal ASC
            )
            FROM itemized_size_buckets
        ), '[]'::jsonb) AS itemized_size_buckets,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'cycle', cycle,
                    'itemized_individual_contribution_amount', itemized_individual_contribution_amount::text,
                    'itemized_transaction_count', itemized_transaction_count
                )
                ORDER BY cycle ASC
            )
            FROM itemized_cycle_totals
        ), '[]'::jsonb) AS itemized_cycle_totals,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'label', label,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY
                    CASE label
                        WHEN 'In district' THEN 1
                        WHEN 'Elsewhere in state' THEN 2
                        WHEN 'Out of state' THEN 3
                        WHEN 'In state' THEN 1
                        WHEN 'Unknown' THEN 4
                        ELSE 5
                    END
            )
            FROM district_totals
        ), '[]'::jsonb) AS district_totals
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

# The six columns that jointly identify a donor group. NULL is a meaningful,
# distinct value here (an absent employer is not the same donor as a present one),
# so the identity comparison must be NULL-safe.
_DONOR_SEARCH_KEY_COLUMNS = (
    "contributor_name",
    "contributor_employer",
    "contributor_occupation",
    "contributor_city",
    "contributor_state",
    "normalized_zip5",
)


def _donor_key_sql(alias: str) -> str:
    """Build a hashable donor-identity key over the grouping columns for ``alias``.

    Comparing the six grouping columns with ``IS NOT DISTINCT FROM`` is NULL-safe
    but not hashable, so PostgreSQL can only join on it with a nested loop. On
    common terms (q=smith) the recipient and source rollups then cross-product the
    full matched-transaction set (~57k rows) against the paginated donor page,
    which timed the endpoint out at ~16s. Encoding the same identity as a single
    md5 text key lets the planner use a hash join instead.

    Each column is wrapped with an explicit ``N``/``V`` null marker before it is
    joined by a unit-separator control character (``\\x1f``) that cannot appear in
    normalized contributor text. The marker guarantees a NULL column can never
    encode to the same string as any present value, so the key preserves the
    NULL-safe equality semantics of the original ``IS NOT DISTINCT FROM`` join.
    """
    encoded_columns = [
        f"CASE WHEN {alias}.{column} IS NULL THEN 'N' ELSE 'V' || {alias}.{column} END"
        for column in _DONOR_SEARCH_KEY_COLUMNS
    ]
    return "md5(" + " || E'\\x1f' || ".join(encoded_columns) + ")"


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
        -- This is the first materialized transaction boundary: keeping the mode
        -- predicate, receipt filters, date window, and source-record validity
        -- together lets the mode index (name/employer trigram or ZIP) be scanned
        -- exactly once. Committee scope is deliberately NOT applied here: an
        -- EXISTS against current_federal_candidate_committees made the planner
        -- re-scan the whole mode bitmap once per federal committee (~508 loops,
        -- ~12s on q=smith). The committee scope is instead applied by the
        -- qualifying_transactions INNER JOIN below, which prunes the same rows
        -- with a single hash join. Do not cap matched rows here: donor LIMIT
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
{NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}
          AND t.contributor_name_raw IS NOT NULL
          AND BTRIM(t.contributor_name_raw) != ''
    ),
    qualifying_transactions AS MATERIALIZED (
        -- Materialized so the mode scan + committee-scope join runs exactly once:
        -- donor_groups and donor_page_transactions both read this set, and an
        -- inline CTE would otherwise recompute the scan-and-join for each. Keep
        -- it narrow: candidate/committee labels are joined only after donor
        -- pagination so the full common-term match does not carry nested-detail
        -- columns through materialization and grouping.
        SELECT
            t.id,
            t.committee_id,
            t.amount,
            t.transaction_date,
            t.contributor_name,
            t.contributor_employer,
            t.contributor_occupation,
            t.contributor_city,
            t.contributor_state,
            t.normalized_zip5,
            {_donor_key_sql("t")} AS donor_key,
            t.source_record_id
        FROM matching_transactions t
        JOIN current_federal_candidate_committees scope
          ON scope.committee_id = t.committee_id
    ),
    donor_groups AS (
        SELECT
            MIN(id::text)::uuid AS id,
            contributor_name,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            normalized_zip5,
            donor_key,
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
            normalized_zip5,
            donor_key
        ORDER BY total_amount DESC, transaction_count DESC, contributor_name ASC, id ASC
        LIMIT %s
        OFFSET %s
    ),
    donor_page_transactions AS MATERIALIZED (
        SELECT qt.*
        FROM donor_groups dg
        JOIN qualifying_transactions qt
          ON qt.donor_key = dg.donor_key
    ),
    recipient_rollups AS (
        -- Scope recipient aggregation to the paginated donor page. Joining the
        -- limited donor_groups set first prunes the transaction universe to the
        -- top-N donors BEFORE the per-recipient rollup, so the recipient×source
        -- fan-out never materializes for donors that pagination discards.
        SELECT
            qt.contributor_name,
            qt.contributor_employer,
            qt.contributor_occupation,
            qt.contributor_city,
            qt.contributor_state,
            qt.normalized_zip5,
            qt.donor_key,
            scope.person_id,
            (ARRAY_AGG(scope.candidate_id ORDER BY scope.candidate_name ASC, scope.candidate_id ASC, scope.committee_name ASC, scope.committee_id ASC))[1]
                AS candidate_id,
            (ARRAY_AGG(scope.fec_candidate_id ORDER BY scope.candidate_name ASC, scope.candidate_id ASC, scope.committee_name ASC, scope.committee_id ASC))[1]
                AS fec_candidate_id,
            (ARRAY_AGG(scope.candidate_name ORDER BY scope.candidate_name ASC, scope.candidate_id ASC, scope.committee_name ASC, scope.committee_id ASC))[1]
                AS candidate_name,
            (ARRAY_AGG(scope.committee_id ORDER BY scope.candidate_name ASC, scope.candidate_id ASC, scope.committee_name ASC, scope.committee_id ASC))[1]
                AS committee_id,
            (ARRAY_AGG(scope.fec_committee_id ORDER BY scope.candidate_name ASC, scope.candidate_id ASC, scope.committee_name ASC, scope.committee_id ASC))[1]
                AS fec_committee_id,
            (ARRAY_AGG(scope.committee_name ORDER BY scope.candidate_name ASC, scope.candidate_id ASC, scope.committee_name ASC, scope.committee_id ASC))[1]
                AS committee_name,
            COALESCE(SUM(qt.amount), 0) AS recipient_total_amount,
            COUNT(*)::integer AS recipient_transaction_count
        FROM donor_page_transactions qt
        JOIN current_federal_candidate_committees scope
          ON scope.committee_id = qt.committee_id
        GROUP BY
            qt.contributor_name,
            qt.contributor_employer,
            qt.contributor_occupation,
            qt.contributor_city,
            qt.contributor_state,
            qt.normalized_zip5,
            qt.donor_key,
            scope.person_id
    ),
    limited_recipient_rollups AS (
        SELECT *
        FROM (
            SELECT
                recipient_rollups.*,
                ROW_NUMBER() OVER (
                    PARTITION BY donor_key
                    ORDER BY
                        recipient_total_amount DESC,
                        recipient_transaction_count DESC,
                        candidate_name ASC,
                        person_id ASC
                ) AS recipient_rank
            FROM recipient_rollups
        ) ranked_recipients
        WHERE recipient_rank <= {_DONOR_SEARCH_NESTED_DETAIL_LIMIT}
    ),
    source_rollups AS (
        SELECT DISTINCT
            source.contributor_name,
            source.contributor_employer,
            source.contributor_occupation,
            source.contributor_city,
            source.contributor_state,
            source.normalized_zip5,
            source.donor_key,
            sr.id AS source_record_id,
            ds.domain,
            ds.jurisdiction,
            ds.name AS data_source_name,
            ds.source_url AS data_source_url,
            sr.source_record_key,
            sr.source_url AS record_url,
            sr.pull_date
        FROM donor_page_transactions source
        JOIN core.source_record sr
          ON sr.id = source.source_record_id AND sr.superseded_by IS NULL
        JOIN core.data_source ds
          ON ds.id = sr.data_source_id
        WHERE source.source_record_id IS NOT NULL
    ),
    limited_source_rollups AS (
        SELECT *
        FROM (
            SELECT
                source_rollups.*,
                ROW_NUMBER() OVER (
                    PARTITION BY donor_key
                    ORDER BY pull_date DESC NULLS LAST, source_record_key ASC NULLS LAST
                ) AS source_rank
            FROM source_rollups
        ) ranked_sources
        WHERE source_rank <= {_DONOR_SEARCH_NESTED_DETAIL_LIMIT}
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
    LEFT JOIN limited_recipient_rollups recipient
      ON recipient.donor_key = dg.donor_key
    LEFT JOIN limited_source_rollups source
      ON source.donor_key = dg.donor_key
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


def _qualifying_transactions_cte(
    select_columns: str,
    *,
    materialized: bool = False,
    cycle_filtered: bool = False,
) -> str:
    """Build the qualifying-transactions CTE fragment.

    Shared between committee-level summary and per-filing breakdown queries.
    Filters: non-memo, non-terminated-amendment, non-superseded source records.
    The caller must bind ``committee_id`` as the first query parameter (``%s``).
    """
    materialized_sql = " MATERIALIZED" if materialized else ""
    cycle_filter_sql = ""
    if cycle_filtered:
        cycle_filter_sql = """
          AND t.transaction_date >= %s
          AND t.transaction_date <= %s"""
    return f"""qualifying_transactions AS{materialized_sql} (
        SELECT
            {select_columns}
        FROM cf.transaction t
        WHERE t.committee_id = %s
{cycle_filter_sql}
          AND t.is_memo = FALSE
          AND t.amendment_indicator != 'T'
{NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}
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

COMMITTEE_STORED_FUNDRAISING_SUMMARY_SQL = """
    WITH stored_cycle_aggregates AS (
        SELECT
            cs.committee_id,
            COALESCE(SUM(cs.derived_total_raised), 0) AS total_raised,
            COALESCE(SUM(cs.derived_total_spent), 0) AS total_spent,
            COALESCE(SUM(cs.derived_net), 0) AS net,
            COALESCE(SUM(cs.derived_transaction_count), 0)::integer AS transaction_count,
            COALESCE(SUM(cs.derived_loan_receipts_total), 0) AS loan_receipts_total,
            COALESCE(SUM(cs.derived_in_kind_receipts_total), 0) AS in_kind_receipts_total,
            COALESCE(SUM(cs.derived_contribution_receipts_total), 0) AS contribution_receipts_total,
            COALESCE(SUM(cs.derived_cash_receipts_total), 0) AS cash_receipts_total,
            (ARRAY_AGG(
                cs.derived_jurisdiction
                ORDER BY cs.derived_data_through DESC NULLS LAST, cs.cycle DESC
            ) FILTER (WHERE cs.derived_jurisdiction IS NOT NULL))[1] AS jurisdiction,
            MAX(cs.derived_data_through) AS data_through,
            BOOL_OR(cs.derived_transaction_count IS NOT NULL) AS has_precomputed_aggregate
        FROM cf.committee_summary cs
        WHERE cs.committee_id = %s
          AND cs.cycle = %s
        GROUP BY cs.committee_id
    )
    SELECT
        c.id AS committee_id,
        c.name AS committee_name,
        sca.total_raised,
        sca.total_spent,
        sca.net,
        sca.transaction_count,
        sca.loan_receipts_total,
        sca.in_kind_receipts_total,
        sca.contribution_receipts_total,
        sca.cash_receipts_total,
        sca.jurisdiction,
        sca.data_through
    FROM cf.committee c
    JOIN stored_cycle_aggregates sca
      ON sca.committee_id = c.id
    WHERE c.id = %s
      AND sca.has_precomputed_aggregate
"""

COMMITTEE_FUNDRAISING_SUMMARY_SQL = f"""
    WITH stored_cycle_aggregates AS (
        SELECT
            cs.committee_id,
            COALESCE(SUM(cs.derived_total_raised), 0) AS total_raised,
            COALESCE(SUM(cs.derived_total_spent), 0) AS total_spent,
            COALESCE(SUM(cs.derived_net), 0) AS net,
            COALESCE(SUM(cs.derived_transaction_count), 0)::integer AS transaction_count,
            COALESCE(SUM(cs.derived_loan_receipts_total), 0) AS loan_receipts_total,
            COALESCE(SUM(cs.derived_in_kind_receipts_total), 0) AS in_kind_receipts_total,
            COALESCE(SUM(cs.derived_contribution_receipts_total), 0) AS contribution_receipts_total,
            COALESCE(SUM(cs.derived_cash_receipts_total), 0) AS cash_receipts_total,
            (ARRAY_AGG(
                cs.derived_jurisdiction
                ORDER BY cs.derived_data_through DESC NULLS LAST, cs.cycle DESC
            ) FILTER (WHERE cs.derived_jurisdiction IS NOT NULL))[1] AS jurisdiction,
            MAX(cs.derived_data_through) AS data_through,
            BOOL_OR(cs.derived_transaction_count IS NOT NULL) AS has_precomputed_aggregate
        FROM cf.committee_summary cs
        WHERE cs.committee_id = %s
          AND cs.cycle = %s
        GROUP BY cs.committee_id
    ),
    stored_summary AS (
        SELECT
            c.id AS committee_id,
            c.name AS committee_name,
            sca.total_raised,
            sca.total_spent,
            sca.net,
            sca.transaction_count,
            sca.loan_receipts_total,
            sca.in_kind_receipts_total,
            sca.contribution_receipts_total,
            sca.cash_receipts_total,
            sca.jurisdiction,
            sca.data_through
        FROM cf.committee c
        JOIN stored_cycle_aggregates sca
          ON sca.committee_id = c.id
        WHERE c.id = %s
          AND sca.has_precomputed_aggregate
    ),
    {_qualifying_transactions_cte("t.id, t.committee_id, t.transaction_type, t.amount, t.source_record_id", cycle_filtered=True)},
    qualifying_source_records AS (
        SELECT DISTINCT source_record_id
        FROM qualifying_transactions
        WHERE source_record_id IS NOT NULL
    ),
    committee_provenance AS (
        -- Bounded provenance aggregate over the committee's own qualifying
        -- source records. Replaces the former ``ORDER BY pull_date DESC LIMIT 1``
        -- CTE, whose plan degraded to a backward index scan over all 16M
        -- ``source_record`` rows for large committees. ``MAX(pull_date)`` and the
        -- ordered pick both read only the committee's source records, so
        -- ``data_through`` stays the latest non-superseded pull_date without the
        -- full-table scan.
        SELECT
            (ARRAY_AGG(ds.jurisdiction ORDER BY sr.pull_date DESC, sr.id ASC))[1] AS jurisdiction,
            MAX(sr.pull_date) AS data_through
        FROM qualifying_source_records qsr
        JOIN core.source_record sr
          ON sr.id = qsr.source_record_id
        LEFT JOIN core.data_source ds
          ON ds.id = sr.data_source_id
    ),
    live_summary AS (
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
            committee_provenance.jurisdiction,
            committee_provenance.data_through
        FROM cf.committee c
        JOIN qualifying_transactions qt
          ON qt.committee_id = c.id
        LEFT JOIN committee_provenance
          ON TRUE
        WHERE c.id = %s
          AND NOT EXISTS (
              SELECT 1
              FROM stored_cycle_aggregates sca
              WHERE sca.has_precomputed_aggregate
          )
        GROUP BY c.id, c.name, committee_provenance.jurisdiction, committee_provenance.data_through
    )
    SELECT * FROM stored_summary
    UNION ALL
    SELECT * FROM live_summary
"""

COMMITTEE_TOP_LISTS_SQL = f"""
    WITH {_qualifying_transactions_cte("t.id, t.transaction_type, t.amount, t.contributor_name_raw, t.memo_text", materialized=True, cycle_filtered=True)},
    top_donors AS (
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
    ),
    top_vendors AS (
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
    ),
    spend_categories AS (
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
    )
    SELECT
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'name', name,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY total_amount DESC, transaction_count DESC, name ASC
            )
            FROM top_donors
        ), '[]'::jsonb) AS top_donors,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'name', name,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY total_amount DESC, transaction_count DESC, name ASC
            )
            FROM top_vendors
        ), '[]'::jsonb) AS top_vendors,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'category', category,
                    'total_amount', total_amount::text,
                    'transaction_count', transaction_count
                )
                ORDER BY total_amount DESC, transaction_count DESC, category ASC
            )
            FROM spend_categories
        ), '[]'::jsonb) AS spend_categories
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

_CANDIDATES_FOR_PEOPLE_SQL = f"""
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
        FALSE AS slug_is_unique
    FROM cf.candidate c
    WHERE c.person_id = ANY(%s::uuid[])
    ORDER BY c.person_id ASC, c.name ASC, c.id ASC
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


def fetch_committee_linked_candidates(
    conn: psycopg.Connection,
    committee_id: UUID,
    selected_cycle: SelectedCycle | int | None = None,
) -> list[dict[str, Any]]:
    """Return active candidates linked to a committee, ordered by candidate name.

    Rows are shaped like ``CandidateListItem`` so Stage 6 can route by ``person_id``
    / slug through the same detail contract already used for the candidate list.
    """
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            COMMITTEE_LINKED_CANDIDATES_SQL,
            (committee_id, cycle.coverage_start_date, cycle.coverage_end_date),
        )
        return list(cursor.fetchall())


def _fetch_committee_name(conn: psycopg.Connection, committee_id: UUID) -> str | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_NAME_SQL, (committee_id,))
        row = cursor.fetchone()
    if row is None:
        return None
    return row["name"]


def _fetch_committee_cycle_summaries(
    conn: psycopg.Connection,
    committee_id: UUID,
    selected_cycle: SelectedCycle,
) -> list[dict[str, Any]]:
    """Load supported-cycle official rows from ``cf.committee_summary``.

    Returned in ascending cycle order with money fields quantized to the standard
    scale so the payload matches ``CommitteeCycleSummary`` without further work
    in the caller.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            COMMITTEE_CYCLE_SUMMARIES_SQL,
            (committee_id, selected_cycle.selected_cycle),
        )
        cycle_rows = list(cursor.fetchall())

    for cycle_row in cycle_rows:
        cycle_row["total_receipts"] = _quantize_money(cycle_row["total_receipts"] or 0)
        cycle_row["total_disbursements"] = _quantize_money(cycle_row["total_disbursements"] or 0)
        if cycle_row["cash_on_hand"] is not None:
            cycle_row["cash_on_hand"] = _quantize_money(cycle_row["cash_on_hand"])
    return cycle_rows


def _decode_json_payload(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _json_rows(value: Any) -> list[dict[str, Any]]:
    decoded = _decode_json_payload(value)
    if decoded is None:
        return []
    return [dict(row) for row in decoded]


def _json_object(value: Any) -> dict[str, Any]:
    decoded = _decode_json_payload(value)
    if decoded is None:
        return {}
    return dict(decoded)


def _empty_committee_top_lists() -> dict[str, list[dict[str, Any]]]:
    return {
        "top_donors": [],
        "top_vendors": [],
        "spend_categories": [],
    }


def _fetch_committee_top_lists(
    conn: psycopg.Connection,
    committee_id: UUID,
    selected_cycle: SelectedCycle,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch and normalize committee donor, vendor, and spend-category rankings."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            COMMITTEE_TOP_LISTS_SQL,
            (
                committee_id,
                selected_cycle.coverage_start_date,
                selected_cycle.coverage_end_date,
                _COMMITTEE_TOP_PARTIES_LIMIT,
                _COMMITTEE_TOP_PARTIES_LIMIT,
                _COMMITTEE_SPEND_CATEGORY_LIMIT,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        return _empty_committee_top_lists()

    top_lists = {
        "top_donors": _json_rows(row["top_donors"]),
        "top_vendors": _json_rows(row["top_vendors"]),
        "spend_categories": _json_rows(row["spend_categories"]),
    }
    for list_name in ("top_donors", "top_vendors", "spend_categories"):
        for list_row in top_lists[list_name]:
            _quantize_money_fields(list_row, "total_amount")
    return top_lists


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


def _receipt_component(label_key: str, total_amount: Decimal) -> dict[str, Any]:
    return {
        "label": _RECEIPT_COMPONENT_LABELS[label_key],
        "total_amount": _quantize_money(total_amount),
        "source": "fec_committee_summary",
    }


def _empty_receipt_source_payload(caveat: str) -> dict[str, Any]:
    return {
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": [caveat],
        "debts_owed_by_committee": None,
    }


def _fetch_receipt_source_payload(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
) -> dict[str, Any]:
    """Build receipt-source composition from complete selected-cycle committee summaries."""
    if not committee_ids:
        return _empty_receipt_source_payload("missing_committee_summary")

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(COMMITTEE_RECEIPT_SOURCE_ROWS_SQL, (committee_ids, selected_cycle.selected_cycle))
        rows = list(cursor.fetchall())

    if len({row["committee_id"] for row in rows}) != len(set(committee_ids)):
        return _empty_receipt_source_payload("missing_committee_summary")
    if any(
        row["coverage_start_date"] is None
        or row["coverage_end_date"] is None
        or row["coverage_start_date"] > selected_cycle.coverage_start_date
        or row["coverage_end_date"] < selected_cycle.coverage_end_date
        or row["total_receipts"] is None
        for row in rows
    ):
        return _empty_receipt_source_payload("incomplete_committee_summary_coverage")

    individual = sum((row["individual_contributions"] or _MONEY_SCALE for row in rows), start=_MONEY_SCALE)
    other_committee = sum((row["other_committee_contributions"] or _MONEY_SCALE for row in rows), start=_MONEY_SCALE)
    party = sum((row["party_committee_contributions"] or _MONEY_SCALE for row in rows), start=_MONEY_SCALE)
    candidate_funding = sum(
        ((row["candidate_contributions"] or _MONEY_SCALE) + (row["candidate_loans"] or _MONEY_SCALE) for row in rows),
        start=_MONEY_SCALE,
    )
    transfers = sum(
        (row["transfers_from_other_authorized_committees"] or _MONEY_SCALE for row in rows),
        start=_MONEY_SCALE,
    )
    total_receipts = sum((row["total_receipts"] for row in rows), start=_MONEY_SCALE)
    named_components = individual + other_committee + party + candidate_funding + transfers
    residual = total_receipts - named_components
    components = [
        _receipt_component("individual_contributions", individual),
        _receipt_component("other_committee_contributions", other_committee),
        _receipt_component("party_committee_contributions", party),
        _receipt_component("candidate_funding", candidate_funding),
        _receipt_component("transfers_from_other_authorized_committees", transfers),
        _receipt_component("other_receipts", residual),
    ]
    has_negative_component = any(component["total_amount"] < 0 for component in components)
    component_total = sum((component["total_amount"] for component in components), start=_MONEY_SCALE)
    reconciles = (
        abs(_quantize_money(component_total) - _quantize_money(total_receipts)) <= _RECEIPT_RECONCILIATION_TOLERANCE
    )
    caveats: list[str] = []
    if has_negative_component:
        caveats.append("negative_receipt_source_component")
    if not reconciles:
        caveats.append("receipt_source_components_do_not_reconcile")
    return {
        "receipt_source_composition": [] if caveats else components,
        "selected_cycle_coverage_complete": True,
        "can_render_share": not caveats,
        "receipt_source_caveats": caveats,
        "debts_owed_by_committee": _quantize_money(
            sum((row["debts_owed_by_committee"] or _MONEY_SCALE for row in rows), start=_MONEY_SCALE)
        ),
    }


def _combine_candidate_receipt_source_payload(committee_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate committee receipt-source payloads into one candidate-level payload."""
    if not committee_summaries:
        return _empty_receipt_source_payload("missing_committee_summary")

    caveats: list[str] = []
    coverage_complete = all(committee.get("selected_cycle_coverage_complete") for committee in committee_summaries)
    debts_owed = sum(
        (committee.get("debts_owed_by_committee") or _MONEY_SCALE for committee in committee_summaries),
        start=_MONEY_SCALE,
    )
    if not coverage_complete:
        caveats.append("missing_committee_summary")
    for committee in committee_summaries:
        for caveat in committee.get("receipt_source_caveats", []):
            if caveat not in caveats:
                caveats.append(caveat)
    if caveats or not all(committee.get("can_render_share") for committee in committee_summaries):
        return {
            "receipt_source_composition": [],
            "selected_cycle_coverage_complete": coverage_complete,
            "can_render_share": False,
            "receipt_source_caveats": caveats or ["receipt_source_components_do_not_reconcile"],
            "debts_owed_by_committee": _quantize_money(debts_owed) if coverage_complete else None,
        }

    totals_by_label = {label: _MONEY_SCALE for label in _RECEIPT_COMPONENT_LABELS.values()}
    for committee in committee_summaries:
        for component in committee["receipt_source_composition"]:
            totals_by_label[component["label"]] += component["total_amount"]
    return {
        "receipt_source_composition": [
            {"label": label, "total_amount": _quantize_money(amount), "source": "fec_committee_summary"}
            for label, amount in totals_by_label.items()
        ],
        "selected_cycle_coverage_complete": True,
        "can_render_share": True,
        "receipt_source_caveats": [],
        "debts_owed_by_committee": _quantize_money(debts_owed),
    }


def fetch_committee_fundraising_summary(
    conn: psycopg.Connection,
    committee_id: UUID,
    selected_cycle: SelectedCycle | int | None = None,
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
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            COMMITTEE_STORED_FUNDRAISING_SUMMARY_SQL,
            (
                committee_id,
                cycle.selected_cycle,
                committee_id,
            ),
        )
        summary_row = cursor.fetchone()

        if summary_row is None:
            cursor.execute(
                COMMITTEE_FUNDRAISING_SUMMARY_SQL,
                (
                    committee_id,
                    cycle.selected_cycle,
                    committee_id,
                    committee_id,
                    cycle.coverage_start_date,
                    cycle.coverage_end_date,
                    committee_id,
                ),
            )
            summary_row = cursor.fetchone()

    top_lists = _fetch_committee_top_lists(conn, committee_id, cycle)
    cycle_summaries = _fetch_committee_cycle_summaries(conn, committee_id, cycle)
    receipt_source_payload = _fetch_receipt_source_payload(conn, [committee_id], cycle)

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

    summary_row["top_donors"] = top_lists["top_donors"]
    summary_row["top_vendors"] = top_lists["top_vendors"]
    summary_row["spend_categories"] = top_lists["spend_categories"] or None
    summary_row.update(cycle.as_payload())
    summary_row["cycle_summaries"] = cycle_summaries
    summary_row["itemized_transaction_count"] = summary_row["transaction_count"]
    summary_row["summary_source"] = "derived"
    summary_row.update(receipt_source_payload)

    if cycle_summaries:
        _apply_committee_official_totals(summary_row, cycle_summaries)

    return summary_row


def build_zero_committee_fundraising_summary(
    *,
    committee_id: UUID,
    committee_name: str,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    """Return the stable zero-total payload for committees without qualifying transactions."""
    cycle = _coerce_selected_cycle(selected_cycle)
    return {
        "committee_id": committee_id,
        "committee_name": committee_name,
        **cycle.as_payload(),
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
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": ["missing_committee_summary"],
        "debts_owed_by_committee": None,
    }


def _null_candidate_self_funding_payload() -> dict[str, Decimal | None]:
    return {
        "candidate_contrib": None,
        "candidate_loans": None,
        "candidate_loan_repay": None,
        "net_self_funding": None,
    }


def build_zero_candidate_fundraising_summary(
    *,
    candidate_id: UUID,
    candidate_name: str,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    """Return the stable zero-total payload for candidates without linked committees.

    The default ``summary_source`` is ``"derived"`` because no FEC weball totals
    are known in this branch. Callers that have official totals build their own
    payload via ``fetch_candidate_summary``.
    """
    cycle = _coerce_selected_cycle(selected_cycle)
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        **cycle.as_payload(),
        "total_raised": _MONEY_SCALE,
        "total_spent": _MONEY_SCALE,
        "net": _MONEY_SCALE,
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [],
        "cash_on_hand": None,
        **_null_candidate_self_funding_payload(),
        "summary_source": "derived",
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": ["missing_committee_summary"],
        "debts_owed_by_committee": None,
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


def _official_candidate_totals_cover_selected_cycle(
    official_row: dict[str, Any],
    selected_cycle: SelectedCycle,
) -> bool:
    return (
        _has_official_candidate_totals(official_row)
        and official_row["summary_coverage_end_date"] == selected_cycle.coverage_end_date
    )


def _build_candidate_summary_from_official_totals(
    *,
    candidate_id: UUID,
    candidate_name: str,
    official_row: dict[str, Any],
    committee_summaries: list[dict[str, Any]],
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    cycle = _coerce_selected_cycle(selected_cycle)
    total_receipts = official_row["total_receipts"] or _MONEY_SCALE
    total_disbursements = official_row["total_disbursements"] or _MONEY_SCALE
    candidate_contrib = official_row["candidate_contrib"]
    candidate_loans = official_row["candidate_loans"]
    candidate_loan_repay = official_row["candidate_loan_repay"]
    self_funding_components = (candidate_contrib, candidate_loans, candidate_loan_repay)
    net_self_funding = None
    if any(component is not None for component in self_funding_components):
        # Repayments can exceed contributions plus loans, so a negative result is meaningful.
        net_self_funding = (
            (candidate_contrib if candidate_contrib is not None else _MONEY_SCALE)
            + (candidate_loans if candidate_loans is not None else _MONEY_SCALE)
            - (candidate_loan_repay if candidate_loan_repay is not None else _MONEY_SCALE)
        )
    derived_transaction_count = sum(committee["transaction_count"] for committee in committee_summaries)
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        **cycle.as_payload(),
        "total_raised": total_receipts,
        "total_spent": total_disbursements,
        "net": total_receipts - total_disbursements,
        # Official weball totals do not carry itemized counts; callers provide
        # derived committee summaries when those counts are part of the contract.
        "transaction_count": derived_transaction_count,
        "itemized_transaction_count": derived_transaction_count,
        "committees": committee_summaries,
        "cash_on_hand": official_row["cash_on_hand"],
        "candidate_contrib": candidate_contrib,
        "candidate_loans": candidate_loans,
        "candidate_loan_repay": candidate_loan_repay,
        "net_self_funding": net_self_funding,
        "summary_source": "fec_weball",
        **_combine_candidate_receipt_source_payload(committee_summaries),
    }


def fetch_candidate_official_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    candidate_name: str,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any] | None:
    """Return the lightweight FEC weball candidate summary, if populated."""
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CANDIDATE_OFFICIAL_TOTALS_SQL, (candidate_id,))
        official_row = cursor.fetchone()

    if official_row is None or not _official_candidate_totals_cover_selected_cycle(official_row, cycle):
        return None

    return _build_candidate_summary_from_official_totals(
        candidate_id=candidate_id,
        candidate_name=candidate_name,
        official_row=official_row,
        committee_summaries=[],
        selected_cycle=cycle,
    )


_CANDIDATE_COMMITTEE_SUMMARY_TOTALS_SQL = """
    WITH linked_committees AS (
        SELECT DISTINCT committee_id
        FROM cf.candidate_committee_link
        WHERE candidate_id = %s
          AND valid_period && daterange(%s, %s, '[]')
    ),
    supported_cycle_rows AS (
        SELECT
            cs.committee_id,
            cs.cycle,
            cs.total_receipts,
            cs.total_disbursements,
            cs.cash_on_hand
        FROM cf.committee_summary cs
        JOIN linked_committees link
          ON link.committee_id = cs.committee_id
        WHERE cs.cycle = %s
    ),
    latest_cash_on_hand AS (
        SELECT DISTINCT ON (committee_id)
            committee_id,
            cash_on_hand
        FROM supported_cycle_rows
        ORDER BY committee_id, cycle DESC
    )
    SELECT
        COUNT(*)::integer AS summary_row_count,
        ARRAY_REMOVE(ARRAY_AGG(DISTINCT committee_id ORDER BY committee_id), NULL) AS committee_ids,
        COALESCE(SUM(total_receipts), 0) AS total_receipts,
        COALESCE(SUM(total_disbursements), 0) AS total_disbursements,
        (
            SELECT SUM(cash_on_hand)
            FROM latest_cash_on_hand
            WHERE cash_on_hand IS NOT NULL
        ) AS cash_on_hand
    FROM supported_cycle_rows
"""

_CANDIDATE_PUBLIC_MONEY_SUMMARIES_SQL = """
    WITH requested_candidates AS (
        SELECT *
        FROM unnest(%s::uuid[], %s::text[]) AS requested(candidate_id, candidate_name)
    ),
    active_links AS (
        SELECT DISTINCT
            link.candidate_id,
            link.committee_id
        FROM cf.candidate_committee_link link
        JOIN requested_candidates requested
          ON requested.candidate_id = link.candidate_id
        WHERE link.valid_period && daterange(%s, %s, '[]')
    ),
    supported_cycle_rows AS (
        SELECT
            link.candidate_id,
            cs.committee_id,
            cs.cycle,
            cs.total_receipts,
            cs.total_disbursements,
            cs.cash_on_hand
        FROM cf.committee_summary cs
        JOIN active_links link
          ON link.committee_id = cs.committee_id
        WHERE cs.cycle = %s
    ),
    latest_cash_on_hand AS (
        SELECT DISTINCT ON (candidate_id, committee_id)
            candidate_id,
            committee_id,
            cash_on_hand
        FROM supported_cycle_rows
        ORDER BY candidate_id, committee_id, cycle DESC
    ),
    committee_totals AS (
        SELECT
            rows.candidate_id,
            COUNT(*)::integer AS summary_row_count,
            COALESCE(SUM(rows.total_receipts), 0) AS committee_total_receipts,
            COALESCE(SUM(rows.total_disbursements), 0) AS committee_total_disbursements,
            (
                SELECT SUM(cash.cash_on_hand)
                FROM latest_cash_on_hand cash
                WHERE cash.candidate_id = rows.candidate_id
                  AND cash.cash_on_hand IS NOT NULL
            ) AS committee_cash_on_hand
        FROM supported_cycle_rows rows
        GROUP BY rows.candidate_id
    )
    SELECT
        requested.candidate_id,
        requested.candidate_name,
        candidate.total_receipts AS official_total_receipts,
        candidate.total_disbursements AS official_total_disbursements,
        candidate.cash_on_hand AS official_cash_on_hand,
        candidate.candidate_contrib AS official_candidate_contrib,
        candidate.candidate_loans AS official_candidate_loans,
        candidate.candidate_loan_repay AS official_candidate_loan_repay,
        candidate.summary_coverage_end_date AS official_summary_coverage_end_date,
        COALESCE(committee_totals.summary_row_count, 0)::integer AS summary_row_count,
        COALESCE(committee_totals.committee_total_receipts, 0) AS committee_total_receipts,
        COALESCE(committee_totals.committee_total_disbursements, 0) AS committee_total_disbursements,
        committee_totals.committee_cash_on_hand
    FROM requested_candidates requested
    JOIN cf.candidate candidate
      ON candidate.id = requested.candidate_id
    LEFT JOIN committee_totals
      ON committee_totals.candidate_id = requested.candidate_id
"""


def _build_zero_public_candidate_summary(
    *,
    candidate_id: UUID,
    candidate_name: str,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    cycle = _coerce_selected_cycle(selected_cycle)
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        **cycle.as_payload(),
        "total_raised": _MONEY_SCALE,
        "total_spent": _MONEY_SCALE,
        "net": _MONEY_SCALE,
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [],
        "cash_on_hand": None,
        **_null_candidate_self_funding_payload(),
        "summary_source": "derived",
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": ["missing_committee_summary"],
        "debts_owed_by_committee": None,
    }


def _build_public_candidate_summary_from_batch_row(
    row: dict[str, Any],
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    cycle = _coerce_selected_cycle(selected_cycle)
    candidate_id = row["candidate_id"]
    candidate_name = row["candidate_name"]
    official_row = {
        "total_receipts": row["official_total_receipts"],
        "total_disbursements": row["official_total_disbursements"],
        "cash_on_hand": row["official_cash_on_hand"],
        "candidate_contrib": row["official_candidate_contrib"],
        "candidate_loans": row["official_candidate_loans"],
        "candidate_loan_repay": row["official_candidate_loan_repay"],
        "summary_coverage_end_date": row["official_summary_coverage_end_date"],
    }
    if _official_candidate_totals_cover_selected_cycle(official_row, cycle):
        return _build_candidate_summary_from_official_totals(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            official_row=official_row,
            committee_summaries=[],
            selected_cycle=cycle,
        )

    if row["summary_row_count"] == 0:
        return _build_zero_public_candidate_summary(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            selected_cycle=cycle,
        )

    total_receipts = row["committee_total_receipts"] or _MONEY_SCALE
    total_disbursements = row["committee_total_disbursements"] or _MONEY_SCALE
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        **cycle.as_payload(),
        "total_raised": total_receipts,
        "total_spent": total_disbursements,
        "net": total_receipts - total_disbursements,
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [],
        "cash_on_hand": row["committee_cash_on_hand"],
        **_null_candidate_self_funding_payload(),
        "summary_source": "fec_committee_summary",
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": ["missing_committee_summary"],
        "debts_owed_by_committee": None,
    }


def fetch_candidate_public_money_summaries(
    conn: psycopg.Connection,
    candidates: Sequence[tuple[UUID, str]],
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[UUID, dict[str, Any]]:
    """Return public-money candidate summaries for many selected candidates."""
    if not candidates:
        return {}

    candidate_ids = [candidate_id for candidate_id, _candidate_name in candidates]
    candidate_names = [candidate_name for _candidate_id, candidate_name in candidates]
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CANDIDATE_PUBLIC_MONEY_SUMMARIES_SQL,
            (
                candidate_ids,
                candidate_names,
                cycle.coverage_start_date,
                cycle.coverage_end_date,
                cycle.selected_cycle,
            ),
        )
        return {
            row["candidate_id"]: _build_public_candidate_summary_from_batch_row(row, cycle) for row in cursor.fetchall()
        }


def fetch_candidate_public_money_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    candidate_name: str,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any] | None:
    """Return the public-money candidate summary without private detail queries."""
    cycle = _coerce_selected_cycle(selected_cycle)
    official_summary = fetch_candidate_official_summary(conn, candidate_id, candidate_name, cycle)
    if official_summary is not None:
        return official_summary

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CANDIDATE_COMMITTEE_SUMMARY_TOTALS_SQL,
            (candidate_id, cycle.coverage_start_date, cycle.coverage_end_date, cycle.selected_cycle),
        )
        committee_summary_row = cursor.fetchone()

    if committee_summary_row is None:
        return None
    if committee_summary_row["summary_row_count"] == 0:
        return _build_zero_public_candidate_summary(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            selected_cycle=cycle,
        )

    total_receipts = committee_summary_row["total_receipts"] or _MONEY_SCALE
    total_disbursements = committee_summary_row["total_disbursements"] or _MONEY_SCALE
    linked_committee_ids = committee_summary_row["committee_ids"] or []
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        **cycle.as_payload(),
        "total_raised": total_receipts,
        "total_spent": total_disbursements,
        "net": total_receipts - total_disbursements,
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [],
        "cash_on_hand": committee_summary_row["cash_on_hand"],
        **_null_candidate_self_funding_payload(),
        "summary_source": "fec_committee_summary",
        **_fetch_receipt_source_payload(conn, linked_committee_ids, cycle),
    }


def fetch_candidate_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    candidate_name: str,
    selected_cycle: SelectedCycle | int | None = None,
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
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(CANDIDATE_OFFICIAL_TOTALS_SQL, (candidate_id,))
        official_row = cursor.fetchone()

    if official_row is None:
        return None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            CANDIDATE_LINKED_COMMITTEE_IDS_SQL, (candidate_id, cycle.coverage_start_date, cycle.coverage_end_date)
        )
        linked_committee_rows = list(cursor.fetchall())

    committee_summaries: list[dict[str, Any]] = []
    for linked_committee_row in linked_committee_rows:
        committee_id = linked_committee_row["committee_id"]
        committee_summary = fetch_committee_fundraising_summary(conn, committee_id, cycle)
        if committee_summary is None:
            committee_row = fetch_one_row(conn, query=CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, row_id=committee_id)
            if committee_row is None:
                raise RuntimeError(f"Linked committee not found for candidate summary: {committee_id}")
            committee_summary = build_zero_committee_fundraising_summary(
                committee_id=committee_id,
                committee_name=committee_row["name"],
                selected_cycle=cycle,
            )
        committee_summaries.append(committee_summary)

    if _official_candidate_totals_cover_selected_cycle(official_row, cycle):
        return _build_candidate_summary_from_official_totals(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            official_row=official_row,
            committee_summaries=committee_summaries,
            selected_cycle=cycle,
        )

    derived_transaction_count = sum(committee["transaction_count"] for committee in committee_summaries)
    derived_total_raised = sum((committee["total_raised"] for committee in committee_summaries), start=_MONEY_SCALE)
    derived_total_spent = sum((committee["total_spent"] for committee in committee_summaries), start=_MONEY_SCALE)
    derived_net = sum((committee["net"] for committee in committee_summaries), start=_MONEY_SCALE)
    receipt_source_payload = _combine_candidate_receipt_source_payload(committee_summaries)
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        **cycle.as_payload(),
        "total_raised": derived_total_raised,
        "total_spent": derived_total_spent,
        "net": derived_net,
        "transaction_count": derived_transaction_count,
        "itemized_transaction_count": derived_transaction_count,
        "committees": committee_summaries,
        "cash_on_hand": None,
        **_null_candidate_self_funding_payload(),
        "summary_source": "derived",
        **receipt_source_payload,
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


def fetch_candidates_for_people(
    conn: psycopg.Connection,
    person_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    """Fetch candidate rows for many people in one query, grouped by person."""
    if not person_ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CANDIDATES_FOR_PEOPLE_SQL, (person_ids,))
        rows = list(cursor.fetchall())

    candidates_by_person: dict[UUID, list[dict[str, Any]]] = {}
    for row in rows:
        candidates_by_person.setdefault(row["person_id"], []).append(row)
    return candidates_by_person


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
    selected_cycle: SelectedCycle | int | None = None,
) -> list[dict[str, Any]]:
    """Fetch filtered transaction list for a committee."""
    cycle = _coerce_selected_cycle(selected_cycle)
    return _fetch_filtered_rows(
        conn,
        sql_template=_TRANSACTION_LIST_SQL_TEMPLATE,
        filter_values=(
            (params.committee_id, "t.committee_id = %s"),
            (params.jurisdiction, "ds.jurisdiction = %s"),
            (cycle.coverage_start_date, "t.transaction_date >= %s"),
            (cycle.coverage_end_date, "t.transaction_date <= %s"),
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

_CANDIDATE_IE_QUALIFYING_PREDICATE_SQL = """
    t.support_oppose IS NOT NULL
    AND t.is_memo = FALSE
    AND t.amendment_indicator != 'T'
    AND (t.source_record_id IS NULL OR sr.id IS NOT NULL)
"""

_CANDIDATE_IE_QUALIFYING_WHERE_SQL = f"""
    WHERE t.recipient_candidate_id = %s
      AND {_CANDIDATE_IE_QUALIFYING_PREDICATE_SQL}
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
      AND t.transaction_date >= %s
      AND t.transaction_date <= %s
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
      AND t.transaction_date >= %s
      AND t.transaction_date <= %s
      AND {_IE_OUTLIER_WHERE_CLAUSE}
"""

_CANDIDATE_IE_SUMMARIES_SQL = f"""
    WITH qualified AS (
        SELECT
            t.recipient_candidate_id AS candidate_id,
            t.support_oppose,
            t.amount
        FROM cf.transaction t
        {_CANDIDATE_IE_SOURCE_RECORD_JOIN_SQL}
        WHERE t.recipient_candidate_id = ANY(%s::uuid[])
          AND t.transaction_date >= %s
          AND t.transaction_date <= %s
          AND {_CANDIDATE_IE_QUALIFYING_PREDICATE_SQL}
    ),
    classified AS (
        SELECT *, amount > %s AS is_outlier
        FROM qualified
    )
    SELECT
        candidate_id,
        COALESCE(SUM(amount) FILTER (WHERE support_oppose = 'S' AND NOT is_outlier), 0) AS support_total,
        COALESCE(SUM(amount) FILTER (WHERE support_oppose = 'O' AND NOT is_outlier), 0) AS oppose_total,
        COUNT(*) FILTER (WHERE support_oppose = 'S' AND NOT is_outlier)::integer AS support_count,
        COUNT(*) FILTER (WHERE support_oppose = 'O' AND NOT is_outlier)::integer AS oppose_count,
        COUNT(*) FILTER (WHERE is_outlier)::integer AS excluded_outlier_count
    FROM classified
    GROUP BY candidate_id
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
      AND t.transaction_date >= %s
      AND t.transaction_date <= %s
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
      AND t.transaction_date >= %s
      AND t.transaction_date <= %s
      AND t.amount > %s
"""


def _quantize_money(value: Any) -> Decimal:
    return Decimal(value).quantize(_MONEY_SCALE)


def _quantize_money_fields(row: dict[str, Any], *field_names: str) -> None:
    for field_name in field_names:
        row[field_name] = _quantize_money(row[field_name])


def _zero_person_contribution_insights(
    person_id: UUID,
    *,
    excluded_geography: str,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    """Return the stable empty contribution-insights payload for a known person."""
    cycle = _coerce_selected_cycle(selected_cycle)
    return {
        "person_id": person_id,
        "has_data": False,
        "metadata": {
            **cycle.as_payload(),
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
            "geography_mode": "excluded",
            "classified_amount": _MONEY_SCALE,
            "classified_transaction_count": 0,
            "unknown_amount": _MONEY_SCALE,
            "unknown_transaction_count": 0,
        },
        "small_dollar_share": {
            "small_dollar_amount": None,
            "total_contribution_amount": None,
            "share": None,
            "available": False,
        },
    }


def _fetch_person_insights_linked_committee_ids(
    conn: psycopg.Connection,
    person_id: UUID,
    selected_cycle: SelectedCycle,
) -> list[UUID]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_LINKED_COMMITTEES_SQL,
            (person_id, selected_cycle.coverage_start_date, selected_cycle.coverage_end_date),
        )
        return [row["committee_id"] for row in cursor.fetchall()]


def _fetch_person_insights_office(conn: psycopg.Connection, person_id: UUID) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_CONTRIBUTION_INSIGHTS_OFFICE_SQL, (person_id,))
        return cursor.fetchone()


def _fetch_person_insights_rows(
    conn: psycopg.Connection,
    query: str,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
    *extra_params: object,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            query,
            (committee_ids, selected_cycle.coverage_start_date, selected_cycle.coverage_end_date, *extra_params),
        )
        rows = list(cursor.fetchall())
    for row in rows:
        if "total_amount" in row:
            row["total_amount"] = _quantize_money(row["total_amount"])
    return rows


def _fetch_person_insights_one(
    conn: psycopg.Connection,
    query: str,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
    *extra_params: object,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            query,
            (committee_ids, selected_cycle.coverage_start_date, selected_cycle.coverage_end_date, *extra_params),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Contribution insights aggregate query returned no row")
    if "total_amount" in row:
        row["total_amount"] = _quantize_money(row["total_amount"])
    return row


def _fetch_person_insights_itemized_rollups(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
    *,
    complete_summary_coverage: bool,
    district_params: tuple[bool, str | None, str | None, str | None] = (False, None, None, None),
) -> dict[str, Any]:
    """Fetch itemized contribution rollups from one shared qualifying-transaction scan."""
    district_enabled, office_name, office_state, office_district = district_params
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_ITEMIZED_ROLLUPS_SQL,
            (
                committee_ids,
                selected_cycle.coverage_start_date,
                selected_cycle.coverage_end_date,
                complete_summary_coverage,
                selected_cycle.coverage_start_date,
                complete_summary_coverage,
                selected_cycle.coverage_end_date,
                district_enabled,
                office_name,
                office_name,
                office_state,
                office_name,
                office_state,
                office_district or "",
                office_state,
                district_enabled,
                district_enabled,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Contribution insights itemized rollup query returned no row")

    monthly_rows = _json_rows(row["monthly_totals"])
    state_rows = _json_rows(row["state_totals"])
    totals_row = _json_object(row["totals"])
    itemized_buckets = _json_rows(row["itemized_size_buckets"])
    itemized_cycle_rows = _json_rows(row["itemized_cycle_totals"])
    district_rows = _json_rows(row["district_totals"])

    for monthly_row in monthly_rows:
        _quantize_money_fields(monthly_row, "total_amount")
    for state_row in state_rows:
        _quantize_money_fields(state_row, "total_amount")
    _quantize_money_fields(totals_row, "total_amount")
    for bucket in itemized_buckets:
        _quantize_money_fields(bucket, "min_amount", "total_amount")
        if bucket["max_amount"] is not None:
            bucket["max_amount"] = _quantize_money(bucket["max_amount"])
    for cycle_row in itemized_cycle_rows:
        _quantize_money_fields(cycle_row, "itemized_individual_contribution_amount")
    for district_row in district_rows:
        _quantize_money_fields(district_row, "total_amount")

    return {
        "monthly_rows": monthly_rows,
        "state_rows": state_rows,
        "totals_row": totals_row,
        "itemized_buckets": itemized_buckets,
        "itemized_cycle_rows": itemized_cycle_rows,
        "district_rows": district_rows,
    }


def _zero_person_insights_career_totals() -> dict[str, Any]:
    return {
        "itemized_individual_contribution_amount": _quantize_money(0),
        "itemized_transaction_count": 0,
        "unitemized_individual_contribution_amount": _quantize_money(0),
        "total_individual_contribution_amount": _quantize_money(0),
        "source": "none",
    }


def _fetch_person_insights_summary(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_SQL, (committee_ids, [selected_cycle.selected_cycle]))
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Contribution insights summary query returned no row")
    row["unitemized_total"] = _quantize_money(row["unitemized_total"])
    row["itemized_total"] = _quantize_money(row["itemized_total"]) if row["itemized_total"] is not None else None
    row["cycles_included"] = list(row["cycles_included"] or [])
    return row


def _fetch_person_insights_summary_rollups(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_ROLLUPS_SQL,
            (
                committee_ids,
                [selected_cycle.selected_cycle],
                selected_cycle.coverage_start_date,
                selected_cycle.coverage_end_date,
            ),
        )
        summary_row = cursor.fetchone()
    if summary_row is None:
        raise RuntimeError("Contribution insights summary rollup query returned no row")

    summary_row["unitemized_total"] = _quantize_money(summary_row["unitemized_total"])
    summary_row["itemized_total"] = (
        _quantize_money(summary_row["itemized_total"]) if summary_row["itemized_total"] is not None else None
    )
    summary_row["cycles_included"] = list(summary_row["cycles_included"] or [])

    coverage_rows = _json_rows(summary_row.pop("coverage_rows"))
    summary_cycle_rows = _json_rows(summary_row.pop("summary_cycle_rows"))
    for cycle_row in summary_cycle_rows:
        _quantize_money_fields(cycle_row, "unitemized_individual_contribution_amount")
    return summary_row, coverage_rows, summary_cycle_rows


def _fetch_person_insights_summary_coverage(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_COVERAGE_SQL,
            (
                selected_cycle.coverage_start_date,
                selected_cycle.coverage_end_date,
                committee_ids,
                [selected_cycle.selected_cycle],
            ),
        )
        return list(cursor.fetchall())


def _fetch_person_insights_summary_cycle_totals(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_SUMMARY_BY_CYCLE_SQL,
            (committee_ids, [selected_cycle.selected_cycle]),
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
    selected_cycle: SelectedCycle,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _PERSON_CONTRIBUTION_INSIGHTS_ITEMIZED_BY_CYCLE_SQL,
            (committee_ids, selected_cycle.coverage_start_date, selected_cycle.coverage_end_date),
        )
        rows = list(cursor.fetchall())
    for row in rows:
        row["itemized_individual_contribution_amount"] = _quantize_money(row["itemized_individual_contribution_amount"])
    return rows


def _has_complete_person_insights_summary(
    summary_row: dict[str, Any],
    summary_coverage_rows: list[dict[str, Any]],
    committee_count: int,
    selected_cycle: SelectedCycle,
) -> bool:
    if summary_row["summary_committee_count"] != committee_count:
        return False
    if not summary_coverage_rows:
        return False
    return all(
        row["committee_count"] == committee_count and row["complete_committee_count"] == committee_count
        for row in summary_coverage_rows
    )


def _person_insights_itemized_summary_reconciles(
    summary_row: dict[str, Any],
    itemized_total: Decimal,
) -> bool:
    summary_itemized_total = summary_row["itemized_total"]
    if summary_itemized_total is None:
        return False
    return abs(_quantize_money(summary_itemized_total) - _quantize_money(itemized_total)) <= Decimal("0.01")


def _person_insights_has_itemized_summary_basis(summary_row: dict[str, Any]) -> bool:
    return summary_row["itemized_total"] is not None


def _build_person_insights_itemized_buckets(
    conn: psycopg.Connection,
    committee_ids: list[UUID],
    selected_cycle: SelectedCycle,
) -> list[dict[str, Any]]:
    """Build backend-owned itemized size buckets from qualifying Schedule A rows."""
    buckets: list[dict[str, Any]] = []
    for label, min_amount, max_amount in CONTRIBUTION_INSIGHTS_SIZE_BUCKETS:
        row = _fetch_person_insights_one(
            conn,
            _PERSON_CONTRIBUTION_INSIGHTS_BUCKET_TOTALS_SQL,
            committee_ids,
            selected_cycle,
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
    selected_cycle: SelectedCycle,
) -> tuple[list[dict[str, Any]], bool, str | None, str]:
    """Return district geography rows or the backend-owned omission reason."""
    if office_row is None:
        return [], False, "no_current_federal_officeholding", "excluded"
    if office_row["office_name"] in {"us_president", "us_vice_president"}:
        return [], False, "federal_executive", "state_bars_only"
    if not office_row["state"] or not office_row["district"]:
        if office_row["office_name"] == "us_senate" and office_row["state"]:
            rows = _fetch_person_insights_rows(
                conn,
                _PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL,
                committee_ids,
                selected_cycle,
                office_row["office_name"],
                office_row["office_name"],
                office_row["state"],
                office_row["office_name"],
                office_row["state"],
                "",
                office_row["state"],
            )
            return rows, True, None, "statewide"
        return [], False, "missing_member_district", "excluded"

    rows = _fetch_person_insights_rows(
        conn,
        _PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL,
        committee_ids,
        selected_cycle,
        office_row["office_name"],
        office_row["office_name"],
        office_row["state"],
        office_row["office_name"],
        office_row["state"],
        office_row["district"],
        office_row["state"],
    )
    matched_rows = [row for row in rows if row["label"] != "Unknown"]
    unknown_rows = [row for row in rows if row["label"] == "Unknown"]
    if unknown_rows:
        caveats.append("missing_zcta_district")
    if selected_cycle.selected_cycle != max(SUPPORTED_COMMITTEE_SUMMARY_CYCLES):
        caveats.append("current_district_approximation")
    if not matched_rows:
        return [], True, None, "district"
    return rows, True, None, "district"


def _person_insights_district_rollup_params(
    office_row: dict[str, Any] | None,
) -> tuple[tuple[bool, str | None, str | None, str | None], bool, str | None, str]:
    if office_row is None:
        return (False, None, None, None), False, "no_current_federal_officeholding", "excluded"
    if office_row["office_name"] in {"us_president", "us_vice_president"}:
        return (False, None, None, None), False, "federal_executive", "state_bars_only"
    if not office_row["state"] or not office_row["district"]:
        if office_row["office_name"] == "us_senate" and office_row["state"]:
            return (True, office_row["office_name"], office_row["state"], ""), True, None, "statewide"
        return (False, None, None, None), False, "missing_member_district", "excluded"
    return (
        (True, office_row["office_name"], office_row["state"], office_row["district"]),
        True,
        None,
        "district",
    )


def _finalize_person_insights_district_rows(
    rows: list[dict[str, Any]],
    *,
    geography_mode: str,
    selected_cycle: SelectedCycle,
    caveats: list[str],
) -> list[dict[str, Any]]:
    if geography_mode != "district":
        return rows

    matched_rows = [row for row in rows if row["label"] != "Unknown"]
    unknown_rows = [row for row in rows if row["label"] == "Unknown"]
    if unknown_rows:
        caveats.append("missing_zcta_district")
    if selected_cycle.selected_cycle != max(SUPPORTED_COMMITTEE_SUMMARY_CYCLES):
        caveats.append("current_district_approximation")
    if not matched_rows:
        return []
    return rows


def _geography_denominators(rows: list[dict[str, Any]], unknown_label: str = "Unknown") -> dict[str, Any]:
    """Split geography rows into classified and unknown contribution denominators."""
    classified_amount = _MONEY_SCALE
    classified_transaction_count = 0
    unknown_amount = _MONEY_SCALE
    unknown_transaction_count = 0
    for row in rows:
        if row["label"] == unknown_label:
            unknown_amount += row["total_amount"]
            unknown_transaction_count += row["transaction_count"]
        else:
            classified_amount += row["total_amount"]
            classified_transaction_count += row["transaction_count"]
    return {
        "classified_amount": _quantize_money(classified_amount),
        "classified_transaction_count": classified_transaction_count,
        "unknown_amount": _quantize_money(unknown_amount),
        "unknown_transaction_count": unknown_transaction_count,
    }


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
        "Elsewhere in state": Decimal("0.00"),
        "In state": Decimal("0.00"),
        "Out of state": Decimal("0.00"),
        "Unknown": Decimal("0.00"),
    }
    for row in district_rows:
        label = str(row["label"])
        if label not in amounts:
            raise ValueError(f"Unexpected district contribution label: {label}")
        amounts[label] = _quantize_money(amounts[label] + row["total_amount"])

    in_district_amount = amounts["In district"] + amounts["In state"]
    out_of_district_amount = amounts["Elsewhere in state"] + amounts["Out of state"]
    unknown_district_amount = amounts["Unknown"]
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


def fetch_person_contribution_insights(
    conn: psycopg.Connection,
    person_id: UUID,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any] | None:
    """Return person-level contribution insights for active linked candidate committees."""
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_EXISTS_SQL, (person_id,))
        if cursor.fetchone() is None:
            return None

    committee_ids = _fetch_person_insights_linked_committee_ids(conn, person_id, cycle)
    if not committee_ids:
        return _zero_person_contribution_insights(
            person_id,
            excluded_geography="no_linked_candidate",
            selected_cycle=cycle,
        )

    summary_row, summary_coverage_rows, summary_cycle_rows = _fetch_person_insights_summary_rollups(
        conn,
        committee_ids,
        cycle,
    )
    complete_summary_coverage = _has_complete_person_insights_summary(
        summary_row,
        summary_coverage_rows,
        len(committee_ids),
        cycle,
    )
    office_row = _fetch_person_insights_office(conn, person_id)
    caveats: list[str] = []
    district_params, approximate_geography, excluded_geography, geography_mode = (
        _person_insights_district_rollup_params(
            office_row,
        )
    )
    itemized_rollups = _fetch_person_insights_itemized_rollups(
        conn,
        committee_ids,
        cycle,
        complete_summary_coverage=complete_summary_coverage,
        district_params=district_params,
    )
    monthly_rows = itemized_rollups["monthly_rows"]
    state_rows = itemized_rollups["state_rows"]
    totals_row = itemized_rollups["totals_row"]
    itemized_buckets = itemized_rollups["itemized_buckets"]
    itemized_cycle_rows = itemized_rollups["itemized_cycle_rows"]

    itemized_total = totals_row["total_amount"]
    has_reconciliation_basis = complete_summary_coverage and _person_insights_has_itemized_summary_basis(
        summary_row,
    )
    summary_available = has_reconciliation_basis and _person_insights_itemized_summary_reconciles(
        summary_row,
        itemized_total,
    )
    if not summary_available:
        if not complete_summary_coverage:
            caveats.append("missing_committee_summary")
            caveats.append("itemized_summary_reconciliation_unavailable")
        elif not has_reconciliation_basis:
            caveats.append("itemized_summary_reconciliation_unavailable")
        else:
            caveats.append("itemized_summary_reconciliation_mismatch")
        caveats.append("itemized_only_cycle_totals")
    district_rows = _finalize_person_insights_district_rows(
        itemized_rollups["district_rows"],
        geography_mode=geography_mode,
        selected_cycle=cycle,
        caveats=caveats,
    )
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
            **cycle.as_payload(),
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
            "geography_mode": geography_mode,
            **_geography_denominators(state_rows),
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
    selected_cycle: SelectedCycle | int | None = None,
) -> list[dict[str, Any]]:
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CANDIDATE_IE_LIST_SQL,
            (candidate_id, cycle.coverage_start_date, cycle.coverage_end_date, limit, offset),
        )
        return list(cursor.fetchall())


def fetch_candidate_ie_summary(
    conn: psycopg.Connection,
    candidate_id: UUID,
    *,
    selected_cycle: SelectedCycle | int | None = None,
    top_spenders_limit: int = _IE_TOP_SPENDERS_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Fetch aggregated IE support/oppose totals and top spenders for a candidate.

    Stage 5: rows above ``CANDIDATE_IE_OUTLIER_CEILING`` are excluded from totals,
    counts, and top-spender rankings; the count of excluded rows is surfaced under
    ``excluded_outlier_count``. The raw list endpoint keeps returning every row.
    """
    cycle = _coerce_selected_cycle(selected_cycle)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CANDIDATE_IE_SUMMARY_SQL,
            (candidate_id, cycle.coverage_start_date, cycle.coverage_end_date, CANDIDATE_IE_OUTLIER_CEILING),
        )
        summary_row = cursor.fetchone()
        if summary_row is None:
            raise RuntimeError(f"IE summary query returned no rows for candidate: {candidate_id}")

        cursor.execute(
            _CANDIDATE_IE_TOP_SPENDERS_SQL,
            (
                candidate_id,
                cycle.coverage_start_date,
                cycle.coverage_end_date,
                CANDIDATE_IE_OUTLIER_CEILING,
                top_spenders_limit,
            ),
        )
        top_spender_rows = list(cursor.fetchall())

        cursor.execute(
            _CANDIDATE_IE_OUTLIER_COUNT_SQL,
            (candidate_id, cycle.coverage_start_date, cycle.coverage_end_date, CANDIDATE_IE_OUTLIER_CEILING),
        )
        outlier_count_row = cursor.fetchone()

    for top_spender_row in top_spender_rows:
        _quantize_money_fields(top_spender_row, "total_amount")

    excluded_outlier_count = 0 if outlier_count_row is None else outlier_count_row["excluded_outlier_count"]
    return {
        "candidate_id": candidate_id,
        **cycle.as_payload(),
        "support_total": _quantize_money(summary_row["support_total"]),
        "oppose_total": _quantize_money(summary_row["oppose_total"]),
        "support_count": summary_row["support_count"],
        "oppose_count": summary_row["oppose_count"],
        "top_spenders": top_spender_rows,
        "excluded_outlier_count": excluded_outlier_count,
    }


def _zero_candidate_ie_summary(
    candidate_id: UUID,
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[str, Any]:
    cycle = _coerce_selected_cycle(selected_cycle)
    return {
        "candidate_id": candidate_id,
        **cycle.as_payload(),
        "support_total": _MONEY_SCALE,
        "oppose_total": _MONEY_SCALE,
        "support_count": 0,
        "oppose_count": 0,
        "top_spenders": [],
        "excluded_outlier_count": 0,
    }


def fetch_candidate_ie_summaries(
    conn: psycopg.Connection,
    candidate_ids: list[UUID],
    selected_cycle: SelectedCycle | int | None = None,
) -> dict[UUID, dict[str, Any]]:
    """Fetch public IE support/oppose totals for many candidates."""
    cycle = _coerce_selected_cycle(selected_cycle)
    summaries = {candidate_id: _zero_candidate_ie_summary(candidate_id, cycle) for candidate_id in candidate_ids}
    if not candidate_ids:
        return summaries

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _CANDIDATE_IE_SUMMARIES_SQL,
            (
                candidate_ids,
                cycle.coverage_start_date,
                cycle.coverage_end_date,
                CANDIDATE_IE_OUTLIER_CEILING,
            ),
        )
        rows = list(cursor.fetchall())

    for row in rows:
        candidate_id = row["candidate_id"]
        summaries[candidate_id] = {
            "candidate_id": candidate_id,
            **cycle.as_payload(),
            "support_total": _quantize_money(row["support_total"]),
            "oppose_total": _quantize_money(row["oppose_total"]),
            "support_count": row["support_count"],
            "oppose_count": row["oppose_count"],
            "top_spenders": [],
            "excluded_outlier_count": row["excluded_outlier_count"],
        }
    return summaries


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
    selected_cycle: SelectedCycle | int | None = None,
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

    cycle = _coerce_selected_cycle(selected_cycle)
    committee_ids = _fetch_person_insights_linked_committee_ids(conn, person_id, cycle)
    if not committee_ids:
        return []

    return _fetch_person_insights_rows(conn, _PERSON_TOP_DONORS_SQL, committee_ids, cycle, limit)


def fetch_person_top_employers(
    conn: psycopg.Connection,
    person_id: UUID,
    limit: int = _PERSON_TOP_DONORS_DEFAULT_LIMIT,
    selected_cycle: SelectedCycle | int | None = None,
) -> list[dict[str, Any]] | None:
    """Return ranked employer-name totals across a person's active linked committees."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PERSON_EXISTS_SQL, (person_id,))
        if cursor.fetchone() is None:
            return None

    cycle = _coerce_selected_cycle(selected_cycle)
    committee_ids = _fetch_person_insights_linked_committee_ids(conn, person_id, cycle)
    if not committee_ids:
        return []

    return _fetch_person_insights_rows(
        conn,
        _PERSON_TOP_EMPLOYERS_SQL,
        committee_ids,
        cycle,
        limit,
    )
