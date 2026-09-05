"""Contract test for the interpreter `start` re-execs its wrapper under.

The detached wrapper is a re-exec of infra/scripts/detached_runner.sh itself.
Resolving that re-exec through PATH hands the wrapper to whichever `bash`
happens to come first, which need not be the one running the runner. The runner
therefore re-execs through `${BASH}` -- the absolute path of its own running
interpreter -- and this module owns that proof for both session-isolating
launch paths, plus the contract that stock macOS Bash 3.2 can complete the
readiness handshake.

These live beside rather than inside tests/infra/test_detached_runner.py only
because that module is already at the repository's file-size ceiling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.infra.detached_runner_helpers import (
    SCRIPT_PATH,
    _json_stdout,
    _observed_process_identity,
    _status,
    _stop_if_running,
    _terminate_recorded_processes,
    _write_executable,
)

# Every launch path the runner can take to isolate a wrapper's session, keyed by
# the environment value that selects it. The setsid path needs a stub because no
# stock macOS ships setsid; the runner would otherwise silently fall through to
# the python3 launcher and this module would prove one path twice.
_FORCE_PYTHON_SESSION_VALUES = ("0", "1")


def _runner_interpreter() -> str:
    """Return the absolute bash the runner itself will be invoked under.

    Resolved before PATH is shadowed, so it names the working interpreter the
    shadowing stub defers to rather than the stub.
    """
    interpreter = shutil.which("bash")
    assert interpreter is not None, "a bash on PATH is required to run the runner"
    return interpreter


def _write_recording_bash(stub_bin: Path, interpreter: str, invocation_log: Path) -> None:
    """Install a `bash` that records its arguments before deferring to `interpreter`.

    The stub passes the invocation through rather than failing it, so a PATH
    re-exec and an interpreter re-exec produce an identical working wrapper and
    the recorded arguments are the only thing that distinguishes them. It also
    reproduces the `argv[0]` a PATH lookup leaves behind -- the bare word
    `bash`, not a path -- which is what makes the wrapper's recorded process
    identity name the interpreter that actually ran it.
    """
    _write_executable(
        stub_bin / "bash",
        f"""#!{sys.executable}
import os
import sys

with open({str(invocation_log)!r}, "a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")
os.execv({interpreter!r}, ["bash", *sys.argv[1:]])
""",
    )


def _write_session_isolating_setsid(stub_bin: Path) -> None:
    """Install the setsid this host lacks, so the setsid launch path is reachable.

    `execvp` is deliberate: it resolves through PATH exactly as the real setsid
    does, so a runner that asks for a bare `bash` still gets the shadowing stub.
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


def _wrapper_invocations(invocation_log: Path) -> list[str]:
    if not invocation_log.exists():
        return []
    return [line for line in invocation_log.read_text(encoding="utf-8").splitlines() if "__run_wrapper" in line]


@pytest.mark.parametrize("force_python_session", _FORCE_PYTHON_SESSION_VALUES)
def test_start_reexecs_the_wrapper_under_the_runners_own_interpreter(tmp_path: Path, force_python_session: str) -> None:
    interpreter = _runner_interpreter()
    job_root = tmp_path / "jobs"
    job_name = f"wrapper_interpreter_{force_python_session}"
    job_dir = job_root / job_name
    stub_bin = tmp_path / "shadow_bin"
    stub_bin.mkdir()
    invocation_log = tmp_path / "path_bash_invocations.log"
    _write_recording_bash(stub_bin, interpreter, invocation_log)
    if force_python_session == "0":
        _write_session_isolating_setsid(stub_bin)

    # Invoked by absolute path so the shadowing stub governs only the re-execs
    # the runner performs, never the runner itself.
    start = subprocess.run(
        [
            interpreter,
            str(SCRIPT_PATH),
            "start",
            job_name,
            "--",
            # Long enough that the payload cannot exit on its own between
            # `start` returning and the assertions below; teardown stops it.
            "sleep",
            "30",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={
            **os.environ,
            "DETACHED_RUNNER_ROOT": str(job_root),
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": force_python_session,
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    try:
        assert start.returncode == 0, start.stderr
        assert _wrapper_invocations(invocation_log) == []
        wrapper_pid = _json_stdout(start)["pid"]
        assert _observed_process_identity(wrapper_pid).startswith(f"{interpreter} {SCRIPT_PATH} __run_wrapper ")
        assert _status(job_root, job_name)["alive"] is True
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)


def test_start_reaches_readiness_under_stock_macos_bash_3_2(tmp_path: Path) -> None:
    stock_bash = Path("/bin/bash")
    version = subprocess.run(
        [str(stock_bash), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if "version 3.2" not in version.stdout:
        pytest.skip("stock macOS Bash 3.2 is unavailable on this host")

    job_root = tmp_path / "jobs"
    job_name = "stock_macos_bash"
    job_dir = job_root / job_name
    start = subprocess.run(
        [str(stock_bash), str(SCRIPT_PATH), "start", job_name, "--", "sleep", "30"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={
            **os.environ,
            "DETACHED_RUNNER_ROOT": str(job_root),
            "DETACHED_RUNNER_FORCE_PYTHON_SESSION": "1",
        },
    )

    try:
        assert start.returncode == 0, start.stderr
        assert _status(job_root, job_name)["alive"] is True
    finally:
        _stop_if_running(job_root, job_name)
        _terminate_recorded_processes(job_dir)
