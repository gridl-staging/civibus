"""Contract tests for the canonical long-running ingest dispatch wrapper.

The wrapper at `infra/scripts/long_running_dispatch.sh` is owned by Stage 2 of the
`docs/howto/operations/long_running_ingest_discipline.md` spec. These tests freeze:

- Static contract (sources `env_lib.sh`, calls `load_civibus_env`, `set -euo pipefail`).
- Argument and filesystem validation (red paths).
- Lifecycle artifact schemas for `dispatch.json` and `closeout.json`.
- Atomic (`*.tmp`-then-rename) write semantics.
- Signal handling (SIGINT/SIGTERM produce an `interrupted` closeout).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_PATH = REPO_ROOT / "infra/scripts/long_running_dispatch.sh"
ENV_LIB_PATH = REPO_ROOT / "infra/scripts/env_lib.sh"

DISPATCH_ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]{7,63}$")
RFC3339_UTC_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
TERMINAL_STATUSES = {"succeeded", "failed", "interrupted"}


# ---------- helpers ----------


def _build_test_repo(tmp_path: Path) -> Path:
    """Mirror just enough of the repo so the wrapper resolves repo_root correctly."""
    scripts_dir = tmp_path / "infra" / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(ENV_LIB_PATH, scripts_dir / "env_lib.sh")
    shutil.copy(WRAPPER_PATH, scripts_dir / "long_running_dispatch.sh")
    (scripts_dir / "long_running_dispatch.sh").chmod(0o755)
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=test\n", encoding="utf-8")
    # env_lib.load_civibus_env refuses group/other-readable secret env files;
    # a real production .env holding POSTGRES_PASSWORD is 0600. Match that here so
    # the fixture exercises the wrapper contract instead of tripping the perms guard.
    (tmp_path / ".env").chmod(0o600)
    return tmp_path


def _run_dispatch(
    test_repo: Path,
    *args: str,
    env_overrides: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    proc_env = {k: v for k, v in os.environ.items()}
    proc_env["PATH"] = proc_env.get("PATH", "/usr/bin:/bin")
    if env_overrides:
        proc_env.update(env_overrides)
    return subprocess.run(
        ["bash", str(test_repo / "infra/scripts/long_running_dispatch.sh"), *args],
        cwd=test_repo,
        capture_output=True,
        text=True,
        check=False,
        env=proc_env,
        timeout=timeout,
    )


def _evidence_dir(test_repo: Path, artifact_id: str, dispatch_id: str) -> Path:
    return test_repo / "docs/reference/research/artifacts" / artifact_id / "hetzner" / dispatch_id


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _basic_args(
    artifact_id: str = "stage2_test",
    dispatch_id: str = "stage2-disp-001",
    probe_sql: str = "SELECT 1",
    wrapped: Sequence[str] | None = None,
) -> list[str]:
    if wrapped is None:
        wrapped = ["bash", "-c", "echo hello"]
    return [
        "--artifact-id",
        artifact_id,
        "--dispatch-id",
        dispatch_id,
        "--probe-sql",
        probe_sql,
        "--",
        *wrapped,
    ]


# ---------- static contract ----------


def test_long_running_dispatch_wrapper_exists_with_strict_shell_contract() -> None:
    assert WRAPPER_PATH.is_file(), "infra/scripts/long_running_dispatch.sh must exist (Stage 2 owner)"
    text = WRAPPER_PATH.read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env bash"), "wrapper must declare bash shebang"
    assert "set -euo pipefail" in text, "wrapper must use strict mode"
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in text, (
        "wrapper must compute script_dir like the rest of the family"
    )
    assert 'repo_root="$(cd "${script_dir}/../.." && pwd)"' in text, "wrapper must compute repo_root from script_dir"
    assert 'source "${script_dir}/env_lib.sh"' in text, "wrapper must source env_lib.sh, not reimplement env loading"
    assert "load_civibus_env" in text, "wrapper must call load_civibus_env (single env bootstrap path)"
    assert "load_env_assignments() {" not in text, "wrapper must not duplicate the parser inline"


def test_long_running_dispatch_wrapper_does_not_alter_runner_or_job_builders() -> None:
    text = WRAPPER_PATH.read_text(encoding="utf-8")
    assert "core/refresh/runner.py" not in text
    assert "core/refresh/job_builders.py" not in text
    assert "python -m core.refresh.runner" not in text


# ---------- argument validation (red paths) ----------


@pytest.fixture()
def test_repo(tmp_path: Path) -> Path:
    return _build_test_repo(tmp_path)


def test_wrapper_rejects_missing_artifact_id(test_repo: Path) -> None:
    result = _run_dispatch(
        test_repo,
        "--dispatch-id",
        "stage2-disp-001",
        "--probe-sql",
        "SELECT 1",
        "--",
        "bash",
        "-c",
        "echo hi",
    )
    assert result.returncode != 0
    assert "artifact-id" in (result.stdout + result.stderr).lower()


def test_wrapper_rejects_missing_dispatch_id(test_repo: Path) -> None:
    result = _run_dispatch(
        test_repo,
        "--artifact-id",
        "stage2_test",
        "--probe-sql",
        "SELECT 1",
        "--",
        "bash",
        "-c",
        "echo hi",
    )
    assert result.returncode != 0
    assert "dispatch-id" in (result.stdout + result.stderr).lower()


def test_wrapper_rejects_missing_probe_sql(test_repo: Path) -> None:
    result = _run_dispatch(
        test_repo,
        "--artifact-id",
        "stage2_test",
        "--dispatch-id",
        "stage2-disp-001",
        "--",
        "bash",
        "-c",
        "echo hi",
    )
    assert result.returncode != 0
    assert "probe-sql" in (result.stdout + result.stderr).lower()


def test_wrapper_rejects_missing_wrapped_command(test_repo: Path) -> None:
    result = _run_dispatch(
        test_repo,
        "--artifact-id",
        "stage2_test",
        "--dispatch-id",
        "stage2-disp-001",
        "--probe-sql",
        "SELECT 1",
        "--",
    )
    assert result.returncode != 0
    assert "wrapped" in (result.stdout + result.stderr).lower() or "command" in (result.stdout + result.stderr).lower()


def test_wrapper_rejects_empty_artifact_id(test_repo: Path) -> None:
    args = _basic_args(artifact_id="")
    result = _run_dispatch(test_repo, *args)
    assert result.returncode != 0


def test_wrapper_rejects_empty_probe_sql(test_repo: Path) -> None:
    args = _basic_args(probe_sql="")
    result = _run_dispatch(test_repo, *args)
    assert result.returncode != 0
    assert "probe-sql" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    "bad_id",
    [
        "abcdefg",  # only 7 chars total → fails {7,63} trailing constraint
        "ABCDEFGHIJ",  # uppercase
        "-bad-id-1",  # leading hyphen
        "bad id 12",  # spaces
        "nc-ie!001",  # special char
        "x" * 65,  # exceeds 64
    ],
)
def test_wrapper_rejects_invalid_dispatch_id(test_repo: Path, bad_id: str) -> None:
    # Sanity-check the cases the regex must reject so the test is honest.
    assert DISPATCH_ID_REGEX.match(bad_id) is None, f"test bug: {bad_id!r} unexpectedly matches the dispatch_id regex"
    args = _basic_args(dispatch_id=bad_id)
    result = _run_dispatch(test_repo, *args)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "dispatch-id" in combined.lower() or "dispatch_id" in combined.lower()


def test_wrapper_refuses_when_evidence_directory_cannot_be_created(
    test_repo: Path,
) -> None:
    # Plant a regular file where the evidence directory would be created so
    # `mkdir -p` fails. The wrapper must refuse to run rather than silently
    # writing artifacts somewhere unexpected.
    artifact_id = "blocked_artifact"
    dispatch_id = "blocked-disp-001"
    blocking_path = test_repo / "docs/reference/research/artifacts" / artifact_id
    blocking_path.parent.mkdir(parents=True)
    blocking_path.write_text("not a directory", encoding="utf-8")

    args = _basic_args(artifact_id=artifact_id, dispatch_id=dispatch_id)
    result = _run_dispatch(test_repo, *args)
    assert result.returncode != 0
    assert not _evidence_dir(test_repo, artifact_id, dispatch_id).exists()


# ---------- lifecycle: dispatch.json ----------


def test_dispatch_json_schema_on_successful_run(test_repo: Path) -> None:
    artifact_id = "schema_test"
    dispatch_id = "schema-test-001"
    probe_sql = "SELECT count(*) FROM raw.example"
    wrapped = ["bash", "-c", "echo first; echo second"]

    args = _basic_args(
        artifact_id=artifact_id,
        dispatch_id=dispatch_id,
        probe_sql=probe_sql,
        wrapped=wrapped,
    )
    result = _run_dispatch(test_repo, *args)
    assert result.returncode == 0, f"wrapped echo command should succeed; stderr={result.stderr}"

    evidence = _evidence_dir(test_repo, artifact_id, dispatch_id)
    dispatch_path = evidence / "dispatch.json"
    log_path = evidence / "dispatch.log"

    assert dispatch_path.is_file()
    assert log_path.is_file()
    # No stray .tmp left behind from atomic write.
    assert not (evidence / "dispatch.json.tmp").exists()
    assert not (evidence / "closeout.json.tmp").exists()

    payload = _read_json(dispatch_path)
    assert payload["schema_version"] == 1
    assert payload["dispatch_id"] == dispatch_id
    assert payload["artifact_id"] == artifact_id
    assert payload["probe_sql"] == probe_sql

    # wrapped_command is required and must reference the launched binary.
    assert isinstance(payload["wrapped_command"], str)
    assert payload["wrapped_command"], "wrapped_command must be non-empty"
    assert "bash" in payload["wrapped_command"]

    # host object
    host = payload["host"]
    assert isinstance(host, dict)
    assert host["hostname"]
    assert host["vm_ip"]
    assert host["worktree"].startswith("/")
    assert os.path.isabs(host["worktree"])

    # absolute path requirements
    assert os.path.isabs(payload["log_path"])
    assert os.path.isabs(payload["evidence_directory"])
    assert payload["evidence_directory"].endswith(
        f"/docs/reference/research/artifacts/{artifact_id}/hetzner/{dispatch_id}"
    )
    assert payload["log_path"].endswith("/dispatch.log")

    # RFC3339 UTC timestamp
    assert RFC3339_UTC_REGEX.match(payload["started_at_utc"]), payload["started_at_utc"]


def test_dispatch_json_uses_atomic_write(test_repo: Path) -> None:
    """No partial JSON; the file appears only once renamed from `*.tmp`."""
    artifact_id = "atomic_test"
    dispatch_id = "atomic-test-001"
    args = _basic_args(artifact_id=artifact_id, dispatch_id=dispatch_id)
    result = _run_dispatch(test_repo, *args)
    assert result.returncode == 0

    text = WRAPPER_PATH.read_text(encoding="utf-8")
    # The implementation must use a tmp-and-rename pattern. Static check makes
    # this contract enforceable independent of timing windows.
    assert "${dispatch_json_path}.tmp" in text, "dispatch.json must be written to a *.tmp sibling and renamed"
    assert "${closeout_json_path}.tmp" in text, "closeout.json must be written to a *.tmp sibling and renamed"
    # Rename step that turns *.tmp into the final file.
    assert 'mv "${tmp}" "${dispatch_json_path}"' in text
    assert 'mv "${tmp}" "${closeout_json_path}"' in text


# ---------- lifecycle: closeout.json ----------


def test_closeout_json_succeeded_on_zero_exit(test_repo: Path) -> None:
    artifact_id = "closeout_ok"
    dispatch_id = "closeout-ok-001"
    args = _basic_args(
        artifact_id=artifact_id,
        dispatch_id=dispatch_id,
        wrapped=["bash", "-c", "echo done"],
    )
    result = _run_dispatch(test_repo, *args)
    assert result.returncode == 0

    evidence = _evidence_dir(test_repo, artifact_id, dispatch_id)
    closeout = _read_json(evidence / "closeout.json")
    dispatch = _read_json(evidence / "dispatch.json")

    assert closeout["schema_version"] == 1
    assert closeout["dispatch_id"] == dispatch["dispatch_id"]
    assert closeout["terminal_status"] == "succeeded"
    assert closeout["exit_code"] == 0
    assert RFC3339_UTC_REGEX.match(closeout["finished_at_utc"]), closeout["finished_at_utc"]
    assert closeout["finished_at_utc"] >= dispatch["started_at_utc"]

    summary = closeout["summary"]
    assert summary["duration_seconds"] >= 0
    assert summary["log_bytes"] >= 0
    # The wrapped command emitted "done\n", at least 5 bytes.
    assert summary["log_bytes"] >= 5
    assert RFC3339_UTC_REGEX.match(summary["last_log_timestamp_utc"]), summary["last_log_timestamp_utc"]


def test_closeout_json_failed_on_nonzero_exit(test_repo: Path) -> None:
    artifact_id = "closeout_fail"
    dispatch_id = "closeout-fail-001"
    args = _basic_args(
        artifact_id=artifact_id,
        dispatch_id=dispatch_id,
        wrapped=["bash", "-c", "echo about-to-fail >&2; exit 7"],
    )
    result = _run_dispatch(test_repo, *args)
    assert result.returncode == 7, "wrapper must propagate the wrapped command's exact exit status"

    evidence = _evidence_dir(test_repo, artifact_id, dispatch_id)
    closeout = _read_json(evidence / "closeout.json")
    assert closeout["terminal_status"] == "failed"
    assert closeout["exit_code"] == 7
    assert closeout["exit_code"] != 0
    assert closeout["terminal_status"] in TERMINAL_STATUSES


def test_closeout_written_exactly_once(test_repo: Path) -> None:
    artifact_id = "once_test"
    dispatch_id = "once-test-001"
    args = _basic_args(artifact_id=artifact_id, dispatch_id=dispatch_id)
    result = _run_dispatch(test_repo, *args)
    assert result.returncode == 0

    evidence = _evidence_dir(test_repo, artifact_id, dispatch_id)
    closeout_path = evidence / "closeout.json"
    assert closeout_path.is_file()
    # Only one closeout file exists (no rotated copies, no .tmp residue).
    files = sorted(p.name for p in evidence.iterdir())
    closeout_files = [name for name in files if name.startswith("closeout")]
    assert closeout_files == ["closeout.json"], files


# ---------- signal handling ----------


def test_signal_term_produces_interrupted_closeout(test_repo: Path) -> None:
    """SIGTERM mid-run must yield an `interrupted` closeout, not `hung`."""
    artifact_id = "signal_test"
    dispatch_id = "signal-test-001"
    args = _basic_args(
        artifact_id=artifact_id,
        dispatch_id=dispatch_id,
        # Long sleep so we have time to send the signal before normal exit.
        wrapped=["bash", "-c", "echo started; sleep 30"],
    )
    proc = subprocess.Popen(
        ["bash", str(test_repo / "infra/scripts/long_running_dispatch.sh"), *args],
        cwd=test_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # New process group so we can target the wrapper without affecting pytest.
        start_new_session=True,
    )

    # Wait for dispatch.json to land so we know setup ran.
    evidence = _evidence_dir(test_repo, artifact_id, dispatch_id)
    dispatch_path = evidence / "dispatch.json"
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and not dispatch_path.is_file():
        time.sleep(0.05)
    assert dispatch_path.is_file(), "dispatch.json must be written before launch"

    # Also wait briefly for the child sleep to have actually started so that
    # the wrapper is in its `wait` and the trap is the path that will fire.
    log_path = evidence / "dispatch.log"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and (
        not log_path.is_file() or "started" not in log_path.read_text(encoding="utf-8")
    ):
        time.sleep(0.05)

    proc.send_signal(signal.SIGTERM)
    try:
        returncode = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        pytest.fail("wrapper did not exit within 15s after SIGTERM")

    assert returncode != 0, "interrupted run must exit non-zero"

    closeout = _read_json(evidence / "closeout.json")
    assert closeout["terminal_status"] == "interrupted"
    assert closeout["exit_code"] != 0
    assert closeout["dispatch_id"] == dispatch_id
