#!/usr/bin/env bash
# Canonical foreground wrapper for long-running ingest dispatch on the Hetzner VM.
#
# Owner: Stage 2 of docs/howto/operations/long_running_ingest_discipline.md.
# Responsibility: launch the wrapped command in the foreground, capture stdout/
# stderr to dispatch.log, write dispatch.json before launch and closeout.json
# exactly once at terminal completion. Does not detach, daemonize, or alter
# the refresh runner or job-selection ownership.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

usage() {
  cat >&2 <<'USAGE'
Usage: long_running_dispatch.sh \
  --artifact-id <id> \
  --dispatch-id <id> \
  --probe-sql <sql> \
  -- <wrapped-command> [args...]

Required:
  --artifact-id   Evidence directory key under docs/reference/research/artifacts/.
  --dispatch-id   Unique dispatch slug, regex ^[a-z0-9][a-z0-9_-]{7,63}$.
  --probe-sql     Non-empty monitor probe SQL recorded in dispatch.json.
  --              Separator before the wrapped command and its arguments.
USAGE
}

fail() {
  echo "long_running_dispatch.sh: $*" >&2
  usage
  exit 2
}

artifact_id=""
dispatch_id=""
probe_sql=""
wrapped_cmd=()
saw_separator=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-id)
      [[ $# -ge 2 ]] || fail "--artifact-id requires a value"
      artifact_id="$2"
      shift 2
      ;;
    --dispatch-id)
      [[ $# -ge 2 ]] || fail "--dispatch-id requires a value"
      dispatch_id="$2"
      shift 2
      ;;
    --probe-sql)
      [[ $# -ge 2 ]] || fail "--probe-sql requires a value"
      probe_sql="$2"
      shift 2
      ;;
    --)
      shift
      saw_separator=1
      wrapped_cmd=("$@")
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ -n "${artifact_id}" ]] || fail "--artifact-id is required and must be non-empty"
[[ -n "${dispatch_id}" ]] || fail "--dispatch-id is required and must be non-empty"
[[ -n "${probe_sql}" ]] || fail "--probe-sql is required and must be non-empty"
(( saw_separator == 1 )) || fail "missing '--' separator before wrapped command"
(( ${#wrapped_cmd[@]} > 0 )) || fail "wrapped command is required after '--'"

# Frozen contract regex from docs/howto/operations/long_running_ingest_discipline.md.
if [[ ! "${dispatch_id}" =~ ^[a-z0-9][a-z0-9_-]{7,63}$ ]]; then
  fail "invalid --dispatch-id '${dispatch_id}'; must match ^[a-z0-9][a-z0-9_-]{7,63}\$"
fi

evidence_directory="${repo_root}/docs/reference/research/artifacts/${artifact_id}/hetzner/${dispatch_id}"
log_path="${evidence_directory}/dispatch.log"
dispatch_json_path="${evidence_directory}/dispatch.json"
closeout_json_path="${evidence_directory}/closeout.json"

if ! mkdir -p "${evidence_directory}" 2>/dev/null; then
  echo "long_running_dispatch.sh: cannot create evidence directory: ${evidence_directory}" >&2
  exit 1
fi
# Ensure the log file exists so wc/stat work even when the wrapped command
# emits no output before signal/exit.
: > "${log_path}"

hostname_value="$(hostname)"
if [[ -n "${VM_IP:-}" ]]; then
  vm_ip_value="${VM_IP}"
else
  # `hostname -I` exists on Linux; macOS dev machines do not support `-I` and
  # exit non-zero, which would abort the script under pipefail+set -e.
  hostname_dash_I_output=""
  hostname_dash_I_output="$(hostname -I 2>/dev/null || true)"
  vm_ip_value="$(awk '{print $1}' <<<"${hostname_dash_I_output}")"
  vm_ip_value="${vm_ip_value:-127.0.0.1}"
fi
worktree_value="${repo_root}"

started_at_epoch="$(date -u +%s)"
started_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Render the wrapped command as a single shell-safe line.
printf -v wrapped_command_str '%q ' "${wrapped_cmd[@]}"
wrapped_command_str="${wrapped_command_str% }"

write_dispatch_json() {
  local tmp="${dispatch_json_path}.tmp"
  jq -n \
    --argjson schema_version 1 \
    --arg dispatch_id "${dispatch_id}" \
    --arg artifact_id "${artifact_id}" \
    --arg wrapped_command "${wrapped_command_str}" \
    --arg hostname "${hostname_value}" \
    --arg vm_ip "${vm_ip_value}" \
    --arg worktree "${worktree_value}" \
    --arg started_at_utc "${started_at_utc}" \
    --arg log_path "${log_path}" \
    --arg evidence_directory "${evidence_directory}" \
    --arg probe_sql "${probe_sql}" \
    '{
       schema_version: $schema_version,
       dispatch_id: $dispatch_id,
       artifact_id: $artifact_id,
       wrapped_command: $wrapped_command,
       host: { hostname: $hostname, vm_ip: $vm_ip, worktree: $worktree },
       started_at_utc: $started_at_utc,
       log_path: $log_path,
       evidence_directory: $evidence_directory,
       probe_sql: $probe_sql
     }' > "${tmp}"
  mv "${tmp}" "${dispatch_json_path}"
}

closeout_written=0

last_log_timestamp_utc() {
  if [[ -s "${log_path}" ]]; then
    # GNU date supports `-r FILE`, BSD/macOS uses `-r SECONDS`. Try GNU first.
    if last_ts="$(date -u -r "${log_path}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"; then
      echo "${last_ts}"
      return 0
    fi
    if mtime_epoch="$(stat -c '%Y' "${log_path}" 2>/dev/null)"; then
      date -u -r "${mtime_epoch}" +%Y-%m-%dT%H:%M:%SZ
      return 0
    fi
    if mtime_epoch="$(stat -f '%m' "${log_path}" 2>/dev/null)"; then
      date -u -r "${mtime_epoch}" +%Y-%m-%dT%H:%M:%SZ
      return 0
    fi
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ
}

write_closeout_json() {
  local terminal_status="$1"
  local exit_code="$2"

  if (( closeout_written != 0 )); then
    return 0
  fi
  closeout_written=1

  local finished_at_epoch finished_at_utc duration_seconds log_bytes last_log
  finished_at_epoch="$(date -u +%s)"
  finished_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  duration_seconds=$(( finished_at_epoch - started_at_epoch ))
  if (( duration_seconds < 0 )); then
    duration_seconds=0
  fi
  if [[ -f "${log_path}" ]]; then
    log_bytes="$(wc -c < "${log_path}" | tr -d '[:space:]')"
  else
    log_bytes=0
  fi
  last_log="$(last_log_timestamp_utc)"

  local tmp="${closeout_json_path}.tmp"
  jq -n \
    --argjson schema_version 1 \
    --arg dispatch_id "${dispatch_id}" \
    --arg finished_at_utc "${finished_at_utc}" \
    --arg terminal_status "${terminal_status}" \
    --argjson exit_code "${exit_code}" \
    --argjson duration_seconds "${duration_seconds}" \
    --argjson log_bytes "${log_bytes}" \
    --arg last_log_timestamp_utc "${last_log}" \
    '{
       schema_version: $schema_version,
       dispatch_id: $dispatch_id,
       finished_at_utc: $finished_at_utc,
       terminal_status: $terminal_status,
       exit_code: $exit_code,
       summary: {
         duration_seconds: $duration_seconds,
         log_bytes: $log_bytes,
         last_log_timestamp_utc: $last_log_timestamp_utc
       }
     }' > "${tmp}"
  mv "${tmp}" "${closeout_json_path}"
}

# Atomic write of dispatch.json BEFORE launching the wrapped command.
write_dispatch_json

signal_received=""
on_signal() {
  # Record the signal; the main flow handles closeout + exit so wait-after-signal
  # ordering is deterministic regardless of trap entry path.
  signal_received="$1"
}
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM

# Run the wrapped command in the background so `wait` can be interrupted by signals.
"${wrapped_cmd[@]}" >> "${log_path}" 2>&1 &
child_pid=$!

set +e
wait "${child_pid}"
wait_status=$?
set -e

if [[ -n "${signal_received}" ]]; then
  # Forward the signal to the child if it is still alive, then reap it.
  if kill -0 "${child_pid}" 2>/dev/null; then
    kill -"${signal_received}" "${child_pid}" 2>/dev/null || true
    set +e
    wait "${child_pid}"
    set -e
  fi
  case "${signal_received}" in
    INT) final_exit=130 ;;
    TERM) final_exit=143 ;;
    *) final_exit=1 ;;
  esac
  write_closeout_json "interrupted" "${final_exit}"
  exit "${final_exit}"
fi

if (( wait_status == 0 )); then
  write_closeout_json "succeeded" 0
  exit 0
fi

write_closeout_json "failed" "${wait_status}"
exit "${wait_status}"
