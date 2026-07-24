"""CI workflow contract tests for Makefile-owned Python quality gates."""

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
WEB_PACKAGE_PATH = REPO_ROOT / "web/package.json"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_NODE_SHA = "820762786026740c76f36085b0efc47a31fe5020"
SETUP_UV_SHA = "0c5e2b8115b80b4c7c5ddf6ffdd634974642d182"


def _read_ci_workflow() -> str:
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_workflow_uses_python_312_with_expected_triggers_and_jobs() -> None:
    workflow_text = _read_ci_workflow()
    lint_job = _job_block(workflow_text, "lint")
    unit_tests_job = _job_block(workflow_text, "unit-tests")
    web_job = _job_block(workflow_text, "web")

    assert "pull_request:\n    branches: [main]" in workflow_text
    assert "push:\n    branches: [main]" in workflow_text
    assert "permissions:\n  contents: read" in workflow_text
    assert "    name: lint" in lint_job.splitlines()
    assert "    name: unit-tests" in unit_tests_job.splitlines()

    for job_block in (lint_job, unit_tests_job, web_job):
        assert f"uses: actions/checkout@{CHECKOUT_SHA}" in job_block
        assert "          fetch-depth: 2" in job_block.splitlines()
        assert "          persist-credentials: false" in job_block.splitlines()

    for python_job in (lint_job, unit_tests_job):
        assert f"uses: astral-sh/setup-uv@{SETUP_UV_SHA}" in python_job
        assert '          python-version: "3.12"' in python_job.splitlines()


def _job_block(workflow_text: str, job_name: str) -> str:
    workflow_lines = workflow_text.splitlines()
    start_index = workflow_lines.index(f"  {job_name}:")
    end_index = len(workflow_lines)
    for index, line in enumerate(workflow_lines[start_index + 1 :], start_index + 1):
        if line.startswith("  ") and not line.startswith("    "):
            end_index = index
            break
    return "\n".join(workflow_lines[start_index:end_index])


def test_ci_workflow_commands_use_make_owned_python_gates() -> None:
    workflow_text = _read_ci_workflow()
    lint_job = _job_block(workflow_text, "lint")
    unit_tests_job = _job_block(workflow_text, "unit-tests")

    assert "        run: uv sync --locked --extra dev --extra entity-resolution" in unit_tests_job.splitlines()
    assert "        run: make test" in unit_tests_job.splitlines()
    assert "        run: uv sync --locked --extra dev" in lint_job.splitlines()
    assert "        run: make lint" in lint_job.splitlines()


def test_ci_workflow_runs_package_owned_web_gates_before_deploy() -> None:
    workflow_text = _read_ci_workflow()
    web_job = _job_block(workflow_text, "web")
    web_package = json.loads(WEB_PACKAGE_PATH.read_text(encoding="utf-8"))

    assert "    name: web" in web_job.splitlines()
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in web_job
    assert "          fetch-depth: 2" in web_job.splitlines()
    assert "          persist-credentials: false" in web_job.splitlines()
    assert web_package["engines"]["node"] == "24.18.0"
    assert f"uses: actions/setup-node@{SETUP_NODE_SHA}" in web_job
    assert "          node-version-file: web/package.json" in web_job.splitlines()
    assert "          cache: npm" in web_job.splitlines()
    assert "          cache-dependency-path: web/package-lock.json" in web_job.splitlines()
    assert web_job.index("uses: actions/setup-node@") < web_job.index("run: npm ci")
    assert web_job.count("        working-directory: web") == 4
    assert "        run: npm ci" in web_job.splitlines()
    assert "        run: npm test" in web_job.splitlines()
    assert "        run: npm run check" in web_job.splitlines()
    assert "        run: npm run build" in web_job.splitlines()
    assert "continue-on-error" not in web_job
    assert "tests/smoke/run-playwright.sh" not in web_job


def test_ci_workflow_does_not_copy_make_owned_python_gate_commands() -> None:
    workflow_text = _read_ci_workflow()
    forbidden_commands = (
        "ruff check tests/ci/",
        "ruff format --check tests/ci/",
        "ruff check .",
        "ruff format --check .",
        'pytest tests/ci/ -m "not dev_repo_only"',
        'pytest -m "not integration and not e2e"',
        "--cov=api --cov=core --cov=domains",
        "--cov-fail-under=70",
        "continue-on-error",
    )

    for command in forbidden_commands:
        assert command not in workflow_text
