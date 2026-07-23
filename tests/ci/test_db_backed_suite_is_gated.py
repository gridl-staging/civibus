"""Contract test for the complete DB-backed product-suite CI invocation."""

import shlex
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/integration.yml"
INTEGRATION_MARKER_EXPRESSION = "integration and not quarantined"
DB_BACKED_TARGET_PATHS = (
    "api/",
    "core/",
    "domains/",
    "tests/integration/",
    "tests/e2e/",
    "tests/test_db_integration.py",
    "tests/test_graph_queries.py",
    "tests/test_relational_queries.py",
)


def _integration_job_run_commands() -> list[str]:
    workflow = yaml.safe_load(INTEGRATION_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "integration workflow must parse as a YAML mapping"

    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "integration workflow must define jobs"
    integration_job = jobs.get("integration-tests")
    assert isinstance(integration_job, dict), "integration workflow must define jobs.integration-tests"

    steps = integration_job.get("steps")
    assert isinstance(steps, list), "jobs.integration-tests must define steps"
    return [run for step in steps if isinstance(step, dict) and isinstance((run := step.get("run")), str)]


def _matching_db_backed_pytest_command_tokens() -> list[list[str]]:
    matching_commands: list[list[str]] = []
    for command in _integration_job_run_commands():
        tokens = shlex.split(command)
        if "pytest" not in tokens:
            continue

        pytest_index = tokens.index("pytest")
        marker_indexes = [index for index, token in enumerate(tokens) if token == "-m" and index > pytest_index]
        if len(marker_indexes) != 1:
            continue

        marker_index = marker_indexes[0]
        if marker_index + 1 < len(tokens) and tokens[marker_index + 1] == INTEGRATION_MARKER_EXPRESSION:
            matching_commands.append(tokens)
    return matching_commands


def test_integration_job_gates_complete_db_backed_product_suite() -> None:
    matching_commands = _matching_db_backed_pytest_command_tokens()

    assert len(matching_commands) == 1, (
        "Missing DB-backed pytest invocation in jobs.integration-tests: expected exactly one command with "
        f"-m {INTEGRATION_MARKER_EXPRESSION!r}, found {len(matching_commands)}"
    )
    command_tokens = matching_commands[0]
    marker_index = command_tokens.index("-m")
    target_tokens = tuple(
        token for token in command_tokens[marker_index + 2 :] if token.strip() and not token.startswith("-")
    )

    for target_path in DB_BACKED_TARGET_PATHS:
        assert command_tokens.count(target_path) == 1, (
            f"DB-backed pytest invocation must include {target_path!r} exactly once; "
            f"found {command_tokens.count(target_path)}"
        )
    assert target_tokens == DB_BACKED_TARGET_PATHS, (
        "DB-backed pytest invocation must target exactly the complete canonical DB-backed product suite; "
        f"expected {DB_BACKED_TARGET_PATHS!r}, got {target_tokens!r}"
    )
