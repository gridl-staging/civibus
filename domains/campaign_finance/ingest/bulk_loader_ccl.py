from __future__ import annotations

from datetime import date
from uuid import UUID

import psycopg

from domains.campaign_finance.ingest.text_utils import normalize_optional_text


def _insert_candidate_committee_link(
    conn: psycopg.Connection,
    *,
    candidate_id: UUID,
    committee_id: UUID,
    designation: str | None,
    candidate_election_year: int,
    fec_election_year: int | None,
    period_start: date,
    period_end: date,
    source_record_id: UUID,
) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT candidate_committee_link_insert")
        try:
            cursor.execute(
                """
                INSERT INTO cf.candidate_committee_link (
                    candidate_id,
                    committee_id,
                    election_id,
                    designation,
                    candidate_election_year,
                    fec_election_year,
                    valid_period,
                    date_precision,
                    source_record_id
                )
                VALUES (
                    %s,
                    %s,
                    NULL,
                    %s,
                    %s,
                    %s,
                    daterange(%s, %s, '[)'),
                    'year',
                    %s
                )
                """,
                (
                    candidate_id,
                    committee_id,
                    designation,
                    candidate_election_year,
                    fec_election_year,
                    period_start,
                    period_end,
                    source_record_id,
                ),
            )
        except psycopg.errors.ExclusionViolation:
            cursor.execute("ROLLBACK TO SAVEPOINT candidate_committee_link_insert")
            cursor.execute("RELEASE SAVEPOINT candidate_committee_link_insert")
            return False

        cursor.execute("RELEASE SAVEPOINT candidate_committee_link_insert")
    return True


def _build_ccl_source_record_key(cycle_key: str, mapped_fields: dict[str, object]) -> str | None:
    linkage_id = normalize_optional_text(mapped_fields.get("linkage_id"))
    if linkage_id is not None:
        return f"ccl:{cycle_key}:{linkage_id}"

    candidate_fec_id = normalize_optional_text(mapped_fields.get("candidate_fec_id"))
    committee_fec_id = normalize_optional_text(mapped_fields.get("committee_fec_id"))
    candidate_election_year = mapped_fields.get("candidate_election_year")

    if candidate_fec_id is None or committee_fec_id is None or not isinstance(candidate_election_year, int):
        return None

    return f"ccl:{cycle_key}:{candidate_fec_id}:{committee_fec_id}:{candidate_election_year}"
