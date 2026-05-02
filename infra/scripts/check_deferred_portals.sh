#!/usr/bin/env bash
# Lightweight health check for formally deferred portals.
#
# Checks DNS resolution and HTTP reachability for portals that are currently
# deferred due to external blockers (not engineering problems). Appends
# timestamped results to a log file.
#
# Designed to run from Hetzner cron weekly. When a portal recovers, the log
# shows it and the portal can re-enter active work.
#
# Usage:
#   bash infra/scripts/check_deferred_portals.sh

set -euo pipefail

LOG_DIR="/var/log/civibus"
LOG_FILE="${LOG_DIR}/deferred-portal-health.log"
PROBE_TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

check_portal() {
  local name="$1"
  local host="$2"
  local url="$3"
  local blocker_type="$4"

  # DNS check.
  dns_result="OK"
  if ! host "${host}" >/dev/null 2>&1; then
    dns_result="NXDOMAIN"
  fi

  # HTTP check (only if DNS resolves).
  http_code="SKIPPED"
  if [[ "${dns_result}" == "OK" ]]; then
    http_code=$(curl -sS -o /dev/null \
      -H "User-Agent: ${UA}" \
      -w '%{http_code}' \
      --max-time 15 \
      "${url}" 2>/dev/null) || http_code="CURL_FAIL"
  fi

  local log_line="${PROBE_TS}\tportal=${name}\tdns=${dns_result}\thttp=${http_code}\tblocker=${blocker_type}"
  if [[ -d "${LOG_DIR}" ]]; then
    echo -e "${log_line}" >> "${LOG_FILE}"
  fi
  echo -e "${log_line}"
}

# Alabama — portal offline (NXDOMAIN since Apr 12, 2026).
check_portal "AL_FCPA" "fcpa.alabamavotes.gov" "https://fcpa.alabamavotes.gov/" "dns_offline"

# Oregon — datacenter IP blocked by cyber-security service.
check_portal "OR_ORESTAR" "secure.sos.state.or.us" "https://secure.sos.state.or.us/orestar/gotoPublicTransactionSearch.do" "datacenter_ip_block"

# FL House — datacenter IP rejected. FL Senate and FL campaign finance work fine.
check_portal "FL_HOUSE" "www.flhouse.gov" "https://www.flhouse.gov/" "datacenter_ip_block"
