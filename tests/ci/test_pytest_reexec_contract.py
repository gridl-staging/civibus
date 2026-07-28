"""Contracts for bootstrapping pytest under the project interpreter."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

import conftest as root_conftest


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CONFTEST_PATH = REPO_ROOT / "conftest.py"
THIRD_PARTY_IMPORT_ROOTS = frozenset({"psycopg", "pydantic", "pytest"})
LEGACY_SYSTEM_PYTHON_PATH = Path("/usr/bin/python3")
EXPECTED_DWO_NODE_IDS = (
    "domains/civics/tests/test_dwo_count_gates.py::test_full_csv_candidacy_count_gate",
    "domains/civics/tests/test_dwo_count_gates.py::test_full_csv_idempotency_rerun_zero_new_candidacies",
    "domains/civics/tests/test_dwo_count_gates.py::test_full_csv_contest_and_office_determinism",
)


def _legacy_system_python() -> Path:
    if not LEGACY_SYSTEM_PYTHON_PATH.exists():
        pytest.skip("system Python is unavailable for the pre-3.12 re-exec contract")

    version_result = subprocess.run(
        [
            LEGACY_SYSTEM_PYTHON_PATH,
            "-c",
            "import sys; print(sys.version_info.major, sys.version_info.minor)",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    version = tuple(int(part) for part in version_result.stdout.split())
    if version >= (3, 12):
        pytest.skip("system Python is not old enough to exercise the re-exec path")
    return LEGACY_SYSTEM_PYTHON_PATH


def test_project_python_bootstrap_precedes_third_party_imports() -> None:
    module = ast.parse(ROOT_CONFTEST_PATH.read_text(encoding="utf-8"))

    reexec_call_line = next(
        node.lineno
        for node in module.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_run_pytest_under_project_python_and_exit_if_needed"
    )
    third_party_import_lines = [
        node.lineno
        for node in module.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any(alias.name.split(".", maxsplit=1)[0] in THIRD_PARTY_IMPORT_ROOTS for alias in node.names)
    ]

    assert third_party_import_lines
    assert reexec_call_line < min(third_party_import_lines)


def test_project_python_reexec_preserves_collection_output_and_status() -> None:
    environment = os.environ.copy()
    environment.pop("CIVIBUS_PYTEST_REEXEC", None)

    result = subprocess.run(
        [
            _legacy_system_python(),
            "-m",
            "pytest",
            "domains/civics/tests/test_dwo_count_gates.py",
            "--collect-only",
            "-q",
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    collected_node_ids = tuple(line for line in result.stdout.splitlines() if "::" in line)
    assert collected_node_ids == EXPECTED_DWO_NODE_IDS
    assert "3 tests collected" in result.stdout


def test_bootstrap_parent_finishes_capture_and_propagates_child_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_manager = root_conftest.CaptureManager("no")
    stop_calls: list[None] = []
    exit_statuses: list[int] = []
    monkeypatch.setattr(
        capture_manager,
        "stop_global_capturing",
        lambda: stop_calls.append(None),
    )
    monkeypatch.setattr(root_conftest.gc, "get_objects", lambda: [capture_manager])
    monkeypatch.setattr(root_conftest.os, "_exit", exit_statuses.append)

    root_conftest._finish_bootstrap_parent(
        subprocess.CompletedProcess(args=["pytest"], returncode=7),
    )

    assert stop_calls == [None]
    assert exit_statuses == [7]
