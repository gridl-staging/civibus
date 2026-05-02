#!/usr/bin/env bash
set -euo pipefail

repo_dir="${REPO_DIR:-/root/civibus/civibus_dev}"
repo_url="${REPO_URL:-https://github.com/gridl-dev/civibus_dev.git}"
env_file_source="${ENV_FILE_SOURCE:-}"
deploy_git_sha="${DEPLOY_GIT_SHA:-}"
github_token_file="${GITHUB_TOKEN_FILE:-}"

die() {
  echo "$1" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "bootstrap_prod_vm.sh must run as root"
  fi
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl git gnupg
}

install_docker_if_missing() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi

  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && printf '%s' "${ID}")/gpg" \
      -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi

  . /etc/os-release
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "${ID}" "${VERSION_CODENAME}" \
    > /etc/apt/sources.list.d/docker.list

  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

run_git_authenticated() {
  if [[ -z "${github_token_file}" ]]; then
    "$@"
    return
  fi

  if [[ ! -s "${github_token_file}" ]]; then
    die "GITHUB_TOKEN_FILE does not exist or is empty: ${github_token_file}"
  fi

  local askpass_script
  local status
  askpass_script="$(mktemp)"
  cat > "${askpass_script}" <<EOF
#!/usr/bin/env bash
case "\$1" in
  *Username*) printf '%s\n' 'x-access-token' ;;
  *Password*) cat "${github_token_file}" ;;
  *) exit 1 ;;
esac
EOF
  chmod 700 "${askpass_script}"
  if GIT_TERMINAL_PROMPT=0 GIT_ASKPASS="${askpass_script}" "$@"; then
    status=0
  else
    status=$?
  fi
  rm -f "${askpass_script}"
  return "${status}"
}

checkout_repo_revision() {
  if [[ -n "${deploy_git_sha}" ]]; then
    run_git_authenticated git -C "${repo_dir}" fetch origin "${deploy_git_sha}"
    git -C "${repo_dir}" checkout --detach "${deploy_git_sha}"
    return
  fi

  run_git_authenticated git -C "${repo_dir}" fetch origin
  git -C "${repo_dir}" checkout --detach origin/main
}

ensure_repo_checkout() {
  install -d "$(dirname "${repo_dir}")"

  if [[ ! -d "${repo_dir}/.git" ]]; then
    run_git_authenticated git clone "${repo_url}" "${repo_dir}"
  fi

  git -C "${repo_dir}" remote set-url origin "${repo_url}"
  checkout_repo_revision
}

materialize_env_file() {
  if [[ -n "${env_file_source}" ]]; then
    if [[ ! -f "${env_file_source}" ]]; then
      die "ENV_FILE_SOURCE does not exist: ${env_file_source}"
    fi
    install -m 0600 "${env_file_source}" "${repo_dir}/.env"
  fi

  if [[ ! -s "${repo_dir}/.env" ]]; then
    die "Missing required production env file at ${repo_dir}/.env"
  fi
}

validate_required_env_keys() {
  local env_file="${repo_dir}/.env"
  local missing=0
  local required_key

  for required_key in POSTGRES_PASSWORD ORIGIN CIVIBUS_API_KEYS CIVIBUS_ADMIN_API_KEYS CIVIBUS_API_KEY FEC_BULK_CYCLE; do
    if ! grep -Eq "^${required_key}=.+$" "${env_file}"; then
      echo "Missing required ${required_key} entry in ${env_file}" >&2
      missing=1
    fi
  done

  if [[ "${missing}" -ne 0 ]]; then
    exit 1
  fi
}

verify_runtime_prereqs() {
  docker compose version >/dev/null
  git -C "${repo_dir}" rev-parse HEAD >/dev/null
}

require_root
install_base_packages
install_docker_if_missing
ensure_repo_checkout
materialize_env_file
validate_required_env_keys
verify_runtime_prereqs
