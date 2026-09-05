#!/usr/bin/env bash
# Job state directory and metadata store for infra/scripts/detached_runner.sh.
#
# Sourced (not executed) by detached_runner.sh. Single owner of the runner's
# failure exit, its symlink and permission guards, atomic metadata writes, job
# name validation, job directory resolution, and metadata reads. Nothing here
# observes processes: every layer above reads and writes job state only through
# these helpers, so the 0600/0700 and no-symlink rules have exactly one home.
# `job_root` is supplied by the sourcing runner.
#
# Cross-file globals make this library lintable only together with the runner
# that sources it, and only under --check-sourced: without that flag a sourced
# file is read for its definitions but never reported on. The lint gate is
# `shellcheck -x --check-sourced infra/scripts/detached_runner.sh`, run by
# tests/infra/test_detached_runner.py so the flag cannot quietly regress.

fail() {
  echo "detached_runner.sh: $*" >&2
  exit 2
}

ensure_path_not_symlink() {
  local path="$1" path_label="$2"
  if [[ -L "${path}" ]]; then
    fail "refusing symlinked ${path_label}: ${path}"
  fi
}

ensure_private_directory() {
  local path="$1" path_label="$2"
  ensure_path_not_symlink "${path}" "${path_label}"
  mkdir -p "${path}"
  chmod 700 "${path}"
}

prepare_empty_file() {
  local path="$1" path_label="$2"
  ensure_path_not_symlink "${path}" "${path_label}"
  : > "${path}"
  chmod 600 "${path}"
}

atomic_write() {
  local path="$1" value="$2" tmp
  ensure_path_not_symlink "${path}" "job metadata path"
  tmp="$(mktemp "${path}.tmp.XXXXXX")"
  printf '%s\n' "${value}" > "${tmp}"
  chmod 600 "${tmp}"
  mv "${tmp}" "${path}"
}

# The `start` critical section's mutex, kept here because the lock is a member
# of the job directory this library already owns and so inherits its no-symlink
# and 0700 guards. `mkdir` is the portable atomic test-and-set -- a single
# syscall on Darwin and Linux alike -- where flock(1) is absent from a stock
# macOS. Every helper below takes a job directory the caller has already
# created, because the lock cannot precede the directory it lives in.
#
# The lock records the PID and command identity of the starter holding it. The
# rule deciding whether that starter is still alive is not this library's --
# nothing here observes processes -- and lives with every other such rule in
# detached_runner_ownership_lib.sh, which layers on this file.

# The job directory whose start lock this process currently holds, published so
# an EXIT trap can release it without depending on a caller's locals surviving
# the exit. The starter identity of that lock is published alongside so release
# can prove the lock still belongs to this process before deleting it.
HELD_START_LOCK_DIRECTORY=""
HELD_START_LOCK_STARTER_PID=""
HELD_START_LOCK_STARTER_IDENTITY=""
# The job directory whose reclaim mutex this process holds. Only one starter at
# a time may evaluate and clear a held start lock; see claim_start_lock_reclaim.
HELD_START_LOCK_RECLAIM_DIRECTORY=""
HELD_START_LOCK_RECLAIM_STARTER_PID=""
HELD_START_LOCK_RECLAIM_STARTER_IDENTITY=""
ACTIVE_START_LOCK_CLAIM_PATH=""
START_LOCK_CLAIM_PATHS=()

start_lock_path() {
  printf '%s/start.lock\n' "$1"
}

start_lock_reclaim_path() {
  printf '%s/start.lock.reclaim\n' "$1"
}

# The reclaim mutex serializes stale-lock reclaimers: exactly one starter at a
# time may decide a held start lock is stale and clear it. Without it, two
# reclaimers could each move the lock aside, and one could move aside a *live*
# replacement lock a third starter claimed in the gap after the first reclaim --
# exposing a claimable vacancy and then discarding that live lock. Holding this
# mutex across the whole reclaim decision guarantees the lock a reclaimer clears
# is still the stale one it observed, because no other reclaimer can act and a
# fresh claim needs the path the stale holder still occupies. Its owner metadata
# and pre-claim record mirror start.lock so a killed reclaimer can be identified
# even if it dies between mkdir and publishing metadata inside the mutex.
claim_start_lock_reclaim() {
  local directory="$1" starter_pid="$2" starter_identity="$3" reclaim_path
  reclaim_path="$(start_lock_reclaim_path "${directory}")"
  prepare_start_lock_claim "${directory}" "${starter_pid}" "${starter_identity}"
  ensure_path_not_symlink "${reclaim_path}" "job start lock reclaim"
  mkdir "${reclaim_path}" 2>/dev/null || return 1
  HELD_START_LOCK_RECLAIM_DIRECTORY="${directory}"
  HELD_START_LOCK_RECLAIM_STARTER_PID="${starter_pid}"
  HELD_START_LOCK_RECLAIM_STARTER_IDENTITY="${starter_identity}"
  chmod 700 "${reclaim_path}"
  atomic_write "${reclaim_path}/starter_pid" "${starter_pid}"
  atomic_write "${reclaim_path}/starter_identity" "${starter_identity}"
  # If command-identity observation failed, retain the PID claim so contenders
  # can fail closed on its liveness instead of treating this live mutex as an
  # abandoned incomplete publication. release_start_lock clears the claim.
  if [[ -n "${starter_identity}" ]]; then
    clear_active_start_lock_claim
  fi
}

release_start_lock_reclaim() {
  local reclaim_path recorded_pid recorded_identity
  [[ -n "${HELD_START_LOCK_RECLAIM_DIRECTORY}" ]] || return 0
  reclaim_path="$(start_lock_reclaim_path "${HELD_START_LOCK_RECLAIM_DIRECTORY}")"
  HELD_START_LOCK_RECLAIM_DIRECTORY=""
  ensure_path_not_symlink "${reclaim_path}" "job start lock reclaim"
  recorded_pid="$(read_first_line_or_empty "${reclaim_path}/starter_pid")"
  recorded_identity="$(read_first_line_or_empty "${reclaim_path}/starter_identity")"
  if [[ "${recorded_pid}" == "${HELD_START_LOCK_RECLAIM_STARTER_PID}" &&
    "${recorded_identity}" == "${HELD_START_LOCK_RECLAIM_STARTER_IDENTITY}" ]]; then
    rm -rf "${reclaim_path}"
  fi
  HELD_START_LOCK_RECLAIM_STARTER_PID=""
  HELD_START_LOCK_RECLAIM_STARTER_IDENTITY=""
}

start_lock_reclaim_starter_pid() {
  read_first_line_or_empty "$(start_lock_reclaim_path "$1")/starter_pid"
}

start_lock_reclaim_starter_identity() {
  read_first_line_or_empty "$(start_lock_reclaim_path "$1")/starter_identity"
}

start_lock_claim_path() {
  printf '%s/start.lock.claim.%s\n' "$1" "$2"
}

collect_start_lock_claim_paths() {
  local directory="$1" claim_path
  START_LOCK_CLAIM_PATHS=()
  for claim_path in "${directory}"/start.lock.claim.*; do
    [[ -e "${claim_path}" || -L "${claim_path}" ]] || continue
    ensure_path_not_symlink "${claim_path}" "job start lock claim"
    [[ -d "${claim_path}" ]] || fail "invalid job start lock claim: ${claim_path}"
    chmod 700 "${claim_path}"
    START_LOCK_CLAIM_PATHS+=("${claim_path}")
  done
}

start_lock_claim_starter_pid() {
  read_first_line_or_empty "$1/starter_pid"
}

start_lock_claim_starter_identity() {
  read_first_line_or_empty "$1/starter_identity"
}

start_lock_starter_pid() {
  read_first_line_or_empty "$(start_lock_path "$1")/starter_pid"
}

start_lock_starter_identity() {
  read_first_line_or_empty "$(start_lock_path "$1")/starter_identity"
}

# Publish the claimant before creating start.lock. If a starter is killed in
# the otherwise unavoidable gap between atomic mkdir and the lock's first
# metadata write, a later starter can still identify the process that made the
# incomplete lock. The PID-scoped path lets concurrent contenders publish
# without overwriting the winner's identity.
prepare_start_lock_claim() {
  local directory="$1" starter_pid="$2" starter_identity="$3" claim_path
  claim_path="$(start_lock_claim_path "${directory}" "${starter_pid}")"
  ensure_private_directory "${claim_path}" "job start lock claim"
  ACTIVE_START_LOCK_CLAIM_PATH="${claim_path}"
  atomic_write "${claim_path}/starter_pid" "${starter_pid}"
  atomic_write "${claim_path}/starter_identity" "${starter_identity}"
}

clear_active_start_lock_claim() {
  local claim_path
  [[ -n "${ACTIVE_START_LOCK_CLAIM_PATH}" ]] || return 0
  claim_path="${ACTIVE_START_LOCK_CLAIM_PATH}"
  ACTIVE_START_LOCK_CLAIM_PATH=""
  ensure_path_not_symlink "${claim_path}" "job start lock claim"
  rm -rf "${claim_path}"
}

# Become the job's starter, or return 1 because another process already is.
# The held-lock marker is published before the in-lock starter metadata is
# written, so an ordinary failure part-way through the claim releases both the
# lock and its pre-claim record from run_start's EXIT trap.
claim_start_lock() {
  local directory="$1" starter_pid="$2" starter_identity="$3" lock_path
  lock_path="$(start_lock_path "${directory}")"
  prepare_start_lock_claim "${directory}" "${starter_pid}" "${starter_identity}"
  ensure_path_not_symlink "${lock_path}" "job start lock"
  if ! mkdir "${lock_path}" 2>/dev/null; then
    clear_active_start_lock_claim
    return 1
  fi
  HELD_START_LOCK_DIRECTORY="${directory}"
  HELD_START_LOCK_STARTER_PID="${starter_pid}"
  HELD_START_LOCK_STARTER_IDENTITY="${starter_identity}"
  chmod 700 "${lock_path}"
  atomic_write "${lock_path}/starter_pid" "${starter_pid}"
  atomic_write "${lock_path}/starter_identity" "${starter_identity}"
  # A blank identity cannot support the ordinary identity verdict. Keep the
  # pre-claim record until release so the ownership layer can still recognize
  # the live publication window and refuse a competing starter safely.
  if [[ -n "${starter_identity}" ]]; then
    clear_active_start_lock_claim
  fi
}

# Release only a lock this process actually claimed and still owns. A caller
# that was refused the lock holds nothing, so this is a no-op for it. And even a
# caller that did claim verifies the lock's recorded starter still names it
# before deleting: if a reclaim ever displaced this lock and another starter now
# holds the path, its metadata no longer matches, and removing it would delete
# that starter's live lock. The reclaim mutex already prevents that displacement,
# so this check is the belt-and-suspenders half of that guarantee.
release_start_lock() {
  local lock_path recorded_pid recorded_identity
  release_start_lock_reclaim
  clear_active_start_lock_claim
  if [[ -n "${HELD_START_LOCK_DIRECTORY}" ]]; then
    lock_path="$(start_lock_path "${HELD_START_LOCK_DIRECTORY}")"
    HELD_START_LOCK_DIRECTORY=""
    ensure_path_not_symlink "${lock_path}" "job start lock"
    recorded_pid="$(read_first_line_or_empty "${lock_path}/starter_pid")"
    recorded_identity="$(read_first_line_or_empty "${lock_path}/starter_identity")"
    if [[ "${recorded_pid}" == "${HELD_START_LOCK_STARTER_PID}" &&
      "${recorded_identity}" == "${HELD_START_LOCK_STARTER_IDENTITY}" ]]; then
      rm -rf "${lock_path}"
    fi
  fi
  HELD_START_LOCK_STARTER_PID=""
  HELD_START_LOCK_STARTER_IDENTITY=""
}

restore_detached_lock() {
  local lock_path="$1" detached_path="$2"
  # Restoring can only fail if a third starter claimed the empty slot, which
  # leaves that starter holding the lock; discard rather than nest one lock
  # directory inside another. Reclaimers run under the reclaim mutex
  # (acquire_start_lock), so in that path the observed holder cannot be replaced
  # by a live lock and this restore never runs against one -- it remains only for
  # a caller invoking discard directly with a mismatched pid.
  if [[ -e "${lock_path}" ]] || ! mv "${detached_path}" "${lock_path}" 2>/dev/null; then
    rm -rf "${detached_path}"
  fi
}

# Clear a start lock that records `expected_starter_pid`, so a new starter may
# claim it. Callers in the runner hold the reclaim mutex, which guarantees the
# lock still records the stale holder they observed; the atomic rename-aside and
# pid recheck below add per-call safety so a direct caller that names the wrong
# pid puts the lock back untouched and reports failure rather than clearing a
# lock it does not own.
discard_start_lock_held_by() {
  local directory="$1" expected_starter_pid="$2" lock_path detached_path
  lock_path="$(start_lock_path "${directory}")"
  detached_path="${lock_path}.detached.$$"
  ensure_path_not_symlink "${lock_path}" "job start lock"
  rm -rf "${detached_path}"
  mv "${lock_path}" "${detached_path}" 2>/dev/null || return 1
  if [[ "$(read_first_line_or_empty "${detached_path}/starter_pid")" == "${expected_starter_pid}" ]]; then
    rm -rf "${detached_path}"
    return 0
  fi
  restore_detached_lock "${lock_path}" "${detached_path}"
  return 1
}

# Clear a dead starter's incomplete lock. The rename protects the decision from
# competing reclaimers, and the metadata recheck protects a live starter that
# completed publication after the caller's first observation.
discard_incomplete_start_lock() {
  local directory="$1" lock_path detached_path holder_pid holder_identity
  lock_path="$(start_lock_path "${directory}")"
  detached_path="${lock_path}.detached.$$"
  ensure_path_not_symlink "${lock_path}" "job start lock"
  rm -rf "${detached_path}"
  mv "${lock_path}" "${detached_path}" 2>/dev/null || return 1
  holder_pid="$(read_first_line_or_empty "${detached_path}/starter_pid")"
  holder_identity="$(read_first_line_or_empty "${detached_path}/starter_identity")"
  if [[ -z "${holder_pid}" || -z "${holder_identity}" ]]; then
    rm -rf "${detached_path}"
    return 0
  fi
  restore_detached_lock "${lock_path}" "${detached_path}"
  return 1
}

# Remove only the reclaim mutex whose complete owner metadata the caller
# observed. Atomic rename plus the metadata recheck prevents a stale verdict
# from deleting a different holder's mutex.
discard_start_lock_reclaim_held_by() {
  local directory="$1" expected_pid="$2" expected_identity="$3" reclaim_path detached_path
  reclaim_path="$(start_lock_reclaim_path "${directory}")"
  detached_path="${reclaim_path}.detached.$$"
  ensure_path_not_symlink "${reclaim_path}" "job start lock reclaim"
  rm -rf "${detached_path}"
  mv "${reclaim_path}" "${detached_path}" 2>/dev/null || return 1
  if [[ "$(read_first_line_or_empty "${detached_path}/starter_pid")" == "${expected_pid}" &&
    "$(read_first_line_or_empty "${detached_path}/starter_identity")" == "${expected_identity}" ]]; then
    rm -rf "${detached_path}"
    return 0
  fi
  restore_detached_lock "${reclaim_path}" "${detached_path}"
  return 1
}

# Clear a reclaim mutex whose owner died before publishing both metadata files.
# The pre-claim record lets the ownership layer distinguish it from a live
# publication window before calling this state-only helper.
discard_incomplete_start_lock_reclaim() {
  local directory="$1" reclaim_path detached_path holder_pid holder_identity
  reclaim_path="$(start_lock_reclaim_path "${directory}")"
  detached_path="${reclaim_path}.detached.$$"
  ensure_path_not_symlink "${reclaim_path}" "job start lock reclaim"
  rm -rf "${detached_path}"
  mv "${reclaim_path}" "${detached_path}" 2>/dev/null || return 1
  holder_pid="$(read_first_line_or_empty "${detached_path}/starter_pid")"
  holder_identity="$(read_first_line_or_empty "${detached_path}/starter_identity")"
  if [[ -z "${holder_pid}" || -z "${holder_identity}" ]]; then
    rm -rf "${detached_path}"
    return 0
  fi
  restore_detached_lock "${reclaim_path}" "${detached_path}"
  return 1
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
  local option_name="$1" option_value="$2"
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
  local path="$1" line
  ensure_path_not_symlink "${path}" "job metadata path"
  if [[ -f "${path}" ]]; then
    while IFS= read -r line || [[ -n "${line}" ]]; do
      printf '%s\n' "${line}"
    done < "${path}"
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
