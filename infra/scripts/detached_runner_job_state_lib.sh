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
