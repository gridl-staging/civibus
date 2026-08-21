#!/usr/bin/env bash
set -euo pipefail

CIVIBUS_PROBE_PORT="${CIVIBUS_PROBE_PORT:-8077}"
CIVIBUS_PROBE_SURFACE="${CIVIBUS_PROBE_SURFACE:-}"
if ! [[ "${CIVIBUS_PROBE_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] \
  || (( CIVIBUS_PROBE_PORT > 65535 )); then
  echo "CIVIBUS_PROBE_PORT must be an integer from 1 through 65535" >&2
  exit 2
fi

PAGE_BACKEND_TARGET_SECONDS="3.5"
REQUEST_HARD_CEILING_SECONDS="10"
EXPECTED_LINKED_OFFICIALS="${CIVIBUS_EXPECTED_LINKED_OFFICIALS:-527}"
PROBE_DB_HOST="${POSTGRES_HOST:-localhost}"
PROBE_DB_PORT="${POSTGRES_PORT:-5433}"
PROBE_DB_NAME="${POSTGRES_DB:-civibus}"
BASE_URL="http://127.0.0.1:${CIVIBUS_PROBE_PORT}"
umask 077
PROBE_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/civibus_public_probe.XXXXXX")"
SERVER_LOG="${PROBE_TMP_DIR}/uvicorn.log"
BODY_PATH="${PROBE_TMP_DIR}/body"
PROBE_API_KEY="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
CACHE_CONTROL_EXPECTED="public, max-age=900"
SERVER_PID=""
REQUEST_STATUS=""
REQUEST_TTFB=""
REQUEST_TOTAL=""
REQUEST_COUNT=""

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}"
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  rm -f -- "${SERVER_LOG}" "${BODY_PATH}"
  rmdir "${PROBE_TMP_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

CIVIBUS_ENV=production \
  CIVIBUS_API_KEYS="${PROBE_API_KEY}" \
  CIVIBUS_RATE_LIMIT_REQUESTS=1000 \
  CIVIBUS_RATE_LIMIT_WINDOW_SECONDS=60 \
  POSTGRES_PASSWORD=civibus_dev \
  uv run --extra api uvicorn api.main:app --host 127.0.0.1 --port "${CIVIBUS_PROBE_PORT}" > "${SERVER_LOG}" 2>&1 &
SERVER_PID="$!"

until curl -fsS "${BASE_URL}/health" >/dev/null; do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "server exited before readiness" >&2
    cat "${SERVER_LOG}" >&2
    exit 1
  fi
  sleep 1
done

target_verdict() {
  local total_seconds="$1"
  awk -v total="${total_seconds}" -v target="${PAGE_BACKEND_TARGET_SECONDS}" \
    'BEGIN { print (total < target) ? "pass" : "over_target" }'
}

request_is_below_ceiling() {
  local total_seconds="$1"
  awk -v total="${total_seconds}" -v ceiling="${REQUEST_HARD_CEILING_SECONDS}" \
    'BEGIN { exit !(total < ceiling) }'
}

measure_selected_request() {
  local label="$1"
  local path="$2"
  local count_filter="$3"
  local evidence_context="${4:-}"
  local curl_metrics
  local curl_exit

  set +e
  curl_metrics="$(
    curl -sS \
      --max-time "${REQUEST_HARD_CEILING_SECONDS}" \
      -H "X-API-Key: ${PROBE_API_KEY}" \
      -o "${BODY_PATH}" \
      -w '%{http_code} %{time_starttransfer} %{time_total}' \
      "${BASE_URL}${path}"
  )"
  curl_exit="$?"
  set -e
  if [[ "${curl_exit}" -ne 0 ]]; then
    echo "surface=${label} path=${path} curl_exit=${curl_exit} hard_ceiling_seconds=${REQUEST_HARD_CEILING_SECONDS}" >&2
    exit 1
  fi

  read -r REQUEST_STATUS REQUEST_TTFB REQUEST_TOTAL <<< "${curl_metrics}"
  REQUEST_COUNT="$(jq "${count_filter}" "${BODY_PATH}")"
  echo "surface=${label} path=${path} status=${REQUEST_STATUS} ttfb_seconds=${REQUEST_TTFB} total_seconds=${REQUEST_TOTAL} response_count=${REQUEST_COUNT} target_seconds=${PAGE_BACKEND_TARGET_SECONDS} target_verdict=$(target_verdict "${REQUEST_TOTAL}") hard_ceiling_seconds=${REQUEST_HARD_CEILING_SECONDS} db_host=${PROBE_DB_HOST} db_port=${PROBE_DB_PORT} database=${PROBE_DB_NAME} ${evidence_context}"

  if [[ "${REQUEST_STATUS}" != "200" ]] || ! request_is_below_ceiling "${REQUEST_TOTAL}"; then
    cat "${BODY_PATH}" >&2
    exit 1
  fi
}

run_congress_surface() {
  local members_total
  local members_count
  local money_total
  local money_count
  local combined_total
  local combined_verdict

  measure_selected_request \
    "congress_members" \
    "/v1/congress/members" \
    "length" \
    "linked_officials=${EXPECTED_LINKED_OFFICIALS}"
  members_total="${REQUEST_TOTAL}"
  members_count="${REQUEST_COUNT}"
  measure_selected_request \
    "congress_money_summaries" \
    "/v1/congress/money-summaries" \
    "length" \
    "linked_officials=${EXPECTED_LINKED_OFFICIALS}"
  money_total="${REQUEST_TOTAL}"
  money_count="${REQUEST_COUNT}"
  combined_total="$(awk -v members="${members_total}" -v money="${money_total}" 'BEGIN { printf "%.6f", members + money }')"
  combined_verdict="$(target_verdict "${combined_total}")"

  echo "surface=congress combined_total_seconds=${combined_total} members_count=${members_count} money_summary_count=${money_count} linked_officials=${EXPECTED_LINKED_OFFICIALS} target_seconds=${PAGE_BACKEND_TARGET_SECONDS} target_verdict=${combined_verdict} hard_ceiling_seconds=${REQUEST_HARD_CEILING_SECONDS} db_host=${PROBE_DB_HOST} db_port=${PROBE_DB_PORT} database=${PROBE_DB_NAME}"
  if [[ "${members_count}" != "${EXPECTED_LINKED_OFFICIALS}" ]] \
    || [[ "${money_count}" != "${EXPECTED_LINKED_OFFICIALS}" ]] \
    || [[ "${combined_verdict}" != "pass" ]]; then
    exit 1
  fi
}

run_selected_surface() {
  local selected_surface="$1"
  case "${selected_surface}" in
    congress)
      run_congress_surface
      ;;
    candidates)
      measure_selected_request "candidates" "/v1/candidates?limit=50&offset=0" ".items | length"
      ;;
    committees)
      measure_selected_request "committees" "/v1/committees?limit=50&offset=0" ".items | length"
      ;;
    search)
      measure_selected_request "search" "/v1/search?q=smith&limit=20&offset=0" ".items | length"
      ;;
    *)
      echo "unknown CIVIBUS_PROBE_SURFACE=${selected_surface}; expected congress, candidates, committees, or search" >&2
      exit 2
      ;;
  esac
}

if [[ -n "${CIVIBUS_PROBE_SURFACE}" ]]; then
  run_selected_surface "${CIVIBUS_PROBE_SURFACE}"
  exit 0
fi

assert_status() {
  local path="$1"
  local expected_status="$2"
  local actual_status
  actual_status="$(curl -sS -o "${BODY_PATH}" -w '%{http_code}' "${BASE_URL}${path}")"
  if [[ "${actual_status}" != "${expected_status}" ]]; then
    echo "${path} expected ${expected_status}, got ${actual_status}" >&2
    cat "${BODY_PATH}" >&2
    exit 1
  fi
  echo "status ${path} ${actual_status}"
}

assert_header() {
  local path="$1"
  local header_name="$2"
  local expected_value="$3"
  local actual_value
  actual_value="$(
    curl -sS -D - -o /dev/null "${BASE_URL}${path}" \
      | awk -v name="${header_name}" 'tolower($0) ~ "^" tolower(name) ":" {sub("^[^:]*: *", ""); sub("\r$", ""); print; exit}'
  )"
  if [[ "${actual_value}" != "${expected_value}" ]]; then
    echo "${path} expected ${header_name}: ${expected_value}, got: ${actual_value}" >&2
    exit 1
  fi
  echo "header ${path} ${header_name}: ${actual_value}"
}

assert_content_type_prefix() {
  local path="$1"
  local expected_prefix="$2"
  local actual_value
  actual_value="$(
    curl -sS -D - -o /dev/null "${BASE_URL}${path}" \
      | awk 'tolower($0) ~ "^content-type:" {sub("^[^:]*: *", ""); sub("\r$", ""); print; exit}'
  )"
  if [[ "${actual_value}" != "${expected_prefix}"* ]]; then
    echo "${path} expected Content-Type prefix ${expected_prefix}, got: ${actual_value}" >&2
    exit 1
  fi
  echo "content-type ${path} ${actual_value}"
}

assert_status "/public/v1/federal/officials" "200"
if ! jq -e 'type == "array"' "${BODY_PATH}" >/dev/null; then
  echo "/public/v1/federal/officials did not return a JSON array" >&2
  cat "${BODY_PATH}" >&2
  exit 1
fi
member_count="$(jq 'length' "${BODY_PATH}")"
echo "member_count ${member_count}"
assert_header "/public/v1/federal/officials" "Cache-Control" "${CACHE_CONTROL_EXPECTED}"

if [[ "${member_count}" -gt 0 ]]; then
  person_id="$(jq -r '.[0].person_id' "${BODY_PATH}")"
  money_path="/public/v1/federal/officials/${person_id}/money"
  money_expected_status="200"
  echo "money_probe seeded-member"
else
  money_path="/public/v1/federal/officials/00000000-0000-0000-0000-000000000000/money"
  money_expected_status="404"
  echo "money_probe empty-db-structural"
fi
assert_status "${money_path}" "${money_expected_status}"
assert_header "${money_path}" "Cache-Control" "${CACHE_CONTROL_EXPECTED}"

assert_status "/public/v1/federal/export.json" "200"
assert_header "/public/v1/federal/export.json" "Cache-Control" "${CACHE_CONTROL_EXPECTED}"

assert_status "/public/v1/federal/export.csv" "200"
assert_content_type_prefix "/public/v1/federal/export.csv" "text/csv"
assert_header "/public/v1/federal/export.csv" "Cache-Control" "${CACHE_CONTROL_EXPECTED}"

assert_status "/v1/candidates" "401"
echo "private_path_gated /v1/candidates 401"
