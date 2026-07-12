from __future__ import annotations

import cProfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import pstats
import statistics
import time
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from domains.campaign_finance.ingest import bulk_stage4_loader
from domains.campaign_finance.ingest.bulk_loader import (
    Stage4LoadOptions,
    ensure_fec_bulk_data_source,
    load_contributions,
)
from domains.campaign_finance.ingest.bulk_parser import ITCONT_COLUMNS
from domains.campaign_finance.ingest.test_bulk_loader_integration import (
    _cleanup_bulk_loader_rows,
    _materialize_bulk_loader_fixture_set,
    _select_bulk_data_source_id,
    _write_fixture_file,
    BulkLoaderFixtureSet,
)
from domains.campaign_finance.ingest.test_bulk_loader_stage4_integration import (
    _load_stage3_committees,
    _make_unique_sub_id,
    _materialize_stage4_fixture_set,
    _write_stage4_fixture_zip,
    Stage4FixtureSet,
)

pytestmark = pytest.mark.integration

_MINIMUM_INPUT_ROWS = 200_000
_BATCH_SIZE = 1_000
_WINDOW_INSERTED_ROWS = 50_000
_TIMED_WINDOW_COUNT = 3
_MINIMUM_MEDIAN_INSERTED_PER_SECOND = 3_000
_MINIMUM_SLOWEST_INSERTED_PER_SECOND = 2_400
_MAXIMUM_WINDOW_SPREAD_RATIO = 0.20


@dataclass(frozen=True, slots=True)
class _CommitSnapshot:
    timestamp: float
    inserted: int
    skipped: int
    errors: int
    processed_rows: int


@dataclass(frozen=True, slots=True)
class _MeasurementWindow:
    name: str
    start: _CommitSnapshot
    end: _CommitSnapshot

    @property
    def inserted_rows(self) -> int:
        return self.end.inserted - self.start.inserted

    @property
    def skipped_rows(self) -> int:
        return self.end.skipped - self.start.skipped

    @property
    def error_rows(self) -> int:
        return self.end.errors - self.start.errors

    @property
    def elapsed_seconds(self) -> float:
        return self.end.timestamp - self.start.timestamp

    @property
    def inserted_per_second(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.inserted_rows / self.elapsed_seconds


@dataclass(frozen=True, slots=True)
class _ExpandedStage4Fixture:
    zip_path: Path
    row_count: int
    source_record_key_fragment: str
    source_record_keys: list[str]


def _expand_stage4_itcont_rows(
    stage4_fixture_set: Stage4FixtureSet,
    *,
    fixture_prefix: str | None = None,
) -> list[dict[str, str | None]]:
    expanded_rows: list[dict[str, str | None]] = []
    row_index = 1
    resolved_fixture_prefix = fixture_prefix or _build_throughput_fixture_prefix()
    while len(expanded_rows) < _MINIMUM_INPUT_ROWS:
        for source_row in stage4_fixture_set.itcont_rows:
            expanded_rows.append(
                {
                    **source_row,
                    "SUB_ID": _make_unique_sub_id(source_row["SUB_ID"], resolved_fixture_prefix, row_index),
                    "TRAN_ID": _make_unique_transaction_id(source_row["TRAN_ID"], resolved_fixture_prefix, row_index),
                }
            )
            row_index += 1
            if len(expanded_rows) >= _MINIMUM_INPUT_ROWS:
                break
    return expanded_rows


def _build_throughput_fixture_prefix() -> str:
    return f"{uuid4().int % 10_000_000_000:010d}"


def _make_unique_transaction_id(base_transaction_id: str | None, fixture_prefix: str, row_index: int) -> str | None:
    if base_transaction_id is None:
        return None
    return f"{base_transaction_id}-{fixture_prefix}-{row_index:06d}"


def _write_expanded_stage4_fixture_zip(
    tmp_path: Path,
    stage4_fixture_set: Stage4FixtureSet,
) -> _ExpandedStage4Fixture:
    fixture_prefix = _build_throughput_fixture_prefix()
    expanded_rows = _expand_stage4_itcont_rows(stage4_fixture_set, fixture_prefix=fixture_prefix)
    itcont_path = tmp_path / "itcont_stage4_transactions_throughput.txt"
    _write_fixture_file(itcont_path, ITCONT_COLUMNS, expanded_rows)
    return _ExpandedStage4Fixture(
        zip_path=_write_stage4_fixture_zip(tmp_path, itcont_path),
        row_count=len(expanded_rows),
        source_record_key_fragment=fixture_prefix,
        source_record_keys=[row["SUB_ID"] for row in expanded_rows if row["SUB_ID"] is not None],
    )


def _cleanup_stage4_throughput_rows_by_source_key_fragment(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key_fragment: str,
    can_truncate_relational_tables: bool,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM cf.stage4_resume_checkpoint
            WHERE data_source_id = %s
              AND cycle = 2024
              AND file_type = 'itcont'
            """,
            (data_source_id,),
        )
        if can_truncate_relational_tables:
            cursor.execute("TRUNCATE cf.transaction, cf.filing")
        else:
            cursor.execute(
                """
                CREATE TEMP TABLE IF NOT EXISTS stage4_throughput_probe_source_records (
                    id UUID PRIMARY KEY
                ) ON COMMIT DROP
                """
            )
            cursor.execute("TRUNCATE stage4_throughput_probe_source_records")
            cursor.execute(
                """
                INSERT INTO stage4_throughput_probe_source_records (id)
                SELECT id
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key LIKE %s
                """,
                (data_source_id, f"%{source_record_key_fragment}%"),
            )
            cursor.execute(
                """
                DELETE FROM cf.transaction
                WHERE source_record_id IN (
                    SELECT id FROM stage4_throughput_probe_source_records
                )
                """
            )
            cursor.execute(
                """
                DELETE FROM cf.filing
                WHERE source_record_id IN (
                    SELECT id FROM stage4_throughput_probe_source_records
                )
                """
            )
        cursor.execute(
            """
            DELETE FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key LIKE %s
            """,
            (data_source_id, f"%{source_record_key_fragment}%"),
        )


def _count_stage4_relational_tables(conn: psycopg.Connection) -> tuple[int, int]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM cf.transaction),
                (SELECT COUNT(*) FROM cf.filing)
            """
        )
        return cursor.fetchone()


def _cleanup_throughput_probe_rows(
    conn: psycopg.Connection,
    *,
    expanded_fixture: _ExpandedStage4Fixture | None,
    data_source_id: UUID | None,
    bulk_loader_fixture_set: BulkLoaderFixtureSet | None,
    initial_data_source_id: UUID | None,
    can_truncate_stage4_tables: bool,
) -> None:
    try:
        conn.rollback()
    except psycopg.Error:
        pass
    if expanded_fixture is not None and data_source_id is not None:
        _cleanup_stage4_throughput_rows_by_source_key_fragment(
            conn,
            data_source_id=data_source_id,
            source_record_key_fragment=expanded_fixture.source_record_key_fragment,
            can_truncate_relational_tables=can_truncate_stage4_tables,
        )
    if bulk_loader_fixture_set is not None:
        _cleanup_bulk_loader_rows(conn, bulk_loader_fixture_set, initial_data_source_id)
    conn.commit()


def _db_identity(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_database(), inet_server_addr()::text, inet_server_port(), version()")
        database, server_addr, server_port, version = cursor.fetchone()
    return {
        "host": conn.info.host or server_addr or "unknown",
        "port": str(conn.info.port or server_port),
        "database": str(database),
        "postgres_version": str(version),
    }


def _print_db_identity(identity: dict[str, str]) -> None:
    print("STAGE4_TRANSACTIONS_THROUGHPUT_DB_IDENTITY")
    for key in ("host", "port", "database", "postgres_version"):
        print(f"{key}: {identity[key]}")


def _snapshot_from_state(state: Any) -> _CommitSnapshot:
    return _CommitSnapshot(
        timestamp=time.perf_counter(),
        inserted=state.load_result.inserted,
        skipped=state.load_result.skipped,
        errors=state.load_result.errors,
        processed_rows=state.processed_rows,
    )


def _install_commit_observers(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: list[_CommitSnapshot],
) -> None:
    original_batch_commit = bulk_stage4_loader._commit_stage4_batch_progress
    original_final_commit = bulk_stage4_loader._commit_stage4_final_progress

    def observed_batch_commit(*args: Any, **kwargs: Any) -> None:
        original_batch_commit(*args, **kwargs)
        state = kwargs["state"]
        if state.processed_since_commit == 0:
            snapshots.append(_snapshot_from_state(state))

    def observed_final_commit(*args: Any, **kwargs: Any) -> bool:
        committed = original_final_commit(*args, **kwargs)
        if committed:
            snapshots.append(_snapshot_from_state(kwargs["state"]))
        return committed

    monkeypatch.setattr(bulk_stage4_loader, "_commit_stage4_batch_progress", observed_batch_commit)
    monkeypatch.setattr(bulk_stage4_loader, "_commit_stage4_final_progress", observed_final_commit)


def _window_from_snapshots(
    snapshots: list[_CommitSnapshot],
    *,
    start_index: int,
    name: str,
) -> tuple[_MeasurementWindow, int]:
    start = snapshots[start_index]
    for end_index in range(start_index + 1, len(snapshots)):
        window = _MeasurementWindow(name=name, start=start, end=snapshots[end_index])
        if window.inserted_rows >= _WINDOW_INSERTED_ROWS:
            return window, end_index
    raise AssertionError(f"Unable to measure {name}: no committed window reached {_WINDOW_INSERTED_ROWS} inserted rows")


def _extract_measurement_windows(snapshots: list[_CommitSnapshot]) -> list[_MeasurementWindow]:
    initial_snapshot = _CommitSnapshot(
        timestamp=snapshots[0].timestamp,
        inserted=0,
        skipped=0,
        errors=0,
        processed_rows=0,
    )
    all_snapshots = [initial_snapshot, *snapshots]
    warmup_window, cursor_index = _window_from_snapshots(all_snapshots, start_index=0, name="warmup")
    assert warmup_window.inserted_rows >= _WINDOW_INSERTED_ROWS

    measured_windows: list[_MeasurementWindow] = []
    for window_number in range(1, _TIMED_WINDOW_COUNT + 1):
        window, cursor_index = _window_from_snapshots(
            all_snapshots,
            start_index=cursor_index,
            name=f"window_{window_number}",
        )
        measured_windows.append(window)
    return measured_windows


def _format_windows(windows: list[_MeasurementWindow]) -> str:
    lines = ["STAGE4_TRANSACTIONS_THROUGHPUT_WINDOWS"]
    for window in windows:
        lines.append(
            " ".join(
                (
                    window.name,
                    f"inserted={window.inserted_rows}",
                    f"skipped={window.skipped_rows}",
                    f"errors={window.error_rows}",
                    f"elapsed_seconds={window.elapsed_seconds:.6f}",
                    f"inserted_per_second={window.inserted_per_second:.2f}",
                    f"cumulative_inserted={window.end.inserted}",
                    f"start_inserted={window.start.inserted}",
                    f"end_processed_rows={window.end.processed_rows}",
                )
            )
        )
    return "\n".join(lines)


def _format_commit_snapshots(snapshots: list[_CommitSnapshot]) -> str:
    lines = ["STAGE4_TRANSACTIONS_THROUGHPUT_COMMIT_SNAPSHOTS"]
    previous_snapshot: _CommitSnapshot | None = None
    for index, snapshot in enumerate(snapshots, start=1):
        inserted_delta = 0 if previous_snapshot is None else snapshot.inserted - previous_snapshot.inserted
        elapsed_seconds = 0.0 if previous_snapshot is None else snapshot.timestamp - previous_snapshot.timestamp
        inserted_per_second = 0.0 if elapsed_seconds <= 0 else inserted_delta / elapsed_seconds
        lines.append(
            " ".join(
                (
                    f"snapshot={index}",
                    f"inserted_delta={inserted_delta}",
                    f"elapsed_seconds={elapsed_seconds:.6f}",
                    f"inserted_per_second={inserted_per_second:.2f}",
                    f"cumulative_inserted={snapshot.inserted}",
                    f"cumulative_skipped={snapshot.skipped}",
                    f"cumulative_errors={snapshot.errors}",
                    f"processed_rows={snapshot.processed_rows}",
                )
            )
        )
        previous_snapshot = snapshot
    return "\n".join(lines)


def _profile_top_20(profile: cProfile.Profile) -> str:
    output = StringIO()
    try:
        pstats.Stats(profile, stream=output).strip_dirs().sort_stats("cumulative").print_stats(20)
    except TypeError as exc:
        return f"profile_unavailable: {exc}"
    return output.getvalue()


def _sql_corroboration(conn: psycopg.Connection, data_source_id: object) -> str:
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.pg_stat_statements')")
        has_pg_stat_statements = cursor.fetchone()[0] is not None
        if has_pg_stat_statements:
            cursor.execute(
                """
                SELECT calls, total_exec_time, rows, left(query, 160)
                FROM pg_stat_statements
                ORDER BY total_exec_time DESC
                LIMIT 5
                """
            )
            rows = cursor.fetchall()
            return "\n".join(f"pg_stat_statements: {row}" for row in rows)

        cursor.execute(
            """
            SELECT state, wait_event_type, wait_event, left(query, 160)
            FROM pg_stat_activity
            WHERE datname = current_database()
            ORDER BY pid
            LIMIT 5
            """
        )
        activity_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s) AS source_records,
                (SELECT COUNT(*) FROM cf.transaction) AS transactions,
                (SELECT COUNT(*) FROM cf.filing) AS filings
            """,
            (data_source_id,),
        )
        count_row = cursor.fetchone()
    return "\n".join(
        [f"pg_stat_activity: {row}" for row in activity_rows]
        + [f"row_counts: source_records={count_row[0]} transactions={count_row[1]} filings={count_row[2]}"]
    )


def _safe_sql_corroboration(conn: psycopg.Connection, data_source_id: object) -> str:
    try:
        return _sql_corroboration(conn, data_source_id)
    except Exception as exc:  # pragma: no cover - diagnostic fallback only
        return f"sql_corroboration_unavailable: {type(exc).__name__}: {exc}"


def _print_probe_diagnostics(
    *,
    result: object | None,
    row_count: int,
    snapshots: list[_CommitSnapshot],
    windows: list[_MeasurementWindow],
    profile: cProfile.Profile,
    conn: psycopg.Connection,
    data_source_id: object,
    measurement_error: BaseException | None,
) -> None:
    if result is None:
        print("STAGE4_TRANSACTIONS_THROUGHPUT_RESULT unavailable")
    else:
        print(
            "STAGE4_TRANSACTIONS_THROUGHPUT_RESULT "
            f"inserted={result.inserted} skipped={result.skipped} errors={result.errors}"
        )
    print(f"STAGE4_TRANSACTIONS_THROUGHPUT_INPUT_ROWS {row_count}")
    if measurement_error is None:
        print(_format_windows(windows))
    else:
        print(
            "STAGE4_TRANSACTIONS_THROUGHPUT_WINDOWS_UNMEASURABLE "
            f"{type(measurement_error).__name__}: {measurement_error}"
        )
        print(_format_commit_snapshots(snapshots))
    print("STAGE4_TRANSACTIONS_THROUGHPUT_PROFILE_TOP_20")
    print(_profile_top_20(profile))
    print("STAGE4_TRANSACTIONS_THROUGHPUT_SQL_CORROBORATION")
    print(_safe_sql_corroboration(conn, data_source_id))


def _assert_valid_measurement_windows(windows: list[_MeasurementWindow]) -> None:
    assert len(windows) == _TIMED_WINDOW_COUNT
    for window in windows:
        assert window.inserted_rows >= _WINDOW_INSERTED_ROWS
        assert window.skipped_rows == 0, f"{window.name} measured skipped rows, not pure inserted throughput"
        assert window.error_rows == 0, f"{window.name} measured error rows, not pure inserted throughput"
        assert window.end.inserted > window.start.inserted, f"{window.name} did not advance inserted rows"


def _window_spread_ratio(rates: list[float]) -> float:
    median_rate = statistics.median(rates)
    if median_rate <= 0:
        return float("inf")
    return (max(rates) - min(rates)) / median_rate


def _assert_stage1_throughput_contract(windows: list[_MeasurementWindow]) -> None:
    rates = [window.inserted_per_second for window in windows]
    median_inserted_per_second = statistics.median(rates)
    slowest_inserted_per_second = min(rates)
    window_spread_ratio = _window_spread_ratio(rates)
    window_summary = [(window.inserted_rows, window.elapsed_seconds, window.inserted_per_second) for window in windows]

    assert median_inserted_per_second >= _MINIMUM_MEDIAN_INSERTED_PER_SECOND, (
        "transactions-only Stage 4 throughput below contract: "
        f"median_inserted_per_second={median_inserted_per_second:.2f}; "
        f"windows={window_summary}"
    )
    assert slowest_inserted_per_second >= _MINIMUM_SLOWEST_INSERTED_PER_SECOND, (
        "transactions-only Stage 4 slowest window below contract: "
        f"slowest_inserted_per_second={slowest_inserted_per_second:.2f}; "
        f"windows={window_summary}"
    )
    assert window_spread_ratio <= _MAXIMUM_WINDOW_SPREAD_RATIO, (
        "transactions-only Stage 4 window spread above contract: "
        f"window_spread_percent={window_spread_ratio * 100:.2f}; "
        f"windows={window_summary}"
    )


def _measurement_window_with_rate(name: str, inserted_per_second: float) -> _MeasurementWindow:
    inserted_rows = _WINDOW_INSERTED_ROWS
    elapsed_seconds = inserted_rows / inserted_per_second
    return _MeasurementWindow(
        name=name,
        start=_CommitSnapshot(timestamp=0.0, inserted=0, skipped=0, errors=0, processed_rows=0),
        end=_CommitSnapshot(
            timestamp=elapsed_seconds,
            inserted=inserted_rows,
            skipped=0,
            errors=0,
            processed_rows=inserted_rows,
        ),
    )


def test_stage1_throughput_contract_rejects_slowest_window_below_floor() -> None:
    windows = [
        _measurement_window_with_rate("window_1", 3_200),
        _measurement_window_with_rate("window_2", 3_100),
        _measurement_window_with_rate("window_3", 2_399),
    ]

    with pytest.raises(AssertionError, match="slowest_inserted_per_second=2399.00"):
        _assert_stage1_throughput_contract(windows)


def test_stage1_throughput_contract_rejects_unstable_window_spread() -> None:
    windows = [
        _measurement_window_with_rate("window_1", 3_100),
        _measurement_window_with_rate("window_2", 3_800),
        _measurement_window_with_rate("window_3", 3_100),
    ]

    with pytest.raises(AssertionError, match="window_spread_percent=22.58"):
        _assert_stage1_throughput_contract(windows)


def test_expand_stage4_itcont_rows_generates_fresh_identities_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix_values = iter(["1111111111", "2222222222"])
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.test_stage4_transactions_throughput._build_throughput_fixture_prefix",
        lambda: next(prefix_values),
    )
    fixture_set = Stage4FixtureSet(
        itcont_path=Path("itcont.txt"),
        itpas2_path=Path("itpas2.txt"),
        itcont_rows=[{"SUB_ID": "1234567890123456789", "TRAN_ID": "T100"}],
        itpas2_rows=[],
    )

    first_rows = _expand_stage4_itcont_rows(fixture_set)
    second_rows = _expand_stage4_itcont_rows(fixture_set)

    assert first_rows[0]["SUB_ID"] == "1234561111111111001"
    assert second_rows[0]["SUB_ID"] == "1234562222222222001"
    assert first_rows[0]["TRAN_ID"] == "T100-1111111111-000001"
    assert second_rows[0]["TRAN_ID"] == "T100-2222222222-000001"
    assert {row["SUB_ID"] for row in first_rows}.isdisjoint({row["SUB_ID"] for row in second_rows})


def test_expanded_stage4_fixture_records_generated_source_record_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.test_stage4_transactions_throughput._MINIMUM_INPUT_ROWS",
        3,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.test_stage4_transactions_throughput._build_throughput_fixture_prefix",
        lambda: "3333333333",
    )
    fixture_set = Stage4FixtureSet(
        itcont_path=Path("itcont.txt"),
        itpas2_path=Path("itpas2.txt"),
        itcont_rows=[
            {"SUB_ID": "1234567890123456789", "TRAN_ID": "T100"},
            {"SUB_ID": "2234567890123456789", "TRAN_ID": "T200"},
        ],
        itpas2_rows=[],
    )

    expanded_fixture = _write_expanded_stage4_fixture_zip(tmp_path, fixture_set)

    assert expanded_fixture.row_count == 3
    assert expanded_fixture.source_record_key_fragment == "3333333333"
    assert expanded_fixture.source_record_keys == [
        "1234563333333333001",
        "2234563333333333002",
        "1234563333333333003",
    ]


def test_cleanup_throughput_probe_rows_reuses_stage4_and_bulk_fixture_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocker = pytest.importorskip("unittest.mock")
    conn = mocker.MagicMock()
    expanded_fixture = _ExpandedStage4Fixture(
        zip_path=Path("indiv.zip"),
        row_count=1,
        source_record_key_fragment="3333333333",
        source_record_keys=["1234563333333333001"],
    )
    bulk_loader_fixture_set = BulkLoaderFixtureSet(
        committee_path=Path("cm.txt"),
        candidate_path=Path("cn.txt"),
        ccl_path=Path("ccl.txt"),
        weball_path=Path("weball.txt"),
        committee_rows=[],
        candidate_rows=[],
        ccl_rows=[],
        weball_rows=[],
    )
    cleanup_stage4_rows = mocker.MagicMock()
    cleanup_bulk_loader_rows = mocker.MagicMock()
    initial_data_source_id = uuid4()
    data_source_id = uuid4()
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.test_stage4_transactions_throughput._cleanup_stage4_throughput_rows_by_source_key_fragment",
        cleanup_stage4_rows,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.test_stage4_transactions_throughput._cleanup_bulk_loader_rows",
        cleanup_bulk_loader_rows,
    )

    _cleanup_throughput_probe_rows(
        conn,
        expanded_fixture=expanded_fixture,
        data_source_id=data_source_id,
        bulk_loader_fixture_set=bulk_loader_fixture_set,
        initial_data_source_id=initial_data_source_id,
        can_truncate_stage4_tables=True,
    )

    conn.rollback.assert_called_once_with()
    cleanup_stage4_rows.assert_called_once_with(
        conn,
        data_source_id=data_source_id,
        source_record_key_fragment="3333333333",
        can_truncate_relational_tables=True,
    )
    cleanup_bulk_loader_rows.assert_called_once_with(conn, bulk_loader_fixture_set, initial_data_source_id)
    conn.commit.assert_called_once_with()


def test_probe_diagnostics_prints_profile_sql_and_snapshots_when_windows_unmeasurable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.test_stage4_transactions_throughput._safe_sql_corroboration",
        lambda _conn, _data_source_id: "sql fallback evidence",
    )
    profile = cProfile.Profile()
    snapshots = [
        _CommitSnapshot(timestamp=10.0, inserted=1_000, skipped=0, errors=0, processed_rows=1_000),
        _CommitSnapshot(timestamp=12.0, inserted=2_000, skipped=0, errors=0, processed_rows=2_000),
    ]
    measurement_error = AssertionError("Unable to measure window_1")

    _print_probe_diagnostics(
        result=None,
        row_count=_MINIMUM_INPUT_ROWS,
        snapshots=snapshots,
        windows=[],
        profile=profile,
        conn=object(),  # type: ignore[arg-type]
        data_source_id=object(),
        measurement_error=measurement_error,
    )

    output = capsys.readouterr().out
    assert "STAGE4_TRANSACTIONS_THROUGHPUT_WINDOWS_UNMEASURABLE AssertionError: Unable to measure window_1" in output
    assert "STAGE4_TRANSACTIONS_THROUGHPUT_COMMIT_SNAPSHOTS" in output
    assert "inserted_delta=1000 elapsed_seconds=2.000000 inserted_per_second=500.00" in output
    assert "STAGE4_TRANSACTIONS_THROUGHPUT_PROFILE_TOP_20" in output
    assert "STAGE4_TRANSACTIONS_THROUGHPUT_SQL_CORROBORATION" in output
    assert "sql fallback evidence" in output


@pytest.mark.timeout(900)
def test_stage4_transactions_only_insert_throughput(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    committing_db_conn: psycopg.Connection,
) -> None:
    bulk_loader_conn = committing_db_conn
    initial_data_source_id = _select_bulk_data_source_id(bulk_loader_conn)
    initial_relational_counts = _count_stage4_relational_tables(bulk_loader_conn)
    can_truncate_stage4_tables = initial_relational_counts == (0, 0)
    bulk_loader_fixture_set: BulkLoaderFixtureSet | None = None
    expanded_fixture: _ExpandedStage4Fixture | None = None
    data_source_id: UUID | None = None
    try:
        assert can_truncate_stage4_tables, (
            "Stage 4 throughput probe requires an empty scratch DB for bounded cleanup: "
            f"initial_transaction_count={initial_relational_counts[0]} "
            f"initial_filing_count={initial_relational_counts[1]}"
        )
        bulk_loader_fixture_set = _materialize_bulk_loader_fixture_set(tmp_path)
        stage4_fixture_set = _materialize_stage4_fixture_set(tmp_path, bulk_loader_fixture_set)
        expanded_fixture = _write_expanded_stage4_fixture_zip(tmp_path, stage4_fixture_set)
        data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
        _load_stage3_committees(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)
        bulk_loader_conn.commit()

        snapshots: list[_CommitSnapshot] = []
        _install_commit_observers(monkeypatch, snapshots)
        _print_db_identity(_db_identity(bulk_loader_conn))

        def load_call() -> object:
            return load_contributions(
                bulk_loader_conn,
                expanded_fixture.zip_path,
                cycle=2024,
                data_source_id=data_source_id,
                options=Stage4LoadOptions(
                    with_transactions=True,
                    entity_extraction=False,
                    batch_size=_BATCH_SIZE,
                ),
            )

        profile = cProfile.Profile()
        result = None
        measurement_error: BaseException | None = None
        profile.enable()
        try:
            result = load_call()
        except BaseException as exc:
            measurement_error = exc
        finally:
            profile.disable()

        windows: list[_MeasurementWindow] = []
        if measurement_error is None:
            try:
                windows = _extract_measurement_windows(snapshots)
            except BaseException as exc:
                measurement_error = exc

        _print_probe_diagnostics(
            result=result,
            row_count=expanded_fixture.row_count,
            snapshots=snapshots,
            windows=windows,
            profile=profile,
            conn=bulk_loader_conn,
            data_source_id=data_source_id,
            measurement_error=measurement_error,
        )
        if measurement_error is not None:
            raise measurement_error

        assert expanded_fixture.row_count >= _MINIMUM_INPUT_ROWS
        assert result.inserted == expanded_fixture.row_count
        assert result.skipped == 0
        assert result.errors == 0
        _assert_valid_measurement_windows(windows)
        _assert_stage1_throughput_contract(windows)
    finally:
        _cleanup_throughput_probe_rows(
            bulk_loader_conn,
            expanded_fixture=expanded_fixture,
            data_source_id=data_source_id,
            bulk_loader_fixture_set=bulk_loader_fixture_set,
            initial_data_source_id=initial_data_source_id,
            can_truncate_stage4_tables=can_truncate_stage4_tables,
        )
