#!/usr/bin/env bash
# Indiana bulk-ZIP freshness cadence polling.
#
# Downloads the 2026 contribution ZIP from campaignfinance.in.gov, extracts the
# max ContributionDate and Last-Modified header, and appends a timestamped row
# to a log file. Designed to run from Hetzner cron every 2 days.
#
# Decision rule (documented in ROADMAP.md):
#   If 3+ probes over 10 days show the file advancing → classify weekly-or-better.
#   Otherwise → classify freshness-limited, ship with user-facing warning.
#   Hard deadline: 2026-04-25 (10 days before May 5 primary).
#
# Usage:
#   bash infra/scripts/poll_in_freshness.sh
#
# Output: appends to /var/log/civibus/in-freshness-cadence.log (VM) or
#         prints to stdout if log dir doesn't exist.

set -euo pipefail

ZIP_URL="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2026_ContributionData.csv.zip"
LOG_DIR="/var/log/civibus"
LOG_FILE="${LOG_DIR}/in-freshness-cadence.log"
PROBE_TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Browser-like headers (required since Apr 2026 to avoid 403).
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

headers_file="${tmpdir}/headers.txt"
zip_file="${tmpdir}/in_2026_contrib.csv.zip"

# Fetch with headers saved.
http_code=$(curl -sS -o "${zip_file}" -D "${headers_file}" \
  -H "User-Agent: ${UA}" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -w '%{http_code}' \
  --max-time 60 \
  "${ZIP_URL}" 2>/dev/null) || http_code="CURL_FAIL"

last_modified="$(grep -i '^Last-Modified:' "${headers_file}" 2>/dev/null | sed 's/^[^:]*: //' | tr -d '\r')" || last_modified="UNKNOWN"
content_length="$(grep -i '^Content-Length:' "${headers_file}" 2>/dev/null | sed 's/^[^:]*: //' | tr -d '\r')" || content_length="UNKNOWN"

max_date="UNKNOWN"
row_count="0"

if [[ "${http_code}" == "200" ]] && [[ -f "${zip_file}" ]]; then
  csv_file="${tmpdir}/contrib.csv"
  unzip -oq "${zip_file}" -d "${tmpdir}" 2>/dev/null || true

  # Find the extracted CSV (name varies).
  extracted="$(find "${tmpdir}" -name '*.csv' -o -name '*.CSV' | head -1)"
  if [[ -n "${extracted}" ]]; then
    # Find the ContributionDate column index and extract max date.
    header_line="$(head -1 "${extracted}")"
    date_col=""
    IFS=',' read -ra cols <<< "${header_line}"
    for i in "${!cols[@]}"; do
      clean="$(echo "${cols[$i]}" | tr -d '"' | tr -d '\r')"
      if [[ "${clean}" == "ContributionDate" ]]; then
        date_col=$((i + 1))
        break
      fi
    done

    if [[ -n "${date_col}" ]]; then
      row_count="$(tail -n +2 "${extracted}" | wc -l | tr -d ' ')"
      # Use python to handle quoted CSV fields correctly.
      # Hardened against NoneType / non-string row shapes the IN source
      # has produced in the wild. Live evidence 2026-04-19..25: the
      # prior one-liner crashed with `'NoneType' object is not
      # subscriptable` on FOUR consecutive cron runs (likely a partial
      # download or schema drift). We now defensively coerce row + cell
      # and wrap each row in try/except so one bad row cannot abort
      # the probe.
      max_date="$(python3 -c "
import csv, sys
mx = ''
try:
    with open(sys.argv[1], newline='', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                if not isinstance(row, dict):
                    continue
                value = row.get('ContributionDate')
                if value is None:
                    continue
                d = str(value)[:10]
                if d > mx:
                    mx = d
            except Exception:
                continue
except Exception:
    pass
print(mx or 'UNKNOWN')
" "${extracted}")"
    fi
  fi
fi

log_line="${PROBE_TS}\thttp=${http_code}\tlast_modified=${last_modified}\tcontent_length=${content_length}\tmax_date=${max_date}\trows=${row_count}"

if [[ -d "${LOG_DIR}" ]]; then
  echo -e "${log_line}" >> "${LOG_FILE}"
fi
echo -e "${log_line}"
