"""Contract for the canonical pytest tier classifier."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

import conftest as root_conftest
from tests.ci.public_mirror_contract import DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID, PROJECTED_PUBLIC_CONTRACT_NODE_ID
from tests.ci.pytest_tier_classifier import (
    MAKEFILE_PATH,
    PytestTier,
    PytestTierClassifier,
    UnownedPytestNodeError,
    _make_variable_tokens,
    build_current_pytest_tier_classifier,
    current_dev_repo_only_node_ids,
    current_parked_target_paths,
    current_quarantined_node_ids,
    current_release_node_ids,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTSIDE_DB_BACKED_INTEGRATION_SPECIMEN = (
    "tests/test_bootstrap_contract.py::test_compose_only_bootstrap_provisions_stage1_canaries"
)
ACTIVE_SHARED_HELPER_SPECIMEN = (
    "domains/campaign_finance/jurisdictions/states/test_load_utils.py::test_validated_limit_rejects_negative_values"
)
QA_FAST_SELECTOR_VARIABLES = (
    ("QA_FAST_STRUCTURAL_TEST_PATHS", "QA_FAST_STRUCTURAL_MARKER_EXPRESSION"),
    ("QA_FAST_PRODUCT_TEST_PATHS", "QA_FAST_PRODUCT_MARKER_EXPRESSION"),
)


def _collect_node_ids(
    *pytest_args: str,
    env: dict[str, str] | None = None,
    inherit_parked_escape_hatch: bool = False,
    timeout: int = 180,
) -> set[str]:
    subprocess_env = dict(os.environ)
    if not inherit_parked_escape_hatch:
        subprocess_env.pop("CIVIBUS_INCLUDE_PARKED", None)
    subprocess_env.update(env or {})
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=subprocess_env,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"collection failed with exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return {line.strip() for line in result.stdout.splitlines() if "::" in line and not line.startswith("<")}


def _make_variable_value(variable_name: str) -> str:
    return " ".join(_make_variable_tokens(MAKEFILE_PATH, variable_name))


def _collect_qa_fast_node_ids() -> set[str]:
    selected_node_ids: set[str] = set()
    for path_variable, marker_variable in QA_FAST_SELECTOR_VARIABLES:
        selected_node_ids.update(
            _collect_node_ids(
                *_make_variable_tokens(MAKEFILE_PATH, path_variable),
                "-m",
                _make_variable_value(marker_variable),
            )
        )
    return selected_node_ids


@pytest.fixture(scope="module")
def collected_tier_inputs() -> dict[str, set[str]]:
    projected_contract_file = PROJECTED_PUBLIC_CONTRACT_NODE_ID.split("::", 1)[0]
    return {
        "default": _collect_node_ids(),
        "dev_repo_only": set(current_dev_repo_only_node_ids()),
        "integration": _collect_node_ids("-m", "integration"),
        "e2e": _collect_node_ids("-m", "e2e"),
        "qa_fast": _collect_qa_fast_node_ids(),
        "projected_public_contract": _collect_node_ids(
            "-m",
            "projected_public_contract",
            projected_contract_file,
        ),
        "parked": _collect_node_ids(
            "-m",
            "not integration and not e2e",
            *current_parked_target_paths(),
            env={"CIVIBUS_INCLUDE_PARKED": "1"},
            inherit_parked_escape_hatch=True,
        ),
    }


@pytest.fixture(scope="module")
def classifier(collected_tier_inputs: dict[str, set[str]]) -> PytestTierClassifier:
    return build_current_pytest_tier_classifier(
        default_node_ids=collected_tier_inputs["default"],
        fast_node_ids=collected_tier_inputs["qa_fast"],
        integration_node_ids=collected_tier_inputs["integration"],
        parked_node_ids=collected_tier_inputs["parked"],
    )


def test_classifier_reuses_every_current_pytest_owner(
    classifier: PytestTierClassifier,
    collected_tier_inputs: dict[str, set[str]],
) -> None:
    reachable_node_ids = set().union(
        collected_tier_inputs["default"],
        collected_tier_inputs["dev_repo_only"],
        collected_tier_inputs["integration"],
        collected_tier_inputs["projected_public_contract"],
        collected_tier_inputs["parked"],
        current_quarantined_node_ids(),
    )

    assert set(DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID) <= classifier.known_node_ids
    assert current_quarantined_node_ids() == {entry.node_id for entry in root_conftest._load_db_backed_quarantine()}
    assert current_quarantined_node_ids() <= classifier.known_node_ids
    assert current_release_node_ids() <= classifier.known_node_ids
    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID in collected_tier_inputs["projected_public_contract"]
    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID not in collected_tier_inputs["default"]
    assert reachable_node_ids <= classifier.known_node_ids


def test_classifier_assigns_exactly_one_tier_to_each_reachable_node(
    classifier: PytestTierClassifier,
    collected_tier_inputs: dict[str, set[str]],
) -> None:
    reachable_node_ids = set().union(
        collected_tier_inputs["default"],
        collected_tier_inputs["dev_repo_only"],
        collected_tier_inputs["integration"],
        collected_tier_inputs["projected_public_contract"],
        collected_tier_inputs["parked"],
        current_quarantined_node_ids(),
    )
    tier_counts = Counter({tier: 0 for tier in PytestTier})

    for node_id in sorted(reachable_node_ids):
        ownership = classifier.classify(node_id)
        assert ownership.node_id == node_id
        assert ownership.tier in PytestTier
        tier_counts[ownership.tier] += 1

    assert sum(tier_counts.values()) == len(reachable_node_ids)
    assert tier_counts[PytestTier.FAST] > 0
    assert tier_counts[PytestTier.DEV_REPO_ONLY] > 0
    assert tier_counts[PytestTier.INTEGRATION] > 0
    assert tier_counts[PytestTier.NIGHTLY] > 0
    assert tier_counts[PytestTier.PARKED_CHANGE_TRIGGERED] > 0


def test_qa_fast_selector_is_db_free_and_owned_by_fast_tier(
    classifier: PytestTierClassifier,
    collected_tier_inputs: dict[str, set[str]],
) -> None:
    qa_fast_node_ids = collected_tier_inputs["qa_fast"]
    stage_1_reachable_node_ids = set().union(
        collected_tier_inputs["default"],
        collected_tier_inputs["dev_repo_only"],
        collected_tier_inputs["integration"],
        collected_tier_inputs["projected_public_contract"],
        collected_tier_inputs["parked"],
        current_quarantined_node_ids(),
    )
    higher_precedence_node_ids = (
        classifier.dev_repo_only_node_ids
        | classifier.release_node_ids
        | classifier.quarantined_node_ids
        | classifier.parked_node_ids
        | classifier.integration_node_ids
    )
    fast_owned_node_ids = qa_fast_node_ids - higher_precedence_node_ids
    nightly_node_ids = classifier.default_node_ids - higher_precedence_node_ids - classifier.fast_node_ids

    assert qa_fast_node_ids
    assert qa_fast_node_ids <= stage_1_reachable_node_ids
    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID not in qa_fast_node_ids
    assert qa_fast_node_ids.isdisjoint(collected_tier_inputs["integration"])
    assert qa_fast_node_ids.isdisjoint(collected_tier_inputs["e2e"])
    assert qa_fast_node_ids.isdisjoint(current_quarantined_node_ids())
    assert fast_owned_node_ids
    assert {classifier.classify(node_id).tier for node_id in fast_owned_node_ids} == {PytestTier.FAST}
    assert nightly_node_ids
    assert {classifier.classify(node_id).tier for node_id in nightly_node_ids} == {PytestTier.NIGHTLY}


@pytest.mark.parametrize(
    ("selector_name", "expected_tier"),
    [
        ("dev_repo_only", PytestTier.DEV_REPO_ONLY),
        ("parked", PytestTier.PARKED_CHANGE_TRIGGERED),
        ("integration", PytestTier.INTEGRATION),
    ],
)
def test_classifier_assigns_reused_selectors_to_expected_tiers(
    classifier: PytestTierClassifier,
    collected_tier_inputs: dict[str, set[str]],
    selector_name: str,
    expected_tier: PytestTier,
) -> None:
    higher_precedence_node_ids = {
        PytestTier.DEV_REPO_ONLY: frozenset(),
        PytestTier.RELEASE: classifier.dev_repo_only_node_ids,
        PytestTier.PARKED_CHANGE_TRIGGERED: classifier.dev_repo_only_node_ids
        | classifier.release_node_ids
        | classifier.quarantined_node_ids,
        PytestTier.INTEGRATION: classifier.dev_repo_only_node_ids | classifier.release_node_ids,
    }[expected_tier]
    expected_node_ids = collected_tier_inputs[selector_name] - higher_precedence_node_ids

    assert expected_node_ids
    assert {classifier.classify(node_id).tier for node_id in expected_node_ids} == {expected_tier}


def test_classifier_assigns_exact_owner_entries_after_precedence(classifier: PytestTierClassifier) -> None:
    assert current_release_node_ids()
    assert current_quarantined_node_ids()
    assert {classifier.classify(node_id).tier for node_id in current_release_node_ids()} == {PytestTier.RELEASE}
    assert {classifier.classify(node_id).tier for node_id in current_quarantined_node_ids()} == {PytestTier.INTEGRATION}


def test_active_shared_helper_tests_remain_in_stage_1_residual_tier(
    classifier: PytestTierClassifier,
    collected_tier_inputs: dict[str, set[str]],
) -> None:
    assert ACTIVE_SHARED_HELPER_SPECIMEN in collected_tier_inputs["default"]
    assert ACTIVE_SHARED_HELPER_SPECIMEN not in collected_tier_inputs["parked"]
    assert classifier.classify(ACTIVE_SHARED_HELPER_SPECIMEN).tier == PytestTier.NIGHTLY


def test_classifier_assigns_all_repository_integration_nodes_to_integration(
    classifier: PytestTierClassifier,
    collected_tier_inputs: dict[str, set[str]],
) -> None:
    assert OUTSIDE_DB_BACKED_INTEGRATION_SPECIMEN in collected_tier_inputs["integration"]
    assert classifier.classify(OUTSIDE_DB_BACKED_INTEGRATION_SPECIMEN).tier == PytestTier.INTEGRATION


def test_parked_targets_are_derived_from_root_conftest_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    parked_parent = REPO_ROOT / "synthetic_parked_parent"
    monkeypatch.setattr(root_conftest, "_PARKED_JURISDICTION_PARENTS", (parked_parent,))

    child_path = parked_parent / "child_jurisdiction"
    monkeypatch.setattr(Path, "iterdir", lambda path: iter((child_path,)) if path == parked_parent else iter(()))
    monkeypatch.setattr(Path, "is_dir", lambda path: path == child_path)

    assert current_parked_target_paths() == (child_path.relative_to(REPO_ROOT).as_posix(),)


def test_non_parked_collections_ignore_inherited_parked_escape_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_INCLUDE_PARKED", "1")

    # Naming the parent keeps collect_ignore active; naming NC directly would bypass it.
    states_parent = "domains/campaign_finance/jurisdictions/states"
    default_node_ids = _collect_node_ids(states_parent)
    explicit_inherited_node_ids = _collect_node_ids(states_parent, inherit_parked_escape_hatch=True)
    default_node_paths = {node_id.split("::", 1)[0] for node_id in default_node_ids}
    explicit_inherited_node_paths = {node_id.split("::", 1)[0] for node_id in explicit_inherited_node_ids}

    assert ACTIVE_SHARED_HELPER_SPECIMEN in default_node_ids
    assert default_node_ids != explicit_inherited_node_ids
    assert not any("/jurisdictions/states/NC/" in node_path for node_path in default_node_paths)
    assert any("/jurisdictions/states/NC/" in node_path for node_path in explicit_inherited_node_paths)


def test_classifier_precedence_keeps_exact_node_registries_authoritative() -> None:
    overlapping_node_id = "domains/campaign_finance/jurisdictions/states/NC/tests/test_case.py::test_case"
    classifier = PytestTierClassifier(
        default_node_ids={overlapping_node_id},
        dev_repo_only_node_ids={overlapping_node_id},
        fast_node_ids={overlapping_node_id},
        quarantined_node_ids=set(),
        release_node_ids={overlapping_node_id},
        integration_node_ids={overlapping_node_id},
        parked_node_ids={overlapping_node_id},
    )

    assert classifier.classify(overlapping_node_id).tier == PytestTier.DEV_REPO_ONLY


def test_classifier_fails_closed_for_synthetic_unowned_node(tmp_path: Path) -> None:
    test_file = tmp_path / "test_unowned_tier.py"
    test_file.write_text("def test_unowned_tier_specimen():\n    assert True\n", encoding="utf-8")
    synthetic_node_ids = _collect_node_ids(test_file.as_posix())
    assert len(synthetic_node_ids) == 1

    classifier = PytestTierClassifier(
        default_node_ids=set(),
        dev_repo_only_node_ids=set(),
        fast_node_ids=set(),
        quarantined_node_ids=set(),
        release_node_ids=set(),
        integration_node_ids=set(),
        parked_node_ids=set(),
    )

    with pytest.raises(UnownedPytestNodeError, match="has no pytest tier owner"):
        classifier.classify(next(iter(synthetic_node_ids)))
