"""Tests for the refresh runner global flock-based mutual exclusion."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path

import pytest

from core.refresh import job_builders
from core.refresh import runner
from core.refresh.runner import _acquire_runner_lock


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
) -> None:
    primary_lock_path = Path("/var/lock/civibus-refresh-runner.lock")
    fallback_lock_path = Path("/tmp/civibus-refresh-runner-test.lock")
    lock_attempts: list[Path] = []

    class FakeConnection:
        def close(self) -> None:
            pass

    def fake_acquire_runner_lock(lock_path: Path) -> int | None:
        lock_attempts.append(lock_path)
        if lock_path == primary_lock_path:
            raise PermissionError("cannot create /var/lock")
        return 123

    monkeypatch.setattr(runner, "_RUNNER_LOCK_PATH", primary_lock_path)
    monkeypatch.setattr(runner, "_fallback_runner_lock_path", lambda: fallback_lock_path)
    monkeypatch.setattr(runner, "_acquire_runner_lock", fake_acquire_runner_lock)
    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [])
    monkeypatch.setattr(runner, "get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        runner,
        "run_all_jobs",
        lambda connection, jobs, dry_run, force, on_result, stop_on_failure=False: [
            runner.RefreshRunResult(
                key="federal-congress-spine",
                status="success",
                metadata_updates=0,
                message="ok",
            )
        ],
    )

    exit_code = runner.main(["--scope", "all", "--job-key-prefix", "federal-congress-spine"])

    assert exit_code == 0
    assert lock_attempts == [primary_lock_path, fallback_lock_path]
    captured = capsys.readouterr()
    assert "Refresh runner using fallback lock" in captured.err
    assert "Another refresh runner is already active" not in captured.err
