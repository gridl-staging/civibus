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

echo "[$(date -Iseconds)] starting nc orchestrator refresh"

# Guarded invocation: under `set -euo pipefail`, a bare `cmd; rc=$?` aborts the
# script before the assignment runs when the child fails, which leaves the
# failure marker below unreachable. The `|| run_exit_code=$?` form suppresses
# `-e` for the failure branch so we can record the child's exit and emit the
# operator-visible marker before re-exiting with the same code.
run_exit_code=0
uv run --extra download python -m domains.campaign_finance.jurisdictions.states.NC.scraper.cli \
  --data-type transactions \
  --orchestrate-committees \
  --window-start "${WINDOW_START}" \
  --window-end "${WINDOW_END}" || run_exit_code=$?

if [[ "${run_exit_code}" -eq 0 ]]; then
  echo "[$(date -Iseconds)] nc orchestrator refresh completed"
else
  echo "[$(date -Iseconds)] nc orchestrator refresh failed exit=${run_exit_code}" >&2
fi

exit "${run_exit_code}"
