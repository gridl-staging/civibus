#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
priority_wrapper="${repo_root}/infra/scripts/refresh_priority.sh"
fec_bulk_wrapper="${repo_root}/infra/scripts/refresh_fec_bulk.sh"
logrotate_source="${repo_root}/infra/scripts/civibus-refresh-logrotate.conf"
logrotate_target="/etc/logrotate.d/civibus-refresh"
log_dir="/var/log/civibus"

if [[ ! -x "${priority_wrapper}" ]]; then
  echo "Missing executable wrapper: ${priority_wrapper}" >&2
  exit 1
fi

if [[ ! -x "${fec_bulk_wrapper}" ]]; then
  echo "Missing executable wrapper: ${fec_bulk_wrapper}" >&2
  exit 1
fi

if [[ ! -f "${logrotate_source}" ]]; then
  echo "Missing logrotate source: ${logrotate_source}" >&2
  exit 1
fi

mkdir -p "${log_dir}"

existing_crontab="$(mktemp -t civibus-refresh-existing.XXXXXX)"
next_crontab="$(mktemp -t civibus-refresh-next.XXXXXX)"
trap 'rm -f "${existing_crontab}" "${next_crontab}"' EXIT

crontab -l >"${existing_crontab}" 2>/dev/null || true
grep -v "infra/scripts/refresh_priority.sh" "${existing_crontab}" | grep -v "infra/scripts/refresh_fec_bulk.sh" >"${next_crontab}" || true

{
  echo "0 */6 * * * bash ${priority_wrapper} >> /var/log/civibus/refresh-priority.log 2>&1"
  echo "0 3 * * * bash ${fec_bulk_wrapper} >> /var/log/civibus/refresh-fec-bulk.log 2>&1"
} >>"${next_crontab}"

crontab "${next_crontab}"
install -m 0644 "${logrotate_source}" "${logrotate_target}"

echo "Installed civibus refresh cron jobs and ${logrotate_target}"
