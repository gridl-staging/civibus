from __future__ import annotations

import threading
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from core.db import get_connection
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    bulk_fixture_contributor_person_ids,
    bulk_fixture_row_counts,
    cleanup_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper import load as pa_load_module
from domains.campaign_finance.jurisdictions.states.PA.scraper import pa_load_test_support as pa_support
from domains.campaign_finance.jurisdictions.states.PA.scraper.load import load_pa_contributions_with_filings

# --- Stage 1: shared bulk/observer seam smoke specimen -------------------------
#
# One DB-backed specimen that exercises the whole Stage 1 seam Stages 2 and 3
# reuse: a bulk contributions fixture crossing load._COMMIT_BATCH_ROWS, exact
# inserted/source-record/transaction counts and the entity-leak guard through the
# pa_support helpers, two independent fixture identities that share one extracted
# address resolving to a single core.address row, and the backend-activity
# observer that later blocking stages poll.

_BULK_ROW_COUNT = pa_load_module._COMMIT_BATCH_ROWS + 1


def _write_clean_fixture(resources: ExitStack, tmp_path: Path, **fixture_options) -> pa_support.PAFixture:
    """Write a PA fixture pair, register its teardown, and clear rows a prior run left.

    Every specimen in this module needs the same three steps before it loads anything,
    and the pre-clean only holds if the caller's connection is already IDLE.
    """
    fixture = pa_support.write_pa_fixture_pair(tmp_path, **fixture_options)
    resources.callback(cleanup_bulk_fixture, fixture)
    cleanup_bulk_fixture(fixture)
    return fixture


def test_pa_bulk_and_shared_address_seam_smoke(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    # db_conn yields with BEGIN already executed; the loader must observe IDLE to
    # own its commits, otherwise nothing commits and the test proves nothing.
    db_conn.rollback()

    with ExitStack() as resources:
        bulk = _write_clean_fixture(resources, tmp_path, row_count=_BULK_ROW_COUNT)
        ident_a = _write_clean_fixture(resources, tmp_path, shared_address="4200 Shared Common Ave")
        ident_b = _write_clean_fixture(resources, tmp_path, shared_address="4200 Shared Common Ave")

        # Backend-activity observer contract (the seam Stage 2's blocking test
        # polls): a real, live backend PID yields a BackendActivity naming that
        # exact PID, and a terminated backend's PID reads as an honest None rather
        # than a synthesised healthy row.
        live_pid = db_conn.info.backend_pid
        live_activity = pa_support.observe_backend_activity(live_pid)
        assert live_activity is not None
        assert live_activity.pid == live_pid
        assert isinstance(live_activity.blocking_pids, list)

        gone_conn = get_connection()
        gone_pid = gone_conn.info.backend_pid
        gone_conn.close()
        # Closing the client connection does not synchronously tear down the server
        # backend, so an independent observer connection can still see the row for a
        # moment. Poll the shared bounded guard instead of assuming synchronous
        # external state; wait_until raises on timeout, so a backend that never goes
        # away fails the test rather than reading as healthy.
        pa_support.wait_until(
            lambda: pa_support.observe_backend_activity(gone_pid) is None,
            timeout_seconds=5.0,
            poll_interval_seconds=0.05,
            description=f"backend pid {gone_pid} to leave pg_stat_activity",
        )
        assert pa_support.observe_backend_activity(gone_pid) is None

        assert len(bulk.source_record_keys) > pa_load_module._COMMIT_BATCH_ROWS
        assert len(bulk.source_record_keys) == _BULK_ROW_COUNT
        assert len(set(bulk.source_record_keys)) == _BULK_ROW_COUNT

        baseline = pa_support.fixture_entity_row_counts(bulk)

        result = load_pa_contributions_with_filings(db_conn, bulk.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        assert result.inserted == _BULK_ROW_COUNT
        assert result.errors == 0

        # Exact inserted/source-record/transaction counts through the helpers, not
        # ad hoc SQL: one source record and one transaction per bulk row.
        source_record_count, transaction_count = bulk_fixture_row_counts(bulk)
        assert source_record_count == _BULK_ROW_COUNT
        assert transaction_count == _BULK_ROW_COUNT

        # Leak guard: the load created entity rows (distinct donor person per row,
        # one shared committee org, one shared street address, one committee).
        after = pa_support.fixture_entity_row_counts(bulk)
        assert after != baseline
        assert after["person"] == baseline["person"] + _BULK_ROW_COUNT
        assert after["organization"] == baseline["organization"] + 1
        assert after["address"] == baseline["address"] + 1
        assert after["committee"] == baseline["committee"] + 1

        cleanup_bulk_fixture(bulk)
        assert pa_support.fixture_entity_row_counts(bulk) == baseline

        # Two independent identities sharing one address resolve to one core.address
        # row while staying separate committee/provenance fixtures.
        result_a = load_pa_contributions_with_filings(db_conn, ident_a.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert result_a.inserted == 1
        assert result_a.errors == 0
        assert bulk_fixture_row_counts(ident_a) == (1, 1)
        assert bulk_fixture_row_counts(ident_b) == (0, 0)
        assert pa_support.fixture_address_ids(ident_b) == []

        result_b = load_pa_contributions_with_filings(db_conn, ident_b.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert result_b.inserted == 1
        assert result_b.errors == 0
        assert bulk_fixture_row_counts(ident_b) == (1, 1)

        address_ids_a = pa_support.fixture_address_ids(ident_a)
        address_ids_b = pa_support.fixture_address_ids(ident_b)
        assert len(address_ids_a) == 1
        assert address_ids_a == address_ids_b
        # Separate identities: distinct committees and distinct source records.
        assert ident_a.committee_fec_id != ident_b.committee_fec_id
        assert set(ident_a.source_record_keys).isdisjoint(ident_b.source_record_keys)


def test_pa_bulk_fixture_person_identities_are_run_scoped(db_conn: psycopg.Connection, tmp_path: Path) -> None:
    db_conn.rollback()

    with ExitStack() as resources:
        shared_address = f"4250 Run Scoped Donor Ave {uuid4().hex[:12]}"
        fixture_a = _write_clean_fixture(resources, tmp_path, shared_address=shared_address)
        fixture_b = _write_clean_fixture(resources, tmp_path, shared_address=shared_address)

        result_a = load_pa_contributions_with_filings(db_conn, fixture_a.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        result_b = load_pa_contributions_with_filings(db_conn, fixture_b.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert (result_a.inserted, result_a.errors) == (1, 0)
        assert (result_b.inserted, result_b.errors) == (1, 0)
        assert bulk_fixture_row_counts(fixture_a) == (1, 1)
        assert bulk_fixture_row_counts(fixture_b) == (1, 1)
        person_zip_keys_a = pa_support.fixture_person_zip_keys(fixture_a)
        person_zip_keys_b = pa_support.fixture_person_zip_keys(fixture_b)
        contributor_person_ids_a = bulk_fixture_contributor_person_ids(fixture_a)
        contributor_person_ids_b = bulk_fixture_contributor_person_ids(fixture_b)
        assert len(contributor_person_ids_a) == len(contributor_person_ids_b) == 1
        assert None not in contributor_person_ids_a + contributor_person_ids_b
        assert contributor_person_ids_a[0] != contributor_person_ids_b[0]
        assert person_zip_keys_a != person_zip_keys_b
        address_ids_a = pa_support.fixture_address_ids(fixture_a)
        address_ids_b = pa_support.fixture_address_ids(fixture_b)
        assert len(address_ids_a) == 1
        assert address_ids_a == address_ids_b


# --- Stage 2: shared-dimension lock-release specimen ---------------------------
#
# One DB-backed acceptance specimen proving the PA loader releases a shared
# core.address lock at its FIRST batch commit (load._COMMIT_BATCH_ROWS rows in),
# before the whole load finishes — not only at job end. Two real loader calls run
# on independent connections in worker threads; Job A holds the uncommitted
# shared-address lock, Job B contends, and every claim is asserted from durable
# committed state (never from wall-clock ordering).

_GATE_TIMEOUT_SECONDS = 60.0
_BULK_TIMEOUT_SECONDS = 90.0


def _hold_at_gate(reached: threading.Event, release: threading.Event, gate_name: str) -> None:
    """Announce arrival at a gate from a worker thread and block until the main thread releases it.

    The timeout is read from the module global at call time so a specimen test can shrink
    it and prove the never-released path raises instead of hanging.
    """
    reached.set()
    if not release.wait(timeout=_GATE_TIMEOUT_SECONDS):
        raise TimeoutError(f"{gate_name} was never released")


def _stage2_gated_row_loader(
    job_a: pa_support.PAFixture,
    gates: tuple[threading.Event, threading.Event, threading.Event, threading.Event],
):
    gate1_reached, gate1_release, gate2_reached, gate2_release = gates
    real_load_pa_row = pa_load_module._load_pa_row
    a_invocations = 0

    def _gated_load_pa_row(conn, row, data_source_id, *, data_type):
        nonlocal a_invocations
        is_job_a = pa_load_module._pa_campaign_finance_id(row, data_type=data_type) == job_a.campaign_finance_id
        if not is_job_a:
            return real_load_pa_row(conn, row, data_source_id, data_type=data_type)

        a_invocations += 1
        if a_invocations == pa_load_module._COMMIT_BATCH_ROWS + 1:
            # GATE 2 holds *before* the row loads, so job A's committed state stays at
            # exactly one batch while the main thread asserts the committed row counts.
            _hold_at_gate(gate2_reached, gate2_release, "GATE 2")
            return real_load_pa_row(conn, row, data_source_id, data_type=data_type)

        result = real_load_pa_row(conn, row, data_source_id, data_type=data_type)
        if a_invocations == 1:
            # GATE 1 holds *after* row 1 loads, so job A still owns the uncommitted
            # shared core.address lock that job B has to contend for.
            _hold_at_gate(gate1_reached, gate1_release, "GATE 1")
        return result

    return _gated_load_pa_row


def test_load_pa_with_filings_releases_shared_dimension_lock_at_batch_commit(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_conn.rollback()

    with ExitStack() as resources:
        shared_address = f"5100 Batch Commit Lock Ave {uuid4().hex[:12]}"
        job_a = _write_clean_fixture(resources, tmp_path, row_count=_BULK_ROW_COUNT, shared_address=shared_address)
        job_b = _write_clean_fixture(resources, tmp_path, shared_address=shared_address)
        assert bulk_fixture_row_counts(job_a) == (0, 0)
        assert bulk_fixture_row_counts(job_b) == (0, 0)

        gates = tuple(threading.Event() for _ in range(4))
        gate1_reached, gate1_release, gate2_reached, gate2_release = gates
        conn_a = get_connection()
        resources.callback(conn_a.close)
        conn_b = get_connection()
        resources.callback(conn_b.close)
        job_a_pid, job_b_pid = conn_a.info.backend_pid, conn_b.info.backend_pid
        worker_errors: dict[str, BaseException] = {}

        def _reraise_worker_error(key: str) -> None:
            """Fail with a worker thread's own exception instead of waiting out its gate."""
            if key in worker_errors:
                raise worker_errors[key]

        def _run_job(conn: psycopg.Connection, fixture: pa_support.PAFixture, key: str) -> None:
            try:
                load_pa_contributions_with_filings(conn, fixture.detail_path, year=pa_support.PA_FIXTURE_YEAR)
            except BaseException as exc:  # noqa: BLE001 - surfaced to main thread
                worker_errors[key] = exc

        thread_a = threading.Thread(target=_run_job, args=(conn_a, job_a, "a"), name="pa-job-a")
        thread_b = threading.Thread(target=_run_job, args=(conn_b, job_b, "b"), name="pa-job-b")
        monkeypatch.setattr(pa_load_module, "_load_pa_row", _stage2_gated_row_loader(job_a, gates))

        try:
            thread_a.start()
            if not gate1_reached.wait(timeout=_GATE_TIMEOUT_SECONDS):
                _reraise_worker_error("a")
                raise AssertionError("Job A never reached GATE 1 (first-row hold)")
            thread_b.start()

            def _b_blocked_by_a() -> bool:
                _reraise_worker_error("b")
                activity = pa_support.observe_backend_activity(job_b_pid)
                return bool(
                    activity
                    and job_a_pid in activity.blocking_pids
                    and activity.wait_event_type == "Lock"
                    and "insert into core.address" in (activity.query or "").lower()
                )

            pa_support.wait_until(
                _b_blocked_by_a,
                timeout_seconds=_GATE_TIMEOUT_SECONDS,
                description="job B blocked by job A on the shared core.address lock",
            )
            gate1_release.set()

            def _a_reached_gate2() -> bool:
                _reraise_worker_error("a")
                return gate2_reached.is_set()

            pa_support.wait_until(
                _a_reached_gate2,
                timeout_seconds=_BULK_TIMEOUT_SECONDS,
                description="job A to pause after its first batch commit (GATE 2)",
            )

            thread_b.join(timeout=_GATE_TIMEOUT_SECONDS)
            assert not thread_b.is_alive(), "Job B did not unblock after A's batch commit"
            _reraise_worker_error("b")
            assert bulk_fixture_row_counts(job_b) == (1, 1)
            source_records_a, _ = bulk_fixture_row_counts(job_a)
            assert source_records_a == pa_load_module._COMMIT_BATCH_ROWS == _BULK_ROW_COUNT - 1

            gate2_release.set()
            thread_a.join(timeout=_BULK_TIMEOUT_SECONDS)
            assert not thread_a.is_alive(), "Job A did not finish after GATE 2 release"
            _reraise_worker_error("a")
            assert bulk_fixture_row_counts(job_a) == (_BULK_ROW_COUNT, _BULK_ROW_COUNT)
        finally:
            gate1_release.set()
            gate2_release.set()
            for thread, timeout in ((thread_a, _BULK_TIMEOUT_SECONDS), (thread_b, _GATE_TIMEOUT_SECONDS)):
                if thread.ident is not None:
                    thread.join(timeout=timeout)


# --- Stage 3: interruption preserves committed batch --------------------------


class _Stage3Interruption(BaseException):
    # _try_load_pa_row swallows Exception, while a process-style interrupt must escape.
    pass


def _stage3_interrupting_row_loader(raise_at_invocation: int):
    real_load_pa_row = pa_load_module._load_pa_row
    invocations = 0

    def _interrupting_load_pa_row(conn, row, data_source_id, *, data_type):
        nonlocal invocations
        invocations += 1
        if invocations == raise_at_invocation:
            raise _Stage3Interruption("stage3 interruption")
        return real_load_pa_row(conn, row, data_source_id, data_type=data_type)

    return _interrupting_load_pa_row


def test_load_pa_with_filings_rerun_after_interruption_preserves_committed_batch(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_conn.rollback()

    with ExitStack() as resources:
        fixture = _write_clean_fixture(resources, tmp_path, row_count=_BULK_ROW_COUNT)
        assert bulk_fixture_row_counts(fixture) == (0, 0)

        monkeypatch.setattr(
            pa_load_module,
            "_load_pa_row",
            _stage3_interrupting_row_loader(_BULK_ROW_COUNT),
        )
        with pytest.raises(_Stage3Interruption, match="stage3 interruption"):
            load_pa_contributions_with_filings(
                db_conn,
                fixture.detail_path,
                year=pa_support.PA_FIXTURE_YEAR,
            )
        db_conn.rollback()

        # Phase 2 never ran, so the committed source-record batch has zero transactions.
        assert bulk_fixture_row_counts(fixture) == (_BULK_ROW_COUNT - 1, 0)

        monkeypatch.undo()
        rerun_conn = get_connection()
        resources.callback(rerun_conn.close)
        rerun_conn.rollback()
        second = load_pa_contributions_with_filings(
            rerun_conn,
            fixture.detail_path,
            year=pa_support.PA_FIXTURE_YEAR,
        )

        assert second.inserted == 1
        assert second.skipped == _BULK_ROW_COUNT - 1
        assert second.errors == 0
        assert bulk_fixture_row_counts(fixture) == (_BULK_ROW_COUNT, _BULK_ROW_COUNT)
