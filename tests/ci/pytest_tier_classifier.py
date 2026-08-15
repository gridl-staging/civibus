"""Shared pytest tier ownership classifier for CI contracts."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

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
