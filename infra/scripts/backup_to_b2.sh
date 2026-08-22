#!/usr/bin/env bash
# Stream a pg_dump of the civibus production DB to Backblaze B2.
#
# Designed to run from cron on the Hetzner production VM. See
# docs/howto/operations/db-backup-runbook.md for one-time setup and restore
# procedures. The B2 object contract (bucket, object naming, retention, prune
# scope) is owned by b2_backup_lib.sh; this wrapper owns the container-local
# dump path only.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
# shellcheck source=infra/scripts/b2_backup_lib.sh
source "${script_dir}/b2_backup_lib.sh"
load_civibus_env

b2_backup_configure_rclone_env

DB_CONTAINER="${DB_CONTAINER:-infra-db-1}"

timestamp="$(b2_backup_new_utc_timestamp)"
remote_path="$(b2_backup_hetzner_dump_path "${timestamp}")"

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
  | b2_backup_upload_stream "${remote_path}"

echo "[$(date -Iseconds)] upload complete; pruning dumps older than $(b2_backup_retention_days)d"

b2_backup_prune_hetzner_dumps

echo "[$(date -Iseconds)] done"
