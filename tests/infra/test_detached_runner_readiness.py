from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.infra.detached_runner_budgets import (
    _READY_WINDOW_SECONDS,
    _READY_WINDOW_WALL_SECONDS,
    _assert_ready_window_budget_ordering,
)
from tests.infra.detached_runner_helpers import (
    _assert_recorded_wrapper_pgid,
    _json_stdout,
    _run_runner,
    _status,
    _stop_if_running,
    _terminate_exact_pid,
    _terminate_recorded_processes,
    _wait_for_file,
    _write_executable,
)


# How long the stub wrapper stays unready before isolating itself, so the runner
# has to keep polling and then still accept it. This is a *lower* budget, so it
# is a fraction of the window's nominal value (`attempts x interval`): nominal
# counts sleeps only and is therefore a lower bound on the window's wall time, so
# a delay under the nominal window is under the wall window too. 0.7 leaves ~30%
# of the window as slack for a wrapper that starts slowly under host load.
_UNREADY_WRAPPER_SECONDS = 0.7 * _READY_WINDOW_SECONDS
# The subprocess guard on `start` is an *upper* budget, so it starts from the
# window's wall estimate rather than its nominal value, plus an allowance for
# interpreter and process startup on both sides of the window.
_START_TIMEOUT_SECONDS = _assert_ready_window_budget_ordering(
    _READY_WINDOW_WALL_SECONDS + 4.0, readiness_delay=_UNREADY_WRAPPER_SECONDS
)


def _assert_cleanup_receipt_matches_empty_child(job_dir: Path, wrapper_pid: int) -> None:
    receipt = (job_dir / "cleanup_receipt").read_text(encoding="utf-8").splitlines()[0]
    assert receipt.split(" ") == [str(wrapper_pid), ""]


def test_wrapper_refuses_foreign_launch_approval_without_payload(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "foreign_wrapper_approval"
    job_dir.mkdir(parents=True)
    (job_dir / "log").touch()
    (job_dir / "progress.jsonl").touch()

    wrapper = subprocess.Popen(
        [
            "bash",
            str(Path("infra/scripts/detached_runner.sh")),
            "__run_wrapper",
            str(job_dir),
            "--require-launch-approval",
            "--",
            "sleep",
            "30",
        ],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert _wait_for_file(job_dir / "wrapper_ready") == f"{wrapper.pid} ready"
        (job_dir / "cleanup_requested").write_text(f"{wrapper.pid}\n", encoding="utf-8")
        (job_dir / "wrapper_ready").write_text(f"{os.getpid()} approved\n", encoding="utf-8")
        try:
            stdout, stderr = wrapper.communicate(timeout=2.0)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("wrapper did not bound its launch-approval wait") from exc

        assert wrapper.returncode != 0, stdout or stderr
        assert not (job_dir / "child_pid").exists()
        _assert_cleanup_receipt_matches_empty_child(job_dir, wrapper.pid)
    finally:
        if wrapper.poll() is None:
            _terminate_exact_pid(wrapper.pid)
            wrapper.wait(timeout=5.0)
        assert not (job_dir / "child_pid").exists()


def test_start_accepts_delayed_valid_isolated_wrapper(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "delayed_valid_wrapper"
    job_dir = job_root / job_name
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_executable(
        stub_bin / "setsid",
        f"""#!{sys.executable}
import os
import sys
import time

time.sleep({_UNREADY_WRAPPER_SECONDS})
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
""",
    )

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        # Long enough that the payload cannot exit on its own between `start`
        # returning and the liveness assertions below; teardown stops it.
        "sleep",
        "30",
        extra_env={
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0",
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        },
        timeout_seconds=_START_TIMEOUT_SECONDS,
    )

    try:
        assert start.returncode == 0, start.stderr
        wrapper_pid = _json_stdout(start)["pid"]
        status_payload = _status(job_root, job_name)
        assert status_payload["alive"] is True
        assert status_payload["exit_code"] is None
        _assert_recorded_wrapper_pgid(job_dir, wrapper_pid)
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)
