
from __future__ import annotations

from collections.abc import Sequence

import psycopg

from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id

_MVP_COUNTIES: tuple[str, ...] = ("DURHAM", "WAKE", "ORANGE")


def _select_registry_sboe_ids(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT sboe_id
            FROM cf.nc_committee_registry
            WHERE NULLIF(BTRIM(sboe_id), '') IS NOT NULL
            ORDER BY sboe_id ASC
            """
        )
        rows = cursor.fetchall()
    return [row[0] for row in rows]


def _build_synthetic_committee_map(sboe_ids: Sequence[str]) -> tuple[list[str], list[str]]:
    synthetic_committee_ids = [generate_synthetic_committee_id("NC", sboe_id) for sboe_id in sboe_ids]
    return list(sboe_ids), synthetic_committee_ids


def _assert_bridged_candidacies_have_election_link(
    conn: psycopg.Connection,
    *,
    sboe_ids: Sequence[str],
    synthetic_committee_ids: Sequence[str],
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH synthetic_map AS (
                SELECT *
                FROM UNNEST(%s::text[], %s::text[])
                    AS mapped(sboe_id, synthetic_fec_committee_id)
            ),
            registry_candidates AS (
                SELECT DISTINCT
                    mapped.synthetic_fec_committee_id,
                    TRIM(REGEXP_REPLACE(reg.candidate_name, '\\s+', ' ', 'g')) AS normalized_candidate_name
                FROM cf.nc_committee_registry AS reg
                JOIN synthetic_map AS mapped
                    ON mapped.sboe_id = reg.sboe_id
                WHERE NULLIF(BTRIM(reg.candidate_name), '') IS NOT NULL
            ),
            matched_bridge_candidates AS (
                SELECT
                    reg_candidate.synthetic_fec_committee_id,
                    reg_candidate.normalized_candidate_name,
                    cand.id AS candidacy_id,
                    contest.election_id
                FROM registry_candidates AS reg_candidate
                JOIN cf.committee AS committee
                    ON committee.fec_committee_id = reg_candidate.synthetic_fec_committee_id
                JOIN civic.candidacy AS cand
                    ON cand.committee_id = committee.id
                JOIN civic.contest AS contest
                    ON contest.id = cand.contest_id
                JOIN civic.office AS office
                    ON office.id = contest.office_id
                WHERE office.state = 'NC'
                  AND NULLIF(BTRIM(cand.name_on_ballot), '') IS NOT NULL
                  AND COALESCE((cand.raw_fields ->> 'nc_stage1_bridge_owned')::boolean, FALSE)
                  AND TRIM(REGEXP_REPLACE(cand.name_on_ballot, '\\s+', ' ', 'g'))
                      = reg_candidate.normalized_candidate_name
            ),
            inferred_bridge_candidates AS (
                SELECT DISTINCT ON (synthetic_fec_committee_id, normalized_candidate_name)
                    synthetic_fec_committee_id,
                    normalized_candidate_name,
                    candidacy_id,
                    election_id
                FROM matched_bridge_candidates
                ORDER BY
                    synthetic_fec_committee_id,
                    normalized_candidate_name,
                    candidacy_id ASC
            )
            SELECT COUNT(*)
            FROM inferred_bridge_candidates
            WHERE election_id IS NULL
            """,
            (list(sboe_ids), list(synthetic_committee_ids)),
        )
        missing_count = cursor.fetchone()[0]
    if missing_count > 0:
        raise ValueError(
            "select_mvp_scope_committees requires contest.election_id for bridged candidacies; "
            f"found {missing_count} rows with committee_id set and election_id NULL"
        )


def select_mvp_scope_committees(conn: psycopg.Connection) -> list[str]:
    """Return sorted distinct NC SBoE committee IDs in MVP candidacy scope."""
    sboe_ids = _select_registry_sboe_ids(conn)
    if not sboe_ids:
        return []

    map_sboe_ids, synthetic_committee_ids = _build_synthetic_committee_map(sboe_ids)
    _assert_bridged_candidacies_have_election_link(
        conn,
        sboe_ids=map_sboe_ids,
        synthetic_committee_ids=synthetic_committee_ids,
    )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH synthetic_map AS (
                SELECT *
                FROM UNNEST(%s::text[], %s::text[])
                    AS mapped(sboe_id, synthetic_fec_committee_id)
            )
            SELECT DISTINCT reg.sboe_id
            FROM civic.candidacy AS cand
            JOIN civic.contest AS contest
                ON contest.id = cand.contest_id
            JOIN civic.election AS election
                ON election.id = contest.election_id
            JOIN cf.committee AS committee
                ON committee.id = cand.committee_id
            JOIN synthetic_map AS mapped
                ON mapped.synthetic_fec_committee_id = committee.fec_committee_id
            JOIN cf.nc_committee_registry AS reg
                ON reg.sboe_id = mapped.sboe_id
            WHERE (
                election.jurisdiction_scope = 'state'
                AND election.state = 'NC'
            ) OR (
                election.jurisdiction_scope = 'county'
                AND election.state = 'NC'
                AND UPPER(COALESCE(election.county, '')) = ANY(%s::text[])
            )
            ORDER BY reg.sboe_id ASC
            """,
            (map_sboe_ids, synthetic_committee_ids, list(_MVP_COUNTIES)),
        )
        rows = cursor.fetchall()
    return [row[0] for row in rows]
