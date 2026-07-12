#!/usr/bin/env bash
# Stream a pg_dump of the civibus production DB to Backblaze B2.
#
# Designed to run from cron on the Hetzner production VM. See
# docs/howto/operations/db-backup-runbook.md for one-time setup and restore
# procedures.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

# B2 credentials required. The application key should be scoped to a single
# bucket (B2_BUCKET) with read/write/delete caps — no account-wide access.
: "${B2_ACCOUNT_ID:?B2_ACCOUNT_ID must be set in .env}"
: "${B2_APPLICATION_KEY:?B2_APPLICATION_KEY must be set in .env}"
B2_BUCKET="${B2_BUCKET:-civibus-db-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DB_CONTAINER="${DB_CONTAINER:-infra-db-1}"

# Configure rclone entirely from env vars — no ~/.config/rclone/rclone.conf
# needed. The remote name "b2" is arbitrary; it only lives in this script.
export RCLONE_CONFIG_B2_TYPE="b2"
export RCLONE_CONFIG_B2_ACCOUNT="${B2_ACCOUNT_ID}"
export RCLONE_CONFIG_B2_KEY="${B2_APPLICATION_KEY}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
remote_path="b2:${B2_BUCKET}/db-${timestamp}.dump"

echo "[$(date -Iseconds)] starting backup -> ${remote_path}"

pgpass_path="/tmp/.pgpass"
cleanup_pgpass() { docker exec "${DB_CONTAINER}" rm -f "${pgpass_path}" 2>/dev/null || true; }
trap cleanup_pgpass EXIT

printf '%s\n' "*:*:${PGDATABASE}:${PGUSER}:${POSTGRES_PASSWORD}" \
  | docker exec -i "${DB_CONTAINER}" sh -c "cat > ${pgpass_path} && chmod 600 ${pgpass_path}"

docker exec -e PGPASSFILE="${pgpass_path}" "${DB_CONTAINER}" pg_dump \
    -U "${PGUSER}" \
    -d "${PGDATABASE}" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
  | rclone rcat "${remote_path}"

echo "[$(date -Iseconds)] upload complete; pruning dumps older than ${RETENTION_DAYS}d"

rclone delete --min-age "${RETENTION_DAYS}d" "b2:${B2_BUCKET}/"

echo "[$(date -Iseconds)] done"
