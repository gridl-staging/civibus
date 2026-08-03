"""Contract tests for database-port guards on lane projects.

`make test-integration-local` pins `POSTGRES_PORT=5475` and refuses to run when
that port is already bound. Batch orchestrations allocate a distinct port per
lane, but that allocation is prose: on 2026-08-01 a lane database
(`civibus_l13-db-1`) held `127.0.0.1:5475` while its own batch still owed the
DB-backed merged-union gate, so the gate could not execute for any concurrent
worker on the host. The failure surfaced at merge time as "Port 5475 is already
bound by a likely concurrent integration run", which names the symptom and not
the cause.

The shared default `POSTGRES_PORT=5433` is also unsafe for a lane because it is
not an allocation. These tests pin both enforcement rules: `make db-up` must
refuse a lane that uses the reserved integration port or did not receive a port
through the environment or command line. The integration-local project remains
exempt because its target owns and pins that runtime.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
RESERVED_PORT = "5475"
RESERVED_PROJECT = "civibus_integration_local"
RESERVED_PORT_GUARD_TARGET = "reject-reserved-integration-port"
UNALLOCATED_PORT_GUARD_TARGET = "reject-unallocated-lane-port"


def _run_guard(
    target: str,
    project: str,
    port: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the guard target alone; it must not need a password or Docker."""
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "COMPOSE_PROJECT_NAME": project,
    }
    if port is not None:
        environment["POSTGRES_PORT"] = port

    return subprocess.run(
        ["make", target],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_lane_project_may_not_bind_the_reserved_port() -> None:
    result = _run_guard(RESERVED_PORT_GUARD_TARGET, "civibus_l13", RESERVED_PORT)

    assert result.returncode != 0, (
        f"a lane compose project must not be allowed to bind the reserved integration port {RESERVED_PORT}"
    )
    assert f"POSTGRES_PORT={RESERVED_PORT} is reserved" in result.stderr
    assert "civibus_l13" in result.stderr, "the refusal must name the offending project"

    leading_zero_result = _run_guard(RESERVED_PORT_GUARD_TARGET, "civibus_l13", f"0{RESERVED_PORT}")

    assert leading_zero_result.returncode != 0, (
        "Compose normalizes a leading-zero port to the reserved integer, so the guard must reject it"
    )
    assert "must be a canonical decimal port" in leading_zero_result.stderr

    for invalid_port in ("0", "65536", "100000"):
        invalid_result = _run_guard(RESERVED_PORT_GUARD_TARGET, "civibus_l13", invalid_port)

        assert invalid_result.returncode != 0, f"invalid port {invalid_port} must fail closed"
        assert "must be a canonical decimal port" in invalid_result.stderr


def test_integration_local_project_may_bind_the_reserved_port() -> None:
    result = _run_guard(RESERVED_PORT_GUARD_TARGET, RESERVED_PROJECT, RESERVED_PORT)

    assert result.returncode == 0, (
        "test-integration-local owns the reserved port and must not be blocked "
        f"by its own guard; stderr={result.stderr!r}"
    )


def test_lane_project_may_bind_its_allocated_port(tmp_path: Path) -> None:
    result = _run_guard(RESERVED_PORT_GUARD_TARGET, "civibus_l13", "5523")

    assert result.returncode == 0, f"the guard must only reject the reserved port; stderr={result.stderr!r}"

    marker_path = tmp_path / "port_value_was_executed"
    malicious_port = f'5523"; touch {marker_path}; echo "'
    malicious_result = _run_guard(RESERVED_PORT_GUARD_TARGET, "civibus_l13", malicious_port)

    assert not marker_path.exists(), "the guard must treat POSTGRES_PORT as data, not shell source"
    assert malicious_result.returncode != 0
    assert "must be a canonical decimal port" in malicious_result.stderr

    make_marker_path = tmp_path / "make_function_was_executed"
    make_syntax_result = _run_guard(
        RESERVED_PORT_GUARD_TARGET,
        "civibus_l13",
        f"$(shell touch {make_marker_path})",
    )

    assert not make_marker_path.exists(), "the guard must not recursively expand caller-supplied Make syntax"
    assert make_syntax_result.returncode != 0


def test_lane_project_must_supply_an_allocated_port() -> None:
    for port in (None, ""):
        result = _run_guard(UNALLOCATED_PORT_GUARD_TARGET, "civibus_c3", port)

        assert result.returncode != 0, "a lane compose project must receive a non-empty allocated port"
        assert "A non-empty POSTGRES_PORT must be supplied by environment or command line" in result.stderr
        assert "civibus_c3" in result.stderr, "the refusal must name the project missing a port allocation"


def test_lane_project_may_use_its_explicitly_allocated_port() -> None:
    result = _run_guard(UNALLOCATED_PORT_GUARD_TARGET, "civibus_c3", "5543")

    assert result.returncode == 0, f"an explicitly allocated lane port must be allowed; stderr={result.stderr!r}"


def test_integration_local_project_may_use_its_pinned_default_port() -> None:
    unpinned_result = _run_guard(UNALLOCATED_PORT_GUARD_TARGET, RESERVED_PROJECT)
    pinned_result = _run_guard(UNALLOCATED_PORT_GUARD_TARGET, RESERVED_PROJECT, RESERVED_PORT)

    assert unpinned_result.returncode != 0, "the project name alone must not bypass allocation enforcement"
    assert pinned_result.returncode == 0, (
        f"test-integration-local exports its target-pinned port to db-up; stderr={pinned_result.stderr!r}"
    )


def test_db_up_requires_the_guard_as_a_prerequisite() -> None:
    """The guards are worthless if `db-up` can reach Docker without them."""
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    db_up_lines = [line for line in makefile_text.splitlines() if line.startswith("db-up:")]
    assert len(db_up_lines) == 1, "Makefile must declare exactly one db-up target"
    for guard_target in (RESERVED_PORT_GUARD_TARGET, UNALLOCATED_PORT_GUARD_TARGET):
        assert guard_target in db_up_lines[0], (
            f"db-up must list {guard_target} as a prerequisite so a lane cannot start "
            f"a database on an invalid port; got {db_up_lines[0]!r}"
        )


def test_integration_local_still_pins_the_reserved_port_and_project() -> None:
    """If either pin moves, the guard's exemption silently stops matching."""
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert f"test-integration-local: override POSTGRES_PORT := {RESERVED_PORT}" in makefile_text
    assert f"test-integration-local: override COMPOSE_PROJECT_NAME := {RESERVED_PROJECT}" in makefile_text
