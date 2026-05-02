#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
web_dir="${repo_root}/web"
lockfile_path="${web_dir}/package-lock.json"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to bootstrap L10 gate dependencies" >&2
  exit 1
fi

if [[ ! -f "${lockfile_path}" ]]; then
  echo "web/package-lock.json is required for deterministic npm ci" >&2
  exit 1
fi

cd "${web_dir}"
npm ci
