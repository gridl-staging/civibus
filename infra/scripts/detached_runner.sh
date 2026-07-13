#!/usr/bin/env bash
# Repo-local detached command runner for multi-hour operator jobs.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
job_root="${DETACHED_RUNNER_ROOT:-${repo_root}/build/detached_jobs}"

usage() {
  cat >&2 <<'USAGE'
Usage:
  detached_runner.sh start <job_name> -- <command...>
  detached_runner.sh status <job_name>
  detached_runner.sh wait <job_name> --poll-seconds N --timeout-seconds M
  detached_runner.sh stop <job_name>
USAGE
}

fail() {
  echo "detached_runner.sh: $*" >&2
  exit 2
}

ensure_path_not_symlink() {
  local path="$1"
  local path_label="$2"
  if [[ -L "${path}" ]]; then
    fail "refusing symlinked ${path_label}: ${path}"
  fi
}

ensure_private_directory() {
  local path="$1"
  local path_label="$2"
  ensure_path_not_symlink "${path}" "${path_label}"
  mkdir -p "${path}"
  chmod 700 "${path}"
}

prepare_empty_file() {
  local path="$1"
  local path_label="$2"
  ensure_path_not_symlink "${path}" "${path_label}"
  : > "${path}"
  chmod 600 "${path}"
}

atomic_write() {
  local path="$1"
  local value="$2"
  local tmp
  ensure_path_not_symlink "${path}" "job metadata path"
  tmp="$(mktemp "${path}.tmp.XXXXXX")"
  printf '%s\n' "${value}" > "${tmp}"
  chmod 600 "${tmp}"
  mv "${tmp}" "${path}"
}

validate_job_name() {
  local job_name="$1"
  if [[ ! "${job_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    fail "invalid job name: ${job_name}"
  fi
  if [[ "${job_name}" == *..* ]]; then
    fail "invalid job name: ${job_name}"
  fi
}

require_positive_integer() {
  local option_name="$1"
  local option_value="$2"
  if [[ ! "${option_value}" =~ ^[1-9][0-9]*$ ]]; then
    fail "${option_name} must be a positive integer"
  fi
}

job_dir_for() {
  local job_name="$1"
  validate_job_name "${job_name}"
  printf '%s/%s\n' "${job_root}" "${job_name}"
}

require_job_dir() {
  local job_name="$1"
  local directory
  directory="$(job_dir_for "${job_name}")"
  ensure_private_directory "${job_root}" "job root"
  ensure_path_not_symlink "${directory}" "job directory"
  if [[ ! -d "${directory}" ]]; then
    fail "unknown job: ${job_name}"
  fi
  chmod 700 "${directory}"
  printf '%s\n' "${directory}"
}

read_file_or_empty() {
  local path="$1"
  ensure_path_not_symlink "${path}" "job metadata path"
  if [[ -f "${path}" ]]; then
    cat "${path}"
  fi
}

read_first_line_or_empty() {
  local path="$1"
  ensure_path_not_symlink "${path}" "job metadata path"
  if [[ -f "${path}" ]]; then
    IFS= read -r line < "${path}" || true
    printf '%s\n' "${line:-}"
  fi
}

last_line_or_empty() {
  local path="$1"
  ensure_path_not_symlink "${path}" "job metadata path"
  if [[ -s "${path}" ]]; then
    tail -n 1 "${path}"
  fi
}

observed_process_identity() {
  local pid="$1"
  ps -p "${pid}" -o command= 2>/dev/null || true
}

stable_process_identity() {
  local pid="$1"
  local observed_identity="" previous_identity="" attempt
  for attempt in 1 2 3 4 5; do
    observed_identity="$(observed_process_identity "${pid}")"
    if [[ -n "${observed_identity}" ]]; then
      if [[ "${observed_identity}" == "${previous_identity}" ]]; then
        printf '%s\n' "${observed_identity}"
        return 0
      fi
      previous_identity="${observed_identity}"
    fi
    sleep 0.05
  done
  if [[ -n "${previous_identity}" ]]; then
    printf '%s\n' "${previous_identity}"
    return 0
  fi
  return 1
}

pid_identity_matches() {
  local pid="$1"
  local recorded_identity="$2"
  local observed_identity
  observed_identity="$(observed_process_identity "${pid}")"
  [[ -n "${observed_identity}" && "${observed_identity}" == "${recorded_identity}" ]]
}

wait_for_pid_exit() {
  local pid="$1"
  local recorded_identity="$2"
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ! pid_identity_matches "${pid}" "${recorded_identity}"; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

# Resolve the safest PID to signal for this job. Prefer the wrapper when its
# recorded identity still matches; otherwise fall back to the child command only
# when the wrapper has disappeared and the child command's own recorded identity
# still matches.
stop_target_pid() {
  local directory="$1"
  local pid recorded_identity child_pid child_identity observed_identity
  STOP_TARGET_PID=""
  STOP_TARGET_KIND=""
  pid="$(read_first_line_or_empty "${directory}/pid")"
  recorded_identity="$(read_file_or_empty "${directory}/process_identity")"
  if [[ -n "${pid}" && -n "${recorded_identity}" ]]; then
    observed_identity="$(observed_process_identity "${pid}")"
    if [[ -n "${observed_identity}" ]]; then
      if [[ "${observed_identity}" == "${recorded_identity}" ]]; then
        STOP_TARGET_PID="${pid}"
        STOP_TARGET_KIND="wrapper"
        return 0
      fi
      return 2
    fi
  fi

  child_pid="$(read_first_line_or_empty "${directory}/child_pid")"
  child_identity="$(read_file_or_empty "${directory}/child_process_identity")"
  if [[ -n "${child_pid}" && -n "${child_identity}" ]] && pid_identity_matches "${child_pid}" "${child_identity}"; then
    STOP_TARGET_PID="${child_pid}"
    STOP_TARGET_KIND="child"
    return 0
  fi

  return 1
}

job_is_alive() {
  local directory="$1"
  local pid recorded_identity child_pid child_identity
  pid="$(read_first_line_or_empty "${directory}/pid")"
  recorded_identity="$(read_file_or_empty "${directory}/process_identity")"
  if [[ -z "${pid}" || -z "${recorded_identity}" ]]; then
    return 1
  fi
  if [[ -f "${directory}/exit_code" ]]; then
    return 1
  fi
  # PID recycling safety: a live PID is ours only while its observed command
  # identity still matches what start recorded immediately after launch.
  if pid_identity_matches "${pid}" "${recorded_identity}"; then
    return 0
  fi

  child_pid="$(read_first_line_or_empty "${directory}/child_pid")"
  child_identity="$(read_file_or_empty "${directory}/child_process_identity")"
  if [[ -n "${child_pid}" && -n "${child_identity}" ]]; then
    pid_identity_matches "${child_pid}" "${child_identity}"
    return
  fi
  return 1
}

shell_quote_command() {
  local quoted=""
  local arg
  for arg in "$@"; do
    printf -v quoted_arg '%q' "${arg}"
    quoted+="${quoted_arg} "
  done
  printf '%s\n' "${quoted% }"
}

emit_status_json() {
  local job_name="$1"
  local directory="$2"
  local pid started_at exit_code alive last_log_line progress_line
  pid="$(read_first_line_or_empty "${directory}/pid")"
  started_at="$(read_first_line_or_empty "${directory}/started_at")"
  exit_code="$(read_first_line_or_empty "${directory}/exit_code")"
  last_log_line="$(last_line_or_empty "${directory}/log")"
  progress_line="$(last_line_or_empty "${directory}/progress.jsonl")"
  alive=false
  if job_is_alive "${directory}"; then
    alive=true
  fi

  JOB_NAME="${job_name}" \
    JOB_PID="${pid}" \
    JOB_ALIVE="${alive}" \
    JOB_EXIT_CODE="${exit_code}" \
    JOB_STARTED_AT="${started_at}" \
    JOB_LAST_LOG_LINE="${last_log_line}" \
    JOB_PROGRESS_LINE="${progress_line}" \
    python3 - <<'PY'
import json
import os

exit_code_text = os.environ["JOB_EXIT_CODE"].strip()
progress_line = os.environ["JOB_PROGRESS_LINE"]
progress = None
if progress_line:
    try:
        progress = json.loads(progress_line)
    except json.JSONDecodeError:
        progress = progress_line

payload = {
    "job": os.environ["JOB_NAME"],
    "pid": int(os.environ["JOB_PID"]) if os.environ["JOB_PID"].strip() else None,
    "alive": os.environ["JOB_ALIVE"] == "true",
    "exit_code": int(exit_code_text) if exit_code_text else None,
    "started_at": os.environ["JOB_STARTED_AT"],
    "last_log_line": os.environ["JOB_LAST_LOG_LINE"],
    "progress": progress,
}
print(json.dumps(payload, separators=(",", ":")))
PY
}

run_status() {
  local job_name="$1"
  local directory
  directory="$(require_job_dir "${job_name}")"
  emit_status_json "${job_name}" "${directory}"
}

run_wrapper() {
  local directory="$1"
  shift
  [[ "${1:-}" == "--" ]] || exit 2
  shift

  local log_path="${directory}/log"
  local progress_path="${directory}/progress.jsonl"
  export DETACHED_RUNNER_JOB_DIR="${directory}"
  export DETACHED_RUNNER_PROGRESS_FILE="${progress_path}"

  set +e
  "$@" >> "${log_path}" 2>&1 &
  local child_pid=$!
  atomic_write "${directory}/child_pid" "${child_pid}"
  local child_identity
  child_identity="$(stable_process_identity "${child_pid}")"
  if [[ -n "${child_identity}" ]]; then
    atomic_write "${directory}/child_process_identity" "${child_identity}"
  fi

  forward_term() {
    kill -TERM "${child_pid}" 2>/dev/null || true
    wait "${child_pid}" 2>/dev/null
    atomic_write "${directory}/exit_code" "143"
    exit 143
  }
  trap forward_term TERM

  wait "${child_pid}"
  local child_status=$?
  atomic_write "${directory}/exit_code" "${child_status}"
  exit "${child_status}"
}

run_start() {
  local job_name="${1:-}"
  [[ -n "${job_name}" ]] || fail "start requires a job name"
  shift
  [[ "${1:-}" == "--" ]] || fail "start requires '--' before command"
  shift
  (( $# > 0 )) || fail "start requires a command"

  local directory display_command started_at wrapper_pid process_identity
  directory="$(job_dir_for "${job_name}")"
  if [[ -d "${directory}" ]] && job_is_alive "${directory}"; then
    echo "detached_runner.sh: job '${job_name}' is already running" >&2
    exit 3
  fi

  ensure_private_directory "${job_root}" "job root"
  ensure_private_directory "${directory}" "job directory"
  prepare_empty_file "${directory}/log" "job log"
  prepare_empty_file "${directory}/progress.jsonl" "job progress file"
  rm -f "${directory}/exit_code" "${directory}/child_pid" "${directory}/child_process_identity" "${directory}/process_identity"

  display_command="$(shell_quote_command "$@")"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  atomic_write "${directory}/cmd" "${display_command}"
  atomic_write "${directory}/started_at" "${started_at}"

  # Darwin dev hosts usually lack setsid; nohup is the portable baseline.
  if command -v setsid >/dev/null 2>&1; then
    setsid bash "${BASH_SOURCE[0]}" __run_wrapper "${directory}" -- "$@" </dev/null >/dev/null 2>&1 &
  else
    nohup bash "${BASH_SOURCE[0]}" __run_wrapper "${directory}" -- "$@" </dev/null >/dev/null 2>&1 &
  fi
  wrapper_pid=$!
  atomic_write "${directory}/pid" "${wrapper_pid}"

  process_identity="$(stable_process_identity "${wrapper_pid}")"
  if [[ -z "${process_identity}" ]]; then
    echo "detached_runner.sh: launched job but could not observe process identity" >&2
    exit 1
  fi
  atomic_write "${directory}/process_identity" "${process_identity}"
  emit_status_json "${job_name}" "${directory}"
}

run_wait() {
  local job_name="${1:-}"
  [[ -n "${job_name}" ]] || fail "wait requires a job name"
  shift

  local poll_seconds="" timeout_seconds=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --poll-seconds)
        [[ $# -ge 2 ]] || fail "--poll-seconds requires a value"
        poll_seconds="$2"
        shift 2
        ;;
      --timeout-seconds)
        [[ $# -ge 2 ]] || fail "--timeout-seconds requires a value"
        timeout_seconds="$2"
        shift 2
        ;;
      *)
        fail "unknown wait argument: $1"
        ;;
    esac
    done
    [[ -n "${poll_seconds}" ]] || fail "--poll-seconds is required"
    [[ -n "${timeout_seconds}" ]] || fail "--timeout-seconds is required"
    require_positive_integer "--poll-seconds" "${poll_seconds}"
    require_positive_integer "--timeout-seconds" "${timeout_seconds}"

    local directory start_epoch now_epoch elapsed exit_code
    directory="$(require_job_dir "${job_name}")"
  start_epoch="$(date -u +%s)"
  while true; do
    exit_code="$(read_first_line_or_empty "${directory}/exit_code")"
    if [[ -n "${exit_code}" ]]; then
      emit_status_json "${job_name}" "${directory}"
      exit "${exit_code}"
    fi
    if ! job_is_alive "${directory}"; then
      exit_code="$(read_first_line_or_empty "${directory}/exit_code")"
      if [[ -n "${exit_code}" ]]; then
        emit_status_json "${job_name}" "${directory}"
        exit "${exit_code}"
      fi
      emit_status_json "${job_name}" "${directory}"
      exit 1
    fi
    now_epoch="$(date -u +%s)"
    elapsed=$(( now_epoch - start_epoch ))
    if (( elapsed >= timeout_seconds )); then
      # Timeout is a reporting outcome only; the detached job remains alive.
      emit_status_json "${job_name}" "${directory}"
      exit 124
    fi
    sleep "${poll_seconds}"
  done
}

run_stop() {
  local job_name="$1"
  local directory stop_target_status child_pid child_identity
  directory="$(require_job_dir "${job_name}")"
  child_pid="$(read_first_line_or_empty "${directory}/child_pid")"
  child_identity="$(read_file_or_empty "${directory}/child_process_identity")"
  if stop_target_pid "${directory}"; then
    stop_target_status=0
  else
    stop_target_status=$?
  fi
  if [[ "${stop_target_status}" -eq 2 ]]; then
    echo "detached_runner.sh: process identity mismatch for job '${job_name}'" >&2
    exit 4
  fi
  if [[ -z "${STOP_TARGET_PID:-}" ]]; then
    echo "detached_runner.sh: job '${job_name}' has incomplete process metadata" >&2
    exit 4
  fi
  kill -TERM "${STOP_TARGET_PID}"
  if [[ "${STOP_TARGET_KIND:-}" == "child" && -n "${child_pid}" && -n "${child_identity}" ]]; then
    if wait_for_pid_exit "${child_pid}" "${child_identity}"; then
      atomic_write "${directory}/exit_code" "143"
    fi
  fi
  emit_status_json "${job_name}" "${directory}"
}

command_name="${1:-}"
case "${command_name}" in
  __run_wrapper)
    shift
    run_wrapper "$@"
    ;;
  start)
    shift
    run_start "$@"
    ;;
  status)
    shift
    [[ $# -eq 1 ]] || fail "status requires exactly one job name"
    run_status "$1"
    ;;
  wait)
    shift
    run_wait "$@"
    ;;
  stop)
    shift
    [[ $# -eq 1 ]] || fail "stop requires exactly one job name"
    run_stop "$1"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
esac
