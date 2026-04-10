"""Integration tests for Schedule E closeout against a real database."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_source_record
from core.types.python.models import DataSource, SourceRecord, utc_now
from domains.campaign_finance.quality.schedule_e_closeout import (
    run_schedule_e_closeout,
)


pytestmark = pytest.mark.integration


def _insert_fec_data_source(conn: psycopg.Connection) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=f"FEC Integration {uuid4()}",
        source_url="https://www.fec.gov/data/browse-data/?tab=bulk-data",
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_schedule_e_record(
    conn: psycopg.Connection,
    *,
    data_source: DataSource,
    cycle: int = 2024,
    committee: str = "C00001",
    filing: str = "F001",
    txn_suffix: str,
    raw_fields: dict[str, object],
    record_hash: str | None = None,
) -> SourceRecord:
    key = f"schedule_e:{cycle}:{committee}:{filing}:{txn_suffix}"
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=record_hash or f"hash-{uuid4().hex[:8]}",
    )
    insert_source_record(conn, source_record)
    return source_record


def test_closeout_passes_with_valid_records(db_conn: psycopg.Connection) -> None:
    """Full closeout produces passing evidence when data is clean."""
    ds = _insert_fec_data_source(db_conn)
    for i in range(3):
        _insert_schedule_e_record(
            db_conn,
            data_source=ds,
            txn_suffix=f"T{i}",
            raw_fields={"sup_opp": "S", "exp_amo": "1000.00", "cand_id": "H0TX01234"},
        )

    evidence = run_schedule_e_closeout(db_conn, ds.id, cycle=2024)

    assert evidence.quality_report.status == "pass"
    assert evidence.source_record_count == 3
    assert evidence.cycle == 2024
    assert evidence.surfaced_anomalies() == []


def test_closeout_fails_when_no_schedule_e_records(db_conn: psycopg.Connection) -> None:
    """Closeout fails source count check when no schedule_e: records exist."""
    ds = _insert_fec_data_source(db_conn)
    # Insert a non-schedule_e record so the data source isn't empty
    sr = SourceRecord(
        data_source_id=ds.id,
        source_record_key="contributions:2024:C00001:F001:T0",
        raw_fields={"amount": "100"},
        pull_date=utc_now(),
        record_hash="hash-contrib",
    )
    insert_source_record(db_conn, sr)

    evidence = run_schedule_e_closeout(db_conn, ds.id, cycle=2024)

    assert evidence.quality_report.status == "fail"
    anomalies = evidence.surfaced_anomalies()
    anomaly_names = [a["name"] for a in anomalies]
    assert "schedule_e_source_count" in anomaly_names


def test_closeout_detects_null_fields(db_conn: psycopg.Connection) -> None:
    """Closeout flags high null rate on critical raw_fields keys."""
    ds = _insert_fec_data_source(db_conn)
    # All records missing cand_id
    for i in range(5):
        _insert_schedule_e_record(
            db_conn,
            data_source=ds,
            txn_suffix=f"T{i}",
            raw_fields={"sup_opp": "S", "exp_amo": "500.00"},
        )

    evidence = run_schedule_e_closeout(db_conn, ds.id, cycle=2024)

    anomaly_names = [a["name"] for a in evidence.surfaced_anomalies()]
    assert "schedule_e_null_rate_cand_id" in anomaly_names


def test_closeout_evidence_serializes_to_json(db_conn: psycopg.Connection) -> None:
    """Evidence round-trips through JSON serialization."""
    import json

    ds = _insert_fec_data_source(db_conn)
    _insert_schedule_e_record(
        db_conn,
        data_source=ds,
        txn_suffix="T0",
        raw_fields={"sup_opp": "O", "exp_amo": "250.00", "cand_id": "S0CA01234"},
    )

    evidence = run_schedule_e_closeout(db_conn, ds.id, cycle=2024)
    parsed = json.loads(evidence.to_json())

    assert parsed["cycle"] == 2024
    assert parsed["source_record_count"] == 1
    assert "quality_report" in parsed
    assert parsed["jurisdiction"] == "federal/fec"
