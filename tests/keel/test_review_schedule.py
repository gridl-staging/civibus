from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

import core.keel_review_schedule as keel_review_schedule


def _write_schedule(path: Path, *, content: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")


def test_load_review_schedule_validates_cadence_vocab(tmp_path: Path) -> None:
    schedule_path = tmp_path / "keel_reviews.yaml"
    _write_schedule(
        schedule_path,
        content={
            "schema_version": 1,
            "reviews": [
                {
                    "review_id": "calibration_audit",
                    "cadence": "quarterly",
                    "primary_prompt": "prompts/judge/calibration_audit.md",
                    "skeptic_prompt": "prompts/judge/calibration_audit_skeptic.md",
                    "evidence_root": "evidence/review/calibration_audit",
                },
                {
                    "review_id": "escalation_review",
                    "cadence": "weekly",
                    "primary_prompt": "prompts/judge/escalation_review.md",
                    "skeptic_prompt": "prompts/judge/escalation_review_skeptic.md",
                    "evidence_root": "evidence/review/escalation_review",
                },
            ],
        },
    )

    schedule = keel_review_schedule.load_schedule(schedule_path)

    assert [entry.review_id for entry in schedule] == ["calibration_audit", "escalation_review"]
    assert schedule[0].cadence == "quarterly"
    assert schedule[1].cadence == "weekly"


def test_load_review_schedule_rejects_unknown_cadence(tmp_path: Path) -> None:
    schedule_path = tmp_path / "keel_reviews.yaml"
    _write_schedule(
        schedule_path,
        content={
            "schema_version": 1,
            "reviews": [
                {
                    "review_id": "x",
                    "cadence": "fortnightly",
                    "primary_prompt": "prompts/judge/x.md",
                    "skeptic_prompt": "prompts/judge/x_skeptic.md",
                    "evidence_root": "evidence/review/x",
                }
            ],
        },
    )

    with pytest.raises(Exception):
        keel_review_schedule.load_schedule(schedule_path)


def test_compute_review_status_marks_missing_evidence_as_overdue(tmp_path: Path) -> None:
    repo_root = tmp_path
    schedule_path = repo_root / "keel_reviews.yaml"
    _write_schedule(
        schedule_path,
        content={
            "schema_version": 1,
            "reviews": [
                {
                    "review_id": "escalation_review",
                    "cadence": "weekly",
                    "primary_prompt": "prompts/judge/escalation_review.md",
                    "skeptic_prompt": "prompts/judge/escalation_review_skeptic.md",
                    "evidence_root": "evidence/review/escalation_review",
                }
            ],
        },
    )

    schedule = keel_review_schedule.load_schedule(schedule_path)
    rows = keel_review_schedule.compute_review_status(
        repo_root=repo_root, schedule=schedule, now_date=date(2026, 4, 25)
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.review_id == "escalation_review"
    assert row.last_evidence_date is None
    assert row.status == "overdue"
    assert row.next_due_date == date(2026, 4, 25)
    assert row.days_overdue >= 0


def test_compute_review_status_finds_latest_evidence_and_computes_next_due(tmp_path: Path) -> None:
    repo_root = tmp_path
    schedule_path = repo_root / "keel_reviews.yaml"
    _write_schedule(
        schedule_path,
        content={
            "schema_version": 1,
            "reviews": [
                {
                    "review_id": "escalation_review",
                    "cadence": "weekly",
                    "primary_prompt": "prompts/judge/escalation_review.md",
                    "skeptic_prompt": "prompts/judge/escalation_review_skeptic.md",
                    "evidence_root": "evidence/review/escalation_review",
                },
                {
                    "review_id": "calibration_audit",
                    "cadence": "quarterly",
                    "primary_prompt": "prompts/judge/calibration_audit.md",
                    "skeptic_prompt": "prompts/judge/calibration_audit_skeptic.md",
                    "evidence_root": "evidence/review/calibration_audit",
                },
            ],
        },
    )

    weekly_evidence_dir = repo_root / "evidence" / "review" / "escalation_review"
    weekly_evidence_dir.mkdir(parents=True)
    (weekly_evidence_dir / "2026-04-20.json").write_text("{}", encoding="utf-8")

    quarterly_evidence_dir = repo_root / "evidence" / "review" / "calibration_audit"
    quarterly_evidence_dir.mkdir(parents=True)
    (quarterly_evidence_dir / "2026-01-15.json").write_text("{}", encoding="utf-8")

    schedule = keel_review_schedule.load_schedule(schedule_path)
    rows = {
        row.review_id: row
        for row in keel_review_schedule.compute_review_status(
            repo_root=repo_root, schedule=schedule, now_date=date(2026, 4, 25)
        )
    }

    weekly = rows["escalation_review"]
    assert weekly.last_evidence_date == date(2026, 4, 20)
    # weekly cadence: next due is last + 7 days = 2026-04-27, so on 2026-04-25 it is on_time
    assert weekly.next_due_date == date(2026, 4, 27)
    assert weekly.status == "on_time"
    assert weekly.days_overdue < 0  # negative = days remaining

    quarterly = rows["calibration_audit"]
    # quarterly cadence: 90 days from 2026-01-15 = 2026-04-15, and now is 2026-04-25 -> overdue 10 days
    assert quarterly.last_evidence_date == date(2026, 1, 15)
    assert quarterly.next_due_date == date(2026, 4, 15)
    assert quarterly.status == "overdue"
    assert quarterly.days_overdue == 10


def test_repo_owned_review_schedule_loads_and_lists_calibration_and_escalation() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    schedule = keel_review_schedule.load_schedule(repo_root / "keel_reviews.yaml")

    review_ids = sorted(entry.review_id for entry in schedule)
    assert review_ids == ["calibration_audit", "escalation_review"]
    by_id = {entry.review_id: entry for entry in schedule}
    assert by_id["calibration_audit"].cadence == "quarterly"
    assert by_id["escalation_review"].cadence == "weekly"
    # All declared prompt paths exist as committed prompt files.
    for entry in schedule:
        assert (repo_root / entry.primary_prompt).is_file(), entry.primary_prompt
        assert (repo_root / entry.skeptic_prompt).is_file(), entry.skeptic_prompt


def test_review_schedule_carries_canonical_thresholds() -> None:
    """The single source of truth for lifecycle-exit and escalation thresholds is
    keel_reviews.yaml, not the prompt prose. Resolves open_questions.md #3 + #6."""
    repo_root = Path(__file__).resolve().parents[2]
    schedule = keel_review_schedule.load_schedule(repo_root / "keel_reviews.yaml")
    by_id = {entry.review_id: entry for entry in schedule}

    escalation_thresholds = by_id["escalation_review"].thresholds
    assert escalation_thresholds["auto_block_days"] == 14

    calibration_thresholds = by_id["calibration_audit"].thresholds
    assert calibration_thresholds["min_real_issues_per_window"] == 1
    assert calibration_thresholds["max_evidence_files_per_window"] == 50


def test_review_prompts_cite_yaml_threshold_fields_by_name() -> None:
    """SSOT cross-check: the calibration/escalation review prompts must cite
    each YAML threshold field by name (e.g. `auto_block_days`,
    `min_real_issues_per_window`) rather than hardcoding the numbers in prose.

    Catches the failure mode where someone retunes the YAML number but the
    prompt rubric still says the old number, leaving the framework with two
    sources of truth.
    """
    repo_root = Path(__file__).resolve().parents[2]
    schedule = keel_review_schedule.load_schedule(repo_root / "keel_reviews.yaml")
    by_id = {entry.review_id: entry for entry in schedule}

    for review_id, entry in by_id.items():
        if not entry.thresholds:
            continue
        prompt_text = (repo_root / entry.primary_prompt).read_text(encoding="utf-8")
        for threshold_name in entry.thresholds:
            assert threshold_name in prompt_text, (
                f"prompt {entry.primary_prompt} must cite threshold "
                f"{threshold_name!r} by name (declared in keel_reviews.yaml "
                f"under {review_id}.thresholds). Hardcoding the number in prose "
                f"creates an SSOT drift hazard."
            )


def test_review_schedule_thresholds_default_to_empty_when_omitted(tmp_path: Path) -> None:
    """Backward-compat: existing schedule entries without a `thresholds` block
    must still load (defaults to an empty dict)."""
    schedule_path = tmp_path / "keel_reviews.yaml"
    _write_schedule(
        schedule_path,
        content={
            "schema_version": 1,
            "reviews": [
                {
                    "review_id": "no_thresholds",
                    "cadence": "weekly",
                    "primary_prompt": "prompts/judge/no_thresholds.md",
                    "skeptic_prompt": "prompts/judge/no_thresholds_skeptic.md",
                    "evidence_root": "evidence/review/no_thresholds",
                }
            ],
        },
    )

    schedule = keel_review_schedule.load_schedule(schedule_path)
    assert schedule[0].thresholds == {}
