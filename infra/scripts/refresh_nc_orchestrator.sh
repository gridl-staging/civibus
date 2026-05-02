#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

WINDOW_START="$(date -u '+%Y-01-01')"
WINDOW_END="$(date -u '+%Y-%m-%d')"

cd "${repo_root}"

exec uv run --extra download python -m domains.campaign_finance.jurisdictions.states.NC.scraper.cli \
  --data-type transactions \
  --orchestrate-committees \
  --window-start "${WINDOW_START}" \
  --window-end "${WINDOW_END}"
