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

ZSH_WORD_SPLITTING_DIRTY = f"""# Word splitting dirty lane

## Stages

{ANTI_STOP_PARAGRAPH}

```bash
list="one two three four"
for spec in $list; do
  set -- $spec
  printf '%s\\n' "$1"
done
```
"""

PIPELINE_MASKING_DIRTY_TEMPLATE = """# Pipeline dirty lane

## Stages

{anti_stop}

```bash
set -e
{command}
```
"""

PIPELINE_TEE_CLEAN = f"""# Tee logging clean lane

## Stages

{ANTI_STOP_PARAGRAPH}

```bash
set -e
cmd --produce-report | tee log
```
"""

PIPELINE_GREP_ASSERTION_CLEAN = f"""# Grep assertion clean lane

## Stages

{ANTI_STOP_PARAGRAPH}

```bash
set -e
cmd --print-status | grep -q expected
```
"""

PIPELINE_PIPEFAIL_CLEAN = f"""# Pipefail clean lane

## Stages

{ANTI_STOP_PARAGRAPH}

```bash
set -e
set -o pipefail
cmd --produce-report | head -n 1
```
"""

PIPELINE_STATUS_CLEAN = f"""# Pipeline status clean lane

## Stages

{ANTI_STOP_PARAGRAPH}

```bash
set -e
cmd --produce-report | tail -n 1
producer_status=${{PIPESTATUS[0]}}
test "$producer_status" -eq 0
```
"""

PREAMBLE_REPEATED_WITH_DIFFERENT_WRAPPING = f"""# Wrapped preamble lane

## PURPOSE

Out of scope for the lane: do NOT edit `api/`, `core/`,
or `domains/` while fixing the checker.

{ANTI_STOP_PARAGRAPH}

## Stages

{ANTI_STOP_PARAGRAPH}

Out of scope for the lane: do NOT edit `api/`,
`core/`, or `domains/` while fixing the checker.
"""

PREAMBLE_REAL_LOSS = f"""# Lost preamble lane

## PURPOSE

Out of scope for the lane: do NOT edit `api/`.

{ANTI_STOP_PARAGRAPH}

## Stages

{ANTI_STOP_PARAGRAPH}

Run the checker tests.
"""

PREAMBLE_PARTIAL_REPEAT_LOSS = f"""# Partial wrapped preamble lane

## PURPOSE

Out of scope for the lane: do NOT edit `api/`, `core/`,
or `domains/` while fixing the checker.

{ANTI_STOP_PARAGRAPH}

## Stages

{ANTI_STOP_PARAGRAPH}

Out of scope for the lane: do NOT edit `api/`, `core/`,
Run the checker tests.
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
def test_zsh_word_splitting_fixture_reports_concrete_shell_hazard() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(ZSH_WORD_SPLITTING_DIRTY) == ["zsh-word-splitting"]


def _pipeline_masking_fixture(command: str) -> str:
    return PIPELINE_MASKING_DIRTY_TEMPLATE.format(anti_stop=ANTI_STOP_PARAGRAPH, command=command)


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_grep_ended_pipeline_fixture_reports_concrete_shell_hazard() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(_pipeline_masking_fixture("cmd --produce-report | grep expected")) == [
        "pipeline-masked-by-grep"
    ]


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_head_ended_pipeline_fixture_reports_concrete_shell_hazard() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(_pipeline_masking_fixture("cmd --produce-report | head -n 1")) == [
        "pipeline-masked-by-head"
    ]


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_tail_ended_pipeline_fixture_reports_concrete_shell_hazard() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(_pipeline_masking_fixture("cmd --produce-report | tail -n 1")) == [
        "pipeline-masked-by-tail"
    ]


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_tee_logging_pipeline_reports_no_shell_findings() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(PIPELINE_TEE_CLEAN) == []


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_grep_q_assertion_pipeline_reports_no_shell_findings() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(PIPELINE_GREP_ASSERTION_CLEAN) == []


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_pipefail_pipeline_reports_no_shell_findings() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(PIPELINE_PIPEFAIL_CLEAN) == []


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_pipestatus_pipeline_reports_no_shell_findings() -> None:
    checker = _load_checker()

    assert checker.shell_hazards(PIPELINE_STATUS_CLEAN) == []


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_repeated_preamble_constraint_with_different_wrapping_is_not_a_loss() -> None:
    checker = _load_checker()

    assert checker.direct_mode_losses(PREAMBLE_REPEATED_WITH_DIFFERENT_WRAPPING) == (False, False, [])


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_missing_repeated_preamble_constraint_still_reports_loss() -> None:
    checker = _load_checker()

    assert checker.direct_mode_losses(PREAMBLE_REAL_LOSS) == (False, False, ["## PURPOSE"])


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_partially_repeated_wrapped_preamble_constraint_still_reports_loss() -> None:
    checker = _load_checker()

    assert checker.direct_mode_losses(PREAMBLE_PARTIAL_REPEAT_LOSS) == (False, False, ["## PURPOSE"])


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_newly_introduced_hazard_reds_the_ratchet(tmp_path: Path) -> None:
    checker = _load_checker()
    path = tmp_path / "chats" / "icg" / "scratch.md"
    path.parent.mkdir(parents=True)
    path.write_text(DIRTY, encoding="utf-8")

    report = checker.scan_paths([path])
    result = checker.evaluate_ratchet(report, changed_paths={path}, baseline_findings={})

    assert result.exit_code == 1
    assert result.changed_files_denominator == 1
    assert result.worsened_files == {
        path.as_posix(): [
            "anti-stop-outside-slice",
            "db-vacuity",
            "preamble-loss",
        ]
    }


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_modified_grandfathered_file_with_unchanged_findings_stays_green(tmp_path: Path) -> None:
    checker = _load_checker()
    path = tmp_path / "chats" / "icg" / "grandfathered.md"
    path.parent.mkdir(parents=True)
    path.write_text(DIRTY.replace("Run the suite.", "Run the same suite with edited prose."), encoding="utf-8")

    report = checker.scan_paths([path])
    result = checker.evaluate_ratchet(
        report,
        changed_paths={path},
        baseline_findings={path.as_posix(): checker.analyze_text(DIRTY).labels},
    )

    assert result.exit_code == 0
    assert result.changed_files_denominator == 1
    assert result.worsened_files == {}


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_zero_changed_files_path_still_checks_the_baseline(tmp_path: Path) -> None:
    checker = _load_checker()
    path = tmp_path / "clean.md"
    path.write_text(CLEAN, encoding="utf-8")

    report = checker.scan_paths([path])
    result = checker.evaluate_ratchet(report, changed_paths=set(), baseline_counts=report.counts)

    assert result.exit_code == 0
    assert result.changed_files_denominator == 0
    assert result.vacuous is True
    assert result.baseline_regressions == {}


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_direct_mode_baselines_cover_current_real_corpus() -> None:
    checker = _load_checker()
    report = checker.scan_paths(sorted(checker.CHECKLIST_DIR.glob("*.md")))

    assert {label: checker.BASELINE_COUNTS[label] for label in ("anti-stop-outside-slice", "preamble-loss")} == {
        "anti-stop-outside-slice": report.counts["anti-stop-outside-slice"],
        "preamble-loss": report.counts["preamble-loss"],
    }


@pytest.mark.unit
@pytest.mark.dev_repo_only(
    private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
    owner="Lane-authoring hazard checker corpus",
)
def test_changed_checklist_paths_include_untracked_scratch_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _load_checker()

    def fake_git_stdout(*args: str) -> str:
        if args[:3] == ("merge-base", "HEAD", "origin/main"):
            return "base-sha"
        if args[:2] == ("diff", "--name-only"):
            return "chats/icg/tracked.md"
        if args[:3] == ("ls-files", "--others", "--exclude-standard"):
            return "chats/icg/untracked.md"
        return ""

    monkeypatch.setattr(checker, "_git_stdout", fake_git_stdout)

    assert checker.changed_checklist_paths() == {
        checker.REPO_ROOT / "chats/icg/tracked.md",
        checker.REPO_ROOT / "chats/icg/untracked.md",
    }

    monkeypatch.setattr(checker, "_git_stdout", lambda *_args: "")

    with pytest.raises(RuntimeError, match="merge-base HEAD origin/main failed"):
        checker.changed_checklist_paths()


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
def test_checker_runs_over_the_real_corpus_with_ratchet_semantics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    checker = _load_checker()
    exit_code = checker.main()
    out = capsys.readouterr().out

    assert exit_code == 0
    scanned = int(out.split("files scanned:")[1].split("\n")[0])
    assert scanned > 50, f"corpus too small to be a real scan: {scanned}"
    for label in (
        "db vacuity hits",
        "direct mode anti-stop loss hits",
        "direct mode preamble loss hits",
        "baseline regressions",
        "enforced changed files",
    ):
        assert f"{label}:" in out
