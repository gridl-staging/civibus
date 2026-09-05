#!/usr/bin/env bash
# Verify the live federal refresh Machine or the frozen local regional profile.

set -euo pipefail

fail_shell() {
  printf 'FAIL: refresh Machine contract: %s\n' "$1" >&2
  exit 1
}

machines_json=""
machine_config_json=""
volumes_json=""
version_json=""
expected_plan_json=""
image_proof_json=""
profile_json=""
candidate_receipt_json=""
profile_only=false
profile_json_seen=false
candidate_receipt_json_seen=false
profile_only_seen=false
regional_app_json=""
regional_machines_json=""
regional_machine_config_json=""
regional_expected_state=""
regional_machine_id=""
regional_config_kind=""
regional_app_json_seen=false
regional_machines_json_seen=false
regional_machine_config_json_seen=false
regional_expected_state_seen=false
regional_machine_id_seen=false
regional_config_kind_seen=false

while (( $# > 0 )); do
  case "$1" in
    --profile-only)
      [[ "$profile_only_seen" == "false" ]] \
        || fail_shell "--profile-only may be supplied only once"
      profile_only_seen=true
      profile_only=true
      shift
      continue
      ;;
    --machines-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      machines_json="$2"
      ;;
    --machine-config-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      machine_config_json="$2"
      ;;
    --volumes-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      volumes_json="$2"
      ;;
    --version-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      version_json="$2"
      ;;
    --expected-plan-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      expected_plan_json="$2"
      ;;
    --image-proof-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      image_proof_json="$2"
      ;;
    --profile-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      [[ "$profile_json_seen" == "false" ]] \
        || fail_shell "--profile-json may be supplied only once"
      profile_json_seen=true
      profile_json="$2"
      ;;
    --candidate-receipt-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      [[ "$candidate_receipt_json_seen" == "false" ]] \
        || fail_shell "--candidate-receipt-json may be supplied only once"
      candidate_receipt_json_seen=true
      candidate_receipt_json="$2"
      ;;
    --regional-app-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      [[ "$regional_app_json_seen" == "false" ]] \
        || fail_shell "--regional-app-json may be supplied only once"
      regional_app_json_seen=true
      regional_app_json="$2"
      ;;
    --regional-machines-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      [[ "$regional_machines_json_seen" == "false" ]] \
        || fail_shell "--regional-machines-json may be supplied only once"
      regional_machines_json_seen=true
      regional_machines_json="$2"
      ;;
    --regional-machine-config-json)
      (( $# >= 2 )) || fail_shell "option $1 requires a path"
      [[ "$regional_machine_config_json_seen" == "false" ]] \
        || fail_shell "--regional-machine-config-json may be supplied only once"
      regional_machine_config_json_seen=true
      regional_machine_config_json="$2"
      ;;
    --regional-expected-state)
      (( $# >= 2 )) || fail_shell "option $1 requires a value"
      [[ "$regional_expected_state_seen" == "false" ]] \
        || fail_shell "--regional-expected-state may be supplied only once"
      regional_expected_state_seen=true
      regional_expected_state="$2"
      ;;
    --regional-machine-id)
      (( $# >= 2 )) || fail_shell "option $1 requires a value"
      [[ "$regional_machine_id_seen" == "false" ]] \
        || fail_shell "--regional-machine-id may be supplied only once"
      regional_machine_id_seen=true
      regional_machine_id="$2"
      ;;
    --regional-config-kind)
      (( $# >= 2 )) || fail_shell "option $1 requires a value"
      [[ "$regional_config_kind_seen" == "false" ]] \
        || fail_shell "--regional-config-kind may be supplied only once"
      regional_config_kind_seen=true
      regional_config_kind="$2"
      ;;
    *)
      fail_shell "unknown option: $1"
      ;;
  esac
  shift 2
done

fixture_count=0
for fixture_path in "$machines_json" "$machine_config_json" "$volumes_json" "$version_json"; do
  if [[ -n "$fixture_path" ]]; then
    fixture_count=$((fixture_count + 1))
  fi
done

plan_proof_count=0
for plan_proof_path in "$expected_plan_json" "$image_proof_json"; do
  if [[ -n "$plan_proof_path" ]]; then
    plan_proof_count=$((plan_proof_count + 1))
  fi
done

if (( fixture_count != 0 && fixture_count != 4 )); then
  fail_shell "fixture mode requires all four JSON paths"
fi

if (( plan_proof_count != 0 && plan_proof_count != 2 )); then
  fail_shell "plan-proof mode requires both JSON paths"
fi

if [[ "$profile_only" == "true" && -z "$profile_json" ]]; then
  fail_shell "--profile-only requires --profile-json"
fi

if [[ -n "$profile_json" ]] && (( fixture_count != 0 || plan_proof_count != 0 )); then
  fail_shell "frozen profile mode does not accept Machine fixtures or plan proof"
fi

if [[ "$candidate_receipt_json_seen" == "true" && -z "$candidate_receipt_json" ]]; then
  fail_shell "--candidate-receipt-json requires a non-empty path"
fi

if [[ "$candidate_receipt_json_seen" == "true" && -z "$profile_json" ]]; then
  fail_shell "candidate receipt mode requires --profile-json"
fi

regional_live_count=0
for regional_path in "$regional_app_json" "$regional_machines_json" "$regional_machine_config_json" "$regional_expected_state" "$regional_machine_id" "$regional_config_kind"; do
  [[ -z "$regional_path" ]] || regional_live_count=$((regional_live_count + 1))
done
if (( regional_live_count != 0 && regional_live_count != 6 )); then
  fail_shell "regional live mode requires app, machines, config, expected-state, Machine-id, and config-kind inputs"
fi
if (( regional_live_count == 6 )) && [[ -z "$candidate_receipt_json" || "$profile_only" == "true" ]]; then
  fail_shell "regional live mode requires profile plus candidate receipt without --profile-only"
fi

if [[ -n "$profile_json" && "$candidate_receipt_json_seen" == "false" && "$profile_only" != "true" ]]; then
  fail_shell "regional profile is unprovisioned; live verification is blocked"
fi

if [[ -z "$profile_json" ]] && (( fixture_count == 0 && plan_proof_count == 0 )); then
  probe_dir="$(mktemp -d)" || fail_shell "cannot create probe directory"
  trap 'rm -rf -- "$probe_dir"' EXIT
  machines_json="$probe_dir/machines.json"
  machine_config_json="$probe_dir/machine_config.json"
  volumes_json="$probe_dir/volumes.json"
  version_json="$probe_dir/version.json"

  flyctl auth whoami >/dev/null || fail_shell "flyctl authentication failed"
  flyctl machines list -a civibus-refresh --json >"$machines_json" \
    || fail_shell "machines-list probe failed"
  flyctl machine status 859e0da479e678 -a civibus-refresh --display-config \
    >"$machine_config_json" || fail_shell "machine display-config probe failed"
  flyctl volumes list -a civibus-refresh --json >"$volumes_json" \
    || fail_shell "volumes-list probe failed"
  curl --fail --silent --show-error --max-time 10 https://civibus.shareborough.com/api/health/version >"$version_json" \
    || fail_shell "version probe failed"
fi

python3 - \
  "$machines_json" \
  "$machine_config_json" \
  "$volumes_json" \
  "$version_json" \
  "$expected_plan_json" \
  "$image_proof_json" \
  "$profile_json" \
  "$candidate_receipt_json" \
  "$profile_only" \
  "$regional_app_json" \
  "$regional_machines_json" \
  "$regional_machine_config_json" \
  "$regional_expected_state" \
  "$regional_machine_id" \
  "$regional_config_kind" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, NoReturn


MACHINE_ID = "859e0da479e678"
MACHINE_NAME = "lingering-butterfly-8636"
VOLUME_ID = "vol_42kzg23gem178304"
EXPECTED_COMMAND = ["python", "-m", "core.refresh.runner", "--scope", "federal"]
EXPECTED_ENV = {
    "CIVIBUS_ENV": "production",
    "POSTGRES_HOST": "civibus-db.internal",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "civibus",
    "POSTGRES_DB": "civibus",
    "CIVIBUS_REFRESH_DATA_DIR": "/data",
    "CIVIBUS_STARTUP_CANARY": "skip",
}
REGIONAL_WA_PROFILE_SHA256 = "2f7fdbe1e97473479617212fa2cc6a22f6f4482011856f0583d9f757c2c4760f"
REGIONAL_CANONICAL_RECEIPT_GIT_SHA = "f198d2d2aab360b62d55d6b61f2853f4a4bc10ac"
REGIONAL_CANONICAL_SOURCE_GIT_SHA = "3df2e919388edb84b9f4f6cc33c496a8a8462937"
REGIONAL_CANONICAL_TREE_GIT_SHA = "61c293365ede61e0a43d42087c0ffdd70251631f"
REGIONAL_ENV = {
    "CIVIBUS_ENV": "production",
    "CIVIBUS_REFRESH_DATA_DIR": "/tmp/civibus-refresh-data",
    "CIVIBUS_STARTUP_CANARY": "skip",
    "POSTGRES_DB": "civibus",
    "POSTGRES_HOST": "civibus-db.internal",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "civibus",
}


def fail(message: str) -> NoReturn:
    print(f"FAIL: refresh Machine contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(path_text: str, label: str) -> Any:
    path = Path(path_text)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        fail(f"cannot read {label} JSON: {path}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fail(f"{label} JSON is not valid JSON")


def read_profile_json(path_text: str) -> Any:
    path = Path(path_text)
    if not path.is_file() or path.is_symlink():
        fail("profile JSON must be a regular non-symlink file")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        fail(f"cannot read profile JSON: {path}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail("profile JSON contains a duplicate object key")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _constant: fail("profile JSON contains a non-finite number"),
        )
    except json.JSONDecodeError:
        fail("profile JSON is not valid JSON")


def read_candidate_receipt_json(path_text: str) -> Any:
    path = Path(path_text)
    if not path.is_file() or path.is_symlink():
        fail("candidate receipt JSON must be a regular non-symlink file")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        fail(f"cannot read candidate receipt JSON: {path}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail("candidate receipt JSON contains a duplicate object key")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _constant: fail(
                "candidate receipt JSON contains a non-finite number"
            ),
        )
    except json.JSONDecodeError:
        fail("candidate receipt JSON is not valid JSON")


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{label} must be a JSON array")
    return value


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        fail(f"{label} expected {expected!r}, found {actual!r}")


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        fail(f"{label} must be a string")
    return value


def require_profile_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        fail(f"regional profile {label} mismatch")


def canonical_sha256(value: Any, label: str) -> str:
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        fail(f"regional profile {label} is not canonical JSON")
    return hashlib.sha256(canonical).hexdigest()


def require_tagged_digest(value: Any, label: str) -> re.Match[str]:
    if not isinstance(value, str):
        fail(f"{label} must be an immutable tag@sha256 identity")
    match = re.fullmatch(
        r"(?P<repository>[a-z0-9][a-z0-9./_-]*):"
        r"(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})"
        r"@sha256:[0-9a-f]{64}",
        value,
    )
    if match is None:
        fail(f"{label} must be an immutable tag@sha256 identity")
    return match


def validate_regional_profile(payload: Any) -> dict[str, Any]:
    profile = require_mapping(payload, "regional profile")
    require_profile_equal(profile.get("schema_version"), 3, "schema_version")
    require_profile_equal(profile.get("provisioning_state"), "unprovisioned", "provisioning_state")
    app = require_string(profile.get("app"), "regional profile app")
    organization = require_string(profile.get("organization"), "regional profile organization")
    organization_id = require_string(profile.get("organization_id"), "regional profile organization id")
    profile_id = require_string(profile.get("profile_id"), "regional profile id")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", app) is None:
        fail("regional profile app identity is invalid")
    if not organization or not organization_id or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", profile_id) is None:
        fail("regional profile organization or profile identity is invalid")
    canonical_source = require_mapping(profile.get("canonical_source"), "regional profile canonical source")
    require_profile_equal(
        canonical_source,
        {
            "receipt_git_sha": REGIONAL_CANONICAL_RECEIPT_GIT_SHA,
            "source_git_sha": REGIONAL_CANONICAL_SOURCE_GIT_SHA,
            "tree_git_sha": REGIONAL_CANONICAL_TREE_GIT_SHA,
        },
        "canonical source",
    )

    plan = require_mapping(profile.get("execution_plan"), "regional profile execution plan")
    require_profile_equal(plan.get("schema_version"), 1, "execution plan schema_version")
    require_profile_equal(plan.get("plan_id"), profile_id, "execution plan id")
    contract_path = require_string(plan.get("contract_path"), "regional execution plan contract path")
    if (
        not contract_path.endswith(".json")
        or contract_path.startswith("/")
        or ".." in Path(contract_path).parts
    ):
        fail("regional execution plan contract path is unsafe")
    authority = require_mapping(plan.get("authority"), "regional execution plan authority")
    require_profile_equal(set(authority), {"kind", "code"}, "execution plan authority key set")
    authority_kind = require_string(authority.get("kind"), "regional execution plan authority kind")
    authority_code = require_string(authority.get("code"), "regional execution plan authority code")
    if authority_kind not in {
        "federal", "state", "county", "municipality", "school_district", "special_district", "named_other"
    } or re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", authority_code) is None:
        fail("regional execution plan authority identity is invalid")
    authority_scope = f"{authority_kind}/{authority_code}"

    scheduled = require_mapping(plan.get("scheduled"), "regional scheduled execution plan")
    canary_plan = require_mapping(plan.get("canary"), "regional canary execution plan")
    for mode_name, mode_payload in (("scheduled", scheduled), ("canary", canary_plan)):
        require_profile_equal(
            set(mode_payload),
            {"execution_origin", "job_keys", "schedule", "stop_on_failure"},
            f"{mode_name} execution plan key set",
        )
        job_keys = require_list(mode_payload.get("job_keys"), f"regional {mode_name} job keys")
        if (
            not job_keys
            or len(job_keys) != len(set(job_keys))
            or any(not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key) is None for key in job_keys)
        ):
            fail(f"regional {mode_name} job keys are empty, duplicated, or invalid")
    require_profile_equal(scheduled.get("execution_origin"), "scheduled", "scheduled execution origin")
    if scheduled.get("schedule") not in {"daily", "weekly"}:
        fail("regional scheduled execution plan cadence is invalid")
    require_profile_equal(canary_plan.get("execution_origin"), "operator_attended", "canary execution origin")
    require_profile_equal(canary_plan.get("schedule"), None, "canary schedule")
    require_profile_equal(canary_plan.get("stop_on_failure"), True, "canary stop_on_failure")
    canary_job_keys = canary_plan["job_keys"]
    if len(canary_job_keys) != 1 or canary_job_keys[0] not in scheduled["job_keys"]:
        fail("regional canary must be a singleton owned by the scheduled execution plan")
    require_profile_equal(
        plan.get("concurrency"),
        {
            "cross_host_lock": "exact_authority_and_job_key_postgres_advisory_lock",
            "max_parallel_jobs": 1,
            "same_host_lock": "exact_authority_and_job_key_flock",
        },
        "execution plan concurrency",
    )
    require_profile_equal(
        plan.get("cadence_clock"),
        {
            "force_allowed": False,
            "job_due": "refresh_history_or_data_source_per_job",
            "scheduler": "machine_schedule",
        },
        "execution plan cadence clock",
    )
    scheduled_command = [
        "python", "-m", "core.refresh.runner",
        "--authority-plan-json", contract_path,
        "--execution-mode", "scheduled",
        "--execution-origin", scheduled["execution_origin"],
    ]
    canary_command = [
        "python", "-m", "core.refresh.runner",
        "--authority-plan-json", contract_path,
        "--execution-mode", "canary",
        "--execution-origin", canary_plan["execution_origin"],
    ]
    canary = require_mapping(profile.get("canary"), "regional profile canary")
    require_profile_equal(
        canary,
        {
            "command": canary_command,
            "execution_origin": canary_plan["execution_origin"],
            "job_key": canary_job_keys[0],
            "schedule": None,
            "stop_on_failure": True,
        },
        "canary",
    )

    image = require_mapping(profile.get("image"), "regional profile image")
    require_profile_equal(image.get("tagged_digest"), None, "unprovisioned image identity")
    require_profile_equal(image.get("repository"), "registry.fly.io/civibus-refresh", "image repository")
    require_profile_equal(
        image.get("qualification"),
        "candidate_receipt_must_bind_exact_tagged_digest_to_descendant_source_git_sha_and_tree",
        "image qualification",
    )

    machine = require_mapping(profile.get("machine"), "regional profile machine")
    require_profile_equal(machine.get("id"), None, "unprovisioned Machine identity")
    machine_name = require_string(machine.get("name"), "regional profile Machine name")
    machine_region = require_string(machine.get("region"), "regional profile Machine region")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", machine_name) is None or not machine_region:
        fail("regional profile Machine identity is invalid")
    require_profile_equal(machine.get("default_state"), "stopped", "Machine default state")
    config = require_mapping(machine.get("config"), "regional profile machine config")
    require_profile_equal(
        machine.get("config_sha256"),
        canonical_sha256(config, "Machine config"),
        "Machine config digest",
    )
    require_profile_equal(config.get("init"), {"cmd": scheduled_command}, "Machine command")
    require_profile_equal(config.get("env"), REGIONAL_ENV, "Machine environment")
    require_profile_equal(config.get("files"), [], "Machine files")
    require_profile_equal(config.get("mounts"), [], "Machine mounts")
    require_profile_equal(config.get("services"), [], "Machine services")
    require_profile_equal(config.get("schedule"), scheduled.get("schedule"), "Machine schedule")
    require_profile_equal(config.get("restart"), {"policy": "no"}, "Machine restart")
    require_profile_equal(config.get("auto_destroy"), False, "Machine auto_destroy")
    require_profile_equal(
        config.get("guest"),
        {"cpu_kind": "shared", "cpus": 1, "memory_mb": 1024},
        "Machine guest",
    )
    require_profile_equal(
        config.get("metadata"),
        {
            "civibus_authority": authority_scope,
            "civibus_execution_plan": profile_id,
            "civibus_profile": profile_id,
        },
        "Machine metadata",
    )
    require_profile_equal(
        profile.get("resource_ownership"),
        {"app": app, "authority": authority_scope, "machine": machine_name, "plan": profile_id},
        "resource ownership",
    )
    secret_delivery = require_mapping(profile.get("secret_delivery"), "regional profile secret delivery")
    require_profile_equal(
        secret_delivery,
        {
            "machine_config_env_names": [],
            "machine_config_files": [],
            "names": ["POSTGRES_PASSWORD"],
            "provider": "fly_app_secret",
            "values_in_profile": False,
        },
        "secret delivery",
    )
    cleanup = require_mapping(profile.get("cleanup"), "regional profile cleanup")
    require_profile_equal(
        cleanup,
        {
            "app_rollback": "destroy_only_task_created_app_after_exact_machine_absence_and_empty_inventory",
            "normal_terminal": "retain_exact_machine_stopped",
            "prestart_failure": "nonforce_destroy_only_exact_owned_stopped_machine_and_verify_absent",
            "indeterminate": "handoff_without_mutation_or_retry",
            "started_rollback": "stop_once_exact_owned_machine_then_nonforce_destroy_and_verify_absent",
            "volume_cleanup": "not_applicable_no_volume",
        },
        "cleanup",
    )
    # Preserve the checked-in Washington control byte-for-byte while allowing a
    # separately named authority profile to reuse this generic validator.  A
    # second Washington owner is not a distinct authority and must fail closed.
    if authority_scope == "state/WA":
        require_profile_equal(app, "civibus-regional-refresh", "Washington app")
        require_profile_equal(profile_id, "regional-wa-scheduled", "Washington profile id")
        require_profile_equal(machine_name, "regional-wa-scheduled", "Washington Machine name")
        require_profile_equal(
            contract_path,
            "infra/fly/regional_refresh_machine_profile.json",
            "Washington execution plan contract path",
        )
        require_profile_equal(
            canonical_sha256(profile, "identity"),
            REGIONAL_WA_PROFILE_SHA256,
            "Washington identity digest",
        )
    return profile


def validate_candidate_receipt(payload: Any, profile: dict[str, Any]) -> None:
    receipt = require_mapping(payload, "candidate receipt")
    expected_keys = {
        "canonical_receipt_git_sha",
        "canonical_source_git_sha",
        "canonical_tree_git_sha",
        "image_proof",
        "machine_config_sha256",
        "produced_image_tagged_digest",
        "profile_sha256",
        "qualification_kind",
        "schema_version",
        "source_git_sha",
        "source_tree_git_sha",
    }
    actual_keys = set(receipt)
    if actual_keys != expected_keys:
        fail(
            "candidate receipt key set mismatch; "
            f"missing: {sorted(expected_keys - actual_keys)!r}; "
            f"extra: {sorted(actual_keys - expected_keys)!r}"
        )
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 2:
        fail("candidate receipt schema_version mismatch")
    require_equal(
        receipt.get("qualification_kind"),
        "authority_refresh_image_candidate",
        "candidate receipt qualification_kind",
    )

    image = require_mapping(profile.get("image"), "regional profile image")
    produced_image = receipt.get("produced_image_tagged_digest")
    produced_match = require_tagged_digest(
        produced_image,
        "candidate receipt produced image",
    )
    require_equal(
        produced_match.group("repository"),
        image.get("repository"),
        "candidate receipt produced image repository",
    )
    canonical_source = require_mapping(profile.get("canonical_source"), "regional profile canonical source")
    require_equal(
        receipt.get("canonical_receipt_git_sha"),
        canonical_source.get("receipt_git_sha"),
        "candidate receipt canonical receipt",
    )
    require_equal(
        receipt.get("canonical_source_git_sha"),
        canonical_source.get("source_git_sha"),
        "candidate receipt canonical source",
    )
    require_equal(
        receipt.get("canonical_tree_git_sha"),
        canonical_source.get("tree_git_sha"),
        "candidate receipt canonical tree",
    )
    for key, label, length in (
        ("source_git_sha", "candidate receipt source", 40),
        ("source_tree_git_sha", "candidate receipt source tree", 40),
    ):
        value = receipt.get(key)
        if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
            fail(f"{label} must be a {length}-character lowercase hexadecimal identity")
    proof = require_mapping(receipt.get("image_proof"), "candidate receipt image proof")
    version = require_mapping(proof.get("build_version"), "candidate receipt build version")
    require_equal(version.get("git_sha"), receipt.get("source_git_sha"), "candidate receipt image source")
    if not require_string(version.get("built_at"), "candidate receipt image built_at"):
        fail("candidate receipt image built_at must not be empty")
    plan = require_mapping(profile.get("execution_plan"), "regional profile execution plan")
    require_equal(
        proof,
        {
            "authority": plan["authority"],
            "build_version": version,
            "cadence_clock": plan["cadence_clock"],
            "canary": plan["canary"],
            "concurrency": plan["concurrency"],
            "execution_plan_id": plan["plan_id"],
            "execution_plan_sha256": canonical_sha256(plan, "execution plan"),
            "scheduled": plan["scheduled"],
        },
        "candidate receipt authority execution plan proof",
    )
    machine = require_mapping(profile.get("machine"), "regional profile machine")
    require_equal(
        receipt.get("machine_config_sha256"),
        machine.get("config_sha256"),
        "candidate receipt Machine config digest",
    )
    require_equal(
        receipt.get("profile_sha256"),
        canonical_sha256(profile, "identity"),
        "candidate receipt profile digest",
    )


def validate_machine_list(payload: Any) -> None:
    machines = require_list(payload, "machines-list payload")
    if len(machines) != 1:
        fail(f"expected exactly one Machine, found {len(machines)}")

    machine = require_mapping(machines[0], "Machine row")
    require_equal(machine.get("id"), MACHINE_ID, "Machine id")
    require_equal(machine.get("name"), MACHINE_NAME, "Machine name")
    require_equal(machine.get("region"), "sjc", "Machine region")
    require_equal(machine.get("state"), "stopped", "Machine state")

    config = require_mapping(machine.get("config"), "machines-list config")
    require_equal(config.get("schedule"), "weekly", "Machine schedule")
    guest = require_mapping(config.get("guest"), "machines-list guest")
    require_equal(guest.get("cpu_kind"), "shared", "VM CPU kind")
    require_equal(guest.get("cpus"), 1, "VM CPU count")
    require_equal(guest.get("memory_mb"), 1024, "VM memory")


def validate_machine_config(payload: Any) -> None:
    config = require_mapping(payload, "display-config payload")
    init = require_mapping(config.get("init"), "display-config init")
    require_equal(init.get("cmd"), EXPECTED_COMMAND, "Machine command")

    restart = require_mapping(config.get("restart"), "display-config restart")
    require_equal(restart.get("policy"), "no", "Machine restart policy")

    environment = require_mapping(config.get("env"), "display-config env")
    for env_name, expected_value in EXPECTED_ENV.items():
        require_equal(
            environment.get(env_name),
            expected_value,
            f"Machine environment {env_name}",
        )

    mounts = require_list(config.get("mounts"), "display-config mounts")
    has_data_mount = any(
        isinstance(mount, dict)
        and mount.get("path") == "/data"
        and mount.get("volume") == VOLUME_ID
        for mount in mounts
    )
    if not has_data_mount:
        fail(f"missing /data mount for volume {VOLUME_ID}")


def validate_volumes(payload: Any) -> None:
    volumes = require_list(payload, "volumes-list payload")
    has_attachment = any(
        isinstance(volume, dict)
        and volume.get("id") == VOLUME_ID
        and volume.get("attached_machine_id") == MACHINE_ID
        for volume in volumes
    )
    if not has_attachment:
        fail(f"missing volume evidence for {VOLUME_ID} attached to {MACHINE_ID}")


def validate_version(payload: Any) -> None:
    version = require_mapping(payload, "version payload")
    require_string(version.get("git_sha"), "version git_sha")
    require_string(version.get("built_at"), "version built_at")


def read_refresh_plan_job_keys(path_text: str, label: str) -> list[str]:
    payload = require_mapping(read_json(path_text, label), label)
    keys = require_list(payload.get("refresh_plan_job_keys"), f"{label} refresh_plan_job_keys")
    invalid_keys = [key for key in keys if not isinstance(key, str)]
    if invalid_keys:
        fail(f"{label} refresh_plan_job_keys must contain only strings")
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicate_keys:
        fail(f"{label} refresh_plan_job_keys contains duplicate keys: {duplicate_keys!r}")
    return sorted(keys)


def validate_refresh_plan_proof(expected_plan_path: str, image_proof_path: str) -> None:
    expected_keys = read_refresh_plan_job_keys(expected_plan_path, "expected-plan")
    image_keys = read_refresh_plan_job_keys(image_proof_path, "image-proof")
    missing_from_image = sorted(set(expected_keys) - set(image_keys))
    extra_in_image = sorted(set(image_keys) - set(expected_keys))
    if missing_from_image or extra_in_image:
        fail(
            "refresh plan job key mismatch; "
            f"missing from image: {missing_from_image!r}; "
            f"extra in image: {extra_in_image!r}"
        )


def validate_regional_live(
    app_payload: Any,
    machines_payload: Any,
    config_payload: Any,
    expected_state: str,
    expected_machine_id: str,
    config_kind: str,
    profile: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if expected_state not in {"stopped", "started"}:
        fail("regional expected state must be stopped or started")
    if re.fullmatch(r"[0-9a-f]+", expected_machine_id) is None:
        fail("regional Machine id must be lowercase hexadecimal")
    app = require_mapping(app_payload, "regional app payload")
    require_equal(app.get("Name", app.get("name")), profile["app"], "regional app name")
    require_equal(app.get("ID"), profile["app"], "regional app id")
    organization = require_mapping(app.get("Organization"), "regional app organization")
    require_equal(organization.get("Slug"), profile["organization"], "regional app organization")
    require_equal(organization.get("ID"), profile["organization_id"], "regional app organization id")
    machines = require_list(machines_payload, "regional machines payload")
    require_equal(len(machines), 1, "regional Machine inventory size")
    machine = require_mapping(machines[0], "regional Machine row")
    require_equal(machine.get("id"), expected_machine_id, "regional Machine id")
    require_equal(machine.get("name"), profile["machine"]["name"], "regional Machine name")
    require_equal(machine.get("region"), profile["machine"]["region"], "regional Machine region")
    require_equal(machine.get("state"), expected_state, "regional Machine state")
    if config_kind not in {"recurring", "canary"}:
        fail("regional config kind must be recurring or canary")
    expected_config = dict(profile["machine"]["config"])
    if config_kind == "canary":
        expected_config = json.loads(json.dumps(expected_config))
        expected_config["init"]["cmd"] = profile["canary"]["command"]
        expected_config.pop("schedule", None)
        plan = profile["execution_plan"]
        authority = plan["authority"]
        expected_config["metadata"] = {
            "civibus_authority": f"{authority['kind']}/{authority['code']}",
            "civibus_execution_plan": plan["plan_id"],
            "civibus_job_key": plan["canary"]["job_keys"][0],
            "civibus_profile": profile["profile_id"],
        }
    config = require_mapping(config_payload, "regional Machine config")
    require_equal(config.get("image"), receipt["produced_image_tagged_digest"], "regional Machine image")
    config_without_image = dict(config)
    del config_without_image["image"]
    require_equal(config_without_image, expected_config, "regional Machine config")


(
    machines_path,
    config_path,
    volumes_path,
    version_path,
    expected_plan_path,
    image_proof_path,
    profile_path,
    candidate_receipt_path,
    profile_only_text,
    regional_app_path,
    regional_machines_path,
    regional_config_path,
    regional_expected_state,
    regional_machine_id,
    regional_config_kind,
) = sys.argv[1:]
if profile_path:
    profile = validate_regional_profile(read_profile_json(profile_path))
    if candidate_receipt_path:
        receipt = read_candidate_receipt_json(candidate_receipt_path)
        validate_candidate_receipt(receipt, profile)
        if all((regional_app_path, regional_machines_path, regional_config_path)):
            validate_regional_live(
                read_json(regional_app_path, "regional-app"),
                read_json(regional_machines_path, "regional-machines"),
                read_json(regional_config_path, "regional-machine-config"),
                regional_expected_state,
                regional_machine_id,
                regional_config_kind,
                profile,
                receipt,
            )
            print("PASS: regional refresh Machine live contract verified")
            raise SystemExit(0)
        print("PASS: regional refresh image candidate receipt verified")
        raise SystemExit(0)
    print("PASS: regional refresh Machine profile frozen (unprovisioned; not execution-ready)")
    raise SystemExit(0)
if all((machines_path, config_path, volumes_path, version_path)):
    validate_machine_list(read_json(machines_path, "machines-list"))
    validate_machine_config(read_json(config_path, "machine-config"))
    validate_volumes(read_json(volumes_path, "volumes-list"))
    validate_version(read_json(version_path, "version"))
if expected_plan_path and image_proof_path:
    validate_refresh_plan_proof(expected_plan_path, image_proof_path)
print("PASS: refresh Machine contract verified")
PY
