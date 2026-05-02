from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date
from pathlib import Path

import pytest

import core.keel_adversarial_pair as keel_adversarial_pair


def _write_schema(path: Path, *, layer: str = "L4") -> None:
    path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["layer", "scope", "verdict"],
                "properties": {
                    "layer": {"const": layer},
                    "scope": {"type": "string"},
                    "verdict": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_pair_summary_schema(path: Path, *, layer: str = "L4") -> None:
    path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                    "primary_verdict",
                    "skeptic_verdict",
                    "pair_outcome",
                    "primary_verdict_path",
                    "skeptic_verdict_path",
                    "bundle_artifacts",
                    "criteria_summary",
                    "escalation_path",
                ],
                "properties": {
                    "layer": {"const": layer},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                    "primary_verdict": {"type": "string"},
                    "skeptic_verdict": {"type": "string"},
                    "pair_outcome": {"type": "string"},
                    "primary_verdict_path": {"type": "string"},
                    "skeptic_verdict_path": {"type": "string"},
                    "bundle_artifacts": {"type": "array", "items": {"type": "string"}},
                    "criteria_summary": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "primary_result", "skeptic_result"],
                            "properties": {
                                "id": {"type": "string"},
                                "primary_result": {"type": "string"},
                                "skeptic_result": {"type": "string"},
                            },
                        },
                    },
                    "escalation_path": {"type": ["string", "null"]},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_prompt(
    path: Path,
    *,
    role: str,
    output_schema: str = "evidence_schemas/L4_judge_verdict.json",
    layer: str = "L4",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
layer: {layer}
role: {role}
model: gpt-5.4
allowed_inputs:
  - evidence/{layer}/NC/2026-04-24/
forbidden_inputs:
  - repo_read
  - prior_research_docs
output_schema: {output_schema}
rubric_version: 0.1.0
---
## Goal

Review the investigation.

## Context (allowed)

Read only the listed artifacts.

## Rubric

- Apply the four required criteria.

## Output format

Return JSON matching the declared schema.

## Calibration examples

- Pass: exhaustive evidence.
""",
        encoding="utf-8",
    )


def _write_verdict(
    path: Path,
    *,
    role: str,
    verdict: str,
    layer: str = "L4",
    scope: str = "NC",
    criterion_result: str = "pass",
    include_criteria: bool = True,
    extra_fields: dict[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "layer": layer,
        "scope": scope,
        "verdict": verdict,
        "confidence": 0.91 if verdict == "pass" else 0.62,
        "rubric_version": "0.1.0",
        "notes": f"{role} notes",
        "session_id": f"{role}-session",
        "timestamp": "2026-04-24T21:00:00Z",
    }
    if include_criteria:
        payload["criteria"] = [
            {
                "id": "trace_completeness",
                "result": criterion_result,
                "reasoning": f"{role} trace review",
                "evidence_urls": [f"evidence/{layer}/{scope}/2026-04-24/trace.json"],
            },
            {
                "id": "multi_domain_scan",
                "result": criterion_result,
                "reasoning": f"{role} multi-domain review",
                "evidence_urls": [f"evidence/{layer}/{scope}/2026-04-24/multi_domain_scan.md"],
            },
            {
                "id": "anchor_projection",
                "result": criterion_result,
                "reasoning": f"{role} anchor projection review",
                "evidence_urls": [f"evidence/{layer}/{scope}/2026-04-24/anchor_projection.json"],
            },
            {
                "id": "disconfirming_search",
                "result": criterion_result,
                "reasoning": f"{role} disconfirming review",
                "evidence_urls": [f"evidence/{layer}/{scope}/2026-04-24/disconfirming.md"],
            },
        ]
    if extra_fields is not None:
        payload.update(extra_fields)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_l8_threshold_verdict(path: Path, *, role: str, verdict: str, criterion_result: str = "pass") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "layer": "L8",
                "scope": "er_threshold",
                "verdict": verdict,
                "confidence": 0.89 if verdict == "pass" else 0.64,
                "rubric_version": "0.1.0",
                "criteria": [
                    {
                        "id": "false_positive_risk",
                        "result": criterion_result,
                        "reasoning": f"{role} false-positive review",
                        "evidence_urls": ["evidence/L8/regression_run_2026-04-24.json"],
                    },
                    {
                        "id": "regression_pair_safety",
                        "result": criterion_result,
                        "reasoning": f"{role} regression-pair review",
                        "evidence_urls": ["tests/er_regression_pairs.yaml"],
                    },
                    {
                        "id": "threshold_delta_safety",
                        "result": criterion_result,
                        "reasoning": f"{role} threshold delta review",
                        "evidence_urls": ["core/entity_resolution/cli.py"],
                    },
                ],
                "notes": f"{role} notes",
                "session_id": f"{role}-session",
                "timestamp": "2026-04-24T21:00:00Z",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _rewrite_criteria_ids(path: Path, criterion_ids: list[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for criterion, criterion_id in zip(payload["criteria"], criterion_ids, strict=True):
        criterion["id"] = criterion_id
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_build_pair_run_plan_uses_distinct_role_scoped_output_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(schema_root / "L4_judge_verdict.json")
    _write_pair_summary_schema(schema_root / "L4.json")
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )

    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    assert plan["layer"] == "L4"
    assert plan["scope"] == "NC"
    assert plan["combined_evidence_output_path"] == "evidence/L4/NC/2026-04-24/summary.json"
    assert plan["combined_output_schema_path"] == "evidence_schemas/L4.json"
    assert plan["escalation_output_path"] == "escalations/2026-04-24/L4_NC.md"
    assert plan["bundle_directory"] == "evidence/L4/NC/2026-04-24"
    assert plan["primary"]["evidence_output_path"] == "evidence/L4/NC/2026-04-24/portal_investigation_review.json"
    assert (
        plan["skeptic"]["evidence_output_path"] == "evidence/L4/NC/2026-04-24/portal_investigation_review_skeptic.json"
    )
    assert plan["primary"]["output_schema_path"] == "evidence_schemas/L4_judge_verdict.json"
    assert plan["skeptic"]["output_schema_path"] == "evidence_schemas/L4_judge_verdict.json"


def test_build_pair_run_plan_rejects_mismatched_layers(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(schema_root / "L4_judge_verdict.json")
    _write_pair_summary_schema(schema_root / "L4.json")
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
        layer="L4",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
        layer="L8",
    )

    with pytest.raises(ValueError, match="must target the same layer"):
        keel_adversarial_pair.build_pair_run_plan(
            repo_root=repo_root,
            primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
            skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
            scope="NC",
            session_id="judge-session-1",
            run_date=date(2026, 4, 24),
        )


def test_build_pair_run_plan_rejects_mismatched_output_schemas(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(schema_root / "L4_judge_verdict.json")
    _write_schema(schema_root / "other_output.json")
    _write_pair_summary_schema(schema_root / "L4.json")
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
        output_schema="evidence_schemas/L4_judge_verdict.json",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
        output_schema="evidence_schemas/other_output.json",
    )

    with pytest.raises(ValueError, match="must share the same output_schema"):
        keel_adversarial_pair.build_pair_run_plan(
            repo_root=repo_root,
            primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
            skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
            scope="NC",
            session_id="judge-session-1",
            run_date=date(2026, 4, 24),
        )


def test_summarize_pair_run_returns_passing_summary_without_escalation(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(schema_root / "L4_judge_verdict.json")
    _write_pair_summary_schema(schema_root / "L4.json")
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=[
            "evidence/L4/NC/2026-04-24/trace.json",
            "evidence/L4/NC/2026-04-24/multi_domain_scan.md",
        ],
    )

    assert summary["status"] == "pass"
    assert summary["pair_outcome"] == "agreement_pass"
    assert summary["primary_verdict_path"] == "evidence/L4/NC/2026-04-24/portal_investigation_review.json"
    assert summary["skeptic_verdict_path"] == "evidence/L4/NC/2026-04-24/portal_investigation_review_skeptic.json"
    assert summary["escalation_path"] is None
    assert escalation_markdown is None


def test_summarize_pair_run_escalates_when_verdicts_diverge(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(schema_root / "L4_judge_verdict.json")
    _write_pair_summary_schema(schema_root / "L4.json")
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_verdict(
        repo_root / plan["skeptic"]["evidence_output_path"],
        role="skeptic",
        verdict="uncertain",
        criterion_result="uncertain",
    )

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L4/NC/2026-04-24/trace.json"],
    )

    assert summary["status"] == "fail"
    assert summary["pair_outcome"] == "escalated"
    assert summary["escalation_path"] == "escalations/2026-04-24/L4_NC.md"
    assert escalation_markdown is not None
    assert "portal_investigation_review" in escalation_markdown


def test_summarize_pair_run_supports_non_l4_pair_with_layer_schema(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    _write_schema(schema_root / "L7_judge_verdict.json", layer="L7")
    (schema_root / "L7.json").write_text(
        (source_schema_root / "L7.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "ops_readiness_review.md",
        role="ops_readiness_review",
        output_schema="evidence_schemas/L7_judge_verdict.json",
        layer="L7",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "ops_readiness_review_skeptic.md",
        role="ops_readiness_review_skeptic",
        output_schema="evidence_schemas/L7_judge_verdict.json",
        layer="L7",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "ops_readiness_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "ops_readiness_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    assert plan["combined_output_schema_path"] == "evidence_schemas/L7.json"
    _write_verdict(
        repo_root / plan["primary"]["evidence_output_path"],
        role="primary",
        verdict="pass",
        layer="L7",
        include_criteria=False,
        extra_fields={
            "checked_clusters": 40,
            "overlapping_clusters": 5,
            "discrepancy_count": 7,
            "discrepancies_by_field": {"canonical_name": 5, "primary_address": 2},
            "sample_discrepancies": [
                {
                    "entity_type": "organization",
                    "cluster_id": "org-7",
                    "field": "canonical_name",
                    "source_count": 2,
                    "distinct_value_count": 2,
                    "source_names": ["source_a", "source_b"],
                    "values": ["Acme LLC", "Acme, LLC"],
                }
            ],
        },
    )
    _write_verdict(
        repo_root / plan["skeptic"]["evidence_output_path"],
        role="skeptic",
        verdict="pass",
        layer="L7",
        include_criteria=False,
        extra_fields={
            "checked_clusters": 40,
            "overlapping_clusters": 5,
            "discrepancy_count": 7,
            "discrepancies_by_field": {"canonical_name": 5, "primary_address": 2},
            "sample_discrepancies": [
                {
                    "entity_type": "organization",
                    "cluster_id": "org-7",
                    "field": "canonical_name",
                    "source_count": 2,
                    "distinct_value_count": 2,
                    "source_names": ["source_a", "source_b"],
                    "values": ["Acme LLC", "Acme, LLC"],
                }
            ],
        },
    )

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L7/NC/2026-04-24/trace.json"],
    )

    assert plan["combined_evidence_output_path"] == "evidence/L7/NC/2026-04-24/summary.json"
    assert summary["layer"] == "L7"
    assert summary["status"] == "pass"
    assert summary["checked_clusters"] == 40
    assert summary["overlapping_clusters"] == 5
    assert summary["discrepancy_count"] == 7
    assert summary["discrepancies_by_field"] == {"canonical_name": 5, "primary_address": 2}
    assert len(summary["sample_discrepancies"]) == 1
    assert "escalation_path" not in summary
    assert escalation_markdown is None


def test_summarize_pair_run_supports_l12_pair_with_layer_summary_schema(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    _write_schema(schema_root / "L12_judge_verdict.json", layer="L12")
    (schema_root / "L12.json").write_text(
        (source_schema_root / "L12.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "session_output.md",
        role="session_output",
        output_schema="evidence_schemas/L12_judge_verdict.json",
        layer="L12",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "session_output_skeptic.md",
        role="session_output_skeptic",
        output_schema="evidence_schemas/L12_judge_verdict.json",
        layer="L12",
    )

    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "session_output.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "session_output_skeptic.md",
        scope="web",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    assert plan["combined_output_schema_path"] == "evidence_schemas/L12.json"
    _write_verdict(
        repo_root / plan["primary"]["evidence_output_path"],
        role="primary",
        verdict="pass",
        layer="L12",
        scope="web",
        include_criteria=False,
        extra_fields={
            "session_id": "judge-session-1",
            "changed_files": ["core/keel_adversarial_pair.py"],
            "touched_layers": ["L4", "L12"],
            "produced_evidence_layers": ["L12"],
            "row_count_deltas": [{"source_id": "tx_bulk", "before": 10, "after": 12, "delta": 2}],
            "anchor_ratio_deltas": [{"scope": "web", "before": 0.2, "after": 0.3, "delta": 0.1}],
        },
    )
    _write_verdict(
        repo_root / plan["skeptic"]["evidence_output_path"],
        role="skeptic",
        verdict="pass",
        layer="L12",
        scope="web",
        include_criteria=False,
        extra_fields={
            "session_id": "judge-session-1",
            "changed_files": ["core/keel_adversarial_pair.py"],
            "touched_layers": ["L4", "L12"],
            "produced_evidence_layers": ["L12"],
            "row_count_deltas": [{"source_id": "tx_bulk", "before": 10, "after": 12, "delta": 2}],
            "anchor_ratio_deltas": [{"scope": "web", "before": 0.2, "after": 0.3, "delta": 0.1}],
        },
    )

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L12/web/2026-04-24/rows.json"],
    )

    assert summary["layer"] == "L12"
    assert summary["scope"] == "web"
    assert summary["status"] == "pass"
    assert summary["session_id"] == "judge-session-1"
    assert summary["changed_files"] == ["core/keel_adversarial_pair.py"]
    assert summary["touched_layers"] == ["L4", "L12"]
    assert summary["produced_evidence_layers"] == ["L12"]
    assert summary["row_count_deltas"] == [{"source_id": "tx_bulk", "before": 10, "after": 12, "delta": 2}]
    assert summary["anchor_ratio_deltas"] == [{"scope": "web", "before": 0.2, "after": 0.3, "delta": 0.1}]
    assert "escalation_path" not in summary
    assert escalation_markdown is None


def test_summarize_pair_run_supports_l11_pair_with_layer_summary_schema(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L11_judge_verdict.json").write_text(
        (source_schema_root / "L11_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L11.json").write_text(
        (source_schema_root / "L11.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "editorial.md",
        role="editorial_review",
        output_schema="evidence_schemas/L11_judge_verdict.json",
        layer="L11",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "editorial_skeptic.md",
        role="editorial_review_skeptic",
        output_schema="evidence_schemas/L11_judge_verdict.json",
        layer="L11",
    )

    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "editorial.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "editorial_skeptic.md",
        scope="web_copy",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    shared_owner_files = [
        "web/src/lib/config/app.ts",
        "web/src/lib/campaign-finance-detail/presentation.ts",
        "web/src/lib/detail-trust/presentation.ts",
        "web/src/lib/civic-detail/presentation.ts",
        "web/src/routes/+page.svelte",
    ]
    shared_rows = [
        {
            "copy_id": "landing-eyebrow",
            "owner_file": "web/src/lib/config/app.ts",
            "text": "Public-records intelligence for journalists",
        },
        {
            "copy_id": "outside-spending-unavailable",
            "owner_file": "web/src/lib/campaign-finance-detail/presentation.ts",
            "text": "Outside-spending data is not yet available for this candidate. Coverage may be incomplete.",
        },
    ]
    _write_verdict(
        repo_root / plan["primary"]["evidence_output_path"],
        role="primary",
        verdict="pass",
        layer="L11",
        scope="web_copy",
        include_criteria=False,
        extra_fields={
            "owner_files": shared_owner_files,
            "rows": shared_rows,
        },
    )
    _write_verdict(
        repo_root / plan["skeptic"]["evidence_output_path"],
        role="skeptic",
        verdict="pass",
        layer="L11",
        scope="web_copy",
        include_criteria=False,
        extra_fields={
            "owner_files": shared_owner_files,
            "rows": shared_rows,
        },
    )

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L11/web_copy/2026-04-24/rows.json"],
    )

    assert plan["combined_output_schema_path"] == "evidence_schemas/L11.json"
    assert summary["layer"] == "L11"
    assert summary["scope"] == "web_copy"
    assert summary["status"] == "pass"
    assert summary["owner_files"] == shared_owner_files
    assert summary["rows"] == shared_rows
    assert "escalation_path" not in summary
    assert escalation_markdown is None


def test_summarize_pair_run_supports_l14_pair_with_layer_summary_schema(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L14_judge_verdict.json").write_text(
        (source_schema_root / "L14_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L14.json").write_text(
        (source_schema_root / "L14.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "coverage.md",
        role="coverage_review",
        output_schema="evidence_schemas/L14_judge_verdict.json",
        layer="L14",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "coverage_skeptic.md",
        role="coverage_review_skeptic",
        output_schema="evidence_schemas/L14_judge_verdict.json",
        layer="L14",
    )

    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "coverage.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "coverage_skeptic.md",
        scope="national_coverage",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    shared_rows = [
        {
            "jurisdiction_code": "CA",
            "name": "California",
            "jurisdiction_type": "state",
            "best_update_frequency": "daily",
            "runner_wired": True,
            "tier": "launch-support candidate",
            "operational_reason": "Daily ingest proven",
            "next_action": "Continue daily refresh",
            "evidence_date": "2026-04-18",
            "loaded_count": 31,
            "expected_count": 31,
            "acquisition_pattern": "bulk_api",
            "discovery_maturity": "interactively_proven",
            "source_contract_maturity": "verified",
            "legal_filing_semantics_maturity": "verified",
            "implementation_maturity": "live_proven",
            "operational_maturity": "operational",
            "public_claim_status": "launch-support candidate",
            "completeness_intelligence_maturity": "gap_detection_ready",
            "civics_candidacy_status": None,
            "main_blocker": "None",
            "nc_geometry_total_count": None,
            "nc_geometry_srid_4326_count": None,
            "nc_geometry_expected_count": None,
            "nc_geometry_counts_match_expected": None,
        },
        {
            "jurisdiction_code": "IN",
            "name": "Indiana",
            "jurisdiction_type": "state",
            "best_update_frequency": "annual",
            "runner_wired": True,
            "tier": "freshness-limited",
            "operational_reason": "Freshness warning shipped",
            "next_action": "Continue cadence monitoring",
            "evidence_date": "2026-04-19",
            "loaded_count": None,
            "expected_count": None,
            "acquisition_pattern": None,
            "discovery_maturity": None,
            "source_contract_maturity": None,
            "legal_filing_semantics_maturity": None,
            "implementation_maturity": None,
            "operational_maturity": None,
            "public_claim_status": None,
            "completeness_intelligence_maturity": None,
            "civics_candidacy_status": None,
            "main_blocker": None,
            "nc_geometry_total_count": None,
            "nc_geometry_srid_4326_count": None,
            "nc_geometry_expected_count": None,
            "nc_geometry_counts_match_expected": None,
        },
    ]
    shared_fields = {
        "registry_path": "docs/research/coverage-registry.json",
        "lifecycle_path": "docs/research/implemented-region-lifecycle.json",
        "lifecycle_updated_at": "2026-04-24",
        "rows": shared_rows,
    }
    _write_verdict(
        repo_root / plan["primary"]["evidence_output_path"],
        role="primary",
        verdict="pass",
        layer="L14",
        scope="national_coverage",
        include_criteria=False,
        extra_fields=shared_fields,
    )
    _write_verdict(
        repo_root / plan["skeptic"]["evidence_output_path"],
        role="skeptic",
        verdict="pass",
        layer="L14",
        scope="national_coverage",
        include_criteria=False,
        extra_fields=shared_fields,
    )

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L14/national_coverage/2026-04-24/rows.json"],
    )

    assert plan["combined_output_schema_path"] == "evidence_schemas/L14.json"
    assert plan["combined_evidence_output_path"] == "evidence/L14/national_coverage/2026-04-24/summary.json"
    assert summary["layer"] == "L14"
    assert summary["scope"] == "national_coverage"
    assert summary["status"] == "pass"
    assert summary["registry_path"] == "docs/research/coverage-registry.json"
    assert summary["lifecycle_path"] == "docs/research/implemented-region-lifecycle.json"
    assert summary["lifecycle_updated_at"] == "2026-04-24"
    assert summary["rows"] == shared_rows
    assert "escalation_path" not in summary
    assert escalation_markdown is None


def test_summarize_pair_run_non_l4_uses_primary_for_one_sided_required_fields(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    _write_schema(schema_root / "L12_judge_verdict.json", layer="L12")
    (schema_root / "L12.json").write_text(
        (source_schema_root / "L12.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "session_output.md",
        role="session_output",
        output_schema="evidence_schemas/L12_judge_verdict.json",
        layer="L12",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "session_output_skeptic.md",
        role="session_output_skeptic",
        output_schema="evidence_schemas/L12_judge_verdict.json",
        layer="L12",
    )

    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "session_output.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "session_output_skeptic.md",
        scope="web",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    primary_only_fields = {
        "session_id": "judge-session-1",
        "changed_files": ["core/keel_adversarial_pair.py"],
        "touched_layers": ["L4", "L12"],
        "produced_evidence_layers": ["L12"],
        "row_count_deltas": [{"source_id": "tx_bulk", "before": 10, "after": 12, "delta": 2}],
        "anchor_ratio_deltas": [{"scope": "web", "before": 0.2, "after": 0.3, "delta": 0.1}],
    }
    _write_verdict(
        repo_root / plan["primary"]["evidence_output_path"],
        role="primary",
        verdict="pass",
        layer="L12",
        scope="web",
        include_criteria=False,
        extra_fields=primary_only_fields,
    )
    _write_verdict(
        repo_root / plan["skeptic"]["evidence_output_path"],
        role="skeptic",
        verdict="pass",
        layer="L12",
        scope="web",
        include_criteria=False,
        extra_fields={"session_id": "judge-session-1"},
    )

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L12/web/2026-04-24/rows.json"],
    )

    assert summary["layer"] == "L12"
    assert summary["status"] == "pass"
    assert summary["changed_files"] == primary_only_fields["changed_files"]
    assert summary["touched_layers"] == primary_only_fields["touched_layers"]
    assert summary["produced_evidence_layers"] == primary_only_fields["produced_evidence_layers"]
    assert summary["row_count_deltas"] == primary_only_fields["row_count_deltas"]
    assert summary["anchor_ratio_deltas"] == primary_only_fields["anchor_ratio_deltas"]
    assert escalation_markdown is None


def test_summarize_pair_run_rejects_missing_required_l4_criterion(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L4_judge_verdict.json").write_text(
        (source_schema_root / "L4_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L4.json").write_text(
        (source_schema_root / "L4.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _rewrite_criteria_ids(
        repo_root / plan["primary"]["evidence_output_path"],
        [
            "trace_completeness",
            "multi_domain_scan",
            "anchor_projection",
            "anchor_projection",
        ],
    )
    _write_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")

    with pytest.raises(ValueError, match="primary verdict must report exactly the four L4 criteria ids"):
        keel_adversarial_pair.summarize_pair_run(
            repo_root=repo_root,
            plan=plan,
            produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
            repo_sha="abc1234",
            gate_command="uv run python -m core.keel_adversarial_pair",
            bundle_artifacts=["evidence/L4/NC/2026-04-24/trace.json"],
        )


def test_summarize_pair_run_rejects_l4_criterion_set_with_duplicate_id(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L4_judge_verdict.json").write_text(
        (source_schema_root / "L4_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L4.json").write_text(
        (source_schema_root / "L4.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")
    _rewrite_criteria_ids(
        repo_root / plan["skeptic"]["evidence_output_path"],
        [
            "trace_completeness",
            "multi_domain_scan",
            "anchor_projection",
            "trace_completeness",
        ],
    )

    with pytest.raises(ValueError, match="skeptic verdict must report exactly the four L4 criteria ids"):
        keel_adversarial_pair.summarize_pair_run(
            repo_root=repo_root,
            plan=plan,
            produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
            repo_sha="abc1234",
            gate_command="uv run python -m core.keel_adversarial_pair",
            bundle_artifacts=["evidence/L4/NC/2026-04-24/trace.json"],
        )


def test_summarize_pair_run_rejects_duplicate_skeptic_l4_criteria(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L4_judge_verdict.json").write_text(
        (source_schema_root / "L4_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L4.json").write_text(
        (source_schema_root / "L4.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")
    _rewrite_criteria_ids(
        repo_root / plan["skeptic"]["evidence_output_path"],
        [
            "trace_completeness",
            "multi_domain_scan",
            "disconfirming_search",
            "disconfirming_search",
        ],
    )

    with pytest.raises(ValueError, match="skeptic verdict must report exactly the four L4 criteria ids"):
        keel_adversarial_pair.summarize_pair_run(
            repo_root=repo_root,
            plan=plan,
            produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
            repo_sha="abc1234",
            gate_command="uv run python -m core.keel_adversarial_pair",
            bundle_artifacts=["evidence/L4/NC/2026-04-24/trace.json"],
        )


def test_summarize_pair_run_supports_l8_threshold_review(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L8_judge_verdict.json").write_text(
        (source_schema_root / "L8_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L8_threshold_review.json").write_text(
        (source_schema_root / "L8_threshold_review.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold.md",
        role="er_threshold",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        role="er_threshold_skeptic",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "er_threshold.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        scope="er_threshold",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_l8_threshold_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_l8_threshold_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L8/regression_run_2026-04-24.json"],
    )

    assert summary["layer"] == "L8"
    assert summary["scope"] == "er_threshold"
    assert summary["status"] == "pass"
    assert summary["pair_outcome"] == "agreement_pass"
    assert plan["summary_schema_path"] == "evidence_schemas/L8_threshold_review.json"
    assert summary["primary_verdict_path"] == "evidence/L8/er_threshold/2026-04-24/er_threshold.json"
    assert summary["skeptic_verdict_path"] == "evidence/L8/er_threshold/2026-04-24/er_threshold_skeptic.json"
    assert summary["escalation_path"] is None
    assert escalation_markdown is None


def test_summarize_pair_run_rejects_missing_required_l8_criterion(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L8_judge_verdict.json").write_text(
        (source_schema_root / "L8_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L8_threshold_review.json").write_text(
        (source_schema_root / "L8_threshold_review.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold.md",
        role="er_threshold",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        role="er_threshold_skeptic",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "er_threshold.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        scope="er_threshold",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_l8_threshold_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _rewrite_criteria_ids(
        repo_root / plan["primary"]["evidence_output_path"],
        [
            "false_positive_risk",
            "regression_pair_safety",
            "regression_pair_safety",
        ],
    )
    _write_l8_threshold_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")

    with pytest.raises(
        ValueError,
        match="primary verdict must report exactly the L8 criteria ids: false_positive_risk, regression_pair_safety, threshold_delta_safety",
    ):
        keel_adversarial_pair.summarize_pair_run(
            repo_root=repo_root,
            plan=plan,
            produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
            repo_sha="abc1234",
            gate_command="uv run python -m core.keel_adversarial_pair",
            bundle_artifacts=["evidence/L8/regression_run_2026-04-24.json"],
        )


def test_build_pair_run_plan_rejects_non_er_threshold_scope_for_l8(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L8_judge_verdict.json").write_text(
        (source_schema_root / "L8_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L8_threshold_review.json").write_text(
        (source_schema_root / "L8_threshold_review.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold.md",
        role="er_threshold",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        role="er_threshold_skeptic",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )

    with pytest.raises(ValueError, match="L8 pair scope must be er_threshold"):
        keel_adversarial_pair.build_pair_run_plan(
            repo_root=repo_root,
            primary_prompt_path=repo_root / "prompts" / "judge" / "er_threshold.md",
            skeptic_prompt_path=repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
            scope="NC",
            session_id="judge-session-1",
            run_date=date(2026, 4, 24),
        )


def test_summarize_pair_run_rejects_plan_scope_mismatch_with_verdict_scope(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L4_judge_verdict.json").write_text(
        (source_schema_root / "L4_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L4.json").write_text(
        (source_schema_root / "L4.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        role="portal_investigation_review",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        role="portal_investigation_review_skeptic",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")
    plan["scope"] = "SC"

    with pytest.raises(ValueError, match="pair plan scope must match verdict scope"):
        keel_adversarial_pair.summarize_pair_run(
            repo_root=repo_root,
            plan=plan,
            produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
            repo_sha="abc1234",
            gate_command="uv run python -m core.keel_adversarial_pair",
            bundle_artifacts=["evidence/L4/NC/2026-04-24/trace.json"],
        )


def test_summarize_pair_run_resolves_summary_schema_path_from_l8_layer(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    source_schema_root = Path(__file__).resolve().parents[2] / "evidence_schemas"
    (schema_root / "L4.json").write_text(
        (source_schema_root / "L4.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L8_judge_verdict.json").write_text(
        (source_schema_root / "L8_judge_verdict.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (schema_root / "L8_threshold_review.json").write_text(
        (source_schema_root / "L8_threshold_review.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold.md",
        role="er_threshold",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    _write_prompt(
        repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        role="er_threshold_skeptic",
        output_schema="evidence_schemas/L8_judge_verdict.json",
        layer="L8",
    )
    plan = keel_adversarial_pair.build_pair_run_plan(
        repo_root=repo_root,
        primary_prompt_path=repo_root / "prompts" / "judge" / "er_threshold.md",
        skeptic_prompt_path=repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        scope="er_threshold",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    _write_l8_threshold_verdict(repo_root / plan["primary"]["evidence_output_path"], role="primary", verdict="pass")
    _write_l8_threshold_verdict(repo_root / plan["skeptic"]["evidence_output_path"], role="skeptic", verdict="pass")
    plan["summary_schema_path"] = "evidence_schemas/L4.json"

    summary, escalation_markdown = keel_adversarial_pair.summarize_pair_run(
        repo_root=repo_root,
        plan=plan,
        produced_at=datetime(2026, 4, 24, 21, 30, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python -m core.keel_adversarial_pair",
        bundle_artifacts=["evidence/L8/regression_run_2026-04-24.json"],
    )

    assert summary["layer"] == "L8"
    assert summary["scope"] == "er_threshold"
    assert summary["status"] == "pass"
    assert summary["pair_outcome"] == "agreement_pass"
    assert escalation_markdown is None
