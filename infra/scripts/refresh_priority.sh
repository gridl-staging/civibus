#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

# CO's TRACER server doesn't send its intermediate SSL cert, so even the
# system CA store can't verify it. The runner passes allow_insecure_tls=True
# for CO; this env var is the second half of the break-glass that enables
# the retry with verify=False.
export CIVIBUS_ALLOW_INSECURE_TLS_RETRY="1"

refresh_cf_args=""

if [[ -n "${NC_COMMITTEE_DOCS_PATH:-}" ]]; then
  resolved_nc_committee_docs_path="${NC_COMMITTEE_DOCS_PATH}"
  if [[ "${resolved_nc_committee_docs_path}" != /* ]]; then
    resolved_nc_committee_docs_path="${repo_root}/${resolved_nc_committee_docs_path}"
  fi

  if [[ ! -f "${resolved_nc_committee_docs_path}" ]]; then
    echo "NC_COMMITTEE_DOCS_PATH does not exist: ${resolved_nc_committee_docs_path}" >&2
    exit 1
  fi

  # Preserve exact argument boundaries when passing optional paths through Make.
  printf -v refresh_cf_args '%q ' --nc-committee-docs-path "${resolved_nc_committee_docs_path}"
  refresh_cf_args="${refresh_cf_args% }"
fi

cd "${repo_root}"

exec make refresh-cf-priority "REFRESH_CF_ARGS=${refresh_cf_args% }"
