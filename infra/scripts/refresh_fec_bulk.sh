#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

# FEC_BULK_CYCLE is required — tells which election cycle to download.
if [[ -z "${FEC_BULK_CYCLE:-}" ]]; then
  echo "FEC_BULK_CYCLE must be set in .env or the shell environment" >&2
  exit 1
fi

export FEC_BULK_DIR="${FEC_BULK_DIR:-/var/lib/civibus/fec/bulk/${FEC_BULK_CYCLE}}"

mkdir -p "${FEC_BULK_DIR}"

cd "${repo_root}"

make download-fec-bulk
exec make ingest-fec-bulk
