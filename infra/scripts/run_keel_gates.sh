#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# shellcheck source=infra/scripts/env_lib.sh
source "${script_dir}/env_lib.sh"
load_civibus_env

cd "${repo_root}"

# Track the worst exit status across every step so the runner reports an
# overall failure to cron without short-circuiting subsequent steps. A gate
# emitting status=fail returns exit 1 \u2014 that is normal cron output, not an
# unrecoverable error, and must NOT prevent later gates / autopublish from
# running. The `|| overall_status=$?` rescue pattern keeps `set -e` strict
# for unexpected errors (missing binaries, syntax errors) while letting
# routine non-zero gate exits flow through.
overall_status=0

make gate-L5 || overall_status=$?
make gate-L7 || overall_status=$?

# keel-reviews-status returns 0 by design (it only reports). Wrap anyway so
# any future strict mode does not silently break the runner.
make keel-reviews-status || overall_status=$?

# Autopublish evidence/findings to origin only when explicitly opted in.
# The opt-in flag (KEEL_AUTOPUBLISH_EVIDENCE=1) must be set in the cron
# environment by the operator. Without it, the VM accumulates evidence
# locally and an operator can run `infra/scripts/commit_evidence.sh`
# manually. This avoids surprising auto-pushes after this script changes.
if [[ "${KEEL_AUTOPUBLISH_EVIDENCE:-}" == "1" ]]; then
    bash "${script_dir}/commit_evidence.sh" || overall_status=$?
fi

exit "${overall_status}"
