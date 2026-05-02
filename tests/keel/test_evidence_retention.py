from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import core.keel_evidence_retention as keel_evidence_retention


def _write_evidence(
    *, evidence_root: Path, layer: str, scope: str, evidence_date: date, status: str
) -> Path:
    bucket = evidence_root / layer / scope
    bucket.mkdir(parents=True, exist_ok=True)
    target = bucket / f"{evidence_date.isoformat()}.json"
    target.write_text(
        json.dumps(
            {
                "layer": layer,
                "scope": scope,
                "schema_version": 1,
                "produced_at_utc": f"{evidence_date.isoformat()}T00:00:00+00:00",
                "repo_sha": "deadbeef",
                "gate_command": "test",
                "status": status,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def test_rotate_keeps_last_30_dailies_plus_last_pass_and_last_fail(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    layer = "L7"
    scope = "global"
    today = date(2026, 4, 25)

    # Within retention window (last 30 days): a daily for every day, all "pass".
    for offset in range(30, -1, -1):
        _write_evidence(
            evidence_root=evidence_root,
            layer=layer,
            scope=scope,
            evidence_date=today - timedelta(days=offset),
            status="pass",
        )
    # Outside retention window: only two "anchor" days, far apart, plus filler "error" days
    # in between. last_passing_old_date is the most recent OLD pass (must be preserved);
    # last_failing_old_date is the most recent OLD fail (must be preserved).
    last_failing_old_date = today - timedelta(days=80)
    last_passing_old_date = today - timedelta(days=70)
    _write_evidence(
        evidence_root=evidence_root,
        layer=layer,
        scope=scope,
        evidence_date=last_failing_old_date,
        status="fail",
    )
    _write_evidence(
        evidence_root=evidence_root,
        layer=layer,
        scope=scope,
        evidence_date=last_passing_old_date,
        status="pass",
    )
    # Filler "error" days at offsets 50, 60, 75 to ensure rotation deletes non-anchors.
    for filler_offset in (50, 60, 75):
        _write_evidence(
            evidence_root=evidence_root,
            layer=layer,
            scope=scope,
            evidence_date=today - timedelta(days=filler_offset),
            status="error",
        )

    summary = keel_evidence_retention.rotate(
        evidence_root=evidence_root,
        now_date=today,
        retention_days=30,
        dry_run=False,
    )

    bucket = evidence_root / layer / scope
    remaining_dailies = sorted(p.name for p in bucket.iterdir() if p.name.endswith(".json") and "rollup" not in p.name)

    # Last 30 days inclusive: today and 30 prior = 31 dailies
    assert f"{today.isoformat()}.json" in remaining_dailies
    assert f"{(today - timedelta(days=30)).isoformat()}.json" in remaining_dailies
    # Day 31 back must not be a daily anymore
    assert f"{(today - timedelta(days=31)).isoformat()}.json" not in remaining_dailies

    # Last passing and last failing OLD records survive even though they fall outside the 30-day window.
    assert f"{last_failing_old_date.isoformat()}.json" in remaining_dailies
    assert f"{last_passing_old_date.isoformat()}.json" in remaining_dailies

    # Rollup file(s) for older months must exist.
    rollups = sorted(p.name for p in bucket.iterdir() if "rollup" in p.name)
    assert rollups, "expected at least one rollup file"
    # Rollup names use rollup_YYYY-MM.json
    sample = json.loads((bucket / rollups[0]).read_text(encoding="utf-8"))
    assert sample["layer"] == layer
    assert sample["scope"] == scope
    assert "status_counts" in sample
    assert sample["status_counts"]["pass"] >= 0

    assert summary.deleted_count > 0
    assert summary.rolled_up_count > 0


def test_rotate_dry_run_does_not_delete_anything(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    today = date(2026, 4, 25)
    for offset in range(60, -1, -1):
        _write_evidence(
            evidence_root=evidence_root,
            layer="L9",
            scope="global",
            evidence_date=today - timedelta(days=offset),
            status="pass",
        )

    pre_count = sum(1 for _ in (evidence_root / "L9" / "global").iterdir())
    summary = keel_evidence_retention.rotate(
        evidence_root=evidence_root,
        now_date=today,
        retention_days=30,
        dry_run=True,
    )
    post_count = sum(1 for _ in (evidence_root / "L9" / "global").iterdir())

    assert pre_count == post_count
    assert summary.deleted_count == 0
    assert summary.rolled_up_count > 0  # still reports what would be rolled up


def test_rotate_never_touches_waivers_directory(tmp_path: Path) -> None:
    repo_root = tmp_path
    evidence_root = repo_root / "evidence"
    waivers_root = repo_root / "waivers"
    waivers_root.mkdir(parents=True)
    waiver_path = waivers_root / "L7_global_2026-01-01.yaml"
    waiver_path.write_text("layer: L7\n", encoding="utf-8")

    today = date(2026, 4, 25)
    _write_evidence(
        evidence_root=evidence_root,
        layer="L7",
        scope="global",
        evidence_date=today - timedelta(days=200),
        status="pass",
    )

    keel_evidence_retention.rotate(
        evidence_root=evidence_root,
        now_date=today,
        retention_days=30,
        dry_run=False,
    )

    assert waiver_path.exists(), "waiver files must never be deleted by rotation"
