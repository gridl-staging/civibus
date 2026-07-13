#!/usr/bin/env bash
# One-shot row-count progress probe for detached loader jobs.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# Reuse the repository's env owner when an operator explicitly points at an env
# file. Detached jobs normally inherit libpq env from their launch shell.
source "${script_dir}/env_lib.sh"
if [[ -n "${CIVIBUS_ENV_FILE:-}" ]]; then
  load_civibus_env "${CIVIBUS_ENV_FILE}"
fi

fail() {
  echo "probe_load_progress.sh: $*" >&2
  exit 2
}

usage() {
  cat >&2 <<'USAGE'
Usage:
  probe_load_progress.sh <schema.table|table> <port>
USAGE
}

validate_table_identifier() {
  local table="$1"
  if [[ ! "${table}" =~ ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$ ]]; then
    fail "invalid table identifier: ${table}"
  fi
}

validate_port() {
  local port="$1"
  if [[ ! "${port}" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    fail "invalid port: ${port}"
  fi
}

read_previous_total() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    local value
    value="$(<"${path}")"
    if [[ "${value}" =~ ^[0-9]+$ ]]; then
      printf '%s\n' "${value}"
      return
    fi
  fi
  printf '0\n'
}

append_progress_payload() {
  local progress_file="$1"
  local table="$2"
  local port="$3"
  local rows_total="$4"
  local rows_delta="$5"

  PROGRESS_FILE="${progress_file}" \
    PROBE_TABLE="${table}" \
    PROBE_PORT="${port}" \
    ROWS_TOTAL="${rows_total}" \
    ROWS_DELTA="${rows_delta}" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

progress_file = Path(os.environ["PROGRESS_FILE"])
progress_file.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "source": "psql_row_count_probe",
    "rows_total": int(os.environ["ROWS_TOTAL"]),
    "rows_delta": int(os.environ["ROWS_DELTA"]),
    "detail": {
        "table": os.environ["PROBE_TABLE"],
        "port": int(os.environ["PROBE_PORT"]),
    },
}
with progress_file.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    handle.write("\n")
PY
}

if [[ $# -ne 2 ]]; then
  usage
  exit 2
fi

table="$1"
port="$2"
validate_table_identifier "${table}"
validate_port "${port}"

job_dir="${DETACHED_RUNNER_JOB_DIR:-}"
progress_file="${DETACHED_RUNNER_PROGRESS_FILE:-}"
[[ -n "${job_dir}" ]] || fail "DETACHED_RUNNER_JOB_DIR is required"
[[ -n "${progress_file}" ]] || fail "DETACHED_RUNNER_PROGRESS_FILE is required"
mkdir -p "${job_dir}"

sql="SELECT COUNT(*)::bigint FROM ${table};"
rows_total="$(
  PGPORT="${port}" psql \
    -h "${PGHOST:-127.0.0.1}" \
    -p "${port}" \
    -U "${PGUSER:-civibus}" \
    -d "${PGDATABASE:-civibus}" \
    -Atqc "${sql}"
)"
rows_total="${rows_total//$'\n'/}"
rows_total="${rows_total//[[:space:]]/}"
if [[ ! "${rows_total}" =~ ^[0-9]+$ ]]; then
  fail "psql returned a non-numeric row count"
fi

state_name="${table//./_}"
previous_path="${job_dir}/probe_${state_name}.previous_rows_total"
previous_total="$(read_previous_total "${previous_path}")"
rows_delta=$(( rows_total - previous_total ))
if (( rows_delta < 0 )); then
  rows_delta=0
fi

printf '%s\n' "${rows_total}" > "${previous_path}"
append_progress_payload "${progress_file}" "${table}" "${port}" "${rows_total}" "${rows_delta}"
