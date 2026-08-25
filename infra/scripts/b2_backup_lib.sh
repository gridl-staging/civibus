#!/usr/bin/env bash
# Shared Backblaze B2 object contract for civibus database backups.
#
# Sourced (not executed) alongside infra/scripts/env_lib.sh by
# backup_to_b2.sh (parked Hetzner path) and backup_fly_db_to_b2.sh (live Fly
# path). This file is the single owner of the bucket, the per-deployment
# object prefixes, the dump object naming scheme, the rclone remote
# configuration, the retention window, and prune scoping. Callers supply
# database coordinates and credentials; they never restate any of the facts
# below.
#
# See docs/howto/operations/db-backup-runbook.md.

if [[ -n "${B2_BACKUP_LIB_SOURCED:-}" ]]; then
  return 0
fi
B2_BACKUP_LIB_SOURCED=1

# rclone remote name. It exists only inside this library and its callers; no
# rclone.conf is involved, the remote is configured entirely from env vars.
B2_BACKUP_REMOTE_NAME="b2"
B2_BACKUP_DEFAULT_BUCKET="civibus-db-backups"
B2_BACKUP_DEFAULT_RETENTION_DAYS="7"

# Live Fly production dumps live under their own prefix. Prunes scoped to this
# prefix therefore cannot reach the historical root-prefix Hetzner dumps.
B2_BACKUP_FLY_DB_PREFIX="fly/civibus-db/"

# The parked Hetzner cron path writes to the bucket root, which predates the
# prefixed layout and must keep its object paths for restore continuity.
B2_BACKUP_HETZNER_DB_PREFIX=""

# Canonical dump object name: db-<UTC timestamp>.dump
B2_BACKUP_DUMP_NAME_PREFIX="db-"
B2_BACKUP_DUMP_NAME_EXTENSION="dump"
B2_BACKUP_UTC_TIMESTAMP_PATTERN='[0-9]{8}T[0-9]{6}Z'
B2_BACKUP_UTC_TIMESTAMP_FORMAT='+%Y%m%dT%H%M%SZ'
B2_BACKUP_DUMP_NAME_PATTERN="^${B2_BACKUP_DUMP_NAME_PREFIX}(${B2_BACKUP_UTC_TIMESTAMP_PATTERN})[.]${B2_BACKUP_DUMP_NAME_EXTENSION}$"

b2_backup_bucket() {
  printf '%s\n' "${B2_BUCKET:-${B2_BACKUP_DEFAULT_BUCKET}}"
}

b2_backup_retention_days() {
  local retention_days="${BACKUP_RETENTION_DAYS:-${B2_BACKUP_DEFAULT_RETENTION_DAYS}}"

  if [[ ! "${retention_days}" =~ ^0*[1-9][0-9]*$ ]]; then
    echo "Backup retention days must be a positive integer: ${retention_days}" >&2
    return 1
  fi

  printf '%s\n' "${retention_days}"
}

b2_backup_new_utc_timestamp() {
  date -u "${B2_BACKUP_UTC_TIMESTAMP_FORMAT}"
}

# Validate a canonical UTC timestamp's calendar fields and convert it to Unix
# epoch seconds. Pure arithmetic keeps this portable across GNU and BSD `date`.
# The day count is days-from-civil (Howard Hinnant); 10# forces base-10 so
# zero-padded values such as 08 and 09 are never interpreted as octal.
b2_backup_utc_timestamp_to_epoch() {
  local timestamp="$1"
  local year month day hour minute second days_in_month

  if [[ ! "${timestamp}" =~ ^${B2_BACKUP_UTC_TIMESTAMP_PATTERN}$ ]]; then
    echo "UTC timestamp does not have the canonical shape: ${timestamp}" >&2
    return 1
  fi

  year=$((10#${timestamp:0:4}))
  month=$((10#${timestamp:4:2}))
  day=$((10#${timestamp:6:2}))
  hour=$((10#${timestamp:9:2}))
  minute=$((10#${timestamp:11:2}))
  second=$((10#${timestamp:13:2}))

  if ((month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59)); then
    echo "UTC timestamp has invalid calendar fields: ${timestamp}" >&2
    return 1
  fi

  case "${month}" in
    2)
      days_in_month=28
      if ((year % 400 == 0 || (year % 4 == 0 && year % 100 != 0))); then
        days_in_month=29
      fi
      ;;
    4 | 6 | 9 | 11) days_in_month=30 ;;
    *) days_in_month=31 ;;
  esac
  if ((day < 1 || day > days_in_month)); then
    echo "UTC timestamp has invalid calendar fields: ${timestamp}" >&2
    return 1
  fi

  local civil_year=$((year - (month <= 2 ? 1 : 0)))
  local era=$(((civil_year >= 0 ? civil_year : civil_year - 399) / 400))
  local year_of_era=$((civil_year - era * 400))
  local day_of_year=$(((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1))
  local day_of_era=$((year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year))
  local days_since_epoch=$((era * 146097 + day_of_era - 719468))
  printf '%s\n' "$((days_since_epoch * 86400 + hour * 3600 + minute * 60 + second))"
}

# Build the canonical object name for a dump taken at the given UTC timestamp.
b2_backup_dump_object_name() {
  local timestamp="$1"

  if ! b2_backup_utc_timestamp_to_epoch "${timestamp}" >/dev/null 2>&1; then
    echo "Refusing to build a dump object name from a non-canonical UTC timestamp: ${timestamp}" >&2
    return 1
  fi

  printf '%s%s.%s\n' "${B2_BACKUP_DUMP_NAME_PREFIX}" "${timestamp}" "${B2_BACKUP_DUMP_NAME_EXTENSION}"
}

# Recover the UTC timestamp from a canonical dump object name. Anything that
# does not match the naming contract is an error, never a silently accepted
# object: freshness decisions downstream depend on this parse failing loudly.
b2_backup_dump_object_timestamp() {
  local object_name="$1"
  local timestamp

  if [[ ! "${object_name}" =~ $B2_BACKUP_DUMP_NAME_PATTERN ]]; then
    echo "Object is not a canonical backup dump object name: ${object_name}" >&2
    return 1
  fi

  timestamp="${BASH_REMATCH[1]}"
  if ! b2_backup_utc_timestamp_to_epoch "${timestamp}" >/dev/null 2>&1; then
    echo "Object is not a canonical backup dump object name: ${object_name}" >&2
    return 1
  fi

  printf '%s\n' "${timestamp}"
}

b2_backup_remote_prefix_path() {
  local prefix="$1"

  printf '%s:%s/%s\n' "${B2_BACKUP_REMOTE_NAME}" "$(b2_backup_bucket)" "${prefix}"
}

b2_backup_fly_prefix_path() {
  b2_backup_remote_prefix_path "${B2_BACKUP_FLY_DB_PREFIX}"
}

b2_backup_hetzner_prefix_path() {
  b2_backup_remote_prefix_path "${B2_BACKUP_HETZNER_DB_PREFIX}"
}

b2_backup_dump_path_under_prefix() {
  local prefix_path="$1"
  local timestamp="$2"
  local object_name

  object_name="$(b2_backup_dump_object_name "${timestamp}")" || return 1
  printf '%s%s\n' "${prefix_path}" "${object_name}"
}

b2_backup_fly_dump_path() {
  b2_backup_dump_path_under_prefix "$(b2_backup_fly_prefix_path)" "$1"
}

b2_backup_hetzner_dump_path() {
  b2_backup_dump_path_under_prefix "$(b2_backup_hetzner_prefix_path)" "$1"
}

# Configure the rclone remote entirely from env vars — no
# ~/.config/rclone/rclone.conf is needed on the VM or the Fly machine. The B2
# application key must be scoped to a single bucket with read/write/delete
# caps; no account-wide access.
b2_backup_configure_rclone_env() {
  local remote_env_key

  : "${B2_ACCOUNT_ID:?B2_ACCOUNT_ID must be set in .env or the machine environment}"
  : "${B2_APPLICATION_KEY:?B2_APPLICATION_KEY must be set in .env or the machine environment}"

  remote_env_key="$(printf '%s' "${B2_BACKUP_REMOTE_NAME}" | tr '[:lower:]' '[:upper:]')"
  # "b2" here is the rclone backend type, not the remote name.
  export "RCLONE_CONFIG_${remote_env_key}_TYPE=b2"
  export "RCLONE_CONFIG_${remote_env_key}_ACCOUNT=${B2_ACCOUNT_ID}"
  export "RCLONE_CONFIG_${remote_env_key}_KEY=${B2_APPLICATION_KEY}"
}

# Keep the two credential domains out of subprocesses that do not need them.
# The backup wrappers deliberately run database clients and rclone in one
# process tree, so relying on ordinary environment inheritance would hand each
# tool the other system's destructive credential as well as its own.
b2_backup_run_database_client() {
  env \
    -u B2_ACCOUNT_ID \
    -u B2_APPLICATION_KEY \
    -u FLY_BACKUP_DB_PASSWORD \
    -u PGPASSWORD \
    -u POSTGRES_PASSWORD \
    -u RCLONE_CONFIG_B2_ACCOUNT \
    -u RCLONE_CONFIG_B2_KEY \
    "$@"
}

b2_backup_rclone() {
  env \
    -u B2_ACCOUNT_ID \
    -u B2_APPLICATION_KEY \
    -u FLY_BACKUP_DB_PASSWORD \
    -u PGPASSFILE \
    -u PGPASSWORD \
    -u POSTGRES_PASSWORD \
    rclone "$@"
}

# Upload stdin straight to the remote object. Streaming keeps multi-GB dumps
# off local disk, so no caller needs a spool file or a cleanup path for one.
b2_backup_upload_stream() {
  local remote_path="$1"

  b2_backup_rclone rcat "${remote_path}"
}

b2_backup_delete_object() {
  local remote_path="$1"

  b2_backup_rclone deletefile "${remote_path}"
}

b2_backup_root_dump_include_pattern() {
  printf '/%s*.%s\n' "${B2_BACKUP_DUMP_NAME_PREFIX}" "${B2_BACKUP_DUMP_NAME_EXTENSION}"
}

b2_backup_prune_prefix_path() {
  local prefix_path="$1"
  local include_pattern="${2:-}"
  local retention_days

  retention_days="$(b2_backup_retention_days)" || return 1

  if [[ -n "${include_pattern}" ]]; then
    b2_backup_rclone delete \
      --min-age "${retention_days}d" \
      --include "${include_pattern}" \
      "${prefix_path}"
    return
  fi

  b2_backup_rclone delete --min-age "${retention_days}d" "${prefix_path}"
}

# Prune helpers take no path argument: each deployment's prune scope is fixed
# here. The root-anchored include also prevents the historical Hetzner prune
# from descending into Fly's prefixed objects.
b2_backup_prune_fly_dumps() {
  b2_backup_prune_prefix_path "$(b2_backup_fly_prefix_path)"
}

b2_backup_prune_hetzner_dumps() {
  b2_backup_prune_prefix_path \
    "$(b2_backup_hetzner_prefix_path)" \
    "$(b2_backup_root_dump_include_pattern)"
}
