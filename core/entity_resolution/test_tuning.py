from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from core.entity_resolution.tuning import (
    append_tuning_summary_row,
    compute_all_cohort_baselines_for_candidate,
    evaluate_persisted_state_cohort_gate,
    load_stage2_cohort_baseline,
    run_tuning_candidate,
)


def test_run_tuning_candidate_threads_candidate_settings_and_emits_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate_id = "candidate_001"
    artifact_dir = tmp_path / "candidate_001"
    candidate_settings = {"id": candidate_id}
    hypothesis = "tighten jaro threshold for canonical_name"
    observed_gate_settings: list[object] = []
    observed_cohort_settings: list[object] = []

    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_candidate_bundle",
        lambda in_candidate_id: {
            "candidate_id": in_candidate_id,
            "hypothesis": hypothesis,
            "probabilistic_settings": candidate_settings,
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.run_l8_regression_gate",
        lambda **kwargs: observed_gate_settings.append(kwargs["probabilistic_settings"])
        or {
            "status": "pass",
            "produced_at_utc": "2026-04-30T00:00:00Z",
            "pair_results": [
                {"case_id": "a", "passed": True},
                {"case_id": "b", "passed": True},
                {"case_id": "c", "passed": False},
            ],
            "false_positive_summary": {
                "cases_evaluated": 5,
                "flagged_false_positives": 1,
                "flagged_case_ids": ["fp_1"],
                "false_positive_rate": 0.2,
            },
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.compute_all_cohort_baselines_for_candidate",
        lambda settings: observed_cohort_settings.append(settings)
        or {
            "ncga_house": {"pct_resolved": 0.82, "gate_target_pct": 0.8},
            "federal": {"pct_resolved": 0.85, "gate_target_pct": 0.8},
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_stage2_cohort_baseline",
        lambda path=None: {
            "ncga_house": {"pct_resolved": 0.81, "gate_target_pct": 0.8, "floor": 0.8},
            "federal": {"pct_resolved": 0.79, "gate_target_pct": 0.8, "floor": 0.8},
        },
    )

    result = run_tuning_candidate(
        candidate_id=candidate_id,
        artifact_dir=artifact_dir,
        summary_path=tmp_path / "stage3_tuning_summary.jsonl",
    )

    assert observed_gate_settings == [candidate_settings]
    assert observed_cohort_settings == [candidate_settings]
    assert result["candidate_id"] == candidate_id
    assert result["hypothesis"] == hypothesis
    assert result["regression"]["passed"] == 2
    assert result["regression"]["total"] == 3
    assert result["regression"]["pass_rate"] == pytest.approx(2 / 3)
    assert result["status"] == "pass"
    assert result["cohort_gate"]["status"] == "pass"
    assert result["cohort_gate"]["failed_cohort_slugs"] == []
    assert result["cohort_gate"]["misses"] == []
    assert result["cohort_gate"]["cohorts"]["ncga_house"]["pct_resolved"] == pytest.approx(0.82)
    assert result["cohort_gate"]["cohorts"]["ncga_house"]["gate_target_pct"] == pytest.approx(0.8)
    assert result["cohort_gate"]["cohorts"]["ncga_house"]["required_target_pct"] == pytest.approx(0.8)
    assert (artifact_dir / "stage7_final_l8_regression.json").exists()
    assert (artifact_dir / "stage7_final_cohort_gate.json").exists()


def test_run_tuning_candidate_hard_fails_on_stage7_cohort_gate_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_candidate_bundle",
        lambda in_candidate_id: {
            "candidate_id": in_candidate_id,
            "hypothesis": "keep defaults",
            "probabilistic_settings": {"id": in_candidate_id},
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.run_l8_regression_gate",
        lambda **kwargs: {
            "status": "pass",
            "produced_at_utc": "2026-04-30T00:00:00Z",
            "pair_results": [{"case_id": "a", "passed": True}],
            "false_positive_summary": {
                "cases_evaluated": 1,
                "flagged_false_positives": 0,
                "flagged_case_ids": [],
                "false_positive_rate": 0.0,
            },
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.compute_all_cohort_baselines_for_candidate",
        lambda settings: {
            "ncga_house": {"pct_resolved": 0.75, "gate_target_pct": 0.8},
            "federal": {"pct_resolved": 0.81, "gate_target_pct": 0.8},
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_stage2_cohort_baseline",
        lambda path=None: {
            "ncga_house": {"pct_resolved": 0.8, "gate_target_pct": 1.0, "floor": 0.8},
            "federal": {"pct_resolved": 0.8, "gate_target_pct": 0.8, "floor": 0.8},
        },
    )

    artifact_dir = tmp_path / "stage7_final"
    with pytest.raises(RuntimeError, match="Stage 7 cohort gate failed"):
        run_tuning_candidate(
            candidate_id="default",
            artifact_dir=artifact_dir,
            summary_path=tmp_path / "stage3_tuning_summary.jsonl",
        )

    cohort_gate_payload = json.loads((artifact_dir / "stage7_final_cohort_gate.json").read_text(encoding="utf-8"))
    assert cohort_gate_payload["status"] == "fail"
    assert cohort_gate_payload["cohort_gate"]["failed_cohort_slugs"] == ["ncga_house"]
    assert cohort_gate_payload["cohort_gate"]["misses"] == [
        {
            "cohort_slug": "ncga_house",
            "pct_resolved": pytest.approx(0.75),
            "required_target_pct": pytest.approx(1.0),
            "delta_pct": pytest.approx(-0.25),
        }
    ]


def test_run_tuning_candidate_hard_fails_on_l8_gate_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_candidate_bundle",
        lambda in_candidate_id: {
            "candidate_id": in_candidate_id,
            "hypothesis": "keep defaults",
            "probabilistic_settings": {"id": in_candidate_id},
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.run_l8_regression_gate",
        lambda **kwargs: {
            "status": "fail",
            "produced_at_utc": "2026-04-30T00:00:00Z",
            "pair_results": [{"case_id": "a", "passed": False}],
            "false_positive_summary": {
                "cases_evaluated": 1,
                "flagged_false_positives": 0,
                "flagged_case_ids": [],
                "false_positive_rate": 0.0,
            },
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.compute_all_cohort_baselines_for_candidate",
        lambda settings: {
            "ncga_house": {"pct_resolved": 1.0, "gate_target_pct": 1.0},
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_stage2_cohort_baseline",
        lambda path=None: {
            "ncga_house": {"pct_resolved": 0.8, "gate_target_pct": 1.0, "floor": 0.8},
        },
    )

    with pytest.raises(RuntimeError, match="Stage 7 acceptance gate failed"):
        run_tuning_candidate(
            candidate_id="default",
            artifact_dir=tmp_path / "stage7_final",
            summary_path=tmp_path / "stage3_tuning_summary.jsonl",
        )


def test_append_tuning_summary_row_is_append_only(tmp_path: Path) -> None:
    summary_path = tmp_path / "stage3_tuning_summary.jsonl"

    append_tuning_summary_row(summary_path, {"candidate_id": "a"})
    append_tuning_summary_row(summary_path, {"candidate_id": "b"})

    rows = [json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"candidate_id": "a"}, {"candidate_id": "b"}]


def test_compute_all_cohort_baselines_for_candidate_persists_candidate_clusters_before_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_settings = {"candidate": "stage3-candidate"}
    candidate_rows = [{"id": uuid4(), "canonical_name": "Example Candidate"}]
    scored_pairs = [
        {
            "entity_id_a": candidate_rows[0]["id"],
            "entity_id_b": candidate_rows[0]["id"],
            "confidence": 0.99,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]
    classified_pairs = [{**scored_pairs[0], "decision": "match"}]
    clustered_pairs = {
        "auto_merge_clusters": [
            {
                "canonical_entity_id": candidate_rows[0]["id"],
                "member_ids": {candidate_rows[0]["id"]},
                "min_confidence": 0.99,
            }
        ],
        "review_components": [],
        "pairwise_decisions": classified_pairs,
    }
    expected_baselines = {"ncga_house": {"pct_resolved": 0.82, "gate_target_pct": 0.8}}
    call_order: list[str] = []

    class FakeConnection:
        def __init__(self) -> None:
            self.rollback_calls = 0
            self.close_calls = 0

        def rollback(self) -> None:
            self.rollback_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    fake_connection = FakeConnection()

    monkeypatch.setattr("core.entity_resolution.tuning.get_connection", lambda: fake_connection)
    monkeypatch.setattr(
        "core.entity_resolution.tuning.extract_rows_for_matching",
        lambda conn, entity_type: call_order.append("extract") or candidate_rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.score_entities",
        lambda conn, entity_type, probabilistic_settings=None: call_order.append("score") or scored_pairs,
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.classify_scored_pairs",
        lambda pairs: call_order.append("classify") or classified_pairs,
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.cluster_scored_pairs",
        lambda classified, rows: call_order.append("cluster") or clustered_pairs,
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.persist_auto_merge_clusters",
        lambda conn, auto_merge_clusters, entity_type: call_order.append("persist")
        or [uuid4() for _ in auto_merge_clusters],
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.compute_all_cohort_baselines",
        lambda conn: call_order.append("cohort_probe") or expected_baselines,
    )

    baselines = compute_all_cohort_baselines_for_candidate(candidate_settings)

    assert baselines == expected_baselines
    assert call_order == ["extract", "score", "classify", "cluster", "persist", "cohort_probe"]
    assert fake_connection.rollback_calls == 1
    assert fake_connection.close_calls == 1


def test_evaluate_stage7_cohort_gate_fails_when_baseline_cohort_missing_from_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stage 2 baseline has 'federal' but candidate output omits it — gate must fail."""
    from core.entity_resolution.tuning import _evaluate_stage7_cohort_gate

    stage2_baseline = {
        "ncga_house": {"pct_resolved": 0.8, "gate_target_pct": 1.0, "floor": 0.8},
        "federal": {"pct_resolved": 0.5, "gate_target_pct": 0.8, "floor": 0.8},
    }
    candidate_cohorts = {
        "ncga_house": {"pct_resolved": 0.85, "gate_target_pct": 1.0},
        # 'federal' deliberately missing
    }

    result = _evaluate_stage7_cohort_gate(
        stage2_baseline=stage2_baseline,
        candidate_cohorts=candidate_cohorts,
    )

    assert result["status"] == "fail"
    assert "federal" in result["failed_cohort_slugs"]
    federal_miss = next(m for m in result["misses"] if m["cohort_slug"] == "federal")
    assert federal_miss["pct_resolved"] == 0.0
    assert federal_miss["required_target_pct"] == pytest.approx(0.8)


def test_run_tuning_candidate_l8_artifact_includes_full_command_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """L8 artifact gate_command must record full invocation args for Stage 8 replay."""
    captured_kwargs: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_candidate_bundle",
        lambda cid: {
            "candidate_id": cid,
            "hypothesis": "test",
            "probabilistic_settings": {"id": cid},
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.run_l8_regression_gate",
        lambda **kwargs: captured_kwargs.append(kwargs)
        or {
            "status": "pass",
            "produced_at_utc": "2026-04-30T00:00:00Z",
            "pair_results": [],
            "false_positive_summary": {
                "cases_evaluated": 0,
                "flagged_false_positives": 0,
                "flagged_case_ids": [],
                "false_positive_rate": 0.0,
            },
        },
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.compute_all_cohort_baselines_for_candidate",
        lambda settings: {"ncga_house": {"pct_resolved": 1.0, "gate_target_pct": 0.8}},
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_stage2_cohort_baseline",
        lambda path=None: {
            "ncga_house": {"pct_resolved": 0.8, "gate_target_pct": 0.8, "floor": 0.8},
        },
    )

    artifact_dir = tmp_path / "stage7"
    stage2_path = tmp_path / "stage2_baseline.json"
    summary_path = tmp_path / "summary.jsonl"

    run_tuning_candidate(
        candidate_id="test_candidate",
        artifact_dir=artifact_dir,
        stage2_baseline_path=stage2_path,
        summary_path=summary_path,
    )

    assert len(captured_kwargs) == 1
    gate_command = captured_kwargs[0]["gate_command"]
    assert "--candidate-id test_candidate" in gate_command
    assert f"--artifact-dir {artifact_dir}" in gate_command
    assert f"--stage2-baseline-path {stage2_path}" in gate_command
    assert f"--summary-path {summary_path}" in gate_command


def test_load_stage2_cohort_baseline_rejects_all_zero_pct(tmp_path: Path) -> None:
    baseline_path = tmp_path / "stage2_zero.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cohorts": {
                    "ncga_house": {"pct_resolved": 0.0},
                    "federal": {"pct_resolved": 0.0},
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at least one cohort baseline with pct_resolved > 0.0"):
        load_stage2_cohort_baseline(path=baseline_path)


def test_evaluate_persisted_state_cohort_gate_reuses_stage2_loader_and_stage7_evaluator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    probe_rows = {
        "ncga_house": {"pct_resolved": 0.81, "gate_target_pct": 0.8},
        "federal": {"pct_resolved": 0.82, "gate_target_pct": 0.8},
    }
    stage2_rows = {
        "ncga_house": {"pct_resolved": 0.8, "gate_target_pct": 0.8, "floor": 0.8},
        "federal": {"pct_resolved": 0.8, "gate_target_pct": 0.8, "floor": 0.8},
    }
    expected_gate = {
        "status": "pass",
        "failed_cohort_slugs": [],
        "misses": [],
        "cohorts": {
            "ncga_house": {
                "pct_resolved": 0.81,
                "gate_target_pct": 0.8,
                "required_target_pct": 0.8,
                "delta_pct": 0.01,
                "passes_gate": True,
            },
            "federal": {
                "pct_resolved": 0.82,
                "gate_target_pct": 0.8,
                "required_target_pct": 0.8,
                "delta_pct": 0.02,
                "passes_gate": True,
            },
        },
    }
    stage2_path = tmp_path / "stage2_baseline.json"
    marker_connection = object()
    observed_path: list[Path | None] = []
    observed_args: list[tuple[dict[str, Any], dict[str, Any]]] = []

    monkeypatch.setattr(
        "core.entity_resolution.tuning.compute_all_cohort_baselines",
        lambda conn: probe_rows if conn is marker_connection else pytest.fail("unexpected connection"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning.load_stage2_cohort_baseline",
        lambda path=None: observed_path.append(path) or stage2_rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.tuning._evaluate_stage7_cohort_gate",
        lambda *, stage2_baseline, candidate_cohorts: observed_args.append((stage2_baseline, candidate_cohorts))
        or expected_gate,
    )

    result = evaluate_persisted_state_cohort_gate(
        marker_connection,
        stage2_baseline_path=stage2_path,
    )

    assert observed_path == [stage2_path]
    assert observed_args == [(stage2_rows, probe_rows)]
    assert result == {
        "stage2_baseline_path": str(stage2_path),
        "cohorts": probe_rows,
        "cohort_gate": expected_gate,
    }
