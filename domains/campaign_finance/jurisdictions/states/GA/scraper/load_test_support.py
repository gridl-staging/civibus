"""
Stub summary for MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/GA/scraper/load_test_support.py.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping, NamedTuple
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from core.db import get_connection
from core.types.python.models import compute_record_hash
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions.states.GA.scraper import (
    CONTRIBUTION_COLUMNS,
    _find_ga_data_source_block_by_transaction_type,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.relational_utils import (
    ga_source_record_key,
    json_compatible_raw_fields,
)

__all__ = [
    "CONTRIBUTION_FIXTURE_PATH",
    "EXPENDITURE_FIXTURE_PATH",
    "GABulkFixture",
    "build_unique_batch_row",
    "candidate_person_count_for_source_record_key",
    "cleanup_source_record_by_key",
    "distinct_person_count_for_source_record_keys",
    "entity_source_count",
    "ga_data_source_count",
    "json_compatible_raw_fields",
    "parsed_contribution_rows",
    "parsed_expenditure_rows",
    "source_record_count_for_key",
    "source_record_id_for_row",
    "write_ga_contribution_fixture",
]

REPO_ROOT = Path(__file__).resolve().parents[6]
GA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA"
CONTRIBUTION_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "contribution_export_sample.xls"
EXPENDITURE_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "expenditure_export_sample.xls"


def parsed_contribution_rows() -> list[dict[str, object]]:
    return [dict(row) for row in parse_contributions(CONTRIBUTION_FIXTURE_PATH)]


def parsed_expenditure_rows() -> list[dict[str, object]]:
    return [dict(row) for row in parse_expenditures(EXPENDITURE_FIXTURE_PATH)]


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


# ---------------------------------------------------------------------------
# Bulk contribution fixture: unique per run, independently observed, leak-proof
# ---------------------------------------------------------------------------


class GABulkFixture(NamedTuple):
    """One synthetic GA contributions CSV and the identities it writes."""

    contributions_path: Path
    run_suffix: str
    filer_id: str
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id("GA", self.filer_id)


def write_ga_contribution_fixture(tmp_path: Path, *, row_count: int = 1) -> GABulkFixture:
    """Write a contributions CSV whose every identity is unique to this run.

    All ``row_count`` rows share one per-run ``FilerID`` — and therefore one committee and
    one filing — while each row carries a distinct donor surname, so its whole-row hash,
    and therefore its ``source_record_key`` and ``transaction_identifier``, is unique.
    That is what lets a bulk fixture cross ``load._COMMIT_BATCH_ROWS`` and still be cleaned
    up by its own scoped keys, and what keeps two fixtures running concurrently under xdist
    from resolving to — and then deleting — each other's rows.

    ``source_record_keys`` is derived by re-parsing the file the loader will read, so it
    cannot drift from the keys a load actually writes.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    filer_id = f"GABATCH{run_suffix}"
    contributions_path = tmp_path / f"ga_bounded_{run_suffix}_contributions.xls"

    base_row = dict(_read_sample_contribution_csv_row())
    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["FilerID"] = filer_id
        row["Committee_Name"] = f"GA Bounded Commit Test Committee {run_suffix}"
        row["FirstName"] = "Casey"
        row["LastName"] = f"Batch Donor {run_suffix} {index}"
        row["Address"] = f"{run_suffix} Test Street"
        row["City"] = "Atlanta"
        row["State"] = "GA"
        row["Zip"] = "30301"
        rows.append(row)

    with contributions_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(CONTRIBUTION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    source_record_keys = [ga_source_record_key(row) for row in parse_contributions(contributions_path)]
    return GABulkFixture(
        contributions_path=contributions_path,
        run_suffix=run_suffix,
        filer_id=filer_id,
        source_record_keys=source_record_keys,
    )


def _read_sample_contribution_csv_row() -> dict[str, str]:
    """Read the first raw CSV row of the checked-in contribution sample."""
    with CONTRIBUTION_FIXTURE_PATH.open("r", encoding="utf-8", newline="") as csv_file:
        return next(csv.DictReader(csv_file))
