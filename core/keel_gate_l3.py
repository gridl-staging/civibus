
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from jsonschema.validators import validator_for
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ALLOWED_SOURCE_STATES = frozenset({"discovered", "prototyped", "validated", "operationalized", "degraded", "deferred"})
# Default contract for `operationalized`: at least N consecutive passing L5 evidence_refs.
# 7 covers a full week of weekly-cadence runs; tunable per project later.
_OPERATIONALIZED_MIN_GREEN_RUNS = 7


class EvidenceRef(BaseModel, extra="forbid"):
    layer: str
    scope: str
    path: str


class SourceTransition(BaseModel, extra="forbid"):
    to_state: str
    recorded_on: date
    rationale: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef]


class SourceEntry(BaseModel, extra="forbid"):
    source_id: str = Field(min_length=1)
    current_state: str
    coverage_boundary: str = Field(min_length=1)
    roster_bootstrap: dict[str, object] | None = None
    transitions: list[SourceTransition]


class JurisdictionEntry(BaseModel, extra="forbid"):
    scope: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    ownership: str = Field(min_length=1)
    sources: list[SourceEntry]


class SourcesRegistry(BaseModel, extra="forbid"):
    schema_version: int = Field(ge=1)
    jurisdictions: list[JurisdictionEntry]


class ValidationCheck(BaseModel, extra="forbid"):
    name: str
    ok: bool
    detail: str | None = None


class LinkedEvidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    path: str
    status: str


class L3Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    source_id: str
    current_state: str
    transition_date: date
    linked_evidence: list[LinkedEvidence]
    validation_checks: list[ValidationCheck]


@dataclass(frozen=True, slots=True)
class SourceValidationResult:
    source_id: str
    status: str
    evidence_path: Path
    validation_checks: list[ValidationCheck]


@dataclass(frozen=True, slots=True)
class RegistryEvaluationResult:
    exit_code: int
    source_results: list[SourceValidationResult]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _repo_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=_REPO_ROOT, text=True).strip()


def _load_json_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_registry(path: Path) -> SourcesRegistry:
    return SourcesRegistry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _validate_evidence_payload(*, repo_root: Path, evidence_ref: EvidenceRef) -> tuple[bool, dict[str, object] | None]:
    evidence_path = repo_root / evidence_ref.path
    if not evidence_path.is_file():
        return False, None

    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None

    if not isinstance(payload, dict):
        return False, None

    schema_path = repo_root / "evidence_schemas" / f"{evidence_ref.layer}.json"
    if not schema_path.is_file():
        return False, None

    schema = _load_json_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    if list(validator.iter_errors(payload)):
        return False, payload
    return True, payload


def _check(name: str, ok: bool, detail: str | None = None) -> ValidationCheck:
    return ValidationCheck(name=name, ok=ok, detail=detail)


def _linked_evidence_item(evidence_ref: EvidenceRef, payload: dict[str, object] | None) -> LinkedEvidence:
    status = "error" if payload is None else str(payload.get("status", "error"))
    return LinkedEvidence(
        layer=evidence_ref.layer,
        scope=evidence_ref.scope,
        path=evidence_ref.path,
        status=status,
    )


def _validate_validated_transition(
    *,
    jurisdiction_scope: str,
    linked_evidence: list[LinkedEvidence],
) -> list[ValidationCheck]:
    has_l1_anchor = any(
        evidence.layer == "L1" and evidence.scope == jurisdiction_scope and evidence.status == "pass"
        for evidence in linked_evidence
    )
    has_source_specific_evidence = any(
        evidence.layer != "L1" and evidence.status == "pass" for evidence in linked_evidence
    )
    return [
        _check(
            "validated_has_l1_anchor",
            has_l1_anchor,
            None if has_l1_anchor else f"validated sources must cite a passing L1 anchor for {jurisdiction_scope}",
        ),
        _check(
            "validated_has_source_specific_evidence",
            has_source_specific_evidence,
            None
            if has_source_specific_evidence
            else "validated sources must cite at least one non-L1 pass evidence artifact",
        ),
    ]


def _validate_operationalized_transition(
    *,
    linked_evidence: list[LinkedEvidence],
) -> list[ValidationCheck]:
    """`operationalized` requires N consecutive green L5 evidence_refs.

    Treats each cited L5 evidence_ref as one runner-history sample. The N most
    recent (by `evidence_refs` ordering, which is the YAML-declared order) must
    all have status=pass. The default N is _OPERATIONALIZED_MIN_GREEN_RUNS.
    """
    l5_refs = [item for item in linked_evidence if item.layer == "L5"]
    consecutive_green = 0
    for item in l5_refs:
        if item.status == "pass":
            consecutive_green += 1
        else:
            break
    ok = consecutive_green >= _OPERATIONALIZED_MIN_GREEN_RUNS
    return [
        _check(
            "operationalized_runner_history_consecutive_green",
            ok,
            None
            if ok
            else (
                f"operationalized requires at least {_OPERATIONALIZED_MIN_GREEN_RUNS} "
                f"consecutive passing L5 evidence_refs (got {consecutive_green})"
            ),
        ),
    ]


def _validate_degraded_transition(
    *,
    linked_evidence: list[LinkedEvidence],
) -> list[ValidationCheck]:
    """`degraded` requires at least one passing AND one failing L5 evidence_ref.

    The failing ref proves the source is currently broken; the passing ref
    proves it was working before, distinguishing `degraded` from `prototyped`.
    """
    l5_items = [item for item in linked_evidence if item.layer == "L5"]
    has_failing = any(item.status == "fail" for item in l5_items)
    has_passing = any(item.status == "pass" for item in l5_items)
    return [
        _check(
            "degraded_has_failing_l5_evidence",
            has_failing,
            None
            if has_failing
            else "degraded sources must cite at least one failing L5 evidence_ref to prove the regression",
        ),
        _check(
            "degraded_has_passing_l5_evidence_history",
            has_passing,
            None if has_passing else "degraded sources must also cite a previously-passing L5 evidence_ref",
        ),
    ]


def _validate_deferred_transition(
    *,
    repo_root: Path,
    transition: SourceTransition,
) -> list[ValidationCheck]:
    """`deferred` requires at least one evidence_ref of `layer: docs` whose path
    is under `docs/` and exists. The docs file documents the deferral reason.
    """
    docs_refs = [ref for ref in transition.evidence_refs if ref.layer == "docs"]
    valid_docs = [ref for ref in docs_refs if ref.path.startswith("docs/") and (repo_root / ref.path).is_file()]
    ok = len(valid_docs) >= 1
    return [
        _check(
            "deferred_has_docs_citation",
            ok,
            None if ok else "deferred sources must cite at least one layer=docs evidence_ref with a path under docs/",
        ),
    ]


def validate_source(
    *,
    repo_root: Path,
    jurisdiction_scope: str,
    source: SourceEntry,
) -> tuple[str, SourceTransition, list[LinkedEvidence], list[ValidationCheck]]:
    checks: list[ValidationCheck] = []
    linked_evidence: list[LinkedEvidence] = []

    checks.append(
        _check(
            "current_state_allowed",
            source.current_state in _ALLOWED_SOURCE_STATES,
            None
            if source.current_state in _ALLOWED_SOURCE_STATES
            else f"unsupported current_state {source.current_state!r}",
        )
    )

    last_transition = source.transitions[-1]
    checks.append(
        _check(
            "last_transition_matches_current_state",
            last_transition.to_state == source.current_state,
            None
            if last_transition.to_state == source.current_state
            else f"last transition state {last_transition.to_state!r} does not match current_state",
        )
    )

    state = source.current_state
    for evidence_ref in last_transition.evidence_refs:
        if evidence_ref.layer == "docs":
            # docs/* refs do not carry an evidence schema. Just verify the path exists.
            doc_path = repo_root / evidence_ref.path
            doc_ok = evidence_ref.path.startswith("docs/") and doc_path.is_file()
            linked_evidence.append(
                LinkedEvidence(
                    layer="docs",
                    scope=evidence_ref.scope,
                    path=evidence_ref.path,
                    status="pass" if doc_ok else "error",
                )
            )
            checks.append(
                _check(
                    f"evidence_ref:docs:{evidence_ref.scope}",
                    doc_ok,
                    None if doc_ok else f"docs evidence_ref {evidence_ref.path} must exist under docs/",
                )
            )
            continue

        schema_valid, payload = _validate_evidence_payload(repo_root=repo_root, evidence_ref=evidence_ref)
        linked_evidence.append(_linked_evidence_item(evidence_ref, payload))
        observed_status = str(payload.get("status")) if isinstance(payload, dict) else None
        # For `degraded` transitions, a failing L5 evidence_ref is *expected* and must
        # not be flagged as a per-ref failure. The aggregate degraded contract checks
        # for at least one fail and one pass via _validate_degraded_transition below.
        accepts_failing_ref = state == "degraded" and evidence_ref.layer == "L5"
        per_ref_ok = (
            schema_valid
            and isinstance(payload, dict)
            and payload.get("layer") == evidence_ref.layer
            and payload.get("scope") == evidence_ref.scope
            and (observed_status == "pass" or (accepts_failing_ref and observed_status in {"pass", "fail"}))
        )
        checks.append(
            _check(
                f"evidence_ref:{evidence_ref.layer}:{evidence_ref.scope}",
                per_ref_ok,
                None
                if per_ref_ok
                else (
                    f"evidence ref {evidence_ref.path} must exist, validate, and be a pass for "
                    f"{evidence_ref.layer}/{evidence_ref.scope}"
                ),
            )
        )

    if state == "validated":
        checks.extend(
            _validate_validated_transition(
                jurisdiction_scope=jurisdiction_scope,
                linked_evidence=linked_evidence,
            )
        )
    elif state == "operationalized":
        checks.extend(_validate_operationalized_transition(linked_evidence=linked_evidence))
    elif state == "degraded":
        checks.extend(_validate_degraded_transition(linked_evidence=linked_evidence))
    elif state == "deferred":
        checks.extend(
            _validate_deferred_transition(
                repo_root=repo_root,
                transition=last_transition,
            )
        )

    status = "pass" if all(check.ok for check in checks) else "fail"
    return status, last_transition, linked_evidence, checks


def write_l3_evidence(
    *,
    jurisdiction: str,
    source_id: str,
    current_state: str,
    transition_date: date,
    linked_evidence: list[LinkedEvidence],
    validation_checks: list[ValidationCheck],
    repo_sha: str,
    produced_at: datetime,
    evidence_root: Path,
) -> Path:
    evidence_path = evidence_root / jurisdiction / source_id / f"{current_state}_{transition_date.isoformat()}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = L3Evidence(
        layer="L3",
        scope=jurisdiction,
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command=f"make gate-L3 JURISDICTION={jurisdiction}",
        status="pass" if all(check.ok for check in validation_checks) else "fail",
        source_id=source_id,
        current_state=current_state,
        transition_date=transition_date,
        linked_evidence=linked_evidence,
        validation_checks=validation_checks,
    )
    evidence_path.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return evidence_path


def evaluate_registry(
    *,
    repo_root: Path,
    sources_path: Path,
    jurisdiction: str,
    produced_at: datetime | None = None,
    evidence_root: Path | None = None,
) -> RegistryEvaluationResult:
    registry = _load_registry(sources_path)
    jurisdiction_entry = next((entry for entry in registry.jurisdictions if entry.scope == jurisdiction), None)
    if jurisdiction_entry is None:
        raise ValueError(f"jurisdiction {jurisdiction!r} is not present in {sources_path}")

    resolved_produced_at = _utc_now() if produced_at is None else produced_at
    resolved_evidence_root = repo_root / "evidence" / "L3" if evidence_root is None else evidence_root
    source_results: list[SourceValidationResult] = []
    repo_sha = _repo_sha()

    for source in jurisdiction_entry.sources:
        status, transition, linked_evidence, checks = validate_source(
            repo_root=repo_root,
            jurisdiction_scope=jurisdiction,
            source=source,
        )
        evidence_path = write_l3_evidence(
            jurisdiction=jurisdiction,
            source_id=source.source_id,
            current_state=source.current_state,
            transition_date=transition.recorded_on,
            linked_evidence=linked_evidence,
            validation_checks=checks,
            repo_sha=repo_sha,
            produced_at=resolved_produced_at,
            evidence_root=resolved_evidence_root,
        )
        source_results.append(
            SourceValidationResult(
                source_id=source.source_id,
                status=status,
                evidence_path=evidence_path,
                validation_checks=checks,
            )
        )

    return RegistryEvaluationResult(
        exit_code=0 if all(result.status == "pass" for result in source_results) else 1,
        source_results=source_results,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the project-local Keel L3 source registry")
    parser.add_argument("--jurisdiction", required=True, help="Jurisdiction scope code, e.g. NC")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--sources-path", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    sources_path = (args.sources_path or (repo_root / "sources.yaml")).resolve()
    jurisdiction = args.jurisdiction.upper()

    try:
        result = evaluate_registry(
            repo_root=repo_root,
            sources_path=sources_path,
            jurisdiction=jurisdiction,
            evidence_root=args.evidence_root,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L3 failed for {jurisdiction}: {error}", file=sys.stderr)
        return 1

    for source_result in result.source_results:
        print(
            f"{source_result.status.upper()}: jurisdiction={jurisdiction} source_id={source_result.source_id} "
            f"evidence={source_result.evidence_path}"
        )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
