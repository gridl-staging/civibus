#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://127.0.0.1:8077"
CACHE_CONTROL_EXPECTED="public, max-age=900"
SERVER_PID=""

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}"
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

CIVIBUS_ENV=production \
  CIVIBUS_API_KEYS=proof-key \
  CIVIBUS_RATE_LIMIT_REQUESTS=1000 \
  CIVIBUS_RATE_LIMIT_WINDOW_SECONDS=60 \
  POSTGRES_PASSWORD=civibus_dev \
  uv run --extra api uvicorn api.main:app --host 127.0.0.1 --port 8077 > /tmp/civibus_public_probe_uvicorn.log 2>&1 &
SERVER_PID="$!"

until curl -fsS "${BASE_URL}/health" >/dev/null; do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "server exited before readiness" >&2
    cat /tmp/civibus_public_probe_uvicorn.log >&2
    exit 1
  fi
  sleep 1
done

assert_status() {
  local path="$1"
  local expected_status="$2"
  local actual_status
  actual_status="$(curl -sS -o /tmp/civibus_public_probe_body -w '%{http_code}' "${BASE_URL}${path}")"
  if [[ "${actual_status}" != "${expected_status}" ]]; then
    echo "${path} expected ${expected_status}, got ${actual_status}" >&2
    cat /tmp/civibus_public_probe_body >&2
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
if ! jq -e 'type == "array"' /tmp/civibus_public_probe_body >/dev/null; then
  echo "/public/v1/federal/officials did not return a JSON array" >&2
  cat /tmp/civibus_public_probe_body >&2
  exit 1
fi
member_count="$(jq 'length' /tmp/civibus_public_probe_body)"
echo "member_count ${member_count}"
assert_header "/public/v1/federal/officials" "Cache-Control" "${CACHE_CONTROL_EXPECTED}"

if [[ "${member_count}" -gt 0 ]]; then
  person_id="$(jq -r '.[0].person_id' /tmp/civibus_public_probe_body)"
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
