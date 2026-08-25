#!/usr/bin/env bash
# Repo-local detached command runner for multi-hour operator jobs.
#
# Owns the `start|status|wait|stop` commands and the `__run_wrapper` entrypoint
# the detached wrapper re-execs into. Job state, process ownership, and the
# launch handshake live in the three libraries sourced below, layered in that
# order; this file composes them and owns nothing they own.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
job_root="${DETACHED_RUNNER_ROOT:-${repo_root}/build/detached_jobs}"
# The wrapper is this same file re-executed, so the launch library needs the
# path this invocation was resolved from.
# shellcheck disable=SC2034  # Read by detached_runner_launch_lib.sh once sourced.
runner_script="${BASH_SOURCE[0]}"

# Libraries resolve from ${script_dir} at run time, which shellcheck cannot
# follow without -x; the source= directives name the targets for that run.
# shellcheck source=infra/scripts/detached_runner_job_state_lib.sh
source "${script_dir}/detached_runner_job_state_lib.sh"
# shellcheck source=infra/scripts/detached_runner_ownership_lib.sh
source "${script_dir}/detached_runner_ownership_lib.sh"
# shellcheck source=infra/scripts/detached_runner_launch_lib.sh
source "${script_dir}/detached_runner_launch_lib.sh"

usage() {
  # Unquoted heredoc: the advertised grace default is interpolated from the
  # ownership library's constant so `--help` cannot go stale when it is retuned.
  cat >&2 <<USAGE
Usage:
  detached_runner.sh start <job_name> -- <command...>
  detached_runner.sh status <job_name>
  detached_runner.sh wait <job_name> --poll-seconds N --timeout-seconds M
  detached_runner.sh stop <job_name>

Environment:
  DETACHED_RUNNER_STOP_GRACE_SECONDS
      Positive whole seconds to wait after TERM before escalating to KILL
      (default: ${DEFAULT_STOP_GRACE_SECONDS}).
USAGE
}

shell_quote_command() {
  local quoted="" arg
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
  local job_name="$1" directory
  directory="$(require_job_dir "${job_name}")"
  emit_status_json "${job_name}" "${directory}"
}

run_wrapper() {
  local directory="$1"
  shift
  local require_launch_approval=false
  if [[ "${1:-}" == "--require-launch-approval" ]]; then
    require_launch_approval=true
    shift
  fi
  [[ "${1:-}" == "--" ]] || exit 2
  shift

  local log_path="${directory}/log"
  local progress_path="${directory}/progress.jsonl"
  export DETACHED_RUNNER_JOB_DIR="${directory}"
  export DETACHED_RUNNER_PROGRESS_FILE="${progress_path}"

  set +e
  local child_pid="" child_status="" receipt_written=false

  # shellcheck disable=SC2329  # Invoked by the EXIT trap below.
  write_cleanup_receipt_on_exit() {
    local requested_wrapper_pid
    requested_wrapper_pid="$(read_first_line_or_empty "${directory}/cleanup_requested")"
    if [[ "${requested_wrapper_pid}" == "${BASHPID}" ]]; then
      atomic_write "${directory}/cleanup_receipt" "${BASHPID} ${child_pid}"
    fi
  }

  write_exit_receipt_once() {
    local status="$1"
    if [[ "${receipt_written}" == "false" ]]; then
      atomic_write "${directory}/exit_code" "${status}"
      receipt_written=true
    fi
  }

  # shellcheck disable=SC2329  # Invoked by the signal traps below.
  forward_signal() {
    local signal_name="$1"
    local signal_status="$2"
    if [[ -n "${child_pid}" ]]; then
      kill "-${signal_name}" "${child_pid}" 2>/dev/null || true
      wait "${child_pid}" 2>/dev/null || true
    fi
    write_exit_receipt_once "${signal_status}"
    exit "${signal_status}"
  }

  trap 'forward_signal INT 130' INT
  trap 'forward_signal QUIT 131' QUIT
  trap 'forward_signal TERM 143' TERM
  trap 'write_cleanup_receipt_on_exit' EXIT

  if [[ "${require_launch_approval}" == "true" ]]; then
    local wrapper_state
    wrapper_state="$(read_first_line_or_empty "${directory}/wrapper_ready")"
    if [[ "${wrapper_state}" != "${BASHPID} refused" ]]; then
      atomic_write "${directory}/wrapper_ready" "${BASHPID} ready"
    fi
    while true; do
      wrapper_state="$(read_first_line_or_empty "${directory}/wrapper_ready")"
      if [[ "${wrapper_state}" == "${BASHPID} approved" ]]; then
        rm -f "${directory}/wrapper_ready"
        break
      fi
      [[ "${wrapper_state}" == "${BASHPID} refused" ]] && exit 1
      sleep 0.05
    done
  fi
  "$@" >> "${log_path}" 2>&1 &
  child_pid=$!
  atomic_write "${directory}/child_pid" "${child_pid}"
  local child_identity
  child_identity="$(stable_process_identity "${child_pid}")"
  if [[ -n "${child_identity}" ]]; then
    atomic_write "${directory}/child_process_identity" "${child_identity}"
  fi
  wait "${child_pid}"
  child_status=$?
  write_exit_receipt_once "${child_status}"
  exit "${child_status}"
}

run_start() {
  local job_name="${1:-}"
  [[ -n "${job_name}" ]] || fail "start requires a job name"
  shift
  [[ "${1:-}" == "--" ]] || fail "start requires '--' before command"
  shift
  (( $# > 0 )) || fail "start requires a command"

  local directory display_command started_at wrapper_pid process_identity wrapper_pgid
  local wrapper_is_isolated=false
  directory="$(job_dir_for "${job_name}")"
  if [[ -d "${directory}" ]]; then
    if job_is_alive "${directory}"; then
      echo "detached_runner.sh: job '${job_name}' is already running" >&2
      exit 3
    fi
    if recorded_child_blocks_start "${directory}"; then
      echo "detached_runner.sh: refusing to start job '${job_name}': ${RECORDED_CHILD_REFUSAL_REASON}" >&2
      exit 3
    fi
  fi

  ensure_private_directory "${job_root}" "job root"
  ensure_private_directory "${directory}" "job directory"
  prepare_empty_file "${directory}/log" "job log"
  prepare_empty_file "${directory}/progress.jsonl" "job progress file"
  rm -f "${directory}/exit_code" "${directory}/child_pid" \
    "${directory}/child_process_identity" "${directory}/cleanup_receipt" \
    "${directory}/cleanup_requested" "${directory}/pid" "${directory}/pgid" \
    "${directory}/process_identity" "${directory}/wrapper_ready"

  display_command="$(shell_quote_command "$@")"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  atomic_write "${directory}/cmd" "${display_command}"
  atomic_write "${directory}/started_at" "${started_at}"

  if ! launch_isolated_wrapper "${directory}" "$@"; then
    exit 1
  fi
  wrapper_pid="${LAUNCHED_WRAPPER_PID}"
  atomic_write "${directory}/pid" "${wrapper_pid}"

  if ! wait_for_wrapper_ready "${directory}" "${wrapper_pid}"; then
    if refuse_unverified_launched_wrapper "${directory}" "${wrapper_pid}"; then
      clear_launch_handshake "${directory}"
    else
      echo "detached_runner.sh: failed to receive cleanup proof from unready wrapper PID ${wrapper_pid}" >&2
    fi
    echo "detached_runner.sh: launched wrapper PID ${wrapper_pid} did not become ready" >&2
    exit 1
  fi
  if wait_for_wrapper_pgid "${wrapper_pid}"; then
    wrapper_is_isolated=true
  fi
  if ! process_identity="$(stable_process_identity "${wrapper_pid}")"; then
    process_identity=""
  fi
  if [[ -z "${process_identity}" ]]; then
    if refuse_unverified_launched_wrapper "${directory}" "${wrapper_pid}"; then
      clear_launch_handshake "${directory}"
    else
      echo "detached_runner.sh: failed to terminate unobservable wrapper PID ${wrapper_pid}" >&2
    fi
    rm -f "${directory}/process_identity" "${directory}/pgid"
    echo "detached_runner.sh: launched job but could not observe process identity" >&2
    exit 1
  fi
  if [[ "${wrapper_is_isolated}" == "false" ]]; then
    if ! terminate_launched_wrapper "${wrapper_pid}" "${process_identity}"; then
      echo "detached_runner.sh: failed to terminate refused wrapper PID ${wrapper_pid}" >&2
    fi
    rm -f "${directory}/process_identity" "${directory}/pgid" "${directory}/wrapper_ready"
    echo "detached_runner.sh: refusing job because wrapper PID ${wrapper_pid} does not lead an isolated process group (observed PGID: ${OBSERVED_WRAPPER_PGID:-unobservable})" >&2
    exit 1
  fi
  wrapper_pgid="${OBSERVED_WRAPPER_PGID}"
  atomic_write "${directory}/process_identity" "${process_identity}"
  atomic_write "${directory}/pgid" "${wrapper_pgid}"
  atomic_write "${directory}/wrapper_ready" "${wrapper_pid} approved"
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

write_stop_receipt_once() {
  local directory="$1"
  if [[ ! -f "${directory}/exit_code" ]]; then
    atomic_write "${directory}/exit_code" "143"
  fi
}

finish_successful_stop() {
  local job_name="$1" directory="$2"
  write_stop_receipt_once "${directory}"
  emit_status_json "${job_name}" "${directory}"
}

# Terminate the job by signalling only the revalidated wrapper-led process
# group, so every descendant the wrapper started dies with it and no process
# outside that group is touched.
run_stop() {
  local job_name="$1" directory stop_grace_seconds stop_group_exit_attempts
  directory="$(require_job_dir "${job_name}")"
  stop_grace_seconds="${DETACHED_RUNNER_STOP_GRACE_SECONDS:-${DEFAULT_STOP_GRACE_SECONDS}}"
  require_positive_integer "DETACHED_RUNNER_STOP_GRACE_SECONDS" "${stop_grace_seconds}"
  stop_group_exit_attempts=$(( stop_grace_seconds * STOP_POLLS_PER_SECOND ))
  if ! verified_owned_process_group "${directory}"; then
    echo "detached_runner.sh: refusing to stop job '${job_name}': ${STOP_REFUSAL_REASON}" >&2
    exit 4
  fi

  kill -TERM "-${VERIFIED_STOP_PGID}" 2>/dev/null || true
  if wait_for_process_group_exit "${VERIFIED_STOP_PGID}" "${stop_group_exit_attempts}"; then
    # The wrapper normally writes its own 143 receipt from the TERM trap; this
    # only covers a wrapper that died without recording a terminal status.
    finish_successful_stop "${job_name}" "${directory}"
    return 0
  fi

  kill -KILL "-${VERIFIED_STOP_PGID}" 2>/dev/null || true
  if wait_for_process_group_exit "${VERIFIED_STOP_PGID}" "${stop_group_exit_attempts}" || \
    process_group_has_no_members "${VERIFIED_STOP_PGID}"; then
    finish_successful_stop "${job_name}" "${directory}"
    return 0
  fi

  echo "detached_runner.sh: failed to stop job '${job_name}': verified process group ${VERIFIED_STOP_PGID} survived TERM and KILL" >&2
  emit_status_json "${job_name}" "${directory}"
  exit 5
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
