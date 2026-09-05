"""Tests for the refresh runner's local and database-backed mutual exclusion."""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.refresh import job_builders
from core.refresh import runner
from core.refresh.runner import _acquire_runner_lock


def _job_for_tests(key: str) -> runner.RefreshJob:
    return runner.RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction="state/WA",
        cadence="daily",
        data_source_names=(f"{key} test source",),
        run_callable=lambda: object(),
    )


def _success_result(key: str) -> runner.RefreshRunResult:
    return runner.RefreshRunResult(key=key, status="success", metadata_updates=0, message="ok")


def _expected_key_lock_path(base_lock_path: Path, key: str) -> Path:
    return base_lock_path.with_name(f"{base_lock_path.stem}-{key}{base_lock_path.suffix}")


def _redirect_runner_lock_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    primary_lock_path = tmp_path / "civibus-refresh-runner.lock"
    fallback_lock_path = tmp_path / "fallback" / "civibus-refresh-runner-10001.lock"
    fallback_lock_path.parent.mkdir()
    monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", primary_lock_path)
    monkeypatch.setattr(runner, "_fallback_runner_lock_path", lambda: fallback_lock_path)
    return primary_lock_path


class _FakeConnection:
    def cursor(self) -> MagicMock:
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value.fetchone.return_value = (True,)
        return cursor_context

    def close(self) -> None:
        pass


def test_acquire_lock_succeeds_when_unlocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test.lock"
        fd = _acquire_runner_lock(lock_path)
        assert fd is not None
        assert lock_path.exists()
        os.close(fd)


def test_acquire_lock_fails_when_already_held() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test.lock"

        first_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(first_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        second_fd = _acquire_runner_lock(lock_path)
        assert second_fd is None

        os.close(first_fd)


def test_lock_released_after_close_allows_reacquire() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test.lock"

        fd1 = _acquire_runner_lock(lock_path)
        assert fd1 is not None
        os.close(fd1)

        fd2 = _acquire_runner_lock(lock_path)
        assert fd2 is not None
        os.close(fd2)


def test_database_runner_locks_use_sorted_distinct_exact_job_keys() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [(True,), (True,)]
    jobs = [
        _job_for_tests("state-wa-contributions"),
        _job_for_tests("federal-fec-masters"),
        _job_for_tests("state-wa-contributions"),
    ]

    assert runner._try_acquire_database_runner_locks(connection, jobs) is True

    assert [call.args[1] for call in cursor.execute.call_args_list] == [
        ("civibus-refresh-runner:federal-fec-masters",),
        ("civibus-refresh-runner:state-wa-contributions",),
    ]
    assert all(
        "pg_try_advisory_lock(hashtextextended(%s, 0))" in call.args[0] for call in cursor.execute.call_args_list
    )


def test_database_runner_lock_returns_false_immediately_on_partial_overlap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [(True,), (False,)]
    jobs = [
        _job_for_tests("state-wa-contributions"),
        _job_for_tests("state-pa-expenditures"),
    ]

    started_at = time.monotonic()
    acquired = runner._try_acquire_database_runner_locks(connection, jobs)

    assert acquired is False
    assert time.monotonic() - started_at < 0.5
    assert [call.args[1] for call in cursor.execute.call_args_list] == [
        ("civibus-refresh-runner:state-pa-expenditures",),
        ("civibus-refresh-runner:state-wa-contributions",),
    ]
    assert "database lock: state-wa-contributions" in capsys.readouterr().err


def test_main_database_lock_contention_exits_two_before_ledger_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    job = _job_for_tests("state-wa-contributions")

    class FakeConnection:
        def close(self) -> None:
            events.append("close_database_connection")

    def fake_database_locks(connection: object, jobs: list[runner.RefreshJob]) -> bool:
        events.append("try_database_locks")
        assert isinstance(connection, FakeConnection)
        assert jobs == [job]
        return False

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: events.append("build_plan") or [job])
    monkeypatch.setattr(
        runner,
        "_acquire_runner_locks_for_jobs",
        lambda jobs, wait_seconds=0.0: events.append("acquire_local_locks") or [101],
    )
    monkeypatch.setattr(
        runner,
        "get_connection",
        lambda **kwargs: events.append("open_database_connection") or FakeConnection(),
    )
    monkeypatch.setattr(runner, "_try_acquire_database_runner_locks", fake_database_locks)
    monkeypatch.setattr(
        runner,
        "run_all_jobs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ledger/callable path must not run")),
    )
    monkeypatch.setattr(
        runner,
        "_release_runner_locks",
        lambda held: events.append(f"release_local_locks:{held}"),
    )

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
    assert events == [
        "build_plan",
        "acquire_local_locks",
        "open_database_connection",
        "try_database_locks",
        "close_database_connection",
        "release_local_locks:[101]",
    ]


def test_acquire_lock_surfaces_lock_path_setup_permission_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_permission_error(*args: object, **kwargs: object) -> None:
        raise PermissionError("cannot create lock directory")

    monkeypatch.setattr(Path, "mkdir", raise_permission_error)

    with pytest.raises(PermissionError, match="cannot create lock directory"):
        _acquire_runner_lock(Path("/var/lock/civibus-refresh-runner.lock"))


def test_fallback_runner_lock_path_uses_tempdir_and_uid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(runner.os, "getuid", lambda: 10001)

    assert runner._fallback_runner_lock_path() == tmp_path / "civibus-refresh-runner-10001.lock"


def test_main_uses_fallback_lock_when_primary_lock_path_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    primary_base_lock_path = tmp_path / "civibus-refresh-runner.lock"
    fallback_base_lock_path = tmp_path / "fallback" / "civibus-refresh-runner-10001.lock"
    job = _job_for_tests("state-wa-contributions")
    primary_key_lock_path = tmp_path / "civibus-refresh-runner-state-wa-contributions.lock"
    fallback_key_lock_path = tmp_path / "fallback" / "civibus-refresh-runner-10001-state-wa-contributions.lock"
    lock_attempts: list[Path] = []
    acquired_fds: list[int] = []
    fallback_base_lock_path.parent.mkdir()

    def fake_acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int | None:
        lock_attempts.append(lock_path)
        if lock_path == primary_key_lock_path:
            raise PermissionError("cannot create /var/lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        acquired_fds.append(fd)
        return fd

    monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", primary_base_lock_path)
    monkeypatch.setattr(runner, "_fallback_runner_lock_path", lambda: fallback_base_lock_path)
    monkeypatch.setattr(runner, "_acquire_runner_lock", fake_acquire_runner_lock)
    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "get_connection", lambda **overrides: _FakeConnection())
    monkeypatch.setattr(
        runner,
        "run_all_jobs",
        lambda connection, jobs, dry_run, force, execution_origin, on_result, stop_on_failure=False, on_heartbeat=None: [
            _success_result(jobs[0].key)
        ],
    )

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", "state-wa-contributions"])
    finally:
        for fd in acquired_fds:
            try:
                os.close(fd)
            except OSError:
                pass

    assert exit_code == 0
    assert lock_attempts == [primary_key_lock_path, fallback_key_lock_path]
    captured = capsys.readouterr()
    assert "Refresh runner using fallback lock" in captured.err
    assert "Another refresh runner is already active" not in captured.err


def test_main_allows_disjoint_key_when_old_global_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    primary_lock_path = _redirect_runner_lock_paths(monkeypatch, tmp_path)
    held_fd = os.open(str(primary_lock_path), os.O_CREAT | os.O_RDWR)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    get_connection_calls = 0
    run_all_jobs_calls = 0
    job = _job_for_tests("state-pa-expenditures")

    def fake_get_connection(**overrides: object) -> _FakeConnection:
        nonlocal get_connection_calls
        get_connection_calls += 1
        return _FakeConnection()

    def fake_run_all_jobs(
        connection,
        jobs,
        dry_run,
        force,
        execution_origin,
        on_result,
        stop_on_failure=False,
        on_heartbeat=None,
    ):
        nonlocal run_all_jobs_calls
        run_all_jobs_calls += 1
        assert jobs == [job]
        assert execution_origin == "legacy_unknown"
        return [_success_result(job.key)]

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(runner, "run_all_jobs", fake_run_all_jobs)

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", job.key])
    finally:
        os.close(held_fd)

    assert exit_code == 0
    assert get_connection_calls == 1
    assert run_all_jobs_calls == 1
    captured = capsys.readouterr()
    assert "Another refresh runner is already active" not in captured.err


def test_main_blocks_same_key_on_contended_per_key_lock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    primary_lock_path = _redirect_runner_lock_paths(monkeypatch, tmp_path)
    job = _job_for_tests("state-pa-contributions")
    held_lock_path = tmp_path / "civibus-refresh-runner-state-pa-contributions.lock"
    held_fd = os.open(str(held_lock_path), os.O_CREAT | os.O_RDWR)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(
        runner, "get_connection", lambda **overrides: (_ for _ in ()).throw(AssertionError("unexpected db open"))
    )
    monkeypatch.setattr(
        runner,
        "run_all_jobs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected job execution")),
    )

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", job.key])
    finally:
        os.close(held_fd)

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("Another refresh runner is already active")
    assert str(_expected_key_lock_path(primary_lock_path, job.key)) in captured.err


def test_main_blocks_partial_overlap_on_any_contended_per_key_lock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    primary_lock_path = _redirect_runner_lock_paths(monkeypatch, tmp_path)
    jobs = [_job_for_tests("state-ny-expenditures"), _job_for_tests("state-pa-expenditures")]
    held_lock_path = tmp_path / "civibus-refresh-runner-state-pa-expenditures.lock"
    held_fd = os.open(str(held_lock_path), os.O_CREAT | os.O_RDWR)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    get_connection_calls = 0
    run_all_jobs_calls = 0

    def fake_get_connection(**overrides: object) -> _FakeConnection:
        nonlocal get_connection_calls
        get_connection_calls += 1
        return _FakeConnection()

    def fake_run_all_jobs(*args: object, **kwargs: object) -> list[runner.RefreshRunResult]:
        nonlocal run_all_jobs_calls
        run_all_jobs_calls += 1
        return [_success_result(job.key) for job in jobs]

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "get_connection", fake_get_connection)
    monkeypatch.setattr(runner, "run_all_jobs", fake_run_all_jobs)

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", "state-"])
    finally:
        os.close(held_fd)

    assert exit_code == 2
    assert get_connection_calls == 0
    assert run_all_jobs_calls == 0
    captured = capsys.readouterr()
    assert captured.err.startswith("Another refresh runner is already active")
    assert str(_expected_key_lock_path(primary_lock_path, "state-pa-expenditures")) in captured.err


def test_main_acquires_key_locks_in_deterministic_sorted_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    primary_lock_path = _redirect_runner_lock_paths(monkeypatch, tmp_path)
    jobs = [
        _job_for_tests("state-ny-expenditures"),
        _job_for_tests("state-wa-contributions"),
        _job_for_tests("state-pa-expenditures"),
        _job_for_tests("state-wa-contributions"),
    ]
    lock_attempts: list[Path] = []
    acquired_fds: list[int] = []

    def fake_acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int | None:
        lock_attempts.append(lock_path)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        acquired_fds.append(fd)
        return fd

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "_acquire_runner_lock", fake_acquire_runner_lock)
    monkeypatch.setattr(runner, "get_connection", lambda **overrides: _FakeConnection())
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: [_success_result(job.key) for job in jobs])

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", "state-"])
    finally:
        for fd in acquired_fds:
            try:
                os.close(fd)
            except OSError:
                pass

    assert exit_code == 0
    assert lock_attempts == [
        _expected_key_lock_path(primary_lock_path, "state-ny-expenditures"),
        _expected_key_lock_path(primary_lock_path, "state-pa-expenditures"),
        _expected_key_lock_path(primary_lock_path, "state-wa-contributions"),
    ]


def test_main_falls_back_to_tempdir_key_locks_for_whole_invocation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    primary_base_lock_path = tmp_path / "civibus-refresh-runner.lock"
    fallback_base_lock_path = tmp_path / "fallback" / "civibus-refresh-runner-10001.lock"
    jobs = [_job_for_tests("state-pa-expenditures"), _job_for_tests("state-wa-contributions")]
    lock_attempts: list[Path] = []
    acquired_fds: list[int] = []
    fallback_base_lock_path.parent.mkdir()

    def fake_acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int | None:
        lock_attempts.append(lock_path)
        if lock_path == _expected_key_lock_path(primary_base_lock_path, "state-pa-expenditures"):
            raise PermissionError("cannot create primary lock root")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        acquired_fds.append(fd)
        return fd

    monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", primary_base_lock_path)
    monkeypatch.setattr(runner, "_fallback_runner_lock_path", lambda: fallback_base_lock_path)
    monkeypatch.setattr(runner, "_acquire_runner_lock", fake_acquire_runner_lock)
    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "get_connection", lambda **overrides: _FakeConnection())
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: [_success_result(job.key) for job in jobs])

    try:
        exit_code = runner.main(["--scope", "all", "--job-key-prefix", "state-"])
    finally:
        for fd in acquired_fds:
            try:
                os.close(fd)
            except OSError:
                pass

    assert exit_code == 0
    assert lock_attempts == [
        _expected_key_lock_path(primary_base_lock_path, "state-pa-expenditures"),
        _expected_key_lock_path(fallback_base_lock_path, "state-pa-expenditures"),
        _expected_key_lock_path(fallback_base_lock_path, "state-wa-contributions"),
    ]
    captured = capsys.readouterr()
    assert captured.err.count("Refresh runner using fallback lock") == 1


@pytest.mark.parametrize("failure_mode", ["contended", "setup-error"])
def test_main_releases_earlier_key_locks_when_later_acquisition_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_mode: str,
) -> None:
    primary_lock_path = _redirect_runner_lock_paths(monkeypatch, tmp_path)
    fallback_lock_path = tmp_path / "fallback" / "civibus-refresh-runner-10001.lock"
    primary_first_lock_path = _expected_key_lock_path(primary_lock_path, "state-pa-contributions")
    primary_second_lock_path = _expected_key_lock_path(primary_lock_path, "state-wa-contributions")
    fallback_first_lock_path = _expected_key_lock_path(fallback_lock_path, "state-pa-contributions")
    fallback_second_lock_path = _expected_key_lock_path(fallback_lock_path, "state-wa-contributions")
    jobs = [_job_for_tests("state-pa-contributions"), _job_for_tests("state-wa-contributions")]
    returned_fds: list[int] = []
    lock_attempts: list[Path] = []

    def fake_acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int | None:
        lock_attempts.append(lock_path)
        if lock_path == primary_first_lock_path:
            fd = _acquire_runner_lock(lock_path)
            assert fd is not None
            returned_fds.append(fd)
            return fd
        if lock_path == primary_second_lock_path and failure_mode == "contended":
            return None
        if lock_path == primary_second_lock_path:
            raise PermissionError("cannot create second primary lock")
        if lock_path == fallback_first_lock_path and failure_mode == "setup-error":
            reacquired_primary_fd = _acquire_runner_lock(primary_first_lock_path)
            assert reacquired_primary_fd is not None
            os.close(reacquired_primary_fd)
            fd = _acquire_runner_lock(lock_path)
            assert fd is not None
            returned_fds.append(fd)
            return fd
        if lock_path == fallback_second_lock_path and failure_mode == "setup-error":
            raise PermissionError("cannot create second fallback lock")
        raise AssertionError(f"unexpected lock path: {lock_path}")

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "_acquire_runner_lock", fake_acquire_runner_lock)
    monkeypatch.setattr(
        runner, "get_connection", lambda **overrides: (_ for _ in ()).throw(AssertionError("unexpected db open"))
    )
    monkeypatch.setattr(
        runner,
        "run_all_jobs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected job execution")),
    )

    exit_code = runner.main(["--scope", "all", "--job-key-prefix", "state-"])

    assert exit_code == 2
    expected_attempts = [primary_first_lock_path, primary_second_lock_path]
    paths_to_reacquire = [primary_first_lock_path]
    if failure_mode == "setup-error":
        expected_attempts.extend([fallback_first_lock_path, fallback_second_lock_path])
        paths_to_reacquire.append(fallback_first_lock_path)
    assert lock_attempts == expected_attempts

    reacquired_fds = [_acquire_runner_lock(lock_path) for lock_path in paths_to_reacquire]
    try:
        assert all(fd is not None for fd in reacquired_fds)
    finally:
        for fd in reacquired_fds:
            if fd is not None:
                os.close(fd)
        for fd in returned_fds:
            try:
                os.close(fd)
            except OSError:
                pass


def test_job_key_lock_path_naming_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    base_lock_path = tmp_path / "civibus-refresh-runner.lock"
    fallback_base_lock_path = tmp_path / "civibus-refresh-runner-10001.lock"
    mapper = getattr(runner, "_runner_lock_path_for_job_key", None)
    assert mapper is not None, "runner must expose one production mapper for key-scoped lock paths"

    plain_path = mapper(base_lock_path, "state-wa-contributions")
    fallback_path = mapper(fallback_base_lock_path, "state-wa-contributions")
    punctuated_path = mapper(base_lock_path, "state/wa contributions")
    alternate_punctuated_path = mapper(base_lock_path, "state wa/contributions")

    assert plain_path == tmp_path / "civibus-refresh-runner-state-wa-contributions.lock"
    assert fallback_path == tmp_path / "civibus-refresh-runner-10001-state-wa-contributions.lock"
    generated_paths = (plain_path, fallback_path, punctuated_path, alternate_punctuated_path)
    assert all(re.fullmatch(r"[A-Za-z0-9._-]+", path.name) for path in generated_paths)
    assert punctuated_path != alternate_punctuated_path


def test_job_key_lock_path_truncation_keeps_digest_and_filesystem_safe_name(tmp_path: Path) -> None:
    base_lock_path = tmp_path / "civibus-refresh-runner.lock"
    mapper = getattr(runner, "_runner_lock_path_for_job_key", None)
    assert mapper is not None, "runner must expose one production mapper for key-scoped lock paths"

    common_prefix = "state-" + ("a" * 300)
    first_path = mapper(base_lock_path, f"{common_prefix}-contributions")
    second_path = mapper(base_lock_path, f"{common_prefix}-expenditures")

    assert first_path.parent == tmp_path
    assert second_path.parent == tmp_path
    assert first_path != second_path
    assert len(first_path.name) <= 255
    assert len(second_path.name) <= 255
    assert re.fullmatch(r"[A-Za-z0-9._-]+", first_path.name)
    assert re.fullmatch(r"[A-Za-z0-9._-]+", second_path.name)


def test_acquire_lock_returns_none_after_bounded_wait_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_RUNNER_LOCK_POLL_SECONDS", 0.01)

    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test.lock"
        with pytest.raises(ValueError, match="wait_seconds must be finite"):
            _acquire_runner_lock(lock_path, wait_seconds=float("inf"))

        holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        started_at = time.monotonic()
        waiter_fd = _acquire_runner_lock(lock_path, wait_seconds=0.1)
        waited_seconds = time.monotonic() - started_at

        assert waiter_fd is None
        assert waited_seconds >= 0.1

        os.close(holder_fd)


def test_acquire_lock_succeeds_once_the_holder_releases_within_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_RUNNER_LOCK_POLL_SECONDS", 0.01)

    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test.lock"
        holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        release_timer = threading.Timer(0.2, lambda: os.close(holder_fd))
        release_timer.start()
        try:
            waiter_fd = _acquire_runner_lock(lock_path, wait_seconds=10.0)
        finally:
            release_timer.join()

        assert waiter_fd is not None
        os.close(waiter_fd)


def test_acquire_lock_does_not_wait_by_default() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test.lock"
        holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        started_at = time.monotonic()
        assert _acquire_runner_lock(lock_path) is None
        assert time.monotonic() - started_at < 0.5

        os.close(holder_fd)


def _run_main_against_contended_key_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    job: runner.RefreshJob,
    lock_wait_seconds_seen: list[float],
) -> Path:
    """Drive main() against a key lock that is unopenable on the primary base and held on the fallback.

    Returns the fallback key lock path the contention message is expected to name.
    """
    primary_base_lock_path = tmp_path / "civibus-refresh-runner.lock"
    fallback_base_lock_path = tmp_path / "fallback" / "civibus-refresh-runner-10001.lock"
    primary_key_lock_path = _expected_key_lock_path(primary_base_lock_path, job.key)
    fallback_key_lock_path = _expected_key_lock_path(fallback_base_lock_path, job.key)

    def fake_acquire_runner_lock(lock_path: Path, wait_seconds: float = 0.0) -> int | None:
        if lock_path == primary_key_lock_path:
            raise PermissionError("cannot create /var/lock")
        assert lock_path == fallback_key_lock_path
        lock_wait_seconds_seen.append(wait_seconds)
        return None

    monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", primary_base_lock_path)
    monkeypatch.setattr(runner, "_fallback_runner_lock_path", lambda: fallback_base_lock_path)
    monkeypatch.setattr(runner, "_acquire_runner_lock", fake_acquire_runner_lock)
    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(
        runner, "get_connection", lambda **overrides: (_ for _ in ()).throw(AssertionError("unexpected db open"))
    )
    return fallback_key_lock_path


def test_main_contention_message_names_the_fallback_lock_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    job = _job_for_tests("state-pa-expenditures")
    lock_wait_seconds_seen: list[float] = []

    fallback_key_lock_path = _run_main_against_contended_key_lock(
        monkeypatch,
        tmp_path,
        job,
        lock_wait_seconds_seen,
    )
    exit_code = runner.main(["--scope", "all", "--job-key-prefix", job.key])

    assert exit_code == 2
    assert lock_wait_seconds_seen == [0.0]
    captured = capsys.readouterr()
    assert f"Another refresh runner is already active (lock: {fallback_key_lock_path})" in captured.err


def test_main_forwards_lock_wait_seconds_to_lock_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    job = _job_for_tests("state-pa-expenditures")
    lock_wait_seconds_seen: list[float] = []

    _run_main_against_contended_key_lock(
        monkeypatch,
        tmp_path,
        job,
        lock_wait_seconds_seen,
    )
    exit_code = runner.main(["--scope", "all", "--job-key-prefix", job.key, "--lock-wait-seconds", "45"])

    assert exit_code == 2
    assert lock_wait_seconds_seen == [45.0]
    capsys.readouterr()

    with pytest.raises(SystemExit) as infinite_wait_error:
        runner.main(["--scope", "all", "--job-key-prefix", job.key, "--lock-wait-seconds", "inf"])
    assert infinite_wait_error.value.code == 2

    with pytest.raises(SystemExit) as nan_wait_error:
        runner.main(["--scope", "all", "--job-key-prefix", job.key, "--lock-wait-seconds", "nan"])
    assert nan_wait_error.value.code == 2

    captured = capsys.readouterr()
    assert captured.err.count("--lock-wait-seconds must be a finite number") == 2
    assert lock_wait_seconds_seen == [45.0]
