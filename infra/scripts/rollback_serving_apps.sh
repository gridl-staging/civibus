#!/usr/bin/env bash
#
# Delegated owner for production serving-app rollback.
#
# Two modes:
#   capture <file>   record the image each serving app is running RIGHT NOW
#   restore <file>   redeploy each recorded image
#
# Why "the image it is running now" rather than "the last release Fly marked
# complete": release status is not a health signal. On 2026-08-03 release v102
# of civibus-api was reported `complete` while the machine crash-looped on its
# startup canary every ten seconds, so rolling back to the newest `complete`
# release would have rolled back onto the broken image. `flyctl machine list`
# reports what is actually loaded, which is the only honest rollback target.
#
# The deploy workflow calls `capture` before its first deploy and `restore` when
# production verification fails. Keeping both here — rather than inline in
# deploy.yml — mirrors how the refresh-machine deploy is delegated to
# deploy_refresh_machine.sh, and lets the behavior be tested against a stub
# flyctl in tests/ci/test_rollback_serving_apps_script.py.
#
# LIMIT, STATED PLAINLY: this restores serving CODE, not database state. Fly runs
# `release_command` (apply_migrations) to completion BEFORE the machine update,
# so a deploy that fails afterwards has already applied its migrations, and they
# are forward-only. Rolling the image back therefore leaves the deployed code
# OLDER than the applied schema. That is exactly what happened on 2026-08-03:
# failed release v99 applied the donor-rollup identity-variant migration — whose
# body deletes the rollup provenance row to fail serving closed — and the
# rollback restored an image that predates that relation, so donor search stayed
# down afterwards for a reason the rollback could not touch. Treat a restore as
# "users can load the site again", never as "the incident is over".
#
# Anchored incident: docs/live-state/2026_08_03_production_outage_restore.md
set -euo pipefail

# Every diagnostic carries this prefix so callers (and the contract tests) can
# tell "the script refused" apart from "bash could not find the script".
readonly ERROR_PREFIX="rollback_serving_apps:"

# The serving set, in deploy order, each paired with its own Fly config.
# civibus-db (holds the data) and civibus-refresh (scheduled worker) are
# deliberately absent: a failed serving deploy must never move the database.
readonly SERVING_APPS=(
  "civibus-api|infra/fly/api.fly.toml"
  "civibus-web|infra/fly/web.fly.toml"
  "civibus-caddy|infra/fly/caddy.fly.toml"
)

die() {
  echo "${ERROR_PREFIX} $*" >&2
  exit 1
}

# Look up the Fly config for an app, and simultaneously act as the allow-list:
# an app that is not in SERVING_APPS has no config and is rejected.
config_for_app() {
  local wanted="${1:?}"
  local entry
  for entry in "${SERVING_APPS[@]}"; do
    if [[ "${entry%%|*}" == "$wanted" ]]; then
      echo "${entry#*|}"
      return 0
    fi
  done
  return 1
}

capture() {
  local output="${1:-}"
  [[ -n "$output" ]] || die "capture requires an output file path"

  # Build the manifest in a temp file and move it into place only on success, so
  # a partial capture never looks like a usable rollback target.
  local staged
  staged="$(mktemp)"
  # shellcheck disable=SC2064  # expand $staged now, not at trap time
  trap "rm -f '$staged'" EXIT

  local entry app config image
  for entry in "${SERVING_APPS[@]}"; do
    app="${entry%%|*}"
    config="${entry#*|}"
    # `.[0].config.image` is the image loaded on the first (and only) machine.
    # `// empty` turns a null/absent image into an empty string rather than the
    # literal "null", so the emptiness check below is meaningful.
    image="$(flyctl machine list -a "$app" --json | jq -r '.[0].config.image // empty')"
    if [[ -z "$image" ]]; then
      die "no running image for ${app} — refusing to deploy without a rollback target"
    fi
    echo "${app}|${config}|${image}" >> "$staged"
    echo "pre_deploy_image app=${app} image=${image}"
  done

  mv "$staged" "$output"
  trap - EXIT
}

restore() {
  local manifest="${1:-}"
  [[ -n "$manifest" ]] || die "restore requires a manifest file path"
  [[ -f "$manifest" ]] || die "rollback manifest not found: ${manifest}"

  # Validate the WHOLE manifest before deploying anything. A rollback that
  # restores two apps and then rejects the third would leave production in a
  # third state that nobody has ever tested.
  local line app config image expected_config
  local -a planned=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "${line// /}" ]] || continue
    app="${line%%|*}"
    image="${line##*|}"
    config="${line#*|}"
    config="${config%%|*}"

    expected_config="$(config_for_app "$app")" ||
      die "refusing to roll back ${app}: not a serving app"
    [[ "$config" == "$expected_config" ]] ||
      die "refusing to roll back ${app}: config ${config} is not its owner ${expected_config}"
    [[ -n "$image" && "$image" != "$app" ]] ||
      die "refusing to roll back ${app}: manifest line has no image"

    planned+=("${app}|${config}|${image}")
  done < "$manifest"

  # An empty manifest means we have no idea what production was serving. Exiting
  # 0 here would report a successful rollback that restored nothing, which is
  # the single worst outcome this script can produce.
  [[ ${#planned[@]} -gt 0 ]] || die "rollback manifest is empty: ${manifest}"

  local entry
  for entry in "${planned[@]}"; do
    app="${entry%%|*}"
    image="${entry##*|}"
    config="${entry#*|}"
    config="${config%%|*}"
    echo "rolling_back app=${app} image=${image}"
    flyctl deploy --image "$image" -a "$app" -c "$config"
  done
}

main() {
  local mode="${1:-}"
  case "$mode" in
    capture) capture "${2:-}" ;;
    restore) restore "${2:-}" ;;
    *) die "unknown mode '${mode}' (expected: capture <file> | restore <file>)" ;;
  esac
}

main "$@"
