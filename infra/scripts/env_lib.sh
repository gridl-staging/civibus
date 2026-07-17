#!/usr/bin/env bash
# Shared .env loading helpers for civibus cron/refresh scripts.
# Sourced (not executed) by refresh_priority.sh and refresh_fec_bulk.sh.

# Return file or directory permission bits as an octal string on macOS/BSD and
# GNU/Linux. Keeping the platform-specific stat probes here lets env-file and
# PATH guards share one policy-neutral helper. Successful output contains only
# the mode; failures are reported on stderr.
get_file_mode_octal() {
  local path="$1"
  local mode

  if mode="$(stat -f '%Lp' -- "${path}" 2>/dev/null)"; then
    printf '%s\n' "${mode}"
    return 0
  fi

  if mode="$(stat -c '%a' -- "${path}" 2>/dev/null)"; then
    printf '%s\n' "${mode}"
    return 0
  fi

  echo "Unable to determine permissions for path: ${path}" >&2
  return 1
}

# Trusted env files and PATH entries also depend on their parent directories:
# writable or symlinked ancestors let another user replace the checked leaf
# after validation. Walk upward to reject those replacement seams.
require_private_parent_directories() {
  local target_path="$1"
  local path_label="${2:-path}"
  local action_verb="${3:-Refusing}"
  local current_path mode next_path

  if [[ "${target_path}" != /* ]]; then
    current_path="${PWD%/}/${target_path}"
  else
    current_path="${target_path}"
  fi
  current_path="$(dirname "${current_path}")"

  while :; do
    if [[ -L "${current_path}" ]]; then
      echo "${action_verb} ${path_label} with symlinked parent directory: ${target_path} (parent ${current_path})" >&2
      return 1
    fi

    mode="$(get_file_mode_octal "${current_path}")" || return 1
    if (( (8#${mode} & 8#022) != 0 )); then
      echo "${action_verb} ${path_label} with parent directory writable by group/other: ${target_path} (parent ${current_path}, mode ${mode})" >&2
      return 1
    fi

    if [[ "${current_path}" == "/" ]]; then
      break
    fi

    next_path="$(dirname "${current_path}")"
    if [[ "${next_path}" == "${current_path}" ]]; then
      break
    fi
    current_path="${next_path}"
  done
}

# Secret-bearing env files must not be accessible to group/other users.
require_private_env_file() {
  local env_path="$1"
  local mode

  if [[ -L "${env_path}" ]]; then
    echo "Refusing to load symlinked env file: ${env_path}" >&2
    return 1
  fi

  mode="$(get_file_mode_octal "${env_path}")" || return 1

  if (( (8#${mode} & 8#077) != 0 )); then
    echo "Refusing to load env file with group/other permissions: ${env_path} (mode ${mode})" >&2
    return 1
  fi

  require_private_parent_directories "${env_path}" "env file" "Refusing" || return 1
}

is_restricted_env_key() {
  local key="$1"

  case "${key}" in
    PATH|HOME|IFS|CDPATH|ENV|BASH_ENV|SHELLOPTS|GLOBIGNORE|PYTHONHOME|PYTHONPATH)
      return 0
      ;;
    LD_*|DYLD_*)
      return 0
      ;;
  esac

  return 1
}

# Avoid prepending shared or redirected command directories ahead of system
# binaries. Cron/refresh scripts inherit secrets and later invoke external
# tools, so only a private real directory is allowed to take PATH precedence.
prepend_private_local_bin() {
  local bin_dir="$1"
  local mode

  if [[ -z "${bin_dir}" || ! -e "${bin_dir}" ]]; then
    return 0
  fi

  if [[ ! -d "${bin_dir}" ]]; then
    echo "Skipping non-directory PATH entry: ${bin_dir}" >&2
    return 0
  fi

  if [[ -L "${bin_dir}" ]]; then
    echo "Skipping symlinked PATH entry: ${bin_dir}" >&2
    return 0
  fi

  if ! require_private_parent_directories "${bin_dir}" "PATH entry" "Skipping"; then
    return 0
  fi

  mode="$(get_file_mode_octal "${bin_dir}")" || return 1

  if (( (8#${mode} & 8#022) != 0 )); then
    echo "Skipping PATH entry writable by group/other: ${bin_dir} (mode ${mode})" >&2
    return 0
  fi

  case ":${PATH}:" in
    *":${bin_dir}:"*)
      return 0
      ;;
  esac

  export PATH="${bin_dir}:${PATH}"
}

# Parse a .env file and export each literal KEY=VALUE pair into the current
# shell. Supports blank lines, leading comments, optional `export` prefixes, and
# single- or double-quoted values without evaluating arbitrary shell syntax.
load_env_assignments() {
  local env_path="$1"
  local raw_line line key value line_number=0

  if [[ -z "${env_path}" ]]; then
    echo "load_env_assignments requires an env file path" >&2
    return 1
  fi

  if [[ ! -r "${env_path}" ]]; then
    echo "Cannot read env file: ${env_path}" >&2
    return 1
  fi

  if [[ ! -f "${env_path}" ]]; then
    echo "Env path is not a regular file: ${env_path}" >&2
    return 1
  fi

  require_private_env_file "${env_path}" || return 1

  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    line_number=$((line_number + 1))
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
      echo "Invalid .env assignment at ${env_path}:${line_number}" >&2
      return 1
    fi

    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"

    if is_restricted_env_key "${key}"; then
      echo "Refusing restricted .env key at ${env_path}:${line_number}: ${key}" >&2
      return 1
    fi

    if [[ "${value}" == \"* && ! "${value}" =~ ^\"(.*)\"$ ]]; then
      echo "Unterminated double-quoted .env value at ${env_path}:${line_number}" >&2
      return 1
    fi

    if [[ "${value}" == \'* && ! "${value}" =~ ^\'(.*)\'$ ]]; then
      echo "Unterminated single-quoted .env value at ${env_path}:${line_number}" >&2
      return 1
    fi

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
  local env_file="${1:-}"
  local system_ca_bundle="/etc/ssl/certs/ca-certificates.crt"

  if [[ -z "${env_file}" ]]; then
    if [[ -z "${repo_root:-}" ]]; then
      echo "load_civibus_env requires an env file path or repo_root to be set" >&2
      return 1
    fi
    env_file="${repo_root}/.env"
  fi

  if [[ ! -e "${env_file}" ]]; then
    echo "Missing required env file: ${env_file}" >&2
    return 1
  fi

  load_env_assignments "${env_file}" || return 1

  if [[ -n "${HOME:-}" ]]; then
    prepend_private_local_bin "${HOME}/.local/bin" || return 1
  fi

  if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    echo "POSTGRES_PASSWORD must be set in .env or the shell environment" >&2
    return 1
  fi

  # Default to the local Postgres socket target, but preserve explicit .env or
  # shell overrides for alternate local ports / forwarded connections.
  export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
  export POSTGRES_PORT="${POSTGRES_PORT:-5432}"

  # libpq-standard vars so bare psycopg.connect() works without explicit DSN
  export PGHOST="${POSTGRES_HOST}"
  export PGPORT="${POSTGRES_PORT}"
  export PGUSER="${POSTGRES_USER:-civibus}"
  export PGPASSWORD="${POSTGRES_PASSWORD}"
  export PGDATABASE="${POSTGRES_DB:-civibus}"

  # Use system CA bundle instead of Python's certifi. Certifi's bundle is
  # missing some government-site cert chains (IL/Cloudflare, CO/Entrust).
  if [[ -z "${SSL_CERT_FILE:-}" && -f "${system_ca_bundle}" ]]; then
    export SSL_CERT_FILE="${system_ca_bundle}"
  fi
}
