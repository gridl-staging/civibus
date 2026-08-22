#!/usr/bin/env bash
# Stream a pg_dump of the live Fly production Postgres (app civibus-db) to
# Backblaze B2.
#
# Designed to run unattended on the dedicated Fly backup machine. The B2
# object contract (bucket, prefix, object naming, retention, prune scope) is
# owned by b2_backup_lib.sh; this wrapper owns the Fly database coordinates
# and the authentication material only. See
# docs/howto/operations/db-backup-runbook.md.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
# shellcheck source=infra/scripts/b2_backup_lib.sh
source "${script_dir}/b2_backup_lib.sh"

FLY_DB_HOST="${FLY_DB_HOST:-civibus-db.internal}"
FLY_DB_PORT="${FLY_DB_PORT:-5432}"
FLY_DB_NAME="${FLY_DB_NAME:-civibus}"
FLY_DB_USER="${FLY_DB_USER:-civibus}"

escape_pgpass_field() {
  local value="$1"

  case "${value}" in
    *$'\n'* | *$'\r'*)
      echo ".pgpass fields must not contain newline characters" >&2
      return 1
      ;;
  esac

  value="${value//\\/\\\\}"
  value="${value//:/\\:}"
  printf '%s' "${value}"
}

# A restore needs a dump written by a client of the server's own major
# version, so a mismatch has to stop the run before anything is uploaded — an
# unrestorable dump in B2 is worse than a missing one, because the freshness
# checker would read it as a healthy backup.
require_matching_pg_dump_major_version() {
  local client_version_pattern='\(PostgreSQL\)[[:space:]]+([0-9]+)'
  local server_version_pattern='^[[:space:]]*([0-9]+)[[:space:]]*$'
  local client_version_output client_major server_version_output server_version_num server_major

  if ! client_version_output="$(pg_dump --version 2>&1)"; then
    echo "Unable to run local pg_dump: ${client_version_output}" >&2
    return 1
  fi
  if [[ ! "${client_version_output}" =~ $client_version_pattern ]]; then
    echo "Unable to parse local pg_dump version: ${client_version_output}" >&2
    return 1
  fi
  client_major="${BASH_REMATCH[1]}"

  if ! server_version_output="$(psql \
    --host "${FLY_DB_HOST}" \
    --port "${FLY_DB_PORT}" \
    --username "${FLY_DB_USER}" \
    --dbname "${FLY_DB_NAME}" \
    --no-password \
    --tuples-only \
    --no-align \
    --command 'SHOW server_version_num' 2>&1)"; then
    echo "Unable to query the server version from ${FLY_DB_HOST}: ${server_version_output}" >&2
    return 1
  fi
  if [[ ! "${server_version_output}" =~ $server_version_pattern ]]; then
    echo "Indeterminate server version from ${FLY_DB_HOST}: ${server_version_output}" >&2
    return 1
  fi
  # server_version_num encodes major*10000 + minor, e.g. 180002 for 18.2.
  server_version_num="${BASH_REMATCH[1]}"
  server_major=$((server_version_num / 10000))

  if [[ "${client_major}" != "${server_major}" ]]; then
    echo "pg_dump major version ${client_major} does not match server major version ${server_major};" \
      "a version-mismatched dump is not restorable" >&2
    return 1
  fi
}

# Fly machines receive their secrets as machine env vars rather than a repo
# .env file, so only load .env when one is actually present.
env_file="${CIVIBUS_ENV_FILE:-${repo_root}/.env}"
if [[ -f "${env_file}" ]]; then
  load_civibus_env "${env_file}"
fi

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env or the machine environment}"

b2_backup_configure_rclone_env

# libpq authenticates from a private .pgpass only: the password never enters
# argv, and PGPASSWORD/POSTGRES_PASSWORD (exported by load_civibus_env) are
# removed from the environment pg_dump and psql inherit.
pgpass_path="$(mktemp -t civibus-fly-backup-pgpass.XXXXXX)"
remote_path=""
upload_complete=0
cleanup() {
  local exit_status=$?

  rm -f "${pgpass_path}" || true
  if ((exit_status != 0 && upload_complete == 0)) && [[ -n "${remote_path}" ]]; then
    if ! b2_backup_delete_object "${remote_path}"; then
      echo "WARNING: failed to remove incomplete backup object: ${remote_path}" >&2
    fi
  fi
  exit "${exit_status}"
}
trap cleanup EXIT
chmod 600 "${pgpass_path}"
pgpass_host="$(escape_pgpass_field "${FLY_DB_HOST}")"
pgpass_port="$(escape_pgpass_field "${FLY_DB_PORT}")"
pgpass_database="$(escape_pgpass_field "${FLY_DB_NAME}")"
pgpass_user="$(escape_pgpass_field "${FLY_DB_USER}")"
pgpass_password="$(escape_pgpass_field "${POSTGRES_PASSWORD}")"
printf '%s:%s:%s:%s:%s\n' \
  "${pgpass_host}" \
  "${pgpass_port}" \
  "${pgpass_database}" \
  "${pgpass_user}" \
  "${pgpass_password}" \
  >"${pgpass_path}"
export PGPASSFILE="${pgpass_path}"
unset PGPASSWORD POSTGRES_PASSWORD pgpass_password

require_matching_pg_dump_major_version

timestamp="$(b2_backup_new_utc_timestamp)"
remote_path="$(b2_backup_fly_dump_path "${timestamp}")"

echo "[$(date -Iseconds)] starting fly backup -> ${remote_path}"

pg_dump \
    --host "${FLY_DB_HOST}" \
    --port "${FLY_DB_PORT}" \
    --username "${FLY_DB_USER}" \
    --dbname "${FLY_DB_NAME}" \
    --no-password \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
  | b2_backup_upload_stream "${remote_path}"
upload_complete=1

echo "[$(date -Iseconds)] upload complete; pruning dumps older than $(b2_backup_retention_days)d"

b2_backup_prune_fly_dumps

echo "[$(date -Iseconds)] done"
