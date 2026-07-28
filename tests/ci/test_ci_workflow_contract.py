"""CI workflow contract tests for Makefile-owned Python quality gates."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parents[2]
_repo_root_path = str(REPO_ROOT)
if _repo_root_path in sys.path:
    sys.path.remove(_repo_root_path)
sys.path.insert(0, _repo_root_path)

from tests.ci.public_mirror_contract import (  # noqa: E402
    DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID,
    PublicMirrorCategory,
    PublicMirrorTestClassification,
    validate_public_mirror_classifications,
)  # noqa: E402


CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
WEB_PACKAGE_PATH = REPO_ROOT / "web/package.json"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_NODE_SHA = "820762786026740c76f36085b0efc47a31fe5020"
SETUP_UV_SHA = "0c5e2b8115b80b4c7c5ddf6ffdd634974642d182"


def _read_ci_workflow() -> str:
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_workflow_uses_python_312_with_expected_triggers_and_jobs() -> None:
    workflow_text = _read_ci_workflow()
    lint_job = _job_block(workflow_text, "lint")
    unit_tests_job = _job_block(workflow_text, "unit-tests")
    web_job = _job_block(workflow_text, "web")

    assert "pull_request:\n    branches: [main]" in workflow_text
    assert "push:\n    branches: [main]" in workflow_text
    assert "permissions:\n  contents: read" in workflow_text
    assert "    name: lint" in lint_job.splitlines()
    assert "    name: unit-tests" in unit_tests_job.splitlines()

    for job_block in (lint_job, unit_tests_job, web_job):
        assert f"uses: actions/checkout@{CHECKOUT_SHA}" in job_block
        assert "          fetch-depth: 2" in job_block.splitlines()
        assert "          persist-credentials: false" in job_block.splitlines()

    for python_job in (lint_job, unit_tests_job):
        assert f"uses: astral-sh/setup-uv@{SETUP_UV_SHA}" in python_job
        assert '          python-version: "3.12"' in python_job.splitlines()


def _job_block(workflow_text: str, job_name: str) -> str:
    workflow_lines = workflow_text.splitlines()
    start_index = workflow_lines.index(f"  {job_name}:")
    end_index = len(workflow_lines)
    for index, line in enumerate(workflow_lines[start_index + 1 :], start_index + 1):
        if line.startswith("  ") and not line.startswith("    "):
            end_index = index
            break
    return "\n".join(workflow_lines[start_index:end_index])


def _make_target_block(makefile_text: str, target_name: str) -> str:
    lines = makefile_text.splitlines()
    start_index = lines.index(f"{target_name}:")
    end_index = len(lines)
    for index, line in enumerate(lines[start_index + 1 :], start_index + 1):
        if line and not line.startswith(("\t", " ")):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index])


def test_ci_workflow_commands_use_make_owned_python_gates() -> None:
    workflow_text = _read_ci_workflow()
    lint_job = _job_block(workflow_text, "lint")
    unit_tests_job = _job_block(workflow_text, "unit-tests")

    assert "        run: uv sync --locked --extra dev --extra entity-resolution" in unit_tests_job.splitlines()
    assert "        run: make test-public" in unit_tests_job.splitlines()
    assert "        run: make test" not in unit_tests_job.splitlines()
    assert "        run: uv sync --locked --extra dev" in lint_job.splitlines()
    assert "        run: make lint" in lint_job.splitlines()


def test_ci_workflow_runs_package_owned_web_gates_before_deploy() -> None:
    workflow_text = _read_ci_workflow()
    web_job = _job_block(workflow_text, "web")
    web_package = json.loads(WEB_PACKAGE_PATH.read_text(encoding="utf-8"))

    assert "    name: web" in web_job.splitlines()
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in web_job
    assert "          fetch-depth: 2" in web_job.splitlines()
    assert "          persist-credentials: false" in web_job.splitlines()
    assert web_package["engines"]["node"] == "24.18.0"
    assert f"uses: actions/setup-node@{SETUP_NODE_SHA}" in web_job
    assert "          node-version-file: web/package.json" in web_job.splitlines()
    assert "          cache: npm" in web_job.splitlines()
    assert "          cache-dependency-path: web/package-lock.json" in web_job.splitlines()
    assert web_job.index("uses: actions/setup-node@") < web_job.index("run: npm ci")
    assert web_job.count("        working-directory: web") == 4
    assert "        run: npm ci" in web_job.splitlines()
    assert "        run: npm test" in web_job.splitlines()
    assert "        run: npm run check" in web_job.splitlines()
    assert "        run: npm run build" in web_job.splitlines()
    assert "continue-on-error" not in web_job
    assert "tests/smoke/run-playwright.sh" not in web_job


def test_ci_workflow_does_not_copy_make_owned_python_gate_commands() -> None:
    workflow_text = _read_ci_workflow()
    forbidden_commands = (
        "ruff check tests/ci/",
        "ruff format --check tests/ci/",
        "ruff check .",
        "ruff format --check .",
        'pytest tests/ci/ -m "not dev_repo_only"',
        'pytest -m "not integration and not e2e"',
        'pytest -m "not integration and not e2e and not dev_repo_only"',
        "--cov=api --cov=core --cov=domains",
        "--cov-fail-under=70",
        "continue-on-error",
    )

    for command in forbidden_commands:
        assert command not in workflow_text


def test_makefile_owns_public_python_gate_selector() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert ".PHONY: db-up db-down db-reset test test-public" in makefile_text
    assert (
        'test-public:\n\tuv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e and not dev_repo_only"'
        in makefile_text
    )
    assert (
        'test:\n\tuv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e"' in makefile_text
    )


def test_makefile_lint_runs_lane_authoring_hazard_ratchet() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    lint_block = _make_target_block(makefile_text, "lint")

    assert (
        "\t@if [ -f scripts/lane_authoring_hazard_checker.py ]; "
        "then uv run python scripts/lane_authoring_hazard_checker.py; fi"
    ) in lint_block


def test_public_mirror_classification_contract_is_valid_and_exact() -> None:
    entries = validate_public_mirror_classifications()

    assert len(entries) == len({entry.node_id for entry in entries})
    assert len(entries) == 113
    assert {entry.category for entry in entries} == {PublicMirrorCategory.DEV_REPO_ONLY}
    assert "tests/ci/test_api_dockerfile_contract.py::test_debbie_sync_includes_api_dockerfile_root_inputs" in (
        DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID
    )


def test_dev_repo_only_marker_selection_matches_public_mirror_contract() -> None:
    collected_node_ids = _collect_node_ids("-m", "dev_repo_only")
    expected_node_ids = set(DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID)

    assert collected_node_ids == expected_node_ids, _node_delta_message(
        expected_node_ids=expected_node_ids,
        actual_node_ids=collected_node_ids,
    )


def test_static_dev_repo_only_markers_carry_matching_contract_metadata() -> None:
    marker_uses = _static_dev_repo_only_markers()

    assert marker_uses, "expected at least one explicit dev_repo_only marker use"
    for marker_use in marker_uses:
        entry = DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID[marker_use.node_id]
        assert marker_use.private_asset == entry.private_asset
        assert marker_use.owner == entry.owner


def test_marker_metadata_audit_rejects_bare_marker() -> None:
    with pytest.raises(AssertionError, match="private_asset"):
        _validate_marker_metadata(
            node_id="tests/example.py::test_private",
            private_asset=None,
            owner="owner",
            classifications={
                "tests/example.py::test_private": PublicMirrorTestClassification(
                    node_id="tests/example.py::test_private",
                    category=PublicMirrorCategory.DEV_REPO_ONLY,
                    private_asset="private-doc.md",
                    owner="owner",
                )
            },
        )


def test_marker_metadata_audit_rejects_unknown_marker_use() -> None:
    with pytest.raises(AssertionError, match="not classified"):
        _validate_marker_metadata(
            node_id="tests/example.py::test_private",
            private_asset="private-doc.md",
            owner="owner",
            classifications={},
        )


def test_public_mirror_classification_rejects_stale_duplicate_entry() -> None:
    duplicate = PublicMirrorTestClassification(
        node_id="tests/example.py::test_private",
        category=PublicMirrorCategory.DEV_REPO_ONLY,
        private_asset="private-doc.md",
        owner="owner",
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_public_mirror_classifications((duplicate, duplicate))


def test_marker_metadata_audit_rejects_product_runtime_quarantine() -> None:
    with pytest.raises(AssertionError, match="product_runtime"):
        _validate_marker_metadata(
            node_id="tests/example.py::test_public",
            private_asset="private-doc.md",
            owner="owner",
            classifications={
                "tests/example.py::test_public": PublicMirrorTestClassification(
                    node_id="tests/example.py::test_public",
                    category=PublicMirrorCategory.PRODUCT_RUNTIME,
                )
            },
        )


class _StaticMarkerUse(BaseModel):
    node_id: str
    private_asset: str | None
    owner: str | None


def _collect_node_ids(*pytest_args: str) -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=110,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    return {line for line in completed.stdout.splitlines() if "::" in line and not line.startswith("<")}


def _node_delta_message(*, expected_node_ids: set[str], actual_node_ids: set[str]) -> str:
    missing = sorted(expected_node_ids - actual_node_ids)
    extra = sorted(actual_node_ids - expected_node_ids)
    return f"missing={missing}\nextra={extra}"


def _static_dev_repo_only_markers() -> list[_StaticMarkerUse]:
    marker_uses: list[_StaticMarkerUse] = []
    for path in sorted(
        (
            *REPO_ROOT.glob("tests/**/*.py"),
            *REPO_ROOT.glob("api/**/*.py"),
            *REPO_ROOT.glob("core/**/*.py"),
            *REPO_ROOT.glob("domains/**/*.py"),
        )
    ):
        module = ast.parse(path.read_text(encoding="utf-8"))
        module_marker = _module_dev_repo_only_marker(module)
        test_functions = [
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        if module_marker is not None:
            for function in test_functions:
                marker_uses.append(_marker_use(path=path, function_name=function.name, marker=module_marker))
        for function in test_functions:
            for decorator in function.decorator_list:
                marker = _dev_repo_only_marker_kwargs(decorator)
                if marker is not None:
                    marker_uses.append(_marker_use(path=path, function_name=function.name, marker=marker))
    return marker_uses


def _module_dev_repo_only_marker(module: ast.Module) -> dict[str, str | None] | None:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            continue
        marker = _dev_repo_only_marker_kwargs(node.value)
        if marker is not None:
            return marker
    return None


def _dev_repo_only_marker_kwargs(node: ast.AST) -> dict[str, str | None] | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "dev_repo_only":
        return None
    if not isinstance(node.func.value, ast.Attribute) or node.func.value.attr != "mark":
        return None
    kwargs = {keyword.arg: _constant_string(keyword.value) for keyword in node.keywords}
    return {"private_asset": kwargs.get("private_asset"), "owner": kwargs.get("owner")}


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _marker_use(*, path: Path, function_name: str, marker: dict[str, str | None]) -> _StaticMarkerUse:
    node_id = f"{path.relative_to(REPO_ROOT).as_posix()}::{function_name}"
    _validate_marker_metadata(
        node_id=node_id,
        private_asset=marker["private_asset"],
        owner=marker["owner"],
        classifications=DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID,
    )
    return _StaticMarkerUse(node_id=node_id, private_asset=marker["private_asset"], owner=marker["owner"])


def _validate_marker_metadata(
    *,
    node_id: str,
    private_asset: str | None,
    owner: str | None,
    classifications: dict[str, PublicMirrorTestClassification],
) -> None:
    assert private_asset, f"{node_id} dev_repo_only marker must include private_asset"
    assert owner, f"{node_id} dev_repo_only marker must include owner"
    entry = classifications.get(node_id)
    assert entry is not None, f"{node_id} is marked dev_repo_only but not classified"
    assert entry.category == PublicMirrorCategory.DEV_REPO_ONLY, f"{node_id} classified as product_runtime"
