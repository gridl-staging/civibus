from __future__ import annotations

from pathlib import Path

import pytest

from infra.scripts import postgres_local


def test_resolve_local_postgres_runtime_uses_repo_runtime_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_connection = {
        "user": "contract-user",
        "password": "contract-password",
        "dbname": "contract-db",
        "host": "contract-host",
        "port": 6543,
    }
    observed: dict[str, object] = {}

    def fake_build_connection_parameters(**overrides: object) -> dict[str, object]:
        observed["build_connection_parameters_overrides"] = overrides
        return expected_connection

    def fake_compose_project_name(repo_root: Path | None = None) -> str:
        observed["compose_project_name_repo_root"] = repo_root
        return "contract-project"

    def fake_resolve_compose_service_container(service_name: str, *, repo_root: Path | None = None) -> str | None:
        observed["resolve_compose_service_container_service_name"] = service_name
        observed["resolve_compose_service_container_repo_root"] = repo_root
        return "contract-db-1"

    monkeypatch.setattr(postgres_local, "build_connection_parameters", fake_build_connection_parameters)
    monkeypatch.setattr(postgres_local, "compose_project_name", fake_compose_project_name)
    monkeypatch.setattr(postgres_local, "resolve_compose_service_container", fake_resolve_compose_service_container)

    runtime = postgres_local.resolve_local_postgres_runtime(repo_root=tmp_path)

    assert runtime.compose_project_name == "contract-project"
    assert runtime.compose_service_name == postgres_local.DB_SERVICE_NAME
    assert runtime.container_name == "contract-db-1"
    assert runtime.connection_parameters == expected_connection
    assert runtime.database_name == "contract-db"
    assert observed == {
        "build_connection_parameters_overrides": {},
        "compose_project_name_repo_root": tmp_path,
        "resolve_compose_service_container_service_name": postgres_local.DB_SERVICE_NAME,
        "resolve_compose_service_container_repo_root": tmp_path,
    }


def test_resolve_local_postgres_runtime_fails_when_db_container_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        postgres_local,
        "build_connection_parameters",
        lambda **overrides: {"user": "civibus", "dbname": "civibus", "host": "localhost", "port": 5433},
    )
    monkeypatch.setattr(postgres_local, "compose_project_name", lambda repo_root=None: "contract-project")
    monkeypatch.setattr(
        postgres_local,
        "resolve_compose_service_container",
        lambda service_name, *, repo_root=None: None,
    )

    with pytest.raises(
        RuntimeError,
        match="Unable to locate a running Compose container for service 'db' in project 'contract-project'",
    ):
        postgres_local.resolve_local_postgres_runtime(repo_root=tmp_path)


def test_create_backup_passes_postgres_password_via_environment_not_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}
    runtime = postgres_local.LocalPostgresRuntime(
        compose_project_name="contract-project",
        compose_service_name=postgres_local.DB_SERVICE_NAME,
        container_name="contract-db-1",
        connection_parameters={"user": "contract-user", "dbname": "contract-db", "host": "localhost", "port": 5433},
        database_name="contract-db",
    )

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed["command"] = command
        observed["kwargs"] = kwargs

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    backup_path = postgres_local.create_backup(output_dir=tmp_path, repo_root=tmp_path)

    command = observed["command"]
    kwargs = observed["kwargs"]

    assert backup_path.parent == tmp_path
    assert "PGPASSWORD=super-secret" not in command
    assert command[:4] == ["docker", "exec", "-e", "PGPASSWORD"]
    assert kwargs["env"]["PGPASSWORD"] == "super-secret"


def test_restore_backup_passes_postgres_password_via_environment_not_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_calls: list[dict[str, object]] = []
    dump_path = tmp_path / "fixture.dump"
    dump_path.write_bytes(b"dump-bytes")
    runtime = postgres_local.LocalPostgresRuntime(
        compose_project_name="contract-project",
        compose_service_name=postgres_local.DB_SERVICE_NAME,
        container_name="contract-db-1",
        connection_parameters={"user": "contract-user", "dbname": "contract-db", "host": "localhost", "port": 5433},
        database_name="contract-db",
    )

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed_calls.append({"command": command, "kwargs": kwargs})

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    postgres_local.restore_backup(dump_path=dump_path, repo_root=tmp_path)

    reset_call, restore_call = observed_calls
    restore_command = restore_call["command"]
    restore_kwargs = restore_call["kwargs"]

    assert reset_call["command"] == ["make", "db-reset"]
    assert "PGPASSWORD=super-secret" not in restore_command
    assert restore_command[:5] == ["docker", "exec", "-i", "-e", "PGPASSWORD"]
    assert restore_kwargs["env"]["PGPASSWORD"] == "super-secret"
