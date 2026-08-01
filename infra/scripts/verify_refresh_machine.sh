#!/usr/bin/env bash
# Verify the live civibus-refresh Machine contract without changing Fly state.

set -euo pipefail

fail_shell() {
  printf 'FAIL: refresh Machine contract: %s\n' "$1" >&2
  exit 1
}

machines_json=""
machine_config_json=""
volumes_json=""
version_json=""

while (( $# > 0 )); do
  if (( $# < 2 )); then
    fail_shell "option $1 requires a path"
  fi
  case "$1" in
    --machines-json)
      machines_json="$2"
      ;;
    --machine-config-json)
      machine_config_json="$2"
      ;;
    --volumes-json)
      volumes_json="$2"
      ;;
    --version-json)
      version_json="$2"
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

if (( fixture_count != 0 && fixture_count != 4 )); then
  fail_shell "fixture mode requires all four JSON paths"
fi

if (( fixture_count == 0 )); then
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

python3 - "$machines_json" "$machine_config_json" "$volumes_json" "$version_json" <<'PY'
from __future__ import annotations

import json
import sys
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


machines_path, config_path, volumes_path, version_path = sys.argv[1:]
validate_machine_list(read_json(machines_path, "machines-list"))
validate_machine_config(read_json(config_path, "machine-config"))
validate_volumes(read_json(volumes_path, "volumes-list"))
validate_version(read_json(version_path, "version"))
print("PASS: refresh Machine contract verified")
PY
