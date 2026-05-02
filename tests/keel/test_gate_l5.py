from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from core.refresh import gate_l5


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_evidence_marks_fail_when_any_non_success_runs_exist(tmp_path: Path) -> None:
    evidence_path = gate_l5.write_l5_evidence(
        counts={"crashed": 1, "empty": 2, "degraded": 0, "success": 4},
        total_runs=7,
        repo_sha="57f90d75",
        produced_at=datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 24),
    )

    payload = _read_json(evidence_path)

    assert evidence_path == tmp_path / "global" / "2026-04-24.json"
    assert payload["status"] == "fail"
    assert payload["scope"] == "global"
    assert payload["total_runs"] == 7
    assert payload["status_counts"] == {"crashed": 1, "empty": 2, "degraded": 0, "success": 4}


def test_build_evidence_marks_pass_when_all_runs_are_success(tmp_path: Path) -> None:
    evidence_path = gate_l5.write_l5_evidence(
        counts={"crashed": 0, "empty": 0, "degraded": 0, "success": 5},
        total_runs=5,
        repo_sha="57f90d75",
        produced_at=datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path,
        evidence_date=date(2026, 4, 24),
    )

    payload = _read_json(evidence_path)

    assert payload["status"] == "pass"
    assert payload["gate_command"] == "make gate-L5"
