#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CIVIBUS_PUBLIC_BASE_URL:-https://civibus-caddy.fly.dev}"
EXPECTED_SHA="${CIVIBUS_EXPECTED_SHA:-}"
FIXTURE_DIR="${CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR:-}"
CIVIBUS_PUBLIC_MONEY_VALUE_FATAL="${CIVIBUS_PUBLIC_MONEY_VALUE_FATAL:-0}"
SITEMAP_LATENCY_BUDGET_SECONDS="30.000"
PUBLIC_SURFACE_MANIFEST_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../public_surface_probes.tsv"
PUBLIC_SURFACE_MANIFEST_HEADER=$'surface_id\tkind\tpath\tmarker\tparity_mode\tuptime_mode\towners'
PUBLIC_SURFACE_RECORDS=()

manifest_header_has_column() {
  local header="$1"
  local column="$2"

  [[ $'\t'"${header}"$'\t' == *$'\t'"${column}"$'\t'* ]]
}

validate_public_surface_manifest_header() {
  local header="$1"
  local column

  if [[ "${header}" == "${PUBLIC_SURFACE_MANIFEST_HEADER}" ]]; then
    return 0
  fi
  for column in surface_id kind path marker parity_mode uptime_mode owners; do
    if ! manifest_header_has_column "${header}" "${column}"; then
      echo "public_surface_manifest_error header missing_column=${column}" >&2
      return 1
    fi
  done
  echo "public_surface_manifest_error header does_not_match_fixed_schema" >&2
  return 1
}

validate_public_surface_manifest_field() {
  local row_number="$1"
  local field_name="$2"
  local value="$3"
  local non_whitespace_value

  non_whitespace_value="${value//[[:space:]]/}"
  if [[ -z "${non_whitespace_value}" ]]; then
    echo "public_surface_manifest_error row=${row_number} blank_field=${field_name}" >&2
    return 1
  fi
}

validate_public_surface_manifest_path() {
  local row_number="$1"
  local value="$2"

  if python3 - "${value}" <<'PY'
import sys
from urllib.parse import unquote, urlsplit


raw_path = sys.argv[1]
if not raw_path.startswith("/") or raw_path.startswith("//"):
    raise SystemExit(1)
if any(ord(character) < 32 or ord(character) == 127 or character == "\\" for character in raw_path):
    raise SystemExit(1)

parsed = urlsplit(raw_path)
if parsed.scheme or parsed.netloc or parsed.fragment:
    raise SystemExit(1)

decoded_path = parsed.path
for _ in range(len(decoded_path) + 1):
    next_path = unquote(decoded_path)
    if next_path == decoded_path:
        break
    decoded_path = next_path
else:
    raise SystemExit(1)

if decoded_path.startswith("//") or "\\" in decoded_path:
    raise SystemExit(1)
if any(segment in {".", ".."} for segment in decoded_path.split("/")):
    raise SystemExit(1)
PY
  then
    return 0
  fi

  echo "public_surface_manifest_error row=${row_number} unsafe_path=${value}" >&2
  return 1
}

validate_public_surface_manifest_enum() {
  local row_number="$1"
  local field_name="$2"
  local value="$3"
  local known_values="$4"

  case " ${known_values} " in
    *" ${value} "*) return 0 ;;
  esac
  echo "public_surface_manifest_error row=${row_number} unknown_${field_name}=${value}" >&2
  return 1
}

load_public_surface_manifest() {
  local header manifest_line without_tabs field_count
  local row_number=1
  local surface_id kind path marker parity_mode uptime_mode owners
  local existing_id
  local -a seen_surface_ids=()

  if [[ ! -f "${PUBLIC_SURFACE_MANIFEST_PATH}" ]]; then
    echo "public_surface_manifest_error missing_file=${PUBLIC_SURFACE_MANIFEST_PATH}" >&2
    return 1
  fi
  exec 3< "${PUBLIC_SURFACE_MANIFEST_PATH}"
  IFS= read -r header <&3 || {
    echo "public_surface_manifest_error missing_header" >&2
    return 1
  }
  validate_public_surface_manifest_header "${header}" || return 1

  while IFS= read -r manifest_line || [[ -n "${manifest_line}" ]]; do
    row_number=$((row_number + 1))
    without_tabs="${manifest_line//$'\t'/}"
    field_count=$((${#manifest_line} - ${#without_tabs} + 1))
    if [[ "${field_count}" -ne 7 ]]; then
      echo "public_surface_manifest_error row=${row_number} field_count=${field_count} expected=7" >&2
      return 1
    fi
    IFS=$'\t' read -r surface_id kind path marker parity_mode uptime_mode owners <<< "${manifest_line}"
    validate_public_surface_manifest_field "${row_number}" surface_id "${surface_id}" || return 1
    validate_public_surface_manifest_field "${row_number}" kind "${kind}" || return 1
    validate_public_surface_manifest_field "${row_number}" path "${path}" || return 1
    validate_public_surface_manifest_field "${row_number}" marker "${marker}" || return 1
    validate_public_surface_manifest_field "${row_number}" parity_mode "${parity_mode}" || return 1
    validate_public_surface_manifest_field "${row_number}" uptime_mode "${uptime_mode}" || return 1
    validate_public_surface_manifest_field "${row_number}" owners "${owners}" || return 1
    validate_public_surface_manifest_path "${row_number}" "${path}" || return 1
    validate_public_surface_manifest_enum "${row_number}" kind "${kind}" "static person_sitemap" || return 1
    validate_public_surface_manifest_enum "${row_number}" parity_mode "${parity_mode}" "fatal known_red skip" || return 1
    validate_public_surface_manifest_enum "${row_number}" uptime_mode "${uptime_mode}" "fatal skip" || return 1
    for existing_id in "${seen_surface_ids[@]+"${seen_surface_ids[@]}"}"; do
      if [[ "${existing_id}" == "${surface_id}" ]]; then
        echo "public_surface_manifest_error row=${row_number} duplicate_surface_id=${surface_id}" >&2
        return 1
      fi
    done
    seen_surface_ids+=("${surface_id}")
    PUBLIC_SURFACE_RECORDS+=("${manifest_line}")
  done <&3
  exec 3<&-

  if [[ "${#PUBLIC_SURFACE_RECORDS[@]}" -eq 0 ]]; then
    echo "public_surface_manifest_error no_surface_rows" >&2
    return 1
  fi
}

load_public_surface_manifest || exit 1
TMP_DIR="$(mktemp -d)"
DEPLOYED_OPENAPI_JSON="${TMP_DIR}/deployed_openapi.json"
API_VERSION_JSON="${TMP_DIR}/api_health_version.json"
WEB_VERSION_JSON="${TMP_DIR}/web_version.json"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

normalize_base_url() {
  python3 - "${BASE_URL}" <<'PY'
import sys
from urllib.parse import urlsplit


raw_base_url = sys.argv[1].strip()
parsed = urlsplit(raw_base_url)

if parsed.scheme not in {"http", "https"}:
    raise SystemExit(1)
if not parsed.hostname:
    raise SystemExit(1)
if parsed.username is not None or parsed.password is not None:
    raise SystemExit(1)
if parsed.query or parsed.fragment:
    raise SystemExit(1)

hostname = parsed.hostname
if ":" in hostname and not hostname.startswith("["):
    hostname = f"[{hostname}]"
netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
path = parsed.path.rstrip("/")

print(f"{parsed.scheme}://{netloc}{path}")
PY
}

BASE_URL="$(normalize_base_url)" || {
  echo "invalid_base_url CIVIBUS_PUBLIC_BASE_URL must be an http(s) URL without embedded credentials, query, or fragment" >&2
  exit 1
}

echo "base_url ${BASE_URL}"

is_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

resolve_expected_sha() {
  if [[ -n "${EXPECTED_SHA}" ]]; then
    printf '%s\n' "${EXPECTED_SHA}"
    return 0
  fi

  if [[ -n "${FIXTURE_DIR}" ]]; then
    echo "missing_expected_sha CIVIBUS_EXPECTED_SHA is required in fixture mode" >&2
    return 1
  fi

  git fetch origin main >/dev/null
  git rev-parse "origin/main^{commit}"
}

copy_fixture_file() {
  local source_path="$1"
  local destination_path="$2"
  local error_message="$3"

  if [[ ! -f "${source_path}" ]]; then
    echo "${error_message} reason=fixture_missing fixture=${source_path}" >&2
    return 1
  fi

  cp "${source_path}" "${destination_path}"
}

fetch_deployed_openapi() {
  local openapi_url="${BASE_URL%/}/api/openapi.json"
  local http_status

  if [[ -n "${FIXTURE_DIR}" ]]; then
    copy_fixture_file \
      "${FIXTURE_DIR}/deployed_openapi.json" \
      "${DEPLOYED_OPENAPI_JSON}" \
      "openapi_fetch_error ${openapi_url}" || return 1
    if [[ -f "${FIXTURE_DIR}/deployed_openapi_status.txt" ]]; then
      http_status="$(tr -d '[:space:]' < "${FIXTURE_DIR}/deployed_openapi_status.txt")"
    else
      http_status="200"
    fi
  else
    http_status="$(
      curl --proto '=http,https' -sS -o "${DEPLOYED_OPENAPI_JSON}" -w "%{http_code}" "${openapi_url}"
    )" || {
      echo "openapi_fetch_error ${openapi_url}" >&2
      return 1
    }
  fi

  if [[ "${http_status}" != "200" ]]; then
    echo "openapi_unexpected_http_status ${openapi_url} ${http_status}" >&2
    return 1
  fi
}

fixture_file_status() {
  local fixture_basename="$1"
  local status_path="${FIXTURE_DIR}/${fixture_basename}_status.txt"

  if [[ -f "${status_path}" ]]; then
    tr -d '[:space:]' < "${status_path}"
  else
    echo "200"
  fi
}

fetch_version_payload() {
  local route_path="$1"
  local payload_path="$2"
  local fixture_basename="$3"
  local http_status

  if [[ -n "${FIXTURE_DIR}" ]]; then
    copy_fixture_file \
      "${FIXTURE_DIR}/${fixture_basename}.json" \
      "${payload_path}" \
      "deployed_sha_unknown route=${route_path}" || return 1
    http_status="$(fixture_file_status "${fixture_basename}")"
  else
    http_status="$(
      curl --proto '=http,https' -sS -o "${payload_path}" -w "%{http_code}" "${BASE_URL%/}${route_path}"
    )" || {
      echo "deployed_sha_unknown route=${route_path} reason=fetch_error" >&2
      return 1
    }
  fi

  if [[ "${http_status}" != "200" ]]; then
    echo "deployed_sha_unknown route=${route_path} http_status=${http_status}" >&2
    return 1
  fi
}

payload_git_sha() {
  local payload_path="$1"

  python3 - "${payload_path}" <<'PY'
import json
import re
import sys
from pathlib import Path


SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
payload_path = Path(sys.argv[1])
try:
    payload = json.loads(payload_path.read_text())
except Exception:  # noqa: BLE001 - probe must degrade to "unknown"
    print("unknown")
    raise SystemExit(0)

git_sha = payload.get("git_sha")
if isinstance(git_sha, str) and SHA_PATTERN.fullmatch(git_sha):
    print(git_sha)
else:
    print("unknown")
PY
}

commit_exists() {
  git cat-file -e "${1}^{commit}" >/dev/null 2>&1
}

print_commit_delta_if_resolvable() {
  local deployed_sha="$1"
  local expected_sha="$2"
  local label="$3"

  if commit_exists "${deployed_sha}" && commit_exists "${expected_sha}"; then
    echo "commit_delta ${deployed_sha}..${expected_sha} label=${label}" >&2
    git log --oneline "${deployed_sha}..${expected_sha}" >&2
  else
    echo "commit_delta_unavailable label=${label} deployed=${deployed_sha} expected=${expected_sha}" >&2
  fi
}

compare_deployed_shas() {
  local expected_sha="$1"
  local api_sha
  local web_sha

  fetch_version_payload "/api/health/version" "${API_VERSION_JSON}" "api_health_version"
  fetch_version_payload "/version.json" "${WEB_VERSION_JSON}" "web_version"

  api_sha="$(payload_git_sha "${API_VERSION_JSON}")"
  web_sha="$(payload_git_sha "${WEB_VERSION_JSON}")"

  if ! is_sha "${api_sha}" || ! is_sha "${web_sha}"; then
    echo "deployed_sha_unknown expected_sha=${expected_sha} api=${api_sha} web=${web_sha}" >&2
    return 1
  fi

  if [[ "${api_sha}" != "${expected_sha}" || "${web_sha}" != "${expected_sha}" ]]; then
    echo "deployed_sha_drift" >&2
    echo "expected_sha ${expected_sha}" >&2
    echo "api_deployed_sha ${api_sha}" >&2
    echo "web_deployed_sha ${web_sha}" >&2
    if [[ "${api_sha}" != "${expected_sha}" ]]; then
      print_commit_delta_if_resolvable "${api_sha}" "${expected_sha}" "api"
    fi
    if [[ "${web_sha}" != "${expected_sha}" && "${web_sha}" != "${api_sha}" ]]; then
      print_commit_delta_if_resolvable "${web_sha}" "${expected_sha}" "web"
    fi
    return 1
  fi

  echo "deployed_sha_match expected=${expected_sha} api=${api_sha} web=${web_sha}"
}

compare_openapi_paths() {
  local repo_openapi_paths_json=""

  if [[ -n "${FIXTURE_DIR}" ]]; then
    repo_openapi_paths_json="${FIXTURE_DIR}/repo_openapi_paths.json"
    if [[ ! -f "${repo_openapi_paths_json}" ]]; then
      echo "openapi_repo_fixture_missing ${repo_openapi_paths_json}" >&2
      return 1
    fi
  fi

  CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR="${FIXTURE_DIR}" \
  DEPLOYED_OPENAPI_JSON="${DEPLOYED_OPENAPI_JSON}" \
  REPO_OPENAPI_PATHS_JSON="${repo_openapi_paths_json}" \
  uv run --extra api python - <<'PY'
import json
import os
import sys
from pathlib import Path


def _load_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 - probe must fail with a stable diagnostic
        print(f"{label}_json_error {path} {exc.__class__.__name__}", file=sys.stderr)
        raise SystemExit(1)


def _normalized_paths(paths: object) -> set[str]:
    if isinstance(paths, dict):
        raw_paths = paths.keys()
    elif isinstance(paths, list):
        raw_paths = paths
    else:
        raise TypeError("OpenAPI paths must be a JSON object or list")
    return {str(path).rstrip("/") or "/" for path in raw_paths}


def _repo_paths_from_app() -> set[str]:
    os.environ.setdefault("CIVIBUS_ENV", "production")
    os.environ.setdefault("CIVIBUS_API_KEYS", "deployed-surface-parity-probe")
    os.environ.setdefault("CIVIBUS_RATE_LIMIT_REQUESTS", "1000")
    os.environ.setdefault("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "60")
    os.environ.setdefault("POSTGRES_PASSWORD", "civibus_dev")

    from api.main import create_app

    return _normalized_paths(create_app().openapi()["paths"])


def _repo_paths() -> set[str]:
    fixture_dir = os.environ.get("CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR", "").strip()
    if fixture_dir:
        return _normalized_paths(_load_json(Path(os.environ["REPO_OPENAPI_PATHS_JSON"]), "repo_openapi_paths"))
    return _repo_paths_from_app()


def _deployed_paths() -> set[str]:
    deployed_openapi = _load_json(Path(os.environ["DEPLOYED_OPENAPI_JSON"]), "deployed_openapi")
    if not isinstance(deployed_openapi, dict) or "paths" not in deployed_openapi:
        print("deployed_openapi_paths_missing", file=sys.stderr)
        raise SystemExit(1)
    return _normalized_paths(deployed_openapi["paths"])


repo_paths = _repo_paths()
deployed_paths = _deployed_paths()
missing_from_deployed = sorted(repo_paths - deployed_paths)
missing_from_repo = sorted(deployed_paths - repo_paths)

for path in missing_from_deployed:
    print(f"missing_from_deployed {path}", file=sys.stderr)
for path in missing_from_repo:
    print(f"missing_from_repo {path}", file=sys.stderr)

if missing_from_deployed or missing_from_repo:
    sys.exit(1)

print(f"openapi_paths_match repo={len(repo_paths)} deployed={len(deployed_paths)}")
PY
}

fixture_page_status() {
  local path="$1"
  awk -F '\t' -v expected_path="${path}" '$1 == expected_path {print $2; found = 1; exit} END {if (!found) exit 1}' \
    "${FIXTURE_DIR}/page_statuses.tsv"
}

fixture_page_latency_seconds() {
  local path="$1"
  local latency_table="${FIXTURE_DIR}/page_latencies.tsv"

  if [[ ! -f "${latency_table}" ]]; then
    echo "page_fetch_error ${path} fixture_latency_table_missing" >&2
    return 1
  fi

  awk -F '\t' -v expected_path="${path}" '$1 == expected_path {print $2; found = 1; exit} END {if (!found) exit 1}' \
    "${latency_table}" || {
      echo "page_fetch_error ${path} fixture_latency_missing" >&2
      return 1
    }
}

page_body_slug() {
  local path="$1"

  # Fixture contract: lowercase hex of the complete UTF-8 path, including query string.
  # This keeps "/", "/a/b", and query-bearing paths deterministic and collision-free.
  printf '%s' "${path}" | od -An -tx1 | tr -d ' \n'
}

copy_fixture_page_body() {
  local path="$1"
  local destination_path="$2"
  local slug
  local source_path

  slug="$(page_body_slug "${path}")"
  source_path="${FIXTURE_DIR}/page_bodies/${slug}.html"
  if [[ ! -f "${source_path}" ]]; then
    echo "page_fetch_error ${path} fixture_body_missing fixture=${source_path}" >&2
    return 1
  fi

  cp "${source_path}" "${destination_path}"
}

fetch_public_page_body() {
  local path="$1"
  local body_path="$2"
  local fetch_result
  local latency_seconds
  local status

  if [[ -n "${FIXTURE_DIR}" ]]; then
    if [[ ! -f "${FIXTURE_DIR}/page_statuses.tsv" ]]; then
      echo "page_fetch_error ${path} fixture_status_table_missing" >&2
      return 1
    fi
    status="$(fixture_page_status "${path}")" || {
      echo "page_fetch_error ${path} fixture_status_missing" >&2
      return 1
    }
    copy_fixture_page_body "${path}" "${body_path}" || return 1
    if [[ "${path}" == "/sitemap.xml" ]]; then
      latency_seconds="$(fixture_page_latency_seconds "${path}")" || return 1
    else
      latency_seconds="not_measured"
    fi
  else
    fetch_result="$(
      curl --proto '=http,https' --max-time 60 -sS -o "${body_path}" -w "%{http_code}\t%{time_total}" "${BASE_URL%/}${path}"
    )" || {
      echo "page_fetch_error ${path}" >&2
      return 1
    }
    status="${fetch_result%%$'\t'*}"
    latency_seconds="${fetch_result#*$'\t'}"
  fi

  printf '%s\t%s\n' "${status}" "${latency_seconds}"
}

resolve_person_surface_specimen() {
  local sitemap_path="$1"
  local body_path="${TMP_DIR}/person_surface_sitemap.html"
  local fetch_result
  local specimen_path
  local specimen_url
  local status

  fetch_result="$(fetch_public_page_body "${sitemap_path}" "${body_path}")" || {
    printf '%s\tfetch_error\n' "${sitemap_path}"
    return 1
  }
  status="${fetch_result%%$'\t'*}"
  if [[ "${status}" != "200" ]]; then
    printf '%s\tunexpected_http_status_%s\n' "${sitemap_path}" "${status}"
    return 1
  fi

  specimen_url="$(grep -o 'https\?://[^<]*/person/[^<]*' "${body_path}" | sed -n '1p')" || true
  if [[ -z "${specimen_url}" ]]; then
    printf '%s\tno_person_specimen\n' "${sitemap_path}"
    return 1
  fi

  specimen_path="/person/${specimen_url#*/person/}"
  printf '%s\tok\n' "${specimen_path}"
}

warm_up_public_page() {
  local path="$1"
  local body_path="${TMP_DIR}/warmup_$(page_body_slug "${path}").html"

  # 2026-07-23 cold/warm probe showed donor search can exceed the kill window
  # on first request while a same-URL warm request returns within bounds.
  fetch_public_page_body "${path}" "${body_path}" >/dev/null || true
}

assert_public_page_body() {
  local path="$1"
  local marker="$2"
  local body_path="$3"

  # Frontend copy owner: web/tests/smoke/smoke-helpers.ts::BACKEND_FAILURE_STATE_COPY.
  if grep -Eiq "temporarily unavailable" "${body_path}"; then
    echo "page_backend_failure_copy ${path} owner=web/tests/smoke/smoke-helpers.ts::BACKEND_FAILURE_STATE_COPY" >&2
    return 1
  fi

  if ! grep -Fq -- "${marker}" "${body_path}"; then
    echo "page_content_marker_missing ${path} marker=${marker}" >&2
    return 1
  fi
}

probe_public_page() {
  local path="$1"
  local marker="$2"
  local parity_mode="$3"
  local surface_id="$4"
  local owners="$5"
  local fetch_result
  local latency_seconds
  local status
  local body_path="${TMP_DIR}/page_body_$(page_body_slug "${path}").html"

  if [[ "${parity_mode}" == "known_red" ]]; then
    probe_known_red_public_page "${path}" "${surface_id}" "${owners}"
    return 0
  fi

  if [[ "${path}" == "/donors?q=smith&by=name" ]]; then
    warm_up_public_page "${path}"
  fi

  fetch_result="$(fetch_public_page_body "${path}" "${body_path}")" || return 1
  status="${fetch_result%%$'\t'*}"
  latency_seconds="${fetch_result#*$'\t'}"

  if [[ "${status}" != "200" ]]; then
    if [[ "${status}" == "404" ]]; then
      echo "missing_page ${path} ${status}" >&2
    else
      echo "page_unexpected_http_status ${path} ${status}" >&2
    fi
    return 1
  fi

  assert_public_page_body "${path}" "${marker}" "${body_path}" || return 1

  echo "page_status ${path} ${status} marker_ok surface_id=${surface_id} owner=${owners}"
  if [[ "${path}" == "/sitemap.xml" ]]; then
    echo "page_latency ${path} seconds=${latency_seconds} budget_seconds=${SITEMAP_LATENCY_BUDGET_SECONDS}"
    if ! python3 - "${latency_seconds}" "${SITEMAP_LATENCY_BUDGET_SECONDS}" <<'PY'
from decimal import Decimal
import sys

raise SystemExit(0 if Decimal(sys.argv[1]) <= Decimal(sys.argv[2]) else 1)
PY
    then
      echo "page_latency_budget_exceeded ${path} seconds=${latency_seconds} budget_seconds=${SITEMAP_LATENCY_BUDGET_SECONDS}" >&2
      return 1
    fi
  fi
}

probe_known_red_public_page() {
  local path="$1"
  local surface_id="$2"
  local owners="$3"
  local status
  local body_path="${TMP_DIR}/known_red_body_$(page_body_slug "${path}").html"

  if status="$(fetch_public_page_body "${path}" "${body_path}")"; then
    echo "WARN known_red_page ${path} ${status} surface_id=${surface_id} owner=${owners} reason=manifest_known_red"
  else
    echo "WARN known_red_page ${path} fetch_error surface_id=${surface_id} owner=${owners} reason=manifest_known_red"
  fi
}

probe_person_surface() {
  local sitemap_path="$1"
  local marker="$2"
  local surface_id="$3"
  local owners="$4"
  local body_path
  local fetch_result
  local reason
  local specimen_result
  local specimen_path
  local status

  specimen_result="$(resolve_person_surface_specimen "${sitemap_path}")" || {
    specimen_path="${specimen_result%%$'\t'*}"
    reason="${specimen_result#*$'\t'}"
    echo "person_surface ${specimen_path} failed reason=${reason} surface_id=${surface_id} owner=${owners}"
    return 1
  }
  specimen_path="${specimen_result%%$'\t'*}"
  body_path="${TMP_DIR}/person_surface_body_$(page_body_slug "${specimen_path}").html"
  fetch_result="$(fetch_public_page_body "${specimen_path}" "${body_path}")" || {
    echo "person_surface ${specimen_path} failed reason=fetch_error surface_id=${surface_id} owner=${owners}"
    return 1
  }
  status="${fetch_result%%$'\t'*}"
  if [[ "${status}" != "200" ]]; then
    echo "person_surface ${specimen_path} failed reason=unexpected_http_status_${status} surface_id=${surface_id} owner=${owners}"
    return 1
  fi
  if ! assert_public_page_body "${specimen_path}" "${marker}" "${body_path}"; then
    if grep -Eiq "temporarily unavailable" "${body_path}"; then
      reason="backend_failure_copy"
    else
      reason="breadcrumb_missing"
    fi
    echo "person_surface ${specimen_path} failed reason=${reason} surface_id=${surface_id} owner=${owners}"
    return 1
  fi

  echo "person_surface ${specimen_path} ok surface_id=${surface_id} owner=${owners}"
}

probe_public_surface() {
  local record
  local surface_id kind path marker parity_mode uptime_mode owners
  local surfaces_probed=0
  local failed=0

  for record in "${PUBLIC_SURFACE_RECORDS[@]}"; do
    IFS=$'\t' read -r surface_id kind path marker parity_mode uptime_mode owners <<< "${record}"
    if [[ "${parity_mode}" == "skip" ]]; then
      continue
    fi
    if [[ "${kind}" == "static" ]]; then
      if [[ "${parity_mode}" == "fatal" ]]; then
        surfaces_probed=$((surfaces_probed + 1))
        if ! probe_public_page "${path}" "${marker}" "${parity_mode}" "${surface_id}" "${owners}"; then
          failed=$((failed + 1))
        fi
      else
        probe_public_page "${path}" "${marker}" "${parity_mode}" "${surface_id}" "${owners}"
      fi
    elif [[ "${parity_mode}" == "fatal" ]]; then
      surfaces_probed=$((surfaces_probed + 1))
      if ! probe_person_surface "${path}" "${marker}" "${surface_id}" "${owners}"; then
        failed=$((failed + 1))
      fi
    else
      probe_person_surface "${path}" "${marker}" "${surface_id}" "${owners}" || true
    fi
  done

  echo "surfaces_probed=${surfaces_probed} failed=${failed}"
  if [[ "${failed}" -ne 0 ]]; then
    echo "surface_parity_failed failed=${failed}" >&2
    return 1
  fi
}

probe_public_money_value() {
  local money_status=0
  local command=(
    uv run --extra api python infra/scripts/public_money_value_probe.py
    --base-url "${BASE_URL}"
  )

  if [[ -n "${FIXTURE_DIR}" ]]; then
    command+=(--fixture-dir "${FIXTURE_DIR}")
  fi

  "${command[@]}" || money_status=$?
  if [[ "${money_status}" -eq 0 ]]; then
    echo "money_value_probe_ok"
    return 0
  fi

  if [[ "${money_status}" -eq 1 ]]; then
    echo "money_value_failure_nonfatal exit_status=${money_status} fatal=0"
    return 0
  fi

  if [[ "${CIVIBUS_PUBLIC_MONEY_VALUE_FATAL}" == "1" && "${money_status}" -eq 2 ]]; then
    echo "money_value_failure_fatal exit_status=${money_status} fatal=1" >&2
    return "${money_status}"
  fi

  if [[ "${money_status}" -eq 2 ]]; then
    echo "money_value_failure_nonfatal exit_status=${money_status} fatal=0"
    return 0
  fi

  echo "money_value_probe_error exit_status=${money_status}" >&2
  return "${money_status}"
}

structural_status=0
money_status=0

EXPECTED_SHA="$(resolve_expected_sha)" || structural_status=1
if [[ "${structural_status}" -eq 0 ]] && ! is_sha "${EXPECTED_SHA}"; then
  echo "invalid_expected_sha ${EXPECTED_SHA}" >&2
  structural_status=1
fi

if fetch_deployed_openapi; then
  compare_openapi_paths || structural_status=1
else
  structural_status=1
fi
if is_sha "${EXPECTED_SHA}"; then
  compare_deployed_shas "${EXPECTED_SHA}" || structural_status=1
fi
probe_public_surface || structural_status=1
probe_public_money_value || money_status=$?

if [[ "${structural_status}" -ne 0 || "${money_status}" -ne 0 ]]; then
  echo "deployed_surface_parity_failed structural_status=${structural_status} money_status=${money_status}" >&2
  exit 1
fi

echo "surface_parity_ok"
