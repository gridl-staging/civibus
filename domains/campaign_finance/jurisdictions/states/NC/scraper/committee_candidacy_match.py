from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from core.db import find_organization_by_identifier
from domains.campaign_finance.ingest.filing_loader import ensure_authority_committee
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    ensure_nc_committee_document_data_source,
)

LOGGER = logging.getLogger(__name__)

_NORMALIZED_NONEMPTY_TEXT_PREDICATE = "NULLIF(trim(regexp_replace({value}, '\\s+', ' ', 'g')), '') IS NOT NULL"


def _materialize_nc_committees_for_name_match(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
) -> None:
    """Ensure every in-scope NC registry row has a corresponding cf.committee row."""
    rows = conn.execute(
        f"""
        SELECT DISTINCT trim(regexp_replace(r.sboe_id, '\\s+', ' ', 'g')) AS sboe_id
        FROM cf.nc_committee_registry r
        WHERE {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.sboe_id")}
          AND {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.candidate_name")}
        """,
    ).fetchall()

    for row in rows:
        sboe_id = row[0]
        organization_id = find_organization_by_identifier(
            conn,
            "nc_sboe_id",
            sboe_id,
            data_source_id=data_source_id,
        )
        if organization_id is None:
            raise ValueError(
                "Missing core.organization bridge for NC registry row "
                f"nc_sboe_id={sboe_id!r}; cannot materialize committee mapping"
            )
        ensure_authority_committee(
            conn,
            data_source_id=data_source_id,
            authority_type="state",
            authority_code="NC",
            native_committee_id=sboe_id,
            organization_id=organization_id,
        )


def _log_ambiguous_candidate_name_count(conn: psycopg.Connection, *, data_source_id: UUID) -> None:
    row = conn.execute(
        f"""
        WITH registry_matches AS (
            SELECT
                trim(regexp_replace(r.candidate_name, '\\s+', ' ', 'g')) AS norm_name,
                c.id AS committee_id
            FROM cf.nc_committee_registry r
            JOIN core.organization o
              ON o.identifiers ->> 'nc_sboe_id' = trim(regexp_replace(r.sboe_id, '\\s+', ' ', 'g'))
            JOIN cf.committee c
              ON c.organization_id = o.id
             AND c.data_source_id = %s
            WHERE {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.candidate_name")}
              AND {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.sboe_id")}
        )
        SELECT COUNT(*)::int
        FROM (
            SELECT norm_name
            FROM registry_matches
            GROUP BY norm_name
            HAVING COUNT(DISTINCT committee_id) > 1
        ) ambiguous
        """,
        (data_source_id,),
    ).fetchone()
    assert row is not None
    ambiguous_name_count = int(row[0])
    if ambiguous_name_count > 0:
        LOGGER.warning(
            "NC run_name_match_pass skipped %s ambiguous candidate_name values",
            ambiguous_name_count,
        )


def run_name_match_pass(conn: psycopg.Connection) -> int:
    """Match NC registry candidate names to civic candidacies and set committee_id."""
    data_source_id = ensure_nc_committee_document_data_source(conn)
    _materialize_nc_committees_for_name_match(conn, data_source_id=data_source_id)
    _log_ambiguous_candidate_name_count(conn, data_source_id=data_source_id)

    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            WITH registry_matches AS (
                SELECT
                    trim(regexp_replace(r.candidate_name, '\\s+', ' ', 'g')) AS norm_name,
                    c.id AS committee_id
                FROM cf.nc_committee_registry r
                JOIN core.organization o
                  ON o.identifiers ->> 'nc_sboe_id' = trim(regexp_replace(r.sboe_id, '\\s+', ' ', 'g'))
                JOIN cf.committee c
                  ON c.organization_id = o.id
                 AND c.data_source_id = %s
                WHERE {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.candidate_name")}
                  AND {_NORMALIZED_NONEMPTY_TEXT_PREDICATE.format(value="r.sboe_id")}
            ),
            unambiguous AS (
                SELECT
                    norm_name,
                    (array_agg(committee_id ORDER BY committee_id))[1] AS committee_id
                FROM registry_matches
                GROUP BY norm_name
                HAVING COUNT(DISTINCT committee_id) = 1
            )
            UPDATE civic.candidacy ca
            SET committee_id = u.committee_id,
                updated_at = NOW()
            FROM unambiguous u, civic.contest ct, civic.office ofc
            WHERE trim(regexp_replace(ca.name_on_ballot, '\\s+', ' ', 'g')) = u.norm_name
              AND ct.id = ca.contest_id
              AND ofc.id = ct.office_id
              AND ca.committee_id IS NULL
              AND ofc.state = 'NC'
              AND ofc.office_level <> 'federal'
            """,
            (data_source_id,),
        )
        updated_rows = cursor.rowcount

    if updated_rows < 0:
        return 0
    return updated_rows
