from __future__ import annotations

from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import insert_organization
from core.types.python.models import Organization
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_committee_document_data_source,
    load_nc_committee_documents,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import parse_committee_docs

pytestmark = pytest.mark.integration

_SAMPLE_COMMITTEE_DOCS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "committee_document_export_sample.csv"
)


def _parsed_committee_doc_rows() -> list[dict[str, str | None]]:
    return list(parse_committee_docs(_SAMPLE_COMMITTEE_DOCS_PATH))


def _insert_nc_committee_bridge(
    conn: psycopg.Connection,
    *,
    committee_sboe_id: str,
    committee_name: str = "NC Committee Bridge",
) -> UUID:
    return insert_organization(
        conn,
        Organization(
            canonical_name=f"{committee_name} {committee_sboe_id}",
            identifiers={"nc_sboe_id": committee_sboe_id},
        ),
    )


def _select_filing_fec_ids(conn: psycopg.Connection, prefix: str) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id
            FROM cf.filing
            WHERE filing_fec_id LIKE %s
            ORDER BY filing_fec_id
            """,
            (f"{prefix}%",),
        )
        rows = cursor.fetchall()
    return [row["filing_fec_id"] for row in rows]


def test_load_nc_committee_documents_creates_filings_and_bridges_committees(
    db_conn: psycopg.Connection,
) -> None:
    committee_rows = _parsed_committee_doc_rows()
    committee_sboe_id = committee_rows[0]["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Fixture Committee")

    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)
    result, filing_lookup = load_nc_committee_documents(
        db_conn,
        _SAMPLE_COMMITTEE_DOCS_PATH,
        data_source_id=committee_document_data_source_id,
    )

    assert result.inserted == 8
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0
    assert len(filing_lookup) == 7
    assert "NC-001-4L70LV-C-001-2025-mid-year-semi-annual" in _select_filing_fec_ids(
        db_conn,
        "NC-001-4L70LV-C-001-",
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'NC'
              AND o.identifiers ->> 'nc_sboe_id' = %s
            """,
            (committee_sboe_id,),
        )
        committee_count = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE amendment_indicator = 'A') AS amended
            FROM cf.filing
            WHERE filing_fec_id LIKE 'NC-001-4L70LV-C-001-%'
            """,
        )
        filing_counts = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing f
            JOIN core.source_record sr
              ON sr.id = f.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE f.filing_fec_id LIKE 'NC-001-4L70LV-C-001-%'
              AND ds.name = 'North Carolina SBoE Committee/Document Search'
            """
        )
        filing_provenance_count = cursor.fetchone()["count"]

    assert committee_count == 1
    assert filing_counts["total"] == 7
    assert filing_counts["amended"] == 1
    assert filing_provenance_count == 7


def test_load_nc_committee_documents_is_idempotent_for_filings_and_committees(
    db_conn: psycopg.Connection,
) -> None:
    committee_sboe_id = "001-4L70LV-C-001"
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Idempotent Committee")
    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)

    first_result, _ = load_nc_committee_documents(
        db_conn,
        _SAMPLE_COMMITTEE_DOCS_PATH,
        data_source_id=committee_document_data_source_id,
    )
    filing_ids_after_first = _select_filing_fec_ids(db_conn, "NC-001-4L70LV-C-001-")

    second_result, _ = load_nc_committee_documents(
        db_conn,
        _SAMPLE_COMMITTEE_DOCS_PATH,
        data_source_id=committee_document_data_source_id,
    )
    filing_ids_after_second = _select_filing_fec_ids(db_conn, "NC-001-4L70LV-C-001-")

    assert first_result.inserted == 8
    assert second_result.inserted == 0
    assert second_result.skipped == 8
    assert filing_ids_after_second == filing_ids_after_first

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'NC'
              AND o.identifiers ->> 'nc_sboe_id' = %s
            """,
            (committee_sboe_id,),
        )
        committee_count = cursor.fetchone()["count"]
    assert committee_count == 1
