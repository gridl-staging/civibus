#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

if [[ -z "${ORIGIN:-}" ]]; then
  echo "ORIGIN must be set in .env or the shell environment" >&2
  exit 1
fi

origin_without_scheme="${ORIGIN#*://}"
origin_authority="${origin_without_scheme%%/*}"
export PUBLIC_HOSTNAME="${origin_authority%%:*}"

if [[ -z "${PUBLIC_HOSTNAME}" ]]; then
  echo "Failed to derive PUBLIC_HOSTNAME from ORIGIN=${ORIGIN}" >&2
  exit 1
fi

cd "${repo_root}"

# Alert only when cert lifetime falls below one week.
expiry_threshold_seconds=604800
cert_chain="$(openssl s_client -connect "${PUBLIC_HOSTNAME}:443" -servername "${PUBLIC_HOSTNAME}" </dev/null 2>/dev/null)"

if [[ -z "${cert_chain}" ]]; then
  echo "Failed to retrieve certificate chain for ${PUBLIC_HOSTNAME}:443" >&2
  exit 1
fi

if ! printf '%s\n' "${cert_chain}" | openssl x509 -checkend "${expiry_threshold_seconds}" -noout >/dev/null; then
  cert_enddate="$(printf '%s\n' "${cert_chain}" | openssl x509 -noout -enddate | cut -d= -f2- || true)"
  echo "Certificate for ${PUBLIC_HOSTNAME} expires within 7 days (notAfter=${cert_enddate:-unknown})." >&2
  exit 1
fi

cert_enddate="$(printf '%s\n' "${cert_chain}" | openssl x509 -noout -enddate | cut -d= -f2- || true)"
echo "Certificate for ${PUBLIC_HOSTNAME} is valid for at least 7 days (notAfter=${cert_enddate:-unknown})."
