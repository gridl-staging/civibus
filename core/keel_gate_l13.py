
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "L13"
_DEFAULT_DEBT_FILE = _REPO_ROOT / "infra" / "deploy_hot_patch_debt.yaml"
_MISSING = object()

# Stage 1 scope guard: L13 only reads these four owner files.
CONTRACT_OWNER_FILES = {
    "workflow": ".github/workflows/deploy.yml",
    "compose": "infra/docker-compose.prod.yml",
    "env_example": ".env.production.example",
    "bootstrap": "infra/scripts/bootstrap_prod_vm.sh",
}

_SECRET_PATHS = (
    "workflow.deploy_env.PRODUCTION_ENV_FILE",
    "compose.required_env.POSTGRES_PASSWORD",
    "compose.required_env.CIVIBUS_API_KEYS",
    "compose.required_env.CIVIBUS_ADMIN_API_KEYS",
    "compose.required_env.CIVIBUS_API_KEY",
)
_NON_SECRET_PATHS = (
    "workflow.deploy_env.DEPLOY_GIT_SHA",
    "workflow.deploy_env.DEPLOY_REPO_URL",
    "compose.images.api",
    "compose.images.web",
    "compose.required_env.ORIGIN",
    "bootstrap.required_env_keys",
    "env_example.keys",
)
_ENV_ASSIGNMENT_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]*)=")
_BOOTSTRAP_REQUIRED_KEYS_PATTERN = re.compile(r"for\s+required_key\s+in\s+(.+?);\s*do")


class DeployHotPatchDebtEntry(BaseModel, extra="forbid"):
    entry_id: str = Field(min_length=1)
    deploy_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    expected_live_value: str
    reason: str = Field(min_length=1)
    expires_at_utc: datetime


class DeployHotPatchDebtFile(BaseModel, extra="forbid"):
    schema_version: int = Field(ge=1)
    entries: list[DeployHotPatchDebtEntry]


class L13DiffSummary(BaseModel, extra="forbid"):
    total_drift: int
    unexpected_drift: int
    allowed_drift: int
    expired_debt_entries: int
    unmatched_debt_entries: int


class L13ReconciliationEntry(BaseModel, extra="forbid"):
    deploy_id: str
    status: str
    total_drift_count: int
    unexpected_drift_count: int
    allowed_drift_count: int
    expired_debt_ids: list[str]
    unmatched_debt_ids: list[str]


class L13Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    diff_summary: L13DiffSummary
    diff_entries: list[dict[str, Any]]
    allowed_drift_entries: list[dict[str, Any]]
    reconciliation: dict[str, L13ReconciliationEntry]


@dataclass(frozen=True, slots=True)
class ContractDriftEvaluation:
    status: str
    diff_entries: list[dict[str, Any]]
    allowed_drift_entries: list[dict[str, Any]]
    unexpected_drift_entries: list[dict[str, Any]]
    expired_debt_ids: list[str]
    unmatched_debt_ids: list[str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _repo_sha(repo_root: Path = _REPO_ROOT) -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_root, text=True).strip()


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must parse as a mapping")
    return payload


def _path_lookup(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for token in dotted_path.split("."):
        if not isinstance(current, dict) or token not in current:
            return _MISSING
        current = current[token]
    return current


def _path_set(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = payload
    for token in parts[:-1]:
        current = current.setdefault(token, {})
    current[parts[-1]] = value


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _fingerprint(value: Any) -> str | None:
    if not _is_present(value):
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_live_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _normalize_non_secret_value(path: str, value: Any) -> Any:
    if path in {"bootstrap.required_env_keys", "env_example.keys"} and isinstance(value, list):
        return sorted(str(item) for item in value)
    return value


def _iter_leaf_paths(payload: Any, prefix: str = "") -> list[str]:
    """Return dotted paths for scalar leaves and list-valued fields."""
    if isinstance(payload, dict):
        paths: list[str] = []
        for key, value in payload.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_iter_leaf_paths(value, child_prefix))
        return paths
    if isinstance(payload, list):
        return [prefix] if prefix else []
    return [prefix] if prefix else []


def _parse_env_keys(env_example_text: str) -> list[str]:
    keys: list[str] = []
    for line in env_example_text.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT_PATTERN.match(stripped_line)
        if match:
            keys.append(match.group(1))
    return sorted(set(keys))


def _parse_bootstrap_required_keys(bootstrap_script_text: str) -> list[str]:
    match = _BOOTSTRAP_REQUIRED_KEYS_PATTERN.search(bootstrap_script_text)
    if match is None:
        raise ValueError("bootstrap script must declare a required_key loop for env validation")
    return sorted({token for token in match.group(1).split() if token})


def _repo_owner_path(repo_root: Path, owner_key: str) -> Path:
    return repo_root / CONTRACT_OWNER_FILES[owner_key]


def _extract_repo_snapshot(repo_root: Path) -> dict[str, Any]:
    workflow = _read_yaml(_repo_owner_path(repo_root, "workflow"))
    compose = _read_yaml(_repo_owner_path(repo_root, "compose"))
    env_example_text = _repo_owner_path(repo_root, "env_example").read_text(encoding="utf-8")
    bootstrap_script_text = _repo_owner_path(repo_root, "bootstrap").read_text(encoding="utf-8")

    deploy_job = workflow["jobs"]["deploy"]
    deploy_env = deploy_job["env"]
    compose_services = compose["services"]

    snapshot: dict[str, Any] = {}
    _path_set(snapshot, "workflow.deploy_env.DEPLOY_GIT_SHA", deploy_env["DEPLOY_GIT_SHA"])
    _path_set(snapshot, "workflow.deploy_env.DEPLOY_REPO_URL", deploy_env["DEPLOY_REPO_URL"])
    _path_set(snapshot, "workflow.deploy_env.PRODUCTION_ENV_FILE", deploy_env["PRODUCTION_ENV_FILE"])
    _path_set(snapshot, "compose.images.api", compose_services["api"]["image"])
    _path_set(snapshot, "compose.images.web", compose_services["web"]["image"])

    db_env = compose_services["db"]["environment"]
    api_env = compose_services["api"]["environment"]
    web_env = compose_services["web"]["environment"]
    _path_set(snapshot, "compose.required_env.POSTGRES_PASSWORD", db_env["POSTGRES_PASSWORD"])
    _path_set(snapshot, "compose.required_env.ORIGIN", web_env["ORIGIN"])
    _path_set(snapshot, "compose.required_env.CIVIBUS_API_KEYS", api_env["CIVIBUS_API_KEYS"])
    _path_set(snapshot, "compose.required_env.CIVIBUS_ADMIN_API_KEYS", api_env["CIVIBUS_ADMIN_API_KEYS"])
    _path_set(snapshot, "compose.required_env.CIVIBUS_API_KEY", web_env["CIVIBUS_API_KEY"])
    required_key_set = set(_parse_bootstrap_required_keys(bootstrap_script_text))
    env_example_key_set = set(_parse_env_keys(env_example_text))
    # Keep the diff surface narrow: only keys explicitly enforced by bootstrap are compared.
    _path_set(snapshot, "bootstrap.required_env_keys", sorted(required_key_set))
    _path_set(snapshot, "env_example.keys", sorted(env_example_key_set & required_key_set))

    return snapshot


def extract_repo_contract(*, repo_root: Path) -> dict[str, Any]:
    snapshot = _extract_repo_snapshot(repo_root)
    non_secret: dict[str, Any] = {}
    for path in _NON_SECRET_PATHS:
        value = _path_lookup(snapshot, path)
        if value is _MISSING:
            continue
        non_secret[path] = _normalize_non_secret_value(path, value)
    secret_presence = {
        path: _is_present(_path_lookup(snapshot, path))
        for path in _SECRET_PATHS
    }

    return {
        "owner_files": list(CONTRACT_OWNER_FILES.values()),
        "non_secret": non_secret,
        "secret_presence": secret_presence,
    }


def normalize_live_snapshot(raw_snapshot: dict[str, Any]) -> dict[str, Any]:
    non_secret: dict[str, Any] = {}
    for path in _NON_SECRET_PATHS:
        value = _path_lookup(raw_snapshot, path)
        if value is not _MISSING:
            non_secret[path] = _normalize_non_secret_value(path, value)

    secret_fingerprints = {}
    for path in _SECRET_PATHS:
        value = _path_lookup(raw_snapshot, path)
        present = value is not _MISSING and _is_present(value)
        secret_fingerprints[path] = {
            "present": present,
            "fingerprint": _fingerprint(value if value is not _MISSING else None),
        }

    allowed_surface = set(_NON_SECRET_PATHS) | set(_SECRET_PATHS)
    outside_diff_surface_paths = sorted(
        {
            dotted_path
            for dotted_path in _iter_leaf_paths(raw_snapshot)
            if dotted_path not in allowed_surface
        }
    )

    # Guard against accidental secret leakage if a caller mixes secret fields into non_secret.
    secrets_redacted = all(secret_path not in non_secret for secret_path in _SECRET_PATHS)
    return {
        "non_secret": non_secret,
        "secret_fingerprints": secret_fingerprints,
        "secrets_redacted": secrets_redacted,
        "outside_diff_surface_paths": outside_diff_surface_paths,
    }


def load_deploy_hot_patch_debt(path: Path) -> list[DeployHotPatchDebtEntry]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    validated = DeployHotPatchDebtFile.model_validate(payload)
    return validated.entries


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _build_drift_entry(
    *,
    path: str,
    drift_type: str,
    repo_value: Any,
    live_value: Any,
    reason: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "drift_type": drift_type,
        "repo_value": repo_value,
        "live_value": live_value,
        "reason": reason,
        "allowed": False,
        "debt_entry_id": None,
    }


def evaluate_contract_drift(
    *,
    repo_contract: dict[str, Any],
    normalized_live_snapshot: dict[str, Any],
    deploy_id: str,
    debt_entries: list[DeployHotPatchDebtEntry],
    produced_at: datetime,
) -> ContractDriftEvaluation:
    repo_non_secret: dict[str, Any] = dict(repo_contract.get("non_secret", {}))
    repo_secret_presence: dict[str, bool] = dict(repo_contract.get("secret_presence", {}))
    live_non_secret: dict[str, Any] = dict(normalized_live_snapshot.get("non_secret", {}))
    live_secret_fingerprints: dict[str, dict[str, Any]] = dict(normalized_live_snapshot.get("secret_fingerprints", {}))
    outside_diff_surface_paths: list[str] = list(normalized_live_snapshot.get("outside_diff_surface_paths", []))

    diff_entries: list[dict[str, Any]] = []
    if not bool(normalized_live_snapshot.get("secrets_redacted", False)):
        diff_entries.append(
            _build_drift_entry(
                path="*",
                drift_type="secret_exposure",
                repo_value=True,
                live_value=False,
                reason="live snapshot normalization did not redact secret-bearing fields",
            )
        )

    for outside_path in outside_diff_surface_paths:
        diff_entries.append(
            _build_drift_entry(
                path=outside_path,
                drift_type="outside_diff_surface",
                repo_value=None,
                live_value="<redacted-outside-surface>",
                reason="live snapshot exposed a path outside the Stage 1 L13 diff surface",
            )
        )

    allowed_surface = set(repo_non_secret.keys()) | set(repo_secret_presence.keys())
    for live_non_secret_path in live_non_secret:
        if live_non_secret_path not in allowed_surface:
            diff_entries.append(
                _build_drift_entry(
                    path=live_non_secret_path,
                    drift_type="outside_diff_surface",
                    repo_value=None,
                    live_value="<redacted-outside-surface>",
                    reason="live snapshot exposed a path outside the Stage 1 L13 diff surface",
                )
            )

    for path, repo_value in repo_non_secret.items():
        live_value = live_non_secret.get(path, _MISSING)
        if live_value is _MISSING or live_value != repo_value:
            diff_entries.append(
                _build_drift_entry(
                    path=path,
                    drift_type="non_secret_mismatch",
                    repo_value=repo_value,
                    live_value=None if live_value is _MISSING else live_value,
                    reason="non-secret contract value differs between repo and live snapshot",
                )
            )

    for path, repo_present in repo_secret_presence.items():
        live_present = bool(live_secret_fingerprints.get(path, {}).get("present", False))
        if live_present != repo_present:
            diff_entries.append(
                _build_drift_entry(
                    path=path,
                    drift_type="secret_presence_mismatch",
                    repo_value=repo_present,
                    live_value=live_present,
                    reason="secret-bearing key presence differs between repo and live snapshot",
                )
            )

    produced_at_utc = _normalize_datetime(produced_at)
    scoped_debt_entries = [entry for entry in debt_entries if entry.deploy_id == deploy_id]
    expired_debt_ids: list[str] = []
    active_debt_entries: list[DeployHotPatchDebtEntry] = []
    for debt_entry in scoped_debt_entries:
        if _normalize_datetime(debt_entry.expires_at_utc) <= produced_at_utc:
            expired_debt_ids.append(debt_entry.entry_id)
        else:
            active_debt_entries.append(debt_entry)

    consumed_diff_indexes: set[int] = set()
    matched_entry_ids: set[str] = set()
    for debt_entry in active_debt_entries:
        for diff_index, diff_entry in enumerate(diff_entries):
            if diff_index in consumed_diff_indexes:
                continue
            if diff_entry["path"] != debt_entry.path:
                continue
            if _canonical_live_value(diff_entry["live_value"]) != debt_entry.expected_live_value:
                continue
            diff_entry["allowed"] = True
            diff_entry["debt_entry_id"] = debt_entry.entry_id
            consumed_diff_indexes.add(diff_index)
            matched_entry_ids.add(debt_entry.entry_id)
            break

    unmatched_debt_ids = sorted(
        entry.entry_id for entry in active_debt_entries if entry.entry_id not in matched_entry_ids
    )
    allowed_drift_entries = [entry for entry in diff_entries if bool(entry["allowed"])]
    unexpected_drift_entries = [entry for entry in diff_entries if not bool(entry["allowed"])]

    status = "pass"
    if unexpected_drift_entries or expired_debt_ids or unmatched_debt_ids:
        status = "fail"

    return ContractDriftEvaluation(
        status=status,
        diff_entries=diff_entries,
        allowed_drift_entries=allowed_drift_entries,
        unexpected_drift_entries=unexpected_drift_entries,
        expired_debt_ids=sorted(expired_debt_ids),
        unmatched_debt_ids=unmatched_debt_ids,
    )


def write_l13_evidence(
    *,
    evaluation: ContractDriftEvaluation,
    deploy_id: str,
    repo_sha: str,
    produced_at: datetime,
    evidence_root: Path,
) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True)
    payload = L13Evidence(
        layer="L13",
        scope="global",
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=repo_sha,
        gate_command=f"python -m core.keel_gate_l13 --deploy-id {deploy_id}",
        status=evaluation.status,
        diff_summary=L13DiffSummary(
            total_drift=len(evaluation.diff_entries),
            unexpected_drift=len(evaluation.unexpected_drift_entries),
            allowed_drift=len(evaluation.allowed_drift_entries),
            expired_debt_entries=len(evaluation.expired_debt_ids),
            unmatched_debt_entries=len(evaluation.unmatched_debt_ids),
        ),
        diff_entries=evaluation.diff_entries,
        allowed_drift_entries=evaluation.allowed_drift_entries,
        reconciliation={
            deploy_id: L13ReconciliationEntry(
                deploy_id=deploy_id,
                status=evaluation.status,
                total_drift_count=len(evaluation.diff_entries),
                unexpected_drift_count=len(evaluation.unexpected_drift_entries),
                allowed_drift_count=len(evaluation.allowed_drift_entries),
                expired_debt_ids=evaluation.expired_debt_ids,
                unmatched_debt_ids=evaluation.unmatched_debt_ids,
            )
        },
    )
    destination = evidence_root / f"{deploy_id}.json"
    destination.write_text(json.dumps(payload.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return destination


def _load_live_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"live snapshot at {path} must be a JSON object")
    return payload


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate repo-vs-live deploy contract drift for Keel L13")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--live-snapshot-path", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--debt-file", type=Path, default=_DEFAULT_DEBT_FILE)
    parser.add_argument("--deploy-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    evidence_root = args.evidence_root.resolve() if args.evidence_root else _DEFAULT_EVIDENCE_ROOT
    produced_at = _utc_now()

    try:
        repo_contract = extract_repo_contract(repo_root=repo_root)
        live_snapshot = _load_live_snapshot(args.live_snapshot_path.resolve())
        normalized_live_snapshot = normalize_live_snapshot(live_snapshot)
        debt_entries = load_deploy_hot_patch_debt(args.debt_file.resolve())
        evaluation = evaluate_contract_drift(
            repo_contract=repo_contract,
            normalized_live_snapshot=normalized_live_snapshot,
            deploy_id=args.deploy_id,
            debt_entries=debt_entries,
            produced_at=produced_at,
        )
        evidence_path = write_l13_evidence(
            evaluation=evaluation,
            deploy_id=args.deploy_id,
            repo_sha=_repo_sha(repo_root),
            produced_at=produced_at,
            evidence_root=evidence_root,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L13 failed: {error}", file=sys.stderr)
        return 1

    print(
        f"{evaluation.status.upper()}: deploy_id={args.deploy_id} "
        f"total_drift={len(evaluation.diff_entries)} unexpected={len(evaluation.unexpected_drift_entries)} "
        f"allowed={len(evaluation.allowed_drift_entries)} evidence={evidence_path}"
    )
    return 0 if evaluation.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
