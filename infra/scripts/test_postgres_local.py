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


def _make_test_runtime() -> postgres_local.LocalPostgresRuntime:
    return postgres_local.LocalPostgresRuntime(
        compose_project_name="contract-project",
        compose_service_name=postgres_local.DB_SERVICE_NAME,
        container_name="contract-db-1",
        connection_parameters={"user": "contract-user", "dbname": "contract-db", "host": "localhost", "port": 5433},
        database_name="contract-db",
    )


def _assert_no_pgpassword_exposure(calls: list[dict[str, object]]) -> None:
    for call in calls:
        cmd = call["command"]
        cmd_str = " ".join(str(c) for c in cmd)
        paired = list(zip(cmd, cmd[1:]))
        assert not any(a == "-e" and b == "PGPASSWORD" for a, b in paired), (
            f"PGPASSWORD must not appear as a docker exec -e arg: {cmd}"
        )
        assert "PGPASSWORD=" not in cmd_str
        env = call["kwargs"].get("env") or {}
        assert "PGPASSWORD" not in env, "PGPASSWORD must not be passed via subprocess env dict"


def test_create_backup_never_exposes_pgpassword_in_argv_or_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_calls: list[dict[str, object]] = []
    runtime = _make_test_runtime()

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed_calls.append({"command": command, "kwargs": kwargs})

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    backup_path = postgres_local.create_backup(output_dir=tmp_path, repo_root=tmp_path)

    assert backup_path.parent == tmp_path
    _assert_no_pgpassword_exposure(observed_calls)


def test_create_backup_writes_pgpass_into_container_via_stdin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_calls: list[dict[str, object]] = []
    runtime = _make_test_runtime()

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed_calls.append({"command": command, "kwargs": kwargs})

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    postgres_local.create_backup(output_dir=tmp_path, repo_root=tmp_path)

    assert len(observed_calls) >= 2, "create_backup must issue at least a .pgpass setup call and a pg_dump call"
    setup_call = observed_calls[0]
    setup_cmd_str = " ".join(str(c) for c in setup_call["command"])
    assert "docker" in setup_cmd_str and "exec" in setup_cmd_str
    assert ".pgpass" in setup_cmd_str
    assert setup_call["kwargs"].get("input") is not None, ".pgpass content must be piped via input, not passed as argv"


def test_create_backup_cleans_up_pgpass_after_dump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_calls: list[dict[str, object]] = []
    runtime = _make_test_runtime()

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed_calls.append({"command": command, "kwargs": kwargs})

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    postgres_local.create_backup(output_dir=tmp_path, repo_root=tmp_path)

    cleanup_call = observed_calls[-1]
    cleanup_cmd_str = " ".join(str(c) for c in cleanup_call["command"])
    assert "rm" in cleanup_cmd_str and ".pgpass" in cleanup_cmd_str, (
        "Last call must remove the temporary .pgpass from the container"
    )


def test_create_backup_runs_pg_dump_with_expected_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_calls: list[dict[str, object]] = []
    runtime = _make_test_runtime()

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed_calls.append({"command": command, "kwargs": kwargs})

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    postgres_local.create_backup(output_dir=tmp_path, repo_root=tmp_path)

    dump_call = next(c for c in observed_calls if "pg_dump" in " ".join(str(x) for x in c["command"]))
    dump_cmd = dump_call["command"]
    assert "pg_dump" in dump_cmd
    assert "-U" in dump_cmd
    idx_u = dump_cmd.index("-U")
    assert dump_cmd[idx_u + 1] == "contract-user"
    assert "-d" in dump_cmd
    idx_d = dump_cmd.index("-d")
    assert dump_cmd[idx_d + 1] == "contract-db"
    assert "--format=custom" in dump_cmd
    assert "--no-owner" in dump_cmd
    assert "--no-privileges" in dump_cmd


def test_restore_backup_never_exposes_pgpassword_in_argv_or_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_calls: list[dict[str, object]] = []
    dump_path = tmp_path / "fixture.dump"
    dump_path.write_bytes(b"dump-bytes")
    runtime = _make_test_runtime()

    def fake_run_command(command: list[str], **kwargs: object) -> None:
        observed_calls.append({"command": command, "kwargs": kwargs})

    monkeypatch.setattr(postgres_local, "resolve_local_postgres_runtime", lambda *, repo_root=tmp_path: runtime)
    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret")

    postgres_local.restore_backup(dump_path=dump_path, repo_root=tmp_path)

    assert observed_calls[0]["command"] == ["make", "db-reset"]
    _assert_no_pgpassword_exposure(observed_calls[1:])
