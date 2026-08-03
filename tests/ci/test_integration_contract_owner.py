"""Contract tests for the workflow-owned DB-backed integration suite."""

from __future__ import annotations

import os
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
    start_index = _recipe_header_index(lines, target_name)
    end_index = len(lines)
    for index, line in enumerate(lines[start_index + 1 :], start_index + 1):
        if line and not line.startswith(("\t", " ")):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index])


def _recipe_header_index(lines: list[str], target_name: str) -> int:
    # Anchor on the recipe-bearing header so targets that carry prerequisites on
    # the header line (`db-teardown: require-postgres-password`) or split their
    # prerequisites across several header lines (`test-integration-local`) both
    # resolve to the block that actually holds the recipe body.
    target_header = f"{target_name}:"
    for index, line in enumerate(lines):
        header_matches = line == target_header or line.startswith(f"{target_header} ")
        has_recipe = index + 1 < len(lines) and lines[index + 1].startswith("\t")
        if header_matches and has_recipe:
            return index
    raise AssertionError(f"Makefile must define a recipe for {target_name}")


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
    assert "test-integration-local: override COMPOSE_PROJECT_NAME := civibus_integration_local" in makefile_text
    assert "POSTGRES_PORT=5475" in target_block
    assert "started_db=0" in target_block
    volume_cleanup = "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans"
    assert target_block.count(volume_cleanup) == 2
    assert "make db-up" in target_block
    assert target_block.index(volume_cleanup) < target_block.index("make db-up")
    make_db_up_position = target_block.index("make db-up")
    started_db_position = target_block.index("started_db=1", make_db_up_position)
    container_lookup_position = target_block.index(
        'container_id="$$(docker compose -f infra/docker-compose.yml ps -q db)"'
    )
    assert make_db_up_position < started_db_position < container_lookup_position
    assert "docker inspect" in target_block
    assert "make db-down" not in target_block
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


TEARDOWN_COMPOSE_COMMAND = "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans"
TEARDOWN_VOLUME_PROOF = 'grep -Fqx "$${COMPOSE_PROJECT_NAME}_civibus_db_data"'
TEARDOWN_CLEAN_RECEIPT = "TEARDOWN CLEAN: docker volume ls contains no civibus_c3 volume"


def _run_db_teardown_with_stub_docker(
    tmp_path: Path,
    volume_ls_output: str,
    volume_ls_exit_code: int = 0,
    project_name: str = "civibus_c3",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    stub_dir = tmp_path / "stub_bin"
    stub_dir.mkdir()
    call_log = tmp_path / "docker_calls.log"
    stub_path = stub_dir / "docker"
    # Record every invocation, no-op the destructive compose command, and let the
    # test dictate what `docker volume ls` reports so the target's own proof runs
    # against synthetic state instead of real Docker.
    stub_path.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$DOCKER_STUB_LOG"\n'
        'case "$1" in\n'
        "  compose) exit 0 ;;\n"
        "  volume)\n"
        '    if [ "$2" = "ls" ]; then printf "%s\\n" "$DOCKER_STUB_VOLUME_LS"; fi\n'
        '    exit "$DOCKER_STUB_VOLUME_LS_EXIT_CODE" ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub_path.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env["POSTGRES_PASSWORD"] = "civibus_dev"
    env["COMPOSE_PROJECT_NAME"] = project_name
    env["DOCKER_STUB_LOG"] = str(call_log)
    env["DOCKER_STUB_VOLUME_LS"] = volume_ls_output
    env["DOCKER_STUB_VOLUME_LS_EXIT_CODE"] = str(volume_ls_exit_code)

    completed = subprocess.run(
        ["make", "--no-print-directory", "db-teardown"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    return completed, call_log


def test_db_teardown_target_owns_destructive_compose_and_volume_proof() -> None:
    target_block = _make_target_block("db-teardown")
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert "db-teardown: require-postgres-password" in makefile_text
    assert TEARDOWN_COMPOSE_COMMAND in target_block
    assert TEARDOWN_VOLUME_PROOF in target_block
    assert "volume_ls_status=$$?" in target_block
    assert "TEARDOWN FAILED: unable to inspect Docker volumes" in target_block
    assert "TEARDOWN FAILED: %s volume survives" in target_block
    assert "TEARDOWN CLEAN: docker volume ls contains no %s volume" in target_block
    assert "$(COMPOSE_PROJECT_NAME)" not in "\n".join(target_block.splitlines()[1:])
    assert any(line.startswith(".PHONY:") and "db-teardown" in line.split() for line in makefile_text.splitlines())
    # db-down stays the non-destructive path: the volumes flag lives only here.
    assert "--volumes" not in _make_target_block("db-down")


def test_db_teardown_fails_without_touching_real_docker_when_volume_survives(tmp_path: Path) -> None:
    completed, call_log = _run_db_teardown_with_stub_docker(tmp_path, "civibus_c3_civibus_db_data")

    assert completed.returncode != 0
    assert "TEARDOWN FAILED: civibus_c3 volume survives" in completed.stderr
    assert TEARDOWN_CLEAN_RECEIPT not in completed.stdout
    logged_calls = call_log.read_text(encoding="utf-8")
    assert "compose -f infra/docker-compose.yml down --volumes --remove-orphans" in logged_calls


def test_db_teardown_clean_path_emits_expanded_receipt(tmp_path: Path) -> None:
    # civibus_c30 shares the civibus_c3 prefix; the anchored proof must not
    # false-match it and must report the lane as clean.
    completed, call_log = _run_db_teardown_with_stub_docker(tmp_path, "civibus_c30_civibus_db_data")

    assert completed.returncode == 0, completed.stderr
    assert TEARDOWN_CLEAN_RECEIPT in completed.stdout
    logged_calls = call_log.read_text(encoding="utf-8")
    assert "compose -f infra/docker-compose.yml down --volumes --remove-orphans" in logged_calls

    injection_tmp_path = tmp_path / "injection_case"
    injection_tmp_path.mkdir()
    marker_path = injection_tmp_path / "project_name_was_executed"
    malicious_project = f'civibus_c3"; touch {marker_path}; echo "'
    malicious_completed, _ = _run_db_teardown_with_stub_docker(
        injection_tmp_path,
        "unrelated_volume",
        project_name=malicious_project,
    )

    assert not marker_path.exists(), "db-teardown must treat COMPOSE_PROJECT_NAME as data, not shell source"
    assert malicious_completed.returncode == 0, malicious_completed.stderr

    make_injection_tmp_path = tmp_path / "make_injection_case"
    make_injection_tmp_path.mkdir()
    make_marker_path = make_injection_tmp_path / "make_function_was_executed"
    make_syntax_project = f"$(shell touch {make_marker_path})"
    make_syntax_completed, _ = _run_db_teardown_with_stub_docker(
        make_injection_tmp_path,
        "unrelated_volume",
        project_name=make_syntax_project,
    )

    assert not make_marker_path.exists(), "db-teardown must not recursively expand caller-supplied Make syntax"
    assert make_syntax_completed.returncode == 0, make_syntax_completed.stderr


def test_db_teardown_fails_when_docker_volume_inspection_fails(tmp_path: Path) -> None:
    completed, call_log = _run_db_teardown_with_stub_docker(tmp_path, "", volume_ls_exit_code=7)

    assert completed.returncode != 0
    assert "TEARDOWN FAILED: unable to inspect Docker volumes" in completed.stderr
    assert TEARDOWN_CLEAN_RECEIPT not in completed.stdout
    logged_calls = call_log.read_text(encoding="utf-8")
    assert "compose -f infra/docker-compose.yml down --volumes --remove-orphans" in logged_calls
    assert "volume ls --format {{.Name}}" in logged_calls
