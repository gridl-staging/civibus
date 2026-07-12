"""
Stub summary for MAR18_cross_domain_er_and_property_graph/civibus_dev/core/docker_compose.py.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

DB_SERVICE_NAME = "db"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def workspace_slug(repo_root: Path | None = None) -> str:
    workspace_name = (repo_root or _REPO_ROOT).parent.name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", workspace_name).strip("_")
    if not slug:
        raise RuntimeError("Unable to derive workspace slug for Compose project name resolution.")
    return slug


def compose_project_name(repo_root: Path | None = None) -> str:
    configured_project_name = os.getenv("COMPOSE_PROJECT_NAME")
    if configured_project_name:
        return configured_project_name
    return f"civibus_{workspace_slug(repo_root)}"


def resolve_compose_service_container(service_name: str, *, repo_root: Path | None = None) -> str | None:
    project_name = compose_project_name(repo_root)
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
            "--filter",
            f"label=com.docker.compose.service={service_name}",
            "--format",
            "{{.Names}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        container_name = line.strip()
        if container_name:
            return container_name
    return None


__all__ = ["DB_SERVICE_NAME", "compose_project_name", "resolve_compose_service_container", "workspace_slug"]
