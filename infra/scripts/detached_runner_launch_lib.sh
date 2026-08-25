#!/usr/bin/env bash
# Wrapper launch and cleanup handshake for infra/scripts/detached_runner.sh.
#
# Sourced (not executed) by detached_runner.sh, layered on
# detached_runner_job_state_lib.sh and detached_runner_ownership_lib.sh, whose
# identity verdicts and polling cadence it reuses. Single owner of session
# isolation at launch, of the wrapper_ready/cleanup_requested handshake that
# proves a launched wrapper is under runner control, and of tearing down a
# wrapper the runner launched but refused to adopt. The wrapper is a re-exec of
# the runner itself, so `runner_script` -- the path the runner was invoked with
# -- is supplied by the sourcing runner.
#
# Cross-file globals make this library lintable only together with the runner
# that sources it, and only under --check-sourced: without that flag a sourced
# file is read for its definitions but never reported on. The lint gate is
# `shellcheck -x --check-sourced infra/scripts/detached_runner.sh`, run by
# tests/infra/test_detached_runner.py so the flag cannot quietly regress.

# Widened because shared-host flakes exceeded the old 2.0s deadline (40 attempts).
# Measured 2026-08-25 on this loaded host: max wrapper_ready latency 0.2533s.
# 100 polls bounds the deadline at 5.0s, so a never-ready start costs +3.0s.
WRAPPER_READY_ATTEMPTS=100
CLEANUP_RECEIPT_ATTEMPTS=10
CLEANUP_PROCESS_EXIT_ATTEMPTS=10

wrapper_ready_matches() {
  local directory="$1" wrapper_pid="$2"
  [[ "$(read_first_line_or_empty "${directory}/wrapper_ready")" == "${wrapper_pid} ready" ]]
}

wait_for_wrapper_ready() {
  poll_until "${WRAPPER_READY_ATTEMPTS}" "${FAST_POLL_INTERVAL_SECONDS}" wrapper_ready_matches "$1" "$2"
}

launch_python_session_wrapper() {
  local directory="$1"
  shift
  python3 - "${runner_script}" "${directory}" "$@" <<'PY'
import os
import subprocess
import sys

script_path = sys.argv[1]
job_directory = sys.argv[2]
command = sys.argv[3:]
devnull = os.open(os.devnull, os.O_RDWR)
try:
    process = subprocess.Popen(
        ["bash", script_path, "__run_wrapper", job_directory, "--require-launch-approval", "--", *command],
        stdin=devnull,
        stdout=devnull,
        stderr=devnull,
        start_new_session=True,
        close_fds=True,
    )
finally:
    os.close(devnull)
print(process.pid)
PY
}

launch_isolated_wrapper() {
  local directory="$1"
  shift
  LAUNCHED_WRAPPER_PID=""

  if [[ "${DETACHED_RUNNER_FORCE_PYTHON_SESSION:-}" == "1" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      echo "detached_runner.sh: Python session launcher requested but python3 is unavailable" >&2
      return 1
    fi
    LAUNCHED_WRAPPER_PID="$(launch_python_session_wrapper "${directory}" "$@")"
  elif command -v setsid >/dev/null 2>&1; then
    setsid bash "${runner_script}" __run_wrapper "${directory}" --require-launch-approval -- "$@" </dev/null >/dev/null 2>&1 &
    LAUNCHED_WRAPPER_PID=$!
  elif command -v python3 >/dev/null 2>&1; then
    LAUNCHED_WRAPPER_PID="$(launch_python_session_wrapper "${directory}" "$@")"
  else
    echo "detached_runner.sh: no session-isolating launcher is available; install setsid or python3" >&2
    return 1
  fi
}

# Tear down a wrapper the runner launched but refused to adopt. This runs before
# ownership metadata is published, so the launch-time identity is the only proof
# available: a PID already gone needs no signal, and one that no longer carries
# that identity names somebody else now. Fails only when a wrapper still provably
# ours survives both TERM and KILL.
terminate_launched_wrapper() {
  local wrapper_pid="$1" wrapper_identity="$2"

  case "$(pid_identity_verdict "${wrapper_pid}" "${wrapper_identity}")" in
    gone) return 0 ;;
    mismatch) return 1 ;;
  esac
  kill -TERM "${wrapper_pid}" 2>/dev/null || true
  if wait_for_pid_exit "${wrapper_pid}" "${wrapper_identity}"; then
    wait "${wrapper_pid}" 2>/dev/null || true
    return 0
  fi

  if pid_identity_matches "${wrapper_pid}" "${wrapper_identity}"; then
    kill -KILL "${wrapper_pid}" 2>/dev/null || true
  fi
  if wait_for_pid_exit "${wrapper_pid}" "${wrapper_identity}"; then
    wait "${wrapper_pid}" 2>/dev/null || true
    return 0
  fi
  return 1
}

refuse_unverified_launched_wrapper() {
  local directory="$1" wrapper_pid="$2" child_pid

  child_pid="$(read_first_line_or_empty "${directory}/child_pid")"
  atomic_write "${directory}/cleanup_requested" "${wrapper_pid}"
  atomic_write "${directory}/wrapper_ready" "${wrapper_pid} refused"
  if ! wait_for_cleanup_receipt "${directory}" "${wrapper_pid}" "${child_pid}"; then
    return 1
  fi
  wait_for_exact_processes_to_exit "${wrapper_pid}" "${child_pid}"
}

clear_launch_handshake() {
  local directory="$1"
  rm -f "${directory}/cleanup_receipt" "${directory}/cleanup_requested" \
    "${directory}/wrapper_ready"
}

wait_for_cleanup_receipt() {
  local directory="$1" wrapper_pid="$2" child_pid="$3"
  poll_until "${CLEANUP_RECEIPT_ATTEMPTS}" "${DEFAULT_POLL_INTERVAL_SECONDS}" cleanup_receipt_matches "${directory}" "${wrapper_pid}" "${child_pid}"
}

cleanup_receipt_matches() {
  local directory="$1" wrapper_pid="$2" child_pid="$3"
  local receipt_wrapper_pid receipt_child_pid extra
  read -r receipt_wrapper_pid receipt_child_pid extra \
    <<< "$(read_first_line_or_empty "${directory}/cleanup_receipt")"
  [[ -z "${extra:-}" && "${receipt_wrapper_pid:-}" == "${wrapper_pid}" && "${receipt_child_pid:-}" == "${child_pid}" ]]
}

wait_for_exact_processes_to_exit() {
  local wrapper_pid="$1" child_pid="$2"
  poll_until "${CLEANUP_PROCESS_EXIT_ATTEMPTS}" "${DEFAULT_POLL_INTERVAL_SECONDS}" exact_processes_exited "${wrapper_pid}" "${child_pid}"
}

exact_processes_exited() {
  local wrapper_pid="$1" child_pid="$2"
  local wrapper_live child_live
  wrapper_live=false
  child_live=false
  kill -0 "${wrapper_pid}" 2>/dev/null && wrapper_live=true
  if [[ -n "${child_pid}" ]]; then
    kill -0 "${child_pid}" 2>/dev/null && child_live=true
  fi
  [[ "${wrapper_live}" == "false" && "${child_live}" == "false" ]]
}

