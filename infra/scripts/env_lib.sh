#!/usr/bin/env bash
# Shared .env loading helpers for civibus cron/refresh scripts.
# Sourced (not executed) by refresh_priority.sh and refresh_fec_bulk.sh.

# Parse a .env file and export each KEY=VALUE pair into the current shell.
# Handles comments, blank lines, 'export' prefixes, and single/double quotes.
# Does NOT eval arbitrary shell syntax — only literal assignments are loaded.
load_env_assignments() {
  local env_path="$1"
  local raw_line line key value

  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    raw_line="${raw_line%$'\r'}"
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"

    if [[ -z "${line}" || "${line:0:1}" == "#" ]]; then
      continue
    fi

    if [[ "${line}" =~ ^export[[:space:]]+ ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi

    if [[ ! "${line}" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      echo "Invalid .env assignment: ${raw_line}" >&2
      return 1
    fi

    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"

    # Load literal KEY=VALUE pairs without executing shell syntax from .env.
    if [[ "${value}" =~ ^\"(.*)\"$ ]]; then
      value="${BASH_REMATCH[1]}"
      value="${value//\\\"/\"}"
      value="${value//\\\\/\\}"
    elif [[ "${value}" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi

    export "${key}=${value}"
  done < "${env_path}"
}

# Load .env, set common env vars needed by all refresh scripts.
# Call this after setting script_dir and repo_root.
load_civibus_env() {
  local env_file="${1:-${repo_root}/.env}"

  if [[ ! -f "${env_file}" ]]; then
    echo "Missing required env file: ${env_file}" >&2
    return 1
  fi

  load_env_assignments "${env_file}"

  export PATH="${HOME}/.local/bin:${PATH}"

  if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "POSTGRES_PASSWORD must be set in .env or the shell environment" >&2
    return 1
  fi

  export POSTGRES_HOST="127.0.0.1"
  export POSTGRES_PORT="5432"

  # libpq-standard vars so bare psycopg.connect() works without explicit DSN
  export PGHOST="${POSTGRES_HOST}"
  export PGPORT="${POSTGRES_PORT}"
  export PGUSER="${POSTGRES_USER:-civibus}"
  export PGPASSWORD="${POSTGRES_PASSWORD}"
  export PGDATABASE="${POSTGRES_DB:-civibus}"

  # Use system CA bundle instead of Python's certifi. Certifi's bundle is
  # missing some government-site cert chains (IL/Cloudflare, CO/Entrust).
  export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"
}
