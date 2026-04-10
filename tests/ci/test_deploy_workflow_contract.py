"""Deploy workflow contract tests for Stage 3 GHCR image publication."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/deploy.yml"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
DOCKER_LOGIN_SHA = "b45d80f862d83dbcd57f89517bcf500b2ab88fb2"
DOCKER_BUILD_PUSH_SHA = "d08e5c354a6adb9ed34480a06d141179aa583294"


def _read_deploy_workflow() -> str:
    return DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")


def _parse_deploy_workflow() -> dict:
    return yaml.safe_load(_read_deploy_workflow())


def _find_build_step_with_file(dockerfile_path: str) -> dict | None:
    """Return the `with` block for the build step targeting a specific Dockerfile."""
    parsed = _parse_deploy_workflow()
    jobs = parsed["jobs"]

    for job_config in jobs.values():
        for step in job_config.get("steps", []):
            step_with = step.get("with", {})
            if step_with.get("file") == dockerfile_path:
                return step_with

    return None


# --- Stage 3 basic structure ---


def test_deploy_workflow_exists_and_parses_cleanly() -> None:
    """YAML parse canary: deploy.yml must exist and load without error."""
    text = _read_deploy_workflow()
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict), "deploy.yml must parse as a YAML mapping"


def test_deploy_workflow_triggers_on_push_to_main_only() -> None:
    text = _read_deploy_workflow()
    assert "push:\n    branches: [main]" in text
    # Should NOT trigger on pull_request — that belongs to ci.yml
    assert "pull_request:" not in text


def test_deploy_workflow_has_least_privilege_permissions() -> None:
    text = _read_deploy_workflow()
    assert "permissions:" in text
    assert "packages: write" in text
    assert "contents: read" in text


def test_deploy_workflow_uses_sha_pinned_actions() -> None:
    text = _read_deploy_workflow()
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in text
    assert f"uses: docker/login-action@{DOCKER_LOGIN_SHA}" in text
    assert f"uses: docker/build-push-action@{DOCKER_BUILD_PUSH_SHA}" in text


def test_deploy_workflow_publishes_api_and_web_images() -> None:
    text = _read_deploy_workflow()
    assert "ghcr.io/" in text
    # Must tag with SHA and latest
    assert "${{ github.sha }}" in text or "github.sha" in text
    assert "latest" in text


def test_deploy_workflow_uses_expected_api_and_web_tag_pairs() -> None:
    """Published tags must map exactly to api/web service names with SHA and latest tags."""
    text = _read_deploy_workflow()
    expected_tags = (
        "ghcr.io/${{ github.repository }}/api:${{ github.sha }}",
        "ghcr.io/${{ github.repository }}/api:latest",
        "ghcr.io/${{ github.repository }}/web:${{ github.sha }}",
        "ghcr.io/${{ github.repository }}/web:latest",
    )

    for expected_tag in expected_tags:
        assert expected_tag in text, f"deploy.yml is missing expected tag '{expected_tag}'"


# --- Job set is a closed set (Stage 3 scope guard) ---

ALLOWED_JOBS = {"publish-api", "publish-web", "deploy"}


def test_deploy_workflow_declares_only_stage3_jobs() -> None:
    """Workflow must contain exactly the intended Stage 3 jobs, no extras."""
    parsed = _parse_deploy_workflow()
    actual_jobs = set(parsed["jobs"].keys())
    assert actual_jobs == ALLOWED_JOBS, f"deploy.yml job set must be exactly {ALLOWED_JOBS}, got {actual_jobs}"


# --- Dockerfile path and build context consistency ---


def test_deploy_workflow_api_uses_correct_dockerfile_and_context() -> None:
    """API image must use repo-root context with infra/api/Dockerfile."""
    api_build_steps = _find_build_step_with_file("infra/api/Dockerfile")
    assert api_build_steps is not None, "No job builds infra/api/Dockerfile"
    assert api_build_steps["context"] == ".", (
        f"API build context must be repo root '.', got '{api_build_steps['context']}'"
    )


def test_deploy_workflow_web_uses_correct_dockerfile_and_context() -> None:
    """Web image must use ./web context with web/Dockerfile."""
    web_build_steps = _find_build_step_with_file("web/Dockerfile")
    assert web_build_steps is not None, "No job builds web/Dockerfile"
    assert web_build_steps["context"] == "./web", (
        f"Web build context must be './web', got '{web_build_steps['context']}'"
    )


def test_deploy_workflow_never_builds_db_image() -> None:
    """DB image (infra/db/Dockerfile) must not appear in the deploy workflow."""
    text = _read_deploy_workflow()
    assert "infra/db/Dockerfile" not in text
    assert "/db:" not in text


# --- Deploy placeholder job and dependency flow ---


def test_deploy_job_depends_on_publish_jobs() -> None:
    """Deploy job must depend on both publish jobs completing first."""
    parsed = _parse_deploy_workflow()
    jobs = parsed["jobs"]

    assert "deploy" in jobs, "deploy.yml must contain a 'deploy' job"
    deploy_job = jobs["deploy"]
    needs = deploy_job.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]

    assert "publish-api" in needs, "deploy must need publish-api"
    assert "publish-web" in needs, "deploy must need publish-web"


def test_deploy_job_uses_environment_protection() -> None:
    """Deploy job must use environment: for manual approval gating."""
    parsed = _parse_deploy_workflow()
    deploy_job = parsed["jobs"]["deploy"]
    assert "environment" in deploy_job, "deploy job must declare an environment for protection"
    assert deploy_job["environment"] == "production", "deploy job must target the protected 'production' environment"


def test_deploy_job_performs_ssh_based_remote_rollout() -> None:
    """Deploy job must SSH into the production host and run bootstrap + compose rollout."""
    parsed = _parse_deploy_workflow()
    deploy_job = parsed["jobs"]["deploy"]
    steps = deploy_job.get("steps", [])

    # The deploy job should have multiple steps for credentials, bootstrap, and rollout
    assert len(steps) >= 3, "deploy job must have at least three steps (credentials, bootstrap, rollout)"

    step_runs = [s.get("run", "") for s in steps if "run" in s]
    assert len(step_runs) >= 3, "deploy job must have at least three run steps"

    # Must configure SSH credentials
    full_run_text = "\n".join(step_runs)
    assert "hetzner_deploy_key" in full_run_text.lower(), "deploy must configure SSH key for Hetzner"
    assert "bootstrap_prod_vm.sh" in full_run_text, "deploy must invoke bootstrap_prod_vm.sh on the remote host"
    assert "docker compose" in full_run_text, "deploy must run docker compose on the remote host"


def test_deploy_workflow_does_not_duplicate_ci_or_integration_concerns() -> None:
    """Deploy workflow must not reintroduce commands that belong to ci.yml or integration.yml."""
    text = _read_deploy_workflow()

    # Lint/test commands that belong to ci.yml
    forbidden_fragments = (
        "ruff check",
        "ruff format",
        "pytest",
        "make lint",
        "make test",
        # Integration workflow commands
        "make db-up",
        "make db-down",
        "make db-reset",
        "make ingest-fec-bulk-sample",
        "make graph-load",
        # Schema commands (compose is allowed for remote rollout; docker-compose
        # substring appears in the legitimate filename docker-compose.prod.yml)
        "schema-init",
        "entities.sql",
        "jurisdiction.sql",
        "provenance.sql",
        "entity_resolution.sql",
        "er_views.sql",
        "LOAD 'age'",
        "create_graph(",
    )

    for fragment in forbidden_fragments:
        assert fragment not in text, f"deploy.yml must not contain '{fragment}' — belongs to ci.yml or integration.yml"
