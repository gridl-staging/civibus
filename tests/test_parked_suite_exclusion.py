"""Contract tests for the regional-suite pytest collection boundary.

The combined state/city campaign-finance suite is excluded from default
collection by a `collect_ignore` gate in the root `conftest.py` so the normal
dev loop and CI stay fast. Active region work runs its explicit region path.
These tests pin the four behaviors the gate must keep true:

1. A default full-tree run collects ZERO tests from per-state/city dirs.
2. CIVIBUS_INCLUDE_PARKED=1 restores collection, preserving the historical
   `make test-parked` full-region signoff command.
3. Shared helpers living DIRECTLY under jurisdictions/states/ (load_utils.py
   and friends) are active federal dependencies — their colocated tests must
   still collect by default (gate is not over-broad).
4. Under the escape hatch, every parked region node id names a test its OWN
   source file defines. A region root without an `__init__.py` makes pytest's
   importlib rootdir walk stop at the region dir, so `GA/scraper/test_cli.py`
   imports as `scraper.test_cli` — the same module name CA already cached —
   and GA/IL then collect CA's function names while their own bodies never
   run. Node ids still PRINT under GA/IL paths, so a contract that only
   asserted "GA node ids exist" would pass while catching nothing; the
   contract here compares collected names against AST-defined names, and the
   companion structural test pins the `__init__.py` markers that prevent the
   aliasing in the first place.

Note: pytest treats paths passed explicitly on the CLI as initial args that
bypass `collect_ignore`, so `pytest domains/.../states/NC` still works without
the env var. That bypass is intentional pytest behavior, not a gate defect —
these tests therefore assert on default (testpaths-driven) collection only.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from domains.campaign_finance.jurisdictions.config_schema import discover_jurisdiction_configs

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Matches file paths inside per-state/city subdirs but NOT files
# directly under jurisdictions/states/ such as test_load_utils.py (active).
_PARKED_PATH_RE = re.compile(r"jurisdictions/(states|cities)/[^/]+/")
_ACTIVE_SHARED_HELPER_NODE = "jurisdictions/states/test_load_utils.py::"


def _parked_node_count(collect_stdout: str) -> int:
    """Count collected node ids whose FILE PATH sits in a parked subdir.

    Match on the path portion before '::' only — parametrized test ids can
    embed slashes inside brackets (e.g. test_x[a/b]), which a whole-line
    regex would misread as parked-directory hits.
    """
    return sum(1 for line in collect_stdout.splitlines() if _PARKED_PATH_RE.search(line.split("::", 1)[0]))


def _ast_defined_test_names(test_file: Path) -> set[str]:
    """Return the runnable test names a file DEFINES, read straight from source.

    Mirrors pytest's default discovery (`python_functions = test*`,
    `python_classes = Test*`; pyproject.toml overrides neither), so the result
    is directly comparable to the name portion of a collected node id. Class
    tests are returned in node-id form (`TestThing::test_case`).

    Reading the source rather than importing it is the whole point: import is
    exactly the step the aliasing defect corrupts, so an import-based oracle
    would report the same wrong answer collection does.
    """
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name.startswith("test"):
                    names.add(f"{node.name}::{member.name}")
    return names


def _parked_names_by_file(collect_stdout: str) -> dict[str, set[str]]:
    """Group collected parked node ids into {repo-relative path: {test names}}.

    Parametrization suffixes are stripped so the set compares against AST
    definitions: WA's test_stage4_regressions.py collects 7 nodes from 4 defs
    and is the live specimen that fails a naive implementation.
    """
    grouped: dict[str, set[str]] = defaultdict(set)
    for line in collect_stdout.splitlines():
        path, sep, name = line.strip().partition("::")
        if not sep or not _PARKED_PATH_RE.search(path):
            continue
        grouped[path].add(name.split("[", 1)[0])
    return dict(grouped)


@lru_cache(maxsize=2)
def _default_collection(include_parked: bool) -> str:
    """Run a full-tree `pytest --collect-only` once per env flavor; return stdout."""
    env = dict(os.environ)
    # Explicitly clear the escape hatch so an operator shell that exports it
    # cannot turn the exclusion assertion into a false positive.
    env.pop("CIVIBUS_INCLUDE_PARKED", None)
    if include_parked:
        env["CIVIBUS_INCLUDE_PARKED"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=110,  # stay under the project-wide 120s pytest timeout
    )
    # Exit 0 = collected fine; anything else means collection itself broke,
    # which would silently invalidate every assertion built on this output.
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    return completed.stdout


def test_parked_state_and_city_tests_excluded_by_default() -> None:
    parked_count = _parked_node_count(_default_collection(include_parked=False))
    assert parked_count == 0, f"parked tests leaked into default collection: {parked_count}"


def test_escape_hatch_restores_parked_collection() -> None:
    parked_count = _parked_node_count(_default_collection(include_parked=True))
    # NC alone carries 400+ tests; a low bar here still catches a broken hatch
    # without pinning the exact (churning) regional-suite size.
    assert parked_count > 100, f"escape hatch restored only {parked_count} parked tests"


def test_active_shared_helper_tests_still_collect_by_default() -> None:
    assert _ACTIVE_SHARED_HELPER_NODE in _default_collection(include_parked=False), (
        "quarantine over-reached: colocated tests for ACTIVE shared helpers "
        "(jurisdictions/states/load_utils.py) vanished from default collection"
    )


def test_parked_node_ids_name_tests_their_own_file_defines() -> None:
    """Every parked node id must name a test its own source file defines.

    This is the module-identity contract. It goes RED whenever a region root
    lacks `__init__.py`: the shadowed region collects the FIRST-cached
    region's function names instead of its own. The state-encoded names in
    the scraper suites (`test_run_ca_refresh_*` vs `test_run_il_refresh_*`)
    are what make that visible as a set difference.
    """
    grouped = _parked_names_by_file(_default_collection(include_parked=True))
    assert grouped, "escape hatch collected no parked node ids at all"

    problems: list[str] = []
    for rel_path in sorted(grouped):
        source = _REPO_ROOT / rel_path
        if not source.is_file():
            problems.append(f"{rel_path}: collected node ids point at a file that does not exist")
            continue
        collected = grouped[rel_path]
        defined = _ast_defined_test_names(source)
        aliased = sorted(collected - defined)
        uncollected = sorted(defined - collected)
        if aliased or uncollected:
            problems.append(
                f"{rel_path}:\n"
                f"    collected but NOT defined here (aliased from another module): {aliased}\n"
                f"    defined here but NOT collected (never runs): {uncollected}"
            )

    assert not problems, (
        "parked region modules collected tests they do not define — pytest's importlib "
        "rootdir walk aliased same-basename modules across regions (missing region-root "
        "__init__.py):\n" + "\n".join(problems)
    )


def test_concrete_jurisdiction_roots_are_python_packages() -> None:
    """Each region root discovered from a config.yaml must be an importable package.

    This is the structural precondition for the identity contract above:
    `--import-mode=importlib` walks up from a test file only while
    `__init__.py` exists, so a region root without one becomes the package
    root and its subpackage names (`scraper.test_cli`) collide across
    regions. Discovery reuses the canonical `discover_jurisdiction_configs`
    owner, which already skips `_template` and never sees shared helper dirs
    such as `jurisdictions/states/` itself (they carry no config.yaml).
    """
    config_paths = discover_jurisdiction_configs(_REPO_ROOT)
    assert config_paths, "discover_jurisdiction_configs found no jurisdiction configs"

    missing = sorted(
        str((config_path.parent / "__init__.py").relative_to(_REPO_ROOT))
        for config_path in config_paths
        if not (config_path.parent / "__init__.py").is_file()
    )
    assert not missing, (
        "concrete jurisdiction roots are missing the __init__.py package marker that "
        "keeps pytest from aliasing same-basename test modules across regions:\n  " + "\n  ".join(missing)
    )
