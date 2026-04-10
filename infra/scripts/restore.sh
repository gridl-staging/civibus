#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "POSTGRES_PASSWORD must be set in the environment" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: ./infra/scripts/restore.sh <dump-path> --yes-overwrite-local-db" >&2
  exit 1
fi

if [[ "${2:-}" != "--yes-overwrite-local-db" ]]; then
  echo "Restore is destructive. Pass --yes-overwrite-local-db to continue." >&2
  exit 1
fi

dump_path="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
cd "${repo_root}"

exec uv run python infra/scripts/postgres_local.py restore "${dump_path}" --yes-overwrite-local-db
