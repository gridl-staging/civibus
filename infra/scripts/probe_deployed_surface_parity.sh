#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CIVIBUS_PUBLIC_BASE_URL:-https://civibus-caddy.fly.dev}"
FIXTURE_DIR="${CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR:-}"
PUBLIC_PAGES=("/" "/congress" "/developers")
TMP_DIR="$(mktemp -d)"
DEPLOYED_OPENAPI_JSON="${TMP_DIR}/deployed_openapi.json"

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

fetch_deployed_openapi() {
  local openapi_url="${BASE_URL%/}/api/openapi.json"
  local http_status

  if [[ -n "${FIXTURE_DIR}" ]]; then
    cp "${FIXTURE_DIR}/deployed_openapi.json" "${DEPLOYED_OPENAPI_JSON}"
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

compare_openapi_paths() {
  CIVIBUS_DEPLOYED_SURFACE_FIXTURE_DIR="${FIXTURE_DIR}" \
  DEPLOYED_OPENAPI_JSON="${DEPLOYED_OPENAPI_JSON}" \
  uv run --extra api python - <<'PY'
import json
import os
import sys
from pathlib import Path


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
        return _normalized_paths(json.loads((Path(fixture_dir) / "repo_openapi_paths.json").read_text()))
    return _repo_paths_from_app()


def _deployed_paths() -> set[str]:
    deployed_openapi = json.loads(Path(os.environ["DEPLOYED_OPENAPI_JSON"]).read_text())
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

probe_public_page() {
  local path="$1"
  local status

  if [[ -n "${FIXTURE_DIR}" ]]; then
    status="$(fixture_page_status "${path}")" || {
      echo "page_fetch_error ${path} fixture_status_missing" >&2
      return 1
    }
  else
    status="$(
      curl --proto '=http,https' -sS -o /dev/null -w "%{http_code}" "${BASE_URL%/}${path}"
    )" || {
      echo "page_fetch_error ${path}" >&2
      return 1
    }
  fi

  if [[ "${status}" != "200" ]]; then
    if [[ "${status}" == "404" ]]; then
      echo "missing_page ${path} ${status}" >&2
    else
      echo "page_unexpected_http_status ${path} ${status}" >&2
    fi
    return 1
  fi

  echo "page_status ${path} ${status}"
}

fetch_deployed_openapi
compare_openapi_paths
for page_path in "${PUBLIC_PAGES[@]}"; do
  probe_public_page "${page_path}"
done

echo "surface_parity_ok"
