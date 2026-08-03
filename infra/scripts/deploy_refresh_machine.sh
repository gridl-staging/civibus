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

fail() {
  printf 'FAIL: refresh Machine deploy: %s\n' "$1" >&2
  exit 1
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

parse_args() {
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

extract_single_pushed_image() {
  local deploy_output_path="$1"
  python3 - "$deploy_output_path" <<'PY'
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

resolve_single_digest_ref() {
  local image_tag="$1"
  python3 - "$APP_NAME" "$image_tag" <<'PY'
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

  python3 - "$machines_json" "$proven_digest_ref" <<'PY'
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

main() {
  parse_args "$@"
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

  prove_image_contents "$digest_ref" "$dev_sha" "$built_at" "$evidence_dir"

  # flyctl resolves the tag to its digest; passing an @sha256 reference makes
  # flyctl append that digest again and the Machines API rejects the result.
  flyctl machine update "$MACHINE_ID" -a "$APP_NAME" --image "$image_tag" --skip-start --yes \
    >"$evidence_dir/machine_update.txt" 2>&1 \
    || fail "image-only Machine update failed"

  capture_refresh_state "post" "$evidence_dir"
  verify_refresh_state "post" "$evidence_dir" \
    || fail "post-update refresh Machine contract verification failed"
  verify_post_image_digest "$evidence_dir/post_machines.json" "$digest_ref" \
    >"$evidence_dir/post_image_digest.txt" \
    || fail "post-update Machine image does not match proven digest"

  printf 'PASS: refresh Machine image updated to %s\n' "$digest_ref"
}

main "$@"
