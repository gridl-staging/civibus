#!/usr/bin/env bash
# VM-side: commit continuous-gate evidence and findings artifacts back to origin.
#
# Resolves docs/reference/keel/open_questions.md item 2. The publish set is restricted to
# evidence/L*/, evidence/review/, and findings/ trees; the redaction blocklist
# rejects anything resembling a secret or credential. Public sync stays opt-in
# via .debbie.toml (which by design does not list these trees in its allowlist).
#
# Usage (idempotent):
#   bash infra/scripts/commit_evidence.sh           # discover, commit, push
#   bash infra/scripts/commit_evidence.sh --dry-run # preview only

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

dry_run=0
if [[ "${1:-}" == "--dry-run" ]]; then
    dry_run=1
fi

cd "${repo_root}"

paths_file="$(mktemp)"
trap 'rm -f "${paths_file}"' EXIT

# Discover the publish set (whitelist + redaction blocklist enforced in Python).
uv run python -m core.keel_evidence_commit --repo-root "${repo_root}" --print-paths > "${paths_file}"

if [[ ! -s "${paths_file}" ]]; then
    echo "no publishable evidence artifacts found"
    exit 0
fi

if [[ "${dry_run}" -eq 1 ]]; then
    echo "would publish:"
    cat "${paths_file}"
    echo
    uv run python -m core.keel_evidence_commit --repo-root "${repo_root}" --print-commit-message
    exit 0
fi

# Stage allowlisted paths only.
xargs -a "${paths_file}" git add --

# If nothing is staged after the add (e.g. files unchanged since last publish),
# skip the commit/push pair so this script stays idempotent.
if git diff --cached --quiet; then
    echo "no staged changes after add; nothing to publish"
    exit 0
fi

commit_message="$(uv run python -m core.keel_evidence_commit --repo-root "${repo_root}" --print-commit-message)"

git commit -m "${commit_message}"
git push origin "$(git rev-parse --abbrev-ref HEAD)"
