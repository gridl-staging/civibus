from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source, load_committees
from domains.campaign_finance.ingest.committee_summary_loader import load_committee_summaries
from domains.campaign_finance.ingest.committee_summary_parser import COMMITTEE_SUMMARY_COLUMNS
from domains.campaign_finance.ingest.test_bulk_loader_integration import (
    _PRIMARY_CYCLE,
    BulkLoaderFixtureSet,
)

pytest_plugins = ("domains.campaign_finance.ingest.test_bulk_loader_integration",)
pytestmark = pytest.mark.integration

_COMMITTEE_SUMMARY_FIXTURE_PATH = Path("tests/fixtures/bulk/committee_summary_2024.csv")


@pytest.fixture
def committee_summary_data_source_id(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
) -> Iterator[UUID]:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    load_committees(
        bulk_loader_conn,
        bulk_loader_fixture_set.committee_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    try:
        yield data_source_id
    finally:
        _cleanup_committee_summary_rows(bulk_loader_conn, data_source_id, bulk_loader_fixture_set.committee_ids)


def _read_committee_summary_fixture_row() -> dict[str, str]:
    with _COMMITTEE_SUMMARY_FIXTURE_PATH.open(newline="", encoding="utf-8") as source_file:
        reader = csv.DictReader(source_file)
        row = next(reader)
    return dict(row)


def _write_committee_summary_fixture(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as target_file:
        writer = csv.DictWriter(target_file, fieldnames=COMMITTEE_SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _summary_row_for_committee(committee_fec_id: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
    row = _read_committee_summary_fixture_row()
    row["CMTE_ID"] = committee_fec_id
    row["Link_Image"] = f"https://www.fec.gov/data/committee/{committee_fec_id}/?cycle=2024"
    if overrides:
        row.update(overrides)
    return row


def _committee_summary_source_key(committee_fec_id: str) -> str:
    return f"committee_summary:{_PRIMARY_CYCLE}:{committee_fec_id}"


def _cleanup_committee_summary_rows(
    conn: psycopg.Connection,
    data_source_id: UUID,
    committee_fec_ids: list[str],
) -> None:
    conn.rollback()
    source_keys = [_committee_summary_source_key(committee_fec_id) for committee_fec_id in committee_fec_ids]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
            """,
            (data_source_id, source_keys),
        )
        source_record_ids = [row[0] for row in cursor.fetchall()]
        if source_record_ids:
            cursor.execute("DELETE FROM cf.committee_summary WHERE source_record_id = ANY(%s)", (source_record_ids,))
            cursor.execute("DELETE FROM core.source_record WHERE id = ANY(%s)", (source_record_ids,))
    conn.commit()


def _fetch_committee_summary(conn: psycopg.Connection, committee_fec_id: str) -> dict[str, object]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT summary.*, source_record.source_record_key
            FROM cf.committee_summary summary
            JOIN cf.committee committee ON committee.id = summary.committee_id
            JOIN core.source_record source_record ON source_record.id = summary.source_record_id
            WHERE committee.fec_committee_id = %s
            """,
            (committee_fec_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return dict(row)


def _fetch_source_rows(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, superseded_by, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            ORDER BY created_at, id
            """,
            (data_source_id, source_record_key),
        )
        return [dict(row) for row in cursor.fetchall()]


def test_load_committee_summaries_maps_fixture_values_to_model_and_table(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    committee_summary_data_source_id: UUID,
    tmp_path: Path,
) -> None:
    committee_fec_id = bulk_loader_fixture_set.committee_ids[0]
    fixture_path = tmp_path / "committee_summary_2024.csv"
    _write_committee_summary_fixture(fixture_path, [_summary_row_for_committee(committee_fec_id)])

    result = load_committee_summaries(
        bulk_loader_conn,
        fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=committee_summary_data_source_id,
        batch_size=1,
    )

    summary = _fetch_committee_summary(bulk_loader_conn, committee_fec_id)
    assert (result.inserted, result.skipped, result.errors) == (1, 0, 0)
    assert summary["source_record_key"] == _committee_summary_source_key(committee_fec_id)
    assert summary["cycle"] == _PRIMARY_CYCLE
    assert summary["link_image"] == f"https://www.fec.gov/data/committee/{committee_fec_id}/?cycle=2024"
    assert summary["committee_name"] == "AMERICAN FREEDOM COALITION PAC"
    assert summary["committee_type"] == "O"
    assert summary["committee_designation"] == "U"
    assert summary["committee_filing_frequency"] == "T"
    assert summary["committee_street_1"] == "1021 NORTH MARKET PLAZA"
    assert summary["committee_street_2"] == "STE 107"
    assert summary["committee_city"] == "PUEBLO WEST"
    assert summary["committee_state"] == "CO"
    assert summary["committee_zip"] == "81007"
    assert summary["treasurer_name"] == "MCCAULEY, MIKE"
    assert summary["total_contributions"] == Decimal("20000.00")
    assert summary["total_receipts"] == Decimal("20000.00")
    assert summary["total_disbursements"] == Decimal("20000.00")
    assert summary["cash_on_hand"] == Decimal("0.00")
    assert summary["coverage_start_date"] == date(2024, 4, 1)
    assert summary["coverage_end_date"] == date(2024, 11, 25)
    assert summary["independent_expenditures"] == Decimal("18500.00")
    assert summary["total_federal_receipts"] == Decimal("20000.00")


def test_load_committee_summaries_skips_unresolved_committee_without_source_record(
    bulk_loader_conn: psycopg.Connection,
    committee_summary_data_source_id: UUID,
    tmp_path: Path,
) -> None:
    missing_committee_fec_id = "C99999999"
    fixture_path = tmp_path / "committee_summary_missing.csv"
    _write_committee_summary_fixture(fixture_path, [_summary_row_for_committee(missing_committee_fec_id)])

    result = load_committee_summaries(
        bulk_loader_conn,
        fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=committee_summary_data_source_id,
        batch_size=1,
    )

    source_rows = _fetch_source_rows(
        bulk_loader_conn,
        data_source_id=committee_summary_data_source_id,
        source_record_key=_committee_summary_source_key(missing_committee_fec_id),
    )
    assert (result.inserted, result.skipped, result.errors) == (0, 1, 0)
    assert source_rows == []


def test_load_committee_summaries_is_idempotent_and_supersedes_changed_rows(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    committee_summary_data_source_id: UUID,
    tmp_path: Path,
) -> None:
    committee_fec_id = bulk_loader_fixture_set.committee_ids[0]
    source_key = _committee_summary_source_key(committee_fec_id)
    original_path = tmp_path / "committee_summary_original.csv"
    changed_path = tmp_path / "committee_summary_changed.csv"
    original_row = _summary_row_for_committee(committee_fec_id)
    changed_row = _summary_row_for_committee(
        committee_fec_id,
        {
            "TTL_CONTB": "21000",
            "TTL_RECEIPTS": "22000",
            "TTL_DISB": "23000",
            "COH_COP": "24000",
        },
    )
    _write_committee_summary_fixture(original_path, [original_row])
    _write_committee_summary_fixture(changed_path, [changed_row])

    first_result = load_committee_summaries(
        bulk_loader_conn,
        original_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=committee_summary_data_source_id,
        batch_size=1,
    )
    second_result = load_committee_summaries(
        bulk_loader_conn,
        original_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=committee_summary_data_source_id,
        batch_size=1,
    )
    changed_result = load_committee_summaries(
        bulk_loader_conn,
        changed_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=committee_summary_data_source_id,
        batch_size=1,
    )

    source_rows = _fetch_source_rows(
        bulk_loader_conn,
        data_source_id=committee_summary_data_source_id,
        source_record_key=source_key,
    )
    active_source_rows = [row for row in source_rows if row["superseded_by"] is None]
    summary = _fetch_committee_summary(bulk_loader_conn, committee_fec_id)
    with bulk_loader_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM cf.committee_summary summary
            JOIN cf.committee committee ON committee.id = summary.committee_id
            WHERE committee.fec_committee_id = %s
              AND summary.cycle = %s
            """,
            (committee_fec_id, _PRIMARY_CYCLE),
        )
        summary_count = cursor.fetchone()[0]

    assert (first_result.inserted, first_result.skipped, first_result.errors) == (1, 0, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 1, 0)
    assert (changed_result.inserted, changed_result.skipped, changed_result.errors) == (1, 0, 0)
    assert len(source_rows) == 2
    assert len(active_source_rows) == 1
    assert any(row["superseded_by"] == active_source_rows[0]["id"] for row in source_rows)
    assert summary_count == 1
    assert summary["source_record_id"] == active_source_rows[0]["id"]
    assert summary["total_contributions"] == Decimal("21000.00")
    assert summary["total_receipts"] == Decimal("22000.00")
    assert summary["total_disbursements"] == Decimal("23000.00")
    assert summary["cash_on_hand"] == Decimal("24000.00")
