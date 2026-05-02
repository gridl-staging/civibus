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
refresh_cf_args_parts=()

if [[ -n "${NC_COMMITTEE_DOCS_PATH:-}" ]]; then
  resolved_nc_committee_docs_path="${NC_COMMITTEE_DOCS_PATH}"
  if [[ "${resolved_nc_committee_docs_path}" != /* ]]; then
    resolved_nc_committee_docs_path="${repo_root}/${resolved_nc_committee_docs_path}"
  fi

  if [[ ! -f "${resolved_nc_committee_docs_path}" ]]; then
    echo "NC_COMMITTEE_DOCS_PATH does not exist: ${resolved_nc_committee_docs_path}" >&2
    exit 1
  fi

  refresh_cf_args_parts+=(--nc-committee-docs-path "${resolved_nc_committee_docs_path}")
fi

if [[ -n "${NC_IE_DOCUMENT_INDEX_PATH:-}" ]]; then
  resolved_nc_ie_document_index_path="${NC_IE_DOCUMENT_INDEX_PATH}"
  if [[ "${resolved_nc_ie_document_index_path}" != /* ]]; then
    resolved_nc_ie_document_index_path="${repo_root}/${resolved_nc_ie_document_index_path}"
  fi

  if [[ ! -f "${resolved_nc_ie_document_index_path}" ]]; then
    echo "NC_IE_DOCUMENT_INDEX_PATH does not exist: ${resolved_nc_ie_document_index_path}" >&2
    exit 1
  fi

  refresh_cf_args_parts+=(--nc-ie-document-index-path "${resolved_nc_ie_document_index_path}")
fi

if [[ -n "${NC_CANDIDATE_LISTING_PATH:-}" ]]; then
  resolved_nc_candidate_listing_path="${NC_CANDIDATE_LISTING_PATH}"
  if [[ "${resolved_nc_candidate_listing_path}" != /* ]]; then
    resolved_nc_candidate_listing_path="${repo_root}/${resolved_nc_candidate_listing_path}"
  fi

  if [[ ! -f "${resolved_nc_candidate_listing_path}" ]]; then
    echo "NC_CANDIDATE_LISTING_PATH does not exist: ${resolved_nc_candidate_listing_path}" >&2
    exit 1
  fi

  refresh_cf_args_parts+=(--candidate-listing-path "${resolved_nc_candidate_listing_path}")
fi

if [[ -n "${CIVICS_YEAR_FROM:-}" ]]; then
  if [[ ! "${CIVICS_YEAR_FROM}" =~ ^[0-9]{4}$ ]]; then
    echo "CIVICS_YEAR_FROM must be a 4-digit year: ${CIVICS_YEAR_FROM}" >&2
    exit 1
  fi
  refresh_cf_args_parts+=(--year-from "${CIVICS_YEAR_FROM}")
fi

if (( ${#refresh_cf_args_parts[@]} > 0 )); then
  # Preserve exact argument boundaries when passing optional paths through Make.
  printf -v refresh_cf_args '%q ' "${refresh_cf_args_parts[@]}"
  refresh_cf_args="${refresh_cf_args% }"
fi

cd "${repo_root}"

exec make refresh-cf-priority "REFRESH_CF_ARGS=${refresh_cf_args% }"
