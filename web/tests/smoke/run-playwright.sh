#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

smoke_mode="${SMOKE_MODE:-local}"
api_pid=""
cleanup() {
  if [[ -n "$api_pid" ]]; then
    kill "$api_pid" >/dev/null 2>&1 || true
    wait "$api_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$smoke_mode" != "production" && "${SMOKE_USE_LIVE_API:-0}" == "1" ]]; then
  live_api_base_url="${SMOKE_LIVE_API_BASE_URL:-http://127.0.0.1:8000}"
  live_api_health_url="${SMOKE_LIVE_API_HEALTH_URL:-${live_api_base_url}/health}"
  live_api_port="${SMOKE_LIVE_API_PORT:-8000}"

  if ! curl --silent --fail "$live_api_health_url" >/dev/null; then
    CIVIBUS_ENV=development \
      CIVIBUS_RATE_LIMIT_REQUESTS="${CIVIBUS_RATE_LIMIT_REQUESTS:-120}" \
      CIVIBUS_RATE_LIMIT_WINDOW_SECONDS="${CIVIBUS_RATE_LIMIT_WINDOW_SECONDS:-60}" \
      POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-civibus_dev}" \
      uv run --directory .. --extra api uvicorn api.main:app --host 127.0.0.1 --port "$live_api_port" \
      >/tmp/civibus_smoke_api.log 2>&1 &
    api_pid=$!
  fi

  for _ in {1..60}; do
    if curl --silent --fail "$live_api_health_url" >/dev/null; then
      break
    fi
    sleep 1
  done

  if ! curl --silent --fail "$live_api_health_url" >/dev/null; then
    echo "Live API health check failed at $live_api_health_url" >&2
    exit 1
  fi
fi

npx playwright --version >/dev/null
npx playwright install chromium >/dev/null

if [[ "${1:-}" == "--" ]]; then
  shift
fi

# Local fixture mode remains default for developer regression coverage.
# Production smoke mode is enabled by callers via SMOKE_MODE=production and SMOKE_BASE_URL.
npx playwright test --config playwright.config.ts "$@"
