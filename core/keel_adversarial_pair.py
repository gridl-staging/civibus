
from __future__ import annotations
"""Stub summary for keel_adversarial_pair.py."""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from jsonschema.validators import validator_for

from core.keel_judge_prompt import build_judge_manifest, load_judge_prompt

# Layers with strict criteria-id validation (L4-style criteria pair checks).
# Layers not listed here (e.g. L11, L14) fall through to the
# `_build_non_l4_summary_payload` path that merges required summary fields
# from the underlying verdict payloads.
_LAYER_PAIR_CONTRACTS: dict[str, dict[str, object]] = {
    "L4": {
        "criteria_ids": (
            "anchor_projection",
            "disconfirming_search",
            "multi_domain_scan",
            "trace_completeness",
        ),
        "required_scope": None,
        "summary_schema_path": "evidence_schemas/L4.json",
        "escalation_resolution_framing": (
            "- Re-read the L4 bundle artifacts and decide whether the skeptical objection reflects a real missed path."
        ),
    },
    "L8": {
        "criteria_ids": (
            "false_positive_risk",
            "regression_pair_safety",
            "threshold_delta_safety",
        ),
        "required_scope": "er_threshold",
        "summary_schema_path": "evidence_schemas/L8_threshold_review.json",
        "escalation_resolution_framing": (
            "- Re-read the L8 regression evidence and decide whether the proposed threshold change preserves the false-positive guardrails."
        ),
    },
}


def _has_strict_contract(layer: str) -> bool:
    """Return True if the layer has L4-style criteria-pair validation."""
    return layer in _LAYER_PAIR_CONTRACTS


def _layer_contract(layer: str) -> dict[str, object]:
    try:
        return _LAYER_PAIR_CONTRACTS[layer]
    except KeyError as error:
        raise ValueError(f"unsupported adversarial-pair layer: {layer}") from error


def _bundle_directory(*, layer: str, scope: str, run_date: date) -> str:
    return f"evidence/{layer}/{scope}/{run_date.isoformat()}"


def _role_evidence_output_path(*, layer: str, scope: str, run_date: date, role: str) -> str:
    return f"{_bundle_directory(layer=layer, scope=scope, run_date=run_date)}/{role}.json"


def _load_schema(schema_path: Path) -> dict:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _load_validated_payload(*, payload_path: Path, schema_path: Path) -> dict[str, object]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    schema = _load_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise ValueError(f"schema-invalid payload at {payload_path}: {errors[0].message}")
    return payload


def _validate_inline_payload(*, payload: dict[str, object], schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise ValueError(f"schema-invalid pair summary: {errors[0].message}")


def _build_non_l4_summary_payload(
    *,
    summary_schema_path: Path,
    base_summary: dict[str, object],
    primary_payload: dict[str, object],
    skeptic_payload: dict[str, object],
) -> dict[str, object]:
    summary = dict(base_summary)
    summary_schema = _load_schema(summary_schema_path)
    required_fields = summary_schema.get("required")
    if not isinstance(required_fields, list):
        raise ValueError(f"invalid summary schema at {summary_schema_path}: required must be a list")

    for required_field in required_fields:
        if not isinstance(required_field, str):
            raise ValueError(f"invalid summary schema at {summary_schema_path}: required entries must be strings")
        if required_field in summary:
            continue

        primary_has_field = required_field in primary_payload
        skeptic_has_field = required_field in skeptic_payload
        if not primary_has_field and not skeptic_has_field:
            raise ValueError(
                "non-L4 pair summary missing required field from verdict payloads: "
                f"{required_field} (required by {summary_schema_path})"
            )
        if primary_has_field and skeptic_has_field and primary_payload[required_field] != skeptic_payload[required_field]:
            raise ValueError(
                "non-L4 pair verdicts disagree on required summary field "
                f"{required_field}: primary={primary_payload[required_field]!r}, "
                f"skeptic={skeptic_payload[required_field]!r}"
            )

        if primary_has_field:
            summary[required_field] = primary_payload[required_field]
        else:
            summary[required_field] = skeptic_payload[required_field]
    return summary


def _summary_schema_path(*, repo_root: Path, layer: str) -> str:
    """Resolve the summary schema path for ``layer``.

    Layers with a strict contract use their declared ``summary_schema_path``; other
    layers fall back to the conventional ``evidence_schemas/{layer}.json`` location
    (used by L11/L14 and any future "merge required fields" style layer).
    """
    if _has_strict_contract(layer):
        relative = str(_layer_contract(layer)["summary_schema_path"])
        schema_path = repo_root / relative
        if not schema_path.is_file():
            raise ValueError(f"missing pair summary schema for {layer}: {schema_path}")
        _load_schema(schema_path)
        return relative
    schema_path = repo_root / "evidence_schemas" / f"{layer}.json"
    if not schema_path.is_file():
        raise ValueError(f"missing pair summary schema for {layer}: {schema_path}")
    _load_schema(schema_path)
    return schema_path.relative_to(repo_root).as_posix()


def _validate_criteria_payload(*, payload: dict[str, object], role: str, layer: str) -> dict[str, str]:
    """Validate the criteria block of a strict-contract pair verdict (L4/L8)."""
    criteria = payload.get("criteria")
    if not isinstance(criteria, list):
        raise ValueError(f"{role} verdict must include a criteria list")

    expected_criterion_ids = tuple(_layer_contract(layer)["criteria_ids"])
    criteria_ids = [str(item.get("id")) for item in criteria if isinstance(item, dict)]
    if sorted(criteria_ids) != list(expected_criterion_ids):
        if layer == "L4":
            message = f"{role} verdict must report exactly the four L4 criteria ids: "
        else:
            message = f"{role} verdict must report exactly the {layer} criteria ids: "
        raise ValueError(message + ", ".join(expected_criterion_ids))

    return {str(item["id"]): str(item["result"]) for item in criteria if isinstance(item, dict)}


def build_pair_run_plan(
    *,
    repo_root: Path,
    primary_prompt_path: Path,
    skeptic_prompt_path: Path,
    scope: str,
    session_id: str,
    run_date: date,
) -> dict[str, object]:
    primary_prompt = load_judge_prompt(primary_prompt_path, repo_root=repo_root)
    skeptic_prompt = load_judge_prompt(skeptic_prompt_path, repo_root=repo_root)

    if primary_prompt.frontmatter.layer != skeptic_prompt.frontmatter.layer:
        raise ValueError("primary and skeptic prompts must target the same layer")
    if primary_prompt.frontmatter.output_schema != skeptic_prompt.frontmatter.output_schema:
        raise ValueError("primary and skeptic prompts must share the same output_schema")
    if primary_prompt.frontmatter.role == skeptic_prompt.frontmatter.role:
        raise ValueError("primary and skeptic prompts must use distinct roles")

    layer = str(primary_prompt.frontmatter.layer)
    if _has_strict_contract(layer):
        required_scope = _layer_contract(layer)["required_scope"]
        if required_scope is not None and scope != required_scope:
            raise ValueError(f"{layer} pair scope must be {required_scope}")

    primary_manifest = build_judge_manifest(
        prompt=primary_prompt,
        repo_root=repo_root,
        scope=scope,
        session_id=session_id,
        run_date=run_date,
    )
    skeptic_manifest = build_judge_manifest(
        prompt=skeptic_prompt,
        repo_root=repo_root,
        scope=scope,
        session_id=session_id,
        run_date=run_date,
    )

    bundle_directory = _bundle_directory(layer=layer, scope=scope, run_date=run_date)
    primary_manifest["evidence_output_path"] = _role_evidence_output_path(
        layer=layer,
        scope=scope,
        run_date=run_date,
        role=str(primary_prompt.frontmatter.role),
    )
    skeptic_manifest["evidence_output_path"] = _role_evidence_output_path(
        layer=layer,
        scope=scope,
        run_date=run_date,
        role=str(skeptic_prompt.frontmatter.role),
    )

    summary_path = _summary_schema_path(repo_root=repo_root, layer=layer)
    return {
        "layer": layer,
        "scope": scope,
        "run_date": run_date.isoformat(),
        "bundle_directory": bundle_directory,
        # `combined_output_schema_path` is the historic L11/L14-side field name.
        # `summary_schema_path` is the L8/L4 side name from the layer contract.
        # Both expose the same value so callers/tests on either side keep working.
        "combined_output_schema_path": summary_path,
        "combined_evidence_output_path": f"{bundle_directory}/summary.json",
        "summary_schema_path": summary_path,
        "escalation_output_path": f"escalations/{run_date.isoformat()}/{layer}_{scope}.md",
        "primary": primary_manifest,
        "skeptic": skeptic_manifest,
    }


def summarize_pair_run(
    *,
    repo_root: Path,
    plan: dict[str, object],
    produced_at: datetime,
    repo_sha: str,
    gate_command: str,
    bundle_artifacts: list[str],
) -> tuple[dict[str, object], str | None]:
    primary_manifest = dict(plan["primary"])
    skeptic_manifest = dict(plan["skeptic"])
    primary_payload = _load_validated_payload(
        payload_path=repo_root / str(primary_manifest["evidence_output_path"]),
        schema_path=repo_root / str(primary_manifest["output_schema_path"]),
    )
    skeptic_payload = _load_validated_payload(
        payload_path=repo_root / str(skeptic_manifest["evidence_output_path"]),
        schema_path=repo_root / str(skeptic_manifest["output_schema_path"]),
    )

    if primary_payload["layer"] != skeptic_payload["layer"]:
        raise ValueError("pair verdicts must target the same layer")
    if primary_payload["scope"] != skeptic_payload["scope"]:
        raise ValueError("pair verdicts must target the same scope")

    layer = str(primary_payload["layer"])
    scope = str(primary_payload["scope"])
    if str(plan["layer"]) != layer:
        raise ValueError("pair plan layer must match verdict layer")
    if str(plan["scope"]) != scope:
        raise ValueError("pair plan scope must match verdict scope")

    # Resolve summary schema authoritatively from the layer (not from plan), so
    # callers can't quietly point summarize at the wrong schema.
    summary_schema_path = repo_root / _summary_schema_path(repo_root=repo_root, layer=layer)

    criteria_summary: list[dict[str, str]] = []
    if _has_strict_contract(layer):
        primary_criteria = _validate_criteria_payload(payload=primary_payload, role="primary", layer=layer)
        skeptic_criteria = _validate_criteria_payload(payload=skeptic_payload, role="skeptic", layer=layer)
        if set(primary_criteria) != set(skeptic_criteria):
            raise ValueError("pair verdicts must report the same criteria ids")
        criteria_summary = [
            {
                "id": criterion_id,
                "primary_result": primary_criteria[criterion_id],
                "skeptic_result": skeptic_criteria[criterion_id],
            }
            for criterion_id in sorted(primary_criteria)
        ]

    primary_verdict = str(primary_payload["verdict"])
    skeptic_verdict = str(skeptic_payload["verdict"])
    escalation_path: str | None = None
    escalation_markdown: str | None = None

    if primary_verdict == skeptic_verdict == "pass":
        status = "pass"
        pair_outcome = "agreement_pass"
    elif primary_verdict == skeptic_verdict == "fail":
        status = "fail"
        pair_outcome = "agreement_fail"
    else:
        status = "fail"
        pair_outcome = "escalated"
        escalation_path = str(plan["escalation_output_path"])
        if _has_strict_contract(layer):
            framing = str(_layer_contract(layer)["escalation_resolution_framing"])
        else:
            framing = (
                f"- Re-read the {layer} bundle artifacts and decide whether the skeptical objection reflects "
                "a real missed path."
            )
        escalation_markdown = "\n".join(
            [
                f"# {layer} Escalation — {scope}",
                "",
                f"- Primary role: {primary_manifest['role']} -> `{primary_verdict}`",
                f"- Skeptic role: {skeptic_manifest['role']} -> `{skeptic_verdict}`",
                f"- Summary evidence: `{plan['combined_evidence_output_path']}`",
                "",
                "## Resolution framing",
                "",
                framing,
            ]
        )

    summary_base: dict[str, object] = {
        "layer": layer,
        "scope": scope,
        "schema_version": 1,
        "produced_at_utc": produced_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "repo_sha": repo_sha,
        "gate_command": gate_command,
        "status": status,
    }

    if _has_strict_contract(layer):
        summary: dict[str, object] = {
            **summary_base,
            "primary_verdict": primary_verdict,
            "skeptic_verdict": skeptic_verdict,
            "pair_outcome": pair_outcome,
            "primary_verdict_path": str(primary_manifest["evidence_output_path"]),
            "skeptic_verdict_path": str(skeptic_manifest["evidence_output_path"]),
            "bundle_artifacts": bundle_artifacts,
            "criteria_summary": criteria_summary,
            "escalation_path": escalation_path,
        }
    else:
        summary = _build_non_l4_summary_payload(
            summary_schema_path=summary_schema_path,
            base_summary=summary_base,
            primary_payload=primary_payload,
            skeptic_payload=skeptic_payload,
        )
        if "escalation_path" in summary:
            summary["escalation_path"] = escalation_path

    _validate_inline_payload(payload=summary, schema_path=summary_schema_path)
    return summary, escalation_markdown


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a project-local Keel adversarial-pair run plan")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--primary-prompt", type=Path, required=True)
    parser.add_argument("--skeptic-prompt", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--run-date", type=date.fromisoformat, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    plan = build_pair_run_plan(
        repo_root=args.repo_root.resolve(),
        primary_prompt_path=args.primary_prompt,
        skeptic_prompt_path=args.skeptic_prompt,
        scope=args.scope,
        session_id=args.session_id,
        run_date=args.run_date,
    )
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
