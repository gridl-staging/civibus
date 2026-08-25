"""Contract tests for the start, wait, status, and progress-probe paths of
infra/scripts/detached_runner.sh.

The `run_stop()` contracts live in tests/infra/test_detached_runner_stop.py.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests.infra.detached_runner_budgets import (
    _READY_WINDOW_WALL_SECONDS,
    _assert_ready_window_budget_ordering,
    _declared_shell_constant_text,
    _shell_library_source,
)
from tests.infra.detached_runner_helpers import (
    SCRIPT_PATH,
    UTC_TIMESTAMP,
    _assert_no_ownership_metadata,
    _assert_recorded_wrapper_pgid,
    _assert_start_and_wait_report_terminal_contract,
    _fixture_command,
    _json_stdout,
    _kill_exact_pid,
    _observed_process_identity,
    _pid_is_alive,
    _run_probe,
    _run_runner,
    _runner_path_without_session_launcher,
    _signal_resistant_fixture,
    _status,
    _stop_if_running,
    _supported_bash,
    _terminate_exact_pid,
    _terminate_recorded_processes,
    _wait_for_file,
    _wait_for_pid_file,
    _wait_for_pid_to_exit,
    _write_executable,
    _write_kill_logging_bash_env,
    _write_session_isolating_setsid_stub,
    _write_unset_bashpid_bash_env,
)

_STOP_CADENCE_CONSTANTS = ("STOP_POLLS_PER_SECOND", "DEFAULT_STOP_GRACE_SECONDS")
# The exact operator-visible duplicate-start refusals, pinned in full so the
# runner keeps one wording per case instead of near-copies that can drift.
_SURVIVING_CHILD_REFUSAL = (
    "surviving child PID {pid} is still recorded and alive; terminate that PID "
    "or remove the stale job directory before retrying"
)
_UNVERIFIABLE_CHILD_REFUSAL = (
    "recorded child PID {pid} is still observable but its identity cannot be "
    "verified; inspect that PID or remove the stale job directory before retrying"
)


def test_probe_load_progress_appends_row_count_deltas_under_current_job(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "probe_job"
    progress_file = job_dir / "progress.jsonl"
    stub_bin = tmp_path / "bin"
    job_dir.mkdir(parents=True)
    stub_bin.mkdir()
    psql_stub = stub_bin / "psql"
    psql_stub.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"${PSQL_STUB_COUNT}\"\n",
        encoding="utf-8",
    )
    psql_stub.chmod(0o755)

    samples = [12, 12, 17]
    for count in samples:
        result = _run_probe(
            job_dir=job_dir,
            progress_file=progress_file,
            stub_bin=stub_bin,
            table="cf.transactions",
            port="5456",
            count=count,
        )
        assert result.returncode == 0, result.stderr

    payloads = [json.loads(line) for line in progress_file.read_text(encoding="utf-8").splitlines()]
    assert [payload["source"] for payload in payloads] == ["psql_row_count_probe"] * 3
    assert [payload["rows_total"] for payload in payloads] == samples
    assert [payload["rows_delta"] for payload in payloads] == [12, 0, 5]
    assert [payload["detail"] for payload in payloads] == [
        {"table": "cf.transactions", "port": 5456},
        {"table": "cf.transactions", "port": 5456},
        {"table": "cf.transactions", "port": 5456},
    ]
    assert all(UTC_TIMESTAMP.match(payload["ts"]) for payload in payloads)
    assert (job_dir / "probe_cf_transactions.previous_rows_total").read_text(encoding="utf-8") == "17\n"


def test_start_status_and_wait_report_terminal_metadata(tmp_path: Path) -> None:
    """Pin the terminal contract on whichever launcher the ambient PATH resolves."""
    _assert_start_and_wait_report_terminal_contract(tmp_path / "jobs", "known_exit")


def test_wrapper_writes_receipt_for_direct_normal_child_exit(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "normal_wrapper_exit"
    job_dir.mkdir(parents=True)
    (job_dir / "log").touch()
    (job_dir / "progress.jsonl").touch()

    result = subprocess.run(
        [
            # `run_wrapper` reads BASHPID, which bash only defines from 4.0. An
            # inherited `bash` is 3.2 on macOS, where `set -u` aborts the EXIT
            # trap on the unbound name -- silently, because the trap runs after
            # `exit` has already fixed the status this test asserts on.
            _supported_bash(),
            str(SCRIPT_PATH),
            "__run_wrapper",
            str(job_dir),
            "--",
            *_fixture_command(exit_code=0, sleep_seconds="0.1"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    # The EXIT trap is the only wrapper path that can still write here after the
    # status is set, so an empty stderr is what proves it ran to completion
    # rather than dying on an unbound name.
    assert result.stderr == "", result.stderr
    assert not (job_dir / "cleanup_receipt").exists(), "no cleanup was requested of this wrapper"
    assert (job_dir / "exit_code").read_text(encoding="utf-8") == "0\n"
    assert (job_dir / "child_pid").read_text(encoding="utf-8").strip()
    assert "fixture final log" in (job_dir / "log").read_text(encoding="utf-8")


def test_wrapper_writes_receipt_and_terminates_child_on_cleanup_signal(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "signaled_wrapper"
    job_dir.mkdir(parents=True)
    (job_dir / "log").touch()
    (job_dir / "progress.jsonl").touch()

    wrapper = subprocess.Popen(
        [
            # Same BASHPID requirement as the normal-exit wrapper test above.
            _supported_bash(),
            str(SCRIPT_PATH),
            "__run_wrapper",
            str(job_dir),
            "--",
            *_fixture_command(exit_code=0, sleep_seconds="5.0"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = int(_wait_for_file(job_dir / "child_pid"))

    try:
        os.kill(wrapper.pid, signal.SIGTERM)
        stderr = wrapper.communicate(timeout=10)[1]
        assert wrapper.returncode == 143, stderr
        assert stderr == "", stderr
        assert (job_dir / "exit_code").read_text(encoding="utf-8") == "143\n"

        child_status = subprocess.run(
            ["ps", "-p", str(child_pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert child_status.stdout.strip() == ""
    finally:
        if wrapper.poll() is None:
            wrapper.terminate()
            wrapper.wait(timeout=10)
        subprocess.run(["kill", "-TERM", str(child_pid)], capture_output=True, check=False, timeout=10)


def test_wait_timeout_is_distinct_and_does_not_kill_job(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "timeout_job"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="5.0"))
    assert start.returncode == 0, start.stderr
    start_payload = _json_stdout(start)

    timeout = _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "1")
    assert timeout.returncode == 124, timeout.stderr
    timeout_payload = _json_stdout(timeout)
    assert timeout_payload["job"] == job_name
    assert timeout_payload["pid"] == start_payload["pid"]
    assert timeout_payload["alive"] is True
    assert timeout_payload["exit_code"] is None

    status_payload = _status(job_root, job_name)
    assert status_payload["alive"] is True
    assert status_payload["exit_code"] is None
    _stop_if_running(job_root, job_name)


def test_start_python_session_fallback_keeps_job_alive_after_launcher_exits(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "python_session_detach"
    job_dir = job_root / job_name

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_fixture_command(exit_code=0, sleep_seconds="3.0"),
        extra_env={"DETACHED_RUNNER_FORCE_PYTHON_SESSION": "1"},
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


def test_start_python_session_handles_unset_bashpid(tmp_path: Path) -> None:
    """The python-session launch branch must survive a shell without BASHPID.

    Bash 3.2 — still the system bash on macOS — has no BASHPID, so a wrapper
    that identifies itself with it dies on an unbound variable before it can
    ready, and `start` refuses a job whose command would have run fine.
    """
    bash_env = tmp_path / "unset_bashpid_env"
    _write_unset_bashpid_bash_env(bash_env)

    _assert_start_and_wait_report_terminal_contract(
        tmp_path / "jobs",
        "python_session_unset_bashpid",
        {"DETACHED_RUNNER_FORCE_PYTHON_SESSION": "1", "BASH_ENV": str(bash_env)},
    )


def test_start_setsid_branch_handles_unset_bashpid(tmp_path: Path) -> None:
    """The setsid launch branch carries the same BASHPID-free requirement."""
    bash_env = tmp_path / "unset_bashpid_env"
    _write_unset_bashpid_bash_env(bash_env)
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_session_isolating_setsid_stub(stub_bin)

    _assert_start_and_wait_report_terminal_contract(
        tmp_path / "jobs",
        "setsid_unset_bashpid",
        {
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0",
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
            "BASH_ENV": str(bash_env),
        },
    )


def test_start_setsid_branch_records_isolated_wrapper_ownership(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "setsid_session_detach"
    job_dir = job_root / job_name
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    _write_session_isolating_setsid_stub(stub_bin)

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_fixture_command(exit_code=0, sleep_seconds="3.0"),
        extra_env={
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0",
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )
    try:
        assert start.returncode == 0, start.stderr
        wrapper_pid = _json_stdout(start)["pid"]
        _assert_recorded_wrapper_pgid(job_dir, wrapper_pid)
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


def test_start_terminates_nonisolated_wrapper_and_withholds_ownership_metadata(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "nonisolated_wrapper"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    path = _runner_path_without_session_launcher(stub_bin)
    _write_executable(stub_bin / "setsid", '#!/usr/bin/env bash\nexec "$@"\n')

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_signal_resistant_fixture(child_pid_path),
        extra_env={"DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0", "PATH": path},
    )

    try:
        assert start.returncode != 0
        assert "isolated process group" in start.stderr
        _assert_no_ownership_metadata(job_dir)
        assert not child_pid_path.exists()
        assert not (job_dir / "child_pid").exists()
        wrapper_pid = int((job_dir / "pid").read_text(encoding="utf-8").strip())
        assert _observed_process_identity(wrapper_pid) == ""
    finally:
        _terminate_recorded_processes(job_dir)


def test_start_refuses_delayed_wrapper_without_signaling_unverified_pid(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "delayed_wrapper"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    stub_bin = tmp_path / "bin"
    bash_env = tmp_path / "bash_env"
    kill_log = tmp_path / "kill.log"
    stub_bin.mkdir()
    path = _runner_path_without_session_launcher(stub_bin)
    _write_executable(
        stub_bin / "setsid",
        """#!/usr/bin/env bash
directory="$4"
while true; do
  state=""
  if [[ -f "${directory}/wrapper_ready" ]]; then
    IFS= read -r state < "${directory}/wrapper_ready" || true
  fi
  [[ "${state}" == "$$ refused" ]] && exec "$@"
  sleep 0.05
done
""",
    )
    _write_kill_logging_bash_env(bash_env, kill_log)

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_signal_resistant_fixture(child_pid_path),
        extra_env={
            "BASH_ENV": str(bash_env),
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0",
            "PATH": path,
        },
        # Upper budget, so the window term is the window's *wall* estimate, not
        # its nominal value. Only that term is derived: the refusal path also
        # runs the cleanup handshake after the window closes, and the whole path
        # measured 7.84s against a ~5.6s wall window, leaving ~2.2s of cleanup
        # plus process startup. 6.0s carries that measurement with headroom for
        # shared-host load.
        timeout_seconds=_assert_ready_window_budget_ordering(_READY_WINDOW_WALL_SECONDS + 6.0),
    )

    wrapper_pid = int((job_dir / "pid").read_text(encoding="utf-8").strip())
    assert start.returncode != 0
    assert "did not become ready" in start.stderr
    assert "failed to receive cleanup proof" not in start.stderr
    _assert_no_ownership_metadata(job_dir)
    assert not child_pid_path.exists()
    assert not (job_dir / "child_pid").exists()
    assert _observed_process_identity(wrapper_pid) == ""
    kill_lines = kill_log.read_text(encoding="utf-8").splitlines() if kill_log.exists() else []
    assert f"-TERM {wrapper_pid}" not in kill_lines
    assert f"-KILL {wrapper_pid}" not in kill_lines


def test_start_cleans_up_wrapper_when_process_identity_is_unobservable(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "unobservable_identity"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    stub_bin = tmp_path / "bin"
    bash_env = tmp_path / "bash_env"
    kill_log = tmp_path / "kill.log"
    real_ps = shutil.which("ps")
    assert real_ps is not None
    stub_bin.mkdir()
    _write_kill_logging_bash_env(bash_env, kill_log)
    _write_executable(
        stub_bin / "ps",
        f"""#!/usr/bin/env bash
for arg in "$@"; do
  if [[ "$arg" == "command=" ]]; then
    exit 0
  fi
done
exec {real_ps} "$@"
""",
    )

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_signal_resistant_fixture(child_pid_path),
        extra_env={
            "BASH_ENV": str(bash_env),
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "1",
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    try:
        assert start.returncode != 0
        assert "could not observe process identity" in start.stderr
        assert "failed to terminate unobservable wrapper" not in start.stderr
        _assert_no_ownership_metadata(job_dir)
        assert not child_pid_path.exists()
        assert not (job_dir / "child_pid").exists()
        wrapper_pid = int((job_dir / "pid").read_text(encoding="utf-8").strip())
        assert _observed_process_identity(wrapper_pid) == ""
        kill_lines = kill_log.read_text(encoding="utf-8").splitlines()
        assert f"-TERM {wrapper_pid}" not in kill_lines
        assert f"-KILL {wrapper_pid}" not in kill_lines
    finally:
        _terminate_recorded_processes(job_dir)


def test_start_refuses_when_no_session_isolating_launcher_is_available(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "missing_session_launcher"
    job_dir = job_root / job_name
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    path = _runner_path_without_session_launcher(stub_bin)
    _write_executable(stub_bin / "nohup", '#!/usr/bin/env bash\nexec "$@"\n')

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_fixture_command(exit_code=0, sleep_seconds="5.0"),
        extra_env={"DETACHED_RUNNER_FORCE_PYTHON_SESSION": "0", "PATH": path},
    )

    try:
        assert start.returncode != 0
        assert "no session-isolating launcher is available" in start.stderr
        _assert_no_ownership_metadata(job_dir)
        if (job_dir / "pid").exists():
            wrapper_pid = int((job_dir / "pid").read_text(encoding="utf-8").strip())
            assert _observed_process_identity(wrapper_pid) == ""
    finally:
        _terminate_recorded_processes(job_dir)


def test_wait_fails_closed_when_wrapper_identity_is_stale(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "child_identity_fallback"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="5.0"))
    assert start.returncode == 0, start.stderr

    _wait_for_file(job_root / job_name / "child_process_identity")
    identity_path = job_root / job_name / "process_identity"
    recorded_identity = identity_path.read_text(encoding="utf-8")
    identity_path.write_text("stale-wrapper-identity\n", encoding="utf-8")

    wait = _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "1")
    assert wait.returncode == 1, wait.stderr
    wait_payload = _json_stdout(wait)
    assert wait_payload["alive"] is False
    assert wait_payload["exit_code"] is None

    identity_path.write_text(recorded_identity, encoding="utf-8")
    _stop_if_running(job_root, job_name)


def test_start_refuses_duplicate_live_job(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "duplicate_job"
    first = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert first.returncode == 0, first.stderr

    duplicate = _run_runner(job_root, "start", job_name, "--", sys.executable, "-c", "print('replacement')")
    assert duplicate.returncode == 3
    assert "already running" in duplicate.stderr
    _stop_if_running(job_root, job_name)


def test_status_does_not_report_alive_from_child_when_wrapper_is_gone(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "dead_wrapper_live_child"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    start = _run_runner(job_root, "start", job_name, "--", *_signal_resistant_fixture(child_pid_path))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]
    child_pid = _wait_for_pid_file(child_pid_path)

    try:
        _kill_exact_pid(wrapper_pid)
        _wait_for_pid_to_exit(wrapper_pid)
        assert _pid_is_alive(child_pid)

        status_payload = _status(job_root, job_name)
        assert status_payload["alive"] is False
        assert status_payload["exit_code"] is None

        stop = _run_runner(job_root, "stop", job_name)
        assert stop.returncode == 4
        assert "wrapper PID" in stop.stderr
        assert "no longer observable" in stop.stderr
    finally:
        _terminate_exact_pid(child_pid)
        _terminate_recorded_processes(job_dir)


@pytest.mark.parametrize(
    ("child_identity_state", "expected_reason"),
    [
        ("matching", _SURVIVING_CHILD_REFUSAL),
        ("missing", _UNVERIFIABLE_CHILD_REFUSAL),
        ("stale", _UNVERIFIABLE_CHILD_REFUSAL),
    ],
)
def test_start_refuses_when_wrapper_died_but_recorded_child_is_observable(
    tmp_path: Path,
    child_identity_state: str,
    expected_reason: str,
) -> None:
    job_root = tmp_path / "jobs"
    job_name = "dead_wrapper_duplicate_start"
    job_dir = job_root / job_name
    child_pid_path = tmp_path / "child.pid"
    start = _run_runner(job_root, "start", job_name, "--", *_signal_resistant_fixture(child_pid_path))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]
    child_pid = _wait_for_pid_file(child_pid_path)
    recorded_child_pid_path = job_dir / "child_pid"
    child_identity_path = job_dir / "child_process_identity"
    _wait_for_file(child_identity_path)
    if child_identity_state == "missing":
        child_identity_path.unlink()
    elif child_identity_state == "stale":
        child_identity_path.write_text("stale-child-identity\n", encoding="utf-8")

    try:
        _kill_exact_pid(wrapper_pid)
        _wait_for_pid_to_exit(wrapper_pid)
        assert _pid_is_alive(child_pid)
        assert recorded_child_pid_path.read_text(encoding="utf-8").strip() == str(child_pid)

        duplicate = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0))
        assert duplicate.returncode == 3
        assert expected_reason.format(pid=child_pid) in duplicate.stderr
        assert recorded_child_pid_path.read_text(encoding="utf-8").strip() == str(child_pid)
        assert _pid_is_alive(child_pid)
    finally:
        _kill_exact_pid(child_pid)
        _terminate_recorded_processes(job_dir)


def test_start_ignores_recorded_child_pid_that_was_gone_at_identity_verdict(tmp_path: Path) -> None:
    """A gone child verdict must not be re-opened by a second PID observation."""
    job_root = tmp_path / "jobs"
    job_name = "gone_child_duplicate_start"
    job_dir = job_root / job_name
    stale_child_pid = "424242"
    ps_state = tmp_path / "child_ps_calls"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    ps_stub = stub_bin / "ps"
    real_ps = shutil.which("ps") or "/bin/ps"
    _write_executable(
        ps_stub,
        f"""#!/usr/bin/env bash
if [[ "$1" == "-p" && "$2" == "{stale_child_pid}" && "$3" == "-o" && "$4" == "command=" ]]; then
  calls=0
  if [[ -f "{ps_state}" ]]; then
    calls="$(<"{ps_state}")"
  fi
  printf '%s\n' "$((calls + 1))" > "{ps_state}"
  if (( calls == 0 )); then
    exit 0
  fi
  printf '%s\n' "reused process for stale child PID"
  exit 0
fi
exec "{real_ps}" "$@"
""",
    )
    job_dir.mkdir(parents=True)
    (job_dir / "child_pid").write_text(f"{stale_child_pid}\n", encoding="utf-8")
    (job_dir / "child_process_identity").write_text("original child identity\n", encoding="utf-8")

    start = _run_runner(
        job_root,
        "start",
        job_name,
        "--",
        *_fixture_command(exit_code=0, sleep_seconds="0.1"),
        extra_env={"PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"},
    )

    try:
        assert start.returncode == 0, start.stderr
        assert ps_state.read_text(encoding="utf-8").strip() == "1"
    finally:
        _terminate_recorded_processes(job_dir)


def test_status_and_wait_liveness_ignore_stop_only_pgid_metadata(tmp_path: Path) -> None:
    """Pin wrapper identity as the only liveness truth for `status` and `wait`.

    `pgid` exists so `stop` can prove it is signalling a group the wrapper still
    leads; it is not evidence of liveness. Routing the shared recorded-wrapper
    identity verdict through that stop-only metadata would report a job with an
    unreadable `pgid` as dead while its wrapper is demonstrably alive, and would
    make `wait` exit 1 on a running job instead of timing out.
    """
    job_root = tmp_path / "jobs"
    job_name = "pgid_independent_liveness"
    job_dir = job_root / job_name
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="5.0"))
    assert start.returncode == 0, start.stderr
    wrapper_pid = _json_stdout(start)["pid"]

    try:
        (job_dir / "pgid").unlink()

        status_payload = _status(job_root, job_name)
        assert status_payload["alive"] is True
        assert status_payload["exit_code"] is None
        assert _pid_is_alive(wrapper_pid)

        wait = _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "1")
        assert wait.returncode == 124, wait.stderr
        wait_payload = _json_stdout(wait)
        assert wait_payload["alive"] is True
        assert wait_payload["exit_code"] is None
    finally:
        _terminate_recorded_processes(job_dir)


def test_recorded_liveness_publishes_no_verdict_from_a_previous_call_after_a_terminal_receipt(
    tmp_path: Path,
) -> None:
    """A settled job must clear every global the recorded-process seam publishes.

    `recorded_process_is_alive()` returns before consulting the identity seam
    once `exit_code` exists, so anything it leaves behind is whatever the last
    call published. The PID, the verdict, and the refusal reason are one set
    describing one answer; leaving the reason set would hand the first caller
    that reads it a message about a different process.
    """
    job_dir = tmp_path / "settled_job"
    job_dir.mkdir()
    (job_dir / "exit_code").write_text("0\n", encoding="utf-8")
    (job_dir / "pid").write_text("1\n", encoding="utf-8")
    (job_dir / "process_identity").write_text("recorded wrapper identity\n", encoding="utf-8")

    probe = f"""
set -euo pipefail
job_root={shlex.quote(str(tmp_path))}
source {shlex.quote(str(SCRIPT_PATH.parent / "detached_runner_job_state_lib.sh"))}
source {shlex.quote(str(SCRIPT_PATH.parent / "detached_runner_ownership_lib.sh"))}
RECORDED_PROCESS_PID="pid-from-a-previous-call"
RECORDED_PROCESS_VERDICT="verdict-from-a-previous-call"
RECORDED_PROCESS_REFUSAL_REASON="reason-from-a-previous-call"
if recorded_process_is_alive {shlex.quote(str(job_dir))} wrapper; then
  echo "settled job reported alive" >&2
  exit 1
fi
printf 'pid=[%s]\nverdict=[%s]\nreason=[%s]\n' \
  "${{RECORDED_PROCESS_PID}}" "${{RECORDED_PROCESS_VERDICT}}" "${{RECORDED_PROCESS_REFUSAL_REASON}}"
"""
    result = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "pid=[]\nverdict=[]\nreason=[]\n"


def test_stop_cadence_constants_live_with_the_ownership_owner() -> None:
    """Guard where the stop cadence constants are declared, not what they hold.

    Retuning either window is a legitimate behaviour-only edit, so this asserts
    on the assignment site alone; pinning the values here would red a placement
    guard for a change that moved nothing.
    """
    runner_source = SCRIPT_PATH.read_text(encoding="utf-8")
    ownership_source = _shell_library_source("detached_runner_ownership_lib.sh")

    for name in _STOP_CADENCE_CONSTANTS:
        assignment = re.compile(rf"^{name}=", re.MULTILINE)
        assert not assignment.search(runner_source), f"{name} is declared in the runner, not its cadence owner"
        assert assignment.search(ownership_source), f"{name} is not declared by the ownership owner"


def test_usage_advertises_the_stop_grace_default_its_owner_declares(tmp_path: Path) -> None:
    """`--help` must quote the live constant rather than a copy of its value.

    The default is operator-visible, and its constant lives in another file, so
    a hardcoded copy here would go stale the moment the window is retuned.
    """
    declared = _declared_shell_constant_text("detached_runner_ownership_lib.sh", "DEFAULT_STOP_GRACE_SECONDS")

    result = _run_runner(tmp_path / "jobs", "--help")

    assert result.returncode == 0, result.stderr
    assert f"(default: {declared})" in result.stderr
