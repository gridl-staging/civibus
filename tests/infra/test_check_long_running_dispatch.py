from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra/scripts/check_long_running_dispatch.py"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _dispatch_payload(dispatch_id: str = "dispatch-1234") -> dict:
    return {
        "schema_version": 1,
        "dispatch_id": dispatch_id,
        "artifact_id": "artifact-1",
        "wrapped_command": "echo hi",
        "host": {"hostname": "h", "vm_ip": "127.0.0.1", "worktree": "/tmp/work"},
        "started_at_utc": "2026-04-29T12:00:00Z",
        "log_path": "/tmp/dispatch.log",
        "evidence_directory": "/tmp/evidence",
        "probe_sql": "SELECT 1",
    }


def _closeout_payload(
    dispatch_id: str = "dispatch-1234",
    terminal_status: str = "succeeded",
    finished_at_utc: str = "2026-04-29T12:10:00Z",
    exit_code: int = 0,
) -> dict:
    return {
        "schema_version": 1,
        "dispatch_id": dispatch_id,
        "finished_at_utc": finished_at_utc,
        "terminal_status": terminal_status,
        "exit_code": exit_code,
        "summary": {
            "duration_seconds": 600,
            "log_bytes": 10,
            "last_log_timestamp_utc": "2026-04-29T12:10:00Z",
        },
    }


def _build_evidence_dir(
    tmp_path: Path,
    *,
    dispatch: dict | None = None,
    closeout: dict | None = None,
    log_age_seconds: int | None = None,
) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    if dispatch is not None:
        _write_json(evidence_dir / "dispatch.json", dispatch)
    if closeout is not None:
        _write_json(evidence_dir / "closeout.json", closeout)
    if log_age_seconds is not None:
        log_path = evidence_dir / "dispatch.log"
        log_path.write_text("log\n", encoding="utf-8")
        mtime = datetime.now(UTC) - timedelta(seconds=log_age_seconds)
        ts = mtime.timestamp()
        log_path.chmod(0o644)
        os.utime(log_path, (ts, ts))
    return evidence_dir


def _run_monitor(evidence_dir: Path, stale_seconds: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(SCRIPT_PATH),
            "--evidence-dir",
            str(evidence_dir),
            "--stale-seconds-threshold",
            str(stale_seconds),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _result_payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"dispatch_id", "status", "reason"}
    return payload


def test_states_from_valid_closeout_terminal_statuses(tmp_path: Path) -> None:
    dispatch = _dispatch_payload()
    mapping = {
        "succeeded": ("succeeded", 0),
        "failed": ("failed", 2),
        "interrupted": ("interrupted", 130),
    }
    for terminal_status, (expected_status, exit_code) in mapping.items():
        evidence_dir = _build_evidence_dir(
            tmp_path / terminal_status,
            dispatch=dispatch,
            closeout=_closeout_payload(terminal_status=terminal_status, exit_code=exit_code),
            log_age_seconds=3600,
        )
        result = _run_monitor(evidence_dir)
        payload = _result_payload(result)
        assert payload["status"] == expected_status


def test_running_when_no_closeout_and_fresh_log(tmp_path: Path) -> None:
    evidence_dir = _build_evidence_dir(
        tmp_path,
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=10,
    )
    payload = _result_payload(_run_monitor(evidence_dir, stale_seconds=60))
    assert payload["status"] == "running"


def test_hung_when_no_closeout_and_stale_log(tmp_path: Path) -> None:
    evidence_dir = _build_evidence_dir(
        tmp_path,
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=500,
    )
    payload = _result_payload(_run_monitor(evidence_dir, stale_seconds=60))
    assert payload["status"] == "hung"


def test_invalid_or_missing_dispatch_json_is_unknown(tmp_path: Path) -> None:
    missing_dir = _build_evidence_dir(tmp_path / "missing", dispatch=None, closeout=None, log_age_seconds=10)
    payload_missing = _result_payload(_run_monitor(missing_dir))
    assert payload_missing["status"] == "unknown"

    invalid_dir = _build_evidence_dir(tmp_path / "invalid", dispatch=None, closeout=None, log_age_seconds=10)
    (invalid_dir / "dispatch.json").write_text("{bad", encoding="utf-8")
    payload_invalid = _result_payload(_run_monitor(invalid_dir))
    assert payload_invalid["status"] == "unknown"

    symlink_dir = _build_evidence_dir(tmp_path / "symlink", dispatch=None, closeout=None, log_age_seconds=10)
    external_dispatch = tmp_path / "external_dispatch.json"
    _write_json(external_dispatch, _dispatch_payload())
    (symlink_dir / "dispatch.json").symlink_to(external_dispatch)
    payload_symlink = _result_payload(_run_monitor(symlink_dir))
    assert payload_symlink["status"] == "unknown"


def test_invalid_or_missing_closeout_falls_back_to_log_freshness(tmp_path: Path) -> None:
    missing_closeout = _build_evidence_dir(
        tmp_path / "missing_closeout",
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(missing_closeout, stale_seconds=60))["status"] == "running"

    invalid_closeout = _build_evidence_dir(
        tmp_path / "invalid_closeout",
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=500,
    )
    (invalid_closeout / "closeout.json").write_text("{bad", encoding="utf-8")
    assert _result_payload(_run_monitor(invalid_closeout, stale_seconds=60))["status"] == "hung"

    symlink_closeout = _build_evidence_dir(
        tmp_path / "symlink_closeout",
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=10,
    )
    external_closeout = tmp_path / "external_closeout.json"
    _write_json(external_closeout, _closeout_payload(terminal_status="failed", exit_code=2))
    (symlink_closeout / "closeout.json").symlink_to(external_closeout)
    assert _result_payload(_run_monitor(symlink_closeout, stale_seconds=60))["status"] == "running"

    symlink_log = _build_evidence_dir(
        tmp_path / "symlink_log",
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=None,
    )
    external_log = tmp_path / "external_dispatch.log"
    external_log.write_text("log\n", encoding="utf-8")
    (symlink_log / "dispatch.log").symlink_to(external_log)
    payload = _result_payload(_run_monitor(symlink_log, stale_seconds=60))
    assert payload["status"] == "unknown"


def test_invariant_violations_are_unknown(tmp_path: Path) -> None:
    mismatch = _build_evidence_dir(
        tmp_path / "mismatch",
        dispatch=_dispatch_payload(dispatch_id="d-1"),
        closeout=_closeout_payload(dispatch_id="d-2"),
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(mismatch))["status"] == "unknown"

    inverted = _build_evidence_dir(
        tmp_path / "inverted",
        dispatch={**_dispatch_payload(), "started_at_utc": "2026-04-29T12:30:00Z"},
        closeout=_closeout_payload(finished_at_utc="2026-04-29T12:10:00Z"),
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(inverted))["status"] == "unknown"

    bad_terminal = _build_evidence_dir(
        tmp_path / "bad_terminal",
        dispatch=_dispatch_payload(),
        closeout=_closeout_payload(terminal_status="completed", exit_code=0),
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(bad_terminal))["status"] == "unknown"


def test_schema_version_conflicts_are_unknown(tmp_path: Path) -> None:
    bad_dispatch_version = _build_evidence_dir(
        tmp_path / "bad_dispatch_version",
        dispatch={**_dispatch_payload(), "schema_version": 2},
        closeout=None,
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(bad_dispatch_version))["status"] == "unknown"

    bad_closeout_version = _build_evidence_dir(
        tmp_path / "bad_closeout_version",
        dispatch=_dispatch_payload(),
        closeout={**_closeout_payload(terminal_status="failed", exit_code=2), "schema_version": 2},
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(bad_closeout_version))["status"] == "unknown"


def test_terminal_exit_code_invariants_are_unknown(tmp_path: Path) -> None:
    succeeded_with_nonzero = _build_evidence_dir(
        tmp_path / "succeeded_with_nonzero",
        dispatch=_dispatch_payload(),
        closeout=_closeout_payload(terminal_status="succeeded", exit_code=7),
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(succeeded_with_nonzero))["status"] == "unknown"

    failed_with_zero = _build_evidence_dir(
        tmp_path / "failed_with_zero",
        dispatch=_dispatch_payload(),
        closeout=_closeout_payload(terminal_status="failed", exit_code=0),
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(failed_with_zero))["status"] == "unknown"

    interrupted_with_zero = _build_evidence_dir(
        tmp_path / "interrupted_with_zero",
        dispatch=_dispatch_payload(),
        closeout=_closeout_payload(terminal_status="interrupted", exit_code=0),
        log_age_seconds=10,
    )
    assert _result_payload(_run_monitor(interrupted_with_zero))["status"] == "unknown"


def test_valid_closeout_precedence_over_stale_log(tmp_path: Path) -> None:
    evidence_dir = _build_evidence_dir(
        tmp_path,
        dispatch=_dispatch_payload(),
        closeout=_closeout_payload(terminal_status="failed", exit_code=3),
        log_age_seconds=999999,
    )
    payload = _result_payload(_run_monitor(evidence_dir, stale_seconds=60))
    assert payload["status"] == "failed"


def test_cli_stdout_schema_and_read_only_behavior(tmp_path: Path) -> None:
    evidence_dir = _build_evidence_dir(
        tmp_path,
        dispatch=_dispatch_payload(),
        closeout=None,
        log_age_seconds=10,
    )
    before_files = sorted(p.name for p in evidence_dir.iterdir())
    result = _run_monitor(evidence_dir, stale_seconds=60)
    payload = _result_payload(result)
    assert payload["dispatch_id"] == "dispatch-1234"
    assert payload["status"] == "running"
    assert isinstance(payload["reason"], str)
    after_files = sorted(p.name for p in evidence_dir.iterdir())
    assert before_files == after_files
    assert not (evidence_dir / "monitor_snapshot.json").exists()


def test_help_works() -> None:
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--evidence-dir" in result.stdout
