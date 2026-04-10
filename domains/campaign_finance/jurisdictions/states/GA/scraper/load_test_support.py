"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/GA/scraper/load_test_support.py.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Mapping
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from core.db import get_connection
from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.GA.scraper import (
    _find_ga_data_source_block_by_transaction_type,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
GA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA"
CONTRIBUTION_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "contribution_export_sample.xls"
EXPENDITURE_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "expenditure_export_sample.xls"


def parsed_contribution_rows() -> list[dict[str, object]]:
    return [dict(row) for row in parse_contributions(CONTRIBUTION_FIXTURE_PATH)]


def parsed_expenditure_rows() -> list[dict[str, object]]:
    return [dict(row) for row in parse_expenditures(EXPENDITURE_FIXTURE_PATH)]


def json_compatible_raw_fields(row: Mapping[str, object]) -> dict[str, object]:
    raw_fields: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            raw_fields[key] = str(value)
        else:
            raw_fields[key] = value
    return raw_fields


def source_record_id_for_row(
    conn: psycopg.Connection,
    data_source_id: UUID,
    row: Mapping[str, object],
) -> UUID:
    source_record_key = compute_record_hash(json_compatible_raw_fields(row))
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, source_record_key),
        )
        source_record = cursor.fetchone()

    assert source_record is not None
    return source_record["id"]


def entity_source_count(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entity_type: str,
    extraction_role: str,
) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = %s
              AND extraction_role = %s
            """,
            (source_record_id, entity_type, extraction_role),
        )
        row = cursor.fetchone()

    return row["count"]


def distinct_person_count_for_source_record_keys(
    conn: psycopg.Connection,
    transaction_type: str,
    source_record_keys: list[str],
    extraction_role: str,
) -> int:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    assert data_source_block is not None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(DISTINCT es.entity_id) AS count
            FROM core.entity_source es
            JOIN core.source_record sr
              ON sr.id = es.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE ds.domain = %s
              AND ds.jurisdiction = %s
              AND ds.name = %s
              AND es.entity_type = 'person'
              AND es.extraction_role = %s
              AND sr.source_record_key = ANY(%s)
            """,
            (
                "campaign_finance",
                "state/GA",
                data_source_block.name,
                extraction_role,
                source_record_keys,
            ),
        )
        row = cursor.fetchone()

    return row["count"]


def source_record_count_for_key(
    conn: psycopg.Connection,
    transaction_type: str,
    source_record_key: str,
) -> int:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    assert data_source_block is not None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record sr
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE ds.domain = %s
              AND ds.jurisdiction = %s
              AND ds.name = %s
              AND sr.source_record_key = %s
            """,
            ("campaign_finance", "state/GA", data_source_block.name, source_record_key),
        )
        row = cursor.fetchone()

    return row["count"]


def cleanup_source_record_by_key(transaction_type: str, source_record_key: str) -> None:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    assert data_source_block is not None

    cleanup_conn = get_connection()

    try:
        with cleanup_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT sr.id
                FROM core.source_record sr
                JOIN core.data_source ds
                  ON ds.id = sr.data_source_id
                WHERE ds.domain = %s
                  AND ds.jurisdiction = %s
                  AND ds.name = %s
                  AND sr.source_record_key = %s
                """,
                ("campaign_finance", "state/GA", data_source_block.name, source_record_key),
            )
            source_records = cursor.fetchall()

            if not source_records:
                cleanup_conn.rollback()
                return

            source_record_ids = [row["id"] for row in source_records]

            for source_record_id in source_record_ids:
                cursor.execute("DELETE FROM core.entity_address WHERE source_record_id = %s", (source_record_id,))
                cursor.execute("DELETE FROM core.entity_source WHERE source_record_id = %s", (source_record_id,))
                cursor.execute("DELETE FROM core.source_record WHERE id = %s", (source_record_id,))

        cleanup_conn.commit()
    except Exception:
        cleanup_conn.rollback()
        raise
    finally:
        cleanup_conn.close()


def build_unique_batch_row(base_row: Mapping[str, object], *, prefix: str) -> dict[str, object]:
    unique_suffix = uuid4().hex[:8]
    street_number = str(int(unique_suffix, 16) % 90_000 + 10_000)
    row = dict(base_row)
    row["FilerID"] = f"{prefix}-filer-{unique_suffix}"
    row["Committee_Name"] = f"Review Committee {unique_suffix}"
    row["FirstName"] = "Casey"
    row["LastName"] = f"Reviewer{unique_suffix}"
    row["Address"] = f"{street_number} Review Ave"
    row["City"] = "Atlanta"
    row["State"] = "GA"
    row["Zip"] = "30301"
    return row


def candidate_person_count_for_source_record_key(
    conn: psycopg.Connection,
    transaction_type: str,
    source_record_key: str,
) -> int:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    assert data_source_block is not None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.person p
            JOIN core.entity_source es
              ON es.entity_type = 'person'
             AND es.entity_id = p.id
             AND es.extraction_role = 'candidate'
            JOIN core.source_record sr
              ON sr.id = es.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE ds.domain = %s
              AND ds.jurisdiction = %s
              AND ds.name = %s
              AND sr.source_record_key = %s
            """,
            ("campaign_finance", "state/GA", data_source_block.name, source_record_key),
        )
        row = cursor.fetchone()

    return row["count"]


def ga_data_source_count(conn: psycopg.Connection, transaction_type: str) -> int:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    assert data_source_block is not None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            """,
            ("campaign_finance", "state/GA", data_source_block.name),
        )
        row = cursor.fetchone()

    return row["count"]
