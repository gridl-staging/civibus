"""Contract for the canonical suite time-budget owner (civibus-y1x).

The budget numbers live in ``tests/ci/pytest_tier_classifier.SUITE_TIME_BUDGETS``
— the same module that owns pytest tier membership — and are enforced as
``timeout-minutes`` on the exact CI step that runs each suite. This module pins
three things:

* the registry stays a closed set: exactly one budget per architecture tier;
* every hard cap sits inside the headroom band, so the enforced timeout can
  neither page on runner variance (flake) nor outlive its ability to catch a
  step-change regression (dead guard);
* every declared cap is actually wired: the named workflow step exists and
  carries ``timeout-minutes`` equal to the declared cap, and the named local
  command exists in its Makefile / package.json owner.

Red-capability: the mutation tests below feed the same checking code paths a
synthetic over-generous cap, a synthetic missing timeout, and a synthetic wrong
timeout, and require each to be flagged. The real assertions run those code
paths against the real registry and workflows.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Callable

import pytest
import yaml
from pydantic import ValidationError

from tests.ci.pytest_tier_classifier import (
    HARD_CAP_MAX_HEADROOM,
    HARD_CAP_MIN_HEADROOM,
    REPO_ROOT,
    SUITE_TIME_BUDGETS,
    MeasuredSuiteBaseline,
    SuiteTier,
    SuiteTimeBudget,
    hard_cap_band_violations,
)


TESTING_DOC_PATH = REPO_ROOT / "docs/reference/testing.md"
WEB_PACKAGE_PATH = REPO_ROOT / "web/package.json"
MAKEFILE_PATH = REPO_ROOT / "Makefile"


def _load_repo_workflow(workflow_path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / workflow_path).read_text(encoding="utf-8"))


def step_timeout_violations(
    budgets: tuple[SuiteTimeBudget, ...],
    load_workflow: Callable[[str], dict] = _load_repo_workflow,
) -> tuple[str, ...]:
    """Return one violation per budget whose CI step lacks its declared cap.

    Takes the workflow loader as a parameter so the mutation tests can prove
    this check red on synthetic workflows through the same code path the real
    assertion uses.
    """
    violations: list[str] = []
    for budget in budgets:
        workflow = load_workflow(budget.ci_workflow)
        job = workflow.get("jobs", {}).get(budget.ci_job)
        if job is None:
            violations.append(f"{budget.suite}: job {budget.ci_job!r} not found in {budget.ci_workflow}")
            continue
        steps_by_name = {step.get("name"): step for step in job.get("steps", []) if isinstance(step, dict)}
        step = steps_by_name.get(budget.ci_step)
        if step is None:
            violations.append(
                f"{budget.suite}: step {budget.ci_step!r} not found in {budget.ci_workflow} job {budget.ci_job!r}"
            )
            continue
        declared_timeout = step.get("timeout-minutes")
        if declared_timeout != budget.hard_cap_minutes:
            violations.append(
                f"{budget.suite}: step {budget.ci_step!r} in {budget.ci_workflow} declares "
                f"timeout-minutes={declared_timeout!r} but the budget owner requires "
                f"{budget.hard_cap_minutes}"
            )
    return tuple(violations)


def _example_budget(**overrides: object) -> SuiteTimeBudget:
    payload: dict[str, object] = {
        "tier": SuiteTier.EDIT_FAST,
        "suite": "synthetic",
        "local_command": "true",
        "local_baseline": MeasuredSuiteBaseline(
            measured_on=date(2026, 8, 21),
            locality="synthetic",
            wall_seconds=5.0,
            test_count=10,
        ),
        "ci_workflow": ".github/workflows/synthetic.yml",
        "ci_job": "synthetic-job",
        "ci_step": "synthetic step",
        "ci_baseline_samples_seconds": (30.0,),
        "ci_baseline_measured_on": date(2026, 8, 21),
        "target_seconds": 60.0,
        "hard_cap_minutes": 2,
    }
    payload.update(overrides)
    return SuiteTimeBudget(**payload)


def test_budget_registry_covers_each_architecture_tier_exactly_once() -> None:
    tiers = [budget.tier for budget in SUITE_TIME_BUDGETS]

    assert len(tiers) == len(set(tiers)), f"duplicate tier budgets: {tiers}"
    assert set(tiers) == set(SuiteTier)


def test_every_hard_cap_sits_inside_the_headroom_band() -> None:
    assert hard_cap_band_violations(SUITE_TIME_BUDGETS) == ()


def test_every_budgeted_ci_step_carries_its_declared_hard_cap() -> None:
    assert step_timeout_violations(SUITE_TIME_BUDGETS) == ()


def test_every_local_command_exists_in_its_owner() -> None:
    """The registry may not name a command that Makefile/package.json no longer owns."""
    package_scripts = json.loads(WEB_PACKAGE_PATH.read_text(encoding="utf-8"))["scripts"]
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    for budget in SUITE_TIME_BUDGETS:
        command = budget.local_command
        if command.startswith("npm --prefix web run "):
            script = command.removeprefix("npm --prefix web run ")
            assert script in package_scripts, f"{budget.suite}: missing web script {script!r}"
        elif command.startswith("npm --prefix web "):
            script = command.removeprefix("npm --prefix web ")
            assert script in package_scripts, f"{budget.suite}: missing web script {script!r}"
        elif command.startswith("make "):
            target = command.removeprefix("make ")
            assert f"\n{target}:" in makefile_text, f"{budget.suite}: missing Makefile target {target!r}"
        else:  # pragma: no cover - a new command shape must extend this closed set
            pytest.fail(f"{budget.suite}: unrecognised local command shape {command!r}")


@pytest.mark.dev_repo_only(private_asset="docs/reference/testing.md", owner="Debbie projection contract")
def test_testing_doc_is_authoritative_and_routes_numbers_to_this_registry() -> None:
    """docs/reference/testing.md owns the policy prose; the numbers live here.

    dev_repo_only because the doc it audits is deliberately outside the public
    mirror's sync whitelist — the 2026-08-21 staging CI run proved the public
    composition red with FileNotFoundError. The registry/workflow/Makefile pins
    in this module stay in the public composition; only the doc-authority audit
    is dev-repo-scoped.

    Before civibus-y1x the doc declared itself "not authoritative" while
    holding the integration-gate policy, which left the policy unowned. The doc
    must now claim authority and point at SUITE_TIME_BUDGETS instead of
    restating budget numbers that would drift.
    """
    doc_text = TESTING_DOC_PATH.read_text(encoding="utf-8")

    assert "not authoritative" not in doc_text.lower()
    assert "authoritative" in doc_text.lower()
    assert "SUITE_TIME_BUDGETS" in doc_text
    assert "tests/ci/pytest_tier_classifier.py" in doc_text


def test_headroom_band_flags_a_cap_that_cannot_fire() -> None:
    # 30s worst sample, 100-minute cap: 200x headroom. A regression would have
    # to make the suite two hundred times slower before this "guard" noticed.
    dead_guard = _example_budget(target_seconds=60.0, hard_cap_minutes=100)

    violations = hard_cap_band_violations((dead_guard,))

    assert len(violations) == 1
    assert "cannot fire" in violations[0]
    assert f"{HARD_CAP_MAX_HEADROOM}" in violations[0]


def test_headroom_band_flags_a_cap_that_would_flake() -> None:
    # 30s worst sample, 1-minute cap: 2x headroom, under the observed CI
    # variance + cold-cache margin — this cap would page on healthy runs.
    flaky_guard = _example_budget(target_seconds=45.0, hard_cap_minutes=1)

    violations = hard_cap_band_violations((flaky_guard,))

    assert len(violations) == 1
    assert "would flake" in violations[0]
    assert f"{HARD_CAP_MIN_HEADROOM}" in violations[0]


def test_step_timeout_check_flags_missing_and_wrong_timeouts() -> None:
    budget = _example_budget()

    def load_missing_timeout(_workflow_path: str) -> dict:
        return {"jobs": {"synthetic-job": {"steps": [{"name": "synthetic step", "run": "true"}]}}}

    def load_wrong_timeout(_workflow_path: str) -> dict:
        return {
            "jobs": {"synthetic-job": {"steps": [{"name": "synthetic step", "run": "true", "timeout-minutes": 59}]}}
        }

    def load_missing_step(_workflow_path: str) -> dict:
        return {"jobs": {"synthetic-job": {"steps": [{"name": "another step", "run": "true"}]}}}

    assert step_timeout_violations((budget,), load_missing_timeout) != ()
    assert step_timeout_violations((budget,), load_wrong_timeout) != ()
    assert step_timeout_violations((budget,), load_missing_step) != ()


def test_budget_model_rejects_a_target_below_measured_reality_or_above_the_cap() -> None:
    with pytest.raises(ValidationError, match="fantasy"):
        _example_budget(target_seconds=10.0)  # below the 30s worst CI sample

    with pytest.raises(ValidationError, match="meaningless"):
        _example_budget(target_seconds=120.0, hard_cap_minutes=2)  # at the cap
