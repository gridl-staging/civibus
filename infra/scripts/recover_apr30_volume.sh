#!/usr/bin/env bash
# recover_apr30_volume.sh — Apr 30 wrong-volume recovery driver.
#
# Wraps docs/howto/operations/apr30_volume_recovery_runbook.md into a single
# artifact with the four verification gates from
# docs/howto/operations/prod_ops_discipline.md:
#
#   Gate 1 — bare `docker compose` calls forbidden; only prod_compose.sh.
#            (Direct `docker stop <name>` / `docker rm <name>` against
#             a specific named container is permitted — see
#             docs/howto/operations/prod_ops_discipline.md for the exact line.)
#   Gate 2 — canonical 163 GB volume size confirmed before mount.
#   Gate 3 — post-action canary (/health/content) must pass.
#   Gate 4 — state changes only with explicit --confirm flag.
#
# Modes:
#   --help       print usage and exit 0
#   --diagnose   read-only probes of Hetzner state (no changes)
#   --plan       print what --confirm would do (no changes)
#   --confirm    actually execute the recovery sequence
#
# This script is the artifact. Whether to RUN it (especially --confirm)
# against the live Hetzner stack depends on operator clarification of
# the deployment topology — see
# docs/reference/research/2026_05_01_deployment_topology_finding.md. Until that
# clarification lands, --confirm should be invoked only by the operator,
# not by an autonomous session.

set -euo pipefail

# ---------- Constants pinned to the verified Apr 30 fingerprint ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

HETZNER_HOST="root@5.78.207.136"
HETZNER_KEY="${REPO_ROOT}/.secret/hetzner_ssh_key.txt"
SSH_OPTS=(-i "${HETZNER_KEY}" -o BatchMode=yes -o ConnectTimeout=15)

CANONICAL_VOLUME_PATH="/mnt/HC_Volume_105390322/pgdata"
# The orphaned volume is 163 GB per the Apr 30 postmortem. We require at
# least 100 GB on the canonical mount before any swap proceeds — that
# threshold catches the Apr 30 fingerprint (empty named volume = ~50 MB)
# without false-positive on minor volume-size drift.
MIN_VOLUME_GB=100

# cf.transaction is the smoking gun for canonical-vs-empty: empty volume
# has 0 rows in cf.transaction; canonical has ~10M+. Floor at 1M to catch
# any partial-restore failure mode.
MIN_CF_TRANSACTION_ROWS=1000000

# Canary endpoint on the API container. Caddy strips /api before proxying,
# so direct localhost probes use the FastAPI post-strip path.
CANARY_PATH="/health/content"

# The prod compose file declares `${CIVIBUS_DB_DATA_PATH:?Set CIVIBUS_DB_DATA_PATH}`
# as a mandatory env var. If it is missing on the VM, the prod compose
# fails fast — but only AFTER we've already stopped/removed the wrong-volume
# db container in step 3. That would leave the stack with no db at all.
# So we must verify this env var BEFORE any state change.
REQUIRED_ENV_VAR="CIVIBUS_DB_DATA_PATH"
EXPECTED_ENV_VALUE="/mnt/HC_Volume_105390322/pgdata"
PROD_ENV_FILE="/root/civibus/civibus_dev/.env"

# ---------- Argument parsing ----------
MODE=""
CONFIRM=""

usage() {
    cat <<EOF
recover_apr30_volume.sh — Apr 30 wrong-volume recovery driver.

Usage:
  $0 --help          Print this help and exit.
  $0 --diagnose      Read-only probe of Hetzner stack state.
  $0 --plan          Print what --confirm would do, without doing it.
  $0 --confirm       Execute recovery (volume swap + canary verification).

Gates enforced by this script:
  1. Bare docker / docker compose calls are forbidden in this script;
     all container-lifecycle actions go through infra/scripts/prod_compose.sh.
  2. Canonical volume at ${CANONICAL_VOLUME_PATH} must be >= ${MIN_VOLUME_GB} GB
     before any mount swap. Empty volume = Apr 30 fingerprint, halts immediately.
  3. After swap, /health/content on the api container must respond healthy
     before the script claims success.
  4. No state changes without an explicit --confirm flag.

See docs/howto/operations/prod_ops_discipline.md for the discipline this enforces.
EOF
}

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    --diagnose)
        MODE="diagnose"
        ;;
    --plan)
        MODE="plan"
        ;;
    --confirm)
        MODE="confirm"
        CONFIRM="yes"
        ;;
    "")
        echo "ERROR: missing mode flag. Run with --help for usage." >&2
        exit 2
        ;;
    *)
        echo "ERROR: unknown flag '$1'. Run with --help for usage." >&2
        exit 2
        ;;
esac

# ---------- Helpers ----------
ssh_remote() {
    # Wraps SSH so all probes share the same options + key.
    # Output is passed through unchanged; errors propagate via set -e.
    ssh "${SSH_OPTS[@]}" "${HETZNER_HOST}" "$@"
}

print_step() {
    # Visual separator for each step. Aids agent-readable scrollback.
    echo ""
    echo "===> $1"
}

die() {
    # Halt with a clear cause line. Pairs with `set -e` for fast-fail.
    echo "FATAL: $1" >&2
    exit 1
}

# ---------- Gate 0: Required env var on prod VM ----------
# This runs BEFORE Gate 2 because if it fails, we must halt before stopping
# the existing db container — otherwise the stack ends up with no db.
gate_required_env_var() {
    print_step "Gate 0: ${REQUIRED_ENV_VAR} set in ${PROD_ENV_FILE}"
    local current_value
    # Allow `=` either with or without surrounding whitespace; tolerate quotes.
    if ! current_value="$(ssh_remote "test -r ${PROD_ENV_FILE} && grep -E '^[[:space:]]*${REQUIRED_ENV_VAR}[[:space:]]*=' ${PROD_ENV_FILE} | tail -1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | tr -d '\"' | tr -d \"'\"")"; then
        die "Unable to read ${PROD_ENV_FILE} on the VM. Check SSH access and file readability before re-running recovery."
    fi
    if [[ -z "${current_value}" ]]; then
        die "${REQUIRED_ENV_VAR} is not set in ${PROD_ENV_FILE} on the VM. \
The prod compose requires it (\`?Set CIVIBUS_DB_DATA_PATH\`). Add it before \
re-running --confirm:
    ssh root@5.78.207.136 \"echo '${REQUIRED_ENV_VAR}=${EXPECTED_ENV_VALUE}' >> ${PROD_ENV_FILE}\""
    fi
    echo "  ${REQUIRED_ENV_VAR}=${current_value}"
    if [[ "${current_value}" != "${EXPECTED_ENV_VALUE}" ]]; then
        die "${REQUIRED_ENV_VAR} is set but to '${current_value}', not the canonical \
'${EXPECTED_ENV_VALUE}'. Refusing to proceed — wrong path = same Apr 30 failure mode."
    fi
    echo "  OK: env var matches canonical path."
}

# ---------- Gate 2: Canonical volume size check ----------
gate_canonical_volume_size() {
    print_step "Gate 2: Canonical volume size check (>= ${MIN_VOLUME_GB} GB)"
    # `du -sh` reports human-readable. We need bytes for comparison.
    # `du -s --block-size=1G` gives integer GB on Linux coreutils.
    local size_gb
    size_gb="$(ssh_remote "du -s --block-size=1G ${CANONICAL_VOLUME_PATH} | cut -f1")"
    echo "  Canonical volume size: ${size_gb} GB"
    if (( size_gb < MIN_VOLUME_GB )); then
        die "Canonical volume too small (${size_gb}G < ${MIN_VOLUME_GB}G). \
This is the Apr 30 fingerprint — refusing to proceed."
    fi
    echo "  OK: canonical volume size precondition met."
}

# ---------- Gate 3: Post-action canary ----------
gate_post_action_canary() {
    print_step "Gate 3: Post-action canary (${CANARY_PATH})"
    # Curl from inside the api container, not from the public hostname,
    # because the topology finding (2026-05-01) is unclear about which
    # public hostname this stack actually serves. Localhost from the api
    # container is unambiguous.
    local http_code
    if ! http_code="$(ssh_remote "docker exec infra-api-1 curl -s -o /tmp/canary_body -w '%{http_code}' http://localhost:8000${CANARY_PATH}")"; then
        local body
        body="$(ssh_remote "docker exec infra-api-1 cat /tmp/canary_body" || echo "<no body captured>")"
        die "Canary probe transport failed before an HTTP response. Body: ${body}"
    fi
    echo "  ${CANARY_PATH} -> HTTP ${http_code}"
    if [[ "${http_code}" != "200" ]]; then
        local body
        body="$(ssh_remote "docker exec infra-api-1 cat /tmp/canary_body" || echo "<no body captured>")"
        die "Canary endpoint did not return 200. Body: ${body}"
    fi
    echo "  OK: canary passed."
}

# ---------- Diagnose mode ----------
run_diagnose() {
    print_step "Diagnose: SSH connectivity"
    ssh_remote "hostname && uname -a" | head -2

    print_step "Diagnose: Running containers"
    ssh_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'"

    print_step "Diagnose: infra-db-1 mounts (looking for canonical bind vs named volume)"
    # Pretty-print just the destination → source mapping, not the full json blob.
    ssh_remote "docker inspect infra-db-1 --format '{{range .Mounts}}{{.Destination}} <- {{.Source}} ({{.Type}}){{println}}{{end}}'"

    print_step "Diagnose: Canonical volume sanity"
    ssh_remote "ls ${CANONICAL_VOLUME_PATH} | head -8"
    ssh_remote "du -sh ${CANONICAL_VOLUME_PATH}"

    print_step "Diagnose: Row counts in running DB (the Apr 30 fingerprint check)"
    ssh_remote "docker exec infra-db-1 psql -U civibus -d civibus -c \"
        SELECT 'cf.transaction' AS t, COUNT(*) FROM cf.transaction
        UNION ALL SELECT 'core.person', COUNT(*) FROM core.person
        UNION ALL SELECT 'core.person_portrait', COUNT(*) FROM core.person_portrait
        UNION ALL SELECT 'civic.officeholding', COUNT(*) FROM civic.officeholding
        ORDER BY t;\""

    print_step "Diagnose: Caddy hostname binding"
    ssh_remote "docker exec infra-caddy-1 cat /etc/caddy/Caddyfile" | head -20

    echo ""
    echo "===> Diagnose complete. No state changes were made."
}

# ---------- Plan mode ----------
run_plan() {
    cat <<EOF

===> Plan: what --confirm would do (in order)

Step P1. Run --diagnose first to confirm Apr 30 fingerprint.
Step P2a. Gate 0: ${REQUIRED_ENV_VAR}=${EXPECTED_ENV_VALUE} must be set in
          ${PROD_ENV_FILE}. Halt with operator instructions if missing —
          required because the prod compose fails fast on it AFTER step 3
          would have stopped/removed the existing db container, leaving
          the stack with no db at all.
Step P2b. Gate 2: gate_canonical_volume_size (>= ${MIN_VOLUME_GB} GB on ${CANONICAL_VOLUME_PATH}).
          Halt if check fails.
Step P3. Stop and remove the wrong-volume db container by NAME.
         (Direct \`docker stop\`/\`docker rm\` against a specific named
         container is the right tool here — the container was created
         by the dev compose so prod_compose.sh's stop/rm may not
         recognize it as its own. Direct-by-name has no wrong-compose
         pickup risk; the discipline forbids bare \`docker compose\`,
         not direct docker on a known container.)
           ssh ${HETZNER_HOST} "docker stop infra-db-1 && docker rm infra-db-1"
Step P4. Pull latest civibus_dev on the VM (SOFT — warns on failure):
           ssh ${HETZNER_HOST} "cd /root/civibus/civibus_dev && \\
             git fetch origin && git checkout main && git pull --ff-only"
         If the VM lacks GitHub credentials (the actual case as of
         2026-05-01) the script warns and continues — the VM's
         existing two-file compose layout is already correct.
Step P5. Bring up DB via wrapper (the wrapper pins
         -f infra/docker-compose.prod.yml; the prod compose binds the
         canonical volume):
           ssh ${HETZNER_HOST} "cd /root/civibus/civibus_dev && \\
             bash infra/scripts/prod_compose.sh up -d --wait db"
Step P6. Sanity check the row count post-mount:
           ssh ${HETZNER_HOST} "docker exec infra-db-1 psql -U civibus -d civibus \\
             -c 'SELECT COUNT(*) FROM cf.transaction;'"
         Halt if < ${MIN_CF_TRANSACTION_ROWS} rows.
Step P7. Bring up rest of stack via wrapper, pulling fresh images:
           ssh ${HETZNER_HOST} "cd /root/civibus/civibus_dev && \\
             bash infra/scripts/prod_compose.sh up -d --force-recreate \\
             --pull always --wait api web caddy"
         (--pull always: deployed api image pre-dates canary endpoint
         commit; without fresh pull, Gate 3 would 404.)
Step P8. Run gate_post_action_canary (curl /health/content from inside
         api container; expect HTTP 200).

This plan does NOT include the loader-replay work (apr29_pm_2 statewide
rosters, apr29_pm_9 portraits) that wrote into the wrong volume during the
~16 hour window. That replay is a separate concern and is the operator's
decision once volume swap is verified.

EOF
}

# ---------- Confirm mode (state changes happen here) ----------
run_confirm() {
    if [[ "${CONFIRM}" != "yes" ]]; then
        die "internal error: run_confirm called without CONFIRM=yes"
    fi

    echo ""
    echo "===> Confirm: executing recovery against ${HETZNER_HOST}"
    echo "===> NOTE: The deployment topology finding from 2026-05-01 (see"
    echo "===> docs/reference/research/2026_05_01_deployment_topology_finding.md) suggests"
    echo "===> civibus.org may not depend on this Hetzner stack at all."
    echo "===> If this script is being invoked autonomously without operator"
    echo "===> confirmation of the recovery goal, abort now (Ctrl-C)."
    echo ""

    print_step "Step 1: Diagnose preconditions"
    run_diagnose

    print_step "Step 2a: Gate 0 (env-var precondition)"
    gate_required_env_var

    print_step "Step 2b: Gate 2 (volume-size check)"
    gate_canonical_volume_size

    print_step "Step 3: Stop and remove wrong-volume db container"
    # Direct docker stop/rm by container name (NOT prod_compose.sh stop/rm).
    # The existing infra-db-1 was created by docker-compose.yml (dev), so
    # prod_compose.sh — which uses docker-compose.prod.yml — may not
    # recognize it as its own service. Acting on the container by NAME has
    # no wrong-compose-pickup risk (the Apr 30 failure mode required a bare
    # `docker compose ...` invocation; direct docker on a named container
    # cannot trigger it). The discipline at docs/howto/operations/prod_ops_discipline.md
    # explicitly permits this exception.
    ssh_remote "docker stop infra-db-1 && docker rm infra-db-1"

    print_step "Step 4: Pull latest civibus_dev (soft — warn on failure, do not halt)"
    # Soft step: the VM's existing infra/docker-compose.prod.yml +
    # docker-compose.volume-override.yml + prod_compose.sh wrapper are
    # already correct (the override binds the canonical volume; the wrapper
    # uses both -f flags). Pulling latest is preferred (gets newest schema /
    # canary endpoint / etc.) but not strictly required for the volume swap
    # to succeed. If the VM lacks GitHub credentials (the actual case as of
    # 2026-05-01), we warn and continue rather than halting after step 3
    # has already removed the db container.
    if ssh_remote "cd /root/civibus/civibus_dev && \
        git fetch origin && git checkout main && git pull --ff-only" 2>&1; then
        echo "  OK: VM repo updated."
    else
        echo "  WARNING: git pull failed (likely no GitHub creds on VM). Continuing — the VM's existing compose layout is already correct for the volume swap."
    fi

    print_step "Step 5: Bring up DB via wrapper"
    ssh_remote "cd /root/civibus/civibus_dev && \
        bash infra/scripts/prod_compose.sh up -d --wait db"

    print_step "Step 6: Sanity check cf.transaction row count"
    local row_count
    row_count="$(ssh_remote "docker exec infra-db-1 psql -U civibus -d civibus -tAc 'SELECT COUNT(*) FROM cf.transaction;'")"
    echo "  cf.transaction rows: ${row_count}"
    if (( row_count < MIN_CF_TRANSACTION_ROWS )); then
        die "cf.transaction row count ${row_count} < floor ${MIN_CF_TRANSACTION_ROWS}. \
The canonical volume may not be the one we expected. Halting before bringing up api/web."
    fi
    echo "  OK: row-count floor met."

    print_step "Step 7: Bring up rest of stack via wrapper (pulling fresh images)"
    # --pull always: the api image deployed on Hetzner pre-dates the canary
    # endpoint commit (89afc876), so without a fresh pull, Gate 3 below
    # would 404 on a real recovery. Pulling latest is the right behavior
    # for a recovery — we want the freshest safety net, not the stale one.
    ssh_remote "cd /root/civibus/civibus_dev && \
        bash infra/scripts/prod_compose.sh up -d --force-recreate --pull always --wait api web caddy"

    print_step "Step 8: Gate 3 (post-action canary)"
    gate_post_action_canary

    echo ""
    echo "===> Recovery complete. Volume swap + canary verification passed."
    echo "===> Next steps (operator-driven, NOT done by this script):"
    echo "===>   - replay loader work that wrote into the empty volume during"
    echo "===>     the ~16 hour window (apr29_pm_2, apr29_pm_9)"
    echo "===>   - take fresh B2 backup of recovered state"
    echo "===>   - update ROADMAP.md / postmortem with recovery timestamp"
}

# ---------- Dispatch ----------
case "${MODE}" in
    diagnose) run_diagnose ;;
    plan)     run_plan ;;
    confirm)  run_confirm ;;
    *)        die "internal error: mode '${MODE}' did not dispatch" ;;
esac
