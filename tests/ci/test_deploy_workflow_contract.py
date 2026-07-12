"""Deploy workflow contract tests for the Fly production deploy lane."""

from pathlib import Path

import yaml

import core.keel_gate_l13 as keel_gate_l13


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/deploy.yml"
FLY_DEPLOY_COMMANDS = [
    "flyctl deploy -c infra/fly/api.fly.toml --remote-only",
    "flyctl deploy web -c infra/fly/web.fly.toml --remote-only",
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


def _read_deploy_workflow() -> str:
    return DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")


def _parse_deploy_workflow() -> dict:
    payload = yaml.safe_load(_read_deploy_workflow())
    assert isinstance(payload, dict), "deploy.yml must parse as a YAML mapping"
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


def test_deploy_workflow_exists_and_parses_cleanly() -> None:
    parsed = _parse_deploy_workflow()
    assert isinstance(parsed, dict)


def test_l13_contract_owner_file_set_is_locked_to_fly_deploy_surface() -> None:
    owner_files = set(keel_gate_l13.CONTRACT_OWNER_FILES.values())
    assert owner_files == L13_OWNER_FILES
    for relative_path in owner_files:
        assert (REPO_ROOT / relative_path).is_file(), f"L13 owner file missing: {relative_path}"


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


def test_deploy_workflow_uses_checkout_and_flyctl_setup_only() -> None:
    workflow_text = _read_deploy_workflow()

    assert "actions/checkout@" in workflow_text
    assert "superfly/flyctl-actions/setup-flyctl" in workflow_text
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


def test_deploy_workflow_never_deploys_db_or_refresh_apps() -> None:
    workflow_text = _read_deploy_workflow()

    for forbidden_target in FORBIDDEN_DEPLOY_TARGETS:
        assert forbidden_target not in workflow_text


def test_deploy_workflow_keeps_production_smoke_gate_after_all_deploys() -> None:
    workflow_text = _read_deploy_workflow()
    smoke_step = _find_step("Run production smoke gate")
    smoke_script = smoke_step["run"]

    assert 'if [[ -z "${PROD_SMOKE_BASE_URL}" ]]' in smoke_script
    assert "SMOKE_MODE=production" in smoke_script
    assert 'SMOKE_BASE_URL="${PROD_SMOKE_BASE_URL}"' in smoke_script
    assert (
        "bash ./tests/smoke/run-playwright.sh -- tests/smoke/production_deploy.spec.ts --reporter=line" in smoke_script
    )
    assert smoke_step["working-directory"] == "web"

    smoke_position = workflow_text.index("Run production smoke gate")
    last_deploy_position = max(workflow_text.index(deploy_command) for deploy_command in FLY_DEPLOY_COMMANDS)
    assert last_deploy_position < smoke_position


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
