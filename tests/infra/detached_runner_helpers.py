from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/detached_runner.sh"
PROBE_SCRIPT_PATH = REPO_ROOT / "infra/scripts/probe_load_progress.sh"
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PROCESS_TREE_LEVELS = ("child", "intermediate", "grandchild")
# Each PID the runner records is only verifiable against the identity file
# start wrote for that same process.
_RECORDED_PROCESS_METADATA = (
    ("child_pid", "child_process_identity"),
    ("pid", "process_identity"),
)


def _run_runner(
    job_root: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: float = 10,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DETACHED_RUNNER_ROOT": str(job_root), **(extra_env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout_seconds,
    )


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


def _wait_for_file(path: Path, *, timeout_seconds: float = 3.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _status(job_root: Path, job_name: str) -> dict:
    result = _run_runner(job_root, "status", job_name)
    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert set(payload) == {
        "job",
        "pid",
        "alive",
        "exit_code",
        "started_at",
        "last_log_line",
        "progress",
    }
    return payload


def _observed_pgid(pid: int) -> int | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pgid="],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    observed_pgid = result.stdout.strip()
    return int(observed_pgid) if observed_pgid else None


def _observed_process_identity(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.stdout.strip()


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid_file(path: Path, *, timeout_seconds: float = 5.0) -> int:
    return int(_wait_for_file(path, timeout_seconds=timeout_seconds))


def _wait_for_exit_without_reaping(control: subprocess.Popen[bytes]) -> None:
    """Block until `control` has exited, deliberately leaving it unreaped.

    `WNOWAIT` keeps the child in its zombie state so a test can observe the
    window in which a PID probe still reports a signalled process as alive.
    """
    os.waitid(os.P_PID, control.pid, os.WEXITED | os.WNOWAIT)


def _wait_for_pid_to_exit(pid: int, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_is_alive(pid) and not _observed_process_identity(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for PID {pid} to exit")


def _assert_pid_keeps_identity(pid: int, identity: str, *, hold_seconds: float = 1.0) -> None:
    """Assert `pid` still runs `identity` for the whole of `hold_seconds`.

    Process teardown is asynchronous, so a single check taken right after a
    teardown attempt also passes for a process that is already on its way out.
    Holding the check open for a window makes "this process was not signalled"
    an observation rather than an accident of timing.
    """
    deadline = time.monotonic() + hold_seconds
    while time.monotonic() < deadline:
        observed_identity = _observed_process_identity(pid)
        assert observed_identity == identity, f"PID {pid} stopped running its recorded command"
        time.sleep(0.05)


def _terminate_exact_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _kill_exact_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _write_kill_logging_bash_env(path: Path, kill_log: Path) -> None:
    path.write_text(
        f"""kill() {{
  printf '%s\\n' "$*" >> "{kill_log}"
  command kill "$@"
}}
""",
        encoding="utf-8",
    )


def _write_group_liveness_bash_env(path: Path, state_path: Path, live_checks: int) -> None:
    path.write_text(
        f"""kill() {{
  if [[ "${{1:-}}" == "-0" && "${{2:-}}" == "-${{DETACHED_RUNNER_TEST_PGID}}" ]]; then
    local checks=0
    if [[ -f "{state_path}" ]]; then
      IFS= read -r checks < "{state_path}" || true
    fi
    checks=$((checks + 1))
    printf '%s\\n' "${{checks}}" > "{state_path}"
    (( checks <= {live_checks} )) && return 0
    return 1
  fi
  if [[ "${{2:-}}" == "-${{DETACHED_RUNNER_TEST_PGID}}" && ( "${{1:-}}" == "-TERM" || "${{1:-}}" == "-KILL" ) ]]; then
    return 0
  fi
  command kill "$@"
}}
""",
        encoding="utf-8",
    )


def _isolated_path(stub_bin: Path, *command_names: str) -> str:
    for command_name in command_names:
        command_path = shutil.which(command_name)
        assert command_path is not None, f"required test command is unavailable: {command_name}"
        (stub_bin / command_name).symlink_to(command_path)
    return str(stub_bin)


def _runner_path_without_session_launcher(stub_bin: Path) -> str:
    return _isolated_path(
        stub_bin,
        "bash",
        "chmod",
        "date",
        "dirname",
        "mkdir",
        "mktemp",
        "mv",
        "ps",
        "rm",
        "sleep",
    )


def _terminate_recorded_processes(job_dir: Path) -> None:
    """SIGTERM each recorded PID that still carries the identity start recorded.

    Matching the observed command against the recorded identity is what makes
    this teardown safe under PID reuse; a bare liveness probe would also
    succeed for an unrelated process that inherited the PID. A missing or
    mismatched identity means the recorded PID can no longer be proven ours, so
    nothing is signalled.
    """
    for pid_name, identity_name in _RECORDED_PROCESS_METADATA:
        pid_path = job_dir / pid_name
        identity_path = job_dir / identity_name
        if not pid_path.exists() or not identity_path.exists():
            continue
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        if _observed_process_identity(pid) == identity_path.read_text(encoding="utf-8").strip():
            _terminate_exact_pid(pid)


def _assert_recorded_wrapper_pgid(job_dir: Path, wrapper_pid: int) -> None:
    recorded_pgid = int((job_dir / "pgid").read_text(encoding="utf-8").strip())
    assert recorded_pgid == _observed_pgid(wrapper_pid)
    assert recorded_pgid == wrapper_pid


def _assert_control_is_running(control: subprocess.Popen[bytes]) -> None:
    """Assert the owned control process has not been signalled.

    `poll()` reaps the child and surfaces the signal that killed it. A PID
    probe cannot: a terminated-but-unreaped child stays a zombie whose PID
    `os.kill(pid, 0)` still resolves, so a liveness check built on the PID
    alone would pass after the runner had already killed the control process.
    """
    returncode = control.poll()
    assert returncode is None, f"control process {control.pid} was signalled (returncode {returncode})"


@dataclasses.dataclass(frozen=True)
class _StopRefusalExpectation:
    """The fail-closed `stop` refusal one job must produce.

    Bundling the job under test with the refusal it must produce keeps
    `_assert_stop_refused_without_signaling()` down to a signature a reader can
    hold in their head, and lets a caller name the whole contract in one
    expression at the point where the stale state is planted.

    `expect_wrapper_alive` selects which state the recorded wrapper PID must be
    in, and both settings assert positively rather than skipping a check. The
    metadata-corruption refusals leave a live wrapper that must survive the
    refusal untouched; the stale-wrapper refusals fire precisely because the
    wrapper is already gone, so there `expect_wrapper_alive=False` proves the
    dead-target precondition the branch under test depends on.
    """

    job_root: Path
    job_name: str
    wrapper_pid: int
    expected_reason: str
    expect_wrapper_alive: bool = True


def _assert_stop_refused_without_signaling(
    expectation: _StopRefusalExpectation,
    *,
    control: subprocess.Popen[bytes],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Assert `stop` refuses as `expectation` describes and signals nothing.

    `control` is required rather than optional: a no-signal proof that can be
    skipped at the call site is not a proof. Pass the process from
    `_unrelated_control_process()`, which runs in its own session outside the
    job's group, so its survival rules out both a stray PID signal and a signal
    to a reused PGID.

    Returns the refusal so callers can assert additional stderr detail without
    re-running `stop` or restating the shared refusal contract.
    """
    # Scratch files sit beside the job root, which every caller places directly
    # under its own `tmp_path`, so each test gets its own kill log without
    # having to route a scratch directory through this contract.
    scratch_dir = expectation.job_root.parent
    kill_log = scratch_dir / f"{expectation.job_name}_stop_kill.log"
    bash_env = scratch_dir / f"{expectation.job_name}_stop_bash_env"
    _write_kill_logging_bash_env(bash_env, kill_log)

    refused = _run_runner(
        expectation.job_root,
        "stop",
        expectation.job_name,
        extra_env={"BASH_ENV": str(bash_env), **(extra_env or {})},
    )
    assert refused.returncode == 4
    assert expectation.expected_reason in refused.stderr
    # Signal delivery is asynchronous, so a control that still reads as running
    # cannot on its own rule out a signal already in flight. The kill log is the
    # deterministic half of the proof: it records every `kill` the refusal path
    # invoked, at the moment of the call rather than after its effect lands.
    assert not kill_log.exists(), f"refusal path signalled: {kill_log.read_text(encoding='utf-8')}"
    wrapper_pid = expectation.wrapper_pid
    if expectation.expect_wrapper_alive:
        assert _pid_is_alive(wrapper_pid)
    else:
        assert not _pid_is_alive(wrapper_pid) and not _observed_process_identity(wrapper_pid)
    _assert_control_is_running(control)
    return refused


def _reused_pgid_stand_in(control: subprocess.Popen[bytes], *, wrapper_pid: int) -> int:
    """Return the control process's real PGID for use as stale job metadata.

    `_unrelated_control_process()` starts a session leader, so its PGID equals
    its own PID and leads a group the job under test does not own. Recording
    that number as a job's process group makes a regression that signals stale
    metadata kill a process the test owns and can observe — something an
    invented group number could never detect.
    """
    reused_pgid = _observed_pgid(control.pid)
    assert reused_pgid == control.pid, "control process must lead its own process group"
    assert reused_pgid != wrapper_pid, "reused PGID must not name the group the job owns"
    return reused_pgid


def _assert_no_ownership_metadata(job_dir: Path) -> None:
    assert not (job_dir / "process_identity").exists()
    assert not (job_dir / "pgid").exists()


def _run_probe(
    *,
    job_dir: Path,
    progress_file: Path,
    stub_bin: Path,
    table: str,
    port: str,
    count: int,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        "DETACHED_RUNNER_JOB_DIR": str(job_dir),
        "DETACHED_RUNNER_PROGRESS_FILE": str(progress_file),
        "PSQL_STUB_COUNT": str(count),
    }
    return subprocess.run(
        ["bash", str(PROBE_SCRIPT_PATH), table, port],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )


def _stop_if_running(job_root: Path, job_name: str) -> None:
    result = _run_runner(job_root, "status", job_name)
    if result.returncode != 0:
        return
    payload = _json_stdout(result)
    if payload["alive"]:
        _run_runner(job_root, "stop", job_name)
        _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "5")


def _fixture_command(*, exit_code: int, sleep_seconds: str = "0.3") -> list[str]:
    script = f"""
import json
import os
import sys
import time

progress_path = os.environ["DETACHED_RUNNER_PROGRESS_FILE"]
print("fixture stdout start", flush=True)
with open(progress_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"phase": "started", "rows": 1}}) + "\\n")
time.sleep({sleep_seconds})
with open(progress_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"phase": "finished", "rows": 2}}) + "\\n")
print("fixture final log", flush=True)
sys.exit({exit_code})
"""
    return [sys.executable, "-c", script]


def _process_group_fixture_command(
    tree_dir: Path,
    *,
    levels: tuple[str, ...],
    term_resistant_levels: tuple[str, ...] = (),
    child_pid_path: Path | None = None,
    sleep_seconds: str = "300",
) -> list[str]:
    tree_dir.mkdir(parents=True, exist_ok=True)
    script_path = tree_dir / "process_group_fixture.sh"
    level_values = " ".join(levels)
    term_resistant_values = f" {' '.join(term_resistant_levels)} "
    child_pid_value = "" if child_pid_path is None else str(child_pid_path)
    _write_executable(
        script_path,
        f"""#!/usr/bin/env bash
set -euo pipefail
tree_dir={str(tree_dir)!r}
child_pid_path={child_pid_value!r}
term_resistant_levels={term_resistant_values!r}
levels=({level_values})

record_process() {{
  local level="$1"
  local pid="$2"
  ps -p "${{pid}}" -o pgid= | tr -d '[:space:]' > "${{tree_dir}}/${{level}}.pgid"
  printf '%s\n' "${{pid}}" > "${{tree_dir}}/${{level}}.pid"
  if [[ "${{level}}" == "child" && -n "${{child_pid_path}}" ]]; then
    printf '%s\n' "${{pid}}" > "${{child_pid_path}}"
  fi
}}

run_level() {{
  local index="$1"
  local level="${{levels[$index]}}"
  if [[ "${{term_resistant_levels}}" == *" ${{level}} "* ]]; then
    trap '' TERM
  fi
  record_process "${{level}}" "${{BASHPID}}"

  local next_index=$((index + 1))
  if (( next_index < ${{#levels[@]}} )); then
    run_level "${{next_index}}" &
    wait
  else
    sleep {sleep_seconds}
  fi
}}

run_level 0
""",
    )
    return ["bash", str(script_path)]


def _signal_resistant_fixture(child_pid_path: Path, *, sleep_seconds: str = "30.0") -> list[str]:
    tree_dir = child_pid_path.parent / f"{child_pid_path.stem}_process_group"
    return _process_group_fixture_command(
        tree_dir,
        levels=("child",),
        term_resistant_levels=("child",),
        child_pid_path=child_pid_path,
        sleep_seconds=sleep_seconds,
    )


def _term_resistant_grandchild_fixture(tree_dir: Path) -> list[str]:
    return _process_group_fixture_command(
        tree_dir,
        levels=("child", "grandchild"),
        term_resistant_levels=("grandchild",),
    )


def _process_tree_fixture_command(tree_dir: Path) -> list[str]:
    return _process_group_fixture_command(tree_dir, levels=PROCESS_TREE_LEVELS)


def _wait_for_process_tree(tree_dir: Path) -> dict[str, int]:
    return {level: _wait_for_pid_file(tree_dir / f"{level}.pid") for level in PROCESS_TREE_LEVELS}


@contextlib.contextmanager
def _unrelated_control_process() -> Iterator[subprocess.Popen[bytes]]:
    """Run a long-lived process in its own session for the block's duration.

    `start_new_session=True` makes the control a session leader, so its PGID
    equals its own PID and is shared with no job under test. That also makes it
    a usable stand-in for a reused process group: a test can record the
    control's real PGID as stale job metadata and prove the runner never
    signals it. Owning the SIGKILL and reap here keeps the teardown contract in
    one place: an assertion failure inside the block can never leak a
    300-second sleeper onto this shared host.
    """
    control = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        yield control
    finally:
        # Kill only a control that is still running: signalling an already
        # terminated child would mask the case these tests exist to catch.
        # Reap unconditionally so no zombie outlives the block.
        if control.poll() is None:
            _kill_exact_pid(control.pid)
        control.wait(timeout=10)
