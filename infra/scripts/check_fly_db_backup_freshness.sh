#!/usr/bin/env bash
# Local, falsifiable freshness gate for the live Fly production DB backup in
# Backblaze B2.
#
# Answers one question the operator can prove: is the newest canonical dump
# object under the Fly prefix younger than --max-age-hours? This script is a
# *consumer* of the B2 object contract owned by b2_backup_lib.sh. It never
# restates the bucket, the Fly prefix, the canonical dump object naming scheme, or the
# UTC timestamp format, and it never writes to B2: no upload, no prune, no
# delete.
#
# Freshness is derived from the canonical filename timestamp only. The object's
# B2 modification time is printed as supplemental listing evidence but is never
# authoritative, so a re-upload or copy that refreshes an object's mtime can
# never make an older dump filename read as fresh.
#
# Exit 0 only when a fresh dump is proven. Every indeterminate condition
# (rclone failure, empty prefix, a non-canonical object under the prefix, an
# unparseable clock) fails closed with a non-zero exit, so a broken or missing
# backup can never read as healthy. See
# docs/howto/operations/db-backup-runbook.md.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/scripts/b2_backup_lib.sh
source "${script_dir}/b2_backup_lib.sh"

usage() {
  echo "usage: $(basename "$0") --max-age-hours <positive integer hours>" >&2
}

max_age_hours=""
while (($# > 0)); do
  case "$1" in
    --max-age-hours)
      if (($# < 2)); then
        echo "ERROR: --max-age-hours requires a value" >&2
        usage
        exit 2
      fi
      max_age_hours="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unrecognized argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${max_age_hours}" ]]; then
  echo "ERROR: --max-age-hours is required" >&2
  usage
  exit 2
fi
if [[ ! "${max_age_hours}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --max-age-hours must be a positive integer number of hours: ${max_age_hours}" >&2
  exit 2
fi
max_age_hours=$((10#${max_age_hours}))
if ((max_age_hours <= 0)); then
  echo "ERROR: --max-age-hours must be a positive integer number of hours: ${max_age_hours}" >&2
  exit 2
fi

# The reference clock is injectable so the gate is deterministically testable;
# unset, it is the real wall clock. Anything that is not a Unix epoch fails
# closed rather than silently reading as "now".
now_epoch="${CIVIBUS_BACKUP_CLOCK_EPOCH:-$(date -u +%s)}"
if [[ ! "${now_epoch}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: reference clock is not a Unix epoch: ${now_epoch}" >&2
  exit 1
fi

b2_backup_configure_rclone_env

prefix_path="$(b2_backup_fly_prefix_path)"

# List only the Fly prefix, never the bucket root. `t;p` gives the object's B2
# modification time and its path, one row per object.
if ! listing="$(b2_backup_rclone lsf --format "tp" "${prefix_path}")"; then
  echo "ERROR: could not list the Fly backup prefix (${prefix_path}); failing closed" >&2
  exit 1
fi

newest_timestamp=""
newest_name=""
newest_mtime=""
while IFS= read -r row; do
  [[ -z "${row}" ]] && continue
  if [[ "${row}" != *";"* ]]; then
    echo "ERROR: object listing row is missing the expected mtime/path separator; failing closed: ${row}" >&2
    exit 1
  fi
  object_mtime="${row%%;*}"
  object_name="${row#*;}"
  # Every object under the Fly prefix must be a canonical dump. A non-canonical
  # name is a broken-contract signal, so reject loudly rather than skip it and
  # risk answering "fresh" off a stale sibling.
  if ! object_timestamp="$(b2_backup_dump_object_timestamp "${object_name}" 2>/dev/null)"; then
    echo "ERROR: object under the Fly prefix is not a canonical backup dump; failing closed: ${object_name}" >&2
    exit 1
  fi
  # Canonical timestamps sort chronologically, so lexical max selects the newest.
  if [[ -z "${newest_timestamp}" || "${object_timestamp}" > "${newest_timestamp}" ]]; then
    newest_timestamp="${object_timestamp}"
    newest_name="${object_name}"
    newest_mtime="${object_mtime}"
  fi
done <<<"${listing}"

if [[ -z "${newest_timestamp}" ]]; then
  echo "ERROR: no backup objects found under the Fly prefix (${prefix_path}); cannot prove freshness" >&2
  exit 1
fi

if ! newest_epoch="$(b2_backup_utc_timestamp_to_epoch "${newest_timestamp}")"; then
  echo "ERROR: newest Fly DB backup has an invalid filename timestamp; failing closed: ${newest_name}" >&2
  exit 1
fi
age_seconds=$((now_epoch - newest_epoch))
max_age_seconds=$((max_age_hours * 3600))

if ((age_seconds < 0)); then
  echo "ERROR: newest Fly DB backup has a future filename timestamp; failing closed: ${newest_name}" >&2
  exit 1
fi

age_hours=$((age_seconds / 3600))
evidence="newest Fly DB backup ${newest_name} is ${age_hours}h old (B2 mtime ${newest_mtime}); threshold ${max_age_hours}h"

if ((age_seconds <= max_age_seconds)); then
  echo "OK: ${evidence}"
  exit 0
fi

echo "STALE: ${evidence}" >&2
exit 1
