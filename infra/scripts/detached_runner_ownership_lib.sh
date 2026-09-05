#!/usr/bin/env bash
# Process observation and ownership verdicts for infra/scripts/detached_runner.sh.
#
# Sourced (not executed) by detached_runner.sh, layered directly on
# detached_runner_job_state_lib.sh, through which it reads recorded PIDs and
# identities. Single owner of the rule deciding whether a recorded PID is still
# a process of ours, of the polling cadence every wait in the runner uses, and
# of the group-leadership check `stop` adds on top of that identity verdict.
#
# Cross-file globals make this library lintable only together with the runner
# that sources it, and only under --check-sourced: without that flag a sourced
# file is read for its definitions but never reported on. The lint gate is
# `shellcheck -x --check-sourced infra/scripts/detached_runner.sh`, run by
# tests/infra/test_detached_runner.py so the flag cannot quietly regress.

FAST_POLL_INTERVAL_SECONDS=0.05
DEFAULT_POLL_INTERVAL_SECONDS=0.1
STOP_POLLS_PER_SECOND=10
DEFAULT_STOP_GRACE_SECONDS=5
WRAPPER_PGID_ATTEMPTS=40
STABLE_PROCESS_IDENTITY_ATTEMPTS=5
# 80 fast polls is a 4.0s approval window, comfortably above start's normal
# post-ready approval path: 40 wrapper-PGID polls + 5 stable-identity polls
# consume at most 2.25s before the small adoption metadata writes.
WRAPPER_LAUNCH_APPROVAL_ATTEMPTS=80
PID_EXIT_ATTEMPTS=10

observed_process_identity() {
  local pid="$1"
  ps -p "${pid}" -o command= 2>/dev/null || true
}

observed_process_pgid() {
  local pid="$1" observed_pgid
  observed_pgid="$(ps -p "${pid}" -o pgid= 2>/dev/null || true)"
  observed_pgid="${observed_pgid//[[:space:]]/}"
  printf '%s\n' "${observed_pgid}"
}

poll_until() {
  local attempts="$1" interval_seconds="$2"
  shift 2
  local attempt
  for (( attempt = 0; attempt < attempts; attempt++ )); do
    if "$@"; then
      return 0
    fi
    sleep "${interval_seconds}"
  done
  return 1
}

wrapper_pgid_is_leader() {
  local wrapper_pid="$1"
  OBSERVED_WRAPPER_PGID=""
  OBSERVED_WRAPPER_PGID="$(observed_process_pgid "${wrapper_pid}")"
  [[ "${OBSERVED_WRAPPER_PGID}" == "${wrapper_pid}" ]]
}

wait_for_wrapper_pgid() {
  poll_until "${WRAPPER_PGID_ATTEMPTS}" "${FAST_POLL_INTERVAL_SECONDS}" wrapper_pgid_is_leader "$1"
}

# Read a PID's command identity, returning it only once two consecutive
# observations agree. A freshly forked process is briefly observable under its
# parent's command line, so a single read taken right after launch can record an
# identity the process never keeps, failing every later check against it.
stable_process_identity() {
  local pid="$1"
  local observed_identity="" previous_identity=""
  local attempt
  for (( attempt = 0; attempt < STABLE_PROCESS_IDENTITY_ATTEMPTS; attempt++ )); do
    observed_identity="$(observed_process_identity "${pid}")"
    if [[ -n "${observed_identity}" ]]; then
      if [[ "${observed_identity}" == "${previous_identity}" ]]; then
        printf '%s\n' "${observed_identity}"
        return 0
      fi
      previous_identity="${observed_identity}"
    fi
    sleep "${FAST_POLL_INTERVAL_SECONDS}"
  done
  if [[ -n "${previous_identity}" ]]; then
    printf '%s\n' "${previous_identity}"
    return 0
  fi
  return 1
}

# The single owner of the runner's ownership rule: a PID is ours only while the
# process it names still carries the identity recorded for it, because PID
# numbers are recycled and a bare liveness probe would also succeed for whatever
# inherited the number. Prints "match", "mismatch" (live, but the number now
# names some other process), or "gone". Callers that must act differently on
# "gone" than on "mismatch" branch on this verdict rather than re-observing.
pid_identity_verdict() {
  local pid="$1" recorded_identity="$2" observed_identity
  observed_identity="$(observed_process_identity "${pid}")"
  if [[ -z "${observed_identity}" ]]; then
    printf 'gone\n'
  elif [[ "${observed_identity}" == "${recorded_identity}" ]]; then
    printf 'match\n'
  else
    printf 'mismatch\n'
  fi
}

pid_identity_matches() {
  [[ "$(pid_identity_verdict "$1" "$2")" == "match" ]]
}

pid_has_exited() {
  ! pid_identity_matches "$1" "$2"
}

wait_for_pid_exit() {
  local pid="$1" recorded_identity="$2"
  poll_until "${PID_EXIT_ATTEMPTS}" "${DEFAULT_POLL_INTERVAL_SECONDS}" pid_has_exited "${pid}" "${recorded_identity}"
}

process_group_has_no_members() {
  local pgid="$1"
  ! kill -0 "-${pgid}" 2>/dev/null
}

wait_for_process_group_exit() {
  local pgid="$1" attempts="$2"
  poll_until "${attempts}" "${DEFAULT_POLL_INTERVAL_SECONDS}" process_group_has_no_members "${pgid}"
}

# The canonical verdict on a recorded process, shared by every command that must
# decide whether job metadata still describes a live process of ours. A job
# records exactly two -- the wrapper the runner launched and that wrapper's
# child -- and this is the one place mapping a role onto its metadata files.
# Publishes the recorded PID even when ownership cannot be proven, so callers can
# name it in a refusal, plus the reason the verdict came out negative.
recorded_process_identity_matches() {
  local directory="$1" role="$2" pid_file identity_file pid recorded_identity
  RECORDED_PROCESS_PID=""
  RECORDED_PROCESS_VERDICT=""
  RECORDED_PROCESS_REFUSAL_REASON=""
  case "${role}" in
    wrapper) pid_file="pid"; identity_file="process_identity" ;;
    child) pid_file="child_pid"; identity_file="child_process_identity" ;;
    *) fail "unknown recorded process role: ${role}" ;;
  esac

  pid="$(read_first_line_or_empty "${directory}/${pid_file}")"
  recorded_identity="$(read_file_or_empty "${directory}/${identity_file}")"
  RECORDED_PROCESS_PID="${pid}"
  if [[ -z "${pid}" || -z "${recorded_identity}" ]]; then
    RECORDED_PROCESS_REFUSAL_REASON="incomplete process metadata"
    return 1
  fi

  RECORDED_PROCESS_VERDICT="$(pid_identity_verdict "${pid}" "${recorded_identity}")"
  case "${RECORDED_PROCESS_VERDICT}" in
    match) return 0 ;;
    gone) RECORDED_PROCESS_REFUSAL_REASON="${role} PID ${pid} is no longer observable" ;;
    *) RECORDED_PROCESS_REFUSAL_REASON="process identity mismatch for ${role} PID ${pid}" ;;
  esac
  return 1
}

# Resolve the process group this job owns, or refuse. A group signal reaches
# every descendant, so it is only safe once the recorded wrapper PID still
# carries its recorded identity AND still leads the recorded process group.
# Anything less means the metadata no longer describes live processes, and the
# runner must signal nothing rather than guess at a target. Both halves reuse the
# shared checks -- the recorded-process identity verdict and the same leadership
# observation launch makes -- so only the comparison against the recorded `pgid`
# is stop-specific, and `status` and `wait` never depend on that stop-only file.
verified_owned_process_group() {
  local directory="$1" pid recorded_pgid
  VERIFIED_STOP_PGID=""
  STOP_REFUSAL_REASON=""

  recorded_pgid="$(read_first_line_or_empty "${directory}/pgid")"
  if [[ -z "${recorded_pgid}" ]]; then
    STOP_REFUSAL_REASON="incomplete process metadata"
    return 1
  fi
  if ! recorded_process_identity_matches "${directory}" wrapper; then
    STOP_REFUSAL_REASON="${RECORDED_PROCESS_REFUSAL_REASON}"
    return 1
  fi

  pid="${RECORDED_PROCESS_PID}"
  if ! wrapper_pgid_is_leader "${pid}" || [[ "${recorded_pgid}" != "${pid}" ]]; then
    STOP_REFUSAL_REASON="wrapper PID ${pid} no longer leads recorded process group ${recorded_pgid} (observed PGID: ${OBSERVED_WRAPPER_PGID:-unobservable})"
    return 1
  fi

  VERIFIED_STOP_PGID="${OBSERVED_WRAPPER_PGID}"
}

# Liveness for a recorded role: the shared identity verdict plus the rule that a
# terminal receipt settles the job for good -- once `exit_code` exists the job
# has reported its outcome and no live PID may reopen it. Leaves the recorded
# PID and verdict published by the identity seam in place for the caller; on the
# settled-job path it publishes the same empty set the identity seam would, so a
# caller never reads a verdict belonging to some earlier call. That path refuses
# nothing -- a job that reported its outcome is finished, not unverifiable -- so
# the refusal reason is cleared rather than filled in.
recorded_process_is_alive() {
  local directory="$1" role="$2"
  RECORDED_PROCESS_PID=""
  RECORDED_PROCESS_VERDICT=""
  RECORDED_PROCESS_REFUSAL_REASON=""
  [[ ! -f "${directory}/exit_code" ]] || return 1
  recorded_process_identity_matches "${directory}" "${role}"
}

# The wrapper is the job: `status` and `wait` call a job alive only while the
# recorded wrapper PID is still provably ours. A surviving child of a dead
# wrapper is an orphan, not a running job, and belongs to the guard below.
job_is_alive() {
  recorded_process_is_alive "$1" wrapper
}

# One wording for every way the start lock is unavailable, because the operator
# is left the same job in each case: another same-name start owns the job
# directory right now, so wait for it or retry.
CONCURRENT_START_REFUSAL_REASON="another start for this job holds the start lock; wait for it to finish or retry"

# The start lock's holder policy: claim the lock, and on failure decide whether
# the starter recorded in it is still alive. The directory mechanics belong to
# detached_runner_job_state_lib.sh; only this verdict is process observation,
# and it is this library's ordinary ownership rule -- a recorded PID is ours
# only while it still carries its recorded identity -- so a recycled PID number
# cannot keep a dead starter's lock alive.
#
# A lock whose starter is dead is RECLAIMED rather than refused forever. The
# runner releases the lock from an EXIT trap, so only a starter killed outright
# can leave one behind; a lock nobody could ever clear would wedge that job name
# until an operator deleted the directory by hand, which is a worse operator
# outcome than the interleaved start the lock exists to prevent. A claimant now
# publishes its PID and identity outside start.lock before mkdir, so an
# incomplete lock is refused while that claimant is alive and reclaimed after
# it dies without guessing from absent in-lock metadata.
#
# Release is `release_start_lock` in the job-state library, which knows what
# this process claimed.
incomplete_start_lock_has_live_claimant() {
  local directory="$1" ignored_pid="${2:-}" ignored_identity="${3:-}"
  local claim_path claimant_pid claimant_identity
  collect_start_lock_claim_paths "${directory}"
  for claim_path in "${START_LOCK_CLAIM_PATHS[@]}"; do
    claimant_pid="$(start_lock_claim_starter_pid "${claim_path}")"
    claimant_identity="$(start_lock_claim_starter_identity "${claim_path}")"
    if [[ "${claimant_pid}" == "${ignored_pid}" && "${claimant_identity}" == "${ignored_identity}" ]]; then
      continue
    fi
    if [[ -n "${claimant_pid}" ]]; then
      if [[ -n "${claimant_identity}" ]] && pid_identity_matches "${claimant_pid}" "${claimant_identity}"; then
        return 0
      fi
      # A claimant whose command identity could not be observed retains this
      # record until release. Bare PID liveness is deliberately fail-closed:
      # PID reuse may delay recovery, but it cannot displace a live starter.
      if [[ -z "${claimant_identity}" ]] && kill -0 "${claimant_pid}" 2>/dev/null; then
        return 0
      fi
    fi
  done
  return 1
}

# Claim the reclaim mutex or recover one whose recorded owner is no longer the
# same live process. The contender's pre-claim record remains visible while it
# examines an incomplete mutex, so it ignores only its own record and refuses
# if the killed holder is actually still publishing ownership metadata.
acquire_start_lock_reclaim() {
  local directory="$1" starter_pid="$2" starter_identity="$3"
  local holder_pid holder_identity claim_rc
  claim_start_lock_reclaim "${directory}" "${starter_pid}" "${starter_identity}" && return 0

  holder_pid="$(start_lock_reclaim_starter_pid "${directory}")"
  holder_identity="$(start_lock_reclaim_starter_identity "${directory}")"
  if [[ -z "${holder_pid}" || -z "${holder_identity}" ]]; then
    if incomplete_start_lock_has_live_claimant "${directory}" "${starter_pid}" "${starter_identity}" ||
      ! discard_incomplete_start_lock_reclaim "${directory}"; then
      clear_active_start_lock_claim
      return 1
    fi
  elif pid_identity_matches "${holder_pid}" "${holder_identity}" ||
    ! discard_start_lock_reclaim_held_by "${directory}" "${holder_pid}" "${holder_identity}"; then
    clear_active_start_lock_claim
    return 1
  fi

  claim_start_lock_reclaim "${directory}" "${starter_pid}" "${starter_identity}"
  claim_rc=$?
  clear_active_start_lock_claim
  return "${claim_rc}"
}

acquire_start_lock() {
  local directory="$1" starter_pid="$2" starter_identity claim_rc
  starter_identity="$(observed_process_identity "${starter_pid}")"
  claim_start_lock "${directory}" "${starter_pid}" "${starter_identity}" && return 0

  # The lock is held. Deciding whether its holder is stale, and clearing it if
  # so, runs under the reclaim mutex. Serializing reclaimers is what makes the
  # clear safe: it guarantees the lock a reclaimer moves aside is still the stale
  # one it observed, so a reclaimer can never move a live replacement lock aside
  # (created in the gap after another reclaimer cleared the original) and expose
  # a claimable vacancy. A contender that finds another reclaimer already
  # deciding refuses rather than reclaiming.
  acquire_start_lock_reclaim "${directory}" "${starter_pid}" "${starter_identity}" || return 1
  if ! reclaim_stale_start_lock "${directory}"; then
    release_start_lock_reclaim
    return 1
  fi
  # The stale lock is cleared. Re-claim under the still-held reclaim mutex; a
  # bare fast-path claimer may have taken the freed path first, in which case
  # this claim fails and we refuse -- one holder, never two.
  claim_start_lock "${directory}" "${starter_pid}" "${starter_identity}"
  claim_rc=$?
  release_start_lock_reclaim
  return "${claim_rc}"
}

# Under the reclaim mutex, decide whether the held start lock is stale and clear
# it if so. Returns 0 when the lock path is now free for the caller to claim, 1
# when the holder is live (or an incomplete claim's claimant is live) and the
# start must be refused. The holder observed here cannot change while this runs:
# the mutex excludes other reclaimers, and a fresh claim needs the path this
# holder still occupies -- so the lock cleared here is provably the one observed.
reclaim_stale_start_lock() {
  local directory="$1" holder_pid holder_identity
  holder_pid="$(start_lock_starter_pid "${directory}")"
  holder_identity="$(start_lock_starter_identity "${directory}")"
  if [[ -z "${holder_pid}" || -z "${holder_identity}" ]]; then
    incomplete_start_lock_has_live_claimant "${directory}" && return 1
    discard_incomplete_start_lock "${directory}"
    return "$?"
  fi
  pid_identity_matches "${holder_pid}" "${holder_identity}" && return 1
  discard_start_lock_held_by "${directory}" "${holder_pid}"
}

# The duplicate-start guard: `start` refuses while the recorded child of a dead
# wrapper is still around, because relaunching would put two jobs on the same
# output. A child the runner cannot clear is refused under one of two verdicts,
# which share a single refusal wording because they leave the operator the same
# job: an unverifiable live PID is no more evidence the old run ended than a
# matching one is.
recorded_child_blocks_start() {
  RECORDED_CHILD_PID=""
  RECORDED_CHILD_REFUSAL_REASON=""
  if recorded_process_is_alive "$1" child; then
    RECORDED_CHILD_PID="${RECORDED_PROCESS_PID}"
    RECORDED_CHILD_REFUSAL_REASON="surviving child PID ${RECORDED_CHILD_PID} is still recorded and alive; terminate that PID or remove the stale job directory before retrying"
    return 0
  fi
  [[ -n "${RECORDED_PROCESS_PID}" ]] || return 1

  # "mismatch" already proved the PID is live under a foreign identity. Only an
  # empty verdict -- incomplete metadata, so nothing was ever observed -- may
  # observe now; a "gone" verdict is settled, and re-observing it would let a
  # recycled PID number reopen a job the identity check already closed.
  if [[ "${RECORDED_PROCESS_VERDICT}" == "mismatch" ]] ||
    { [[ -z "${RECORDED_PROCESS_VERDICT}" ]] && [[ -n "$(observed_process_identity "${RECORDED_PROCESS_PID}")" ]]; }; then
    RECORDED_CHILD_PID="${RECORDED_PROCESS_PID}"
    RECORDED_CHILD_REFUSAL_REASON="recorded child PID ${RECORDED_CHILD_PID} is still observable but its identity cannot be verified; inspect that PID or remove the stale job directory before retrying"
    return 0
  fi
  return 1
}
