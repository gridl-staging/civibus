"""Deploy workflow contract tests for the Fly production deploy lane."""

from pathlib import Path
import shlex
import tomllib

import pytest
import yaml

import core.keel_gate_l13 as keel_gate_l13


REPO_ROOT = Path(__file__).resolve().parents[2]
DEBBIE_CONFIG_PATH = REPO_ROOT / ".debbie.toml"
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/deploy.yml"
FLY_DEPLOY_COMMANDS = [
    "flyctl deploy -c infra/fly/api.fly.toml --remote-only "
    "--build-arg CIVIBUS_GIT_SHA=${{ steps.provenance.outputs.dev_sha }} "
    "--build-arg CIVIBUS_BUILT_AT=${{ steps.provenance.outputs.built_at }}",
    'flyctl deploy web -c "$GITHUB_WORKSPACE/infra/fly/web.fly.toml" --remote-only '
    "--build-arg CIVIBUS_GIT_SHA=${{ steps.provenance.outputs.dev_sha }} "
    "--build-arg CIVIBUS_BUILT_AT=${{ steps.provenance.outputs.built_at }}",
    "flyctl deploy -c infra/fly/caddy.fly.toml --remote-only",
]
FORBIDDEN_DEPLOY_TARGETS = (
    "infra/fly/db.fly.toml",
    "infra/fly/refresh.fly.toml",
    "civibus-db",
    "civibus-refresh",
)
L13_OWNER_FILES = {
    ".github/workflows/deploy.yml",
    "infra/fly/api.fly.toml",
    "infra/fly/web.fly.toml",
    "infra/fly/caddy.fly.toml",
}
PUBLIC_CI_SUPPORT_FILES = {
    "scripts/register_roster_pilot_sources.py",
    "scripts/stage_close_gate.py",
}
PUBLIC_CI_SUPPORT_DIRS = {
    "docs/reference/research/artifacts/2026_04_29_dwo_county_muni",
    "evidence_schemas",
}


def _read_deploy_workflow() -> str:
    return DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")


def _parse_deploy_workflow() -> dict:
    payload = yaml.safe_load(_read_deploy_workflow())
    assert isinstance(payload, dict), "deploy.yml must parse as a YAML mapping"
    return payload


def _parse_debbie_config() -> dict:
    payload = tomllib.loads(DEBBIE_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), ".debbie.toml must parse as a TOML mapping"
    return payload


def _workflow_triggers(workflow_config: dict) -> dict:
    return workflow_config.get("on", workflow_config.get(True, {}))


def _deploy_job() -> dict:
    return _parse_deploy_workflow()["jobs"]["deploy"]


def _deploy_steps() -> list[dict]:
    return _deploy_job().get("steps", [])


def _find_step(step_name: str) -> dict:
    for step in _deploy_steps():
        if step.get("name") == step_name:
            return step
    raise AssertionError(f"deploy step {step_name!r} is required")


def _run_scripts() -> list[str]:
    return [step.get("run", "") for step in _deploy_steps() if "run" in step]


REFRESH_MACHINE_STEP_NAME = "Deploy refresh machine"
PRE_DEPLOY_CAPTURE_STEP_NAME = "Capture pre-deploy serving images"
ROLLBACK_STEP_NAME = "Roll back serving apps on failed production verification"
ROLLBACK_SCRIPT = "infra/scripts/rollback_serving_apps.sh"
SERVING_DEPLOY_STEP_NAMES = (
    "Deploy API to Fly",
    "Deploy web to Fly",
    "Deploy Caddy to Fly",
)
# The steps that decide whether production is actually serving what we just
# built. A failure in any of them means users are looking at a broken site.
PRODUCTION_VERIFICATION_STEP_NAMES = (
    "Verify public deploy serves built dev SHA",
    "Run deployed surface parity gate",
    "Run production smoke gate",
)
# Step ids the rollback condition must consult. `smoke_deps` (npm ci) is
# deliberately absent: a tooling failure while installing Playwright says
# nothing about production health, and rolling back on it would undo a deploy
# that already passed SHA and parity verification.
ROLLBACK_TRIGGER_STEP_IDS = (
    "deploy_api",
    "deploy_web",
    "deploy_caddy",
    "verify_sha",
    "parity_gate",
    "smoke_gate",
)
REFRESH_DEPLOY_INVOCATION = (
    'bash infra/scripts/deploy_refresh_machine.sh --evidence-dir "$evidence" '
    '--dev-sha "${{ steps.provenance.outputs.dev_sha }}"'
)
REFRESH_VERIFIER_SCRIPT = "infra/scripts/verify_refresh_machine.sh"
REFRESH_EVIDENCE_ARTIFACT_STEP_NAME = "Persist refresh deploy evidence"
REFRESH_EVIDENCE_ARTIFACT_ACTION = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


def _assert_single_delegated_refresh_deploy(steps: list[dict]) -> None:
    """Whole-workflow single-delegation contract for the refresh machine deploy.

    Scoped to the entire parsed step list, not just the first matching step, so a
    duplicated destructive deploy step or a stray workflow-wide verifier call is caught.
    """
    step_names = [step.get("name") for step in steps]
    all_scripts = "\n".join(step.get("run", "") for step in steps if "run" in step)

    assert step_names.count(REFRESH_MACHINE_STEP_NAME) == 1, (
        "exactly one refresh-machine deploy step is allowed across the whole workflow"
    )
    assert all_scripts.count(REFRESH_DEPLOY_INVOCATION) == 1, (
        "exactly one workflow-wide deploy_refresh_machine.sh invocation is allowed"
    )
    assert REFRESH_VERIFIER_SCRIPT not in all_scripts, (
        "verify_refresh_machine.sh is owned by the deploy script, not workflow YAML"
    )


def _assert_refresh_deploy_uses_manifest_dev_sha(steps: list[dict]) -> None:
    refresh_steps = [step for step in steps if step.get("name") == REFRESH_MACHINE_STEP_NAME]
    assert len(refresh_steps) == 1
    refresh_script = refresh_steps[0]["run"]
    assert refresh_script.count(REFRESH_DEPLOY_INVOCATION) == 1, (
        "refresh deploy must receive the validated manifest dev SHA"
    )


def _assert_production_verification_precedes_refresh_machine(steps: list[dict]) -> None:
    """Production verification must not be reachable only through the refresh-machine step.

    GitHub Actions skips every following step once one fails, so ordering *is*
    the gate here — no `if:` is involved. On 2026-08-03 the refresh-machine
    deploy failed in run 30823303168 and took `Verify public deploy serves built
    dev SHA`, `Run deployed surface parity gate`, and `Run production smoke
    gate` down with it as `skipped`. API, web, and caddy had already shipped, so
    the pipeline published a crash-looping API and then skipped every check that
    would have noticed.

    `civibus-refresh` serves no user traffic. It is the least important thing in
    this workflow and it must therefore be deployed last, after the surfaces
    that users actually load have been proven healthy.
    """
    step_names = [step.get("name") for step in steps]
    assert REFRESH_MACHINE_STEP_NAME in step_names, "refresh-machine deploy step is required"
    refresh_position = step_names.index(REFRESH_MACHINE_STEP_NAME)

    for verification_step_name in PRODUCTION_VERIFICATION_STEP_NAMES:
        assert verification_step_name in step_names, f"missing verification step {verification_step_name!r}"
        assert step_names.index(verification_step_name) < refresh_position, (
            f"{verification_step_name!r} runs after {REFRESH_MACHINE_STEP_NAME!r}, so a refresh-machine "
            "failure silently skips production verification"
        )


def _assert_rollback_is_gated_on_serving_outcomes(steps: list[dict]) -> None:
    """The rollback must fire for serving failures and only for serving failures.

    A bare `if: ${{ failure() }}` is wrong in both directions: it would roll
    production back when the refresh machine fails (undoing a healthy deploy),
    and it reads as if every failure is a production failure. The condition must
    name the serving and verification step outcomes explicitly.
    """
    step_names = [step.get("name") for step in steps]
    assert ROLLBACK_STEP_NAME in step_names, "a rollback step is required for failed production verification"
    rollback_step = steps[step_names.index(ROLLBACK_STEP_NAME)]
    condition = rollback_step.get("if", "")

    assert condition, "rollback step must carry an explicit `if:` condition"
    assert condition.strip() not in {"${{ failure() }}", "failure()"}, (
        "a bare failure() condition would roll production back when the refresh machine fails"
    )
    assert REFRESH_MACHINE_STEP_NAME not in condition
    assert "steps.deploy_refresh" not in condition, (
        "the refresh machine serves no user traffic; its outcome must not trigger a production rollback"
    )
    for step_id in ROLLBACK_TRIGGER_STEP_IDS:
        assert f"steps.{step_id}.outcome" in condition, f"rollback condition must consult steps.{step_id}.outcome"
    # The rollback is only meaningful if we actually captured a target.
    assert "steps.pre_deploy.outcome == 'success'" in condition


def _fly_deploy_commands() -> list[str]:
    return [
        line.strip()
        for script in _run_scripts()
        for line in script.splitlines()
        if line.strip().startswith("flyctl deploy")
    ]


def _deploy_config_path_is_workspace_anchored(config_path: str) -> bool:
    return Path(config_path).is_absolute() or config_path.startswith("$GITHUB_WORKSPACE/")


def _fly_deploy_command_has_positional_workdir_before_config(command: str) -> bool:
    tokens = shlex.split(command)
    assert tokens[:2] == ["flyctl", "deploy"], f"unexpected deploy command: {command}"
    config_index = tokens.index("-c")
    return any(not token.startswith("-") for token in tokens[2:config_index])


def _fly_deploy_config_path(command: str) -> str:
    tokens = shlex.split(command)
    config_index = tokens.index("-c")
    return tokens[config_index + 1]


def test_deploy_workflow_exists_and_parses_cleanly() -> None:
    parsed = _parse_deploy_workflow()
    assert isinstance(parsed, dict)


def test_l13_contract_owner_file_set_is_locked_to_fly_deploy_surface() -> None:
    owner_files = set(keel_gate_l13.CONTRACT_OWNER_FILES.values())
    assert owner_files == L13_OWNER_FILES
    for relative_path in owner_files:
        assert (REPO_ROOT / relative_path).is_file(), f"L13 owner file missing: {relative_path}"


def test_public_ci_support_scripts_sync_to_staging_and_prod() -> None:
    for relative_path in PUBLIC_CI_SUPPORT_FILES:
        assert (REPO_ROOT / relative_path).is_file(), f"public CI support file missing: {relative_path}"

    for relative_path in PUBLIC_CI_SUPPORT_DIRS:
        assert (REPO_ROOT / relative_path).is_dir(), f"public CI support directory missing: {relative_path}"

    if not DEBBIE_CONFIG_PATH.exists():
        return

    debbie_payload = _parse_debbie_config()
    sync_files = set(debbie_payload["sync"]["files"])
    sync_dirs = {entry["path"].rstrip("/") for entry in debbie_payload["sync"]["dirs"]}

    assert PUBLIC_CI_SUPPORT_FILES.issubset(sync_files)
    assert PUBLIC_CI_SUPPORT_DIRS.issubset(sync_dirs)


def test_deploy_workflow_triggers_on_push_to_main_and_manual_dispatch_only() -> None:
    parsed = _parse_deploy_workflow()
    triggers = _workflow_triggers(parsed)

    assert triggers["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers


def test_deploy_workflow_has_single_guarded_production_job() -> None:
    parsed = _parse_deploy_workflow()
    jobs = parsed["jobs"]
    deploy_job = jobs["deploy"]

    assert set(jobs) == {"deploy"}
    assert deploy_job["runs-on"] == "ubuntu-latest"
    assert deploy_job["environment"] == "production"
    assert deploy_job["if"] == "github.repository == 'gridl-hq/civibus'"
    assert parsed["permissions"] == {"contents": "read"}
    assert deploy_job.get("permissions", {"contents": "read"}) == {"contents": "read"}


def test_deploy_workflow_uses_fly_token_secret_and_smoke_url_variable() -> None:
    deploy_env = _deploy_job()["env"]

    assert deploy_env["FLY_API_TOKEN"] == "${{ secrets.FLY_API_TOKEN }}"
    assert deploy_env["PROD_SMOKE_BASE_URL"] == "${{ vars.PROD_SMOKE_BASE_URL }}"


def test_deploy_workflow_uses_checkout_uv_and_flyctl_setup_only() -> None:
    workflow_text = _read_deploy_workflow()
    setup_steps = [step for step in _deploy_steps() if "uses" in step]

    assert "actions/checkout@" in workflow_text
    assert "superfly/flyctl-actions/setup-flyctl" in workflow_text
    assert {
        "uses": "astral-sh/setup-uv@0c5e2b8115b80b4c7c5ddf6ffdd634974642d182",
        "with": {"python-version": "3.12"},
    } in setup_steps
    forbidden_fragments = (
        "docker/login-action",
        "docker/build-push-action",
        "packages: write",
        "ghcr.io/",
        "secrets.GITHUB_TOKEN",
        "HETZNER_",
        "PRODUCTION_ENV_FILE",
        "known_hosts",
        "ssh ",
        "scp ",
        "prod_compose.sh",
        "bootstrap_prod_vm.sh",
    )
    for fragment in forbidden_fragments:
        assert fragment not in workflow_text, f"deploy.yml must not keep obsolete {fragment!r} plumbing"


def test_deploy_workflow_runs_exactly_three_serving_fly_deploys() -> None:
    deploy_scripts = [script for script in _run_scripts() if "flyctl deploy" in script]
    workflow_text = _read_deploy_workflow()

    assert len(deploy_scripts) == len(FLY_DEPLOY_COMMANDS)
    for deploy_command in FLY_DEPLOY_COMMANDS:
        assert workflow_text.count(deploy_command) == 1

    deploy_positions = [workflow_text.index(deploy_command) for deploy_command in FLY_DEPLOY_COMMANDS]
    assert deploy_positions == sorted(deploy_positions)


def test_positional_fly_deploy_workdirs_use_workspace_anchored_config_paths() -> None:
    for command in _fly_deploy_commands():
        if not _fly_deploy_command_has_positional_workdir_before_config(command):
            continue

        config_path = _fly_deploy_config_path(command)
        assert _deploy_config_path_is_workspace_anchored(config_path), (
            f"{command!r} has a positional deploy workdir before -c, so the config path must be absolute "
            "or $GITHUB_WORKSPACE-anchored"
        )


def test_deploy_workflow_resolves_dev_sha_from_sync_manifest() -> None:
    provenance_step = _find_step("Resolve dev build provenance")
    script = provenance_step["run"]

    assert provenance_step.get("id") == "provenance", "provenance step must expose an id for step outputs"
    # Reads the dev SHA from the prod-mirror sync manifest, NOT ${{ github.sha }}.
    assert ".debbie/sync_manifest.json" in script
    assert "github.sha" not in script
    assert ".dev_sha" in script
    # Fails loud on a missing manifest or a non-40-char-hex SHA — never degrades
    # to stamping "unknown".
    assert "^[0-9a-f]{40}$" in script
    assert "exit 1" in script
    # Both provenance values are exported for the deploy steps to consume.
    assert "dev_sha=" in script
    assert "built_at=" in script
    assert "$GITHUB_OUTPUT" in script


def test_deploy_workflow_passes_dev_provenance_build_args_to_api_and_web() -> None:
    for step_name in ("Deploy API to Fly", "Deploy web to Fly"):
        run_script = _find_step(step_name)["run"]
        assert "--build-arg CIVIBUS_GIT_SHA=${{ steps.provenance.outputs.dev_sha }}" in run_script
        assert "--build-arg CIVIBUS_BUILT_AT=${{ steps.provenance.outputs.built_at }}" in run_script

    caddy_script = _find_step("Deploy Caddy to Fly")["run"]
    assert "--build-arg" not in caddy_script, "caddy is a bare reverse proxy — no provenance stamp"


def test_deploy_workflow_never_deploys_db_or_refresh_apps() -> None:
    """Keep target details in the delegated refresh deploy owner, not workflow YAML."""
    workflow_text = _read_deploy_workflow()

    for forbidden_target in FORBIDDEN_DEPLOY_TARGETS:
        assert forbidden_target not in workflow_text


def test_deploy_workflow_delegates_refresh_machine_deploy_after_serving_deploys() -> None:
    deploy_steps = _deploy_steps()
    step_names = [step.get("name") for step in deploy_steps]
    refresh_step = _find_step("Deploy refresh machine")
    refresh_script = refresh_step["run"]

    assert refresh_step["name"] == "Deploy refresh machine"
    assert refresh_step["shell"] == "bash"
    assert refresh_script.splitlines()[0] == "set -euo pipefail"
    assert 'evidence="$RUNNER_TEMP/refresh_deploy_evidence"' in refresh_script
    assert 'mkdir -p "$evidence"' in refresh_script
    assert refresh_script.count(REFRESH_DEPLOY_INVOCATION) == 1
    for delegated_owner_literal in (
        "infra/scripts/verify_refresh_machine.sh",
        "civibus-refresh",
        "infra/fly/refresh.fly.toml",
    ):
        assert delegated_owner_literal not in refresh_script

    refresh_position = step_names.index("Deploy refresh machine")
    for serving_step_name in SERVING_DEPLOY_STEP_NAMES:
        assert step_names.index(serving_step_name) < refresh_position
    # Inverted 2026-08-03. This assertion previously required the refresh-machine
    # deploy to run BEFORE production verification, which is the ordering that
    # caused the outage: the refresh step failed and every verification step was
    # skipped behind it. The refresh machine is now last, and
    # `_assert_production_verification_precedes_refresh_machine` owns that rule.
    assert refresh_position > step_names.index("Verify public deploy serves built dev SHA")


def test_deploy_workflow_delegates_refresh_deploy_exactly_once_workflow_wide() -> None:
    _assert_single_delegated_refresh_deploy(_deploy_steps())
    _assert_refresh_deploy_uses_manifest_dev_sha(_deploy_steps())


def test_production_verification_runs_before_the_refresh_machine_deploy() -> None:
    _assert_production_verification_precedes_refresh_machine(_deploy_steps())


def test_refresh_machine_before_verification_fails_the_ordering_contract() -> None:
    """Self-check: the ordering guard must reject the exact layout that caused the outage."""
    steps = [dict(step) for step in _deploy_steps()]
    refresh_step = next(step for step in steps if step.get("name") == REFRESH_MACHINE_STEP_NAME)
    steps.remove(refresh_step)
    verification_position = min(
        index for index, step in enumerate(steps) if step.get("name") in PRODUCTION_VERIFICATION_STEP_NAMES
    )
    steps.insert(verification_position, refresh_step)

    with pytest.raises(AssertionError, match="silently skips production verification"):
        _assert_production_verification_precedes_refresh_machine(steps)


def test_deploy_workflow_captures_a_rollback_target_before_the_first_deploy() -> None:
    steps = _deploy_steps()
    step_names = [step.get("name") for step in steps]
    capture_step = _find_step(PRE_DEPLOY_CAPTURE_STEP_NAME)

    assert capture_step.get("id") == "pre_deploy", "capture step must expose an id the rollback condition can read"
    capture_position = step_names.index(PRE_DEPLOY_CAPTURE_STEP_NAME)
    for serving_step_name in SERVING_DEPLOY_STEP_NAMES:
        assert capture_position < step_names.index(serving_step_name), (
            "the rollback target must be captured before anything is deployed over it"
        )
    # Delegated to the rollback owner so the workflow YAML holds no app or image
    # plumbing of its own, matching how the refresh-machine deploy is delegated.
    assert f"bash {ROLLBACK_SCRIPT} capture" in capture_step["run"]


def test_deploy_workflow_rolls_back_serving_apps_on_failed_production_verification() -> None:
    _assert_rollback_is_gated_on_serving_outcomes(_deploy_steps())

    steps = _deploy_steps()
    step_names = [step.get("name") for step in steps]
    rollback_step = _find_step(ROLLBACK_STEP_NAME)

    assert f"bash {ROLLBACK_SCRIPT} restore" in rollback_step["run"]
    # Rollback must precede the refresh-machine deploy: once production has been
    # put back on its previous image, shipping a new refresh machine built from
    # the rejected commit is incoherent.
    assert step_names.index(ROLLBACK_STEP_NAME) < step_names.index(REFRESH_MACHINE_STEP_NAME)
    for verification_step_name in PRODUCTION_VERIFICATION_STEP_NAMES:
        assert step_names.index(verification_step_name) < step_names.index(ROLLBACK_STEP_NAME)


def test_bare_failure_condition_fails_the_rollback_gating_contract() -> None:
    """Self-check: `if: failure()` must be rejected — it rolls back on refresh-machine failures too."""
    steps = [dict(step) for step in _deploy_steps()]
    rollback_step = next(step for step in steps if step.get("name") == ROLLBACK_STEP_NAME)
    rollback_step["if"] = "${{ failure() }}"

    with pytest.raises(AssertionError, match="bare failure\\(\\) condition"):
        _assert_rollback_is_gated_on_serving_outcomes(steps)


def test_rollback_triggered_by_the_refresh_machine_fails_the_gating_contract() -> None:
    """Self-check: wiring the refresh machine into the rollback condition must be rejected."""
    steps = [dict(step) for step in _deploy_steps()]
    rollback_step = next(step for step in steps if step.get("name") == ROLLBACK_STEP_NAME)
    rollback_step["if"] = rollback_step["if"].replace(
        "steps.deploy_api.outcome", "steps.deploy_refresh.outcome || steps.deploy_api.outcome"
    )

    with pytest.raises(AssertionError, match="serves no user traffic"):
        _assert_rollback_is_gated_on_serving_outcomes(steps)


def test_serving_and_verification_steps_expose_the_ids_the_rollback_reads() -> None:
    """The rollback condition is only as good as the ids it names."""
    named_ids = {step.get("id") for step in _deploy_steps()}
    for step_id in ROLLBACK_TRIGGER_STEP_IDS:
        assert step_id in named_ids, f"step id {step_id!r} is referenced by the rollback condition but never defined"


def test_mirror_sha_substitution_fails_refresh_provenance_contract() -> None:
    steps = [dict(step) for step in _deploy_steps()]
    refresh_step = next(step for step in steps if step.get("name") == REFRESH_MACHINE_STEP_NAME)
    refresh_step["run"] = refresh_step["run"].replace("${{ steps.provenance.outputs.dev_sha }}", "$GITHUB_SHA")

    with pytest.raises(AssertionError, match="validated manifest dev SHA"):
        _assert_refresh_deploy_uses_manifest_dev_sha(steps)


def test_duplicated_refresh_step_fails_single_delegation_contract() -> None:
    steps = _deploy_steps()
    duplicated = steps + [dict(_find_step(REFRESH_MACHINE_STEP_NAME))]
    with pytest.raises(AssertionError):
        _assert_single_delegated_refresh_deploy(duplicated)


def test_inlined_refresh_verifier_fails_single_delegation_contract() -> None:
    steps = _deploy_steps()
    with_verifier = steps + [{"name": "Verify refresh", "run": f"bash {REFRESH_VERIFIER_SCRIPT}"}]
    with pytest.raises(AssertionError):
        _assert_single_delegated_refresh_deploy(with_verifier)


def test_deploy_workflow_persists_successful_refresh_digest_evidence() -> None:
    steps = _deploy_steps()
    step_names = [step.get("name") for step in steps]
    artifact_step = _find_step(REFRESH_EVIDENCE_ARTIFACT_STEP_NAME)

    assert artifact_step == {
        "name": REFRESH_EVIDENCE_ARTIFACT_STEP_NAME,
        # Scoped 2026-08-03 from a bare `always()`. The refresh-machine step is
        # now last and is skipped when a rollback fires, and `always()` plus
        # `if-no-files-found: error` would then fail the run on a missing
        # evidence directory that was never supposed to exist.
        "if": "${{ always() && steps.deploy_refresh.outcome != 'skipped' }}",
        "env": {"FLY_API_TOKEN": ""},
        "uses": REFRESH_EVIDENCE_ARTIFACT_ACTION,
        "with": {
            "name": "refresh_deploy_evidence",
            "path": "${{ runner.temp }}/refresh_deploy_evidence",
            "if-no-files-found": "error",
            "retention-days": 14,
        },
    }
    assert step_names.index(REFRESH_MACHINE_STEP_NAME) < step_names.index(REFRESH_EVIDENCE_ARTIFACT_STEP_NAME)
    # Inverted 2026-08-03 with the refresh-machine move: evidence upload now
    # trails the verification it used to precede.
    assert step_names.index(REFRESH_EVIDENCE_ARTIFACT_STEP_NAME) > step_names.index(
        "Verify public deploy serves built dev SHA"
    )


def test_deploy_workflow_keeps_production_smoke_gate_after_all_deploys() -> None:
    workflow_text = _read_deploy_workflow()
    drift_step = _find_step("Verify public deploy serves built dev SHA")
    install_step = _find_step("Install web smoke dependencies")
    smoke_step = _find_step("Run production smoke gate")
    drift_script = drift_step["run"]
    install_script = install_step["run"]
    smoke_script = smoke_step["run"]

    assert "/api/health/version" in drift_script
    assert "/version.json" in drift_script
    assert "${{ steps.provenance.outputs.dev_sha }}" in drift_script
    assert "seq 1 18" in drift_script
    assert "sleep 5" in drift_script
    assert "exit 1" in drift_script
    assert 'if [[ -z "${PROD_SMOKE_BASE_URL}" ]]' in drift_script

    assert "npm ci" in install_script
    assert install_step["working-directory"] == "web"
    assert 'if [[ -z "${PROD_SMOKE_BASE_URL}" ]]' in smoke_script
    assert "SMOKE_MODE=production" in smoke_script
    assert 'SMOKE_BASE_URL="${PROD_SMOKE_BASE_URL}"' in smoke_script
    assert (
        "bash ./tests/smoke/run-playwright.sh -- "
        "tests/smoke/production_deploy.spec.ts "
        "tests/smoke/production_finance_visuals.spec.ts "
        "tests/smoke/primary_nav_nonempty.spec.ts --reporter=line" in smoke_script
    )
    assert smoke_step["working-directory"] == "web"

    drift_position = workflow_text.index("Verify public deploy serves built dev SHA")
    install_position = workflow_text.index("Install web smoke dependencies")
    smoke_position = workflow_text.index("Run production smoke gate")
    last_deploy_position = max(workflow_text.index(deploy_command) for deploy_command in FLY_DEPLOY_COMMANDS)
    assert last_deploy_position < drift_position < install_position < smoke_position


def test_deploy_workflow_runs_deployed_surface_parity_gate_before_smoke() -> None:
    deploy_steps = _deploy_steps()
    step_names = [step.get("name") for step in deploy_steps]
    drift_position = step_names.index("Verify public deploy serves built dev SHA")
    probe_position = step_names.index("Run deployed surface parity gate")
    install_position = step_names.index("Install web smoke dependencies")
    smoke_position = step_names.index("Run production smoke gate")
    probe_step = deploy_steps[probe_position]
    probe_script = probe_step["run"]

    assert probe_position == drift_position + 1
    assert probe_position < install_position < smoke_position
    assert "continue-on-error" not in probe_step
    assert probe_script.splitlines()[0] == "set -euo pipefail"
    assert 'CIVIBUS_PUBLIC_BASE_URL="${PROD_SMOKE_BASE_URL}"' in probe_script
    assert 'CIVIBUS_EXPECTED_SHA="${{ steps.provenance.outputs.dev_sha }}"' in probe_script
    assert "CIVIBUS_PUBLIC_MONEY_VALUE_FATAL=0" not in probe_script
    assert "jul30_10pm_8" in probe_script
    assert "CIVIBUS_PUBLIC_MONEY_VALUE_FATAL=1" in probe_script
    assert probe_script.count("bash infra/scripts/probe_deployed_surface_parity.sh") == 1
    assert probe_script.splitlines()[-1].strip() == "bash infra/scripts/probe_deployed_surface_parity.sh"
    for forbidden_filter in (" | ", "grep ", "tee "):
        assert forbidden_filter not in probe_script


def test_deploy_workflow_does_not_duplicate_ci_integration_or_refresh_concerns() -> None:
    workflow_text = _read_deploy_workflow()
    forbidden_fragments = (
        "ruff check",
        "ruff format",
        "pytest",
        "make lint",
        "make test",
        "make db-up",
        "make db-down",
        "make db-reset",
        "make refresh",
        "schema-init",
        "entities.sql",
        "jurisdiction.sql",
        "provenance.sql",
        "entity_resolution.sql",
        "er_views.sql",
        "LOAD 'age'",
        "create_graph(",
        "fixture",
        "integration",
    )
    for fragment in forbidden_fragments:
        assert fragment not in workflow_text, f"deploy.yml must not contain {fragment!r}"
