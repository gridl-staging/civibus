"""Safety contracts for the dry-run-first Civibus lane collector."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = REPO_ROOT / "infra/scripts/collect_lane_resources.py"


@dataclass(frozen=True)
class CollectorScenario:
    containers: tuple[dict[str, str], ...]
    volumes: tuple[dict[str, str], ...] = ()
    active_projects: tuple[str, ...] = ()
    apply: bool = False
    container_rm_error: str | None = None


def _container(
    name: str,
    project: str,
    *,
    state: str = "exited",
    ports: str = "",
    working_dir: str = "",
) -> dict[str, str]:
    return {
        "kind": "container",
        "identifier": f"id-{name}",
        "name": name,
        "state": state,
        "ports": ports,
        "project": project,
        "working_dir": working_dir,
    }


def _volume(name: str, project: str) -> dict[str, str]:
    return {
        "kind": "volume",
        "identifier": name,
        "name": name,
        "state": "",
        "ports": "",
        "project": project,
        "working_dir": "",
    }


def _write_docker_stub(tmp_path: Path) -> tuple[Path, Path]:
    stub_dir = tmp_path / "stub_bin"
    stub_dir.mkdir(parents=True)
    call_log = tmp_path / "docker_calls.log"
    docker_stub = stub_dir / "docker"
    docker_stub.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$DOCKER_STUB_LOG"\n'
        'if [ "$1 $2" = "container ls" ]; then\n'
        '  case "$*" in *\'{{json (.Label "\'*) ;; *) exit 65 ;; esac\n'
        '  printf "%s" "$DOCKER_STUB_CONTAINERS"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "volume ls" ]; then\n'
        '  case "$*" in *\'{{json (.Label "\'*) ;; *) exit 65 ;; esac\n'
        '  printf "%s" "$DOCKER_STUB_VOLUMES"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "container rm" ]; then\n'
        '  if [ -n "$DOCKER_STUB_CONTAINER_RM_ERROR" ]; then\n'
        '    printf "%s\\n" "$DOCKER_STUB_CONTAINER_RM_ERROR" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "volume rm" ]; then\n'
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)
    return stub_dir, call_log


def _json_lines(objects: tuple[dict[str, str], ...]) -> str:
    if not objects:
        return ""
    return "".join(f"{json.dumps(item)}\n" for item in objects)


def _run_collector(tmp_path: Path, scenario: CollectorScenario) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    stub_dir, call_log = _write_docker_stub(tmp_path)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{stub_dir}:{env['PATH']}",
            "DOCKER_STUB_LOG": str(call_log),
            "DOCKER_STUB_CONTAINERS": _json_lines(scenario.containers),
            "DOCKER_STUB_CONTAINER_RM_ERROR": scenario.container_rm_error or "",
            "DOCKER_STUB_VOLUMES": _json_lines(scenario.volumes),
        }
    )
    command = [sys.executable, str(COLLECTOR_PATH)]
    for project in scenario.active_projects:
        command.extend(("--active-project", project))
    if scenario.apply:
        command.append("--apply")
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
        check=False,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return completed, calls


def _create_merged_lane_worktree(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    lane_worktree = tmp_path / "lane_worktree"
    subprocess.run(("git", "init", "-b", "main", str(repository)), check=True, capture_output=True, text=True)
    subprocess.run(("git", "-C", str(repository), "config", "user.email", "test@example.invalid"), check=True)
    subprocess.run(("git", "-C", str(repository), "config", "user.name", "Collector Test"), check=True)
    (repository / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "base.txt"), check=True)
    subprocess.run(("git", "-C", str(repository), "commit", "-m", "base"), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(repository), "worktree", "add", "-b", "lane", str(lane_worktree)),
        check=True,
        capture_output=True,
        text=True,
    )
    (lane_worktree / "lane.txt").write_text("finished\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(lane_worktree), "add", "lane.txt"), check=True)
    subprocess.run(("git", "-C", str(lane_worktree), "commit", "-m", "finish lane"), check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(repository), "merge", "--ff-only", "lane"), check=True, capture_output=True, text=True
    )
    working_dir = lane_worktree / "infra"
    working_dir.mkdir()
    return working_dir


def test_merged_lane_orphan_is_collectable_and_apply_removes_only_its_objects(tmp_path: Path) -> None:
    working_dir = _create_merged_lane_worktree(tmp_path)
    scenario = CollectorScenario(
        containers=(_container("civibus_merged_lane-db-1", "civibus_merged_lane", working_dir=str(working_dir)),),
        volumes=(_volume("civibus_merged_lane_civibus_db_data", "civibus_merged_lane"),),
        active_projects=("civibus_active_lane",),
        apply=True,
    )

    completed, calls = _run_collector(tmp_path / "collector", scenario)

    assert completed.returncode == 0, completed.stderr
    assert "civibus_merged_lane-db-1\tcollectable\t" in completed.stdout
    assert "branch lane is merged into main" in completed.stdout
    assert any(call == "container rm id-civibus_merged_lane-db-1" for call in calls)
    assert any(call == "volume rm civibus_merged_lane_civibus_db_data" for call in calls)


def test_supplied_active_project_is_refused(tmp_path: Path) -> None:
    scenario = CollectorScenario(
        containers=(_container("civibus_a1-db-1", "civibus_a1"),),
        active_projects=("civibus_a1",),
        apply=True,
    )

    completed, calls = _run_collector(tmp_path, scenario)

    assert completed.returncode == 0, completed.stderr
    assert "civibus_a1-db-1\tactive\tproject was supplied as active" in completed.stdout
    assert not any(" rm " in f" {call} " for call in calls)


def test_merged_lane_with_uncommitted_work_is_refused(tmp_path: Path) -> None:
    working_dir = _create_merged_lane_worktree(tmp_path)
    (working_dir.parent / "unfinished.txt").write_text("still in progress\n", encoding="utf-8")
    scenario = CollectorScenario(
        containers=(_container("civibus_dirty_lane-db-1", "civibus_dirty_lane", working_dir=str(working_dir)),),
        active_projects=("civibus_active_lane",),
        apply=True,
    )

    completed, calls = _run_collector(tmp_path / "collector", scenario)

    assert completed.returncode == 0, completed.stderr
    assert "civibus_dirty_lane-db-1\tunclassified\tmatching workspace has uncommitted changes" in completed.stdout
    assert not any(" rm " in f" {call} " for call in calls)


def test_project_with_responding_published_port_is_refused(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        scenario = CollectorScenario(
            containers=(
                _container(
                    "civibus_finished-db-1",
                    "civibus_finished",
                    ports=f"127.0.0.1:{port}->5432/tcp",
                    working_dir=str(tmp_path / "missing_workspace"),
                ),
            ),
            active_projects=("civibus_active_lane",),
            apply=True,
        )

        completed, calls = _run_collector(tmp_path / "collector", scenario)

    assert completed.returncode == 0, completed.stderr
    assert f"civibus_finished-db-1\tlive\tpublished port 127.0.0.1:{port} responds" in completed.stdout
    assert not any(" rm " in f" {call} " for call in calls)


@pytest.mark.parametrize(
    ("state", "status", "reason"),
    (
        ("paused", "unclassified", "container civibus_finished-db-1 is paused, not a stopped terminal state"),
        ("restarting", "live", "container civibus_finished-db-1 is restarting"),
        ("created", "unclassified", "container civibus_finished-db-1 is created, not a stopped terminal state"),
    ),
)
def test_non_terminal_container_states_are_refused(
    tmp_path: Path,
    state: str,
    status: str,
    reason: str,
) -> None:
    working_dir = _create_merged_lane_worktree(tmp_path)
    scenario = CollectorScenario(
        containers=(
            _container("civibus_finished-db-1", "civibus_finished", state=state, working_dir=str(working_dir)),
        ),
        active_projects=("civibus_active_lane",),
        apply=True,
    )

    completed, calls = _run_collector(tmp_path / "collector", scenario)

    assert completed.returncode == 0, completed.stderr
    assert f"civibus_finished-db-1\t{status}\t{reason}" in completed.stdout
    assert not any(" rm " in f" {call} " for call in calls)


def test_foreign_names_are_unmatchable_by_anchored_project_predicate(tmp_path: Path) -> None:
    foreign_names = ("fjcloud_stage-db-1", "ayb-web-1", "fj_worker-db-1")
    scenario = CollectorScenario(
        containers=tuple(_container(name, name.rsplit("-", 2)[0]) for name in foreign_names),
        active_projects=("civibus_active_lane",),
        apply=True,
    )

    completed, calls = _run_collector(tmp_path, scenario)

    assert completed.returncode == 0, completed.stderr
    for name in foreign_names:
        assert f"{name}\tforeign\tCompose project is not anchored with civibus_" in completed.stdout
    assert not any(" rm " in f" {call} " for call in calls)


def test_unclassifiable_civibus_object_is_reported_and_dry_run_never_mutates(tmp_path: Path) -> None:
    ambiguous_workspace = tmp_path / "not_a_git_worktree" / "infra"
    ambiguous_workspace.mkdir(parents=True)
    scenario = CollectorScenario(
        containers=(
            _container(
                "civibus_mystery-db-1",
                "civibus_mystery",
                working_dir=str(ambiguous_workspace),
            ),
        ),
        volumes=(_volume("civibus_mystery_civibus_db_data", "civibus_mystery"),),
    )

    completed, calls = _run_collector(tmp_path / "collector", scenario)

    assert completed.returncode == 0, completed.stderr
    assert "MODE\tdry-run\tno Docker objects will be removed" in completed.stdout
    assert "civibus_mystery-db-1\tunclassified\t" in completed.stdout
    assert "civibus_mystery_civibus_db_data\tunclassified\t" in completed.stdout
    forbidden_mutations = ("container rm", "volume rm", "compose down")
    assert not any(mutation in call for call in calls for mutation in forbidden_mutations)


def test_unknown_flag_fails_closed_before_docker_discovery() -> None:
    completed = subprocess.run(
        (sys.executable, str(COLLECTOR_PATH), "--surprise"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 2
    assert "unrecognized arguments: --surprise" in completed.stderr


def test_apply_fails_closed_if_container_turns_running_before_removal(tmp_path: Path) -> None:
    working_dir = _create_merged_lane_worktree(tmp_path)
    scenario = CollectorScenario(
        containers=(_container("civibus_merged_lane-db-1", "civibus_merged_lane", working_dir=str(working_dir)),),
        volumes=(_volume("civibus_merged_lane_civibus_db_data", "civibus_merged_lane"),),
        active_projects=("civibus_active_lane",),
        apply=True,
        container_rm_error="Error response from daemon: cannot remove container because it is running",
    )

    completed, calls = _run_collector(tmp_path / "collector", scenario)

    assert completed.returncode == 1
    assert (
        "ERROR: docker container rm failed: Error response from daemon: cannot remove container because it is running"
        in completed.stderr
    )
    assert any(call == "container rm id-civibus_merged_lane-db-1" for call in calls)
    assert not any(call.startswith("container rm --force ") for call in calls)
    assert not any(call == "volume rm civibus_merged_lane_civibus_db_data" for call in calls)
    assert "REMOVED\tcontainer\tcivibus_merged_lane-db-1" not in completed.stdout
