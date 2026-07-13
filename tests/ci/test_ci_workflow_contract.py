"""CI workflow contract tests for Stage 1 quality-gate behavior."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_UV_SHA = "0c5e2b8115b80b4c7c5ddf6ffdd634974642d182"
PUBLIC_CI_FORMAT_PATHS = (
    "tests/ci/test_ci_workflow_contract.py",
    "tests/ci/test_deploy_workflow_contract.py",
    "tests/ci/test_integration_workflow_contract.py",
    "tests/ci/test_ci_smoke.py",
)
PUBLIC_CI_TEST_PATHS = PUBLIC_CI_FORMAT_PATHS


def _read_ci_workflow() -> str:
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_workflow_uses_python_312_with_expected_triggers_and_jobs() -> None:
    workflow_text = _read_ci_workflow()

    assert "pull_request:\n    branches: [main]" in workflow_text
    assert "push:\n    branches: [main]" in workflow_text
    assert "permissions:\n  contents: read" in workflow_text
    assert "name: lint" in workflow_text
    assert "name: unit-tests" in workflow_text
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in workflow_text
    assert f"uses: astral-sh/setup-uv@{SETUP_UV_SHA}" in workflow_text
    assert 'python-version: "3.12"' in workflow_text


def test_ci_workflow_commands_enforce_locked_stage1_contract() -> None:
    workflow_text = _read_ci_workflow()
    format_paths = " ".join(PUBLIC_CI_FORMAT_PATHS)
    test_paths = " ".join(PUBLIC_CI_TEST_PATHS)
    required_commands = (
        "uv sync --locked --extra dev",
        f"uv run --locked ruff check {format_paths}",
        f"uv run --locked ruff format --check {format_paths}",
        "uv sync --locked --extra dev --extra entity-resolution",
        f"uv run --locked pytest {test_paths} --tb=short",
    )

    for command in required_commands:
        assert f"run: {command}" in workflow_text


def test_ci_workflow_does_not_run_private_or_full_repo_tests_in_public_mirror() -> None:
    workflow_text = _read_ci_workflow()
    forbidden_commands = (
        "ruff check .",
        "ruff format --check .",
        'pytest -m "not integration and not e2e"',
        "--cov=api --cov=core --cov=domains",
        "--cov-fail-under=70",
    )

    for command in forbidden_commands:
        assert command not in workflow_text
