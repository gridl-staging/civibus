from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import core.keel_judge_prompt as keel_judge_prompt


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


def test_load_judge_prompt_parses_frontmatter_and_builds_manifest(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_path = repo_root / "evidence_schemas" / "judge_output.json"
    schema_path.parent.mkdir(parents=True)
    _write_schema(schema_path)
    prompt_path = repo_root / "prompts" / "judge" / "portal_investigation_review.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text(
        """---
layer: L4
role: portal_investigation_review
model: gpt-5.4
allowed_inputs:
  - web_search
  - evidence/L4/NC/2026-04-24/
forbidden_inputs:
  - repo_read
  - prior_research_docs
output_schema: evidence_schemas/judge_output.json
rubric_version: 0.1.0
---
## Goal

Decide whether the portal investigation exhausted plausible acquisition paths.

## Context (allowed)

Read only the listed investigation artifacts and the live portal.

## Rubric

- Pass if the trace, multi-domain scan, and disconfirming search are all present and coherent.

## Output format

Return JSON matching the declared schema.

## Calibration examples

- Pass: exhaustive trace with documented dead ends.
""",
        encoding="utf-8",
    )

    prompt = keel_judge_prompt.load_judge_prompt(prompt_path, repo_root=repo_root)
    manifest = keel_judge_prompt.build_judge_manifest(
        prompt=prompt,
        repo_root=repo_root,
        scope="NC",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    assert prompt.frontmatter.layer == "L4"
    assert prompt.frontmatter.rubric_version == "0.1.0"
    assert manifest["evidence_output_path"] == "evidence/L4/NC/2026-04-24.json"
    assert manifest["escalation_output_dir"] == "escalations/2026-04-24"
    assert manifest["output_schema_path"] == "evidence_schemas/judge_output.json"
    assert manifest["reserved_paths"]["prompts_judge"] == "prompts/judge"


def test_non_l4_prompt_pair_reuses_shared_validated_output_schema(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_path = repo_root / "evidence_schemas" / "l7_judge_output.json"
    schema_path.parent.mkdir(parents=True)
    _write_schema(schema_path, layer="L7")
    prompt_root = repo_root / "prompts" / "judge"
    prompt_root.mkdir(parents=True)
    primary_prompt_path = prompt_root / "ops_readiness_review.md"
    skeptic_prompt_path = prompt_root / "ops_readiness_review_skeptic.md"
    prompt_template = """---
layer: L7
role: {role}
model: gpt-5.4
allowed_inputs:
  - evidence/L7/OPS/2026-04-24/
forbidden_inputs:
  - repo_read
output_schema: evidence_schemas/l7_judge_output.json
rubric_version: 0.1.0
---
## Goal

Decide whether the OPS readiness investigation has enough evidence.

## Context (allowed)

Read only the listed investigation artifacts.

## Rubric

- Pass if evidence and rationale are coherent.

## Output format

Return JSON matching the declared schema.

## Calibration examples

- Pass: complete evidence trace.
"""
    primary_prompt_path.write_text(prompt_template.format(role="ops_readiness_review"), encoding="utf-8")
    skeptic_prompt_path.write_text(prompt_template.format(role="ops_readiness_review_skeptic"), encoding="utf-8")

    primary_prompt = keel_judge_prompt.load_judge_prompt(primary_prompt_path, repo_root=repo_root)
    skeptic_prompt = keel_judge_prompt.load_judge_prompt(skeptic_prompt_path, repo_root=repo_root)
    primary_manifest = keel_judge_prompt.build_judge_manifest(
        prompt=primary_prompt,
        repo_root=repo_root,
        scope="OPS",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    skeptic_manifest = keel_judge_prompt.build_judge_manifest(
        prompt=skeptic_prompt,
        repo_root=repo_root,
        scope="OPS",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    assert primary_prompt.frontmatter.layer == "L7"
    assert skeptic_prompt.frontmatter.layer == "L7"
    assert primary_prompt.frontmatter.output_schema == "evidence_schemas/l7_judge_output.json"
    assert primary_prompt.frontmatter.output_schema == skeptic_prompt.frontmatter.output_schema
    assert primary_manifest["output_schema_path"] == "evidence_schemas/l7_judge_output.json"
    assert primary_manifest["output_schema_path"] == skeptic_manifest["output_schema_path"]
    assert primary_manifest["evidence_output_path"] == "evidence/L7/OPS/2026-04-24.json"


def test_load_judge_prompt_rejects_missing_required_section(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_path = repo_root / "evidence_schemas" / "judge_output.json"
    schema_path.parent.mkdir(parents=True)
    _write_schema(schema_path)
    prompt_path = repo_root / "prompts" / "judge" / "portal_investigation_review.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text(
        """---
layer: L4
role: portal_investigation_review
model: gpt-5.4
allowed_inputs:
  - web_search
forbidden_inputs:
  - repo_read
output_schema: evidence_schemas/judge_output.json
rubric_version: 0.1.0
---
## Goal

Decide whether the portal investigation exhausted plausible acquisition paths.

## Context (allowed)

Read only the listed investigation artifacts and the live portal.

## Rubric

- Pass if the trace, multi-domain scan, and disconfirming search are all present and coherent.

## Output format

Return JSON matching the declared schema.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required section\\(s\\): Calibration examples"):
        keel_judge_prompt.load_judge_prompt(prompt_path, repo_root=repo_root)


def test_load_judge_prompt_rejects_output_schema_path_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_schema = tmp_path / "outside.json"
    _write_schema(external_schema)
    prompt_path = repo_root / "prompts" / "judge" / "portal_investigation_review.md"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text(
        """---
layer: L4
role: portal_investigation_review
model: gpt-5.4
allowed_inputs:
  - web_search
forbidden_inputs:
  - repo_read
output_schema: ../outside.json
rubric_version: 0.1.0
---
## Goal

Decide whether the portal investigation exhausted plausible acquisition paths.

## Context (allowed)

Read only the listed investigation artifacts and the live portal.

## Rubric

- Pass if the trace, multi-domain scan, and disconfirming search are all present and coherent.

## Output format

Return JSON matching the declared schema.

## Calibration examples

- Pass: exhaustive trace with documented dead ends.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="output_schema path must stay within the repo"):
        keel_judge_prompt.load_judge_prompt(prompt_path, repo_root=repo_root)


def test_repo_portal_investigation_prompt_pair_loads_with_shared_schema() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    primary_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review.md",
        repo_root=repo_root,
    )
    skeptic_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "portal_investigation_review_skeptic.md",
        repo_root=repo_root,
    )

    assert primary_prompt.frontmatter.layer == "L4"
    assert skeptic_prompt.frontmatter.layer == "L4"
    assert primary_prompt.frontmatter.role == "portal_investigation_review"
    assert skeptic_prompt.frontmatter.role == "portal_investigation_review_skeptic"
    assert primary_prompt.frontmatter.output_schema == skeptic_prompt.frontmatter.output_schema


def test_repo_editorial_prompt_pair_loads_with_shared_schema() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    primary_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "editorial.md",
        repo_root=repo_root,
    )
    skeptic_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "editorial_skeptic.md",
        repo_root=repo_root,
    )

    assert primary_prompt.frontmatter.layer == "L11"
    assert skeptic_prompt.frontmatter.layer == "L11"
    assert primary_prompt.frontmatter.role == "editorial_review"
    assert skeptic_prompt.frontmatter.role == "editorial_review_skeptic"
    assert primary_prompt.frontmatter.output_schema == "evidence_schemas/L11_judge_verdict.json"
    assert primary_prompt.frontmatter.output_schema == skeptic_prompt.frontmatter.output_schema


def test_repo_coverage_prompt_pair_loads_with_shared_schema() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    primary_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "coverage.md",
        repo_root=repo_root,
    )
    skeptic_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "coverage_skeptic.md",
        repo_root=repo_root,
    )

    assert primary_prompt.frontmatter.layer == "L14"
    assert skeptic_prompt.frontmatter.layer == "L14"
    assert primary_prompt.frontmatter.role == "coverage_review"
    assert skeptic_prompt.frontmatter.role == "coverage_review_skeptic"
    assert primary_prompt.frontmatter.output_schema == "evidence_schemas/L14_judge_verdict.json"
    assert primary_prompt.frontmatter.output_schema == skeptic_prompt.frontmatter.output_schema


def test_repo_er_threshold_prompt_pair_loads_with_shared_schema() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    primary_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "er_threshold.md",
        repo_root=repo_root,
    )
    skeptic_prompt = keel_judge_prompt.load_judge_prompt(
        repo_root / "prompts" / "judge" / "er_threshold_skeptic.md",
        repo_root=repo_root,
    )

    assert primary_prompt.frontmatter.layer == "L8"
    assert skeptic_prompt.frontmatter.layer == "L8"
    assert primary_prompt.frontmatter.role == "er_threshold"
    assert skeptic_prompt.frontmatter.role == "er_threshold_skeptic"
    assert primary_prompt.frontmatter.output_schema == skeptic_prompt.frontmatter.output_schema

    primary_manifest = keel_judge_prompt.build_judge_manifest(
        prompt=primary_prompt,
        repo_root=repo_root,
        scope="er_threshold",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )
    skeptic_manifest = keel_judge_prompt.build_judge_manifest(
        prompt=skeptic_prompt,
        repo_root=repo_root,
        scope="er_threshold",
        session_id="judge-session-1",
        run_date=date(2026, 4, 24),
    )

    assert primary_manifest["role"] == "er_threshold"
    assert skeptic_manifest["role"] == "er_threshold_skeptic"
    assert primary_manifest["role"] != skeptic_manifest["role"]
    assert primary_manifest["output_schema_path"] == "evidence_schemas/L8_judge_verdict.json"
    assert skeptic_manifest["output_schema_path"] == "evidence_schemas/L8_judge_verdict.json"
    assert primary_manifest["evidence_output_path"] == "evidence/L8/er_threshold/2026-04-24.json"
    assert skeptic_manifest["evidence_output_path"] == "evidence/L8/er_threshold/2026-04-24.json"
