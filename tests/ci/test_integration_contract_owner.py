"""Contract tests for the workflow-owned DB-backed integration suite."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/integration.yml"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
DB_BACKED_STEP_NAME = "DB-backed product suite"
QA_INTEGRATION_TARGET = "qa-integration"
COMPATIBILITY_TARGET = "test-integration-local"
DOCKER_UNAVAILABLE_MESSAGE = "qa-integration requires Docker-backed PostgreSQL, but the Docker daemon is unavailable"
WORKFLOW_PARITY_PATHS = frozenset(
    {
        "api/",
        "core/",
        "domains/",
        "tests/integration/",
        "tests/e2e/",
        "tests/test_db_integration.py",
        "tests/test_graph_queries.py",
        "tests/test_relational_queries.py",
    }
)
MAKE_EXECUTABLE = shutil.which("make")
assert MAKE_EXECUTABLE is not None, "contract tests require make"
DOCKER_STUB_SCRIPT = (
    "#!/bin/sh\n"
    'printf "docker %s\\n" "$*" >> "$QA_STUB_LOG"\n'
    'if [ "$1" = "info" ]; then exit "$DOCKER_INFO_STATUS"; fi\n'
    'if [ "$1" = "compose" ] && [ "$4" = "ps" ]; then printf "%s\\n" "stub-db"; fi\n'
    'if [ "$1" = "inspect" ]; then printf "%s\\n" "healthy"; fi\n'
    "exit 0\n"
)
NESTED_MAKE_STUB_SCRIPT = (
    "#!/bin/sh\n"
    'printf "nested-make %s\\n" "$*" >> "$QA_STUB_LOG"\n'
    'if [ "$1" = "$NESTED_MAKE_FAILURE" ]; then exit 17; fi\n'
    "exit 0\n"
)
UV_STUB_SCRIPT = (
    "#!/bin/sh\n"
    'count=0; if [ -f "$QA_PYTEST_COUNT" ]; then count="$(cat "$QA_PYTEST_COUNT")"; fi\n'
    'count=$((count + 1)); printf "%s\\n" "$count" > "$QA_PYTEST_COUNT"\n'
    'printf "uv CIVIBUS_REQUIRE_DB=%s %s\\n" "${CIVIBUS_REQUIRE_DB:-}" "$*" >> "$QA_STUB_LOG"\n'
    'if [ "$count" -eq "$UV_FAILURE_CALL" ]; then exit 23; fi\n'
    "exit 0\n"
)


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


def _make_target_declarations(target_name: str) -> list[str]:
    target_header = f"{target_name}:"
    return [
        line
        for line in MAKEFILE_PATH.read_text(encoding="utf-8").splitlines()
        if line == target_header or line.startswith(f"{target_header} ")
    ]


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


def _workflow_parity_command(target_block: str) -> str:
    command_prefix = "CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest -m"
    command_start = target_block.index(command_prefix)
    command_end = target_block.index("; \\\n", command_start)
    return target_block[command_start:command_end]


def test_qa_integration_matches_workflow_owned_pytest_contract() -> None:
    workflow_contract = _pytest_marker_and_paths(_db_backed_workflow_command())
    target_block = _make_target_block(QA_INTEGRATION_TARGET)
    makefile_contract = _pytest_marker_and_paths(_workflow_parity_command(target_block))

    assert makefile_contract == workflow_contract
    assert makefile_contract == ("integration and not quarantined", WORKFLOW_PARITY_PATHS)


def test_qa_integration_owns_workflow_setup_and_standalone_lifecycle() -> None:
    target_block = _make_target_block(QA_INTEGRATION_TARGET)
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    setup_commands = (
        "$(MAKE) db-up",
        "$(MAKE) db-reset",
        "$(MAKE) ingest-fec-bulk-sample",
        "$(MAKE) graph-load",
    )

    setup_positions = [target_block.index(command) for command in setup_commands]
    assert setup_positions == sorted(setup_positions)
    assert "qa-integration: override POSTGRES_PORT := 5475" in makefile_text
    assert "qa-integration: override COMPOSE_PROJECT_NAME := civibus_integration_local" in makefile_text
    assert any(
        line.startswith(".PHONY:") and QA_INTEGRATION_TARGET in line.split() for line in makefile_text.splitlines()
    )
    assert "POSTGRES_PORT=5475" in target_block
    assert "cleanup_required=0" in target_block
    assert "probe.bind" in target_block
    volume_cleanup = "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans"
    assert target_block.count(volume_cleanup) == 2
    assert target_block.index(volume_cleanup) < target_block.index("$(MAKE) db-up")
    cleanup_required_position = target_block.index("cleanup_required=1")
    initial_cleanup_position = target_block.index(volume_cleanup, cleanup_required_position)
    make_db_up_position = target_block.index("$(MAKE) db-up")
    container_lookup_position = target_block.index(
        'container_id="$$(docker compose -f infra/docker-compose.yml ps -q db)"'
    )
    assert target_block.index("trap cleanup EXIT") < cleanup_required_position
    assert cleanup_required_position < initial_cleanup_position < make_db_up_position
    assert make_db_up_position < container_lookup_position
    assert "docker inspect" in target_block
    assert "make db-down" not in target_block
    assert "\n\tmake " not in target_block


def test_compatibility_target_is_a_prerequisite_only_alias() -> None:
    assert _make_target_declarations(COMPATIBILITY_TARGET) == ["test-integration-local: qa-integration"]


def test_qa_integration_explicitly_runs_workflow_and_merge_db_suites() -> None:
    target_block = _make_target_block(QA_INTEGRATION_TARGET)
    workflow_command = _workflow_parity_command(target_block)
    merge_command = (
        "CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest $(MERGE_DB_BACKED_TEST_NODES)"
    )

    assert workflow_command.startswith("CIVIBUS_REQUIRE_DB=1 ")
    assert merge_command in target_block
    assert target_block.index(workflow_command) < target_block.index(merge_command)
    assert target_block.count("CIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest") == 2


def test_qa_integration_signal_traps_exit_through_cleanup() -> None:
    target_block = _make_target_block(QA_INTEGRATION_TARGET)

    assert target_block.index("trap cleanup EXIT") < target_block.index("$(MAKE) db-up")
    for signal_name, exit_status in (("HUP", 129), ("INT", 130), ("TERM", 143)):
        assert f"trap 'exit {exit_status}' {signal_name}" in target_block


def test_qa_integration_and_alias_reject_incompatible_port_before_compose(tmp_path: Path) -> None:
    refusal = "qa-integration pins POSTGRES_PORT=5475 internally; do not provide a POSTGRES_PORT override"
    for target_name in (QA_INTEGRATION_TARGET, COMPATIBILITY_TARGET):
        completed = subprocess.run(
            [MAKE_EXECUTABLE, "--no-print-directory", "POSTGRES_PORT=5433", target_name],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert completed.returncode != 0
        assert refusal in completed.stderr
        assert "docker compose" not in completed.stdout

    marker_path = tmp_path / "make_function_was_expanded"
    malicious_completed = subprocess.run(
        [
            MAKE_EXECUTABLE,
            "--no-print-directory",
            f"POSTGRES_PORT=$(shell touch {marker_path})",
            QA_INTEGRATION_TARGET,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert malicious_completed.returncode != 0
    assert refusal in malicious_completed.stderr
    assert not marker_path.exists()
    assert "docker compose" not in malicious_completed.stdout


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _create_qa_command_stubs(stub_dir: Path) -> tuple[Path, Path]:
    stub_dir.mkdir(parents=True)
    docker_stub = stub_dir / "docker"
    nested_make_stub = stub_dir / "nested_make"
    uv_stub = stub_dir / "uv"
    _write_executable(docker_stub, DOCKER_STUB_SCRIPT)
    _write_executable(nested_make_stub, NESTED_MAKE_STUB_SCRIPT)
    _write_executable(uv_stub, UV_STUB_SCRIPT)
    return stub_dir, nested_make_stub


def _run_qa_integration_with_stubs(
    tmp_path: Path,
    *,
    docker_info_status: int = 0,
    failing_nested_target: str = "",
    failing_pytest_call: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    stub_dir, nested_make_stub = _create_qa_command_stubs(tmp_path / "stub_bin")
    call_log = tmp_path / "calls.log"
    pytest_count = tmp_path / "pytest_count"

    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{stub_dir}:{env['PATH']}",
            "POSTGRES_PASSWORD": "contract-only-password",
            "DOCKER_INFO_STATUS": str(docker_info_status),
            "NESTED_MAKE_FAILURE": failing_nested_target,
            "UV_FAILURE_CALL": str(failing_pytest_call),
            "QA_STUB_LOG": str(call_log),
            "QA_PYTEST_COUNT": str(pytest_count),
        }
    )
    env.pop("POSTGRES_PORT", None)
    env.pop("COMPOSE_PROJECT_NAME", None)
    completed = subprocess.run(
        [
            MAKE_EXECUTABLE,
            "--no-print-directory",
            f"MAKE={nested_make_stub}",
            QA_INTEGRATION_TARGET,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=False,
    )
    logged_calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return completed, logged_calls


def test_qa_integration_refuses_unavailable_docker_before_mutation_or_pytest(tmp_path: Path) -> None:
    completed, logged_calls = _run_qa_integration_with_stubs(tmp_path, docker_info_status=1)

    assert completed.returncode != 0
    assert completed.stderr.splitlines().count(DOCKER_UNAVAILABLE_MESSAGE) == 1
    assert logged_calls == ["docker info"]


def test_qa_integration_cleanup_covers_success_and_owned_failures(tmp_path: Path) -> None:
    success, success_calls = _run_qa_integration_with_stubs(tmp_path / "success")
    pytest_failure, pytest_failure_calls = _run_qa_integration_with_stubs(
        tmp_path / "pytest_failure", failing_pytest_call=1
    )
    db_up_failure, db_up_failure_calls = _run_qa_integration_with_stubs(
        tmp_path / "db_up_failure", failing_nested_target="db-up"
    )
    setup_failure, setup_failure_calls = _run_qa_integration_with_stubs(
        tmp_path / "setup_failure", failing_nested_target="db-reset"
    )
    cleanup_call = "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans"

    assert success.returncode == 0, success.stderr
    assert success_calls.count(cleanup_call) == 2
    assert [call for call in success_calls if call.startswith("nested-make")] == [
        "nested-make db-up",
        "nested-make db-reset",
        "nested-make ingest-fec-bulk-sample",
        "nested-make graph-load",
    ]
    assert [call for call in success_calls if call.startswith("uv ")] == [
        call for call in success_calls if call.startswith("uv CIVIBUS_REQUIRE_DB=1 ")
    ]
    assert len([call for call in success_calls if call.startswith("uv ")]) == 2

    assert pytest_failure.returncode != 0
    assert pytest_failure_calls.count(cleanup_call) == 2
    assert len([call for call in pytest_failure_calls if call.startswith("uv ")]) == 1

    assert db_up_failure.returncode != 0
    assert db_up_failure_calls.count(cleanup_call) == 2
    assert "nested-make db-up" in db_up_failure_calls
    assert not any(call.startswith("uv ") for call in db_up_failure_calls)

    assert setup_failure.returncode != 0
    assert setup_failure_calls.count(cleanup_call) == 2
    assert "nested-make db-up" in setup_failure_calls
    assert not any(call.startswith("uv ") for call in setup_failure_calls)


TEARDOWN_COMPOSE_COMMAND = "docker compose -f infra/docker-compose.yml down --volumes --remove-orphans"
TEARDOWN_VOLUME_PROOF = 'grep -Fqx "$${COMPOSE_PROJECT_NAME}_civibus_db_data"'
TEARDOWN_CLEAN_RECEIPT = "TEARDOWN CLEAN: docker volume ls contains no civibus_c3 volume"


def _run_db_target_with_stub_docker(
    tmp_path: Path,
    target_name: str,
    env_overrides: dict[str, str | None] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    stub_dir = tmp_path / "stub_bin"
    stub_dir.mkdir(parents=True)
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
    env["COMPOSE_PROJECT_NAME"] = "civibus_c3"
    env["DOCKER_STUB_VOLUME_LS"] = "unrelated_volume"
    env["DOCKER_STUB_VOLUME_LS_EXIT_CODE"] = "0"
    env["DOCKER_STUB_LOG"] = str(call_log)
    env.pop("POSTGRES_PORT", None)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    completed = subprocess.run(
        ["make", "--no-print-directory", target_name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    return completed, call_log


def _run_db_teardown_with_stub_docker(
    tmp_path: Path,
    volume_ls_output: str,
    volume_ls_exit_code: int = 0,
    project_name: str = "civibus_c3",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    return _run_db_target_with_stub_docker(
        tmp_path,
        "db-teardown",
        {
            "COMPOSE_PROJECT_NAME": project_name,
            "DOCKER_STUB_VOLUME_LS": volume_ls_output,
            "DOCKER_STUB_VOLUME_LS_EXIT_CODE": str(volume_ls_exit_code),
            "POSTGRES_PORT": "5543",
        },
    )


def test_db_lifecycle_targets_reject_unallocated_lane_port_before_docker(tmp_path: Path) -> None:
    for target_name in ("db-down", "db-teardown"):
        completed, call_log = _run_db_target_with_stub_docker(
            tmp_path / target_name,
            target_name,
            {"COMPOSE_PROJECT_NAME": "civibus_a10"},
        )

        assert completed.returncode != 0
        assert "A non-empty POSTGRES_PORT must be supplied by environment or command line" in completed.stderr
        assert "COMPOSE_PROJECT_NAME=civibus_a10" in completed.stderr
        assert not call_log.exists() or call_log.read_text(encoding="utf-8") == ""


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
