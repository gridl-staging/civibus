from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/detached_runner.sh"
PROBE_SCRIPT_PATH = REPO_ROOT / "infra/scripts/probe_load_progress.sh"
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _run_runner(job_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DETACHED_RUNNER_ROOT": str(job_root)}
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


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


def test_start_status_and_wait_report_terminal_metadata(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "known_exit"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=7))
    assert start.returncode == 0, start.stderr
    start_payload = _json_stdout(start)
    assert start_payload["job"] == job_name
    assert start_payload["alive"] is True
    assert start_payload["exit_code"] is None
    assert UTC_TIMESTAMP.match(start_payload["started_at"])

    wait = _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "5")
    assert wait.returncode == 7, wait.stderr
    terminal_payload = _json_stdout(wait)
    assert terminal_payload == {
        "job": job_name,
        "pid": start_payload["pid"],
        "alive": False,
        "exit_code": 7,
        "started_at": (job_root / job_name / "started_at").read_text(encoding="utf-8").strip(),
        "last_log_line": "fixture final log",
        "progress": {"phase": "finished", "rows": 2},
    }


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


def test_wait_uses_child_identity_when_wrapper_identity_races(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "child_identity_fallback"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr

    identity_path = job_root / job_name / "process_identity"
    recorded_identity = identity_path.read_text(encoding="utf-8")
    identity_path.write_text("stale-wrapper-identity\n", encoding="utf-8")

    timeout = _run_runner(job_root, "wait", job_name, "--poll-seconds", "1", "--timeout-seconds", "1")
    assert timeout.returncode == 124, timeout.stderr
    timeout_payload = _json_stdout(timeout)
    assert timeout_payload["alive"] is True
    assert timeout_payload["exit_code"] is None

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


def test_stop_refuses_when_recorded_process_identity_does_not_match(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_name = "identity_guard"
    start = _run_runner(job_root, "start", job_name, "--", *_fixture_command(exit_code=0, sleep_seconds="2.0"))
    assert start.returncode == 0, start.stderr

    identity_path = job_root / job_name / "process_identity"
    recorded_identity = identity_path.read_text(encoding="utf-8")
    identity_path.write_text("definitely-not-the-recorded-command\n", encoding="utf-8")

    refused = _run_runner(job_root, "stop", job_name)
    assert refused.returncode == 4
    assert "process identity mismatch" in refused.stderr

    identity_path.write_text(recorded_identity, encoding="utf-8")
    _stop_if_running(job_root, job_name)
