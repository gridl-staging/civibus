"""Contract tests for the parked-jurisdiction pytest quarantine.

Federal-first v1 (PROJECT_OVERVIEW.md) freezes all state/city campaign-finance
pipelines. Their ~2,500 tests are excluded from default collection by a
`collect_ignore` gate in the root `conftest.py` so the dev loop and CI only
pay for tests that guard active code. These tests pin the three behaviors
the gate must keep true; each would fail for a real defect:

1. A default full-tree run collects ZERO tests from per-state/city dirs.
2. CIVIBUS_INCLUDE_PARKED=1 restores collection (escape hatch works, so
   `make test-parked` and post-v1 un-parking remain possible).
3. Shared helpers living DIRECTLY under jurisdictions/states/ (load_utils.py
   and friends) are active federal dependencies — their colocated tests must
   still collect by default (gate is not over-broad).

Note: pytest treats paths passed explicitly on the CLI as initial args that
bypass `collect_ignore`, so `pytest domains/.../states/NC` still works without
the env var. That bypass is intentional pytest behavior, not a gate defect —
these tests therefore assert on default (testpaths-driven) collection only.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Matches file paths inside per-state/city subdirs (parked) but NOT files
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
    # without pinning the exact (churning) parked-suite size.
    assert parked_count > 100, f"escape hatch restored only {parked_count} parked tests"


def test_active_shared_helper_tests_still_collect_by_default() -> None:
    assert _ACTIVE_SHARED_HELPER_NODE in _default_collection(include_parked=False), (
        "quarantine over-reached: colocated tests for ACTIVE shared helpers "
        "(jurisdictions/states/load_utils.py) vanished from default collection"
    )
