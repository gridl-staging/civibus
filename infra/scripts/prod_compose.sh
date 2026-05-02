#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

source "${script_dir}/env_lib.sh"
load_civibus_env

origin_without_scheme="${ORIGIN#*://}"
origin_authority="${origin_without_scheme%%/*}"
export PUBLIC_HOSTNAME="${origin_authority%%:*}"

cd "${repo_root}"

# Single self-contained prod compose file — no overlays, no `-f` chain.
# See infra/docker-compose.prod.yml for the Apr 30 incident context.
docker compose --env-file .env -f infra/docker-compose.prod.yml "$@"
