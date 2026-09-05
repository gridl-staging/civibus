from __future__ import annotations

import atexit
import contextlib
import dataclasses
import functools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/detached_runner.sh"
PROBE_SCRIPT_PATH = REPO_ROOT / "infra/scripts/probe_load_progress.sh"
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PROCESS_TREE_LEVELS = ("child", "intermediate", "grandchild")
# Per-subshell PID probe for the fixture generator, portable to bash 3.2 (no
# BASHPID). Neither `$$` nor `BASHPID` fits here: `$$` names the one bash process
# and is identical at every nesting level, while `BASHPID` is unbound under bash
# 3.2 `set -u`. A direct child reliably observes the enclosing shell through
# `getppid()`. The generated script writes that result to a file because putting
# the probe in command substitution adds another shell process on bash 3.2 and
# reports that transient process instead of the fixture shell.
_SUBSHELL_PID_PROBE_COMMAND = f"{sys.executable!r} -c 'import os; print(os.getppid())'"
# Each PID the runner records is only verifiable against the identity file
# start wrote for that same process.
_RECORDED_PROCESS_METADATA = (
    ("child_pid", "child_process_identity"),
    ("pid", "process_identity"),
)


# `run_wrapper` in the runner, and the process-tree fixtures below, identify the
# shell they are running in through BASHPID, which bash only defines from 4.0.
# macOS still ships bash 3.2 as /bin/bash and puts it ahead of any newer install
# on the default PATH, so the interpreter these tests hand the runner has to be
# chosen rather than inherited.
_BASHPID_PROBE = 'printf %s "${BASHPID}"'


def _bash_defines_bashpid(bash_path: str) -> bool:
    """Report whether `bash_path` is an interpreter that defines BASHPID.

    A candidate that cannot be run at all -- `os.access` also grants X_OK to a
    directory named `bash`, and a wedged interpreter never answers -- is simply
    not such an interpreter. Answering False rather than raising keeps the
    search in `_supported_bash()` free to move on to the next PATH entry
    instead of aborting every test in this harness on one unusable candidate.
    """
    try:
        probe = subprocess.run(
            [bash_path, "-c", _BASHPID_PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0 and probe.stdout.strip().isdigit()


@functools.lru_cache(maxsize=None)
def _supported_bash() -> str:
    """Return the first bash on PATH that defines BASHPID."""
    for directory in os.get_exec_path():
        candidate = os.path.join(directory, "bash")
        if os.access(candidate, os.X_OK) and _bash_defines_bashpid(candidate):
            return candidate
    raise AssertionError("no bash on PATH defines BASHPID; the detached runner requires bash >= 4")


@functools.lru_cache(maxsize=None)
def _supported_bash_shim_directory() -> str:
    """Return a directory holding nothing but a `bash` link to `_supported_bash()`.

    The runner re-execs itself as plain `bash`, so a supported interpreter has
    to be reachable by name and not only by path. Prepending a directory that
    holds this one link puts it first without smuggling any other command onto
    the PATH of tests that build a deliberately stripped one.
    """
    directory = Path(tempfile.mkdtemp(prefix="detached_runner_bash_"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    (directory / "bash").symlink_to(_supported_bash())
    return str(directory)


def _path_with_supported_bash(path: str) -> str:
    return f"{_supported_bash_shim_directory()}{os.pathsep}{path}"


def _runner_env(job_root: Path, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Compose the environment every runner invocation runs under.

    The supported-bash shim is prepended after `extra_env` is merged, so a
    caller that replaces PATH to hide a launcher from the runner still leaves
    the runner an interpreter able to run it.
    """
    env = {**os.environ, "DETACHED_RUNNER_ROOT": str(job_root), **(extra_env or {})}
    env["PATH"] = _path_with_supported_bash(env["PATH"])
    return env


def _run_runner(
    job_root: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: float = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_supported_bash(), str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=_runner_env(job_root, extra_env),
        timeout=timeout_seconds,
    )


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


@dataclasses.dataclass(frozen=True)
class _StartedJob:
    """One runner job a test started, as `start` recorded it.

    Job root, job name and wrapper PID are always used together, so they travel
    as one value rather than as three parallel locals per caller.
    """

    job_root: Path
    job_name: str
    wrapper_pid: int

    @property
    def job_dir(self) -> Path:
        return self.job_root / self.job_name


def _start_job(job_root: Path, job_name: str, *command: str) -> _StartedJob:
    """Start `job_name` under `job_root` and return what `start` recorded.

    Asserting `start` succeeded here keeps a failed launch from being read
    later as the contract under test failing.
    """
    start = _run_runner(job_root, "start", job_name, "--", *command)
    assert start.returncode == 0, start.stderr
    return _StartedJob(job_root, job_name, _json_stdout(start)["pid"])


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
    """Observe `pid` running `identity` continuously for `hold_seconds`.

    The hold starts after the initial matching observation and ends only after
    another matching observation at or beyond the deadline. Identity continuity
    alone does not establish why a process later exits.
    """
    assert identity, f"PID {pid}: invalid expected identity"
    deadline: float | None = None
    while True:
        observed_identity = _observed_process_identity(pid)
        assert observed_identity, f"PID {pid}: identity unavailable"
        assert observed_identity == identity, (
            f"PID {pid}: identity mismatch; expected {identity!r}, observed {observed_identity!r}"
        )
        if deadline is None:
            deadline = time.monotonic() + hold_seconds
        elif time.monotonic() >= deadline:
            return
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


def _write_session_isolating_setsid_stub(stub_bin: Path) -> None:
    """Install a `setsid` that really starts a new session before exec.

    The real `setsid` is absent on macOS, so the runner's setsid launch branch
    is only reachable in tests through a stub. This one calls `os.setsid()` so
    the wrapper genuinely becomes a session and process-group leader, which is
    what the ownership assertions verify.
    """
    _write_executable(
        stub_bin / "setsid",
        f"""#!{sys.executable}
import os
import sys

os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
""",
    )


def _write_unset_bashpid_bash_env(path: Path) -> None:
    """Strip BASHPID from every bash the runner starts.

    Bash 3.2 has no BASHPID at all, so under the runner's `set -u` a read of it
    aborts the shell with `BASHPID: unbound variable`. Unsetting the variable
    drops its special attribute on bash 4+ too, so a read there aborts
    identically -- the same failure, not an approximation of it. That keeps the
    regression deterministic instead of depending on which bash the ambient
    PATH resolves.
    """
    path.write_text("unset BASHPID\n", encoding="utf-8")


def _isolated_path(stub_bin: Path, *command_names: str) -> str:
    for command_name in command_names:
        command_path = shutil.which(command_name, path=_path_with_supported_bash(os.environ["PATH"]))
        assert command_path is not None, f"required test command is unavailable: {command_name}"
        (stub_bin / command_name).symlink_to(command_path)
    return str(stub_bin)


def _runner_path_without_session_launcher(stub_bin: Path) -> str:
    return _isolated_path(stub_bin, "bash", "chmod", "date", "dirname", "mkdir", "mktemp", "mv", "ps", "rm", "sleep")


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


class _OwnedProcessReclaimer:
    """Teardown state for the test-owned processes started by one job under test.

    A success-path test proves its fixture processes are gone before it
    finishes, and a PID already proven gone is a number the kernel may have
    handed to somebody else, so signalling it afterwards is a blind signal at a
    stranger. Discarding each PID as its exit is proven leaves the `finally`
    reclaim signalling only the PIDs a *failing* test could have left running --
    the unrecorded descendants `_terminate_recorded_processes()` has no metadata
    to reach -- and delegating the rest to that owner keeps every recorded PID
    behind the identity check it already enforces.
    """

    def __init__(self, job_dir: Path) -> None:
        self._job_dir = job_dir
        self._live_pids: list[int] = []

    def track(self, *pids: int) -> None:
        """Record PIDs this test started and must reclaim if the body fails.

        A non-positive PID is refused rather than stored. `os.kill` reads 0 as
        the caller's whole process group and -1 as every process the user can
        signal, so one such number would turn `reclaim()` from an exact-PID
        teardown into a broadcast SIGKILL across a host that runs concurrent
        workers. PIDs reach here from parsing a fixture-written file, where
        `int("0")` parses just as happily as a real PID, so intake is the last
        point that can still tell the two apart. Every PID is checked before
        any is stored, so a refused batch leaves nothing behind to signal.
        """
        for pid in pids:
            assert pid > 0, f"reclaim tracks exact PIDs only; {pid} would signal beyond this test"
        for pid in pids:
            if pid not in self._live_pids:
                self._live_pids.append(pid)

    def discard_proven_dead(self, pid: int) -> None:
        """Drop `pid` from direct cleanup because its exit has been proven."""
        if pid in self._live_pids:
            self._live_pids.remove(pid)

    def confirm_exited(self, pid: int, *, timeout_seconds: float = 5.0) -> None:
        """Prove `pid` exited, then stop treating it as a PID to signal."""
        _wait_for_pid_to_exit(pid, timeout_seconds=timeout_seconds)
        self.discard_proven_dead(pid)

    def reclaim(self) -> None:
        """Signal the still-tracked PIDs, then sweep the recorded ones.

        SIGKILL rather than SIGTERM: the tracked set exists to catch a fixture
        left running by a failed body, and several of those fixtures trap TERM
        precisely so the runner has to escalate.
        """
        for pid in reversed(self._live_pids):
            _kill_exact_pid(pid)
        self._live_pids.clear()
        _terminate_recorded_processes(self._job_dir)


@contextlib.contextmanager
def _reclaiming_test_owned_processes(job_dir: Path) -> Iterator[_OwnedProcessReclaimer]:
    """Reclaim the block's test-owned and recorded processes however it exits."""
    reclaimer = _OwnedProcessReclaimer(job_dir)
    try:
        yield reclaimer
    finally:
        reclaimer.reclaim()


def _assert_recorded_wrapper_pgid(job_dir: Path, wrapper_pid: int) -> None:
    recorded_pgid = int((job_dir / "pgid").read_text(encoding="utf-8").strip())
    assert recorded_pgid == _observed_pgid(wrapper_pid)
    assert recorded_pgid == wrapper_pid


def _assert_start_and_wait_report_terminal_contract(
    job_root: Path, job_name: str, extra_env: dict[str, str] | None = None
) -> None:
    """Drive one job from `start` through `wait` and pin the whole terminal payload.

    Sole owner of the start-through-wait known-answer contract, so the launch
    branch a caller selects is the only thing that varies between the ambient
    launcher and the forced ones. The fixture sleeps long enough that the
    wrapper is still alive when the process-group ownership is checked; a
    short-lived wrapper would already have exited and `_observed_pgid` would
    report nothing to compare against. Omitting `extra_env` exercises whichever
    launcher the ambient environment resolves.
    """
    job_dir = job_root / job_name
    start = _run_runner(
        job_root, "start", job_name, "--", *_fixture_command(exit_code=7, sleep_seconds="3.0"), extra_env=extra_env
    )
    try:
        assert start.returncode == 0, start.stderr
        start_payload = _json_stdout(start)
        assert start_payload["job"] == job_name
        assert start_payload["alive"] is True
        assert start_payload["exit_code"] is None
        assert UTC_TIMESTAMP.match(start_payload["started_at"])
        _assert_recorded_wrapper_pgid(job_dir, start_payload["pid"])

        wait = _run_runner(
            job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "10", timeout_seconds=20
        )
        assert wait.returncode == 7, wait.stderr
        assert _json_stdout(wait) == {
            "job": job_name,
            "pid": start_payload["pid"],
            "alive": False,
            "exit_code": 7,
            "started_at": (job_dir / "started_at").read_text(encoding="utf-8").strip(),
            "last_log_line": "fixture final log",
            "progress": {"phase": "finished", "rows": 2},
        }
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


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

    Naming the whole contract in one expression, at the point where the stale
    state is planted, keeps `_assert_stop_refused_without_signaling()` down to
    a signature a reader can hold in their head.

    `expect_wrapper_alive` selects which state the recorded wrapper PID must be
    in, and both settings assert positively rather than skipping a check. The
    metadata-corruption refusals leave a live wrapper that must survive the
    refusal untouched; the stale-wrapper refusals fire precisely because the
    wrapper is already gone, so there `expect_wrapper_alive=False` proves the
    dead-target precondition the branch under test depends on.
    """

    job: _StartedJob
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
    job = expectation.job
    scratch_dir = job.job_root.parent
    kill_log = scratch_dir / f"{job.job_name}_stop_kill.log"
    bash_env = scratch_dir / f"{job.job_name}_stop_bash_env"
    _write_kill_logging_bash_env(bash_env, kill_log)

    refused = _run_runner(
        job.job_root, "stop", job.job_name, extra_env={"BASH_ENV": str(bash_env), **(extra_env or {})}
    )
    assert refused.returncode == 4
    assert expectation.expected_reason in refused.stderr
    # Signal delivery is asynchronous, so a control that still reads as running
    # cannot on its own rule out a signal already in flight. The kill log is the
    # deterministic half of the proof: it records every `kill` the refusal path
    # invoked, at the moment of the call rather than after its effect lands.
    assert not kill_log.exists(), f"refusal path signalled: {kill_log.read_text(encoding='utf-8')}"
    wrapper_pid = job.wrapper_pid
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
        "PATH": _path_with_supported_bash(f"{stub_bin}{os.pathsep}{os.environ['PATH']}"),
        "DETACHED_RUNNER_JOB_DIR": str(job_dir),
        "DETACHED_RUNNER_PROGRESS_FILE": str(progress_file),
        "PSQL_STUB_COUNT": str(count),
    }
    return subprocess.run(
        [_supported_bash(), str(PROBE_SCRIPT_PATH), table, port],
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


def _fixture_command(*, exit_code: int, sleep_seconds: str = "0.3", release_path: Path | None = None) -> list[str]:
    completion_wait = (
        f"while not os.path.exists({str(release_path)!r}):\n    time.sleep(0.05)"
        if release_path is not None
        else f"time.sleep({sleep_seconds})"
    )
    script = f"""
import json
import os
import sys
import time

progress_path = os.environ["DETACHED_RUNNER_PROGRESS_FILE"]
print("fixture stdout start", flush=True)
with open(progress_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"phase": "started", "rows": 1}}) + "\\n")
{completion_wait}
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
  local current_pid current_pid_path="${{tree_dir}}/${{level}}.current_pid"
  if [[ "${{term_resistant_levels}}" == *" ${{level}} "* ]]; then
    trap '' TERM
  fi
  {_SUBSHELL_PID_PROBE_COMMAND} > "${{current_pid_path}}"
  IFS= read -r current_pid < "${{current_pid_path}}"
  rm -f "${{current_pid_path}}"
  record_process "${{level}}" "${{current_pid}}"

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
    pids = {level: _wait_for_pid_file(tree_dir / f"{level}.pid") for level in PROCESS_TREE_LEVELS}
    # Distinct PIDs are the whole point of a multi-level tree: a degraded PID
    # idiom (e.g. `$$`) collapses every level onto the one bash PID and would
    # otherwise pass silently. The lineage check also rejects distinct but
    # transient command-substitution PIDs, which bash 3.2 can keep observable as
    # zombies long enough for process-group-only assertions to pass incorrectly.
    assert len(set(pids.values())) == len(PROCESS_TREE_LEVELS), f"process tree collapsed onto shared PIDs: {pids}"
    for parent_level, child_level in zip(PROCESS_TREE_LEVELS, PROCESS_TREE_LEVELS[1:]):
        observed_parent = subprocess.run(
            ["ps", "-p", str(pids[child_level]), "-o", "ppid="],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        parent_pid = observed_parent.stdout.strip()
        assert observed_parent.returncode == 0 and parent_pid, f"could not observe parent of {child_level}: {pids}"
        assert int(parent_pid) == pids[parent_level], f"process tree has incorrect lineage: {pids}"
    return pids


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
