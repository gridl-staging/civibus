"""Shared pytest tier ownership classifier and suite time-budget owner for CI contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

import conftest as root_conftest
from tests.ci.public_mirror_contract import DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
MERGE_DB_BACKED_TEST_NODES_VARIABLE = "MERGE_DB_BACKED_TEST_NODES"


class PytestTier(StrEnum):
    FAST = "fast"
    INTEGRATION = "integration"
    NIGHTLY = "nightly"
    RELEASE = "release"
    DEV_REPO_ONLY = "dev_repo_only"
    PARKED_CHANGE_TRIGGERED = "parked_change_triggered"


class UnownedPytestNodeError(ValueError):
    """Raised when a node has no canonical pytest tier owner."""


class PytestTierOwnership(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    tier: PytestTier


class PytestTierClassifier(BaseModel):
    """Classify pytest node IDs into exactly one current CI tier.

    Precedence is intentional and stable:
    exact `dev_repo_only` registry entries, exact release target nodes, exact
    DB-backed quarantine entries, parked-suite collection, integration marker
    collection, the Makefile-owned `fast` selection, then the residual `nightly`
    bucket for default-reachable nodes.
    """

    model_config = ConfigDict(frozen=True)

    default_node_ids: frozenset[str] = Field(default_factory=frozenset)
    dev_repo_only_node_ids: frozenset[str] = Field(default_factory=frozenset)
    fast_node_ids: frozenset[str] = Field(default_factory=frozenset)
    quarantined_node_ids: frozenset[str] = Field(default_factory=frozenset)
    release_node_ids: frozenset[str] = Field(default_factory=frozenset)
    integration_node_ids: frozenset[str] = Field(default_factory=frozenset)
    parked_node_ids: frozenset[str] = Field(default_factory=frozenset)

    @property
    def known_node_ids(self) -> frozenset[str]:
        return frozenset(
            self.default_node_ids
            | self.dev_repo_only_node_ids
            | self.fast_node_ids
            | self.quarantined_node_ids
            | self.release_node_ids
            | self.integration_node_ids
            | self.parked_node_ids
        )

    def classify(self, node_id: str) -> PytestTierOwnership:
        for tier, node_ids in self._precedence_order():
            if node_id in node_ids:
                return PytestTierOwnership(node_id=node_id, tier=tier)
        raise UnownedPytestNodeError(f"{node_id} has no pytest tier owner")

    def _precedence_order(self) -> tuple[tuple[PytestTier, frozenset[str]], ...]:
        return (
            (PytestTier.DEV_REPO_ONLY, self.dev_repo_only_node_ids),
            (PytestTier.RELEASE, self.release_node_ids),
            (PytestTier.INTEGRATION, self.quarantined_node_ids),
            (PytestTier.PARKED_CHANGE_TRIGGERED, self.parked_node_ids),
            (PytestTier.INTEGRATION, self.integration_node_ids),
            (PytestTier.FAST, self.fast_node_ids),
            (PytestTier.NIGHTLY, self.default_node_ids),
        )


def current_dev_repo_only_node_ids() -> frozenset[str]:
    return frozenset(DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID)


def current_quarantined_node_ids() -> frozenset[str]:
    return frozenset(entry.node_id for entry in root_conftest._load_db_backed_quarantine())


def current_release_node_ids(makefile_path: Path = MAKEFILE_PATH) -> frozenset[str]:
    return frozenset(_make_variable_tokens(makefile_path, MERGE_DB_BACKED_TEST_NODES_VARIABLE))


def current_parked_target_paths() -> tuple[str, ...]:
    """Return parked-suite collection targets from the root conftest owner."""
    return tuple(child.relative_to(REPO_ROOT).as_posix() for child in root_conftest._parked_jurisdiction_child_dirs())


def build_current_pytest_tier_classifier(
    *,
    default_node_ids: set[str],
    fast_node_ids: set[str],
    integration_node_ids: set[str],
    parked_node_ids: set[str],
) -> PytestTierClassifier:
    return PytestTierClassifier(
        default_node_ids=frozenset(default_node_ids),
        dev_repo_only_node_ids=current_dev_repo_only_node_ids(),
        fast_node_ids=frozenset(fast_node_ids),
        quarantined_node_ids=current_quarantined_node_ids(),
        release_node_ids=current_release_node_ids(),
        integration_node_ids=frozenset(integration_node_ids),
        parked_node_ids=frozenset(parked_node_ids),
    )


def _make_variable_tokens(makefile_path: Path, variable_name: str) -> tuple[str, ...]:
    makefile_lines = makefile_path.read_text(encoding="utf-8").splitlines()
    prefix = f"{variable_name} :="
    start_index = next(index for index, line in enumerate(makefile_lines) if line.startswith(prefix))
    value_lines = [makefile_lines[start_index][len(prefix) :].strip()]
    for line in makefile_lines[start_index + 1 :]:
        if not line.startswith("\t"):
            break
        value_lines.append(line.strip())
    value = " ".join(value_lines).replace("\\", "").strip()
    return tuple(token for token in value.split() if token)


# --- Suite time budgets (civibus-y1x) ----------------------------------------
#
# One owner for the four execution-tier TIME budgets that
# ~/.matt/scrai/globals/standards/ui_test_architecture.md requires ("numeric
# target and hard-cap minutes for all four tiers in one architecture owner").
# This module already owns tier MEMBERSHIP, so the budgets live beside it
# instead of in a parallel registry. docs/reference/testing.md points here and
# never restates the numbers.
#
# ENFORCEMENT DESIGN — why the guard measures CI wall clock and nothing else:
#
# * Laptop wall clock is not assertable. The same `tests/ci` battery measured
#   78s and 271s in the same week on the same machine, differing only in host
#   load (aug19/aug21 handoffs). Any local-wall assertion tight enough to catch
#   real bloat pages on every contended run and gets deleted; any loose enough
#   to survive contention never fires. So no local target is machine-enforced.
# * CI wall clock IS assertable at generous multiples. GitHub-hosted runner
#   step durations for these four suites varied at most ~30% run-to-run across
#   the 2026-08-20/21 samples recorded below, because each run gets a dedicated
#   VM rather than a shared laptop.
# * The enforcement hook is the CI step's `timeout-minutes`, pinned to
#   `hard_cap_minutes` by tests/ci/test_suite_time_budget_contract.py. A breach
#   fails the CI run — a guard that can genuinely fire — and the headroom band
#   below keeps it from firing on runner variance.
#
# HEADROOM BAND — cannot flake AND cannot never-fire, structurally:
# the contract test asserts every hard cap is between MIN and MAX multiples of
# the worst recorded CI sample. Below MIN the cap would page on ordinary runner
# variance and cold caches (flake); above MAX the cap could no longer catch a
# step-change regression (a DB-backed suite leaking into a fast tier, a hang, a
# runaway addition) before it doubles again (dead guard). When a suite grows
# legitimately, the cap eventually fires once; the fix is re-measure, re-declare
# the baseline here, and let the band force the cap to move — which is exactly
# the "hard-cap breach is a failing architecture signal" behavior the standard
# prescribes, not an incident.
HARD_CAP_MIN_HEADROOM = 2.5
HARD_CAP_MAX_HEADROOM = 8.0


class SuiteTier(StrEnum):
    """The four execution tiers from ui_test_architecture.md, mapped to civibus suites."""

    EDIT_FAST = "edit_fast"
    QA_MEDIUM = "qa_medium"
    QA_NIGHTLY = "qa_nightly"
    QA_SIGNOFF = "qa_signoff"


class MeasuredSuiteBaseline(BaseModel):
    """One dated wall-clock measurement of a suite in a named locality."""

    model_config = ConfigDict(frozen=True)

    measured_on: date
    locality: str
    wall_seconds: float = Field(gt=0)
    test_count: int | None = Field(default=None, ge=1)


class SuiteTimeBudget(BaseModel):
    """Numeric target and hard cap for one execution tier's gating suite.

    ``target_seconds`` is the healthy-run upper bound in CI locality; breaching
    it is an investigate-at-next-re-measure signal, surfaced by ``--durations``
    observability, never a paging gate (see the module comment for why).
    ``hard_cap_minutes`` is machine-enforced as ``timeout-minutes`` on the named
    CI step, so a breach fails the run.
    """

    model_config = ConfigDict(frozen=True)

    tier: SuiteTier
    suite: str
    local_command: str
    local_baseline: MeasuredSuiteBaseline
    ci_workflow: str
    ci_job: str
    ci_step: str
    # Worst and full sample set from GitHub-hosted runners; the headroom band
    # is checked against the worst sample so one slow-but-green run cannot
    # silently shrink the cap's real margin.
    ci_baseline_samples_seconds: tuple[float, ...] = Field(min_length=1)
    ci_baseline_measured_on: date
    target_seconds: float = Field(gt=0)
    hard_cap_minutes: int = Field(ge=1)

    @property
    def ci_baseline_worst_seconds(self) -> float:
        return max(self.ci_baseline_samples_seconds)

    @property
    def hard_cap_seconds(self) -> float:
        return float(self.hard_cap_minutes * 60)

    @model_validator(mode="after")
    def _target_between_baseline_and_cap(self) -> "SuiteTimeBudget":
        if not self.ci_baseline_worst_seconds <= self.target_seconds < self.hard_cap_seconds:
            raise ValueError(
                f"{self.suite}: target_seconds={self.target_seconds} must sit between the worst "
                f"measured CI sample ({self.ci_baseline_worst_seconds}s) and the hard cap "
                f"({self.hard_cap_seconds}s); a target below what green runs already measure is "
                "fantasy, and a target at or above the cap makes the cap meaningless"
            )
        return self

    def hard_cap_headroom(self) -> float:
        """Hard cap as a multiple of the worst measured CI sample."""
        return self.hard_cap_seconds / self.ci_baseline_worst_seconds


def hard_cap_band_violations(budgets: tuple[SuiteTimeBudget, ...]) -> tuple[str, ...]:
    """Return one violation per budget whose hard cap leaves the headroom band.

    Shared by the real contract assertion and its mutation proofs so both run
    the same code path; see the band rationale in the module comment above.
    """
    violations: list[str] = []
    for budget in budgets:
        headroom = budget.hard_cap_headroom()
        if headroom < HARD_CAP_MIN_HEADROOM:
            violations.append(
                f"{budget.suite}: hard cap {budget.hard_cap_minutes}min is {headroom:.1f}x the worst "
                f"measured CI sample ({budget.ci_baseline_worst_seconds}s) — under "
                f"{HARD_CAP_MIN_HEADROOM}x it would flake on runner variance and cold caches"
            )
        if headroom > HARD_CAP_MAX_HEADROOM:
            violations.append(
                f"{budget.suite}: hard cap {budget.hard_cap_minutes}min is {headroom:.1f}x the worst "
                f"measured CI sample ({budget.ci_baseline_worst_seconds}s) — over "
                f"{HARD_CAP_MAX_HEADROOM}x the cap cannot fire on a real bloat-class regression; "
                "re-measure the suite and re-declare the baseline instead of padding the cap"
            )
    return tuple(violations)


# Measured evidence, 2026-08-20/21 (this lane re-measured; magnitudes match the
# aug19/aug21 handoff baselines):
# * local (macOS laptop, quiet host): web unit 4.91s vitest / 6.72s wall, 1268
#   tests; fixture smoke 23.7s / 125 passed; qa-fast 131s wall; qa-integration
#   143.4s wall, exit 0 (aug21 handoff §5 had measured ~4:20 on a busier host).
# * CI (github-hosted ubuntu-latest, step wall clock): web unit 34/44/36s;
#   fixture smoke 140/151/144s; qa-fast-public 160/131/135s; DB-backed product
#   suite 206/226/256s (runs 32444574772, 32439273017, 32432898271, 32428714368,
#   32428293705, 32344623826, 32444574747, 32431543481, 32346874235).
SUITE_TIME_BUDGETS: tuple[SuiteTimeBudget, ...] = (
    SuiteTimeBudget(
        tier=SuiteTier.EDIT_FAST,
        suite="web unit",
        local_command="npm --prefix web test",
        local_baseline=MeasuredSuiteBaseline(
            measured_on=date(2026, 8, 21),
            locality="macOS laptop, quiet host",
            wall_seconds=6.7,
            test_count=1268,
        ),
        ci_workflow=".github/workflows/nightly.yml",
        ci_job="web-full",
        ci_step="Web unit tests",
        ci_baseline_samples_seconds=(34.0, 44.0, 36.0),
        ci_baseline_measured_on=date(2026, 8, 21),
        target_seconds=60.0,
        hard_cap_minutes=3,
    ),
    SuiteTimeBudget(
        tier=SuiteTier.QA_MEDIUM,
        suite="qa-fast",
        local_command="make qa-fast",
        local_baseline=MeasuredSuiteBaseline(
            measured_on=date(2026, 8, 21),
            locality="macOS laptop, quiet host",
            wall_seconds=131.0,
            test_count=None,
        ),
        ci_workflow=".github/workflows/ci.yml",
        ci_job="fast",
        ci_step="qa-fast (public locality)",
        ci_baseline_samples_seconds=(160.0, 131.0, 135.0),
        ci_baseline_measured_on=date(2026, 8, 21),
        target_seconds=240.0,
        hard_cap_minutes=10,
    ),
    SuiteTimeBudget(
        tier=SuiteTier.QA_NIGHTLY,
        suite="fixture smoke",
        local_command="npm --prefix web run test:smoke",
        local_baseline=MeasuredSuiteBaseline(
            measured_on=date(2026, 8, 21),
            locality="macOS laptop, quiet host",
            wall_seconds=23.7,
            test_count=125,
        ),
        ci_workflow=".github/workflows/nightly.yml",
        ci_job="browser-smoke-fixture",
        ci_step="Fixture-lane smoke journeys",
        ci_baseline_samples_seconds=(140.0, 151.0, 144.0),
        ci_baseline_measured_on=date(2026, 8, 21),
        target_seconds=240.0,
        hard_cap_minutes=10,
    ),
    SuiteTimeBudget(
        tier=SuiteTier.QA_SIGNOFF,
        suite="qa-integration (DB-backed product suite)",
        local_command="make qa-integration",
        # Re-measured by this lane once port 5475 freed: 143.4s wall, exit 0
        # (the aug21 handoff had measured ~4:20 on a busier host the day
        # before — more same-host contention spread, same magnitude).
        local_baseline=MeasuredSuiteBaseline(
            measured_on=date(2026, 8, 21),
            locality="macOS laptop, quiet host",
            wall_seconds=143.4,
            test_count=None,
        ),
        ci_workflow=".github/workflows/integration.yml",
        ci_job="integration-tests",
        ci_step="DB-backed product suite",
        ci_baseline_samples_seconds=(206.0, 226.0, 256.0),
        ci_baseline_measured_on=date(2026, 8, 21),
        target_seconds=420.0,
        hard_cap_minutes=20,
    ),
)
