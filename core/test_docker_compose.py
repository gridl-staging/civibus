from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.docker_compose import compose_project_name, resolve_compose_service_container, workspace_slug


def test_compose_project_name_prefers_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "custom_project")

    assert compose_project_name() == "custom_project"


def test_workspace_slug_derives_from_repo_parent_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    repo_root = tmp_path / "Mar15 Stage1 Closeout"
    repo_root = repo_root / "civibus_dev"
    repo_root.mkdir(parents=True)

    assert workspace_slug(repo_root) == "mar15_stage1_closeout"
    assert compose_project_name(repo_root) == "civibus_mar15_stage1_closeout"


def test_resolve_compose_service_container_filters_by_project_and_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    repo_root = tmp_path / "parallel workspace" / "civibus_dev"
    repo_root.mkdir(parents=True)
    recorded: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        recorded["command"] = command
        recorded["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="civibus_parallel_workspace-db-1\n", stderr="")

    monkeypatch.setattr("core.docker_compose.subprocess.run", fake_run)

    container_name = resolve_compose_service_container("db", repo_root=repo_root)

    assert container_name == "civibus_parallel_workspace-db-1"
    assert recorded["command"] == [
        "docker",
        "ps",
        "--filter",
        "label=com.docker.compose.project=civibus_parallel_workspace",
        "--filter",
        "label=com.docker.compose.service=db",
        "--format",
        "{{.Names}}",
    ]
    assert recorded["kwargs"] == {"check": False, "capture_output": True, "text": True}


def test_resolve_compose_service_container_returns_none_on_docker_error(monkeypatch) -> None:
    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="docker unavailable")

    monkeypatch.setattr("core.docker_compose.subprocess.run", fake_run)

    assert resolve_compose_service_container("db") is None
