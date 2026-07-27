"""Contract tests for the shadow-mode lane-authoring hazard checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / "scripts" / "lane_authoring_hazard_checker.py"


def _load_checker() -> ModuleType:
    """Load the private checker lazily so public collection can classify tests."""
    assert CHECKER_PATH.is_file(), "lane-authoring checker is intentionally absent from public mirrors"
    spec = importlib.util.spec_from_file_location("lane_authoring_hazard_checker", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANTI_STOP_PARAGRAPH = (
    "> `blocked/inconclusive` is a failure mode, not an acceptable outcome. before writing it, produce a gap spec."
)

CLEAN = f"""# Clean lane

## PURPOSE

Background prose with no constraints in it.

## Stages

### Do the thing

{ANTI_STOP_PARAGRAPH}

Out of scope: editing anything else. Do NOT touch `web/`.

```bash
CIVIBUS_REQUIRE_DB=1 make test
```

## Merge notes

- Target branch: `main`.
"""

DIRTY = f"""# Dirty lane

## PURPOSE

Out of scope for the whole lane: do NOT edit `conftest.py`.

{ANTI_STOP_PARAGRAPH}

## Stages

### Do the thing

Run the suite.

```bash
make test
```
"""


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_clean_fixture_reports_no_findings() -> None:
    checker = _load_checker()
    strict, refined = checker.db_vacuity(CLEAN)
    outside, absent, offenders = checker.direct_mode_losses(CLEAN)

    assert (strict, refined) == (False, False)
    assert outside is False
    assert absent is False
    assert offenders == []


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_dirty_fixture_reports_exactly_the_three_expected_findings() -> None:
    checker = _load_checker()
    strict, refined = checker.db_vacuity(DIRTY)
    outside, absent, offenders = checker.direct_mode_losses(DIRTY)

    assert (strict, refined) == (True, True), "bare `make test` with no CIVIBUS_REQUIRE_DB=1"
    assert outside is True, "anti-stop paragraph sits above `## Stages` and is sliced away"
    assert absent is False, "it is present in the file, just in the wrong place"
    assert offenders == ["## PURPOSE"], "the out-of-scope list is discarded by direct mode"


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_prose_mentioning_the_env_var_does_not_clear_a_file() -> None:
    checker = _load_checker()
    # The whole point: a lane that merely discusses the hazard must not exempt
    # itself, or the receipt's denominator hides exactly the files at risk.
    prose = DIRTY.replace("Run the suite.", "Note that CIVIBUS_REQUIRE_DB=1 avoids a vacuous green.")

    assert checker.db_vacuity(prose) == (True, True)


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_fenced_assignment_does_clear_a_file() -> None:
    checker = _load_checker()
    fenced = DIRTY.replace("make test", "CIVIBUS_REQUIRE_DB=1 make test")

    assert checker.db_vacuity(fenced) == (False, False)


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_named_test_file_targets_are_refined_out_but_still_counted_strictly() -> None:
    checker = _load_checker()
    named = DIRTY.replace("make test", "pytest domains/campaign_finance/ingest/test_bulk_cli.py -q")
    strict, refined = checker.db_vacuity(named)

    assert strict is True, "the path is under a DB-backed tree"
    assert refined is False, "but an explicitly named unit-test file does not need Postgres"


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_directory_level_pytest_target_is_a_refined_hit() -> None:
    checker = _load_checker()
    directory = DIRTY.replace("make test", "pytest domains/ -q")

    assert checker.db_vacuity(directory) == (True, True)


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_file_without_a_stages_heading_is_not_a_direct_mode_hit() -> None:
    checker = _load_checker()
    assert checker.stages_slice("# Doc\n\n## Notes\n\nprose\n") is None
    assert checker.direct_mode_losses("# Doc\n\n## Notes\n\nprose\n") == (False, False, [])


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_slice_boundary_matches_direct_mode_semantics() -> None:
    checker = _load_checker()
    sliced = checker.stages_slice("# T\n\n## Stages\n\nkept\n\n## Merge notes\n\ndropped\n")

    assert sliced is not None
    assert "kept" in sliced
    assert "dropped" not in sliced


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_checker_runs_over_the_real_corpus_and_stays_shadow_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = _load_checker()
    exit_code = checker.main()
    out = capsys.readouterr().out

    assert exit_code == 0, "shadow mode must never gate"
    scanned = int(out.split("files scanned:")[1].split("\n")[0])
    assert scanned > 50, f"corpus too small to be a real scan: {scanned}"
    for label in ("db vacuity hits", "direct mode anti-stop loss hits", "direct mode preamble loss hits"):
        assert f"{label}:" in out
