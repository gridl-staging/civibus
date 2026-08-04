"""Deploy workflow contract tests for the Fly production deploy lane."""

from pathlib import Path
import re
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
SERVING_DEPLOY_STEP_NAMES = ("Deploy API to Fly", "Deploy web to Fly", "Deploy Caddy to Fly")
PRODUCTION_VERIFICATION_STEP_NAMES = (
    "Verify public deploy serves built dev SHA",
    "Run deployed surface parity gate",
    "Run production smoke gate",
)
REFRESH_BUILD_IDENTITY_STEP_IDS = ("deploy_api", "deploy_web", "deploy_caddy", "verify_sha")
REFRESH_CONTENT_EVIDENCE_STEP_IDS = ("parity_gate", "smoke_gate")
# The rollback consults both refresh owner sets; derive it so the six ids keep one home (line ~546 pins it).
ROLLBACK_TRIGGER_STEP_IDS = (*REFRESH_BUILD_IDENTITY_STEP_IDS, *REFRESH_CONTENT_EVIDENCE_STEP_IDS)
ROLLBACK_STEP_ID = "rollback"
REFRESH_OPTIONAL_GUARD_STEP_IDS = ("pre_deploy",)
REFRESH_GATE_MODELED_STEP_IDS = (*ROLLBACK_TRIGGER_STEP_IDS, *REFRESH_OPTIONAL_GUARD_STEP_IDS, ROLLBACK_STEP_ID)
# Either lead keeps GitHub's implicit success() from skipping the step after a red content probe.
# `!cancelled()` is the stricter of the two because it also stops a cancelled run from deploying.
REFRESH_GATE_STATUS_FUNCTION_LEADS = ("always()", "!cancelled()")
REFRESH_BARE_STATUS_CONDITIONS = frozenset(
    {f"${{{{ {lead} }}}}" for lead in REFRESH_GATE_STATUS_FUNCTION_LEADS} | set(REFRESH_GATE_STATUS_FUNCTION_LEADS)
)


def _refresh_gate_condition(
    lead: str = "always()", *, step_ids: tuple[str, ...] = REFRESH_BUILD_IDENTITY_STEP_IDS
) -> str:
    """Build a workflow-shaped refresh gate condition for checker self-checks."""
    predicates = " && ".join(f"steps.{step_id}.outcome == 'success'" for step_id in step_ids)
    return f"${{{{ {lead} && {predicates} }}}}"


REFRESH_GATE_TEST_CONDITION = _refresh_gate_condition()
# Every rejected shape the checker must red on, keyed by the message fragment that names the defect.
_REJECTED_REFRESH_CONDITIONS = {
    "must lead with one of": _refresh_gate_condition("success()"),
    "unsupported syntax": REFRESH_GATE_TEST_CONDITION.replace(" }}", " && true }}"),
    "misordered parentheses": REFRESH_GATE_TEST_CONDITION.replace(" && steps.deploy_web", ") && (steps.deploy_web", 1),
    "unbalanced parentheses": REFRESH_GATE_TEST_CONDITION.replace("always() && ", "always() && (", 1),
    "does not model": _refresh_gate_condition(step_ids=(*REFRESH_BUILD_IDENTITY_STEP_IDS, "install_smoke_deps")),
}
REFRESH_DEPLOY_INVOCATION = (
    'bash infra/scripts/deploy_refresh_machine.sh --evidence-dir "$evidence" '
    '--dev-sha "${{ steps.provenance.outputs.dev_sha }}"'
)
REFRESH_VERIFIER_SCRIPT = "infra/scripts/verify_refresh_machine.sh"
REFRESH_EVIDENCE_ARTIFACT_STEP_NAME = "Persist refresh deploy evidence"
REFRESH_EVIDENCE_ARTIFACT_ACTION = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


def _assert_single_delegated_refresh_deploy(steps: list[dict]) -> None:
    step_names = [step.get("name") for step in steps]
    all_scripts = "\n".join(step.get("run", "") for step in steps if "run" in step)
    assert step_names.count(REFRESH_MACHINE_STEP_NAME) == 1, "exactly one refresh-machine deploy step is allowed"
    duplicate_deploy_error = "exactly one deploy_refresh_machine.sh invocation is allowed"
    assert all_scripts.count(REFRESH_DEPLOY_INVOCATION) == 1, duplicate_deploy_error
    verifier_owner_error = "verify_refresh_machine.sh is owned by the deploy script, not YAML"
    assert REFRESH_VERIFIER_SCRIPT not in all_scripts, verifier_owner_error


def _assert_refresh_deploy_uses_manifest_dev_sha(steps: list[dict]) -> None:
    refresh_steps = [step for step in steps if step.get("name") == REFRESH_MACHINE_STEP_NAME]
    assert len(refresh_steps) == 1
    manifest_sha_error = "refresh deploy must receive the validated manifest dev SHA"
    assert refresh_steps[0]["run"].count(REFRESH_DEPLOY_INVOCATION) == 1, manifest_sha_error


def _assert_production_verification_precedes_refresh_machine(steps: list[dict]) -> None:
    step_names = [step.get("name") for step in steps]
    assert REFRESH_MACHINE_STEP_NAME in step_names, "refresh-machine deploy step is required"
    refresh_position = step_names.index(REFRESH_MACHINE_STEP_NAME)
    for verification_step_name in PRODUCTION_VERIFICATION_STEP_NAMES:
        assert verification_step_name in step_names, f"missing verification step {verification_step_name!r}"
        ordering_error = f"{verification_step_name!r} after refresh silently skips production verification"
        assert step_names.index(verification_step_name) < refresh_position, ordering_error


def _assert_rollback_is_gated_on_serving_outcomes(steps: list[dict]) -> None:
    step_names = [step.get("name") for step in steps]
    assert ROLLBACK_STEP_NAME in step_names, "a rollback step is required for failed production verification"
    condition = steps[step_names.index(ROLLBACK_STEP_NAME)].get("if", "")
    assert condition, "rollback step must carry an explicit `if:` condition"
    bare_failure_error = "bare failure() condition would roll back on refresh failure"
    assert condition.strip() not in {"${{ failure() }}", "failure()"}, bare_failure_error
    assert REFRESH_MACHINE_STEP_NAME not in condition
    refresh_rollback_error = "the refresh machine serves no user traffic; must not trigger rollback"
    assert "steps.deploy_refresh" not in condition, refresh_rollback_error
    for step_id in ROLLBACK_TRIGGER_STEP_IDS:
        assert f"steps.{step_id}.outcome" in condition, f"rollback condition must consult steps.{step_id}.outcome"
    # The rollback is only meaningful if we actually captured a target.
    assert "steps.pre_deploy.outcome == 'success'" in condition


_REFRESH_OUTCOME_PREDICATE = re.compile(
    r"steps\.([a-z_][a-z0-9_]*)\.outcome\s*==\s*'(success|failure|cancelled|skipped)'"
)


def _refresh_condition_matches_outcomes(condition: str, outcomes: dict[str, str]) -> bool:
    """Evaluate only the conjunction grammar accepted for the refresh gate."""
    expression = condition.strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    lead = next((fn for fn in REFRESH_GATE_STATUS_FUNCTION_LEADS if expression.startswith(fn)), None)
    # A leading status function keeps content failures from implying success().
    assert lead is not None, f"refresh condition must lead with one of {REFRESH_GATE_STATUS_FUNCTION_LEADS}"
    predicate_values: list[bool] = []

    def replace_predicate(match: re.Match[str]) -> str:
        step_id, expected_outcome = match.groups()
        # A step this contract does not model is a fixture gap, not a broken workflow condition.
        fixture_gap_error = f"refresh condition names step {step_id!r} the contract does not model; add to fixture"
        assert step_id in outcomes, fixture_gap_error
        predicate_values.append(outcomes[step_id] == expected_outcome)
        return "PREDICATE"

    remainder = _REFRESH_OUTCOME_PREDICATE.sub(replace_predicate, expression[len(lead) :])
    assert predicate_values, "refresh deploy condition must compare named step outcomes"
    syntax_error = f"unsupported syntax after {REFRESH_GATE_STATUS_FUNCTION_LEADS}; use && and parens"
    assert re.fullmatch(r"(?:\s*&&\s*\(*\s*PREDICATE\s*\)*)+", remainder), syntax_error
    parenthesis_depth = 0
    for character in remainder:
        if character == "(":
            parenthesis_depth += 1
        elif character == ")":
            parenthesis_depth -= 1
        assert parenthesis_depth >= 0, "refresh deploy condition has misordered parentheses"
    assert parenthesis_depth == 0, "refresh deploy condition has unbalanced parentheses"
    return all(predicate_values)


def _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(
    steps: list[dict], outcomes: dict[str, str], *, expected: bool
) -> None:
    step_names = [step.get("name") for step in steps]
    assert REFRESH_MACHINE_STEP_NAME in step_names, "refresh-machine deploy step is required"
    condition = steps[step_names.index(REFRESH_MACHINE_STEP_NAME)].get("if", "")
    assert condition, "refresh deploy step must carry an explicit if condition"
    stripped_condition = condition.strip()
    bare_status_error = "bare always()/!cancelled() condition ignores broken serving identity"
    assert stripped_condition not in REFRESH_BARE_STATUS_CONDITIONS, bare_status_error
    assert stripped_condition not in {"${{ success() }}", "success()"}, "bare success() skips refresh after content red"
    for step_id in REFRESH_BUILD_IDENTITY_STEP_IDS:
        assert f"steps.{step_id}.outcome" in condition, f"refresh gate must consult steps.{step_id}.outcome directly"
    # Explicit Stage-1 decision: the rollback fires on the content-red parity/smoke failures the
    # refresh writer must survive, so its outcome must not consult the gate.
    rollback_gate_error = "refresh gate must not consult the rollback outcome (content-red)"
    assert f"steps.{ROLLBACK_STEP_ID}" not in condition, rollback_gate_error
    actual = _refresh_condition_matches_outcomes(condition, outcomes)
    assert actual is expected, f"refresh condition evaluated {actual} for {outcomes}; expected {expected}"


API_DEPLOY_STEP_NAME = "Deploy API to Fly"
API_HEALTHY_CONTENT_LITERAL = '{"healthy":true}'


def _assert_step_probes_api_public_readiness(step: dict) -> None:
    script = step.get("run", "")
    lines = script.splitlines()
    deploy_indexes = [index for index, line in enumerate(lines) if line.strip().startswith("flyctl deploy")]
    assert deploy_indexes, f"{step.get('name')!r} must run `flyctl deploy`"
    probe_after = "\n".join(lines[deploy_indexes[-1] + 1 :])
    assert 'if [[ -z "${PROD_SMOKE_BASE_URL}" ]]' in probe_after, "probe must guard on empty PROD_SMOKE_BASE_URL"
    assert 'expected_sha="${{ steps.provenance.outputs.dev_sha }}"' in probe_after, "probe must pin the built dev SHA"
    assert "${PROD_SMOKE_BASE_URL%/}/api/health/version" in probe_after, "probe must read public /api/health/version"
    assert "${PROD_SMOKE_BASE_URL%/}/api/health/content" in probe_after, "probe must read public /api/health/content"
    assert "seq 1 18" in probe_after, "the probe must reuse the seq 1 18 retry shape"
    assert "sleep 5" in probe_after, "the probe must reuse the sleep 5 retry cadence"
    assert "curl -fsS" in probe_after, "the probe must fail closed on non-2xx responses with curl -fsS"
    assert "exit 1" in probe_after, "the probe must fail the step when readiness is never observed"
    success_branch = next(
        (line for line in probe_after.splitlines() if API_HEALTHY_CONTENT_LITERAL in line and "$expected_sha" in line),
        None,
    )
    success_error = f"one success branch must require BOTH dev SHA and byte-exact {API_HEALTHY_CONTENT_LITERAL}"
    assert success_branch is not None, success_error


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
    refresh_script = _find_step(REFRESH_MACHINE_STEP_NAME)["run"]
    assert "actions/checkout@" in workflow_text
    assert "superfly/flyctl-actions/setup-flyctl" in workflow_text
    assert {
        "uses": "astral-sh/setup-uv@0c5e2b8115b80b4c7c5ddf6ffdd634974642d182",
        "with": {"python-version": "3.12"},
    } in setup_steps
    expected_refresh_setup = (
        'uv sync --frozen\nPYTHON_BIN="$GITHUB_WORKSPACE/.venv/bin/python" ' + REFRESH_DEPLOY_INVOCATION
    )
    assert expected_refresh_setup in refresh_script, (
        "refresh deploy must use the locked project interpreter immediately after dependency sync"
    )
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
    assert "^[0-9a-f]{40}$" in script
    assert "exit 1" in script
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
    workflow_text = _read_deploy_workflow()

    for forbidden_target in FORBIDDEN_DEPLOY_TARGETS:
        assert forbidden_target not in workflow_text


def test_deploy_workflow_delegates_refresh_machine_deploy_after_serving_deploys() -> None:
    deploy_steps = _deploy_steps()
    step_names = [step.get("name") for step in deploy_steps]
    refresh_step = _find_step("Deploy refresh machine")
    refresh_script = refresh_step["run"]
    assert refresh_step["shell"] == "bash"
    assert refresh_script.splitlines()[0] == "set -euo pipefail"
    assert 'evidence="$RUNNER_TEMP/refresh_deploy_evidence"' in refresh_script
    assert 'mkdir -p "$evidence"' in refresh_script
    for delegated_owner_literal in (
        "infra/scripts/verify_refresh_machine.sh",
        "civibus-refresh",
        "infra/fly/refresh.fly.toml",
    ):
        assert delegated_owner_literal not in refresh_script
    # Verification-step ordering is owned by _assert_production_verification_precedes_refresh_machine.
    refresh_position = step_names.index("Deploy refresh machine")
    for serving_step_name in SERVING_DEPLOY_STEP_NAMES:
        assert step_names.index(serving_step_name) < refresh_position


def test_deploy_workflow_delegates_refresh_deploy_exactly_once_workflow_wide() -> None:
    _assert_single_delegated_refresh_deploy(_deploy_steps())
    _assert_refresh_deploy_uses_manifest_dev_sha(_deploy_steps())


def _successful_refresh_gate_outcomes() -> dict[str, str]:
    outcomes = {step_id: "success" for step_id in REFRESH_GATE_MODELED_STEP_IDS}
    outcomes[ROLLBACK_STEP_ID] = _rollback_outcome(outcomes)
    return outcomes


def _rollback_outcome(outcomes: dict[str, str]) -> str:
    if outcomes["pre_deploy"] != "success":
        return "skipped"
    return "success" if any(outcomes[step_id] == "failure" for step_id in ROLLBACK_TRIGGER_STEP_IDS) else "skipped"


def _refresh_gate_outcomes_with(**updates: str) -> dict[str, str]:
    outcomes = _successful_refresh_gate_outcomes()
    outcomes.update(updates)
    outcomes[ROLLBACK_STEP_ID] = _rollback_outcome(outcomes)
    return outcomes


def _copy_steps_with_refresh_condition(condition: str | None) -> list[dict]:
    steps = [dict(step) for step in _deploy_steps()]
    refresh_step = next(step for step in steps if step.get("name") == REFRESH_MACHINE_STEP_NAME)
    if condition is None:
        refresh_step.pop("if", None)
    else:
        refresh_step["if"] = condition
    return steps


@pytest.mark.parametrize("failed_content_step_id", REFRESH_CONTENT_EVIDENCE_STEP_IDS)
def test_refresh_deploy_still_runs_when_content_evidence_is_red(failed_content_step_id: str) -> None:
    outcomes = _refresh_gate_outcomes_with(**{failed_content_step_id: "failure"})

    _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(_deploy_steps(), outcomes, expected=True)


@pytest.mark.parametrize("failed_step_id", REFRESH_BUILD_IDENTITY_STEP_IDS)
def test_refresh_deploy_does_not_run_when_build_or_identity_evidence_is_red(failed_step_id: str) -> None:
    outcomes = _refresh_gate_outcomes_with(**{failed_step_id: "failure"}, parity_gate="failure")
    _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(_deploy_steps(), outcomes, expected=False)


@pytest.mark.parametrize("lead", REFRESH_GATE_STATUS_FUNCTION_LEADS)
def test_a_lead_gated_build_identity_condition_satisfies_the_whole_refresh_contract(lead: str) -> None:
    steps = _copy_steps_with_refresh_condition(_refresh_gate_condition(lead))
    outcomes = _refresh_gate_outcomes_with(smoke_gate="failure")
    _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(steps, outcomes, expected=True)
    outcomes = _refresh_gate_outcomes_with(smoke_gate="failure", verify_sha="failure")
    _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(steps, outcomes, expected=False)


def test_refresh_and_rollback_gate_owner_sets_remain_explicit_and_distinct() -> None:
    assert REFRESH_BUILD_IDENTITY_STEP_IDS == ("deploy_api", "deploy_web", "deploy_caddy", "verify_sha")
    assert REFRESH_CONTENT_EVIDENCE_STEP_IDS == ("parity_gate", "smoke_gate")
    assert REFRESH_OPTIONAL_GUARD_STEP_IDS == ("pre_deploy",)
    assert ROLLBACK_STEP_ID == "rollback"
    assert REFRESH_GATE_MODELED_STEP_IDS == (*ROLLBACK_TRIGGER_STEP_IDS, "pre_deploy", "rollback")
    assert REFRESH_GATE_STATUS_FUNCTION_LEADS == ("always()", "!cancelled()")
    # The rollback consults both owner sets; the six-id literal lives here (module derives it), so a
    # bad derivation still reds. The composition is asserted alongside the literal.
    literal_rollback_owner_ids = ("deploy_api", "deploy_web", "deploy_caddy", "verify_sha", "parity_gate", "smoke_gate")
    assert ROLLBACK_TRIGGER_STEP_IDS == literal_rollback_owner_ids
    assert ROLLBACK_TRIGGER_STEP_IDS == (*REFRESH_BUILD_IDENTITY_STEP_IDS, *REFRESH_CONTENT_EVIDENCE_STEP_IDS)
    _assert_rollback_is_gated_on_serving_outcomes(_deploy_steps())
    rollback_condition = _find_step(ROLLBACK_STEP_NAME)["if"]
    assert "steps.deploy_refresh" not in rollback_condition
    assert "smoke_deps" not in rollback_condition


def test_refresh_gate_deliberately_excludes_the_content_red_rollback_outcome() -> None:
    """Stage-1 decision: steps.rollback must NOT gate refresh. The rollback fires on the
    content-red parity/smoke failures the refresh writer must survive, so a
    rollback == 'skipped' predicate would re-block refresh on exactly those runs."""
    outcomes = _successful_refresh_gate_outcomes()
    assert outcomes[ROLLBACK_STEP_ID] == "skipped"  # all owners green -> no rollback
    outcomes = _refresh_gate_outcomes_with(parity_gate="failure")
    assert outcomes[ROLLBACK_STEP_ID] == "success"
    assert _refresh_gate_outcomes_with(deploy_api="failure")[ROLLBACK_STEP_ID] == "success"
    assert _refresh_gate_outcomes_with(pre_deploy="failure", smoke_gate="failure")[ROLLBACK_STEP_ID] == "skipped"
    assert _refresh_condition_matches_outcomes(_refresh_gate_condition(), outcomes) is True
    coupled = _refresh_gate_condition().replace(" }}", " && steps.rollback.outcome == 'skipped' }}")
    assert _refresh_condition_matches_outcomes(coupled, outcomes) is False
    with pytest.raises(AssertionError, match="must not consult the rollback outcome"):
        _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(
            _copy_steps_with_refresh_condition(coupled), outcomes, expected=False
        )


@pytest.mark.parametrize(("expected_error", "condition"), sorted(_REJECTED_REFRESH_CONDITIONS.items()))
def test_refresh_condition_checker_fails_closed_on_rejected_conditions(expected_error: str, condition: str) -> None:
    with pytest.raises(AssertionError, match=expected_error):
        _refresh_condition_matches_outcomes(condition, _successful_refresh_gate_outcomes())


@pytest.mark.parametrize("lead", REFRESH_GATE_STATUS_FUNCTION_LEADS)
def test_refresh_condition_checker_accepts_status_leads_and_the_pre_deploy_guard(lead: str) -> None:
    outcomes = _refresh_gate_outcomes_with(parity_gate="failure")
    guard_ids = (*REFRESH_OPTIONAL_GUARD_STEP_IDS, *REFRESH_BUILD_IDENTITY_STEP_IDS)
    guarded_condition = _refresh_gate_condition(lead, step_ids=guard_ids)
    # A red content probe never blocks either lead, with or without the extra capture guard.
    assert _refresh_condition_matches_outcomes(_refresh_gate_condition(lead), outcomes) is True
    assert _refresh_condition_matches_outcomes(guarded_condition, outcomes) is True
    outcomes = _refresh_gate_outcomes_with(parity_gate="failure", pre_deploy="failure")
    assert _refresh_condition_matches_outcomes(guarded_condition, outcomes) is False
    outcomes = _refresh_gate_outcomes_with(parity_gate="failure", deploy_caddy="failure")
    assert _refresh_condition_matches_outcomes(_refresh_gate_condition(lead), outcomes) is False


@pytest.mark.parametrize("bare_condition", sorted(REFRESH_BARE_STATUS_CONDITIONS))
def test_bare_status_function_condition_fails_the_refresh_build_gating_contract(bare_condition: str) -> None:
    steps = _copy_steps_with_refresh_condition(bare_condition)
    outcomes = _refresh_gate_outcomes_with(deploy_api="failure")
    with pytest.raises(AssertionError, match=r"bare always\(\)/!cancelled\(\) condition"):
        _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(steps, outcomes, expected=False)


@pytest.mark.parametrize("failed_content_step_id", REFRESH_CONTENT_EVIDENCE_STEP_IDS)
def test_missing_refresh_condition_fails_the_content_red_positive_contract(failed_content_step_id: str) -> None:
    steps = _copy_steps_with_refresh_condition(None)
    outcomes = _refresh_gate_outcomes_with(**{failed_content_step_id: "failure"})
    with pytest.raises(AssertionError, match="refresh deploy step must carry an explicit if condition"):
        _assert_refresh_deploy_is_gated_on_build_identity_not_content_outcomes(steps, outcomes, expected=True)


def test_production_verification_runs_before_the_refresh_machine_deploy() -> None:
    _assert_production_verification_precedes_refresh_machine(_deploy_steps())


def test_refresh_machine_before_verification_fails_the_ordering_contract() -> None:
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
    assert f"bash {ROLLBACK_SCRIPT} capture" in capture_step["run"]


def test_deploy_workflow_rolls_back_serving_apps_on_failed_production_verification() -> None:
    _assert_rollback_is_gated_on_serving_outcomes(_deploy_steps())
    steps = _deploy_steps()
    step_names = [step.get("name") for step in steps]
    rollback_step = _find_step(ROLLBACK_STEP_NAME)
    assert f"bash {ROLLBACK_SCRIPT} restore" in rollback_step["run"]
    assert step_names.index(ROLLBACK_STEP_NAME) < step_names.index(REFRESH_MACHINE_STEP_NAME)
    for verification_step_name in PRODUCTION_VERIFICATION_STEP_NAMES:
        assert step_names.index(verification_step_name) < step_names.index(ROLLBACK_STEP_NAME)


def test_bare_failure_condition_fails_the_rollback_gating_contract() -> None:
    steps = [dict(step) for step in _deploy_steps()]
    rollback_step = next(step for step in steps if step.get("name") == ROLLBACK_STEP_NAME)
    rollback_step["if"] = "${{ failure() }}"

    with pytest.raises(AssertionError, match="bare failure\\(\\) condition"):
        _assert_rollback_is_gated_on_serving_outcomes(steps)


def test_rollback_triggered_by_the_refresh_machine_fails_the_gating_contract() -> None:
    steps = [dict(step) for step in _deploy_steps()]
    rollback_step = next(step for step in steps if step.get("name") == ROLLBACK_STEP_NAME)
    rollback_step["if"] = rollback_step["if"].replace(
        "steps.deploy_api.outcome", "steps.deploy_refresh.outcome || steps.deploy_api.outcome"
    )
    with pytest.raises(AssertionError, match="serves no user traffic"):
        _assert_rollback_is_gated_on_serving_outcomes(steps)


def test_api_deploy_step_probes_public_api_readiness() -> None:
    step = _find_step(API_DEPLOY_STEP_NAME)
    _assert_step_probes_api_public_readiness(step)
    assert step.get("env", {}).get("FLY_API_TOKEN") != "", (
        "Deploy API step still runs flyctl deploy and must keep its FLY_API_TOKEN"
    )


def test_api_deploy_without_public_probe_fails_the_readiness_contract() -> None:
    step = dict(_find_step(API_DEPLOY_STEP_NAME))
    lines = step["run"].splitlines()
    deploy_index = next(index for index, line in enumerate(lines) if line.strip().startswith("flyctl deploy"))
    step["run"] = "\n".join(lines[: deploy_index + 1])
    with pytest.raises(AssertionError):
        _assert_step_probes_api_public_readiness(step)


def test_serving_and_verification_steps_expose_the_ids_the_rollback_reads() -> None:
    named_ids = {step.get("id") for step in _deploy_steps()}
    for step_id in ROLLBACK_TRIGGER_STEP_IDS:
        assert step_id in named_ids, f"step id {step_id!r} is referenced by the rollback condition but never defined"


def test_mirror_sha_substitution_fails_refresh_provenance_contract() -> None:
    steps = [dict(step) for step in _deploy_steps()]
    refresh_step = next(step for step in steps if step.get("name") == REFRESH_MACHINE_STEP_NAME)
    refresh_step["run"] = refresh_step["run"].replace("${{ steps.provenance.outputs.dev_sha }}", "$GITHUB_SHA")

    with pytest.raises(AssertionError, match="validated manifest dev SHA"):
        _assert_refresh_deploy_uses_manifest_dev_sha(steps)


@pytest.mark.parametrize(
    "extra_step",
    [
        {"name": REFRESH_MACHINE_STEP_NAME, "run": REFRESH_DEPLOY_INVOCATION},
        {"name": "Verify refresh", "run": f"bash {REFRESH_VERIFIER_SCRIPT}"},
    ],
    ids=("duplicated_refresh_step", "inlined_refresh_verifier"),
)
def test_extra_refresh_steps_fail_the_single_delegation_contract(extra_step: dict) -> None:
    with pytest.raises(AssertionError):
        _assert_single_delegated_refresh_deploy(_deploy_steps() + [extra_step])


def test_deploy_workflow_persists_successful_refresh_digest_evidence() -> None:
    steps = _deploy_steps()
    step_names = [step.get("name") for step in steps]
    artifact_step = _find_step(REFRESH_EVIDENCE_ARTIFACT_STEP_NAME)

    assert artifact_step == {
        "name": REFRESH_EVIDENCE_ARTIFACT_STEP_NAME,
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
