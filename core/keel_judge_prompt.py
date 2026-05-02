
from __future__ import annotations
"""Stub summary for keel_judge_prompt.py."""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from jsonschema.validators import validator_for
from pydantic import BaseModel, Field

_REQUIRED_SECTIONS = (
    "Goal",
    "Context (allowed)",
    "Rubric",
    "Output format",
    "Calibration examples",
)
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class JudgePromptFrontmatter(BaseModel, extra="forbid"):
    layer: str = Field(pattern=r"^L[0-9]+$")
    role: str = Field(min_length=1)
    model: str = Field(min_length=1)
    allowed_inputs: list[str] = Field(min_length=1)
    forbidden_inputs: list[str]
    output_schema: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class JudgePromptTemplate:
    path: Path
    frontmatter: JudgePromptFrontmatter
    body: str


def _require_path_within_repo(*, repo_root: Path, candidate_path: Path, description: str) -> Path:
    resolved_repo_root = repo_root.resolve()
    resolved_candidate = candidate_path.resolve()
    try:
        resolved_candidate.relative_to(resolved_repo_root)
    except ValueError as error:
        raise ValueError(f"{description} must stay within the repo: {candidate_path}") from error
    return resolved_candidate


def _split_frontmatter(markdown: str) -> tuple[str, str]:
    if not markdown.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")

    parts = markdown.split("\n---\n", 1)
    if len(parts) != 2:
        raise ValueError("missing closing YAML frontmatter delimiter")
    _, remainder = parts
    frontmatter_text = markdown[len("---\n") : len(markdown) - len(remainder) - len("\n---\n")]
    return frontmatter_text, remainder.lstrip()


def _validate_body_sections(body: str) -> None:
    missing_sections = [section for section in _REQUIRED_SECTIONS if f"## {section}" not in body]
    if missing_sections:
        raise ValueError(f"missing required section(s): {', '.join(missing_sections)}")


def _validate_output_schema(*, repo_root: Path, output_schema: str) -> str:
    schema_path = _require_path_within_repo(
        repo_root=repo_root,
        candidate_path=repo_root / output_schema,
        description="output_schema path",
    )
    if not schema_path.is_file():
        raise ValueError(f"output_schema path does not exist: {output_schema}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    return schema_path.relative_to(repo_root).as_posix()


def load_judge_prompt(prompt_path: Path, *, repo_root: Path) -> JudgePromptTemplate:
    resolved_prompt_path = _require_path_within_repo(
        repo_root=repo_root,
        candidate_path=prompt_path,
        description="prompt path",
    )
    if not resolved_prompt_path.is_file():
        raise ValueError(f"prompt does not exist: {prompt_path}")

    frontmatter_text, body = _split_frontmatter(resolved_prompt_path.read_text(encoding="utf-8"))
    frontmatter = JudgePromptFrontmatter.model_validate(yaml.safe_load(frontmatter_text))
    if not _SEMVER_PATTERN.fullmatch(frontmatter.rubric_version):
        raise ValueError("rubric_version must use semver (for example 0.1.0)")

    _validate_body_sections(body)
    _validate_output_schema(repo_root=repo_root, output_schema=frontmatter.output_schema)
    return JudgePromptTemplate(
        path=resolved_prompt_path,
        frontmatter=frontmatter,
        body=body,
    )


def build_judge_manifest(
    *,
    prompt: JudgePromptTemplate,
    repo_root: Path,
    scope: str,
    session_id: str,
    run_date: date,
) -> dict[str, object]:
    schema_path = _validate_output_schema(repo_root=repo_root, output_schema=prompt.frontmatter.output_schema)
    run_date_text = run_date.isoformat()
    return {
        "layer": prompt.frontmatter.layer,
        "role": prompt.frontmatter.role,
        "model": prompt.frontmatter.model,
        "scope": scope,
        "session_id": session_id,
        "prompt_path": prompt.path.relative_to(repo_root).as_posix(),
        "allowed_inputs": prompt.frontmatter.allowed_inputs,
        "forbidden_inputs": prompt.frontmatter.forbidden_inputs,
        "rubric_version": prompt.frontmatter.rubric_version,
        "output_schema_path": schema_path,
        "evidence_output_path": f"evidence/{prompt.frontmatter.layer}/{scope}/{run_date_text}.json",
        "escalation_output_dir": f"escalations/{run_date_text}",
        "findings_output_path": f"findings/{run_date_text}.md",
        "reserved_paths": {
            "prompts_judge": "prompts/judge",
            "findings": "findings",
            "escalations": "escalations",
            "tickets": "tickets",
            "waivers": "waivers",
        },
    }
