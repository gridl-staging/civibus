from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from tests.ci.public_mirror_contract import (
    DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID,
    MINIMUM_PUBLIC_ELIGIBLE_NODE_TOTAL,
    MINIMUM_PUBLIC_NODE_PREFIX_TOTALS,
    PROJECTED_PUBLIC_CONTRACT_NODE_ID,
    evaluate_public_node_expectations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POST_SYNC_SCRIPT = REPO_ROOT / ".debbie" / "post-sync.sh"
DEBBIE_CONFIG_PATH = REPO_ROOT / ".debbie.toml"
ACCESSIBILITY_SPEC_PATH = REPO_ROOT / "web/tests/smoke/accessibility.spec.ts"
SMOKE_EXECUTION_CONTRACT_PATH = REPO_ROOT / "web/tests/smoke/execution-contract.json"
ACCESSIBILITY_RECEIPT_RELATIVE_PATH = "docs/live-state/2026_07_29_accessibility_baseline.md"
SYNC_GUARD_PATH = REPO_ROOT / ".debbie" / "verify_sync_source.py"
PUBLIC_RUN_SPECIMENS = (
    ".debbie.toml",
    "ROADMAP.md",
    "PROJECT_OVERVIEW.md",
    "docs/reference/keel/",
    "evidence/",
)
PROJECTED_PYTEST_TIMEOUT_SECONDS = 600


def _load_guard_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("debbie_verify_sync_source", SYNC_GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


debbie_selected_paths = _load_guard_module().debbie_selected_paths


@dataclass(frozen=True)
class ProjectedMirror:
    root: Path
    env: dict[str, str]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def project_debbie_public_mirror(tmp_path: Path) -> ProjectedMirror:
    target_root = tmp_path / "public-mirror"
    target_root.mkdir()
    _copy_debbie_projection(target_root)
    _initialize_projection_git_checkout(target_root)
    matt_repo = _write_fake_matt_repo(tmp_path / "gridl" / "mike_dev")

    env = os.environ.copy()
    env.pop("UV_FROZEN", None)
    env["DEBBIE_TARGET_ROOT"] = str(target_root)
    env["MATT_REPO_ROOT"] = str(matt_repo)
    subprocess.run(["bash", str(POST_SYNC_SCRIPT)], cwd=REPO_ROOT, check=True, env=env)
    return ProjectedMirror(root=target_root, env=env)


def _copy_debbie_projection(target_root: Path) -> None:
    for relative_path in debbie_selected_paths(REPO_ROOT, DEBBIE_CONFIG_PATH):
        source_path = REPO_ROOT / relative_path
        if source_path.exists():
            _copy_path(source_path, target_root / relative_path)


@pytest.mark.dev_repo_only(
    private_asset="private Beads ledger (.beads/), frozen ROADMAP.md, and BEADS_QA_TRANSITION.md",
    owner="Debbie projection contract",
)
def test_debbie_projection_excludes_private_ledger_and_planning_docs_from_physical_tree(tmp_path: Path) -> None:
    target_root = tmp_path / "public-mirror"
    target_root.mkdir()

    _copy_debbie_projection(target_root)

    assert not (target_root / ".beads").exists(), "Debbie projection leaked private path .beads/"
    assert not (target_root / "ROADMAP.md").exists(), "Debbie projection leaked private path ROADMAP.md"
    assert not (target_root / "BEADS_QA_TRANSITION.md").exists(), (
        "Debbie projection leaked private path BEADS_QA_TRANSITION.md"
    )


@pytest.mark.dev_repo_only(private_asset=".debbie.toml", owner="Debbie projection contract")
def test_nightly_live_accessibility_receipt_is_projected(tmp_path: Path) -> None:
    """Every private input read by a mirrored live journey must be projected."""
    debbie_payload = tomllib.loads(DEBBIE_CONFIG_PATH.read_text(encoding="utf-8"))
    accessibility_spec = ACCESSIBILITY_SPEC_PATH.read_text(encoding="utf-8")
    execution_contract = json.loads(SMOKE_EXECUTION_CONTRACT_PATH.read_text(encoding="utf-8"))["specs"]
    target_root = tmp_path / "public-mirror"
    target_root.mkdir()

    assert ACCESSIBILITY_RECEIPT_RELATIVE_PATH in accessibility_spec
    assert "live" in execution_contract["accessibility.spec.ts"]["modes"]
    assert ACCESSIBILITY_RECEIPT_RELATIVE_PATH in debbie_payload["sync"]["files"]
    _copy_debbie_projection(target_root)
    assert (target_root / ACCESSIBILITY_RECEIPT_RELATIVE_PATH).read_bytes() == (
        REPO_ROOT / ACCESSIBILITY_RECEIPT_RELATIVE_PATH
    ).read_bytes()


@pytest.mark.dev_repo_only(private_asset=".debbie.toml", owner="Debbie projection contract")
def test_debbie_projection_excludes_sveltekit_generated_output() -> None:
    selected_paths = debbie_selected_paths(
        REPO_ROOT,
        DEBBIE_CONFIG_PATH,
        (
            Path("web/src/routes/version.json/+server.ts"),
            Path("web/.svelte-kit/output/server/app.js"),
            Path("web/.svelte-kit/types/src/routes/proxy+page.server.ts"),
        ),
    )

    assert Path("web/src/routes/version.json/+server.ts") in selected_paths
    assert Path("web/.svelte-kit/output/server/app.js") not in selected_paths
    assert Path("web/.svelte-kit/types/src/routes/proxy+page.server.ts") not in selected_paths


def _copy_project_toolchain(target_root: Path) -> None:
    for relative_path in ("pyproject.toml", "uv.lock"):
        _copy_path(REPO_ROOT / relative_path, target_root / relative_path)
    for package_dir in ("api", "core", "domains"):
        (target_root / package_dir).mkdir(exist_ok=True)


def _copy_path(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def _initialize_projection_git_checkout(target_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=target_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=target_root, check=True)
    subprocess.run(["git", "config", "user.name", "CI Fixture"], cwd=target_root, check=True)
    (target_root / ".gitkeep").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], cwd=target_root, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=target_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=target_root, check=True)
    subprocess.run(["git", "commit", "-m", "projection"], cwd=target_root, check=True, capture_output=True, text=True)


def _write_fake_matt_repo(matt_repo: Path) -> Path:
    strip_module = matt_repo / "matt_root" / "matt" / "scrai" / "strip.py"
    strip_module.parent.mkdir(parents=True, exist_ok=True)
    strip_module.write_text("# fixture module marker\n", encoding="utf-8")
    _write_executable(
        matt_repo / ".venv" / "bin" / "python",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            if [[ "${1:-}" == "-m" && "${2:-}" == "matt" && "${3:-}" == "scrai" && "${4:-}" == "strip" ]]; then
              exit 0
            fi
            exit 1
            """
        ),
    )
    return matt_repo


def _pytest_collect_command_from_make_target(project_root: Path, target_name: str) -> list[str]:
    recipe = _make_target_recipe(project_root / "Makefile", target_name)
    pytest_line = next((line for line in recipe if " pytest" in line or line.startswith("pytest ")), None)
    assert pytest_line is not None, f"Makefile:{target_name} must run pytest"
    pytest_parts = shlex.split(pytest_line)
    assert "pytest" in pytest_parts, f"Makefile:{target_name} must expose pytest as a shell token"
    pytest_index = pytest_parts.index("pytest")
    return [
        *pytest_parts[: pytest_index + 1],
        "--collect-only",
        "-q",
        *pytest_parts[pytest_index + 1 :],
    ]


def _make_target_recipe(makefile_path: Path, target_name: str) -> list[str]:
    lines = makefile_path.read_text(encoding="utf-8").splitlines()
    start_index = lines.index(f"{target_name}:")
    recipe: list[str] = []
    for line in lines[start_index + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        if line.startswith("\t"):
            recipe.append(line.strip())
    return recipe


def _run_projected_pytest(projected_mirror: ProjectedMirror, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=projected_mirror.root,
        env=projected_mirror.env,
        capture_output=True,
        text=True,
        # The projected mirror creates its own environment and runs the full
        # public unit selection. Keep a bounded timeout, but leave enough margin
        # for the measured ~160-second quiet-host run under shared-host load.
        timeout=PROJECTED_PYTEST_TIMEOUT_SECONDS,
        check=False,
    )


def _collected_node_ids(stdout: str) -> set[str]:
    return {line for line in stdout.splitlines() if "::" in line and not line.startswith("<")}


def _failed_node_ids(stdout: str) -> set[str]:
    """FAILED and ERROR summary lines both count as projection failures.

    ERROR lines cover fixture-setup and module-collection breakage; leaving
    them out let a red public selection pass the local projected proof on
    2026-08-15. Module-level collection errors yield a bare file path rather
    than a node id — deliberately kept, so they surface as unexpected entries
    in the registered-vs-reproduced comparison instead of vanishing.
    """
    summary_prefixes = ("FAILED ", "ERROR ")
    return {
        line.split(" ", 1)[1].split(" - ", 1)[0] for line in stdout.splitlines() if line.startswith(summary_prefixes)
    }


def test_projected_public_contract_is_selected_only_by_named_target() -> None:
    collect_commands = {
        "default target": _pytest_collect_command_from_make_target(REPO_ROOT, "test"),
        "named target": _pytest_collect_command_from_make_target(REPO_ROOT, "test-projected-public-contract"),
        "direct hot file": [
            "uv",
            "run",
            "--extra",
            "dev",
            "--extra",
            "entity-resolution",
            "pytest",
            "--collect-only",
            "-q",
            "tests/test_debbie_post_sync_hook.py",
        ],
        # Batman merge validation runs its own directory-level selection with
        # only the integration/e2e markers excluded. On 2026-08-15 that pulled
        # the ~10-minute projected contract into a merge gate and tripped the
        # 300-second no-output watchdog, refusing a green canary merge. The
        # exclusion must therefore live at the collection layer, not only in
        # the Makefile's -m expression.
        "bare tests directory": [
            "uv",
            "run",
            "--extra",
            "dev",
            "--extra",
            "entity-resolution",
            "pytest",
            "--collect-only",
            "-q",
            "tests/",
            "-m",
            "not integration and not e2e",
        ],
    }

    collected_nodes_by_selection: dict[str, set[str]] = {}
    for selection, command in collect_commands.items():
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=110,
            check=False,
        )
        assert completed.returncode == 0, f"{selection}\n{_collection_diagnostics(completed)}"
        collected_nodes_by_selection[selection] = _collected_node_ids(completed.stdout)

    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID not in collected_nodes_by_selection["default target"]
    assert collected_nodes_by_selection["named target"] == {PROJECTED_PUBLIC_CONTRACT_NODE_ID}
    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID not in collected_nodes_by_selection["direct hot file"]
    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID not in collected_nodes_by_selection["bare tests directory"]


def test_failed_node_ids_classifies_failed_and_error_summary_lines() -> None:
    """Setup/collection ERRORs are projection failures and must be visible.

    On 2026-08-15 the projected-contract proof passed locally while the
    staging mirror's fast job was red: parked-inclusive collection ERRORed at
    fixture setup, and ERROR summary lines were invisible to this classifier,
    so registered-vs-reproduced comparison never saw them. An error that
    reaches the public selection is exactly as red as a FAILED line.
    """
    stdout = "\n".join(
        [
            "FAILED tests/test_debbie_post_sync_hook.py::test_failed_one - AssertionError: first",
            "ERROR tests/test_debbie_post_sync_hook.py::test_error_one - fixture setup failed",
            "ERROR domains/example/test_module.py - AssertionError: required file missing",
            "    FAILED tests/test_debbie_post_sync_hook.py::test_indented_failed - not a summary line",
            "FAILEDtests/test_debbie_post_sync_hook.py::test_missing_space - not a summary line",
            "ERRORtests/test_debbie_post_sync_hook.py::test_missing_space_error - not a summary line",
            "FAILED tests/test_debbie_post_sync_hook.py::test_failed_two",
        ]
    )

    assert _failed_node_ids(stdout) == {
        "tests/test_debbie_post_sync_hook.py::test_failed_one",
        "tests/test_debbie_post_sync_hook.py::test_error_one",
        "domains/example/test_module.py",
        "tests/test_debbie_post_sync_hook.py::test_failed_two",
    }


def test_fixture_sensitive_nodes_reproduce_as_visible_failures() -> None:
    """Registered nodes that ERROR at fixture setup are observed failures.

    This test used to pin the OPPOSITE: ERROR summary lines were invisible to
    the classifier, and the invisibility was asserted as correct. On
    2026-08-15 that blessed a red staging mirror (parked-inclusive collection
    ERRORed at setup and the projected proof saw nothing), so the contract
    inverted: however a registered node breaks in the projection — FAILED or
    ERROR — the comparison must see it.
    """
    fixture_sensitive_nodes = {
        "tests/test_debbie_post_sync_hook.py::test_projected_public_mirror_is_ruff_format_clean",
        "tests/test_debbie_post_sync_hook.py::test_projected_public_mirror_post_sync_is_idempotent",
        "tests/test_debbie_post_sync_hook.py::test_projected_public_mirror_make_lint_passes",
        "tests/test_debbie_post_sync_hook.py::test_projected_public_gate_matches_canonical_public_eligible_nodes",
    }
    expected_failure_nodes = set(DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID)
    assert fixture_sensitive_nodes <= expected_failure_nodes

    stdout = "\n".join(
        f"{'ERROR' if node_id in fixture_sensitive_nodes else 'FAILED'} {node_id} - synthetic specimen"
        for node_id in sorted(expected_failure_nodes)
    )

    observed_failure_nodes = _failed_node_ids(stdout)

    assert observed_failure_nodes == expected_failure_nodes


def _collection_diagnostics(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        [
            "public CI run 30099808029 specimens:",
            *PUBLIC_RUN_SPECIMENS,
            "stdout tail:",
            completed.stdout[-4000:],
            "stderr tail:",
            completed.stderr[-4000:],
        ]
    )


def _run_locked_ruff_format_check(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--locked", "--extra", "dev", "ruff", "format", "--check", "."],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _run_projected_make_lint(projected_mirror: ProjectedMirror) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "lint"],
        cwd=projected_mirror.root,
        env=projected_mirror.env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _ruff_format_diagnostics(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        [
            f"returncode={completed.returncode}",
            "stdout:",
            completed.stdout,
            "stderr:",
            completed.stderr,
        ]
    )


def _command_diagnostics(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        [
            f"returncode={completed.returncode}",
            "stdout:",
            completed.stdout[-4000:],
            "stderr:",
            completed.stderr[-4000:],
        ]
    )


def _public_node_headroom_diagnostic(canonical_nodes: set[str], projected_nodes: set[str]) -> str:
    lines = [
        "public mirror node headroom:",
        (
            f"total canonical={len(canonical_nodes)} projected={len(projected_nodes)} "
            f"floor={MINIMUM_PUBLIC_ELIGIBLE_NODE_TOTAL}"
        ),
    ]
    for prefix, minimum in sorted(MINIMUM_PUBLIC_NODE_PREFIX_TOTALS.items()):
        canonical_count = sum(1 for node_id in canonical_nodes if node_id.startswith(prefix))
        projected_count = sum(1 for node_id in projected_nodes if node_id.startswith(prefix))
        lines.append(f"{prefix} canonical={canonical_count} projected={projected_count} floor={minimum}")
    return "\n".join(lines)


def _tracked_file_bytes(project_root: Path) -> dict[str, bytes]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=project_root,
        capture_output=True,
        check=True,
    )
    return {
        path.decode("utf-8"): (project_root / path.decode("utf-8")).read_bytes()
        for path in completed.stdout.split(b"\0")
        if path
    }


def _tracked_snapshot_diagnostics(before: dict[str, bytes], after: dict[str, bytes]) -> str:
    before_paths = set(before)
    after_paths = set(after)
    changed_paths = sorted(path for path in before_paths & after_paths if before[path] != after[path])
    return "\n".join(
        [
            f"added={sorted(after_paths - before_paths)}",
            f"removed={sorted(before_paths - after_paths)}",
            f"changed={changed_paths}",
        ]
    )


# Scrai strip owns generic scaffold removal. This hook owns the Civibus projected
# final state because that removal changes target files and can leave a dirty
# Ruff formatting diff in the public mirror.
def test_projected_public_mirror_is_ruff_format_clean(tmp_path: Path) -> None:
    projected_mirror = project_debbie_public_mirror(tmp_path)

    completed = _run_locked_ruff_format_check(projected_mirror.root)

    assert completed.returncode == 0, _ruff_format_diagnostics(completed)


def test_post_sync_formats_only_debbie_target_root(tmp_path: Path) -> None:
    target_root = tmp_path / "staging"
    target_root.mkdir()
    _copy_project_toolchain(target_root)
    projected_specimen = target_root / "core" / "specimen.py"
    projected_specimen.parent.mkdir(parents=True, exist_ok=True)
    projected_specimen.write_text("numbers=[1,2,3]\n", encoding="utf-8")

    caller_cwd = tmp_path / "caller-cwd"
    caller_cwd.mkdir()
    outside_sentinel = tmp_path / "outside" / "sentinel.py"
    outside_sentinel.parent.mkdir()
    outside_sentinel.write_text("numbers=[1,2,3]\n", encoding="utf-8")
    original_sentinel_bytes = outside_sentinel.read_bytes()

    env = os.environ.copy()
    env["DEBBIE_TARGET_ROOT"] = str(target_root)
    env["MATT_REPO_ROOT"] = str(_write_fake_matt_repo(tmp_path / "gridl" / "mike_dev"))

    subprocess.run(["bash", str(POST_SYNC_SCRIPT)], cwd=caller_cwd, check=True, env=env)

    assert outside_sentinel.read_bytes() == original_sentinel_bytes
    assert projected_specimen.read_text(encoding="utf-8") == "numbers = [1, 2, 3]\n"


def test_projected_public_mirror_post_sync_is_idempotent(tmp_path: Path) -> None:
    projected_mirror = project_debbie_public_mirror(tmp_path)
    first_snapshot = _tracked_file_bytes(projected_mirror.root)
    first_format_check = _run_locked_ruff_format_check(projected_mirror.root)
    assert first_format_check.returncode == 0, _ruff_format_diagnostics(first_format_check)

    subprocess.run(
        ["bash", str(POST_SYNC_SCRIPT)],
        cwd=tmp_path,
        env=projected_mirror.env,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    second_format_check = _run_locked_ruff_format_check(projected_mirror.root)
    second_snapshot = _tracked_file_bytes(projected_mirror.root)

    assert second_format_check.returncode == 0, _ruff_format_diagnostics(second_format_check)
    assert second_snapshot == first_snapshot, _tracked_snapshot_diagnostics(first_snapshot, second_snapshot)


def test_projected_public_mirror_make_lint_passes(tmp_path: Path) -> None:
    projected_mirror = project_debbie_public_mirror(tmp_path)

    completed = _run_projected_make_lint(projected_mirror)
    output = f"{completed.stdout}\n{completed.stderr}"

    assert completed.returncode == 0, _command_diagnostics(completed)
    assert "check-retired-symbols" in output
    assert "uv run --extra dev ruff check ." in output
    assert "uv run --extra dev ruff format --check ." in output


def test_post_sync_removes_todo_scaffolds_when_strip_is_noop(tmp_path: Path) -> None:
    target_root = tmp_path / "staging"
    target_root.mkdir()
    _copy_project_toolchain(target_root)

    python_file = target_root / "core" / "example.py"
    shell_file = target_root / "infra" / "env_lib.sh"
    python_file.parent.mkdir(parents=True, exist_ok=True)
    shell_file.parent.mkdir(parents=True, exist_ok=True)

    fake_bin = tmp_path / "fake-bin"
    _write_executable(
        fake_bin / "matt",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            if [[ "${1:-}" == "scrai" && "${2:-}" == "strip" && "${3:-}" == "--help" ]]; then
              exit 0
            fi
            if [[ "${1:-}" == "scrai" && "${2:-}" == "strip" ]]; then
              exit 0
            fi
            exit 1
            """
        ),
    )

    env = os.environ.copy()
    env["DEBBIE_TARGET_ROOT"] = str(target_root)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env.pop("MATT_REPO_ROOT", None)

    subprocess.run(["bash", str(POST_SYNC_SCRIPT)], check=True, env=env)


def test_post_sync_uses_repo_virtualenv_python_when_python3_fails(tmp_path: Path) -> None:
    target_root = tmp_path / "staging"
    target_root.mkdir()
    _copy_project_toolchain(target_root)

    python_file = target_root / "core" / "example.py"
    python_file.parent.mkdir(parents=True, exist_ok=True)

    venv_log = tmp_path / "venv-python.log"
    unsafe_matt_repo = _write_fake_matt_repo(tmp_path / "not-trusted" / "mike_dev")
    _write_executable(
        unsafe_matt_repo / ".venv" / "bin" / "python",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            printf '%s\n' "$*" >> "${VENV_PYTHON_LOG:?}"
            exit 0
            """
        ),
    )
    matt_repo = _write_fake_matt_repo(tmp_path / "gridl" / "mike_dev")
    _write_executable(
        matt_repo / ".venv" / "bin" / "python",
        textwrap.dedent(
            """\
            #!/bin/bash
            set -euo pipefail
            if [[ "${1:-}" == "-m" && "${2:-}" == "matt" && "${3:-}" == "scrai" && "${4:-}" == "strip" ]]; then
              printf '%s\n' "$*" >> "${VENV_PYTHON_LOG:?}"
              exit 0
            fi
            exit 1
            """
        ),
    )

    fake_bin = tmp_path / "fake-bin"
    _write_executable(fake_bin / "python3", "#!/bin/bash\nexit 1\n")
    _write_executable(fake_bin / "matt", "#!/bin/bash\nexit 1\n")

    env = os.environ.copy()
    env["DEBBIE_TARGET_ROOT"] = str(target_root)
    env["MATT_REPO_ROOT"] = str(unsafe_matt_repo)
    env["VENV_PYTHON_LOG"] = str(venv_log)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    rejected = subprocess.run(
        ["bash", str(POST_SYNC_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert rejected.returncode != 0
    assert "trusted mike_dev checkout" in rejected.stderr
    assert not venv_log.exists()

    env["MATT_REPO_ROOT"] = str(matt_repo)
    subprocess.run(["bash", str(POST_SYNC_SCRIPT)], check=True, env=env)

    assert venv_log.exists()
    log_text = venv_log.read_text(encoding="utf-8")
    assert "-m matt scrai strip --help" in log_text


@pytest.mark.timeout(900)
def test_projected_public_gate_matches_canonical_public_eligible_nodes(tmp_path: Path) -> None:
    projected_mirror = project_debbie_public_mirror(tmp_path)
    canonical_command = _pytest_collect_command_from_make_target(REPO_ROOT, "test-public")
    projected_command = _pytest_collect_command_from_make_target(projected_mirror.root, "test-public")

    canonical = subprocess.run(
        canonical_command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=110,
        check=False,
    )
    projected = _run_projected_pytest(projected_mirror, projected_command)
    canonical_nodes = _collected_node_ids(canonical.stdout)
    projected_nodes = _collected_node_ids(projected.stdout)

    assert canonical.returncode == 0, _collection_diagnostics(canonical)
    assert projected.returncode == 0, _collection_diagnostics(projected)

    # Both clauses — exact projection fidelity and the non-collapse floors — live
    # in `tests/ci/public_mirror_contract.py` so they are unit-testable without
    # this test's multi-minute double collection. See
    # `tests/ci/test_public_mirror_node_expectations.py`.
    violations = evaluate_public_node_expectations(canonical_nodes, projected_nodes)
    headroom_diagnostic = _public_node_headroom_diagnostic(canonical_nodes, projected_nodes)
    print(headroom_diagnostic)

    assert violations == (), (
        "\n".join(violations) + f"\ncanonical_total={len(canonical_nodes)} projected_total={len(projected_nodes)}"
    )
