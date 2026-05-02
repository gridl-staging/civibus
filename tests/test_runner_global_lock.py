"""Tests for the refresh runner global flock-based mutual exclusion."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path

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
