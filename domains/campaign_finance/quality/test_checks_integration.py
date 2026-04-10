"""Integration tests for quality SQL edge cases."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_source_record
from core.types.python.models import DataSource, SourceRecord, utc_now
from domains.campaign_finance.quality.checks import (
    check_amount_sanity,
    check_duplicate_records,
    check_raw_field_null_rate,
    check_source_count,
)


pytestmark = pytest.mark.integration


def _insert_quality_data_source(conn: psycopg.Connection) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/CO",
        name=f"Quality Integration {uuid4()}",
        source_url="https://example.com/quality",
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_quality_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    raw_fields: dict[str, object],
    record_hash: str | None,
) -> SourceRecord:
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=record_hash,
    )
    insert_source_record(conn, source_record)
    return source_record


def test_check_duplicate_records_ignores_null_record_hashes(db_conn: psycopg.Connection) -> None:
    data_source = _insert_quality_data_source(db_conn)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-1",
        raw_fields={"row_id": "1"},
        record_hash=None,
    )
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-2",
        raw_fields={"row_id": "2"},
        record_hash=None,
    )

    result = check_duplicate_records(db_conn, data_source.id, data_source.name)

    assert result.status == "pass"
    assert result.metric_value == 0.0
    assert result.details["duplicate_hash_groups"] == 0


def test_check_amount_sanity_counts_non_numeric_values_as_outliers(db_conn: psycopg.Connection) -> None:
    data_source = _insert_quality_data_source(db_conn)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-valid",
        raw_fields={"transaction_amt": "25.00"},
        record_hash="hash-valid",
    )
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="record-invalid",
        raw_fields={"transaction_amt": "not-a-number"},
        record_hash="hash-invalid",
    )

    result = check_amount_sanity(db_conn, data_source.id, data_source.name)

    assert result.status == "fail"
    assert result.metric_value == 1.0
    assert result.details["invalid_amount_count"] == 1
    assert result.details["records_with_field"] == 2


def test_check_source_count_with_prefix_scopes_to_matching_keys(db_conn: psycopg.Connection) -> None:
    """source_key_prefix filters count to only matching source_record_keys."""
    data_source = _insert_quality_data_source(db_conn)
    # Two schedule_e records
    for i in range(2):
        _insert_quality_source_record(
            db_conn,
            data_source_id=data_source.id,
            source_record_key=f"schedule_e:2024:C00001:F001:T{i}",
            raw_fields={"sup_opp": "S"},
            record_hash=f"hash-se-{i}",
        )
    # One non-schedule_e record in the same data source
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="contributions:2024:C00001:F001:T0",
        raw_fields={"amount": "100"},
        record_hash="hash-contrib-0",
    )

    result = check_source_count(
        db_conn,
        data_source.id,
        data_source.name,
        source_key_prefix="schedule_e:",
    )

    assert result.status == "pass"
    assert result.metric_value == 2.0


def test_check_source_count_without_prefix_counts_all(db_conn: psycopg.Connection) -> None:
    """Without prefix, all records in the data source are counted."""
    data_source = _insert_quality_data_source(db_conn)
    for i in range(3):
        _insert_quality_source_record(
            db_conn,
            data_source_id=data_source.id,
            source_record_key=f"record-{i}",
            raw_fields={"x": "y"},
            record_hash=f"hash-{i}",
        )

    result = check_source_count(db_conn, data_source.id, data_source.name)

    assert result.metric_value == 3.0


def test_check_raw_field_null_rate_detects_missing_jsonb_key(db_conn: psycopg.Connection) -> None:
    """raw_field_null_rate counts missing JSONB keys as null."""
    data_source = _insert_quality_data_source(db_conn)
    # Record WITH the field
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T0",
        raw_fields={"sup_opp": "S", "exp_amo": "1000"},
        record_hash="hash-0",
    )
    # Record WITHOUT the field (missing key)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T1",
        raw_fields={"exp_amo": "500"},
        record_hash="hash-1",
    )

    result = check_raw_field_null_rate(
        db_conn,
        data_source.id,
        data_source.name,
        "sup_opp",
        source_key_prefix="schedule_e:",
    )

    # 1 null out of 2 = 0.5, above default threshold 0.05
    assert result.status == "fail"
    assert result.metric_value == 0.5
    assert result.details["null_count"] == 1
    assert result.details["total_count"] == 2


def test_check_raw_field_null_rate_counts_empty_strings_as_null(db_conn: psycopg.Connection) -> None:
    """Empty/whitespace-only values in raw_fields are treated as null."""
    data_source = _insert_quality_data_source(db_conn)
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T0",
        raw_fields={"sup_opp": "S"},
        record_hash="hash-0",
    )
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="schedule_e:2024:C00001:F001:T1",
        raw_fields={"sup_opp": "  "},
        record_hash="hash-1",
    )

    result = check_raw_field_null_rate(
        db_conn,
        data_source.id,
        data_source.name,
        "sup_opp",
        source_key_prefix="schedule_e:",
    )

    assert result.details["null_count"] == 1
    assert result.details["total_count"] == 2


def test_check_duplicate_records_with_prefix_scopes_to_matching_keys(db_conn: psycopg.Connection) -> None:
    """source_key_prefix scopes duplicate detection to only matching records."""
    data_source = _insert_quality_data_source(db_conn)
    # Two schedule_e records with same hash (duplicate)
    for i in range(2):
        _insert_quality_source_record(
            db_conn,
            data_source_id=data_source.id,
            source_record_key=f"schedule_e:2024:C00001:F001:T{i}",
            raw_fields={"sup_opp": "S"},
            record_hash="duplicate-hash",
        )
    # Non-schedule_e record with same hash — should be excluded by prefix
    _insert_quality_source_record(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="contributions:2024:C00001:F001:T0",
        raw_fields={"amount": "100"},
        record_hash="duplicate-hash",
    )

    result = check_duplicate_records(
        db_conn,
        data_source.id,
        data_source.name,
        source_key_prefix="schedule_e:",
    )

    # Only 2 schedule_e records share the hash → 1 extra
    assert result.status == "warn"
    assert result.metric_value == 1.0
