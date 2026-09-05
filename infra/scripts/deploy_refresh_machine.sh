#!/usr/bin/env bash
# Build, prove, and install a new image on the existing stopped refresh Machine.

set -euo pipefail

APP_NAME="civibus-refresh"
MACHINE_ID="859e0da479e678"
FLY_CONFIG="infra/fly/refresh.fly.toml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERIFIER="$REPO_ROOT/infra/scripts/verify_refresh_machine.sh"
VERSION_URL="https://civibus.shareborough.com/api/health/version"
PUBLIC_BASE_URL="https://civibus-caddy.fly.dev"
PYTHON_BIN="${PYTHON_BIN:-python3}"

fail() {
  printf 'FAIL: refresh Machine deploy: %s\n' "$1" >&2
  exit 1
}

sanitize_machine_config() {
  local config_path="$1"
  local sanitized_path
  sanitized_path="${config_path}.sanitized"

  # The verifier only needs this fixed-shape, non-secret subset. Persisting the
  # raw display-config would risk uploading any future secret env additions in
  # the evidence artifact.
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$config_path" <<'PY' >"$sanitized_path"
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("machine display-config payload must be a JSON object")

environment = payload.get("env", {})
if not isinstance(environment, dict):
    raise SystemExit("machine display-config env must be a JSON object")

allowed_env = (
    "CIVIBUS_ENV",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "CIVIBUS_REFRESH_DATA_DIR",
    "CIVIBUS_STARTUP_CANARY",
)
sanitized = {
    "init": payload.get("init"),
    "env": {key: environment[key] for key in allowed_env if key in environment},
    "mounts": payload.get("mounts"),
    "restart": payload.get("restart"),
}
print(json.dumps(sanitized, sort_keys=True))
PY
  mv "$sanitized_path" "$config_path" \
    || fail "cannot replace sanitized machine config evidence"
}

require_empty_evidence_dir() {
  local evidence_dir="$1"
  [[ -d "$evidence_dir" ]] || fail "evidence directory must already exist: $evidence_dir"
  if [[ -n "$(ls -A "$evidence_dir")" ]]; then
    fail "evidence directory must be empty: $evidence_dir"
  fi
}

require_external_evidence_dir() {
  local evidence_dir="$1"
  case "$evidence_dir/" in
    "$REPO_ROOT/"*)
      fail "evidence directory must be outside the repository: $evidence_dir"
      ;;
  esac
}

configure_flyctl_local_docker_host() {
  # flyctl's local builder reads DOCKER_HOST but does not honor Docker CLI contexts.
  [[ -z "${DOCKER_HOST:-}" ]] || return

  local active_context
  local context_host
  active_context="$(docker context show 2>/dev/null)" \
    || fail "cannot resolve the active Docker context for the regional image build"
  [[ -n "$active_context" ]] \
    || fail "active Docker context is empty for the regional image build"
  context_host="$(
    docker context inspect "$active_context" \
      --format '{{.Endpoints.docker.Host}}' 2>/dev/null
  )" || fail "cannot resolve the active Docker endpoint for the regional image build"
  case "$context_host" in
    unix://*|tcp://*|npipe://*) ;;
    *) fail "active Docker endpoint is not a supported local Docker host" ;;
  esac
  export DOCKER_HOST="$context_host"
}

parse_args() {
  SELECT_MACHINE_IMAGE=false
  MACHINE_IMAGE_IDENTITY=""
  QUALIFY_ONLY=false
  REGIONAL_BUILD_QUALIFY=false
  REGIONAL_ACTION=""
  if [[ "${1:-}" == "--select-machine-image" ]]; then
    (( $# == 2 )) \
      || fail "--select-machine-image requires one PROVEN_TAGGED_DIGEST"
    SELECT_MACHINE_IMAGE=true
    MACHINE_IMAGE_IDENTITY="$2"
    return
  fi

  if [[ "${1:-}" == "--regional-build-qualify" ]]; then
    REGIONAL_BUILD_QUALIFY=true
    REGIONAL_BUILD_PROFILE_JSON=""
    REGIONAL_BUILD_CANDIDATE_MANIFEST_JSON=""
    REGIONAL_BUILD_EVIDENCE_DIR=""
    REGIONAL_BUILD_CANDIDATE_RECEIPT_JSON=""
    local regional_build_seen=""
    shift
    while (( $# > 0 )); do
      (( $# >= 2 )) || fail "$1 requires a non-empty value"
      case "$regional_build_seen" in
        *" $1 "*) fail "$1 may be supplied only once" ;;
      esac
      regional_build_seen="$regional_build_seen $1 "
      case "$1" in
        --profile-json) REGIONAL_BUILD_PROFILE_JSON="${2:-}" ;;
        --candidate-manifest-json) REGIONAL_BUILD_CANDIDATE_MANIFEST_JSON="${2:-}" ;;
        --evidence-dir) REGIONAL_BUILD_EVIDENCE_DIR="${2:-}" ;;
        --candidate-receipt-json) REGIONAL_BUILD_CANDIDATE_RECEIPT_JSON="${2:-}" ;;
        *) fail "unknown regional build qualification option: $1" ;;
      esac
      [[ -n "$2" ]] || fail "$1 requires a non-empty value"
      shift 2
    done
    [[ -n "$REGIONAL_BUILD_PROFILE_JSON" \
      && -n "$REGIONAL_BUILD_CANDIDATE_MANIFEST_JSON" \
      && -n "$REGIONAL_BUILD_EVIDENCE_DIR" \
      && -n "$REGIONAL_BUILD_CANDIDATE_RECEIPT_JSON" ]] \
      || fail "regional build qualification requires profile, manifest, evidence directory, and receipt"
    return
  fi

  if [[ "${1:-}" == "--qualify-only" ]]; then
    QUALIFY_ONLY=true
    PROFILE_JSON=""
    CANDIDATE_MANIFEST_JSON=""
    PRODUCED_IMAGE_TAGGED_DIGEST=""
    CANDIDATE_RECEIPT_JSON=""
    PROFILE_JSON_SEEN=false
    CANDIDATE_MANIFEST_JSON_SEEN=false
    PRODUCED_IMAGE_TAGGED_DIGEST_SEEN=false
    CANDIDATE_RECEIPT_JSON_SEEN=false
    shift
    while (( $# > 0 )); do
      case "$1" in
        --profile-json)
          (( $# >= 2 )) || fail "--profile-json requires a path"
          [[ "$PROFILE_JSON_SEEN" == "false" ]] \
            || fail "--profile-json may be supplied only once"
          PROFILE_JSON_SEEN=true
          PROFILE_JSON="$2"
          shift 2
          ;;
        --candidate-manifest-json)
          (( $# >= 2 )) || fail "--candidate-manifest-json requires a path"
          [[ "$CANDIDATE_MANIFEST_JSON_SEEN" == "false" ]] \
            || fail "--candidate-manifest-json may be supplied only once"
          CANDIDATE_MANIFEST_JSON_SEEN=true
          CANDIDATE_MANIFEST_JSON="$2"
          shift 2
          ;;
        --produced-image-tagged-digest)
          (( $# >= 2 )) || fail "--produced-image-tagged-digest requires a value"
          [[ "$PRODUCED_IMAGE_TAGGED_DIGEST_SEEN" == "false" ]] \
            || fail "--produced-image-tagged-digest may be supplied only once"
          PRODUCED_IMAGE_TAGGED_DIGEST_SEEN=true
          PRODUCED_IMAGE_TAGGED_DIGEST="$2"
          shift 2
          ;;
        --candidate-receipt-json)
          (( $# >= 2 )) || fail "--candidate-receipt-json requires a path"
          [[ "$CANDIDATE_RECEIPT_JSON_SEEN" == "false" ]] \
            || fail "--candidate-receipt-json may be supplied only once"
          CANDIDATE_RECEIPT_JSON_SEEN=true
          CANDIDATE_RECEIPT_JSON="$2"
          shift 2
          ;;
        *)
          fail "unknown qualification-only option: $1"
          ;;
      esac
    done
    [[ -n "$PROFILE_JSON" ]] || fail "--profile-json is required for --qualify-only"
    [[ -n "$CANDIDATE_MANIFEST_JSON" ]] \
      || fail "--candidate-manifest-json is required for --qualify-only"
    [[ -n "$PRODUCED_IMAGE_TAGGED_DIGEST" ]] \
      || fail "--produced-image-tagged-digest is required for --qualify-only"
    [[ -n "$CANDIDATE_RECEIPT_JSON" ]] \
      || fail "--candidate-receipt-json is required for --qualify-only"
    return
  fi

  if [[ "${1:-}" == "--regional-action" ]]; then
    (( $# >= 2 )) || fail "--regional-action requires an action"
    REGIONAL_ACTION="$2"
    REGIONAL_PROFILE_JSON=""
    REGIONAL_CANDIDATE_RECEIPT_JSON=""
    REGIONAL_LIFECYCLE_DIR=""
    REGIONAL_SECRET_FILE=""
    REGIONAL_REFRESH_POSTCONDITION_JSON=""
    REGIONAL_EXPECTED_REFRESH_RUN_ID=""
    REGIONAL_AUTHORITY_LEDGER_PROOF_JSON=""
    REGIONAL_CANARY_PROMOTION_JSON=""
    REGIONAL_INVARIANCE_STAGE=""
    REGIONAL_LEGACY_INVARIANCE_INPUT=false
    local regional_seen=""
    shift 2
    while (( $# > 0 )); do
      (( $# >= 2 )) || fail "$1 requires a non-empty value"
      case "$regional_seen" in
        *" $1 "*) fail "$1 may be supplied only once" ;;
      esac
      regional_seen="$regional_seen $1 "
      case "$1" in
        --profile-json) REGIONAL_PROFILE_JSON="${2:-}" ;;
        --candidate-receipt-json) REGIONAL_CANDIDATE_RECEIPT_JSON="${2:-}" ;;
        --lifecycle-dir) REGIONAL_LIFECYCLE_DIR="${2:-}" ;;
        --secret-file) REGIONAL_SECRET_FILE="${2:-}" ;;
        --refresh-postcondition-json) REGIONAL_REFRESH_POSTCONDITION_JSON="${2:-}" ;;
        --expected-refresh-run-id) REGIONAL_EXPECTED_REFRESH_RUN_ID="${2:-}" ;;
        --authority-ledger-proof-json) REGIONAL_AUTHORITY_LEDGER_PROOF_JSON="${2:-}" ;;
        --federal-invariance-before-json)
          REGIONAL_LEGACY_INVARIANCE_INPUT=true
          ;;
        --federal-invariance-after-json)
          REGIONAL_LEGACY_INVARIANCE_INPUT=true
          ;;
        --public-invariance-before-json)
          REGIONAL_LEGACY_INVARIANCE_INPUT=true
          ;;
        --public-invariance-after-json)
          REGIONAL_LEGACY_INVARIANCE_INPUT=true
          ;;
        --invariance-stage) REGIONAL_INVARIANCE_STAGE="${2:-}" ;;
        --canary-promotion-json) REGIONAL_CANARY_PROMOTION_JSON="${2:-}" ;;
        *) fail "unknown regional lifecycle option: $1" ;;
      esac
      [[ -n "$2" ]] || fail "$1 requires a non-empty value"
      shift 2
    done
    [[ "$REGIONAL_ACTION" == "create-stopped" \
      || "$REGIONAL_ACTION" == "start-once" \
      || "$REGIONAL_ACTION" == "create-canary-stopped" \
      || "$REGIONAL_ACTION" == "start-canary-once" \
      || "$REGIONAL_ACTION" == "capture-invariance" \
      || "$REGIONAL_ACTION" == "rollback" ]] \
      || fail "regional action must be create-stopped, start-once, create-canary-stopped, capture-invariance, start-canary-once, or rollback"
    [[ -n "$REGIONAL_PROFILE_JSON" && -n "$REGIONAL_CANDIDATE_RECEIPT_JSON" && -n "$REGIONAL_LIFECYCLE_DIR" ]] \
      || fail "regional action requires profile, candidate receipt, and lifecycle directory"
    if [[ "$REGIONAL_ACTION" == "create-stopped" || "$REGIONAL_ACTION" == "create-canary-stopped" ]]; then
      [[ -n "$REGIONAL_SECRET_FILE" ]] || fail "$REGIONAL_ACTION requires --secret-file"
    elif [[ -n "$REGIONAL_SECRET_FILE" ]]; then
      fail "--secret-file is accepted only for a stopped create action"
    fi
    [[ "$REGIONAL_LEGACY_INVARIANCE_INPUT" == "false" ]] \
      || fail "legacy caller-supplied invariance evidence is forbidden; use capture-invariance"
    if [[ "$REGIONAL_ACTION" == "capture-invariance" ]]; then
      [[ "$REGIONAL_INVARIANCE_STAGE" == "before" || "$REGIONAL_INVARIANCE_STAGE" == "after" ]] \
        || fail "capture-invariance requires --invariance-stage before or after"
    elif [[ -n "$REGIONAL_INVARIANCE_STAGE" ]]; then
      fail "--invariance-stage is accepted only for capture-invariance"
    fi
    if [[ -n "$REGIONAL_EXPECTED_REFRESH_RUN_ID" && "$REGIONAL_ACTION" != "rollback" ]]; then
      fail "--expected-refresh-run-id is accepted only for rollback"
    fi
    if [[ "$REGIONAL_ACTION" == "create-stopped" ]]; then
      [[ -n "$REGIONAL_CANARY_PROMOTION_JSON" ]] \
        || fail "complete canary promotion artifact is required before recurring provisioning"
      [[ -z "$REGIONAL_REFRESH_POSTCONDITION_JSON" ]] \
        || fail "--refresh-postcondition-json cannot replace the complete canary promotion artifact"
    fi
    return
  fi

  EVIDENCE_DIR=""
  DEV_SHA=""
  while (( $# > 0 )); do
    case "$1" in
      --evidence-dir)
        (( $# >= 2 )) || fail "--evidence-dir requires a path"
        EVIDENCE_DIR="$2"
        shift 2
        ;;
      --dev-sha)
        (( $# >= 2 )) || fail "--dev-sha requires a value"
        DEV_SHA="$2"
        shift 2
        ;;
      *)
        fail "unknown option: $1"
        ;;
    esac
  done
  [[ -n "$EVIDENCE_DIR" ]] || fail "--evidence-dir is required"
  [[ "$DEV_SHA" =~ ^[0-9a-f]{40}$ ]] \
    || fail "--dev-sha must be a 40-character lowercase hexadecimal commit SHA"
}

qualify_image_candidate() {
  local profile_json="$1"
  local candidate_manifest_json="$2"
  local produced_image_tagged_digest="$3"
  local candidate_receipt_json="$4"
  local qualification_mode="${5:-full}"
  local receipt_dir
  local receipt_name
  local candidate_tmp
  local context_tmp
  local image_proof_tmp
  local candidate_source_sha
  local image_plan_contract_path

  [[ ! -e "$candidate_receipt_json" && ! -L "$candidate_receipt_json" ]] \
    || fail "candidate receipt path must not already exist: $candidate_receipt_json"
  receipt_dir="$(cd "$(dirname "$candidate_receipt_json")" && pwd -P)" \
    || fail "candidate receipt directory must already exist"
  require_external_evidence_dir "$receipt_dir"
  receipt_name="$(basename "$candidate_receipt_json")"
  [[ -n "$receipt_name" && "$receipt_name" != "." && "$receipt_name" != ".." ]] \
    || fail "candidate receipt filename is invalid"
  candidate_receipt_json="$receipt_dir/$receipt_name"
  candidate_tmp="$(mktemp "$receipt_dir/.${receipt_name}.tmp.XXXXXX")" \
    || fail "cannot create temporary candidate receipt"
  context_tmp="$(mktemp "$receipt_dir/.${receipt_name}.context.XXXXXX")" \
    || fail "cannot create temporary candidate context"
  image_proof_tmp="$(mktemp "$receipt_dir/.${receipt_name}.image-proof.XXXXXX")" \
    || fail "cannot create temporary image proof"
  trap 'rm -f -- "$candidate_tmp" "$context_tmp" "$image_proof_tmp"' EXIT

  bash "$VERIFIER" --profile-json "$profile_json" --profile-only >/dev/null \
    || fail "regional profile validation failed before image qualification"

  candidate_source_sha="$(PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$profile_json" "$candidate_manifest_json" "$produced_image_tagged_digest" \
    "$context_tmp" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    raise SystemExit(message)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()).hexdigest()


def read_strict(path: Path, label: str) -> Any:
    if not path.is_file() or path.is_symlink():
        fail(f"{label} must be a regular non-symlink file")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"{label} contains a duplicate object key")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda _value: fail(f"{label} contains a non-finite number"),
        )
    except (OSError, json.JSONDecodeError):
        fail(f"{label} is not valid readable JSON")


def git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        fail(f"git identity proof failed for {' '.join(args)}")
    return result.stdout.strip()


profile = read_strict(Path(sys.argv[1]), "profile JSON")
manifest = read_strict(Path(sys.argv[2]), "candidate manifest JSON")
if not isinstance(profile, dict) or not isinstance(manifest, dict):
    fail("profile and candidate manifest must be JSON objects")
expected_manifest_keys = {
    "authority",
    "baseline_receipt_git_sha", "baseline_source_git_sha", "baseline_tree_git_sha",
    "candidate_git_sha", "candidate_tree_git_sha", "changed_paths", "manifest_kind",
    "execution_plan_id", "profile_sha256", "schema_version",
}
if set(manifest) != expected_manifest_keys:
    fail("candidate manifest key set mismatch")
if (
    type(manifest.get("schema_version")) is not int
    or manifest.get("schema_version") != 2
    or manifest.get("manifest_kind") != "authority_refresh_candidate"
):
    fail("candidate manifest identity mismatch")
plan = profile.get("execution_plan")
if not isinstance(plan, dict):
    fail("authority profile execution plan must be a JSON object")
if (
    manifest.get("authority") != plan.get("authority")
    or manifest.get("execution_plan_id") != plan.get("plan_id")
    or manifest.get("profile_sha256") != canonical_sha256(profile)
):
    fail("candidate manifest authority profile binding mismatch")
canonical = profile.get("canonical_source")
if not isinstance(canonical, dict):
    fail("regional profile canonical source must be a JSON object")
for manifest_key, profile_key in (
    ("baseline_receipt_git_sha", "receipt_git_sha"),
    ("baseline_source_git_sha", "source_git_sha"),
    ("baseline_tree_git_sha", "tree_git_sha"),
):
    if manifest.get(manifest_key) != canonical.get(profile_key):
        fail(f"candidate manifest {manifest_key} does not match regional profile")
source = manifest.get("candidate_git_sha")
tree = manifest.get("candidate_tree_git_sha")
for value, label in ((source, "candidate manifest source"), (tree, "candidate manifest tree")):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        fail(f"{label} must be a 40-character lowercase hexadecimal identity")
paths = manifest.get("changed_paths")
if not isinstance(paths, list) or paths != sorted(set(paths)) or any(
    not isinstance(path, str) or not path or path.startswith(("/", "../")) or "/../" in path
    for path in paths
):
    fail("candidate manifest changed_paths must be a safe sorted unique array")
image = profile.get("image")
machine = profile.get("machine")
if not isinstance(image, dict) or not isinstance(machine, dict) or not isinstance(machine.get("config"), dict):
    fail("regional profile image and Machine config must be JSON objects")
match = re.fullmatch(
    r"(?P<repository>[a-z0-9][a-z0-9./_-]*):[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}@sha256:[0-9a-f]{64}",
    sys.argv[3],
)
if match is None or match.group("repository") != image.get("repository"):
    fail("produced image identity does not match regional profile repository")
receipt_sha = canonical["receipt_git_sha"]
base_source = canonical["source_git_sha"]
base_tree = canonical["tree_git_sha"]
if git_output("rev-parse", f"{base_source}^{{tree}}") != base_tree:
    fail("canonical source tree does not match regional profile")
if git_output("rev-parse", f"{receipt_sha}^{{tree}}") != base_tree:
    fail("canonical receipt tree does not match regional profile")
if git_output("rev-parse", f"{receipt_sha}^") != base_source:
    fail("canonical receipt does not have the accepted source as its parent")
if git_output("rev-parse", "--verify", f"{source}^{{commit}}") != source:
    fail("candidate source commit cannot be resolved exactly")
if git_output("rev-parse", f"{source}^{{tree}}") != tree:
    fail("candidate source tree does not match candidate manifest")
if subprocess.run(["git", "merge-base", "--is-ancestor", receipt_sha, source], check=False).returncode:
    fail("candidate source is not descended from the accepted canonical receipt")
diff = subprocess.run(
    ["git", "diff", "--name-only", "--no-renames", "-z", receipt_sha, source],
    capture_output=True,
    check=False,
)
if diff.returncode:
    fail("candidate changed-path proof failed")
try:
    actual_paths = diff.stdout.decode("utf-8").split("\0")
except UnicodeDecodeError:
    fail("candidate changed-path proof is not UTF-8")
if not actual_paths or actual_paths[-1] != "" or actual_paths[:-1] != paths:
    fail("candidate manifest changed_paths do not match the canonical Git diff")
config_sha = canonical_sha256(machine["config"])
if config_sha != machine.get("config_sha256"):
    fail("regional profile Machine config digest mismatch")
context = {
    "canonical_receipt_git_sha": receipt_sha,
    "canonical_source_git_sha": base_source,
    "canonical_tree_git_sha": base_tree,
    "machine_config_sha256": config_sha,
    "produced_image_tagged_digest": sys.argv[3],
    "profile_sha256": canonical_sha256(profile),
    "source_git_sha": source,
    "source_tree_git_sha": tree,
}
Path(sys.argv[4]).write_text(json.dumps(context, sort_keys=True), encoding="utf-8")
print(source)
PY
  )" || fail "candidate manifest and image preflight failed"

  if [[ "$qualification_mode" == "preflight" ]]; then
    rm -f -- "$candidate_tmp" "$context_tmp" "$image_proof_tmp"
    trap - EXIT
    printf '%s\n' "$candidate_source_sha"
    return
  fi
  [[ "$qualification_mode" == "full" ]] || fail "unsupported image qualification mode"

  image_plan_contract_path="$(PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$profile_json" <<'PY'
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
path = profile.get("execution_plan", {}).get("contract_path")
if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
    raise SystemExit("authority execution plan contract path is invalid")
print(path)
PY
  )" || fail "authority execution plan contract path proof failed"

  docker pull "$produced_image_tagged_digest" >/dev/null \
    || fail "immutable regional candidate image pull failed"
  docker run --rm --platform linux/amd64 \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    -e PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint python "$produced_image_tagged_digest" -c '
import json
import sys

from api.health_version import build_version_payload
from core.refresh.authority_execution_plan import select_execution_plan_jobs
from core.refresh.authority_operations_profile import (
    expected_image_plan_proof,
    load_authority_operations_profile,
)
from core.refresh.job_builders import build_refresh_plan

expected_source = sys.argv[1]
profile = load_authority_operations_profile(sys.argv[2])
version = build_version_payload()
if version.get("git_sha") != expected_source or not version.get("built_at"):
    raise SystemExit(f"regional image source stamp mismatch: {version!r}")
registry_jobs = build_refresh_plan(scope="all")
scheduled = select_execution_plan_jobs(
    registry_jobs, profile.execution_plan, mode="scheduled"
)
canary = select_execution_plan_jobs(
    registry_jobs, profile.execution_plan, mode="canary"
)
if tuple(job.key for job in scheduled) != profile.execution_plan.scheduled.job_keys:
    raise SystemExit("authority image scheduled plan mismatch")
if tuple(job.key for job in canary) != profile.execution_plan.canary.job_keys:
    raise SystemExit("authority image canary plan mismatch")
print(json.dumps(expected_image_plan_proof(profile, build_version=version), sort_keys=True))
' "$candidate_source_sha" "$image_plan_contract_path" >"$image_proof_tmp" \
    || fail "immutable regional candidate image content proof failed"

  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$context_tmp" "$image_proof_tmp" "$profile_json" <<'PY' >"$candidate_tmp"
import json
import hashlib
import sys
from pathlib import Path

context = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
image_proof = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
profile = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
plan = profile["execution_plan"]
version = image_proof.get("build_version")
plan_sha = hashlib.sha256(json.dumps(
    plan, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True
).encode()).hexdigest()
expected_proof = {
    "authority": plan["authority"],
    "build_version": version,
    "cadence_clock": plan["cadence_clock"],
    "canary": plan["canary"],
    "concurrency": plan["concurrency"],
    "execution_plan_id": plan["plan_id"],
    "execution_plan_sha256": plan_sha,
    "scheduled": plan["scheduled"],
}
if (
    not isinstance(image_proof, dict)
    or not isinstance(version, dict)
    or version.get("git_sha") != context["source_git_sha"]
    or not version.get("built_at")
    or image_proof != expected_proof
):
    raise SystemExit("authority image proof mismatch")
receipt = dict(context)
receipt.update({
    "image_proof": image_proof,
    "qualification_kind": "authority_refresh_image_candidate",
    "schema_version": 2,
})
print(json.dumps(receipt, sort_keys=True))
PY

  bash "$VERIFIER" \
    --profile-json "$profile_json" \
    --candidate-receipt-json "$candidate_tmp" \
    --profile-only >/dev/null \
    || fail "regional image candidate verification failed"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$candidate_tmp" "$candidate_receipt_json" <<'PY' \
    || fail "cannot publish verified regional image candidate receipt without overwriting"
import os
import sys

os.link(sys.argv[1], sys.argv[2], follow_symlinks=False)
PY
  rm -f -- "$candidate_tmp"
  rm -f -- "$context_tmp"
  rm -f -- "$image_proof_tmp"
  trap - EXIT
  printf 'PASS: regional refresh image candidate qualified at %s\n' \
    "$candidate_receipt_json"
}

regional_context() {
  bash "$VERIFIER" --profile-json "$REGIONAL_PROFILE_JSON" \
    --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" --profile-only >/dev/null \
    || fail "regional profile/candidate receipt validation failed"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$REGIONAL_PROFILE_JSON" "$REGIONAL_CANDIDATE_RECEIPT_JSON" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

profile_path, receipt_path = map(Path, sys.argv[1:])
profile = json.loads(profile_path.read_text(encoding="utf-8"))
receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
plan = profile["execution_plan"]
authority = plan["authority"]
print("\t".join((
    profile["app"], profile["organization"], profile["organization_id"],
    profile["machine"]["name"], profile["machine"]["region"],
    receipt["produced_image_tagged_digest"],
    f"{authority['kind']}/{authority['code']}", plan["plan_id"],
    plan["canary"]["job_keys"][0],
    profile["machine"]["config"]["env"]["POSTGRES_HOST"],
    profile["machine"]["config"]["env"]["POSTGRES_PORT"],
    profile["machine"]["config"]["env"]["POSTGRES_DB"],
    profile["machine"]["config"]["env"]["POSTGRES_USER"],
    hashlib.sha256(profile_path.read_bytes()).hexdigest(),
    hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    receipt["source_git_sha"], receipt["source_tree_git_sha"],
    profile["machine"]["config_sha256"],
    profile["canonical_source"]["receipt_git_sha"],
    profile["canonical_source"]["source_git_sha"],
    profile["canonical_source"]["tree_git_sha"],
)))
PY
}

snapshot_regional_input() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$1" "$2" <<'PY'
import os
import secrets
import stat
import sys
from pathlib import Path

source, destination = sys.argv[1:]
source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
try:
    if not stat.S_ISREG(os.fstat(source_fd).st_mode):
        raise SystemExit("regional lifecycle input must be a regular non-symlink file")
    destination_path = Path(destination)
    temporary = destination_path.parent / (
        f".{destination_path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    try:
        destination_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(destination_fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            while chunk := os.read(source_fd, 1024 * 1024):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination_path, follow_symlinks=False)
        directory_fd = os.open(destination_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
finally:
    os.close(source_fd)
PY
}

publish_or_match_regional_input() {
  local source="$1"
  local destination="$2"
  if [[ -e "$destination" || -L "$destination" ]]; then
    [[ -f "$destination" && ! -L "$destination" ]] \
      || fail "durable regional evidence must be a regular non-symlink file"
    cmp -s -- "$source" "$destination" \
      || fail "durable regional evidence does not match the supplied owner file"
    return
  fi
  snapshot_regional_input "$source" "$destination" \
    || fail "cannot atomically publish durable regional evidence"
}

publish_regional_invariance_pair() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$1" "$2" "$3" "$4" <<'PY'
import os
import stat
import sys
from pathlib import Path

federal_source, federal_destination, public_source, public_destination = map(Path, sys.argv[1:])
pairs = (
    (federal_source, federal_destination),
    (public_source, public_destination),
)
for source, _destination in pairs:
    if source.is_symlink() or not source.is_file() or stat.S_IMODE(source.stat().st_mode) != 0o600:
        raise SystemExit("regional invariance source must be a regular mode-0600 file")
existing = tuple(destination.exists() or destination.is_symlink() for _source, destination in pairs)
if any(existing):
    if existing != (True, True):
        raise SystemExit("regional invariance evidence is partially published")
    for source, destination in pairs:
        if (
            destination.is_symlink()
            or not destination.is_file()
            or stat.S_IMODE(destination.stat().st_mode) != 0o600
            or source.read_bytes() != destination.read_bytes()
        ):
            raise SystemExit("regional invariance evidence does not match derived owner bytes")
    raise SystemExit(0)

published: list[Path] = []
try:
    for source, destination in pairs:
        os.link(source, destination, follow_symlinks=False)
        published.append(destination)
    directory_fd = os.open(federal_destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except BaseException:
    for destination in reversed(published):
        destination.unlink(missing_ok=True)
    raise
PY
}

publish_once_regional_input() {
  local source="$1"
  local destination="$2"
  if [[ -e "$destination" || -L "$destination" ]]; then
    [[ -f "$destination" && ! -L "$destination" ]] \
      || fail "durable regional evidence must be a regular non-symlink file"
    [[ "$(stat -f '%Lp' "$destination")" == "600" ]] \
      || fail "durable regional evidence must remain mode 0600"
    return
  fi
  snapshot_regional_input "$source" "$destination" \
    || fail "cannot atomically publish durable regional evidence"
}

publish_empty_regional_inventory() {
  local destination="$1"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$destination" <<'PY'
import os
import secrets
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = b"[]\n"
if path.exists() or path.is_symlink():
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600 or path.read_bytes() != data:
        raise SystemExit("durable empty inventory byte identity mismatch")
else:
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise SystemExit("durable empty inventory byte identity mismatch")
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
PY
}

regional_marker() {
  local path="$1"
  local kind="$2"
  local machine_id="${3:-}"
  local federal_before="${4:-}"
  local public_before="${5:-}"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$path" "$kind" "$REGIONAL_APP" "$REGIONAL_MACHINE_NAME" "$machine_id" \
    "$REGIONAL_AUTHORITY" "$REGIONAL_EXECUTION_PLAN" \
    "$REGIONAL_PROFILE_FILE_SHA" "$REGIONAL_RECEIPT_FILE_SHA" \
    "$federal_before" "$public_before" <<'PY'
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path

from domains.campaign_finance.coverage.lifecycle import (
    RawInvarianceSnapshot,
    RawRegionalLifecycleMarker,
    invariance_capture_time_is_fresh,
)

(
    path_text,
    kind,
    app,
    name,
    machine_id,
    authority,
    plan,
    profile_sha,
    receipt_sha,
    federal_before_text,
    public_before_text,
) = sys.argv[1:]
path = Path(path_text)
payload = {
    "app": app,
    "authority": authority,
    "execution_plan": plan,
    "kind": kind,
    "machine_id": machine_id or None,
    "machine_name": name,
    "profile_file_sha256": profile_sha,
    "candidate_receipt_file_sha256": receipt_sha,
    "schema_version": 2,
}
if bool(federal_before_text) != bool(public_before_text):
    raise SystemExit("start admission requires both exact before snapshots")
if federal_before_text:
    if kind != "regional_start_attempt":
        raise SystemExit("invariance admission is valid only for a start-attempt marker")
    admitted_at = datetime.now(timezone.utc)
    references = {}
    captured_times = []
    for expected_scope, snapshot_text in (
        ("federal", federal_before_text),
        ("public", public_before_text),
    ):
        snapshot_path = Path(snapshot_text)
        if (
            not snapshot_path.is_file()
            or snapshot_path.is_symlink()
            or stat.S_IMODE(snapshot_path.stat().st_mode) != 0o600
        ):
            raise SystemExit("start admission snapshot must be a regular mode-0600 file")
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = RawInvarianceSnapshot.model_validate_json(snapshot_bytes)
        if snapshot.scope != expected_scope or snapshot.stage != "before":
            raise SystemExit("start admission snapshot scope or stage mismatch")
        if not invariance_capture_time_is_fresh(snapshot.captured_at, admitted_at=admitted_at):
            raise SystemExit("start admission snapshot is stale or future")
        captured_times.append(snapshot.captured_at)
        references[f"{expected_scope}_before"] = {
            "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "identity_sha256": snapshot.identity_sha256,
        }
    if captured_times[0] != captured_times[1]:
        raise SystemExit("start admission snapshot capture times are split")
    payload["schema_version"] = 3
    payload["invariance_admission"] = {
        "admitted_at": admitted_at.isoformat().replace("+00:00", "Z"),
        "max_age_seconds": 600,
        "future_skew_seconds": 60,
        **references,
    }
RawRegionalLifecycleMarker.model_validate(payload)
data = (json.dumps(payload, sort_keys=True) + "\n").encode()
temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
try:
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path, follow_symlinks=False)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    temporary.unlink(missing_ok=True)
PY
}

regional_marker_machine_id() {
  local path="$1"
  local expected_kind="$2"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$path" "$expected_kind" "$REGIONAL_APP" "$REGIONAL_MACHINE_NAME" \
    "$REGIONAL_AUTHORITY" "$REGIONAL_EXECUTION_PLAN" \
    "$REGIONAL_PROFILE_FILE_SHA" "$REGIONAL_RECEIPT_FILE_SHA" <<'PY'
import json
import re
import sys
from pathlib import Path

from domains.campaign_finance.coverage.lifecycle import RawRegionalLifecycleMarker

path = Path(sys.argv[1])
if not path.is_file() or path.is_symlink():
    raise SystemExit("regional lifecycle marker must be a regular non-symlink file")
text = path.read_text(encoding="utf-8")

def reject_duplicate_keys(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise SystemExit("regional lifecycle marker contains duplicate keys")
        payload[key] = value
    return payload

payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
if text != json.dumps(payload, sort_keys=True) + "\n":
    raise SystemExit("regional lifecycle marker byte identity mismatch")
expected = {
    "app": sys.argv[3], "kind": sys.argv[2], "machine_name": sys.argv[4],
    "authority": sys.argv[5], "execution_plan": sys.argv[6],
    "profile_file_sha256": sys.argv[7], "candidate_receipt_file_sha256": sys.argv[8],
}
if not isinstance(payload, dict):
    raise SystemExit("regional lifecycle marker shape mismatch")
schema_version = payload.get("schema_version")
expected_keys = set(expected) | {"machine_id", "schema_version"}
if schema_version == 3:
    expected_keys.add("invariance_admission")
if set(payload) != expected_keys:
    raise SystemExit("regional lifecycle marker shape mismatch")
try:
    marker = RawRegionalLifecycleMarker.model_validate(payload)
except Exception as error:
    raise SystemExit("regional lifecycle marker shape mismatch") from error
if any(payload.get(key) != value for key, value in expected.items()):
    raise SystemExit("regional lifecycle marker identity mismatch")
machine_id = marker.machine_id
if machine_id is not None and (not isinstance(machine_id, str) or re.fullmatch(r"[0-9a-f]+", machine_id) is None):
    raise SystemExit("regional lifecycle marker Machine id mismatch")
print(machine_id or "")
PY
}

regional_marker_matches_machine_id() {
  local actual_machine_id
  actual_machine_id="$(regional_marker_machine_id "$1" "$2")" || return 1
  [[ "$actual_machine_id" == "$3" ]]
}

verify_regional_refresh_postcondition() {
  local path="$1"
  local expected_machine_id="$2"
  local require_success="$3"
  local expected_refresh_run_id="${4:-}"
  local require_historical_failure="${5:-false}"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$path" "$REGIONAL_APP" "$expected_machine_id" "$REGIONAL_AUTHORITY" \
    "$REGIONAL_EXECUTION_PLAN" "$REGIONAL_CANARY_JOB" "$require_success" \
    "$REGIONAL_DB_HOST" "$REGIONAL_DB_PORT" "$REGIONAL_DB_NAME" \
    "$expected_refresh_run_id" "$require_historical_failure" <<'PY'
import json
import re
import sys
from datetime import datetime
from pathlib import Path

(
    path_text, expected_app, expected_machine_id, expected_authority,
    expected_plan, expected_job, require_success_text,
    expected_db_host, expected_db_port, expected_db_name,
    expected_refresh_run_id, require_historical_failure_text,
) = sys.argv[1:]
path = Path(path_text)
if not path.is_file() or path.is_symlink():
    raise SystemExit("refresh postcondition must be a regular non-symlink file")
text = path.read_text(encoding="utf-8")

def reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SystemExit("refresh postcondition contains duplicate keys")
        value[key] = item
    return value

payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
if text != json.dumps(payload, sort_keys=True) + "\n":
    raise SystemExit("refresh postcondition byte identity mismatch")
expected_keys = {
    "active_refresh_backends", "app", "authority", "completed_at", "database",
    "execution_origin", "execution_plan", "job_key", "machine_id", "metadata_updates",
    "pull_status", "refresh_run_id", "running_refresh_rows", "long_idle_transactions",
    "ungranted_locks", "schema_version",
}
if not isinstance(payload, dict) or set(payload) != expected_keys:
    raise SystemExit("refresh postcondition shape mismatch")
database = payload.get("database")
identity_matches = (
    payload.get("schema_version") == 1
    and payload.get("app") == expected_app
    and payload.get("authority") == expected_authority
    and payload.get("execution_plan") == expected_plan
    and payload.get("job_key") == expected_job
    and payload.get("execution_origin") == "operator_attended"
    and isinstance(payload.get("machine_id"), str)
    and (not expected_machine_id or payload.get("machine_id") == expected_machine_id)
    and isinstance(payload.get("refresh_run_id"), str)
    and re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        payload["refresh_run_id"],
    )
    and database == {"host": expected_db_host, "name": expected_db_name, "port": int(expected_db_port)}
)
if not identity_matches:
    raise SystemExit("refresh postcondition identity mismatch")
if expected_refresh_run_id and payload["refresh_run_id"] != expected_refresh_run_id:
    raise SystemExit("refresh postcondition attempt identity mismatch")
for field in (
    "metadata_updates", "running_refresh_rows", "active_refresh_backends",
    "long_idle_transactions", "ungranted_locks",
):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemExit(f"refresh postcondition {field} is invalid")
terminal_statuses = {"crashed", "empty", "degraded", "failed", "success"}
if payload.get("pull_status") not in terminal_statuses or not isinstance(payload.get("completed_at"), str):
    raise SystemExit("exact refresh attempt is not terminal")
try:
    completed_at = datetime.fromisoformat(payload["completed_at"].replace("Z", "+00:00"))
except ValueError as error:
    raise SystemExit("exact refresh attempt completed_at is invalid") from error
if completed_at.tzinfo is None:
    raise SystemExit("exact refresh attempt completed_at is invalid")
if payload["running_refresh_rows"] != 0:
    raise SystemExit("exact refresh attempt is not terminal; running refresh rows remain")
if payload["active_refresh_backends"] != 0:
    raise SystemExit("active refresh backends remain")
if payload["long_idle_transactions"] != 0:
    raise SystemExit("long-idle database transactions remain")
if payload["ungranted_locks"] != 0:
    raise SystemExit("ungranted database locks remain")
if require_historical_failure_text == "true":
    if payload["pull_status"] != "failed":
        raise SystemExit("historical rollback requires the recovered failed refresh attempt")
    if payload["metadata_updates"] != 0:
        raise SystemExit("historical rollback requires zero metadata updates")
elif require_success_text == "true":
    if payload["pull_status"] != "success" or payload["metadata_updates"] != 1:
        raise SystemExit("complete canary refresh postcondition is required before recurring provisioning")
elif payload["pull_status"] != "success" and payload["metadata_updates"] != 0:
    raise SystemExit("failed refresh postcondition cannot promote source freshness")
print(payload["refresh_run_id"])
PY
}

validate_regional_invariance_snapshot() {
  local path="$1"
  local expected_scope="$2"
  local expected_stage="$3"
  local expected_machine_id="$4"
  local admission_marker="${5:-}"
  local terminal_machine="${6:-}"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$path" "$expected_scope" "$REGIONAL_CANDIDATE_SOURCE_SHA" \
    "$REGIONAL_DB_HOST" "$REGIONAL_DB_PORT" "$REGIONAL_DB_NAME" \
    "$expected_stage" "$expected_machine_id" "$REGIONAL_CANDIDATE_TREE_SHA" \
    "$REGIONAL_CANONICAL_RECEIPT_SHA" "$REGIONAL_CANONICAL_SOURCE_SHA" \
    "$REGIONAL_CANONICAL_TREE_SHA" "$REGIONAL_AUTHORITY" \
    "$REGIONAL_EXECUTION_PLAN" "$REGIONAL_CANARY_JOB" \
    "$REGIONAL_PROFILE_FILE_SHA" "$REGIONAL_RECEIPT_FILE_SHA" \
    "$REGIONAL_IMAGE" "$REGIONAL_APP" "$REGIONAL_MACHINE_NAME" \
    "$REGIONAL_MACHINE_CONFIG_SHA" "$admission_marker" "$terminal_machine" <<'PY'
from datetime import datetime, timedelta, timezone
import hashlib
import json
import stat
import sys
from pathlib import Path

from domains.campaign_finance.coverage.lifecycle import (
    RawCanaryTerminalMachine,
    RawInvarianceSnapshot,
    RawRegionalLifecycleMarker,
    invariance_capture_time_is_fresh,
)

path = Path(sys.argv[1])
if not path.is_file() or path.is_symlink():
    raise SystemExit("invariance snapshot must be a regular non-symlink file")
snapshot_bytes = path.read_bytes()
snapshot = RawInvarianceSnapshot.model_validate_json(snapshot_bytes)
expected_database = {"host": sys.argv[4], "port": int(sys.argv[5]), "name": sys.argv[6]}
authority_kind, authority_code = sys.argv[13].split("/", maxsplit=1)
expected_identity = (
    "regional_lifecycle_invariance_capture",
    sys.argv[7],
    sys.argv[2],
    sys.argv[3],
    sys.argv[9],
    sys.argv[10],
    sys.argv[11],
    {"kind": authority_kind, "code": authority_code},
    sys.argv[14],
    sys.argv[15],
    "operator_attended",
    sys.argv[16],
    sys.argv[17],
    sys.argv[18],
    sys.argv[19],
    sys.argv[8],
    sys.argv[20],
    sys.argv[21],
    expected_database,
)
actual_identity = (
    snapshot.producer,
    snapshot.stage,
    snapshot.scope,
    snapshot.source_revision,
    snapshot.source_tree_git_sha,
    snapshot.canonical_receipt_git_sha,
    snapshot.canonical_source_git_sha,
    snapshot.authority.model_dump(mode="json"),
    snapshot.execution_plan,
    snapshot.job_key,
    snapshot.execution_origin,
    snapshot.profile_file_sha256,
    snapshot.candidate_receipt_file_sha256,
    snapshot.qualified_image,
    snapshot.app,
    snapshot.machine_id,
    snapshot.machine_name,
    snapshot.machine_config_sha256,
    snapshot.database.model_dump(mode="json"),
)
captured_at = snapshot.captured_at
now = datetime.now(timezone.utc)
identity_matches = actual_identity == expected_identity
tree_matches = snapshot.canonical_tree_git_sha == sys.argv[12]
fresh = now - timedelta(minutes=10) <= captured_at <= now + timedelta(minutes=1)
admission_marker_text = sys.argv[22]
terminal_machine_text = sys.argv[23]
if admission_marker_text:
    marker_path = Path(admission_marker_text)
    if (
        not marker_path.is_file()
        or marker_path.is_symlink()
        or stat.S_IMODE(marker_path.stat().st_mode) != 0o600
    ):
        raise SystemExit("start-admission marker must be a regular mode-0600 file")
    marker = RawRegionalLifecycleMarker.model_validate_json(marker_path.read_bytes())
    expected_marker_identity = (
        3,
        sys.argv[19],
        sys.argv[13],
        sys.argv[14],
        "regional_start_attempt",
        sys.argv[8],
        sys.argv[20],
        sys.argv[16],
        sys.argv[17],
    )
    marker_identity = (
        marker.schema_version,
        marker.app,
        marker.authority,
        marker.execution_plan,
        marker.kind,
        marker.machine_id,
        marker.machine_name,
        marker.profile_file_sha256,
        marker.candidate_receipt_file_sha256,
    )
    admission = marker.invariance_admission
    if marker_identity != expected_marker_identity or admission is None:
        raise SystemExit("start-admission marker identity mismatch")
    reference = getattr(admission, f"{sys.argv[2]}_before")
    fresh = (
        invariance_capture_time_is_fresh(
            captured_at,
            admitted_at=admission.admitted_at,
            max_age_seconds=admission.max_age_seconds,
            future_skew_seconds=admission.future_skew_seconds,
        )
        and admission.admitted_at <= now + timedelta(minutes=1)
        and hashlib.sha256(snapshot_bytes).hexdigest() == reference.snapshot_sha256
        and snapshot.identity_sha256 == reference.identity_sha256
    )
    if terminal_machine_text:
        terminal_path = Path(terminal_machine_text)
        if (
            not terminal_path.is_file()
            or terminal_path.is_symlink()
            or stat.S_IMODE(terminal_path.stat().st_mode) != 0o600
        ):
            raise SystemExit("terminal Machine evidence must be a regular mode-0600 file")
        terminal = RawCanaryTerminalMachine.model_validate_json(terminal_path.read_bytes())
        terminal_identity = (
            terminal.app,
            terminal.machine_id,
            terminal.machine_name,
            terminal.image,
            terminal.machine_config_sha256,
        )
        expected_terminal_identity = (
            sys.argv[19],
            sys.argv[8],
            sys.argv[20],
            sys.argv[18],
            sys.argv[21],
        )
        fresh = fresh and terminal_identity == expected_terminal_identity and (
            admission.admitted_at
            <= terminal.occurred_at
            <= admission.admitted_at + timedelta(minutes=30)
        )
if not identity_matches or not tree_matches or not fresh:
    raise SystemExit(
        "invariance snapshot provenance, identity, stage, or freshness mismatch: "
        f"identity={identity_matches} "
        f"identity_fields={[index for index, values in enumerate(zip(actual_identity, expected_identity)) if values[0] != values[1]]} "
        f"tree={tree_matches} "
        f"fresh={fresh}"
    )
print(snapshot.identity_sha256)
PY
}

validate_regional_canary_evidence_set() {
  local proof_path="$1"
  local postcondition_path="$2"
  local machine_id="$3"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m core.refresh.authority_ledger \
    --profile-json "$REGIONAL_PROFILE_JSON" --proof-json "$proof_path" >/dev/null \
    || fail "regional canary authority ledger proof is not exact"
  local refresh_run_id
  refresh_run_id="$(verify_regional_refresh_postcondition \
    "$postcondition_path" "$machine_id" true)" \
    || fail "regional canary database postcondition is not exact successful zero-state evidence"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$proof_path" "$refresh_run_id" "$REGIONAL_AUTHORITY" \
    "$REGIONAL_EXECUTION_PLAN" "$REGIONAL_CANARY_JOB" <<'PY'
import json
import sys
from pathlib import Path

proof = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
runs = proof.get("refresh_runs") if isinstance(proof, dict) else None
if not isinstance(runs, list) or len(runs) != 1:
    raise SystemExit("canary proof must contain exactly one refresh run")
run = runs[0]
authority = proof.get("authority")
authority_identity = f"{authority.get('kind')}/{authority.get('code')}" if isinstance(authority, dict) else ""
if (
    proof.get("execution_mode") != "canary"
    or authority_identity != sys.argv[3]
    or proof.get("execution_plan_id") != sys.argv[4]
    or run.get("refresh_run_id") != sys.argv[2]
    or run.get("job_key") != sys.argv[5]
    or run.get("execution_origin") != "operator_attended"
    or run.get("pull_status") != "success"
):
    raise SystemExit("canary proof and database postcondition attempt identity mismatch")
PY
}

publish_regional_terminal_machine() {
  local machine_inventory="$1"
  local destination="$2"
  local machine_id="$3"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$machine_inventory" "$destination" "$REGIONAL_APP" "$machine_id" "$REGIONAL_MACHINE_NAME" \
    "$REGIONAL_IMAGE" "$REGIONAL_MACHINE_CONFIG_SHA" <<'PY'
from datetime import datetime, timezone
import json
import os
import secrets
import sys
from pathlib import Path

inventory_text, path_text, app, machine_id, machine_name, image, config_sha = sys.argv[1:]
machines = json.loads(Path(inventory_text).read_text(encoding="utf-8"))
if not isinstance(machines, list) or len(machines) != 1 or not isinstance(machines[0], dict):
    raise SystemExit("terminal Machine inventory must contain exactly one Machine")
machine = machines[0]
if (
    machine.get("id") != machine_id
    or machine.get("name") != machine_name
    or machine.get("state") != "stopped"
):
    raise SystemExit("terminal Machine identity or state mismatch")
image_ref = machine.get("image_ref")
if not isinstance(image_ref, dict):
    raise SystemExit("terminal Machine has no structured image identity")
registry = image_ref.get("registry")
repository = image_ref.get("repository")
tag = image_ref.get("tag")
digest = image_ref.get("digest")
if not all(isinstance(value, str) and value for value in (registry, repository, tag, digest)):
    raise SystemExit("terminal Machine image identity is incomplete")
observed_image = f"{registry}/{repository}:{tag}@{digest}"
if observed_image != image:
    raise SystemExit("terminal Machine image identity mismatch")

events = machine.get("events")
if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
    raise SystemExit("terminal Machine events are malformed")
start_events = [event for event in events if event.get("type") == "start"]
exit_events = [event for event in events if event.get("type") == "exit"]
if len(start_events) != 1 or len(exit_events) != 1:
    raise SystemExit("terminal Machine requires exactly one start and one exit event")
start_event = start_events[0]
exit_event = exit_events[0]
if start_event.get("status") != "started" or exit_event.get("status") != "stopped":
    raise SystemExit("terminal Machine start or exit status mismatch")
start_timestamp = start_event.get("timestamp")
exit_timestamp = exit_event.get("timestamp")
if (
    not isinstance(start_timestamp, int)
    or isinstance(start_timestamp, bool)
    or not isinstance(exit_timestamp, int)
    or isinstance(exit_timestamp, bool)
    or start_timestamp <= 0
    or exit_timestamp <= start_timestamp
):
    raise SystemExit("terminal Machine event timestamps are invalid or reordered")
request = exit_event.get("request")
if not isinstance(request, dict):
    raise SystemExit("terminal Machine exit request is absent")
exit_evidence = []
direct_exit = request.get("exit_event")
if isinstance(direct_exit, dict):
    exit_evidence.append(direct_exit)
for monitor_key in ("monitor_event", "MonitorEvent"):
    monitor = request.get(monitor_key)
    if isinstance(monitor, dict) and isinstance(monitor.get("exit_event"), dict):
        exit_evidence.append(monitor["exit_event"])
exit_codes = [item.get("exit_code") for item in exit_evidence]
if exit_codes != [0]:
    raise SystemExit("terminal Machine requires one unambiguous zero exit code")

path = Path(path_text)
captured_at_value = datetime.now(timezone.utc)
occurred_at_value = datetime.fromtimestamp(exit_timestamp / 1000, timezone.utc)
if occurred_at_value > captured_at_value:
    raise SystemExit("terminal Machine exit event is future-dated")
captured_at = captured_at_value.isoformat().replace("+00:00", "Z")
occurred_at = occurred_at_value.isoformat().replace("+00:00", "Z")
payload = {
    "app": app,
    "captured_at": captured_at,
    "exit_code": 0,
    "image": image,
    "machine_config_sha256": config_sha,
    "machine_id": machine_id,
    "machine_name": machine_name,
    "occurred_at": occurred_at,
    "schema_version": 1,
    "state": "stopped",
}
data = (json.dumps(payload, sort_keys=True) + "\n").encode()
temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
try:
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path, follow_symlinks=False)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    temporary.unlink(missing_ok=True)
PY
}

regional_app_inventory_state() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$1" "$REGIONAL_APP" <<'PY'
import json
import sys
from pathlib import Path

apps = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(apps, list):
    raise SystemExit("regional app inventory must be a JSON list")
matches = []
for app in apps:
    if not isinstance(app, dict):
        raise SystemExit("regional app inventory contains a malformed row")
    name = app.get("Name", app.get("name"))
    app_id = app.get("ID")
    if not isinstance(name, str) or not isinstance(app_id, str):
        raise SystemExit("regional app inventory row has no string name or ID")
    if name == sys.argv[2] or app_id == sys.argv[2]:
        matches.append(app)
if not matches:
    print("absent")
elif len(matches) == 1:
    print("present")
else:
    raise SystemExit("regional app inventory is ambiguous")
PY
}

complete_absent_historical_rollback() {
  local ownership="$1"
  local machine_ownership="$2"
  local provision="$3"
  local start_attempt="$4"
  local canary_mode="$5"
  local canary_machine_terminal="$6"
  local rollback_attempt="$7"
  local rollback_stopped="$8"
  local rollback_complete="$9"

  [[ -n "$REGIONAL_EXPECTED_REFRESH_RUN_ID" ]] \
    || fail "absent-app historical rollback requires the exact refresh attempt id"
  [[ -n "$REGIONAL_REFRESH_POSTCONDITION_JSON" ]] \
    || fail "absent-app historical rollback requires the recovered refresh postcondition"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$REGIONAL_LIFECYCLE_DIR" "$rollback_stopped" "$rollback_complete" <<'PY' \
    || fail "absent-app historical rollback marker inventory is not exact"
import stat
import sys
from pathlib import Path

lifecycle_dir = Path(sys.argv[1])
required = {
    "canary_mode.json",
    "candidate_receipt.json",
    "create_ownership.json",
    "machine_ownership.json",
    "profile.json",
    "provision.json",
    "rollback_apps_after.json",
    "rollback_apps_before.json",
    "rollback_attempt.json",
    "rollback_machines_after.json",
    "rollback_machines_before.json",
    "rollback_volumes_after.json",
    "rollback_volumes_before.json",
    "start_attempt.json",
}
optional = {Path(sys.argv[2]).name, Path(sys.argv[3]).name}
entries = {path.name for path in lifecycle_dir.iterdir() if not path.name.startswith(".capture.")}
if not required.issubset(entries) or not entries.issubset(required | optional):
    raise SystemExit("historical rollback requires the exact retained marker set")
for name in entries:
    path = lifecycle_dir / name
    if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise SystemExit("historical rollback markers must be regular non-symlink mode-0600 files")
if Path(sys.argv[3]).exists() and not Path(sys.argv[2]).exists():
    raise SystemExit("historical rollback completion exists without the stopped boundary")
PY
  [[ ! -e "$canary_machine_terminal" && ! -L "$canary_machine_terminal" ]] \
    || fail "absent-app historical rollback refuses a foreign canary terminal marker"
  local ownership_machine_id
  ownership_machine_id="$(regional_marker_machine_id "$ownership" "regional_create_ownership")" \
    || fail "historical app ownership marker validation failed"
  [[ -z "$ownership_machine_id" ]] \
    || fail "historical app ownership marker unexpectedly owns a Machine"
  local machine_id
  machine_id="$(regional_marker_machine_id "$machine_ownership" "regional_machine_ownership")" \
    || fail "historical Machine ownership marker validation failed"
  [[ -n "$machine_id" ]] || fail "historical Machine ownership marker has no Machine id"
  regional_marker_matches_machine_id "$provision" "regional_stopped_provision" "$machine_id" \
    || fail "historical provision marker does not match exact Machine ownership"
  regional_marker_matches_machine_id "$start_attempt" "regional_start_attempt" "$machine_id" \
    || fail "historical start marker does not match exact Machine ownership"
  regional_marker_matches_machine_id "$canary_mode" "regional_canary_mode" "$machine_id" \
    || fail "historical canary marker does not match exact Machine ownership"
  local rollback_attempt_machine_id
  rollback_attempt_machine_id="$(regional_marker_machine_id "$rollback_attempt" "regional_rollback_attempt")" \
    || fail "historical rollback-attempt marker validation failed"
  [[ -z "$rollback_attempt_machine_id" ]] \
    || fail "historical rollback-attempt marker unexpectedly owns a Machine"
  verify_regional_refresh_postcondition \
    "$REGIONAL_REFRESH_POSTCONDITION_JSON" "$machine_id" false \
    "$REGIONAL_EXPECTED_REFRESH_RUN_ID" true >/dev/null \
    || fail "absent-app historical rollback postcondition is not exact failed zero-state evidence"
  if [[ -e "$rollback_stopped" || -L "$rollback_stopped" ]]; then
    regional_marker_matches_machine_id "$rollback_stopped" "regional_rollback_stopped" "$machine_id" \
      || fail "historical rollback-stopped marker does not match exact Machine ownership"
  else
    regional_marker "$rollback_stopped" "regional_rollback_stopped" "$machine_id" \
      || fail "cannot publish historical stopped rollback boundary"
  fi
  if [[ -e "$rollback_complete" || -L "$rollback_complete" ]]; then
    regional_marker_matches_machine_id "$rollback_complete" "regional_rollback_complete" "$machine_id" \
      || fail "historical rollback-complete marker does not match exact Machine ownership"
  else
    regional_marker "$rollback_complete" "regional_rollback_complete" "$machine_id" \
      || fail "cannot publish historical rollback completion"
  fi
}

capture_regional_live() {
  local capture_dir="$1"
  flyctl status -a "$REGIONAL_APP" --json >"$capture_dir/app.json" \
    || fail "regional app probe failed"
  flyctl machines list -a "$REGIONAL_APP" --json >"$capture_dir/machines.json" \
    || fail "regional Machine inventory probe failed"
}

require_regional_app_absent() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$1" "$REGIONAL_APP" <<'PY'
import json
import sys
from pathlib import Path

apps = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(apps, list):
    raise SystemExit("regional app inventory must be a JSON list")
for app in apps:
    if not isinstance(app, dict):
        raise SystemExit("regional app inventory contains a malformed row")
    name = app.get("Name", app.get("name"))
    app_id = app.get("ID")
    if not isinstance(name, str) or not isinstance(app_id, str):
        raise SystemExit("regional app inventory row has no string name or ID")
    if name == sys.argv[2] or app_id == sys.argv[2]:
        raise SystemExit("regional app is present")
PY
}

verify_regional_app() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$1" "$REGIONAL_APP" "$REGIONAL_ORGANIZATION" "$REGIONAL_ORGANIZATION_ID" <<'PY'
import json
import sys
from pathlib import Path

app = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
organization = app.get("Organization") if isinstance(app, dict) else None
if (
    not isinstance(organization, dict)
    or app.get("Name", app.get("name")) != sys.argv[2]
    or app.get("ID") != sys.argv[2]
    or organization.get("Slug") != sys.argv[3]
    or organization.get("ID") != sys.argv[4]
):
    raise SystemExit("regional app identity mismatch")
PY
}

regional_single_machine_id() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$1" "$REGIONAL_MACHINE_NAME" <<'PY'
import json
import re
import sys
from pathlib import Path

machines = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(machines, list) or len(machines) != 1 or machines[0].get("name") != sys.argv[2]:
    raise SystemExit("expected exactly one named regional Machine")
machine_id = machines[0].get("id")
if not isinstance(machine_id, str) or re.fullmatch(r"[0-9a-f]+", machine_id) is None:
    raise SystemExit("regional Machine id is invalid")
print(machine_id)
PY
}

regional_owned_machine_state() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
    "$1" "$2" "$REGIONAL_MACHINE_NAME" "$REGIONAL_REGION" <<'PY'
import json
import sys
from pathlib import Path

machines = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_id, expected_name, expected_region = sys.argv[2:]
if not isinstance(machines, list):
    raise SystemExit("regional Machine inventory is malformed")
if not expected_id:
    if machines:
        raise SystemExit("regional Machine exists without an exact ownership marker")
    print("")
elif (
    len(machines) != 1
    or not isinstance(machines[0], dict)
    or machines[0].get("id") != expected_id
    or machines[0].get("name") != expected_name
    or machines[0].get("region") != expected_region
):
    raise SystemExit("regional Machine inventory does not match exact ownership")
else:
    print(machines[0].get("state", ""))
PY
}

verify_regional_live() {
  local capture_dir="$1"
  local expected_state="$2"
  local machine_id="$3"
  flyctl machine status "$machine_id" -a "$REGIONAL_APP" --display-config \
    | PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -c '
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
config_kind = sys.argv[2]
expected = profile["machine"]["config"]
if config_kind == "canary":
    expected = json.loads(json.dumps(expected))
    expected["init"]["cmd"] = profile["canary"]["command"]
    expected.pop("schedule", None)
    plan = profile["execution_plan"]
    authority = plan["authority"]
    expected["metadata"] = {
        "civibus_authority": authority["kind"] + "/" + authority["code"],
        "civibus_execution_plan": plan["plan_id"],
        "civibus_job_key": plan["canary"]["job_keys"][0],
        "civibus_profile": profile["profile_id"],
    }
elif config_kind != "recurring":
    raise SystemExit("unknown regional Machine config kind")
raw = json.load(sys.stdin)
if not isinstance(raw, dict):
    raise SystemExit("regional Machine config shape mismatch")
for key, default in (
    ("auto_destroy", False),
    ("files", []),
    ("mounts", []),
    ("services", []),
):
    if key not in raw and expected.get(key) == default:
        raw[key] = default
if raw.get("auto_destroy") is not False:
    raise SystemExit("regional Machine config value mismatch")
if any(not isinstance(raw.get(key), list) for key in ("files", "mounts", "services")):
    raise SystemExit("regional Machine config value mismatch")
if "dns" in raw:
    if not isinstance(raw["dns"], dict) or raw["dns"]:
        raise SystemExit("regional Machine config value mismatch")
    raw.pop("dns")
if set(raw) != set(expected) | {"image"}:
    raise SystemExit("regional Machine config shape mismatch")
if any(raw.get(key) != value for key, value in expected.items()):
    raise SystemExit("regional Machine config value mismatch")
image = raw.get("image")
if not isinstance(image, str):
    raise SystemExit("regional Machine image identity is absent")
safe = dict(expected)
safe["image"] = image
json.dump(safe, sys.stdout, sort_keys=True)
' "$REGIONAL_PROFILE_JSON" "$REGIONAL_CONFIG_KIND" >"$capture_dir/config.json" \
    || fail "regional Machine config probe failed"
  bash "$VERIFIER" --profile-json "$REGIONAL_PROFILE_JSON" \
    --candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
    --regional-app-json "$capture_dir/app.json" \
    --regional-machines-json "$capture_dir/machines.json" \
    --regional-machine-config-json "$capture_dir/config.json" \
    --regional-expected-state "$expected_state" --regional-machine-id "$machine_id" \
    --regional-config-kind "$REGIONAL_CONFIG_KIND" >/dev/null \
    || fail "regional live contract verification failed"
}

capture_regional_invariance() {
  local capture_dir="$1"
  local machine_id="$2"
  local federal_destination="$3"
  local public_destination="$4"
  local stage="$REGIONAL_INVARIANCE_STAGE"

  if [[ -e "$federal_destination" || -L "$federal_destination" \
    || -e "$public_destination" || -L "$public_destination" ]]; then
    [[ -f "$federal_destination" && ! -L "$federal_destination" \
      && -f "$public_destination" && ! -L "$public_destination" ]] \
      || fail "regional invariance evidence is partially published or non-regular"
  fi

  local captured_at
  if [[ -f "$federal_destination" && -f "$public_destination" ]]; then
    validate_regional_invariance_snapshot \
      "$federal_destination" federal "$stage" "$machine_id" >/dev/null \
      || fail "existing federal invariance snapshot is invalid or stale"
    validate_regional_invariance_snapshot \
      "$public_destination" public "$stage" "$machine_id" >/dev/null \
      || fail "existing public invariance snapshot is invalid or stale"
    captured_at="$({
      PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
        "$federal_destination" "$public_destination" <<'PY'
import json
import sys
from pathlib import Path

federal = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
public = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if federal.get("captured_at") != public.get("captured_at"):
    raise SystemExit("existing regional invariance timestamps are split")
print(federal["captured_at"])
PY
    })" || fail "existing regional invariance capture time is invalid"
  else
    captured_at="$(PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
PY
    )" || fail "cannot establish regional invariance capture time"
  fi

  capture_regional_live "$capture_dir"
  verify_regional_live "$capture_dir" "stopped" "$machine_id"

  flyctl machines list -a "$APP_NAME" --json >"$capture_dir/federal_machines.json" \
    || fail "federal Machine inventory capture failed"
  flyctl machine status "$MACHINE_ID" -a "$APP_NAME" --display-config \
    >"$capture_dir/federal_machine_config.json" \
    || fail "federal Machine config capture failed"
  sanitize_machine_config "$capture_dir/federal_machine_config.json" \
    || fail "federal Machine config sanitization failed"
  flyctl volumes list -a "$APP_NAME" --json >"$capture_dir/federal_volumes.json" \
    || fail "federal volume inventory capture failed"
  curl --proto '=https' --fail --silent --show-error --max-time 10 "$VERSION_URL" \
    >"$capture_dir/federal_version.json" \
    || fail "federal version capture failed"
  bash "$VERIFIER" \
    --machines-json "$capture_dir/federal_machines.json" \
    --machine-config-json "$capture_dir/federal_machine_config.json" \
    --volumes-json "$capture_dir/federal_volumes.json" \
    --version-json "$capture_dir/federal_version.json" \
    >"$capture_dir/federal_verifier.log" \
    || fail "federal Machine invariance verifier failed"

  curl --proto '=https' --fail --silent --show-error --max-time 10 \
    "$PUBLIC_BASE_URL/api/health/version" >"$capture_dir/public_api_version.json" \
    || fail "public API version capture failed"
  curl --proto '=https' --fail --silent --show-error --max-time 10 \
    "$PUBLIC_BASE_URL/version.json" >"$capture_dir/public_web_version.json" \
    || fail "public web version capture failed"
  curl --proto '=https' --fail --silent --show-error --max-time 10 \
    "$PUBLIC_BASE_URL/api/health/content" >"$capture_dir/public_content_health.json" \
    || fail "public content-health capture failed"

  [[ -n "${POSTGRES_HOST:-}" && -n "${POSTGRES_PORT:-}" \
    && -n "${POSTGRES_USER:-}" && -n "${POSTGRES_DB:-}" ]] \
    || fail "capture-invariance requires explicit POSTGRES host, port, user, and database"
  [[ "$POSTGRES_PORT" =~ ^[1-9][0-9]{0,4}$ ]] \
    || fail "capture-invariance POSTGRES port is invalid"
  [[ "$POSTGRES_USER" == "$REGIONAL_DB_USER" && "$POSTGRES_DB" == "$REGIONAL_DB_NAME" ]] \
    || fail "capture-invariance database user or name is foreign"
  if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
    export PGPASSWORD="$POSTGRES_PASSWORD"
  else
    [[ -n "${PGPASSFILE:-}" && -f "$PGPASSFILE" && ! -L "$PGPASSFILE" \
      && "$(stat -f '%Lp' "$PGPASSFILE")" == "600" ]] \
      || fail "capture-invariance requires POSTGRES_PASSWORD or a mode-0600 PGPASSFILE"
  fi
  PGHOST="$POSTGRES_HOST" PGPORT="$POSTGRES_PORT" PGUSER="$POSTGRES_USER" \
    PGDATABASE="$POSTGRES_DB" PGAPPNAME='civibus:regional-invariance-capture' \
    PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
    psql -X -qAt -v ON_ERROR_STOP=1 >"$capture_dir/database_observation.json" <<'SQL' \
    || fail "regional invariance read-only database capture failed"
BEGIN READ ONLY;
SELECT json_build_object(
  'schema_version', 1,
  'application_name', current_setting('application_name'),
  'transaction_read_only', current_setting('transaction_read_only'),
  'default_transaction_read_only', current_setting('default_transaction_read_only'),
  'database_name', current_database(),
  'server_address', coalesce(inet_server_addr()::text, 'local'),
  'server_port', inet_server_port(),
  'running_refresh_rows', (
    SELECT count(*)::integer FROM core.refresh_run WHERE pull_status = 'running'
  ),
  'active_refresh_backends', (
    SELECT count(*)::integer
    FROM pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND datname = current_database()
      AND backend_type = 'client backend'
      AND application_name LIKE 'refresh:%'
  ),
  'long_idle_transactions', (
    SELECT count(*)::integer
    FROM pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND datname = current_database()
      AND state LIKE 'idle in transaction%'
      AND xact_start < now() - interval '30 minutes'
  ),
  'ungranted_locks', (
    SELECT count(*)::integer
    FROM pg_locks
    WHERE NOT granted
      AND pid <> pg_backend_pid()
      AND (database = 0 OR database = (SELECT oid FROM pg_database WHERE datname = current_database()))
  ),
  'advisory_locks', (
    SELECT count(*)::integer
    FROM pg_locks
    WHERE locktype = 'advisory'
      AND pid <> pg_backend_pid()
      AND (database = 0 OR database = (SELECT oid FROM pg_database WHERE datname = current_database()))
  )
);
ROLLBACK;
SQL
  unset PGPASSWORD

  local federal_output="$capture_dir/federal_invariance_${stage}.json"
  local public_output="$capture_dir/public_invariance_${stage}.json"
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m domains.campaign_finance.coverage.lifecycle \
    --regional-invariance-profile-json "$REGIONAL_PROFILE_JSON" \
    --regional-invariance-candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" \
    --regional-invariance-stage "$stage" \
    --regional-invariance-captured-at "$captured_at" \
    --regional-invariance-machine-id "$machine_id" \
    --regional-invariance-federal-machines-json "$capture_dir/federal_machines.json" \
    --regional-invariance-federal-machine-config-json "$capture_dir/federal_machine_config.json" \
    --regional-invariance-federal-volumes-json "$capture_dir/federal_volumes.json" \
    --regional-invariance-federal-version-json "$capture_dir/federal_version.json" \
    --regional-invariance-public-api-version-json "$capture_dir/public_api_version.json" \
    --regional-invariance-public-web-version-json "$capture_dir/public_web_version.json" \
    --regional-invariance-public-content-health-json "$capture_dir/public_content_health.json" \
    --regional-invariance-database-observation-json "$capture_dir/database_observation.json" \
    --regional-invariance-federal-output-json "$federal_output" \
    --regional-invariance-public-output-json "$public_output" >/dev/null \
    || fail "canonical regional invariance derivation failed"

  publish_regional_invariance_pair \
    "$federal_output" "$federal_destination" "$public_output" "$public_destination" \
    || fail "cannot atomically publish canonical regional invariance evidence"
  [[ "$(stat -f '%Lp' "$federal_destination")" == "600" \
    && "$(stat -f '%Lp' "$public_destination")" == "600" ]] \
    || fail "regional invariance evidence must be mode 0600"
  validate_regional_invariance_snapshot \
    "$federal_destination" federal "$stage" "$machine_id" >/dev/null \
    || fail "published federal invariance snapshot is invalid"
  validate_regional_invariance_snapshot \
    "$public_destination" public "$stage" "$machine_id" >/dev/null \
    || fail "published public invariance snapshot is invalid"
  printf 'PASS: canonical regional invariance captured stage=%s machine=%s\n' "$stage" "$machine_id"
}

regional_lifecycle() {
  [[ -d "$REGIONAL_LIFECYCLE_DIR" ]] || fail "regional lifecycle directory must already exist"
  REGIONAL_LIFECYCLE_DIR="$(cd "$REGIONAL_LIFECYCLE_DIR" && pwd -P)"
  require_external_evidence_dir "$REGIONAL_LIFECYCLE_DIR"

  local ownership="$REGIONAL_LIFECYCLE_DIR/create_ownership.json"
  local machine_ownership="$REGIONAL_LIFECYCLE_DIR/machine_ownership.json"
  local provision="$REGIONAL_LIFECYCLE_DIR/provision.json"
  local start_attempt="$REGIONAL_LIFECYCLE_DIR/start_attempt.json"
  local canary_mode="$REGIONAL_LIFECYCLE_DIR/canary_mode.json"
  local canary_machine_terminal="$REGIONAL_LIFECYCLE_DIR/canary_machine_terminal.json"
  local rollback_attempt="$REGIONAL_LIFECYCLE_DIR/rollback_attempt.json"
  local rollback_stopped="$REGIONAL_LIFECYCLE_DIR/rollback_stopped.json"
  local rollback_complete="$REGIONAL_LIFECYCLE_DIR/rollback_complete.json"
  local durable_profile="$REGIONAL_LIFECYCLE_DIR/profile.json"
  local durable_candidate="$REGIONAL_LIFECYCLE_DIR/candidate_receipt.json"
  local terminal_machine="$REGIONAL_LIFECYCLE_DIR/terminal_machine.json"
  local authority_ledger_proof="$REGIONAL_LIFECYCLE_DIR/authority_ledger_proof.json"
  local database_postcondition="$REGIONAL_LIFECYCLE_DIR/database_postcondition.json"
  local federal_invariance_before="$REGIONAL_LIFECYCLE_DIR/federal_invariance_before.json"
  local federal_invariance_after="$REGIONAL_LIFECYCLE_DIR/federal_invariance_after.json"
  local public_invariance_before="$REGIONAL_LIFECYCLE_DIR/public_invariance_before.json"
  local public_invariance_after="$REGIONAL_LIFECYCLE_DIR/public_invariance_after.json"
  local rollback_apps_before="$REGIONAL_LIFECYCLE_DIR/rollback_apps_before.json"
  local rollback_machines_before="$REGIONAL_LIFECYCLE_DIR/rollback_machines_before.json"
  local rollback_volumes_before="$REGIONAL_LIFECYCLE_DIR/rollback_volumes_before.json"
  local rollback_apps_after="$REGIONAL_LIFECYCLE_DIR/rollback_apps_after.json"
  local rollback_machines_after="$REGIONAL_LIFECYCLE_DIR/rollback_machines_after.json"
  local rollback_volumes_after="$REGIONAL_LIFECYCLE_DIR/rollback_volumes_after.json"
  local canary_promotion="$REGIONAL_LIFECYCLE_DIR/regional_canary_promotion.json"
  local capture_dir
  capture_dir="$(mktemp -d "$REGIONAL_LIFECYCLE_DIR/.capture.XXXXXX")" \
    || fail "cannot create regional capture directory"
  trap 'rm -rf -- "$capture_dir"' EXIT
  snapshot_regional_input "$REGIONAL_PROFILE_JSON" "$capture_dir/profile.json" \
    || fail "cannot snapshot regional profile"
  snapshot_regional_input "$REGIONAL_CANDIDATE_RECEIPT_JSON" "$capture_dir/candidate_receipt.json" \
    || fail "cannot snapshot regional candidate receipt"
  REGIONAL_PROFILE_JSON="$capture_dir/profile.json"
  REGIONAL_CANDIDATE_RECEIPT_JSON="$capture_dir/candidate_receipt.json"
  IFS=$'\t' read -r REGIONAL_APP REGIONAL_ORGANIZATION REGIONAL_ORGANIZATION_ID \
    REGIONAL_MACHINE_NAME REGIONAL_REGION REGIONAL_IMAGE \
    REGIONAL_AUTHORITY REGIONAL_EXECUTION_PLAN REGIONAL_CANARY_JOB \
    REGIONAL_DB_HOST REGIONAL_DB_PORT REGIONAL_DB_NAME REGIONAL_DB_USER \
    REGIONAL_PROFILE_FILE_SHA REGIONAL_RECEIPT_FILE_SHA \
    REGIONAL_CANDIDATE_SOURCE_SHA REGIONAL_CANDIDATE_TREE_SHA \
    REGIONAL_MACHINE_CONFIG_SHA REGIONAL_CANONICAL_RECEIPT_SHA \
    REGIONAL_CANONICAL_SOURCE_SHA REGIONAL_CANONICAL_TREE_SHA <<<"$(regional_context)" \
    || fail "cannot read regional lifecycle context"
  REGIONAL_CONFIG_KIND="recurring"
  if [[ "$REGIONAL_ACTION" == "create-canary-stopped" \
    || "$REGIONAL_ACTION" == "start-canary-once" \
    || -e "$canary_mode" || -L "$canary_mode" ]]; then
    REGIONAL_CONFIG_KIND="canary"
  fi
  if [[ -n "$REGIONAL_REFRESH_POSTCONDITION_JSON" ]]; then
    snapshot_regional_input "$REGIONAL_REFRESH_POSTCONDITION_JSON" "$capture_dir/refresh_postcondition.json" \
      || fail "cannot snapshot regional refresh postcondition"
    REGIONAL_REFRESH_POSTCONDITION_JSON="$capture_dir/refresh_postcondition.json"
  fi
  if [[ -n "$REGIONAL_AUTHORITY_LEDGER_PROOF_JSON" ]]; then
    snapshot_regional_input "$REGIONAL_AUTHORITY_LEDGER_PROOF_JSON" "$capture_dir/authority_ledger_proof.json" \
      || fail "cannot snapshot regional authority ledger proof"
    REGIONAL_AUTHORITY_LEDGER_PROOF_JSON="$capture_dir/authority_ledger_proof.json"
  fi
  if [[ -n "$REGIONAL_CANARY_PROMOTION_JSON" ]]; then
    snapshot_regional_input "$REGIONAL_CANARY_PROMOTION_JSON" "$capture_dir/canary_promotion.json" \
      || fail "cannot snapshot regional canary promotion artifact"
    REGIONAL_CANARY_PROMOTION_JSON="$capture_dir/canary_promotion.json"
  fi
  if [[ "$REGIONAL_ACTION" != "create-stopped" && "$REGIONAL_ACTION" != "create-canary-stopped" ]]; then
    if [[ ! -e "$durable_profile" && ! -L "$durable_profile" \
      && ! -e "$durable_candidate" && ! -L "$durable_candidate" \
      && "$REGIONAL_ACTION" == "rollback" ]]; then
      publish_or_match_regional_input "$REGIONAL_PROFILE_JSON" "$durable_profile"
      publish_or_match_regional_input "$REGIONAL_CANDIDATE_RECEIPT_JSON" "$durable_candidate"
    fi
    [[ -f "$durable_profile" && ! -L "$durable_profile" \
      && -f "$durable_candidate" && ! -L "$durable_candidate" ]] \
      || fail "regional lifecycle has no durable profile and candidate ownership snapshots"
    cmp -s -- "$REGIONAL_PROFILE_JSON" "$durable_profile" \
      || fail "regional profile changed after lifecycle creation"
    cmp -s -- "$REGIONAL_CANDIDATE_RECEIPT_JSON" "$durable_candidate" \
      || fail "regional candidate receipt changed after lifecycle creation"
    REGIONAL_PROFILE_JSON="$durable_profile"
    REGIONAL_CANDIDATE_RECEIPT_JSON="$durable_candidate"
  fi

  if [[ "$REGIONAL_ACTION" == "capture-invariance" ]]; then
    local machine_id
    machine_id="$(regional_marker_machine_id "$provision" "regional_stopped_provision")" \
      || fail "regional provision receipt validation failed before invariance capture"
    [[ -n "$machine_id" ]] || fail "regional provision receipt has no Machine id"
    regional_marker_matches_machine_id "$machine_ownership" "regional_machine_ownership" "$machine_id" \
      || fail "regional Machine ownership marker is invalid before invariance capture"
    regional_marker_matches_machine_id "$canary_mode" "regional_canary_mode" "$machine_id" \
      || fail "regional canary-mode marker is invalid before invariance capture"
    if [[ "$REGIONAL_INVARIANCE_STAGE" == "before" ]]; then
      [[ ! -e "$start_attempt" && ! -L "$start_attempt" \
        && ! -e "$canary_machine_terminal" && ! -L "$canary_machine_terminal" \
        && ! -e "$terminal_machine" && ! -L "$terminal_machine" \
        && ! -e "$rollback_attempt" && ! -L "$rollback_attempt" ]] \
        || fail "before-invariance capture refuses a started, terminal, or rollback lifecycle"
      capture_regional_invariance \
        "$capture_dir" "$machine_id" "$federal_invariance_before" "$public_invariance_before"
    else
      regional_marker_matches_machine_id "$start_attempt" "regional_start_attempt" "$machine_id" \
        || fail "after-invariance capture requires the exact one-start marker"
      regional_marker_matches_machine_id \
        "$canary_machine_terminal" "regional_canary_machine_terminal" "$machine_id" \
        || fail "after-invariance capture requires the exact terminal marker"
      [[ -f "$terminal_machine" && ! -L "$terminal_machine" \
        && ! -e "$rollback_attempt" && ! -L "$rollback_attempt" ]] \
        || fail "after-invariance capture requires terminal evidence before rollback"
      capture_regional_invariance \
        "$capture_dir" "$machine_id" "$federal_invariance_after" "$public_invariance_after"
    fi
    rm -rf -- "$capture_dir"
    trap - EXIT
    return
  elif [[ "$REGIONAL_ACTION" == "create-stopped" || "$REGIONAL_ACTION" == "create-canary-stopped" ]]; then
    [[ -z "$(find "$REGIONAL_LIFECYCLE_DIR" -mindepth 1 -maxdepth 1 ! -name '.capture.*' -print -quit)" ]] \
      || fail "regional lifecycle directory must be empty before a stopped create"
    publish_or_match_regional_input "$REGIONAL_PROFILE_JSON" "$durable_profile"
    publish_or_match_regional_input "$REGIONAL_CANDIDATE_RECEIPT_JSON" "$durable_candidate"
    REGIONAL_PROFILE_JSON="$durable_profile"
    REGIONAL_CANDIDATE_RECEIPT_JSON="$durable_candidate"
    if [[ "$REGIONAL_ACTION" == "create-stopped" ]]; then
      PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m domains.campaign_finance.coverage.lifecycle \
        --regional-canary-artifact-json "$REGIONAL_CANARY_PROMOTION_JSON" \
        --regional-canary-profile-json "$REGIONAL_PROFILE_JSON" \
        --regional-canary-candidate-receipt-json "$REGIONAL_CANDIDATE_RECEIPT_JSON" >/dev/null \
        || fail "complete canary promotion artifact is required before recurring provisioning"
      publish_or_match_regional_input \
        "$REGIONAL_CANARY_PROMOTION_JSON" "$REGIONAL_LIFECYCLE_DIR/admitted_canary_promotion.json"
    fi
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$REGIONAL_SECRET_FILE" <<'PY' \
      || fail "regional secret file must be mode 0600 with exactly POSTGRES_PASSWORD"
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
    raise SystemExit(1)
text = path.read_text(encoding="utf-8")
if re.fullmatch(r"POSTGRES_PASSWORD=[^\r\n]+\n?", text) is None:
    raise SystemExit(1)
PY
    local regional_image_selector
    local expected_registry_manifest_digest
    local registry_manifest_digest
    regional_image_selector="$(select_machine_image "$REGIONAL_IMAGE")" \
      || fail "cannot select the exact qualified regional image tag"
    expected_registry_manifest_digest="${REGIONAL_IMAGE##*@}"
    configure_flyctl_local_docker_host
    flyctl auth docker >"$capture_dir/fly_auth_docker.txt" 2>&1 \
      || fail "regional registry authentication failed at lifecycle handoff"
    registry_manifest_digest="$(resolve_registry_manifest_digest \
      "$regional_image_selector" "$capture_dir/registry_manifest_handoff.txt")" \
      || fail "registry metadata could not resolve the qualified regional image at lifecycle handoff"
    [[ "$registry_manifest_digest" == "$expected_registry_manifest_digest" ]] \
      || fail "qualified regional image digest changed before lifecycle handoff"
    flyctl apps list --json >"$capture_dir/apps_before.json" \
      || fail "regional app inventory preflight failed"
    require_regional_app_absent "$capture_dir/apps_before.json" \
      || fail "regional app already exists or inventory is malformed"
    local config_tmp
    config_tmp="$(mktemp "$capture_dir/.machine-config.XXXXXX.json")" \
      || fail "cannot create regional Machine config"
    chmod 600 "$config_tmp"
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - \
      "$REGIONAL_PROFILE_JSON" "$REGIONAL_CONFIG_KIND" >"$config_tmp" <<'PY'
import json
import sys
from pathlib import Path

profile = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
kind = sys.argv[2]
config = profile["machine"]["config"]
if kind == "canary":
    config = json.loads(json.dumps(config))
    config["init"]["cmd"] = profile["canary"]["command"]
    config.pop("schedule", None)
    plan = profile["execution_plan"]
    authority = plan["authority"]
    config["metadata"] = {
        "civibus_authority": f"{authority['kind']}/{authority['code']}",
        "civibus_execution_plan": plan["plan_id"],
        "civibus_job_key": plan["canary"]["job_keys"][0],
        "civibus_profile": profile["profile_id"],
    }
elif kind != "recurring":
    raise SystemExit("unknown regional Machine config kind")
print(json.dumps(config, sort_keys=True))
PY
    flyctl apps create "$REGIONAL_APP" --org "$REGIONAL_ORGANIZATION" --json --yes \
      >"$capture_dir/app_create.json" \
      || fail "regional app create failed"
    regional_marker "$ownership" "regional_create_ownership" \
      || fail "cannot publish regional app ownership marker"
    flyctl status -a "$REGIONAL_APP" --json >"$capture_dir/app_after_create.json" \
      || fail "regional created-app identity probe failed"
    verify_regional_app "$capture_dir/app_after_create.json" \
      || fail "regional created-app identity validation failed"
    flyctl secrets import -a "$REGIONAL_APP" <"$REGIONAL_SECRET_FILE" \
      >/dev/null 2>&1 || fail "regional secret staging failed"
    flyctl machine create "$regional_image_selector" -a "$REGIONAL_APP" \
      --name "$REGIONAL_MACHINE_NAME" --region "$REGIONAL_REGION" \
      --machine-config "$config_tmp" >"$capture_dir/machine_create.txt" \
      || fail "regional stopped Machine create failed"
    rm -f -- "$config_tmp"
    capture_regional_live "$capture_dir"
    local machine_id
    machine_id="$(regional_single_machine_id "$capture_dir/machines.json")" \
      || fail "regional stopped Machine identity is ambiguous"
    regional_marker "$machine_ownership" "regional_machine_ownership" "$machine_id" \
      || fail "cannot publish regional Machine ownership marker"
    if [[ "$REGIONAL_CONFIG_KIND" == "canary" ]]; then
      regional_marker "$canary_mode" "regional_canary_mode" "$machine_id" \
        || fail "cannot publish regional canary-mode marker"
    fi
    flyctl machine wait "$machine_id" -a "$REGIONAL_APP" \
      --state stopped --wait-timeout 30m >"$capture_dir/machine_wait.txt" \
      || fail "regional stopped Machine did not reach the stopped state"
    capture_regional_live "$capture_dir"
    regional_marker_machine_id "$ownership" "regional_create_ownership" >/dev/null \
      || fail "regional app ownership marker validation failed after stopped-state wait"
    regional_marker_matches_machine_id "$machine_ownership" "regional_machine_ownership" "$machine_id" \
      || fail "regional Machine ownership marker does not match after stopped-state wait"
    if [[ "$REGIONAL_CONFIG_KIND" == "canary" ]]; then
      regional_marker_matches_machine_id "$canary_mode" "regional_canary_mode" "$machine_id" \
        || fail "regional canary-mode marker does not match after stopped-state wait"
    fi
    verify_regional_live "$capture_dir" "stopped" "$machine_id"
    regional_marker "$provision" "regional_stopped_provision" "$machine_id" \
      || fail "cannot publish regional provision receipt"
    printf 'PASS: regional refresh Machine created stopped and verified: %s\n' "$machine_id"
  elif [[ "$REGIONAL_ACTION" == "start-once" || "$REGIONAL_ACTION" == "start-canary-once" ]]; then
    local machine_id
    machine_id="$(regional_marker_machine_id "$provision" "regional_stopped_provision")" \
      || fail "regional provision receipt validation failed"
    [[ -n "$machine_id" ]] || fail "regional provision receipt has no Machine id"
    if [[ "$REGIONAL_ACTION" == "start-canary-once" ]]; then
      regional_marker_matches_machine_id "$canary_mode" "regional_canary_mode" "$machine_id" \
        || fail "regional canary-mode marker does not match exact Machine ownership"
      if [[ -e "$start_attempt" || -L "$start_attempt" ]]; then
        regional_marker_matches_machine_id "$start_attempt" "regional_start_attempt" "$machine_id" \
          || fail "regional start-attempt marker does not match exact Machine ownership"
        regional_marker_matches_machine_id \
          "$canary_machine_terminal" "regional_canary_machine_terminal" "$machine_id" \
          || fail "regional terminal marker is absent or foreign during evidence finalization"
        [[ -f "$terminal_machine" && ! -L "$terminal_machine" ]] \
          || fail "durable regional terminal Machine evidence is absent"
        [[ -n "$REGIONAL_AUTHORITY_LEDGER_PROOF_JSON" \
          && -n "$REGIONAL_REFRESH_POSTCONDITION_JSON" ]] \
          || fail "terminal canary finalization requires ledger, database, and after-invariance owner evidence"
        [[ -f "$federal_invariance_before" && ! -L "$federal_invariance_before" \
          && -f "$public_invariance_before" && ! -L "$public_invariance_before" \
          && -f "$federal_invariance_after" && ! -L "$federal_invariance_after" \
          && -f "$public_invariance_after" && ! -L "$public_invariance_after" ]] \
          || fail "terminal canary finalization requires canonical durable before/after invariance evidence"
        validate_regional_canary_evidence_set \
          "$REGIONAL_AUTHORITY_LEDGER_PROOF_JSON" "$REGIONAL_REFRESH_POSTCONDITION_JSON" "$machine_id"
        local federal_before_identity
        local federal_after_identity
        local public_before_identity
        local public_after_identity
        federal_before_identity="$(validate_regional_invariance_snapshot \
          "$federal_invariance_before" federal before "$machine_id" \
          "$start_attempt" "$terminal_machine")" \
          || fail "durable federal invariance baseline is invalid"
        federal_after_identity="$(validate_regional_invariance_snapshot \
          "$federal_invariance_after" federal after "$machine_id")" \
          || fail "federal invariance postcondition is invalid"
        public_before_identity="$(validate_regional_invariance_snapshot \
          "$public_invariance_before" public before "$machine_id" \
          "$start_attempt" "$terminal_machine")" \
          || fail "durable public invariance baseline is invalid"
        public_after_identity="$(validate_regional_invariance_snapshot \
          "$public_invariance_after" public after "$machine_id")" \
          || fail "public invariance postcondition is invalid"
        [[ "$federal_before_identity" == "$federal_after_identity" \
          && "$public_before_identity" == "$public_after_identity" ]] \
          || fail "canary federal or public invariance identity changed"
        publish_or_match_regional_input \
          "$REGIONAL_AUTHORITY_LEDGER_PROOF_JSON" "$authority_ledger_proof"
        publish_or_match_regional_input \
          "$REGIONAL_REFRESH_POSTCONDITION_JSON" "$database_postcondition"
        printf 'PASS: regional canary terminal evidence finalized without another start: %s\n' "$machine_id"
        rm -rf -- "$capture_dir"
        trap - EXIT
        return
      fi
      [[ -z "$REGIONAL_AUTHORITY_LEDGER_PROOF_JSON" \
        && -z "$REGIONAL_REFRESH_POSTCONDITION_JSON" ]] \
        || fail "regional canary refuses post-start evidence before the one-shot start"
      [[ -f "$federal_invariance_before" && ! -L "$federal_invariance_before" \
        && -f "$public_invariance_before" && ! -L "$public_invariance_before" ]] \
        || fail "regional canary start requires canonical captured before-invariance evidence"
      validate_regional_invariance_snapshot \
        "$federal_invariance_before" federal before "$machine_id" >/dev/null \
        || fail "federal invariance baseline is invalid before canary start"
      validate_regional_invariance_snapshot \
        "$public_invariance_before" public before "$machine_id" >/dev/null \
        || fail "public invariance baseline is invalid before canary start"
    elif [[ -e "$canary_mode" || -L "$canary_mode" ]]; then
      fail "recurring start-once refuses a canary lifecycle"
    fi
    capture_regional_live "$capture_dir"
    verify_regional_live "$capture_dir" "stopped" "$machine_id"
    if [[ "$REGIONAL_ACTION" == "start-canary-once" ]]; then
      regional_marker \
        "$start_attempt" "regional_start_attempt" "$machine_id" \
        "$federal_invariance_before" "$public_invariance_before" \
        || fail "regional start was already attempted or invariance admission failed"
      validate_regional_invariance_snapshot \
        "$federal_invariance_before" federal before "$machine_id" "$start_attempt" >/dev/null \
        || fail "admitted federal invariance baseline is invalid before canary start"
      validate_regional_invariance_snapshot \
        "$public_invariance_before" public before "$machine_id" "$start_attempt" >/dev/null \
        || fail "admitted public invariance baseline is invalid before canary start"
    else
      regional_marker "$start_attempt" "regional_start_attempt" "$machine_id" \
        || fail "regional start was already attempted"
    fi
    flyctl machine start "$machine_id" -a "$REGIONAL_APP" \
      >"$capture_dir/machine_start.txt" || fail "regional Machine start-once failed"
    if [[ "$REGIONAL_ACTION" == "start-canary-once" ]]; then
      flyctl machine wait "$machine_id" -a "$REGIONAL_APP" \
        --state stopped --wait-timeout 30m >"$capture_dir/machine_wait.txt" \
        || fail "regional canary did not reach the terminal stopped state"
      capture_regional_live "$capture_dir"
      verify_regional_live "$capture_dir" "stopped" "$machine_id"
      publish_regional_terminal_machine \
        "$capture_dir/machines.json" "$terminal_machine" "$machine_id" \
        || fail "cannot publish durable regional terminal Machine evidence"
      regional_marker "$canary_machine_terminal" "regional_canary_machine_terminal" "$machine_id" \
        || fail "cannot publish regional canary Machine terminal receipt"
      fail "regional canary Machine is terminal; exact database postcondition is required before rollback completion"
    else
      capture_regional_live "$capture_dir"
      verify_regional_live "$capture_dir" "started" "$machine_id"
      printf 'PASS: regional refresh Machine start-once verified: %s\n' "$machine_id"
    fi
  else
    flyctl apps list --json >"$capture_dir/apps_rollback_inventory.json" \
      || fail "regional rollback app inventory probe failed"
    publish_once_regional_input \
      "$capture_dir/apps_rollback_inventory.json" "$rollback_apps_before"
    local rollback_app_state
    rollback_app_state="$(regional_app_inventory_state "$capture_dir/apps_rollback_inventory.json")" \
      || fail "regional rollback app inventory is malformed or ambiguous"
    if [[ "$rollback_app_state" == "absent" ]]; then
      publish_or_match_regional_input \
        "$capture_dir/apps_rollback_inventory.json" "$rollback_apps_after"
      publish_empty_regional_inventory "$rollback_machines_before" \
        || fail "cannot publish absent rollback Machine inventory before"
      publish_empty_regional_inventory "$rollback_machines_after" \
        || fail "cannot publish absent rollback Machine inventory after"
      publish_empty_regional_inventory "$rollback_volumes_before" \
        || fail "cannot publish absent rollback volume inventory before"
      publish_empty_regional_inventory "$rollback_volumes_after" \
        || fail "cannot publish absent rollback volume inventory after"
      complete_absent_historical_rollback \
        "$ownership" "$machine_ownership" "$provision" "$start_attempt" \
        "$canary_mode" "$canary_machine_terminal" "$rollback_attempt" \
        "$rollback_stopped" "$rollback_complete"
      printf 'PASS: absent regional refresh app historical rollback receipts verified\n'
      rm -rf -- "$capture_dir"
      trap - EXIT
      return
    fi
    regional_marker_machine_id "$ownership" "regional_create_ownership" >/dev/null \
      || fail "regional ownership marker validation failed"
    if [[ -e "$rollback_attempt" || -L "$rollback_attempt" ]]; then
      [[ -e "$rollback_stopped" || -L "$rollback_stopped" ]] \
        || fail "regional rollback was already attempted before a durable stopped boundary"
      regional_marker_machine_id "$rollback_attempt" "regional_rollback_attempt" >/dev/null \
        || fail "regional rollback-attempt marker validation failed"
      regional_marker_machine_id "$rollback_stopped" "regional_rollback_stopped" >/dev/null \
        || fail "regional rollback-stopped marker validation failed"
    else
      regional_marker "$rollback_attempt" "regional_rollback_attempt" \
        || fail "cannot publish regional rollback-attempt marker"
    fi
    local machine_id
    machine_id=""
    if [[ -e "$machine_ownership" || -L "$machine_ownership" ]]; then
      machine_id="$(regional_marker_machine_id "$machine_ownership" "regional_machine_ownership")" \
        || fail "regional Machine ownership marker validation failed"
      [[ -n "$machine_id" ]] || fail "regional Machine ownership marker has no Machine id"
    fi
    if [[ -e "$provision" || -L "$provision" ]]; then
      regional_marker_matches_machine_id "$provision" "regional_stopped_provision" "$machine_id" \
        || fail "regional provision receipt does not match exact Machine ownership"
    fi
    if [[ -e "$rollback_stopped" || -L "$rollback_stopped" ]]; then
      regional_marker_matches_machine_id "$rollback_stopped" "regional_rollback_stopped" "$machine_id" \
        || fail "regional rollback-stopped marker does not match exact Machine ownership"
    fi
    if [[ "$REGIONAL_CONFIG_KIND" == "canary" ]]; then
      regional_marker_matches_machine_id "$canary_mode" "regional_canary_mode" "$machine_id" \
        || fail "regional canary-mode marker does not match exact Machine ownership"
      if [[ -e "$canary_machine_terminal" || -L "$canary_machine_terminal" ]]; then
        regional_marker_matches_machine_id \
          "$canary_machine_terminal" "regional_canary_machine_terminal" "$machine_id" \
          || fail "regional canary Machine terminal receipt does not match exact Machine ownership"
      fi
    fi
    capture_regional_live "$capture_dir"
    verify_regional_app "$capture_dir/app.json" \
      || fail "regional rollback app identity validation failed"
    publish_once_regional_input "$capture_dir/machines.json" "$rollback_machines_before"
    flyctl volumes list -a "$REGIONAL_APP" --json >"$capture_dir/volumes_rollback_inventory.json" \
      || fail "regional rollback volume inventory probe failed"
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$capture_dir/volumes_rollback_inventory.json" <<'PY' \
      || fail "regional app rollback refuses non-empty or malformed volume inventory"
import json
import sys
from pathlib import Path
if json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) != []:
    raise SystemExit(1)
PY
    publish_once_regional_input \
      "$capture_dir/volumes_rollback_inventory.json" "$rollback_volumes_before"
    local state
    state="$(regional_owned_machine_state "$capture_dir/machines.json" "$machine_id")" \
      || fail "regional rollback inventory is ambiguous"
    if [[ -n "$machine_id" ]]; then
      if [[ "$state" == "started" ]]; then
        regional_marker_matches_machine_id "$start_attempt" "regional_start_attempt" "$machine_id" \
          || fail "running regional Machine has no exact start-attempt ownership"
        flyctl machine stop "$machine_id" -a "$REGIONAL_APP" \
          >"$capture_dir/machine_stop.txt" || fail "regional rollback stop-once failed"
        capture_regional_live "$capture_dir"
        verify_regional_live "$capture_dir" "stopped" "$machine_id"
      elif [[ "$state" != "stopped" ]]; then
        fail "regional rollback refuses indeterminate Machine state"
      else
        verify_regional_live "$capture_dir" "stopped" "$machine_id"
      fi
      if [[ "$REGIONAL_CONFIG_KIND" == "canary" && ( -e "$start_attempt" || -L "$start_attempt" ) ]]; then
        if [[ ! -e "$rollback_stopped" && ! -L "$rollback_stopped" ]]; then
          regional_marker "$rollback_stopped" "regional_rollback_stopped" "$machine_id" \
            || fail "cannot publish regional stopped rollback boundary"
        fi
        [[ -n "$REGIONAL_REFRESH_POSTCONDITION_JSON" ]] \
          || {
            if [[ -f "$database_postcondition" && ! -L "$database_postcondition" ]]; then
              REGIONAL_REFRESH_POSTCONDITION_JSON="$database_postcondition"
            else
              fail "exact terminal refresh postcondition is required after stopping the started canary"
            fi
          }
        verify_regional_refresh_postcondition "$REGIONAL_REFRESH_POSTCONDITION_JSON" "$machine_id" false >/dev/null \
          || fail "regional rollback refresh postcondition is not exact, terminal, and zero-state"
      fi
      flyctl machine destroy "$machine_id" -a "$REGIONAL_APP" \
        >"$capture_dir/machine_destroy.txt" || fail "regional nonforce Machine destroy failed"
    fi
    flyctl machines list -a "$REGIONAL_APP" --json >"$capture_dir/machines_after.json" \
      || fail "regional Machine absence probe failed"
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$capture_dir/machines_after.json" <<'PY' \
      || fail "regional Machine still present after destroy"
import json
import sys
from pathlib import Path
if json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) != []:
    raise SystemExit(1)
PY
    publish_or_match_regional_input "$capture_dir/machines_after.json" "$rollback_machines_after"
    flyctl status -a "$REGIONAL_APP" --json >"$capture_dir/app_before_destroy.json" \
      || fail "regional app pre-destroy probe failed"
    verify_regional_app "$capture_dir/app_before_destroy.json" \
      || fail "regional app pre-destroy identity validation failed"
    flyctl apps destroy "$REGIONAL_APP" --yes >"$capture_dir/app_destroy.txt" \
      || fail "regional app rollback failed"
    flyctl apps list --json >"$capture_dir/apps_after.json" \
      || fail "regional app absence probe failed"
    require_regional_app_absent "$capture_dir/apps_after.json" \
      || fail "regional app still present after rollback"
    publish_or_match_regional_input "$capture_dir/apps_after.json" "$rollback_apps_after"
    publish_empty_regional_inventory "$rollback_volumes_after" \
      || fail "cannot publish rollback volume inventory after"
    regional_marker "$rollback_complete" "regional_rollback_complete" "$machine_id" \
      || fail "cannot publish regional rollback completion marker"
    if [[ "$REGIONAL_CONFIG_KIND" == "canary" \
      && -f "$terminal_machine" && -f "$authority_ledger_proof" \
      && -f "$database_postcondition" && -f "$federal_invariance_after" \
      && -f "$public_invariance_after" ]]; then
      if [[ -e "$canary_promotion" || -L "$canary_promotion" ]]; then
        PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m domains.campaign_finance.coverage.lifecycle \
          --regional-canary-artifact-json "$canary_promotion" \
          --regional-canary-profile-json "$durable_profile" \
          --regional-canary-candidate-receipt-json "$durable_candidate" >/dev/null \
          || fail "existing regional canary promotion artifact is invalid"
      else
        PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m domains.campaign_finance.coverage.lifecycle \
          --regional-canary-evidence-directory "$REGIONAL_LIFECYCLE_DIR" \
          --regional-canary-artifact-output-json "$canary_promotion" >/dev/null \
          || fail "cannot build regional canary promotion artifact from the durable lifecycle graph"
      fi
    fi
    printf 'PASS: regional refresh app and Machine rollback verified\n'
  fi
  rm -rf -- "$capture_dir"
  trap - EXIT
}

select_machine_image() {
  local proven_identity="$1"

  "$PYTHON_BIN" - "$APP_NAME" "$proven_identity" <<'PY'
from __future__ import annotations

import re
import sys

app_name = sys.argv[1]
proven_identity = sys.argv[2]
repository = f"registry.fly.io/{app_name}"

# flyctl v0.4.93 appends the resolved digest to the selector it receives.
# Require one already-proven tag@digest identity, then give flyctl only its tag
# so the composed Machine image is that identity rather than digest@digest.
match = re.fullmatch(
    rf"({re.escape(repository)}:[A-Za-z0-9_][A-Za-z0-9_.-]{{0,127}})"
    rf"@(sha256:[0-9a-f]{{64}})",
    proven_identity,
)
if match is None:
    raise SystemExit(1)
print(match.group(1))
PY
}

require_clean_worktree() {
  local status_output
  status_output="$(git status --porcelain --untracked-files=normal)" \
    || fail "cannot inspect git worktree"
  [[ -z "$status_output" ]] || fail "worktree must be clean before building a stamped image"
}

require_recorded_clean_head() {
  local recorded_head_sha="$1"
  local current_head_sha
  require_clean_worktree
  current_head_sha="$(git rev-parse --verify HEAD)" || fail "cannot re-resolve HEAD before build"
  [[ "$current_head_sha" == "$recorded_head_sha" ]] \
    || fail "HEAD changed after deployment evidence capture"
}

capture_refresh_state() {
  local phase="$1"
  local evidence_dir="$2"

  flyctl machines list -a "$APP_NAME" --json >"$evidence_dir/${phase}_machines.json" \
    || fail "$phase machines-list probe failed"
  flyctl machine status "$MACHINE_ID" -a "$APP_NAME" --display-config \
    >"$evidence_dir/${phase}_machine_config.json" \
    || fail "$phase machine display-config probe failed"
  sanitize_machine_config "$evidence_dir/${phase}_machine_config.json" \
    || fail "$phase machine display-config sanitization failed"
  flyctl machine status "$MACHINE_ID" -a "$APP_NAME" \
    >"$evidence_dir/${phase}_event_log.txt" \
    || fail "$phase machine event-log probe failed"
  flyctl volumes list -a "$APP_NAME" --json >"$evidence_dir/${phase}_volumes.json" \
    || fail "$phase volumes-list probe failed"
  curl --fail --silent --show-error --max-time 10 "$VERSION_URL" \
    >"$evidence_dir/${phase}_version.json" \
    || fail "$phase public version probe failed"
}

verify_refresh_state() {
  local phase="$1"
  local evidence_dir="$2"

  bash "$VERIFIER" \
    --machines-json "$evidence_dir/${phase}_machines.json" \
    --machine-config-json "$evidence_dir/${phase}_machine_config.json" \
    --volumes-json "$evidence_dir/${phase}_volumes.json" \
    --version-json "$evidence_dir/${phase}_version.json" \
    >"$evidence_dir/${phase}_verify_refresh_machine.txt"
}

write_expected_refresh_plan() {
  local evidence_dir="$1"

  PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" - "$REPO_ROOT" <<'PY' >"$evidence_dir/expected_refresh_plan.txt"
from __future__ import annotations

import json
import sys

sys.path.insert(0, sys.argv[1])
from core.refresh.job_builders import build_refresh_plan

print(
    json.dumps(
        {
            "refresh_plan_job_keys": sorted(
                job.key for job in build_refresh_plan(scope="federal")
            ),
        },
        sort_keys=True,
    )
)
PY
}

verify_image_refresh_plan() {
  local evidence_dir="$1"

  bash "$VERIFIER" \
    --expected-plan-json "$evidence_dir/expected_refresh_plan.txt" \
    --image-proof-json "$evidence_dir/image_proof.txt" \
    >"$evidence_dir/image_plan_verify_refresh_machine.txt"
}

extract_single_pushed_image() {
  local deploy_output_path="$1"
  "$PYTHON_BIN" - "$deploy_output_path" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
matches = sorted(
    set(
        re.findall(
            r"registry\.fly\.io/civibus-refresh:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}",
            text,
        )
    )
)
if len(matches) != 1:
    print(f"expected exactly one pushed image reference, found {len(matches)}", file=sys.stderr)
    raise SystemExit(1)
print(matches[0])
PY
}

extract_single_pushed_manifest_digest() {
  local deploy_output_path="$1"
  local image_tag="$2"
  "$PYTHON_BIN" - "$deploy_output_path" "$image_tag" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
image_tag = sys.argv[2]
image_tag_name = image_tag.rsplit(":", 1)[1]
matches = sorted(
    set(
        re.findall(
            rf"{re.escape(image_tag)}@(sha256:[0-9a-f]{{64}})",
            text,
        )
        + re.findall(
            rf"(?m)^{re.escape(image_tag_name)}:\s+digest:\s+"
            rf"(sha256:[0-9a-f]{{64}})\s+size:\s+[0-9]+\s*$",
            text,
        )
    )
)
if len(matches) != 1:
    print(f"expected exactly one emitted manifest digest, found {len(matches)}", file=sys.stderr)
    raise SystemExit(1)
print(matches[0])
PY
}

resolve_registry_manifest_digest() {
  local image_tag="$1"
  local metadata_path="$2"

  docker buildx imagetools inspect "$image_tag" >"$metadata_path" 2>&1 \
    || return 1
  "$PYTHON_BIN" - "$metadata_path" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
matches = sorted(set(re.findall(r"(?m)^Digest:\s*(sha256:[0-9a-f]{64})\s*$", text)))
if len(matches) != 1:
    print(f"expected exactly one registry manifest digest, found {len(matches)}", file=sys.stderr)
    raise SystemExit(1)
print(matches[0])
PY
}

resolve_single_digest_ref() {
  local image_tag="$1"
  "$PYTHON_BIN" - "$APP_NAME" "$image_tag" <<'PY'
from __future__ import annotations

import json
import re
import subprocess
import sys

app_name = sys.argv[1]
image_tag = sys.argv[2]
result = subprocess.run(
    ["docker", "image", "inspect", image_tag, "--format", "{{json .RepoDigests}}"],
    capture_output=True,
    text=True,
    check=False,
)
if result.returncode != 0:
    sys.stderr.write(result.stderr)
    raise SystemExit(result.returncode)
try:
    payload = json.loads(result.stdout)
except json.JSONDecodeError:
    print("docker image inspect did not return JSON", file=sys.stderr)
    raise SystemExit(1)
expected_digest = re.compile(
    rf"registry\.fly\.io/{re.escape(app_name)}@sha256:[0-9a-f]{{64}}"
)
matches = sorted(
    digest
    for digest in payload
    if isinstance(digest, str) and expected_digest.fullmatch(digest)
)
if len(matches) != 1:
    print(f"expected exactly one repository digest for {app_name}, found {len(matches)}", file=sys.stderr)
    raise SystemExit(1)
print(matches[0])
PY
}

pull_pushed_image() {
  local image_tag="$1"
  local evidence_dir="$2"
  local retry_delay
  local retry_delays=(0 2 4 8 16 30)

  : >"$evidence_dir/docker_pull.txt"
  : >"$evidence_dir/registry_pull_wait.txt"
  for retry_delay in "${retry_delays[@]}"; do
    if (( retry_delay > 0 )); then
      printf 'waiting %s seconds for pushed image visibility\n' "$retry_delay" \
        >>"$evidence_dir/registry_pull_wait.txt"
      sleep "$retry_delay"
    fi
    if docker pull "$image_tag" >>"$evidence_dir/docker_pull.txt" 2>&1; then
      return 0
    fi
  done
  fail "docker pull failed after bounded registry visibility wait"
}

prove_image_contents() {
  local digest_ref="$1"
  local head_sha="$2"
  local built_at="$3"
  local evidence_dir="$4"

  docker run --rm --platform linux/amd64 \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    -e PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint python "$digest_ref" -c '
import inspect
import json
import sys

from api.health_version import build_version_payload
from core.refresh.job_builders import build_refresh_plan
from core.refresh import runner as refresh_runner
from domains.campaign_finance.ingest.candidate_summary_loader import update_candidate_person_link

expected_sha = sys.argv[1]
expected_built_at = sys.argv[2]
payload = build_version_payload()
if payload != {"git_sha": expected_sha, "built_at": expected_built_at}:
    raise SystemExit(f"build version mismatch: {payload!r}")
source = inspect.getsource(update_candidate_person_link)
if "person_link_is_fillable" not in source:
    raise SystemExit("person_link_is_fillable guard missing")
# The 2026-08-01 image carried the durability guard but NOT the repair-pair
# alarm, because this script was written before the alarm merged. Without this
# assertion the deploy whose entire purpose is to ship the alarm cannot prove it
# did. A guard that cannot fail is not a guard.
for alarm_symbol in ("_record_repair_pair_alarm", "_append_repair_pair_alarms"):
    if not hasattr(refresh_runner, alarm_symbol):
        raise SystemExit(f"partial-run alarm missing: core.refresh.runner.{alarm_symbol}")
if not hasattr(refresh_runner.RefreshJob, "side_effects_repaired_by_job_key"):
    raise SystemExit("partial-run alarm missing: RefreshJob.side_effects_repaired_by_job_key")
print(
    json.dumps(
        {
            "build_version": payload,
            "person_link_is_fillable": True,
            "repair_pair_alarm": True,
            "refresh_plan_job_keys": sorted(
                job.key for job in build_refresh_plan(scope="federal")
            ),
        },
        sort_keys=True,
    )
)
' "$head_sha" "$built_at" >"$evidence_dir/image_proof.txt" \
    || fail "pushed image provenance/guard proof failed"
}

verify_post_image_digest() {
  local machines_json="$1"
  local proven_digest_ref="$2"

  "$PYTHON_BIN" - "$machines_json" "$proven_digest_ref" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

machines_path = Path(sys.argv[1])
proven_digest_ref = sys.argv[2]
expected_repository, expected_digest = proven_digest_ref.rsplit("@", 1)

machines = json.loads(machines_path.read_text(encoding="utf-8"))
# The canonical verifier has already proved there is exactly one expected Machine.
image_ref = machines[0]["image_ref"]
actual_repository = f'{image_ref["registry"]}/{image_ref["repository"]}'
actual_digest = image_ref["digest"]
if actual_repository != expected_repository or actual_digest != expected_digest:
    print(
        "post-update Machine image "
        f"{actual_repository}@{actual_digest} does not match proven digest "
        f"{proven_digest_ref}",
        file=sys.stderr,
    )
    raise SystemExit(1)
print(
    json.dumps(
        {
            "machine_digest": f"{actual_repository}@{actual_digest}",
            "proven_digest": proven_digest_ref,
        },
        sort_keys=True,
    )
)
PY
}

remove_task_local_regional_image() {
  local image_tag="$1"
  local cleanup_log="$2"

  if docker image inspect "$image_tag" >/dev/null 2>&1; then
    docker image rm "$image_tag" >"$cleanup_log" 2>&1 \
      || fail "cannot remove the exact task-created local regional image tag"
  else
    printf 'exact task-created local regional image tag is absent\n' >"$cleanup_log"
  fi
}

regional_build_qualify() {
  local evidence_dir="$REGIONAL_BUILD_EVIDENCE_DIR"
  local receipt_path="$REGIONAL_BUILD_CANDIDATE_RECEIPT_JSON"
  local receipt_parent
  local placeholder_identity
  local candidate_source_sha
  local candidate_tree_sha
  local built_at
  local image_tag
  local emitted_manifest_digest
  local registry_manifest_digest
  local produced_identity

  placeholder_identity="registry.fly.io/civibus-refresh:preflight@sha256:$(printf '0%.0s' {1..64})"

  require_empty_evidence_dir "$evidence_dir"
  evidence_dir="$(cd "$evidence_dir" && pwd -P)"
  require_external_evidence_dir "$evidence_dir"
  receipt_parent="$(cd "$(dirname "$receipt_path")" && pwd -P)" \
    || fail "regional candidate receipt parent must already exist"
  [[ "$receipt_parent" == "$evidence_dir" ]] \
    || fail "regional candidate receipt must be written inside the exact evidence directory"
  receipt_path="$receipt_parent/$(basename "$receipt_path")"
  require_clean_worktree

  candidate_source_sha="$(qualify_image_candidate \
    "$REGIONAL_BUILD_PROFILE_JSON" \
    "$REGIONAL_BUILD_CANDIDATE_MANIFEST_JSON" \
    "$placeholder_identity" \
    "$evidence_dir/.candidate_preflight.json" \
    preflight)" || fail "regional candidate source preflight failed"
  [[ "$(git rev-parse --verify HEAD)" == "$candidate_source_sha" ]] \
    || fail "worktree HEAD does not match the regional candidate manifest"
  candidate_tree_sha="$(git rev-parse "$candidate_source_sha^{tree}")" \
    || fail "cannot resolve regional candidate source tree"
  built_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '%s\n' "$candidate_source_sha" >"$evidence_dir/candidate_source_git_sha.txt"
  printf '%s\n' "$candidate_tree_sha" >"$evidence_dir/candidate_source_tree_git_sha.txt"
  printf '%s\n' "$built_at" >"$evidence_dir/built_at.txt"

  configure_flyctl_local_docker_host
  flyctl auth whoami >"$evidence_dir/fly_auth_whoami.txt" \
    || fail "regional build authentication failed"
  require_recorded_clean_head "$candidate_source_sha"
  flyctl deploy --build-only --push --local-only -c "$FLY_CONFIG" \
    --build-arg "CIVIBUS_GIT_SHA=$candidate_source_sha" \
    --build-arg "CIVIBUS_BUILT_AT=$built_at" \
    >"$evidence_dir/fly_deploy_build_push.txt" 2>&1 \
    || fail "regional image build/push failed"
  image_tag="$(extract_single_pushed_image "$evidence_dir/fly_deploy_build_push.txt")" \
    || fail "regional pushed image reference was missing or ambiguous"
  printf '%s\n' "$image_tag" >"$evidence_dir/pushed_image.txt"
  emitted_manifest_digest="$(extract_single_pushed_manifest_digest \
    "$evidence_dir/fly_deploy_build_push.txt" "$image_tag")" \
    || {
      remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
      fail "regional pushed image manifest digest was missing or ambiguous"
    }
  printf '%s\n' "$emitted_manifest_digest" \
    >"$evidence_dir/emitted_image_manifest_digest.txt"

  if ! flyctl auth docker >"$evidence_dir/fly_auth_docker.txt"; then
    remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
    fail "regional registry authentication failed"
  fi
  registry_manifest_digest="$(resolve_registry_manifest_digest \
    "$image_tag" "$evidence_dir/registry_manifest_inspect.txt")" \
    || {
      remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
      fail "registry metadata could not resolve the regional pushed image"
    }
  printf '%s\n' "$registry_manifest_digest" \
    >"$evidence_dir/registry_manifest_digest.txt"
  if [[ "$registry_manifest_digest" != "$emitted_manifest_digest" ]]; then
    remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
    fail "regional registry manifest digest does not match the emitted digest"
  fi
  produced_identity="$image_tag@$registry_manifest_digest"
  printf '%s\n' "$produced_identity" >"$evidence_dir/produced_image_tagged_digest.txt"

  if ! (require_recorded_clean_head "$candidate_source_sha"); then
    remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
    fail "worktree identity changed after the regional image build"
  fi
  if ! (qualify_image_candidate \
    "$REGIONAL_BUILD_PROFILE_JSON" \
    "$REGIONAL_BUILD_CANDIDATE_MANIFEST_JSON" \
    "$produced_identity" \
    "$receipt_path"); then
    remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
    fail "regional pushed image qualification failed"
  fi
  remove_task_local_regional_image "$image_tag" "$evidence_dir/local_image_rm.txt"
  printf 'PASS: regional refresh image built and qualified as %s\n' "$produced_identity"
}

main() {
  parse_args "$@"

  if [[ "$SELECT_MACHINE_IMAGE" == "true" ]]; then
    select_machine_image "$MACHINE_IMAGE_IDENTITY" \
      || fail "invalid immutable image identity for --select-machine-image"
    return
  fi

  if [[ "$QUALIFY_ONLY" == "true" ]]; then
    qualify_image_candidate \
      "$PROFILE_JSON" \
      "$CANDIDATE_MANIFEST_JSON" \
      "$PRODUCED_IMAGE_TAGGED_DIGEST" \
      "$CANDIDATE_RECEIPT_JSON"
    return
  fi

  if [[ "$REGIONAL_BUILD_QUALIFY" == "true" ]]; then
    regional_build_qualify
    return
  fi

  if [[ -n "$REGIONAL_ACTION" ]]; then
    regional_lifecycle
    return
  fi

  local evidence_dir="$EVIDENCE_DIR"
  local dev_sha="$DEV_SHA"

  require_empty_evidence_dir "$evidence_dir"
  evidence_dir="$(cd "$evidence_dir" && pwd -P)"
  require_external_evidence_dir "$evidence_dir"
  require_clean_worktree

  local checkout_head_sha
  local built_at
  checkout_head_sha="$(git rev-parse --verify HEAD)" || fail "cannot resolve HEAD"
  built_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '%s\n' "$checkout_head_sha" >"$evidence_dir/checkout_head_sha.txt"
  printf '%s\n' "$dev_sha" >"$evidence_dir/dev_sha.txt"
  printf '%s\n' "$built_at" >"$evidence_dir/built_at.txt"
  write_expected_refresh_plan "$evidence_dir" \
    || fail "repository refresh plan proof failed"

  flyctl auth whoami >"$evidence_dir/fly_auth_whoami.txt" \
    || fail "flyctl authentication failed"

  capture_refresh_state "pre" "$evidence_dir"
  verify_refresh_state "pre" "$evidence_dir" \
    || fail "pre-update refresh Machine contract verification failed"

  require_recorded_clean_head "$checkout_head_sha"
  flyctl deploy --build-only --push -c "$FLY_CONFIG" \
    --build-arg "CIVIBUS_GIT_SHA=$dev_sha" \
    --build-arg "CIVIBUS_BUILT_AT=$built_at" \
    >"$evidence_dir/fly_deploy_build_push.txt" 2>&1 \
    || fail "flyctl build/push failed"

  local image_tag
  image_tag="$(extract_single_pushed_image "$evidence_dir/fly_deploy_build_push.txt")" \
    || fail "pushed image reference was missing or ambiguous"
  printf '%s\n' "$image_tag" >"$evidence_dir/pushed_image.txt"

  flyctl auth docker >"$evidence_dir/fly_auth_docker.txt" \
    || fail "Fly registry authentication failed"
  pull_pushed_image "$image_tag" "$evidence_dir"

  local digest_ref
  digest_ref="$(resolve_single_digest_ref "$image_tag")" \
    || fail "pushed image digest was missing or ambiguous"
  printf '%s\n' "$digest_ref" >"$evidence_dir/image_digest.txt"

  local machine_image_selector
  machine_image_selector="$(select_machine_image "$image_tag@${digest_ref##*@}")" \
    || fail "pushed image tag and digest do not form one immutable image identity"

  prove_image_contents "$digest_ref" "$dev_sha" "$built_at" "$evidence_dir"
  verify_image_refresh_plan "$evidence_dir" \
    || fail "pushed image refresh plan verification failed"

  # Drop the local copy before updating the Machine. pull_pushed_image put this
  # tag in the local docker daemon so prove_image_contents could run the image;
  # that proof is complete by this point. If the tag is still present locally,
  # `flyctl machine update --image` logs "Searching for image ... locally...
  # image found" and RE-PUSHES it, minting a second deployment tag and therefore
  # a second manifest digest (identical layers -- every one logs "Layer already
  # exists"). verify_post_image_digest below then compares the first digest to
  # the second and can never match, which made this gate unpassable on both
  # 2026-08-17 deploy attempts (civibus-n8r). With no local copy, flyctl
  # references the already-pushed remote tag and the post-update digest equals
  # the proven digest by construction.
  docker image rm "$image_tag" >"$evidence_dir/local_image_rm.txt" 2>&1 \
    || fail "could not drop the local copy of the pushed image before Machine update"

  # flyctl resolves the tag to its digest; passing an @sha256 reference makes
  # flyctl append that digest again and the Machines API rejects the result.
  flyctl machine update "$MACHINE_ID" -a "$APP_NAME" --image "$machine_image_selector" --yes \
    >"$evidence_dir/machine_update.txt" 2>&1 \
    || fail "image-only Machine update failed"

  capture_refresh_state "post" "$evidence_dir"
  verify_post_image_digest "$evidence_dir/post_machines.json" "$digest_ref" \
    >"$evidence_dir/post_image_digest.txt" \
    || fail "post-update Machine image does not match proven digest"

  printf 'PASS: refresh Machine image updated to %s\n' "$digest_ref"
}

main "$@"
