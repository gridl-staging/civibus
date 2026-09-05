from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest

from core import db
from core.refresh import job_builders, runner
from core.types.python.models import DataSource, RefreshRun
from test_support.refresh_run_fixtures import refresh_job_for_tests


def _wait_for_backend_exit(
    connection: psycopg.Connection,
    *,
    backend_pid: int,
    timeout_seconds: float = 2.0,
) -> None:
    """Wait until PostgreSQL observes client close and releases session locks."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        # pg_stat_activity caches a snapshot for this transaction. Refresh it
        # so each poll observes server-side exits since the preceding check.
        connection.execute("SELECT pg_stat_clear_snapshot()")
        row = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid = %s)",
            (backend_pid,),
        ).fetchone()
        if row == (False,):
            return
        time.sleep(0.01)
    pytest.fail(f"PostgreSQL backend {backend_pid} did not exit within {timeout_seconds} seconds")


def _historical_recovery_identity(
    *,
    refresh_run_id: UUID,
    job_key: str,
    source_name: str,
    started_at: datetime,
) -> runner.HistoricalRefreshRecoveryIdentity:
    parameters = db.build_connection_parameters()
    return runner.HistoricalRefreshRecoveryIdentity(
        refresh_run_id=refresh_run_id,
        job_key=job_key,
        domain="campaign_finance",
        jurisdiction="state/WA",
        filing_authority_type="state",
        filing_authority_code="WA",
        data_source_names=(source_name,),
        execution_origin="operator_attended",
        started_at=started_at,
        app="civibus-regional-refresh",
        machine_id="abc123",
        authority="state/WA",
        execution_plan="regional-wa-scheduled",
        database_host=str(parameters["host"]),
        database_port=int(parameters["port"]),
        database_name=str(parameters["dbname"]),
    )


def _seed_historical_recovery_attempt(
    connection: psycopg.Connection,
    *,
    job_key: str,
) -> tuple[runner.HistoricalRefreshRecoveryIdentity, UUID, datetime]:
    source_name = f"WA historical recovery proof {uuid4()}"
    source_id = db.insert_data_source(
        connection,
        DataSource(
            domain="campaign_finance",
            jurisdiction="state/WA",
            filing_authority_type="state",
            filing_authority_code="WA",
            name=source_name,
            source_url="https://example.invalid/historical-recovery-proof",
            last_pull_at=datetime(2026, 8, 26, 4, 41, 59, tzinfo=timezone.utc),
            last_pull_status="success",
        ),
    )
    refresh_run_id = uuid4()
    started_at = datetime(2026, 8, 29, 23, 39, 28, tzinfo=timezone.utc)
    db.insert_refresh_run(
        connection,
        RefreshRun(
            id=refresh_run_id,
            job_key=job_key,
            domain="campaign_finance",
            jurisdiction="state/WA",
            data_source_names=[source_name],
            execution_origin="operator_attended",
            pull_status="running",
            started_at=started_at,
            completed_at=None,
            metadata_updates=0,
            message="Refresh job started",
        ),
    )
    connection.commit()
    return (
        _historical_recovery_identity(
            refresh_run_id=refresh_run_id,
            job_key=job_key,
            source_name=source_name,
            started_at=started_at,
        ),
        source_id,
        datetime(2026, 8, 26, 4, 41, 59, tzinfo=timezone.utc),
    )


def _delete_historical_recovery_fixture(
    connection: psycopg.Connection,
    *,
    identity: runner.HistoricalRefreshRecoveryIdentity,
    source_id: UUID,
) -> None:
    connection.rollback()
    connection.execute("DELETE FROM core.refresh_run WHERE id = %s", (identity.refresh_run_id,))
    connection.execute("DELETE FROM core.data_source WHERE id = %s", (source_id,))
    connection.commit()


@pytest.mark.integration
def test_historical_recovery_atomically_terminalizes_exact_orphan_without_freshness_promotion_and_repeats(
    committing_db_conn: psycopg.Connection,
) -> None:
    identity, source_id, source_last_pull_at = _seed_historical_recovery_attempt(
        committing_db_conn,
        job_key=f"state-wa-historical-recovery-{uuid4()}",
    )
    recovery = runner.get_connection(application_name="historical-recovery-proof")
    completed_at = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    try:
        first = runner.recover_historical_refresh_attempt(recovery, identity, completed_at=completed_at)
        second = runner.recover_historical_refresh_attempt(recovery, identity)

        assert first.already_terminal is False
        assert second.already_terminal is True
        assert first.postcondition == second.postcondition
        assert first.postcondition["running_refresh_rows"] == 0
        assert first.postcondition["active_refresh_backends"] == 0
        row = committing_db_conn.execute(
            """
            SELECT pull_status, completed_at, inserted_count, skipped_count,
                   quarantined_count, superseded_count, error_count, metadata_updates,
                   message, error
            FROM core.refresh_run
            WHERE id = %s
            """,
            (identity.refresh_run_id,),
        ).fetchone()
        assert row == (
            "failed",
            completed_at,
            0,
            0,
            0,
            0,
            0,
            0,
            runner._HISTORICAL_RECOVERY_MESSAGE,
            runner._HISTORICAL_RECOVERY_ERROR,
        )
        source_row = committing_db_conn.execute(
            "SELECT last_pull_at, last_pull_status FROM core.data_source WHERE id = %s",
            (source_id,),
        ).fetchone()
        assert source_row == (source_last_pull_at, "success")
    finally:
        recovery.close()
        _delete_historical_recovery_fixture(
            committing_db_conn,
            identity=identity,
            source_id=source_id,
        )


@pytest.mark.integration
def test_historical_recovery_refuses_an_active_exact_job_backend_before_mutation(
    committing_db_conn: psycopg.Connection,
) -> None:
    identity, source_id, _ = _seed_historical_recovery_attempt(
        committing_db_conn,
        job_key=f"state-wa-historical-backend-{uuid4()}",
    )
    active_job = runner.get_connection(application_name=runner._scoped_connection_identity(identity.job_key))
    recovery = runner.get_connection(application_name="historical-recovery-backend-proof")
    try:
        with pytest.raises(RuntimeError, match="exact historical refresh job still has an active backend"):
            runner.recover_historical_refresh_attempt(recovery, identity)
        row = committing_db_conn.execute(
            "SELECT pull_status, completed_at FROM core.refresh_run WHERE id = %s",
            (identity.refresh_run_id,),
        ).fetchone()
        assert row == ("running", None)
    finally:
        recovery.close()
        active_job.close()
        _delete_historical_recovery_fixture(
            committing_db_conn,
            identity=identity,
            source_id=source_id,
        )


@pytest.mark.integration
def test_historical_recovery_refuses_existing_runner_advisory_lock_and_concurrent_row_lock(
    committing_db_conn: psycopg.Connection,
) -> None:
    identity, source_id, _ = _seed_historical_recovery_attempt(
        committing_db_conn,
        job_key=f"state-wa-historical-lock-{uuid4()}",
    )
    job = refresh_job_for_tests(identity.job_key)
    advisory_holder = runner.get_connection(application_name="historical-advisory-holder")
    row_holder = runner.get_connection(application_name="historical-row-holder")
    recovery = runner.get_connection(application_name="historical-recovery-lock-proof")
    try:
        assert runner._try_acquire_database_runner_locks(advisory_holder, [job]) is True
        with pytest.raises(RuntimeError, match="advisory lock"):
            runner.recover_historical_refresh_attempt(recovery, identity)
        advisory_holder.close()

        row_holder.execute(
            "SELECT id FROM core.refresh_run WHERE id = %s FOR UPDATE",
            (identity.refresh_run_id,),
        )
        with pytest.raises(RuntimeError, match="row lock"):
            runner.recover_historical_refresh_attempt(recovery, identity)
        row = committing_db_conn.execute(
            "SELECT pull_status, completed_at FROM core.refresh_run WHERE id = %s",
            (identity.refresh_run_id,),
        ).fetchone()
        assert row == ("running", None)
    finally:
        recovery.close()
        row_holder.rollback()
        row_holder.close()
        if not advisory_holder.closed:
            advisory_holder.close()
        _delete_historical_recovery_fixture(
            committing_db_conn,
            identity=identity,
            source_id=source_id,
        )


@pytest.mark.integration
def test_historical_recovery_rolls_back_terminal_update_when_finalization_fails(
    monkeypatch: pytest.MonkeyPatch,
    committing_db_conn: psycopg.Connection,
) -> None:
    identity, source_id, _ = _seed_historical_recovery_attempt(
        committing_db_conn,
        job_key=f"state-wa-historical-rollback-{uuid4()}",
    )
    recovery = runner.get_connection(application_name="historical-recovery-rollback-proof")
    original_finish = runner._finish_refresh_run

    def _update_then_fail(*args: object, **kwargs: object) -> None:
        original_finish(*args, **kwargs)
        raise RuntimeError("injected post-update failure")

    monkeypatch.setattr(runner, "_finish_refresh_run", _update_then_fail)
    try:
        with pytest.raises(RuntimeError, match="injected post-update failure"):
            runner.recover_historical_refresh_attempt(recovery, identity)
        row = committing_db_conn.execute(
            "SELECT pull_status, completed_at, metadata_updates FROM core.refresh_run WHERE id = %s",
            (identity.refresh_run_id,),
        ).fetchone()
        assert row == ("running", None, 0)
    finally:
        recovery.close()
        _delete_historical_recovery_fixture(
            committing_db_conn,
            identity=identity,
            source_id=source_id,
        )


@pytest.mark.integration
def test_database_runner_lock_serializes_sessions_and_releases_partial_acquisition_on_close() -> None:
    regional_job = refresh_job_for_tests("state-wa-contributions")
    federal_job = refresh_job_for_tests("federal-fec-masters")
    holder = runner.get_connection(application_name="refresh-lock-test-holder")
    contender = runner.get_connection(application_name="refresh-lock-test-contender")
    observer = runner.get_connection(application_name="refresh-lock-test-observer")
    holder_closed = False
    contender_closed = False

    try:
        assert runner._try_acquire_database_runner_locks(holder, [regional_job]) is True
        holder.commit()
        holder.rollback()

        started_at = time.monotonic()
        assert runner._try_acquire_database_runner_locks(contender, [regional_job, federal_job]) is False
        assert time.monotonic() - started_at < 0.5

        # Sorted acquisition took the disjoint federal key before finding the
        # regional overlap. The contender session owns it until main() closes
        # that session on exit 2.
        assert runner._try_acquire_database_runner_locks(observer, [federal_job]) is False
        contender_backend_pid = contender.info.backend_pid
        contender.close()
        contender_closed = True
        _wait_for_backend_exit(observer, backend_pid=contender_backend_pid)
        assert runner._try_acquire_database_runner_locks(observer, [federal_job]) is True

        holder_backend_pid = holder.info.backend_pid
        holder.close()
        holder_closed = True
        _wait_for_backend_exit(observer, backend_pid=holder_backend_pid)
        assert runner._try_acquire_database_runner_locks(observer, [regional_job]) is True
    finally:
        if not holder_closed:
            holder.close()
        if not contender_closed:
            contender.close()
        observer.close()


@pytest.mark.integration
def test_authority_ownership_lock_blocks_same_authority_cross_run_but_not_another_authority() -> None:
    wa_contributions = refresh_job_for_tests("state-wa-contributions", jurisdiction="state/WA")
    wa_loans = refresh_job_for_tests("state-wa-loans", jurisdiction="state/WA")
    sf_transactions = refresh_job_for_tests("city-sf-transactions", jurisdiction="municipality/SF")
    holder = runner.get_connection(application_name="refresh-authority-lock-holder")
    contender = runner.get_connection(application_name="refresh-authority-lock-contender")
    observer = runner.get_connection(application_name="refresh-authority-lock-observer")
    try:
        assert (
            runner._try_acquire_database_runner_locks(
                holder,
                [wa_contributions],
                authority_ownership_lock_key="authority-plan:state/WA",
            )
            is True
        )
        assert (
            runner._try_acquire_database_runner_locks(
                contender,
                [wa_loans],
                authority_ownership_lock_key="authority-plan:state/WA",
            )
            is False
        )
        assert (
            runner._try_acquire_database_runner_locks(
                observer,
                [sf_transactions],
                authority_ownership_lock_key="authority-plan:municipality/SF",
            )
            is True
        )
    finally:
        holder.close()
        contender.close()
        observer.close()


@pytest.mark.integration
def test_main_cross_host_contention_exits_two_before_refresh_or_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_callable = MagicMock(side_effect=AssertionError("refresh callable must not run"))
    job = refresh_job_for_tests("state-wa-contributions", run_callable=run_callable)
    holder = runner.get_connection(application_name="refresh-lock-main-holder")
    holder_closed = False
    run_all_jobs = MagicMock(side_effect=AssertionError("ledger path must not run"))
    local_base_path = tmp_path / "regional-machine" / "civibus-refresh-runner.lock"

    try:
        assert runner._try_acquire_database_runner_locks(holder, [job]) is True
        monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", local_base_path)
        monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
        monkeypatch.setattr(runner, "run_all_jobs", run_all_jobs)

        exit_code = runner.main(
            [
                "--scope",
                "all",
                "--job-key-prefix",
                job.key,
                "--execution-origin",
                "operator_attended",
            ]
        )

        assert exit_code == 2
        run_all_jobs.assert_not_called()
        run_callable.assert_not_called()
        assert "database lock: state-wa-contributions" in capsys.readouterr().err

        local_key_path = runner._runner_lock_path_for_job_key(local_base_path, job.key)
        reacquired_fd = runner._acquire_runner_lock(local_key_path)
        assert reacquired_fd is not None
        runner._release_runner_locks([reacquired_fd])

        holder.close()
        holder_closed = True
        probe = runner.get_connection(application_name="refresh-lock-main-cleanup-probe")
        try:
            assert runner._try_acquire_database_runner_locks(probe, [job]) is True
        finally:
            probe.close()
    finally:
        if not holder_closed:
            holder.close()
