from __future__ import annotations

from pathlib import Path

import pytest

from core import schema_sql_runner


def test_build_base_psql_command_prefers_env_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SCHEMA_PSQL_CMD", "env PGPASSWORD=secret psql -h db -U civibus")

    assert schema_sql_runner.build_base_psql_command(
        "civibus_test",
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    ) == ["env", "PGPASSWORD=secret", "psql", "-h", "db", "-U", "civibus", "-d", "civibus_test"]


def test_build_base_psql_command_rejects_non_psql_env_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SCHEMA_PSQL_CMD", "python -c 'print(1)'")

    with pytest.raises(RuntimeError, match="must invoke psql directly or via docker exec"):
        schema_sql_runner.build_base_psql_command(
            "civibus_test",
            command_env_var="TEST_SCHEMA_PSQL_CMD",
            repo_root=Path("/tmp/repo"),
        )


def test_build_base_psql_command_rejects_env_psql_sql_execution_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SCHEMA_PSQL_CMD", "psql -f /tmp/evil.sql")

    with pytest.raises(RuntimeError, match="may not include psql SQL execution flags"):
        schema_sql_runner.build_base_psql_command(
            "civibus_test",
            command_env_var="TEST_SCHEMA_PSQL_CMD",
            repo_root=Path("/tmp/repo"),
        )


def test_build_base_psql_command_accepts_env_wrapped_docker_exec_psql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "TEST_SCHEMA_PSQL_CMD",
        "env PGPASSWORD=secret docker exec custom-db psql -U civibus -h db.internal",
    )

    assert schema_sql_runner.build_base_psql_command(
        "civibus_test",
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    ) == [
        "env",
        "PGPASSWORD=secret",
        "docker",
        "exec",
        "custom-db",
        "psql",
        "-U",
        "civibus",
        "-h",
        "db.internal",
        "-d",
        "civibus_test",
    ]


def test_build_base_psql_command_rejects_env_wrapped_docker_exec_without_psql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_SCHEMA_PSQL_CMD", "env PGPASSWORD=secret docker exec custom-db sh -lc 'echo nope'")

    with pytest.raises(RuntimeError, match="must invoke psql directly or via docker exec"):
        schema_sql_runner.build_base_psql_command(
            "civibus_test",
            command_env_var="TEST_SCHEMA_PSQL_CMD",
            repo_root=Path("/tmp/repo"),
        )


def test_build_base_psql_command_uses_compose_container_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_SCHEMA_PSQL_CMD", raising=False)
    monkeypatch.setattr("core.schema_sql_runner.shutil.which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        "core.schema_sql_runner.resolve_compose_service_container", lambda service_name, *, repo_root: "db-1"
    )

    assert schema_sql_runner.build_base_psql_command(
        "civibus_test",
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    ) == ["docker", "exec", "db-1", "psql", "-U", "civibus", "-d", "civibus_test"]


def test_build_base_psql_command_falls_back_to_local_psql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_SCHEMA_PSQL_CMD", raising=False)

    def fake_which(command: str) -> str | None:
        return "/usr/bin/psql" if command == "psql" else None

    monkeypatch.setattr("core.schema_sql_runner.shutil.which", fake_which)
    monkeypatch.setattr(
        "core.schema_sql_runner.resolve_compose_service_container", lambda service_name, *, repo_root: None
    )

    assert schema_sql_runner.build_base_psql_command(
        "civibus_test",
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    ) == ["psql", "-d", "civibus_test"]


def test_run_psql_command_uses_psycopg_fallback_when_no_cli_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: [],
    )
    monkeypatch.setattr(
        "core.schema_sql_runner.run_sql_via_psycopg",
        lambda database, sql, *, expect_tuples=True: ["1"],
    )

    result = schema_sql_runner.run_psql_command(
        "civibus_test",
        "SELECT 1;",
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    assert result == ["1"]


def test_run_psql_command_ignores_psql_command_status_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: ["psql", "-d", database],
    )
    monkeypatch.setattr("core.schema_sql_runner._run_command", lambda command: "person\nINSERT 0 1")

    result = schema_sql_runner.run_psql_command(
        "civibus_test",
        "SELECT 'person';",
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    assert result == ["person"]


def test_run_psql_file_uses_psycopg_fallback_when_no_cli_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: [],
    )
    monkeypatch.setattr(
        "core.schema_sql_runner.run_sql_file_via_psycopg",
        lambda database, path: calls.append((database, path)),
    )

    schema_sql_runner.run_psql_file(
        "civibus_test",
        sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    assert calls == [("civibus_test", sql_file)]


def test_run_psql_file_preserves_env_docker_command_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    commands: list[list[str]] = []
    base_command = [
        "docker",
        "exec",
        "custom-db",
        "psql",
        "-U",
        "custom-user",
        "-h",
        "db.internal",
        "-d",
        "civibus_test",
    ]
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: base_command,
    )
    monkeypatch.setattr("core.schema_sql_runner._run_command", lambda command: commands.append(command) or "")

    schema_sql_runner.run_psql_file(
        "civibus_test",
        sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    copied_target = commands[0][3]
    container_sql_path = copied_target.split(":", maxsplit=1)[1]
    assert commands == [
        ["docker", "cp", str(sql_file), copied_target],
        base_command + ["-v", "ON_ERROR_STOP=1", "-f", container_sql_path],
        ["docker", "exec", "custom-db", "rm", "-f", container_sql_path],
    ]
    assert copied_target.startswith("custom-db:/tmp/")
    assert container_sql_path.endswith("-test.sql")


def test_run_psql_file_handles_docker_exec_flags_when_copying_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    commands: list[list[str]] = []
    base_command = [
        "docker",
        "exec",
        "-i",
        "--user",
        "postgres",
        "custom-db",
        "psql",
        "-U",
        "custom-user",
        "-d",
        "civibus_test",
    ]
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: base_command,
    )
    monkeypatch.setattr("core.schema_sql_runner._run_command", lambda command: commands.append(command) or "")

    schema_sql_runner.run_psql_file(
        "civibus_test",
        sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    copied_target = commands[0][3]
    assert copied_target.startswith("custom-db:/tmp/")
    assert commands[1] == base_command + ["-v", "ON_ERROR_STOP=1", "-f", copied_target.split(":", maxsplit=1)[1]]
    assert commands[2] == [
        "docker",
        "exec",
        "-i",
        "--user",
        "postgres",
        "custom-db",
        "rm",
        "-f",
        copied_target.split(":", maxsplit=1)[1],
    ]


def test_run_psql_file_uses_distinct_container_paths_for_duplicate_basenames(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_sql_file = tmp_path / "property" / "tables.sql"
    first_sql_file.parent.mkdir()
    first_sql_file.write_text("SELECT 1;", encoding="utf-8")
    second_sql_file = tmp_path / "campaign_finance" / "tables.sql"
    second_sql_file.parent.mkdir()
    second_sql_file.write_text("SELECT 1;", encoding="utf-8")
    commands: list[list[str]] = []
    base_command = ["docker", "exec", "custom-db", "psql", "-U", "custom-user", "-d", "civibus_test"]
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: base_command,
    )
    monkeypatch.setattr("core.schema_sql_runner._run_command", lambda command: commands.append(command) or "")

    schema_sql_runner.run_psql_file(
        "civibus_test",
        first_sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )
    schema_sql_runner.run_psql_file(
        "civibus_test",
        second_sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    first_target = commands[0][3]
    second_target = commands[3][3]
    assert first_target != second_target
    assert first_target.startswith("custom-db:/tmp/")
    assert second_target.startswith("custom-db:/tmp/")


def test_run_psql_file_uses_unique_container_path_for_repeated_same_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sql_file = tmp_path / "tables.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    commands: list[list[str]] = []
    base_command = ["docker", "exec", "custom-db", "psql", "-U", "custom-user", "-d", "civibus_test"]
    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: base_command,
    )
    monkeypatch.setattr("core.schema_sql_runner._run_command", lambda command: commands.append(command) or "")

    schema_sql_runner.run_psql_file(
        "civibus_test",
        sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )
    schema_sql_runner.run_psql_file(
        "civibus_test",
        sql_file,
        command_env_var="TEST_SCHEMA_PSQL_CMD",
        repo_root=Path("/tmp/repo"),
    )

    first_target = commands[0][3]
    second_target = commands[3][3]
    assert first_target != second_target
    assert first_target.startswith("custom-db:/tmp/")
    assert second_target.startswith("custom-db:/tmp/")


def test_run_psql_file_cleans_up_container_temp_sql_when_psql_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sql_file = tmp_path / "tables.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    commands: list[list[str]] = []
    base_command = ["docker", "exec", "custom-db", "psql", "-U", "custom-user", "-d", "civibus_test"]

    monkeypatch.setattr(
        "core.schema_sql_runner.build_base_psql_command",
        lambda database, *, command_env_var, repo_root: base_command,
    )

    def fake_run_command(command: list[str]) -> str:
        commands.append(command)
        if command[:4] == base_command[:4]:
            raise RuntimeError("psql failed")
        return ""

    monkeypatch.setattr("core.schema_sql_runner._run_command", fake_run_command)

    with pytest.raises(RuntimeError, match="psql failed"):
        schema_sql_runner.run_psql_file(
            "civibus_test",
            sql_file,
            command_env_var="TEST_SCHEMA_PSQL_CMD",
            repo_root=Path("/tmp/repo"),
        )

    container_sql_path = commands[0][3].split(":", maxsplit=1)[1]
    assert commands == [
        ["docker", "cp", str(sql_file), f"custom-db:{container_sql_path}"],
        base_command + ["-v", "ON_ERROR_STOP=1", "-f", container_sql_path],
        ["docker", "exec", "custom-db", "rm", "-f", container_sql_path],
    ]
