"""Contract tests for the reserved-integration-port guard on lane databases.

`make test-integration-local` pins `POSTGRES_PORT=5475` and refuses to run when
that port is already bound. Batch orchestrations allocate a distinct port per
lane, but that allocation is prose: on 2026-08-01 a lane database
(`civibus_l13-db-1`) held `127.0.0.1:5475` while its own batch still owed the
DB-backed merged-union gate, so the gate could not execute for any concurrent
worker on the host. The failure surfaced at merge time as "Port 5475 is already
bound by a likely concurrent integration run", which names the symptom and not
the cause.

These tests pin the enforcement: `make db-up` must refuse the reserved port for
every project except the integration-local project that owns it. Deleting the
`reject-reserved-integration-port` prerequisite or its port comparison turns
`test_lane_project_may_not_bind_the_reserved_port` red.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
RESERVED_PORT = "5475"
RESERVED_PROJECT = "civibus_integration_local"
GUARD_TARGET = "reject-reserved-integration-port"


def _run_guard(port: str, project: str) -> subprocess.CompletedProcess[str]:
    """Invoke the guard target alone; it must not need a password or Docker."""
    return subprocess.run(
        ["make", GUARD_TARGET],
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "POSTGRES_PORT": port,
            "COMPOSE_PROJECT_NAME": project,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_lane_project_may_not_bind_the_reserved_port() -> None:
    result = _run_guard(RESERVED_PORT, "civibus_l13")

    assert result.returncode != 0, (
        f"a lane compose project must not be allowed to bind the reserved integration port {RESERVED_PORT}"
    )
    assert f"POSTGRES_PORT={RESERVED_PORT} is reserved" in result.stderr
    assert "civibus_l13" in result.stderr, "the refusal must name the offending project"


def test_integration_local_project_may_bind_the_reserved_port() -> None:
    result = _run_guard(RESERVED_PORT, RESERVED_PROJECT)

    assert result.returncode == 0, (
        "test-integration-local owns the reserved port and must not be blocked "
        f"by its own guard; stderr={result.stderr!r}"
    )


def test_lane_project_may_bind_its_allocated_port() -> None:
    result = _run_guard("5523", "civibus_l13")

    assert result.returncode == 0, f"the guard must only reject the reserved port; stderr={result.stderr!r}"


def test_db_up_requires_the_guard_as_a_prerequisite() -> None:
    """The guard is worthless if `db-up` can reach `docker compose` without it."""
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    db_up_lines = [line for line in makefile_text.splitlines() if line.startswith("db-up:")]
    assert len(db_up_lines) == 1, "Makefile must declare exactly one db-up target"
    assert GUARD_TARGET in db_up_lines[0], (
        f"db-up must list {GUARD_TARGET} as a prerequisite so a lane cannot start "
        f"a database on the reserved port; got {db_up_lines[0]!r}"
    )


def test_integration_local_still_pins_the_reserved_port_and_project() -> None:
    """If either pin moves, the guard's exemption silently stops matching."""
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert f"test-integration-local: override POSTGRES_PORT := {RESERVED_PORT}" in makefile_text
    assert f"test-integration-local: override COMPOSE_PROJECT_NAME := {RESERVED_PROJECT}" in makefile_text
