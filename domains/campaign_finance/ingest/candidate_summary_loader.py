"""Candidate summary persistence for FEC bulk ingest."""

from __future__ import annotations

import psycopg


def update_candidate_summary(
    conn: psycopg.Connection,
    *,
    mapped_fields: dict[str, object],
) -> None:
    """Keep candidate weball totals from the newest coverage date.

    Equal-date corrections replace prior values.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH matched_candidate AS (
                SELECT id,
                       (
                           (
                               %s::date IS NOT NULL
                               AND (
                                   summary_coverage_end_date IS NULL
                                   OR %s::date >= summary_coverage_end_date
                               )
                           )
                           OR (
                               %s::date IS NULL
                               AND summary_coverage_end_date IS NULL
                           )
                       ) AS summary_coverage_end_date_is_newer
                FROM cf.candidate
                WHERE fec_candidate_id = %s
                FOR UPDATE
            )
            UPDATE cf.candidate AS candidate
            -- Prevent load-order nondeterminism. Per-cycle storage stays out of
            -- scope because serving labels this total with its coverage window.
            SET total_receipts = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.total_receipts
                END,
                total_disbursements = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.total_disbursements
                END,
                cash_on_hand = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.cash_on_hand
                END,
                candidate_contrib = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.candidate_contrib
                END,
                candidate_loans = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.candidate_loans
                END,
                candidate_loan_repay = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.candidate_loan_repay
                END,
                summary_coverage_end_date = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN %s
                    ELSE candidate.summary_coverage_end_date
                END,
                updated_at = CASE
                    WHEN matched_candidate.summary_coverage_end_date_is_newer THEN NOW()
                    ELSE candidate.updated_at
                END
            FROM matched_candidate
            WHERE candidate.id = matched_candidate.id
            """,
            (
                mapped_fields["summary_coverage_end_date"],
                mapped_fields["summary_coverage_end_date"],
                mapped_fields["summary_coverage_end_date"],
                mapped_fields["fec_candidate_id"],
                mapped_fields["total_receipts"],
                mapped_fields["total_disbursements"],
                mapped_fields["cash_on_hand"],
                mapped_fields["candidate_contrib"],
                mapped_fields["candidate_loans"],
                mapped_fields["candidate_loan_repay"],
                mapped_fields["summary_coverage_end_date"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Expected one candidate summary update for {mapped_fields['fec_candidate_id']}")
