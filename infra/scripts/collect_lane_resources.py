#!/usr/bin/env python3
"""Collect positively identified, finished Civibus Compose lane resources."""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"
CIVIBUS_PROJECT_PREFIX = "civibus_"
PUBLISHED_PORT_PATTERN = re.compile(r"(?:(?P<host>[^,:]+):)?(?P<port>[0-9]+)->")
LIVE_CONTAINER_STATES = frozenset({"running", "restarting"})
STOPPED_TERMINAL_CONTAINER_STATES = frozenset({"exited", "dead"})


@dataclass(frozen=True)
class DockerObject:
    kind: str
    identifier: str
    name: str
    state: str
    ports: str
    project: str
    working_dir: str


@dataclass(frozen=True)
class Classification:
    status: str
    reason: str


def _docker_output(arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ("docker", *arguments),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"docker {' '.join(arguments[:2])} failed: {detail}")
    return completed.stdout


def _decode_objects(output: str) -> list[DockerObject]:
    objects: list[DockerObject] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        try:
            raw = json.loads(line)
            objects.append(DockerObject(**raw))
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError(f"invalid Docker discovery record on line {line_number}: {error}") from error
    return objects


def discover_containers() -> list[DockerObject]:
    record_template = (
        '{"kind":"container","identifier":{{json .ID}},"name":{{json .Names}},'
        '"state":{{json .State}},"ports":{{json .Ports}},'
        f'"project":{{{{json (.Label "{COMPOSE_PROJECT_LABEL}")}}}},'
        f'"working_dir":{{{{json (.Label "{COMPOSE_WORKING_DIR_LABEL}")}}}}}}'
    )
    output = _docker_output(("container", "ls", "--all", "--format", record_template))
    return _decode_objects(output)


def discover_volumes() -> list[DockerObject]:
    record_template = (
        '{"kind":"volume","identifier":{{json .Name}},"name":{{json .Name}},'
        '"state":"","ports":"",'
        f'"project":{{{{json (.Label "{COMPOSE_PROJECT_LABEL}")}}}},"working_dir":""}}'
    )
    output = _docker_output(("volume", "ls", "--format", record_template))
    return _decode_objects(output)


def discover_docker_objects() -> list[DockerObject]:
    return [*discover_containers(), *discover_volumes()]


def extract_compose_projects(objects: Iterable[DockerObject]) -> dict[str, list[DockerObject]]:
    projects: dict[str, list[DockerObject]] = defaultdict(list)
    for docker_object in objects:
        projects[docker_object.project].append(docker_object)
    return dict(projects)


def _published_endpoints(objects: Iterable[DockerObject]) -> Iterable[tuple[str, int]]:
    for docker_object in objects:
        for match in PUBLISHED_PORT_PATTERN.finditer(docker_object.ports):
            host = match.group("host") or "127.0.0.1"
            if host in {"0.0.0.0", "::", "[::]"}:
                host = "127.0.0.1"
            yield host, int(match.group("port"))


def _first_responding_endpoint(objects: Iterable[DockerObject]) -> tuple[str, int] | None:
    for host, port in _published_endpoints(objects):
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return host, port
        except OSError:
            continue
    return None


def classify_container_runtime(objects: Iterable[DockerObject]) -> Classification | None:
    for docker_object in objects:
        if docker_object.kind != "container":
            continue
        state = docker_object.state.lower()
        if state in STOPPED_TERMINAL_CONTAINER_STATES:
            continue
        if state in LIVE_CONTAINER_STATES:
            return Classification("live", f"container {docker_object.name} is {state}")
        return Classification(
            "unclassified", f"container {docker_object.name} is {state}, not a stopped terminal state"
        )
    return None


def _git_output(working_dir: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(working_dir), *arguments),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def classify_finished_lane(objects: Sequence[DockerObject]) -> Classification:
    working_dirs = {Path(item.working_dir) for item in objects if item.working_dir}
    if not working_dirs:
        return Classification("unclassified", "no matching workspace path was discovered")
    if len(working_dirs) != 1:
        return Classification("unclassified", "Compose objects disagree about the matching workspace path")

    working_dir = next(iter(working_dirs))
    if not working_dir.exists():
        return Classification("collectable", f"matching workspace is gone: {working_dir}")

    status_result = _git_output(working_dir, "status", "--porcelain", "--untracked-files=normal")
    if status_result.returncode != 0:
        return Classification("unclassified", f"matching workspace is not an inspectable Git worktree: {working_dir}")
    if status_result.stdout:
        return Classification("unclassified", "matching workspace has uncommitted changes")

    branch_result = _git_output(working_dir, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch_result.returncode != 0:
        return Classification("unclassified", f"matching workspace has no inspectable branch: {working_dir}")
    branch = branch_result.stdout.strip()
    merged_result = _git_output(working_dir, "merge-base", "--is-ancestor", "HEAD", "main")
    if merged_result.returncode == 0:
        return Classification("collectable", f"branch {branch} is merged into main")
    if merged_result.returncode == 1:
        return Classification("unclassified", f"branch {branch} is not merged into main")
    detail = merged_result.stderr.strip() or "git could not inspect main"
    return Classification("unclassified", detail)


def classify_project(
    project: str,
    objects: Sequence[DockerObject],
    active_projects: frozenset[str],
) -> Classification:
    if not project.startswith(CIVIBUS_PROJECT_PREFIX):
        return Classification("foreign", "Compose project is not anchored with civibus_")
    if project in active_projects:
        return Classification("active", "project was supplied as active")

    endpoint = _first_responding_endpoint(objects)
    if endpoint is not None:
        return Classification("live", f"published port {endpoint[0]}:{endpoint[1]} responds")
    container_runtime = classify_container_runtime(objects)
    if container_runtime is not None:
        return container_runtime
    return classify_finished_lane(objects)


def classify_all(
    objects: Sequence[DockerObject],
    active_projects: frozenset[str],
) -> dict[str, Classification]:
    return {
        project: classify_project(project, project_objects, active_projects)
        for project, project_objects in extract_compose_projects(objects).items()
    }


def report(objects: Sequence[DockerObject], classifications: dict[str, Classification]) -> None:
    for docker_object in objects:
        classification = classifications[docker_object.project]
        project = docker_object.project or "<none>"
        print(
            f"{docker_object.kind}\t{docker_object.name}\t{classification.status}\t"
            f"{classification.reason}\tproject={project}"
        )


def execute_collection(objects: Sequence[DockerObject]) -> None:
    containers = [item for item in objects if item.kind == "container"]
    volumes = [item for item in objects if item.kind == "volume"]
    for container in containers:
        _docker_output(("container", "rm", container.identifier))
        print(f"REMOVED\tcontainer\t{container.name}")
    for volume in volumes:
        _docker_output(("volume", "rm", volume.identifier))
        print(f"REMOVED\tvolume\t{volume.name}")


def apply_collectable_projects(active_projects: frozenset[str], projects: Iterable[str]) -> None:
    for project in projects:
        current_objects = discover_docker_objects()
        grouped_objects = extract_compose_projects(current_objects)
        project_objects = grouped_objects.get(project, [])
        if not project_objects:
            print(f"SKIPPED\t{project}\tobjects disappeared before apply")
            continue
        current_classification = classify_project(project, project_objects, active_projects)
        if current_classification.status != "collectable":
            print(f"REFUSED\t{project}\t{current_classification.status}: {current_classification.reason}")
            continue
        execute_collection(project_objects)


def parse_args(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="remove collectable objects; default is dry-run")
    parser.add_argument(
        "--active-project",
        action="append",
        default=[],
        metavar="CIVIBUS_PROJECT",
        help="Compose project that must never be collected; repeat for each live lane",
    )
    parsed = parser.parse_args(arguments)
    invalid_projects = [name for name in parsed.active_project if not name.startswith(CIVIBUS_PROJECT_PREFIX)]
    if invalid_projects:
        parser.error(f"active projects must start with {CIVIBUS_PROJECT_PREFIX}: {', '.join(invalid_projects)}")
    if parsed.apply and not parsed.active_project:
        parser.error("--apply requires at least one --active-project safety declaration")
    return parsed


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = parse_args(arguments if arguments is not None else sys.argv[1:])
    active_projects = frozenset(parsed.active_project)
    try:
        objects = discover_docker_objects()
        classifications = classify_all(objects, active_projects)
        mode = "apply" if parsed.apply else "dry-run"
        mode_detail = "eligible Docker objects will be removed" if parsed.apply else "no Docker objects will be removed"
        print(f"MODE\t{mode}\t{mode_detail}")
        report(objects, classifications)
        if parsed.apply:
            collectable_projects = [
                project for project, classification in classifications.items() if classification.status == "collectable"
            ]
            apply_collectable_projects(active_projects, collectable_projects)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
