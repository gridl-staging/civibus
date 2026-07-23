#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CIVIBUS_PUBLIC_BASE_URL:-https://civibus-caddy.fly.dev}"
EXPECTED_SHA="${CIVIBUS_EXPECTED_SHA:-}"
FIXTURE_DIR="${CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR:-}"
PUBLIC_PAGES=(
  "/|Follow money around Congress and the White House."
  "/search?q=ossoff|data-testid=\"search-results-region\""
  "/donors?q=smith&by=name|data-testid=\"donor-result-row\""
  "/congress|data-testid=\"congress-member-row-0\""
  "/methodology|Methodology"
  "/developers|GET /api/public/v1/federal/officials"
  "/candidates|Candidates"
  "/committees|Committees"
  "/committee/jon-ossoff-for-senate|Key metrics"
  "/compare|Compare officeholders"
  "/calendar|Election calendar"
  "/coverage|campaign_finance"
  "/data-sources|campaign_finance"
)
KNOWN_RED_PUBLIC_PAGES=(
  "/sitemap.xml|dynamic sitemap can depend on campaign-list data not yet promoted to fail-closed|surface-parity-stage-1"
)
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
  else
    status="$(
      curl --proto '=http,https' --max-time 25 -sS -o "${body_path}" -w "%{http_code}" "${BASE_URL%/}${path}"
    )" || {
      echo "page_fetch_error ${path}" >&2
      return 1
    }
  fi

  printf '%s\n' "${status}"
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

  if ! grep -Fq "${marker}" "${body_path}"; then
    echo "page_content_marker_missing ${path} marker=${marker}" >&2
    return 1
  fi
}

probe_public_page() {
  local entry="$1"
  local path="${entry%%|*}"
  local marker="${entry#*|}"
  local status
  local body_path="${TMP_DIR}/page_body_$(page_body_slug "${path}").html"

  if [[ "${path}" == "/donors?q=smith&by=name" ]]; then
    warm_up_public_page "${path}"
  fi

  status="$(fetch_public_page_body "${path}" "${body_path}")" || return 1

  if [[ "${status}" != "200" ]]; then
    if [[ "${status}" == "404" ]]; then
      echo "missing_page ${path} ${status}" >&2
    else
      echo "page_unexpected_http_status ${path} ${status}" >&2
    fi
    return 1
  fi

  assert_public_page_body "${path}" "${marker}" "${body_path}" || return 1

  echo "page_status ${path} ${status} marker_ok"
}

probe_known_red_public_page() {
  local entry="$1"
  local path="${entry%%|*}"
  local remainder="${entry#*|}"
  local reason="${remainder%%|*}"
  local owner="${remainder#*|}"
  local status
  local body_path="${TMP_DIR}/known_red_body_$(page_body_slug "${path}").html"

  if status="$(fetch_public_page_body "${path}" "${body_path}")"; then
    echo "WARN known_red_page ${path} ${status} owner=${owner} reason=${reason}"
  else
    echo "WARN known_red_page ${path} fetch_error owner=${owner} reason=${reason}"
  fi
}

probe_public_surface() {
  local entry
  local surfaces_probed=0
  local failed=0

  for entry in "${PUBLIC_PAGES[@]}"; do
    surfaces_probed=$((surfaces_probed + 1))
    if ! probe_public_page "${entry}"; then
      failed=$((failed + 1))
    fi
  done

  for entry in "${KNOWN_RED_PUBLIC_PAGES[@]}"; do
    probe_known_red_public_page "${entry}"
  done

  echo "surfaces_probed=${surfaces_probed} failed=${failed}"
  if [[ "${failed}" -ne 0 ]]; then
    echo "surface_parity_failed failed=${failed}" >&2
    return 1
  fi
}

EXPECTED_SHA="$(resolve_expected_sha)" || exit 1
if ! is_sha "${EXPECTED_SHA}"; then
  echo "invalid_expected_sha ${EXPECTED_SHA}" >&2
  exit 1
fi

fetch_deployed_openapi
compare_openapi_paths
compare_deployed_shas "${EXPECTED_SHA}"
probe_public_surface

echo "surface_parity_ok"
