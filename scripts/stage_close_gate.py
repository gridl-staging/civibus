
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import yaml
from jsonschema.validators import validator_for

from core.keel_emitted_evidence import latest_emitted_payload_by_key
from core.keel_judge_prompt import load_judge_prompt

_DATE_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ESCALATION_FILE_RE = re.compile(r"^L\d+_.+\.md$")
_TICKET_FILE_RE = re.compile(r"^reinvestigate_.+_\d{4}-\d{2}-\d{2}\.md$")


@dataclass(frozen=True, slots=True)
class LayerCheck:
    layer_id: str
    ok: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StageCloseResult:
    exit_code: int
    touched_layers: list[str]
    failures: list[str]


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_schema(schema_path: Path) -> dict:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate_yaml_payload(*, payload_path: Path, schema_path: Path) -> tuple[bool, dict[str, object] | None]:
    payload = yaml.safe_load(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False, None

    schema = _load_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    if list(validator.iter_errors(payload)):
        return False, payload
    return True, payload


def _validate_evidence_payload(*, evidence_path: Path, schema_path: Path) -> tuple[bool, dict[str, object] | None]:
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None

    if not isinstance(payload, dict):
        return False, None

    schema = _load_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    if list(validator.iter_errors(payload)):
        return False, payload
    return True, payload


def _path_matches_any_pattern(path: str, patterns: list[str]) -> bool:
    pure_path = PurePosixPath(path)
    return any(pure_path.match(pattern) for pattern in patterns)


def touched_layers_for_files(*, changed_files: list[str], layers_payload: dict) -> list[dict]:
    touched_layers: list[dict] = []
    for layer in layers_payload["layers"]:
        patterns = layer.get("file_path_triggers", [])
        if any(_path_matches_any_pattern(path, patterns) for path in changed_files):
            touched_layers.append(layer)
    return touched_layers


def _latest_evidence_date(scope_root: Path) -> date | None:
    dated_files = []
    for candidate in scope_root.glob("*.json"):
        try:
            dated_files.append(date.fromisoformat(candidate.stem))
        except ValueError:
            continue
    return max(dated_files, default=None)


def _latest_emitted_payload_by_key(
    *,
    repo_root: Path,
    layer: dict,
    key_field: str,
    scope_filter_field: str | None = None,
    scope_filter_value: str | None = None,
) -> dict[str, tuple[Path, bool, dict[str, object] | None]]:
    latest_by_scope = latest_emitted_payload_by_key(
        repo_root=repo_root,
        layer=layer,
        key_field=key_field,
        scope_filter_field=scope_filter_field,
        scope_filter_value=scope_filter_value,
    )
    return {
        scope: (evidence.evidence_path, evidence.schema_valid, evidence.payload)
        for scope, evidence in latest_by_scope.items()
    }


def _format_scope_list(scopes: list[str]) -> str:
    return ", ".join(scopes)


def _emitted_value_label(field: str) -> str:
    if field == "scope":
        return "scopes"
    return f"{field} values"


def _waiver_allows_failure(
    *,
    repo_root: Path,
    layer_id: str,
    scope: str,
    evidence_path: Path,
    current_time_utc: datetime,
) -> LayerCheck | None:
    waiver_root = repo_root / "waivers"
    if not waiver_root.is_dir():
        return None

    waiver_schema_path = repo_root / "evidence_schemas" / "waiver.json"
    expected_evidence_path = evidence_path.relative_to(repo_root).as_posix()
    invalid_waiver_reason: str | None = None
    expired_waiver_reason: str | None = None

    for waiver_path in sorted(waiver_root.glob(f"{layer_id}_{scope}_*.yaml")):
        schema_valid, payload = _validate_yaml_payload(payload_path=waiver_path, schema_path=waiver_schema_path)
        if not schema_valid:
            invalid_waiver_reason = f"{layer_id}: schema-invalid waiver at {waiver_path.relative_to(repo_root)}"
            continue

        assert payload is not None
        if payload["layer"] != layer_id or payload["scope"] != scope:
            invalid_waiver_reason = f"{layer_id}: mismatched waiver metadata at {waiver_path.relative_to(repo_root)}"
            continue
        if payload["evidence_path"] != expected_evidence_path:
            continue

        expires_at = datetime.fromisoformat(str(payload["expires_at_utc"]))
        if expires_at <= current_time_utc:
            expired_waiver_reason = f"{layer_id}: expired waiver at {waiver_path.relative_to(repo_root)}"
            continue

        return LayerCheck(layer_id=layer_id, ok=True)

    if expired_waiver_reason is not None:
        return LayerCheck(layer_id=layer_id, ok=False, reason=expired_waiver_reason)
    if invalid_waiver_reason is not None:
        return LayerCheck(layer_id=layer_id, ok=False, reason=invalid_waiver_reason)
    return None


def _fixed_scope_check(*, repo_root: Path, layer: dict, today_utc: date) -> LayerCheck:
    layer_id = layer["id"]
    scope = layer["scope_strategy"]["value"]
    evidence_root = repo_root / "evidence" / layer_id / scope
    today_path = evidence_root / f"{today_utc.isoformat()}.json"
    if today_path.is_file():
        schema_path = repo_root / layer["required_evidence"]["schema"]
        schema_valid, payload = _validate_evidence_payload(evidence_path=today_path, schema_path=schema_path)
        if not schema_valid:
            return LayerCheck(
                layer_id=layer_id,
                ok=False,
                reason=f"{layer_id}: schema-invalid evidence at {today_path.relative_to(repo_root)}",
            )
        if payload is None or payload.get("status") != "pass":
            waiver_result = _waiver_allows_failure(
                repo_root=repo_root,
                layer_id=layer_id,
                scope=scope,
                evidence_path=today_path,
                current_time_utc=_now_utc(),
            )
            if waiver_result is not None:
                return waiver_result
            return LayerCheck(
                layer_id=layer_id,
                ok=False,
                reason=f"{layer_id}: non-passing evidence status at {today_path.relative_to(repo_root)}",
            )
        return LayerCheck(layer_id=layer_id, ok=True)

    latest_date = _latest_evidence_date(evidence_root) if evidence_root.is_dir() else None
    if latest_date is None:
        return LayerCheck(
            layer_id=layer_id,
            ok=False,
            reason=f"{layer_id}: missing fresh evidence for fixed scope '{scope}'",
        )
    return LayerCheck(
        layer_id=layer_id,
        ok=False,
        reason=f"{layer_id}: stale evidence for fixed scope '{scope}' (latest is {latest_date.isoformat()})",
    )


def _emitted_scope_check(*, repo_root: Path, layer: dict, today_utc: date) -> LayerCheck:
    layer_id = layer["id"]
    scope_strategy = layer["scope_strategy"]
    field = str(scope_strategy.get("field", "scope"))
    expected_scopes = list(scope_strategy.get("expected_scopes", []))
    latest_by_scope = _latest_emitted_payload_by_key(
        repo_root=repo_root,
        layer=layer,
        key_field=field,
        scope_filter_field=scope_strategy.get("scope_filter_field"),
        scope_filter_value=scope_strategy.get("scope_filter_value"),
    )
    value_label = str(scope_strategy.get("missing_label", _emitted_value_label(field)))
    if not latest_by_scope and not expected_scopes:
        return LayerCheck(layer_id=layer_id, ok=False, reason=f"{layer_id}: missing fresh emitted evidence")

    missing_scopes: list[str] = []
    stale_scopes: list[str] = []

    scopes_to_check = expected_scopes or sorted(latest_by_scope)
    for scope in scopes_to_check:
        candidate = latest_by_scope.get(scope)
        if candidate is None:
            missing_scopes.append(scope)
            continue

        evidence_path, schema_valid, payload = candidate
        if not schema_valid:
            return LayerCheck(
                layer_id=layer_id,
                ok=False,
                reason=f"{layer_id}: schema-invalid evidence at {evidence_path.relative_to(repo_root)}",
            )

        assert payload is not None
        produced_at = datetime.fromisoformat(str(payload["produced_at_utc"]))
        if produced_at.date() != today_utc:
            stale_scopes.append(scope)
            continue
        if payload.get("status") == "pass":
            continue
        waiver_scope = str(payload.get(field, payload.get("scope", scope)))
        waiver_result = _waiver_allows_failure(
            repo_root=repo_root,
            layer_id=layer_id,
            scope=waiver_scope,
            evidence_path=evidence_path,
            current_time_utc=_now_utc(),
        )
        if waiver_result is not None and waiver_result.ok:
            continue
        if waiver_result is not None:
            return waiver_result
        return LayerCheck(
            layer_id=layer_id,
            ok=False,
            reason=f"{layer_id}: non-passing emitted evidence at {evidence_path.relative_to(repo_root)}",
        )

    if missing_scopes:
        return LayerCheck(
            layer_id=layer_id,
            ok=False,
            reason=f"{layer_id}: missing fresh emitted evidence for {value_label} {_format_scope_list(missing_scopes)}",
        )
    if stale_scopes:
        return LayerCheck(
            layer_id=layer_id,
            ok=False,
            reason=f"{layer_id}: stale emitted evidence for {value_label} {_format_scope_list(stale_scopes)}",
        )
    return LayerCheck(layer_id=layer_id, ok=True)


def _validate_reserved_directory_change(*, repo_root: Path, changed_path: str) -> str | None:
    pure_path = PurePosixPath(changed_path)
    parts = pure_path.parts
    if not parts:
        return None

    if len(parts) >= 2 and parts[0] == "prompts" and parts[1] == "judge":
        if pure_path.name == "README.md":
            return None
        if pure_path.suffix != ".md":
            return f"reserved path {changed_path}: judge prompts must be Markdown files under prompts/judge/"
        try:
            load_judge_prompt(repo_root / changed_path, repo_root=repo_root)
        except ValueError as error:
            return f"judge prompt {changed_path}: {error}"
        return None

    if parts[0] == "findings":
        if changed_path == "findings/README.md":
            return None
        if len(parts) != 2 or pure_path.suffix != ".md" or not _DATE_STAMP_RE.fullmatch(pure_path.stem):
            return f"reserved path {changed_path}: findings files must be findings/YYYY-MM-DD.md"
        return None

    if parts[0] == "tickets":
        if changed_path == "tickets/README.md":
            return None
        if len(parts) != 2 or not _TICKET_FILE_RE.fullmatch(pure_path.name):
            return f"reserved path {changed_path}: tickets must be tickets/reinvestigate_<source>_YYYY-MM-DD.md"
        return None

    if parts[0] == "escalations":
        if changed_path == "escalations/README.md":
            return None
        if len(parts) != 3 or not _DATE_STAMP_RE.fullmatch(parts[1]) or not _ESCALATION_FILE_RE.fullmatch(parts[2]):
            return f"reserved path {changed_path}: escalations must be escalations/YYYY-MM-DD/LN_scope.md"
        return None

    return None


def _validate_l12_summary(
    *,
    repo_root: Path,
    session_id: str,
    today_utc: date,
    changed_files: list[str],
    touched_layer_ids: list[str],
    gated_layer_ids: list[str],
) -> str | None:
    summary_path = repo_root / "evidence" / "L12" / session_id / "summary.json"
    if not summary_path.is_file():
        return f"L12: missing session summary at {summary_path.relative_to(repo_root)}"

    schema_valid, payload = _validate_evidence_payload(
        evidence_path=summary_path,
        schema_path=repo_root / "evidence_schemas" / "L12.json",
    )
    if not schema_valid or payload is None:
        return f"L12: schema-invalid evidence at {summary_path.relative_to(repo_root)}"

    produced_at = datetime.fromisoformat(str(payload["produced_at_utc"]).replace("Z", "+00:00"))
    if produced_at.date() != today_utc:
        return f"L12: stale evidence at {summary_path.relative_to(repo_root)}"
    if payload.get("status") != "pass":
        return f"L12: non-passing evidence status at {summary_path.relative_to(repo_root)}"
    if payload.get("session_id") != session_id or payload.get("scope") != session_id:
        return f"L12: session_id mismatch in {summary_path.relative_to(repo_root)}"
    if sorted(str(path) for path in payload.get("changed_files", [])) != sorted(changed_files):
        return f"L12: changed_files mismatch in {summary_path.relative_to(repo_root)}"
    if list(payload.get("touched_layers", [])) != touched_layer_ids:
        return f"L12: touched_layers mismatch in {summary_path.relative_to(repo_root)}"

    produced_layers = {str(layer_id) for layer_id in payload.get("produced_evidence_layers", [])}
    if "L12" not in produced_layers:
        return f"L12: produced_evidence_layers missing L12 in {summary_path.relative_to(repo_root)}"
    if not set(gated_layer_ids).issubset(produced_layers):
        return f"L12: produced_evidence_layers missing touched layers in {summary_path.relative_to(repo_root)}"
    return None


def check_layer(*, repo_root: Path, layer: dict, today_utc: date) -> LayerCheck:
    scope_strategy = layer["scope_strategy"]["type"]
    if scope_strategy == "fixed_scope":
        return _fixed_scope_check(repo_root=repo_root, layer=layer, today_utc=today_utc)
    if scope_strategy == "emitted_by_gate":
        return _emitted_scope_check(repo_root=repo_root, layer=layer, today_utc=today_utc)
    raise ValueError(f"Unsupported scope strategy: {scope_strategy}")


def _layer_status_gates_stage_close(layer: dict) -> bool:
    status = layer["status"]
    if status in {"introduced", "deprecated"}:
        return False
    if status in {"piloted", "enforced"}:
        return True
    raise ValueError(f"Unsupported layer status: {status}")


def _git_diff_changed_files(repo_root: Path) -> list[str]:
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    staged_files = [line for line in staged.stdout.splitlines() if line]
    if staged_files:
        return staged_files

    working_tree = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return [line for line in working_tree.stdout.splitlines() if line]


def evaluate_stage_close(
    *,
    repo_root: Path,
    changed_files: list[str],
    today_utc: date,
    session_id: str | None = None,
) -> StageCloseResult:
    if os.environ.get("KEEL_DISABLE"):
        return StageCloseResult(
            exit_code=1,
            touched_layers=[],
            failures=["KEEL_DISABLE is not allowed during stage-close; use a committed waiver instead"],
        )

    layers_payload = _load_yaml(repo_root / "layers.yaml")
    touched_layer_defs = touched_layers_for_files(changed_files=changed_files, layers_payload=layers_payload)
    touched_layer_ids = [layer["id"] for layer in touched_layer_defs]
    gated_layer_defs = [layer for layer in touched_layer_defs if _layer_status_gates_stage_close(layer)]
    reserved_directory_failures = [
        failure
        for failure in (
            _validate_reserved_directory_change(repo_root=repo_root, changed_path=path) for path in changed_files
        )
        if failure is not None
    ]
    layer_failures = [
        result.reason
        for result in (check_layer(repo_root=repo_root, layer=layer, today_utc=today_utc) for layer in gated_layer_defs)
        if not result.ok
    ]
    l12_failure = None
    if session_id is not None:
        l12_failure = _validate_l12_summary(
            repo_root=repo_root,
            session_id=session_id,
            today_utc=today_utc,
            changed_files=changed_files,
            touched_layer_ids=touched_layer_ids,
            gated_layer_ids=[layer["id"] for layer in gated_layer_defs],
        )
    failures = reserved_directory_failures + layer_failures + ([l12_failure] if l12_failure is not None else [])
    return StageCloseResult(
        exit_code=0 if not failures else 1,
        touched_layers=touched_layer_ids,
        failures=failures,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Keel Phase 1 stage-close gate")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed file path relative to repo root. Defaults to git diff output when omitted.",
    )
    parser.add_argument("--session-id", help="Keel session id used for the required L12 session summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    changed_files = args.changed_file or _git_diff_changed_files(repo_root)
    session_id = args.session_id or os.environ.get("KEEL_SESSION_ID") or os.environ.get("MATT_SESSION_ID")

    if not session_id:
        print("FAIL: stage-close gate requires --session-id or KEEL_SESSION_ID/MATT_SESSION_ID", file=sys.stderr)
        return 1

    try:
        result = evaluate_stage_close(
            repo_root=repo_root,
            changed_files=changed_files,
            today_utc=_today_utc(),
            session_id=session_id,
        )
    except Exception as error:  # noqa: BLE001
        print(f"FAIL: stage-close gate errored: {error}", file=sys.stderr)
        return 1

    if result.exit_code == 0:
        touched = ",".join(result.touched_layers) if result.touched_layers else "none"
        print(f"PASS: touched_layers={touched}")
        return 0

    print("FAIL: " + "; ".join(result.failures), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
