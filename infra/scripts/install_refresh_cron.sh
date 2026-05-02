#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
priority_wrapper="${repo_root}/infra/scripts/refresh_priority.sh"
fec_bulk_wrapper="${repo_root}/infra/scripts/refresh_fec_bulk.sh"
keel_gates_wrapper="${repo_root}/infra/scripts/run_keel_gates.sh"
nc_orchestrator_wrapper="${repo_root}/infra/scripts/refresh_nc_orchestrator.sh"
backup_wrapper="${repo_root}/infra/scripts/backup_to_b2.sh"
cert_wrapper="${repo_root}/infra/scripts/check_cert_expiry.sh"
logrotate_source="${repo_root}/infra/scripts/civibus-refresh-logrotate.conf"
logrotate_target="/etc/logrotate.d/civibus-refresh"
log_dir="/var/log/civibus"

if [[ ! -f "${priority_wrapper}" ]]; then
  echo "Missing executable wrapper: ${priority_wrapper}" >&2
  exit 1
fi

if [[ ! -f "${fec_bulk_wrapper}" ]]; then
  echo "Missing executable wrapper: ${fec_bulk_wrapper}" >&2
  exit 1
fi

if [[ ! -f "${keel_gates_wrapper}" ]]; then
  echo "Missing executable wrapper: ${keel_gates_wrapper}" >&2
  exit 1
fi

if [[ ! -f "${nc_orchestrator_wrapper}" ]]; then
  echo "Missing executable wrapper: ${nc_orchestrator_wrapper}" >&2
  exit 1
fi

if [[ ! -f "${backup_wrapper}" ]]; then
  echo "Missing executable wrapper: ${backup_wrapper}" >&2
  exit 1
fi

if [[ ! -f "${cert_wrapper}" ]]; then
  echo "Missing executable wrapper: ${cert_wrapper}" >&2
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
grep -v "infra/scripts/refresh_priority.sh" "${existing_crontab}" \
  | grep -v "infra/scripts/refresh_fec_bulk.sh" \
  | grep -v "infra/scripts/run_keel_gates.sh" \
  | grep -v "infra/scripts/refresh_nc_orchestrator.sh" \
  | grep -v "infra/scripts/backup_to_b2.sh" \
  | grep -v "infra/scripts/check_cert_expiry.sh" \
  >"${next_crontab}" || true

# Run the NC committee orchestrator weekly on Sunday 17:00 UTC so it lands
# well before the next day's 02:30 UTC backup window.
{
  echo "0 */6 * * * bash ${priority_wrapper} >> /var/log/civibus/refresh-priority.log 2>&1"
  echo "20 */6 * * * bash ${keel_gates_wrapper} >> /var/log/civibus/keel-gates.log 2>&1"
  echo "0 3 * * * bash ${fec_bulk_wrapper} >> /var/log/civibus/refresh-fec-bulk.log 2>&1"
  echo "0 17 * * 0 bash ${nc_orchestrator_wrapper} >> /var/log/civibus/refresh-nc-orchestrator.log 2>&1"
  echo "30 2 * * * bash ${backup_wrapper} >> /var/log/civibus/backup.log 2>&1"
  echo "0 6 * * * bash ${cert_wrapper} >> /var/log/civibus/check-cert.log 2>&1"
} >>"${next_crontab}"

crontab "${next_crontab}"
install -m 0644 "${logrotate_source}" "${logrotate_target}"

echo "Installed civibus refresh cron jobs and ${logrotate_target}"
