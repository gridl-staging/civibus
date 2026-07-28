"""Contract tests for the workflow-owned DB-backed integration suite."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/integration.yml"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
DB_BACKED_STEP_NAME = "DB-backed product suite"


def _db_backed_workflow_command() -> str:
    workflow = yaml.safe_load(INTEGRATION_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "integration workflow must parse as a YAML mapping"

    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "integration workflow must define jobs"
    integration_job = jobs.get("integration-tests")
    assert isinstance(integration_job, dict), "integration workflow must define jobs.integration-tests"

    steps = integration_job.get("steps")
    assert isinstance(steps, list), "jobs.integration-tests must define steps"
    matching_steps = [step for step in steps if isinstance(step, dict) and step.get("name") == DB_BACKED_STEP_NAME]
    assert len(matching_steps) == 1, f"jobs.integration-tests must define exactly one {DB_BACKED_STEP_NAME!r} step"

    command = matching_steps[0].get("run")
    assert isinstance(command, str), f"{DB_BACKED_STEP_NAME!r} step must define a run command"
    return command


def _make_target_block(target_name: str) -> str:
    lines = MAKEFILE_PATH.read_text(encoding="utf-8").splitlines()
    target_header = f"{target_name}:"
    assert target_header in lines, f"Makefile must define a {target_name} target"

    start_index = lines.index(target_header)
    end_index = len(lines)
    for index, line in enumerate(lines[start_index + 1 :], start_index + 1):
        if line and not line.startswith(("\t", " ")):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index])


def _pytest_marker_and_paths(command: str) -> tuple[str, frozenset[str]]:
    tokens = shlex.split(command)
    pytest_index = tokens.index("pytest")
    marker_index = tokens.index("-m", pytest_index + 1)
    marker = tokens[marker_index + 1]
    path_tokens = [
        token for token in tokens[marker_index + 2 :] if token.strip() and not token.startswith("-") and token != "\\"
    ]
    paths = frozenset(path_tokens)
    assert paths, "DB-backed pytest command must select at least one path"
    assert len(paths) == len(path_tokens), "DB-backed pytest paths must not contain duplicates"
    return marker, paths


def test_local_target_matches_workflow_owned_pytest_contract() -> None:
    workflow_contract = _pytest_marker_and_paths(_db_backed_workflow_command())
    makefile_contract = _pytest_marker_and_paths(_make_target_block("test-integration-local"))

    assert makefile_contract == workflow_contract


def test_local_target_owns_workflow_setup_and_standalone_lifecycle() -> None:
    target_block = _make_target_block("test-integration-local")
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    setup_commands = (
        "make db-reset",
        "make ingest-fec-bulk-sample",
        "make graph-load",
    )

    setup_positions = [target_block.index(command) for command in setup_commands]
    assert setup_positions == sorted(setup_positions)
    assert "test-integration-local: override POSTGRES_PORT := 5475" in makefile_text
    assert "POSTGRES_PORT=5475" in target_block
    assert "started_db=0" in target_block
    assert "make db-up" in target_block
    make_db_up_position = target_block.index("make db-up")
    started_db_position = target_block.index("started_db=1", make_db_up_position)
    container_lookup_position = target_block.index(
        'container_id="$$(docker compose -f infra/docker-compose.yml ps -q db)"'
    )
    assert make_db_up_position < started_db_position < container_lookup_position
    assert "docker inspect" in target_block
    assert "make db-down" in target_block
    assert "CIVIBUS_REQUIRE_DB=1" in target_block
    assert "uv run --extra dev --extra entity-resolution pytest" in target_block


def test_local_target_rejects_incompatible_port_before_compose(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["make", "--no-print-directory", "POSTGRES_PORT=5433", "test-integration-local"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode != 0
    assert (
        "test-integration-local pins POSTGRES_PORT=5475 internally; do not provide a POSTGRES_PORT override"
        in completed.stderr
    )
    assert "docker compose" not in completed.stdout
    marker_path = tmp_path / "make_function_was_expanded"
    malicious_completed = subprocess.run(
        [
            "make",
            "--no-print-directory",
            f"POSTGRES_PORT=$(shell touch {marker_path})",
            "test-integration-local",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert malicious_completed.returncode != 0
    assert (
        "test-integration-local pins POSTGRES_PORT=5475 internally; do not provide a POSTGRES_PORT override"
        in malicious_completed.stderr
    )
    assert not marker_path.exists()
    assert "docker compose" not in malicious_completed.stdout
