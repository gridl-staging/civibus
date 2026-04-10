#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

npx --yes @playwright/test@1.56.0 --version >/dev/null
runner_bin="$(ls -td "$HOME"/.npm/_npx/*/node_modules/.bin/playwright | head -n 1)"
runner_root="$(cd "$(dirname "$runner_bin")/.." && pwd)"

mkdir -p node_modules
ln -sfn "$runner_root/playwright" node_modules/playwright
ln -sfn "$runner_root/playwright-core" node_modules/playwright-core

"$runner_root/.bin/playwright" install chromium >/dev/null

if [[ "${1:-}" == "--" ]]; then
  shift
fi

exec "$runner_root/.bin/playwright" test --config playwright.config.ts "$@"
