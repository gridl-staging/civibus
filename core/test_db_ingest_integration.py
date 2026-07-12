from __future__ import annotations

from datetime import date
from threading import Event, Thread
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.range import DateRange

from core import db_ingest
from core.db import (
    find_organization_by_identifier,
    find_person_by_identifier,
    find_person_by_name_and_zip,
    get_connection,
    insert_address,
    insert_data_source,
    insert_entity_address,
    insert_entity_source,
    insert_organization,
    insert_person,
    insert_source_record,
    try_insert_data_source,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)


pytestmark = pytest.mark.integration


def _insert_test_data_source(conn: psycopg.Connection) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=f"Stage 5 Review {uuid4()}",
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_test_source_record(
    conn: psycopg.Connection,
    data_source_id: UUID,
    source_record_key: str,
) -> SourceRecord:
    raw_fields = {"sub_id": source_record_key}
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(conn, source_record)
    return source_record


def _source_record_for_fields(
    data_source_id: UUID,
    source_record_key: str,
    raw_fields: dict[str, object],
) -> SourceRecord:
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )


def _select_count(conn: psycopg.Connection, query: str, params: tuple[object, ...]) -> int:
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()[0]


def _insert_person_address_link_dependencies(
    conn: psycopg.Connection,
    source_record_key: str,
) -> tuple[Person, Address, SourceRecord]:
    data_source = _insert_test_data_source(conn)
    source_record = _insert_test_source_record(conn, data_source.id, source_record_key)
    address = Address(raw_address=f"{uuid4()} LINK ST, DURHAM, NC 27701", city="DURHAM", state="NC", zip5="27701")
    person = Person(canonical_name="Alice Jones", first_name="ALICE", last_name="JONES")
    insert_address(conn, address)
    insert_person(conn, person)
    return person, address, source_record


def test_upsert_address_returns_existing_id_for_duplicate_raw_address(db_conn: psycopg.Connection) -> None:
    address = Address(raw_address="123 MAIN ST, DURHAM, NC 27701", city="DURHAM", state="NC", zip5="27701")

    first_id = upsert_address(db_conn, address)
    duplicate_id = upsert_address(
        db_conn,
        Address(raw_address=address.raw_address, city="DURHAM", state="NC", zip5="27701"),
    )

    assert duplicate_id == first_id
    assert (
        _select_count(db_conn, "SELECT COUNT(*) FROM core.address WHERE raw_address = %s", (address.raw_address,)) == 1
    )


def test_try_insert_source_record_supersedes_when_active_key_exists(db_conn: psycopg.Connection) -> None:
    """Re-ingest with same key and different hash triggers supersession, not silent drop."""
    data_source = _insert_test_data_source(db_conn)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="sub-1",
        raw_fields={"sub_id": "sub-1"},
        pull_date=utc_now(),
        record_hash=compute_record_hash({"sub_id": "sub-1"}),
    )
    amended_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="sub-1",
        raw_fields={"sub_id": "sub-1", "amended": True},
        pull_date=utc_now(),
        record_hash=compute_record_hash({"sub_id": "sub-1", "amended": True}),
    )

    inserted_id = try_insert_source_record(db_conn, source_record)
    amended_id = try_insert_source_record(db_conn, amended_record)

    assert inserted_id == source_record.id
    # Amendment with different hash → supersession, returns new UUID
    assert amended_id == amended_record.id
    assert amended_id != inserted_id
    # Both records exist: original is superseded, amendment is active
    assert (
        _select_count(
            db_conn,
            "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source.id, "sub-1"),
        )
        == 2
    )


def test_amendment_with_different_hash_supersedes_old_record(db_conn: psycopg.Connection) -> None:
    """Amendment with different record_hash supersedes old record and returns new UUID."""
    data_source = _insert_test_data_source(db_conn)
    original_fields = {"sub_id": "txn-100", "amount": "500"}
    amended_fields = {"sub_id": "txn-100", "amount": "750", "amended": True}

    original = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-100",
        raw_fields=original_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(original_fields),
    )
    amended = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-100",
        raw_fields=amended_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(amended_fields),
    )

    original_id = try_insert_source_record(db_conn, original)
    amended_id = try_insert_source_record(db_conn, amended)

    assert original_id == original.id
    # Amendment must return a new UUID (not None)
    assert amended_id == amended.id
    assert amended_id != original_id

    # Old record should be superseded by the new one
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT superseded_by FROM core.source_record WHERE id = %s",
            (original_id,),
        )
        old_superseded_by = cur.fetchone()[0]
        assert old_superseded_by == amended_id

        # New record should be active (superseded_by IS NULL)
        cur.execute(
            "SELECT superseded_by FROM core.source_record WHERE id = %s",
            (amended_id,),
        )
        new_superseded_by = cur.fetchone()[0]
        assert new_superseded_by is None

    # Two records total for this key
    assert (
        _select_count(
            db_conn,
            "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source.id, "txn-100"),
        )
        == 2
    )


def test_identical_reingest_with_same_hash_returns_none(db_conn: psycopg.Connection) -> None:
    """Identical re-ingest with same record_hash returns None and does not insert a duplicate."""
    data_source = _insert_test_data_source(db_conn)
    raw_fields = {"sub_id": "txn-200", "amount": "100"}
    record_hash = compute_record_hash(raw_fields)

    original = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-200",
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=record_hash,
    )
    duplicate = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-200",
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=record_hash,
    )

    original_id = try_insert_source_record(db_conn, original)
    duplicate_id = try_insert_source_record(db_conn, duplicate)

    assert original_id == original.id
    # Identical hash → skip, return None
    assert duplicate_id is None

    # Only one record should exist
    assert (
        _select_count(
            db_conn,
            "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source.id, "txn-200"),
        )
        == 1
    )


def test_concurrent_reingest_returns_none_instead_of_unique_violation() -> None:
    """Concurrent identical re-ingest must serialize and return None, not raise."""
    setup_conn = get_connection()
    first_conn = get_connection()
    cleanup_conn = get_connection()
    data_source: DataSource | None = None
    worker_done = Event()
    worker_started = Event()
    worker_result: dict[str, object] = {}

    try:
        data_source = DataSource(
            domain="campaign_finance",
            jurisdiction="federal/fec",
            name=f"Stage 5 Review Concurrent {uuid4()}",
            source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
        )
        insert_data_source(setup_conn, data_source)
        setup_conn.commit()

        raw_fields = {"sub_id": f"txn-concurrent-{uuid4()}", "amount": "100"}
        record_hash = compute_record_hash(raw_fields)
        original = SourceRecord(
            data_source_id=data_source.id,
            source_record_key=raw_fields["sub_id"],
            raw_fields=raw_fields,
            pull_date=utc_now(),
            record_hash=record_hash,
        )
        duplicate = SourceRecord(
            data_source_id=data_source.id,
            source_record_key=raw_fields["sub_id"],
            raw_fields=raw_fields,
            pull_date=utc_now(),
            record_hash=record_hash,
        )

        first_conn.execute("BEGIN")
        inserted_id = try_insert_source_record(first_conn, original)
        assert inserted_id == original.id

        def _insert_duplicate() -> None:
            worker_conn = get_connection()
            try:
                worker_conn.execute("BEGIN")
                worker_started.set()
                worker_result["id"] = try_insert_source_record(worker_conn, duplicate)
            except Exception as exc:  # pragma: no cover - exercised on regression only
                worker_result["error"] = exc
            finally:
                try:
                    worker_conn.rollback()
                finally:
                    worker_conn.close()
                    worker_done.set()

        thread = Thread(target=_insert_duplicate, daemon=True)
        thread.start()

        assert worker_started.wait(timeout=1)
        assert not worker_done.wait(timeout=0.2)

        first_conn.commit()
        thread.join(timeout=2)

        assert worker_done.is_set()
        assert "error" not in worker_result
        assert worker_result["id"] is None
        assert (
            cleanup_conn.execute(
                "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
                (data_source.id, raw_fields["sub_id"]),
            ).fetchone()[0]
            == 1
        )
    finally:
        first_conn.rollback()
        if data_source is not None:
            cleanup_conn.execute("DELETE FROM core.source_record WHERE data_source_id = %s", (data_source.id,))
            cleanup_conn.execute("DELETE FROM core.data_source WHERE id = %s", (data_source.id,))
            cleanup_conn.commit()
        cleanup_conn.close()
        first_conn.close()
        setup_conn.close()


def test_null_key_always_inserts_without_conflict(db_conn: psycopg.Connection) -> None:
    """source_record_key IS NULL always inserts without conflict logic."""
    data_source = _insert_test_data_source(db_conn)
    fields_a = {"blob": "aaa"}
    fields_b = {"blob": "bbb"}

    record_a = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=None,
        raw_fields=fields_a,
        pull_date=utc_now(),
        record_hash=compute_record_hash(fields_a),
    )
    record_b = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=None,
        raw_fields=fields_b,
        pull_date=utc_now(),
        record_hash=compute_record_hash(fields_b),
    )

    id_a = try_insert_source_record(db_conn, record_a)
    id_b = try_insert_source_record(db_conn, record_b)

    # Both should insert successfully and return UUIDs
    assert id_a == record_a.id
    assert id_b == record_b.id
    assert id_a != id_b

    # Both records exist
    assert (
        _select_count(
            db_conn,
            "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND source_record_key IS NULL",
            (data_source.id,),
        )
        == 2
    )


def test_try_insert_source_records_bulk_preserves_order_and_supersession(
    db_conn: psycopg.Connection,
) -> None:
    data_source = _insert_test_data_source(db_conn)
    duplicate_fields = {"sub_id": "txn-bulk-duplicate", "amount": "100"}
    amended_original_fields = {"sub_id": "txn-bulk-amended", "amount": "250"}
    amended_new_fields = {"sub_id": "txn-bulk-amended", "amount": "300", "amended": True}
    fresh_fields = {"sub_id": "txn-bulk-fresh", "amount": "500"}
    duplicate_original = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-bulk-duplicate",
        raw_fields=duplicate_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(duplicate_fields),
    )
    amended_original = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-bulk-amended",
        raw_fields=amended_original_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(amended_original_fields),
    )
    duplicate_reingest = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-bulk-duplicate",
        raw_fields=duplicate_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(duplicate_fields),
    )
    amended_reingest = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-bulk-amended",
        raw_fields=amended_new_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(amended_new_fields),
    )
    fresh_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-bulk-fresh",
        raw_fields=fresh_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(fresh_fields),
    )

    assert try_insert_source_record(db_conn, duplicate_original) == duplicate_original.id
    assert try_insert_source_record(db_conn, amended_original) == amended_original.id

    results = db_ingest.try_insert_source_records_bulk(
        db_conn,
        [fresh_record, duplicate_reingest, amended_reingest],
    )

    assert [(result.source_record_id, result.inserted) for result in results] == [
        (fresh_record.id, True),
        (None, False),
        (amended_reingest.id, True),
    ]
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, raw_fields, superseded_by
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key IN (%s, %s, %s)
            ORDER BY source_record_key, created_at, id
            """,
            (
                data_source.id,
                "txn-bulk-amended",
                "txn-bulk-duplicate",
                "txn-bulk-fresh",
            ),
        )
        rows = cursor.fetchall()

    rows_by_key: dict[str, list[tuple[UUID, dict[str, object], UUID | None]]] = {}
    for row_id, source_record_key, raw_fields, superseded_by in rows:
        rows_by_key.setdefault(source_record_key, []).append((row_id, raw_fields, superseded_by))

    assert rows_by_key["txn-bulk-duplicate"] == [
        (duplicate_original.id, duplicate_fields, None),
    ]
    assert rows_by_key["txn-bulk-fresh"] == [
        (fresh_record.id, fresh_fields, None),
    ]
    assert rows_by_key["txn-bulk-amended"] == [
        (amended_original.id, amended_original_fields, amended_reingest.id),
        (amended_reingest.id, amended_new_fields, None),
    ]


def test_try_insert_source_records_bulk_attributes_mixed_batch_lanes(
    db_conn: psycopg.Connection,
) -> None:
    data_source = _insert_test_data_source(db_conn)
    duplicate_key = f"txn-bulk-duplicate-{uuid4()}"
    same_hash_key = f"txn-bulk-same-hash-{uuid4()}"
    amended_key = f"txn-bulk-amended-{uuid4()}"
    fresh_fields = {"sub_id": f"txn-bulk-fresh-{uuid4()}", "amount": "500"}
    duplicate_original_fields = {"sub_id": duplicate_key, "amount": "100"}
    duplicate_amended_fields = {**duplicate_original_fields, "amount": "125", "amended": True}
    null_key_fields = {"sub_id": None, "amount": "50"}
    same_hash_fields = {"sub_id": same_hash_key, "amount": "250"}
    amended_original_fields = {"sub_id": amended_key, "amount": "300"}
    amended_new_fields = {**amended_original_fields, "amount": "350", "amended": True}

    duplicate_first = _source_record_for_fields(data_source.id, duplicate_key, duplicate_original_fields)
    duplicate_second = _source_record_for_fields(data_source.id, duplicate_key, duplicate_amended_fields)
    null_key_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=None,
        raw_fields=null_key_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(null_key_fields),
    )
    fresh_record = _source_record_for_fields(data_source.id, str(fresh_fields["sub_id"]), fresh_fields)
    same_hash_original = _source_record_for_fields(data_source.id, same_hash_key, same_hash_fields)
    same_hash_reingest = _source_record_for_fields(data_source.id, same_hash_key, same_hash_fields)
    amended_original = _source_record_for_fields(data_source.id, amended_key, amended_original_fields)
    amended_reingest = _source_record_for_fields(data_source.id, amended_key, amended_new_fields)

    assert try_insert_source_record(db_conn, same_hash_original) == same_hash_original.id
    assert try_insert_source_record(db_conn, amended_original) == amended_original.id

    results = db_ingest.try_insert_source_records_bulk(
        db_conn,
        [
            fresh_record,
            duplicate_first,
            null_key_record,
            same_hash_reingest,
            duplicate_second,
            amended_reingest,
        ],
    )

    assert [(result.source_record_id, result.inserted) for result in results] == [
        (fresh_record.id, True),
        (duplicate_first.id, True),
        (null_key_record.id, True),
        (None, False),
        (duplicate_second.id, True),
        (amended_reingest.id, True),
    ]
    attribution_counts = db_ingest.summarize_source_record_bulk_insert_attribution(results)
    assert attribution_counts == db_ingest.SourceRecordBulkInsertAttributionCounts(
        fast_path_candidates=3,
        forced_per_row_rows=3,
        fast_path_inserted=1,
        fast_path_fallbacks=2,
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, raw_fields, superseded_by
            FROM core.source_record
            WHERE data_source_id = %s
              AND (
                  source_record_key IS NULL
                  OR source_record_key IN (%s, %s, %s, %s)
              )
            ORDER BY source_record_key NULLS FIRST, created_at, id
            """,
            (
                data_source.id,
                duplicate_key,
                same_hash_key,
                amended_key,
                fresh_fields["sub_id"],
            ),
        )
        rows = cursor.fetchall()

    rows_by_key: dict[str | None, list[tuple[UUID, dict[str, object], UUID | None]]] = {}
    for row_id, source_record_key, raw_fields, superseded_by in rows:
        rows_by_key.setdefault(source_record_key, []).append((row_id, raw_fields, superseded_by))

    assert rows_by_key[None] == [(null_key_record.id, null_key_fields, None)]
    assert rows_by_key[fresh_fields["sub_id"]] == [(fresh_record.id, fresh_fields, None)]
    assert rows_by_key[same_hash_key] == [(same_hash_original.id, same_hash_fields, None)]
    assert rows_by_key[duplicate_key] == [
        (duplicate_first.id, duplicate_original_fields, duplicate_second.id),
        (duplicate_second.id, duplicate_amended_fields, None),
    ]
    assert rows_by_key[amended_key] == [
        (amended_original.id, amended_original_fields, amended_reingest.id),
        (amended_reingest.id, amended_new_fields, None),
    ]


def test_try_insert_source_records_bulk_skips_same_hash_reingest_that_reuses_active_id(
    db_conn: psycopg.Connection,
) -> None:
    """A caller-supplied id matching the active row must not be read as proof of insertion."""
    data_source = _insert_test_data_source(db_conn)
    fields = {"sub_id": "txn-bulk-same-id", "amount": "100"}
    original = SourceRecord(
        data_source_id=data_source.id,
        source_record_key="txn-bulk-same-id",
        raw_fields=fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(fields),
    )
    assert try_insert_source_record(db_conn, original) == original.id

    reingest_reusing_active_id = SourceRecord(
        id=original.id,
        data_source_id=data_source.id,
        source_record_key="txn-bulk-same-id",
        raw_fields=fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(fields),
    )

    results = db_ingest.try_insert_source_records_bulk(db_conn, [reingest_reusing_active_id])

    assert [(result.source_record_id, result.inserted) for result in results] == [(None, False)]
    assert (
        _select_count(
            db_conn,
            "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source.id, "txn-bulk-same-id"),
        )
        == 1
    )


def test_try_insert_source_records_bulk_serializes_existing_key_before_same_hash_skip() -> None:
    setup_conn = get_connection()
    amendment_conn = get_connection()
    cleanup_conn = get_connection()
    data_source: DataSource | None = None
    worker_done = Event()
    worker_started = Event()
    worker_result: dict[str, object] = {}

    try:
        data_source = DataSource(
            domain="campaign_finance",
            jurisdiction="federal/fec",
            name=f"Stage 2 Bulk Race {uuid4()}",
            source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
        )
        insert_data_source(setup_conn, data_source)

        original_fields = {"sub_id": f"txn-bulk-race-{uuid4()}", "amount": "100"}
        amended_fields = {**original_fields, "amount": "125", "amended": True}
        original = _source_record_for_fields(data_source.id, original_fields["sub_id"], original_fields)
        amendment = _source_record_for_fields(data_source.id, original_fields["sub_id"], amended_fields)
        same_hash_reingest = _source_record_for_fields(data_source.id, original_fields["sub_id"], original_fields)

        assert try_insert_source_record(setup_conn, original) == original.id
        setup_conn.commit()

        amendment_conn.execute("BEGIN")
        assert try_insert_source_record(amendment_conn, amendment) == amendment.id

        def _bulk_insert_same_hash_reingest() -> None:
            worker_conn = get_connection()
            try:
                worker_conn.execute("BEGIN")
                worker_started.set()
                results = db_ingest.try_insert_source_records_bulk(worker_conn, [same_hash_reingest])
                worker_conn.commit()
                worker_result["results"] = results
            except Exception as exc:  # pragma: no cover - exercised on regression only
                worker_conn.rollback()
                worker_result["error"] = exc
            finally:
                worker_conn.close()
                worker_done.set()

        thread = Thread(target=_bulk_insert_same_hash_reingest, daemon=True)
        thread.start()

        assert worker_started.wait(timeout=1)
        assert not worker_done.wait(timeout=0.2)

        amendment_conn.commit()
        thread.join(timeout=2)

        assert worker_done.is_set()
        assert "error" not in worker_result
        results = worker_result["results"]
        assert [(result.source_record_id, result.inserted) for result in results] == [
            (same_hash_reingest.id, True),
        ]

        with cleanup_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, raw_fields, superseded_by
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key = %s
                """,
                (data_source.id, original_fields["sub_id"]),
            )
            rows = {row_id: (raw_fields, superseded_by) for row_id, raw_fields, superseded_by in cursor}

        assert rows == {
            original.id: (original_fields, amendment.id),
            amendment.id: (amended_fields, same_hash_reingest.id),
            same_hash_reingest.id: (original_fields, None),
        }
    finally:
        setup_conn.rollback()
        amendment_conn.rollback()
        if data_source is not None:
            cleanup_conn.execute("DELETE FROM core.source_record WHERE data_source_id = %s", (data_source.id,))
            cleanup_conn.execute("DELETE FROM core.data_source WHERE id = %s", (data_source.id,))
            cleanup_conn.commit()
        cleanup_conn.close()
        amendment_conn.close()
        setup_conn.close()


def test_try_insert_data_source_returns_none_when_name_exists(db_conn: psycopg.Connection) -> None:
    source_name = f"FEC Schedule A API {uuid4()}"
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=source_name,
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )
    duplicate_data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=source_name,
        source_url="https://api.open.fec.gov/v1/schedules/schedule_a/",
    )

    inserted_id = try_insert_data_source(db_conn, data_source)
    duplicate_id = try_insert_data_source(db_conn, duplicate_data_source)

    assert inserted_id == data_source.id
    assert duplicate_id is None
    assert (
        _select_count(
            db_conn,
            """
            SELECT COUNT(*)
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            """,
            ("campaign_finance", "federal/fec", source_name),
        )
        == 1
    )


def test_find_organization_by_identifier_returns_matching_row(db_conn: psycopg.Connection) -> None:
    organization = Organization(canonical_name="TEST PAC", identifiers={"fec_committee_id": "C00123456"})
    insert_organization(db_conn, organization)

    assert find_organization_by_identifier(db_conn, "fec_committee_id", "C00123456") == organization.id
    assert find_organization_by_identifier(db_conn, "fec_committee_id", "C00999999") is None


def test_find_person_by_identifier_returns_matching_row(db_conn: psycopg.Connection) -> None:
    person = Person(
        canonical_name="ALICE JONES",
        first_name="ALICE",
        last_name="JONES",
        identifiers={"fec_candidate_id": "H0NC01001"},
    )
    insert_person(db_conn, person)

    assert find_person_by_identifier(db_conn, "fec_candidate_id", "H0NC01001") == person.id
    assert find_person_by_identifier(db_conn, "fec_candidate_id", "H0NC99999") is None


def test_insert_entity_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    data_source = _insert_test_data_source(db_conn)
    source_record = _insert_test_source_record(db_conn, data_source.id, "source-link")
    person = Person(canonical_name="Alice Jones", first_name="ALICE", last_name="JONES")
    insert_person(db_conn, person)

    first_link_id = insert_entity_source(db_conn, "person", person.id, source_record.id, "donor")
    duplicate_link_id = insert_entity_source(db_conn, "person", person.id, source_record.id, "donor")

    assert duplicate_link_id == first_link_id
    assert (
        _select_count(
            db_conn,
            """
        SELECT COUNT(*)
        FROM core.entity_source
        WHERE entity_type = %s
          AND entity_id = %s
          AND source_record_id = %s
          AND extraction_role = %s
        """,
            ("person", person.id, source_record.id, "donor"),
        )
        == 1
    )


def test_insert_entity_address_is_idempotent_and_person_lookup_uses_zip(
    db_conn: psycopg.Connection,
) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(db_conn, "address-link")

    first_link_id = insert_entity_address(db_conn, "person", person.id, address.id, source_record.id, "mailing")
    duplicate_link_id = insert_entity_address(db_conn, "person", person.id, address.id, source_record.id, "mailing")
    stored_period, stored_precision = db_conn.execute(
        "SELECT valid_period, date_precision FROM core.entity_address WHERE id = %s",
        (first_link_id,),
    ).fetchone()

    assert duplicate_link_id == first_link_id
    assert stored_period == DateRange(None, None)
    assert stored_precision == "day"
    assert find_person_by_name_and_zip(db_conn, "JONES", "ALICE", "27701") == person.id
    assert (
        _select_count(
            db_conn,
            """
        SELECT COUNT(*)
        FROM core.entity_address
        WHERE entity_type = %s
          AND entity_id = %s
          AND address_id = %s
          AND address_role = %s
        """,
            ("person", person.id, address.id, "mailing"),
        )
        == 1
    )


def test_insert_entity_address_with_explicit_valid_period(db_conn: psycopg.Connection) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(db_conn, "address-link-period")
    valid_period = DateRange(date(2020, 1, 1), None)

    inserted_id = insert_entity_address(
        db_conn,
        "person",
        person.id,
        address.id,
        source_record.id,
        "mailing",
        valid_period=valid_period,
    )

    stored_period = db_conn.execute(
        "SELECT valid_period FROM core.entity_address WHERE id = %s",
        (inserted_id,),
    ).fetchone()[0]

    assert stored_period == valid_period


def test_insert_entity_address_with_explicit_date_precision(db_conn: psycopg.Connection) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(db_conn, "address-link-precision")

    inserted_id = insert_entity_address(
        db_conn,
        "person",
        person.id,
        address.id,
        source_record.id,
        "mailing",
        date_precision="month",
    )

    stored_precision = db_conn.execute(
        "SELECT date_precision FROM core.entity_address WHERE id = %s",
        (inserted_id,),
    ).fetchone()[0]

    assert stored_precision == "month"


def test_insert_entity_address_rejects_same_period_with_different_date_precision(
    db_conn: psycopg.Connection,
) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(
        db_conn, "address-link-precision-conflict"
    )
    valid_period = DateRange(date(2020, 1, 1), None)

    insert_entity_address(
        db_conn,
        "person",
        person.id,
        address.id,
        source_record.id,
        "mailing",
        valid_period=valid_period,
        date_precision="day",
    )

    with pytest.raises((psycopg.errors.ExclusionViolation, psycopg.errors.UniqueViolation)):
        insert_entity_address(
            db_conn,
            "person",
            person.id,
            address.id,
            source_record.id,
            "mailing",
            valid_period=valid_period,
            date_precision="month",
        )


def test_insert_entity_address_rejects_overlapping_via_constraint(db_conn: psycopg.Connection) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(db_conn, "address-link-overlap")

    insert_entity_address(
        db_conn,
        "person",
        person.id,
        address.id,
        source_record.id,
        "mailing",
        valid_period=DateRange(date(2020, 1, 1), date(2021, 1, 1)),
    )

    with pytest.raises((psycopg.errors.ExclusionViolation, psycopg.errors.UniqueViolation)):
        insert_entity_address(
            db_conn,
            "person",
            person.id,
            address.id,
            source_record.id,
            "mailing",
            valid_period=DateRange(date(2020, 6, 1), None),
        )


def test_insert_entity_address_idempotent_with_same_valid_period(db_conn: psycopg.Connection) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(db_conn, "address-link-idempotent")
    valid_period = DateRange(date(2020, 1, 1), None)

    first_id = insert_entity_address(
        db_conn,
        "person",
        person.id,
        address.id,
        source_record.id,
        "mailing",
        valid_period=valid_period,
    )
    duplicate_id = insert_entity_address(
        db_conn,
        "person",
        person.id,
        address.id,
        source_record.id,
        "mailing",
        valid_period=valid_period,
    )

    assert duplicate_id == first_id


def test_insert_entity_address_recovers_id_after_insert_conflict(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person, address, source_record = _insert_person_address_link_dependencies(db_conn, "address-link-race")
    expected_id = insert_entity_address(db_conn, "person", person.id, address.id, source_record.id, "mailing")

    original_select_existing_id = db_ingest._select_existing_id
    select_calls = {"count": 0}

    def _select_existing_id_with_stale_first_read(
        cursor: psycopg.Cursor,
        query: str,
        params: tuple[object, ...],
    ) -> UUID | None:
        select_calls["count"] += 1
        if select_calls["count"] == 1 and "FROM core.entity_address" in query:
            return None
        return original_select_existing_id(cursor, query, params)

    monkeypatch.setattr(db_ingest, "_select_existing_id", _select_existing_id_with_stale_first_read)

    recovered_id = insert_entity_address(db_conn, "person", person.id, address.id, source_record.id, "mailing")

    assert recovered_id == expected_id
    assert select_calls["count"] >= 2


def test_find_person_by_name_and_zip_matches_name_only_when_zip_missing(db_conn: psycopg.Connection) -> None:
    person = Person(canonical_name="Bob Smith", first_name="BOB", last_name="SMITH")
    insert_person(db_conn, person)

    assert find_person_by_name_and_zip(db_conn, "SMITH", "BOB", None) == person.id
