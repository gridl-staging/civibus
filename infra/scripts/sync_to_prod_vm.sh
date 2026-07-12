#!/usr/bin/env bash
# sync_to_prod_vm.sh — push the local repo to the Hetzner prod VM via rsync.
#
# Replaces the historical "git pull on the VM" pattern (which required
# a GitHub PAT on the VM, since the org has deploy keys disabled). rsync
# uses the existing SSH key the operator already trusts; no new secrets
# on prod, nothing to rotate.
#
# Modes:
#   default        --dry-run; prints what would change without changing anything.
#   --apply        actually run the sync.
#   --help         print usage and exit.
#
# What gets synced: the source-repo working tree, MINUS the exclude list
# below. Everything that the cron jobs, prod_compose.sh, or the db
# init-scripts on the VM might read is included; runtime artifacts,
# secrets, and dev-only files are excluded.
#
# Authorization: this is a "non-secret prod config" change per
# docs/howto/operations/prod_ops_discipline.md "Default to action — authorization
# scope". AI agents may run --dry-run freely. --apply is permitted when
# changes are intended (it's a deploy, not a recovery).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

HETZNER_HOST="root@5.78.207.136"
HETZNER_KEY="${REPO_ROOT}/.secret/hetzner_ssh_key.txt"
VM_REPO_PATH="/root/civibus/civibus_dev"

# Exclude list — comments explain WHY each path is excluded so a future
# editor doesn't strip an entry without thinking. If you add a new entry,
# add a comment for it too.
RSYNC_EXCLUDES=(
    # Git plumbing — the VM doesn't run git commands; including .git would
    # also produce noisy diffs every time pack-files differ between sides
    # (different gc timing, etc.). The source-repo is the authoritative
    # commit state; the VM's working tree is just deployed code.
    --exclude='.git'
    --exclude='.git/'
    --exclude='.gitignore'

    # Runtime artifacts — big and regenerable.
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='*.pyo'
    --exclude='.pytest_cache/'
    --exclude='.ruff_cache/'
    --exclude='.mypy_cache/'
    --exclude='.coverage'
    --exclude='web/test-results/'

    # Per-machine env / secrets — VM has its own, never overwrite.
    --exclude='.env'
    --exclude='.env.*'
    --exclude='.secret/'

    # Dev tooling state — not needed on prod.
    --exclude='.venv/'
    --exclude='node_modules/'
    --exclude='.matt/'
    --exclude='.claude/'
    --exclude='.cursor/'
    --exclude='.vscode/'
    --exclude='.hashbrown/'
    --exclude='.batman.toml'

    # Build artifacts — regenerated at deploy time.
    --exclude='web/.svelte-kit/'
    --exclude='web/build/'
    --exclude='web/dist/'

    # Local data dumps + scratch — VM data/ and generated research artifacts
    # are host-local and should not be deleted by repo sync.
    --exclude='data/'
    --exclude='docs/reference/research/artifacts/'
    --exclude='docs/reference/research/portal_contracts/'
    --exclude='docs/reference/research/portal_contracts/runs/'
    --exclude='**/research_artifacts/'
    --exclude='**/*.shp'
    --exclude='**/*.shx'
    --exclude='**/*.dbf'

    # macOS noise.
    --exclude='.DS_Store'
)

usage() {
    cat <<EOF
sync_to_prod_vm.sh — push local repo to Hetzner prod VM via rsync.

Usage:
  $0                Run --dry-run by default (no changes).
  $0 --apply        Actually perform the sync.
  $0 --help         Print this help and exit.

Source: ${REPO_ROOT}/
Target: ${HETZNER_HOST}:${VM_REPO_PATH}/
Key:    ${HETZNER_KEY}

The exclude list (in script source) covers env files, secrets, runtime
artifacts, dev-tooling state, and build outputs. Read the source for
the full list and the per-entry rationale.

After --apply: the VM's working tree matches the source-repo's tree
for the included paths. The VM's .env, .secret/, and runtime logs are
preserved. Cron jobs pick up new script versions on their next run;
container restarts pick up new compose / schema-init files when the
operator next runs prod_compose.sh.
EOF
}

MODE="dry-run"
case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --apply)   MODE="apply" ;;
    "")        MODE="dry-run" ;;
    *)
        echo "ERROR: unknown flag '$1'. Run with --help for usage." >&2
        exit 2
        ;;
esac

if [[ ! -f "${HETZNER_KEY}" ]]; then
    echo "FATAL: SSH key not found at ${HETZNER_KEY}" >&2
    exit 1
fi

RSYNC_OPTS=(
    -avz                    # archive (preserves perms/links/times), verbose, compressed
    --delete-after          # delete remote files not in source AFTER successful transfer
                            # (so a failure mid-transfer doesn't leave the VM half-deleted)
    -e "ssh -i ${HETZNER_KEY} -o BatchMode=yes -o ConnectTimeout=15"
    "${RSYNC_EXCLUDES[@]}"
)

if [[ "${MODE}" = "dry-run" ]]; then
    echo "===> DRY RUN — no changes will be made. Use --apply to actually sync."
    echo ""
    rsync "${RSYNC_OPTS[@]}" --dry-run --itemize-changes \
        "${REPO_ROOT}/" "${HETZNER_HOST}:${VM_REPO_PATH}/" | tail -200
    echo ""
    echo "===> Dry run complete. Re-run with --apply to perform the sync."
else
    echo "===> APPLY — syncing ${REPO_ROOT}/ -> ${HETZNER_HOST}:${VM_REPO_PATH}/"
    echo ""
    rsync "${RSYNC_OPTS[@]}" "${REPO_ROOT}/" "${HETZNER_HOST}:${VM_REPO_PATH}/"
    echo ""
    echo "===> Sync complete."
    echo ""
    echo "===> Note: .git is NOT synced — the VM's working tree now reflects"
    echo "===> the source-repo's tree, but the VM's .git directory (if any)"
    echo "===> still points at whatever commit existed there before. To know"
    echo "===> what is deployed, ask the source repo, not the VM."
fi
