"""Contract tests for `run_stop()` in infra/scripts/detached_runner.sh.

Covers termination of the verified wrapper-led process group, every fail-closed
refusal that the ownership guard enforces, and stop/status idempotence after a job
reaches a terminal receipt. The start, wait, status, and progress-probe contracts
live in tests/infra/test_detached_runner.py; both files share
tests/infra/detached_runner_helpers.py as their single helper owner.
"""

from __future__ import annotations

import os
import shutil
import signal
from pathlib import Path

import pytest

from tests.infra.detached_runner_helpers import (
    _assert_control_is_running,
    _assert_pid_keeps_identity,
    _assert_recorded_wrapper_pgid,
    _assert_stop_refused_without_signaling,
    _fixture_command,
    _json_stdout,
    _kill_exact_pid,
    _observed_pgid,
    _pid_is_alive,
    _process_tree_fixture_command,
    _reused_pgid_stand_in,
    _run_runner,
    _signal_resistant_fixture,
    _status,
    _stop_if_running,
    _StopRefusalExpectation,
    _term_resistant_grandchild_fixture,
    _terminate_exact_pid,
    _terminate_recorded_processes,
    _unrelated_control_process,
    _wait_for_exit_without_reaping,
    _wait_for_file,
    _wait_for_pid_file,
    _wait_for_pid_to_exit,
    _wait_for_process_tree,
    _write_executable,
    _write_group_liveness_bash_env,
)


def test_control_liveness_proof_rejects_a_signalled_unreaped_control() -> None:
    """Guard the no-signal proof itself against zombie false positives.

    Every refusal test below concludes "nothing was signalled" from the control
    process still being alive. A PID probe cannot support that conclusion: a
    child killed but not yet reaped keeps its PID resolvable. This proves the
    shared assertion rejects exactly that state, so a regression that signals
    the control cannot pass as a refusal.
    """
    with _unrelated_control_process() as control:
        _assert_control_is_running(control)

        os.kill(control.pid, signal.SIGKILL)
        _wait_for_exit_without_reaping(control)
        assert _pid_is_alive(control.pid), "expected an unreaped zombie whose PID still resolves"

        with pytest.raises(AssertionError, match="was signalled"):
            _assert_control_is_running(control)


def test_recorded_process_teardown_requires_a_matching_recorded_identity(tmp_path: Path) -> None:
    """Prove the shared teardown signals only PIDs it can still prove are ours.

    `_terminate_recorded_processes()` is what the refusal tests fall back on
    once they have proved a recorded PID is gone, so its guard has to hold in
    both directions. It must refuse a recorded PID whose observed command no
    longer matches what start recorded — under PID reuse that number names
    somebody else — and it must still terminate one that does match. A guard
    that only ever skipped would pass this file's teardowns while quietly
    leaking every job process onto this shared host.
    """
    job_root = tmp_path / "jobs"
    job_name = "recorded_teardown_guard"
    job_dir = job_root / job_name
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="10.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]
    wrapper_identity_path = job_dir / "process_identity"
    child_identity_path = job_dir / "child_process_identity"
    recorded_identities: dict[Path, str] = {}

    try:
        _wait_for_file(child_identity_path)
        recorded_identities = {
            path: path.read_text(encoding="utf-8") for path in (wrapper_identity_path, child_identity_path)
        }
        for path in recorded_identities:
            path.write_text("definitely-not-the-recorded-command\n", encoding="utf-8")

        _terminate_recorded_processes(job_dir)
        # The wrapper only outlives its child, so holding its identity for a
        # window proves neither recorded PID was signalled — a single check here
        # would also pass for a wrapper already exiting on its child's TERM.
        _assert_pid_keeps_identity(wrapper_pid, recorded_identities[wrapper_identity_path].strip())

        for path, recorded_identity in recorded_identities.items():
            path.write_text(recorded_identity, encoding="utf-8")
        _terminate_recorded_processes(job_dir)
        _wait_for_pid_to_exit(wrapper_pid)
    finally:
        for path, recorded_identity in recorded_identities.items():
            path.write_text(recorded_identity, encoding="utf-8")
        _terminate_recorded_processes(job_dir)


def test_stop_refuses_when_recorded_process_identity_does_not_match(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "identity_guard"
    job_dir = job_root / job_name
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]

    identity_path = job_dir / "process_identity"
    recorded_identity = identity_path.read_text(encoding="utf-8")
    identity_path.write_text("definitely-not-the-recorded-command\n", encoding="utf-8")

    status_payload = _status(job_root, job_name)
    assert status_payload["alive"] is False
    assert status_payload["exit_code"] is None

    with _unrelated_control_process() as control:
        _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job_root=job_root,
                job_name=job_name,
                wrapper_pid=wrapper_pid,
                expected_reason="process identity mismatch",
            ),
            control=control,
        )

    identity_path.write_text(recorded_identity, encoding="utf-8")
    _stop_if_running(job_root, job_name)


def test_stop_kills_verified_group_when_term_does_not_finish(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "term_resistant"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    start = _run_runner(job_root, "start", job_name, "--", *_signal_resistant_fixture(child_pid_path))
    assert start.returncode == 0, start.stderr
    child_pid = _wait_for_pid_file(child_pid_path)

    try:
        stop = _run_runner(
            job_root,
            "stop",
            job_name,
            extra_env={"DETACHED_RUNNER_STOP_GRACE_SECONDS": "1"},
            timeout_seconds=4,
        )
        assert stop.returncode == 0, stop.stderr
        _wait_for_pid_to_exit(child_pid)

        status_payload = _status(job_root, job_name)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143
    finally:
        _kill_exact_pid(child_pid)
        _terminate_recorded_processes(job_dir)


def test_stop_writes_receipt_when_group_drains_after_kill_wait(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "kill_timeout_receipt"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    bash_env = tmp_path / "bash_env"
    liveness_state = tmp_path / "group_liveness_count"
    start = _run_runner(job_root, "start", job_name, "--", *_signal_resistant_fixture(child_pid_path))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]
    child_pid = _wait_for_pid_file(child_pid_path)
    _write_group_liveness_bash_env(bash_env, liveness_state, live_checks=40)

    try:
        stop = _run_runner(
            job_root,
            "stop",
            job_name,
            extra_env={
                "BASH_ENV": str(bash_env),
                "DETACHED_RUNNER_STOP_GRACE_SECONDS": "2",
                "DETACHED_RUNNER_TEST_PGID": str(wrapper_pid),
            },
            timeout_seconds=7,
        )
        assert stop.returncode == 0, stop.stderr
        status_payload = _json_stdout(stop)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143
        assert (job_dir / "exit_code").read_text(encoding="utf-8") == "143\n"
    finally:
        _kill_exact_pid(child_pid)
        _kill_exact_pid(wrapper_pid)
        _terminate_recorded_processes(job_dir)


def test_stop_kills_group_when_descendant_survives_term(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "term_resistant_grandchild"
    job_dir = job_root / job_name
    tree_dir = tmp_path / "tree"
    start = _run_runner(job_root, "start", job_name, "--", *_term_resistant_grandchild_fixture(tree_dir))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]
    child_pid = _wait_for_pid_file(tree_dir / "child.pid")
    grandchild_pid = _wait_for_pid_file(tree_dir / "grandchild.pid")

    try:
        _assert_recorded_wrapper_pgid(job_dir, wrapper_pid)
        recorded_pgid = int((job_dir / "pgid").read_text(encoding="utf-8").strip())
        assert int(_wait_for_file(tree_dir / "child.pgid")) == recorded_pgid
        assert int(_wait_for_file(tree_dir / "grandchild.pgid")) == recorded_pgid

        stop = _run_runner(
            job_root,
            "stop",
            job_name,
            extra_env={"DETACHED_RUNNER_STOP_GRACE_SECONDS": "1"},
            timeout_seconds=4,
        )
        assert stop.returncode == 0, stop.stderr
        _wait_for_pid_to_exit(child_pid)
        _wait_for_pid_to_exit(grandchild_pid)

        status_payload = _status(job_root, job_name)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] == 143
    finally:
        _kill_exact_pid(grandchild_pid)
        _kill_exact_pid(child_pid)
        _terminate_recorded_processes(job_dir)


@pytest.mark.parametrize("metadata_name", ["pid", "process_identity", "pgid"])
def test_stop_refuses_when_required_stop_metadata_is_missing(
    tmp_path: Path,
    metadata_name: str,
) -> None:
    job_root = tmp_path / "jobs"
    job_name = "missing_stop_metadata_guard"
    job_dir = job_root / job_name
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr
    # Capture the wrapper PID before mutating metadata: the "pid" case deletes
    # the only recorded copy, so cleanup cannot read it back afterwards.
    wrapper_pid = _json_stdout(start)["pid"]

    with _unrelated_control_process() as control:
        try:
            (job_dir / metadata_name).unlink()

            _assert_stop_refused_without_signaling(
                _StopRefusalExpectation(
                    job_root=job_root,
                    job_name=job_name,
                    wrapper_pid=wrapper_pid,
                    expected_reason="incomplete process metadata",
                ),
                control=control,
            )
        finally:
            _terminate_exact_pid(wrapper_pid)


def test_stop_refuses_when_recorded_pid_points_at_an_unrelated_live_process(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "reused_pid_guard"
    job_dir = job_root / job_name
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]

    with _unrelated_control_process() as control:
        try:
            # Stand-in for PID reuse: the recorded PID now names an unrelated
            # live process while the recorded identity still describes the
            # wrapper.
            (job_dir / "pid").write_text(f"{control.pid}\n", encoding="utf-8")

            _assert_stop_refused_without_signaling(
                _StopRefusalExpectation(
                    job_root=job_root,
                    job_name=job_name,
                    wrapper_pid=wrapper_pid,
                    expected_reason="process identity mismatch",
                ),
                control=control,
            )
        finally:
            _terminate_exact_pid(wrapper_pid)


def test_stop_refuses_when_recorded_pgid_does_not_match_wrapper_pid(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "recorded_pgid_guard"
    job_dir = job_root / job_name
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]

    with _unrelated_control_process() as control:
        # Stand-in for PGID reuse: record a process group that is real and live,
        # led by an unrelated session leader.
        reused_pgid = _reused_pgid_stand_in(control, wrapper_pid=wrapper_pid)
        (job_dir / "pgid").write_text(f"{reused_pgid}\n", encoding="utf-8")

        _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job_root=job_root,
                job_name=job_name,
                wrapper_pid=wrapper_pid,
                expected_reason=f"wrapper PID {wrapper_pid} no longer leads recorded process group {reused_pgid}",
            ),
            control=control,
        )
    _terminate_recorded_processes(job_dir)


def test_stop_refuses_when_observed_pgid_does_not_match_wrapper_pid(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "observed_pgid_guard"
    job_dir = job_root / job_name
    stub_bin = tmp_path / "bin"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]
    real_ps = shutil.which("ps")
    assert real_ps is not None
    stub_bin.mkdir()

    with _unrelated_control_process() as control:
        # The wrapper now appears to sit in a process group that is real and
        # live, led by an unrelated session leader.
        reused_pgid = _reused_pgid_stand_in(control, wrapper_pid=wrapper_pid)
        _write_executable(
            stub_bin / "ps",
            f"""#!/usr/bin/env bash
if [[ "$*" == "-p {wrapper_pid} -o pgid=" ]]; then
  printf '%s\\n' {reused_pgid}
  exit 0
fi
exec {real_ps} "$@"
""",
        )

        refused = _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job_root=job_root,
                job_name=job_name,
                wrapper_pid=wrapper_pid,
                expected_reason=f"wrapper PID {wrapper_pid} no longer leads recorded process group {wrapper_pid}",
            ),
            control=control,
            extra_env={"PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"},
        )
        assert f"observed PGID: {reused_pgid}" in refused.stderr
    _terminate_recorded_processes(job_dir)


def test_stop_terminates_owned_process_tree(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "process_tree_stop"
    job_dir = job_root / job_name
    tree_dir = tmp_path / "tree"
    owned_pids: dict[str, int] = {}

    with _unrelated_control_process() as control:
        try:
            start = _run_runner(job_root, "start", job_name, "--", *_process_tree_fixture_command(tree_dir))
            assert start.returncode == 0, start.stderr
            wrapper_pid = _json_stdout(start)["pid"]
            owned_pids = _wait_for_process_tree(tree_dir)
            _assert_recorded_wrapper_pgid(job_dir, wrapper_pid)

            recorded_pgid = int((job_dir / "pgid").read_text(encoding="utf-8").strip())
            for level, pid in owned_pids.items():
                assert _observed_pgid(pid) == recorded_pgid, level
                assert int((tree_dir / f"{level}.pgid").read_text(encoding="utf-8").strip()) == recorded_pgid
            assert _observed_pgid(control.pid) != recorded_pgid

            stop = _run_runner(job_root, "stop", job_name)
            assert stop.returncode == 0, stop.stderr

            for pid in owned_pids.values():
                _wait_for_pid_to_exit(pid)
            _assert_control_is_running(control)

            status_payload = _status(job_root, job_name)
            assert status_payload["alive"] is False
            assert status_payload["exit_code"] == 143
        finally:
            for pid in owned_pids.values():
                _terminate_exact_pid(pid)
            _terminate_recorded_processes(job_dir)


def test_stop_and_status_are_idempotent_after_termination(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "idempotent_stop"
    job_dir = job_root / job_name
    exit_code_path = job_dir / "exit_code"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="5.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]

    with _unrelated_control_process() as control:
        try:
            stop = _run_runner(job_root, "stop", job_name)
            assert stop.returncode == 0, stop.stderr
            assert exit_code_path.read_text(encoding="utf-8").strip() == "143"

            _assert_stop_refused_without_signaling(
                _StopRefusalExpectation(
                    job_root=job_root,
                    job_name=job_name,
                    wrapper_pid=wrapper_pid,
                    expected_reason=f"wrapper PID {wrapper_pid} is no longer observable",
                    expect_wrapper_alive=False,
                ),
                control=control,
            )
            # The refusal returns before write_stop_receipt_once(), so the
            # receipt recorded by the first stop must survive untouched.
            assert exit_code_path.read_text(encoding="utf-8").strip() == "143"

            for _ in range(2):
                status_payload = _status(job_root, job_name)
                assert status_payload["alive"] is False
                assert status_payload["exit_code"] == 143
        finally:
            # The refusal above proved this wrapper PID is gone, so signalling
            # it directly could only reach whatever inherited the number. The
            # shared teardown owner signals a recorded PID only while it still
            # carries its recorded identity.
            _terminate_recorded_processes(job_dir)


def test_stop_after_normal_completion_preserves_receipt(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "completed_job_stop"
    job_dir = job_root / job_name
    exit_code_path = job_dir / "exit_code"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="0.3"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]

    wait = _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "5")
    assert wait.returncode == 0, wait.stderr
    # `wait` returns as soon as the receipt appears, but the wrapper can still be
    # observable for a moment afterwards; stopping then would legitimately
    # succeed. Wait out the wrapper so the refusal below is deterministic.
    _wait_for_pid_to_exit(wrapper_pid)

    with _unrelated_control_process() as control:
        _assert_stop_refused_without_signaling(
            _StopRefusalExpectation(
                job_root=job_root,
                job_name=job_name,
                wrapper_pid=wrapper_pid,
                expected_reason=f"wrapper PID {wrapper_pid} is no longer observable",
                expect_wrapper_alive=False,
            ),
            control=control,
        )
        # A fail-closed refusal must never overwrite a genuine completion
        # receipt with the stop receipt's 143.
        assert exit_code_path.read_text(encoding="utf-8").strip() == "0"
