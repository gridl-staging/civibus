"""Unit contract for the public-mirror node expectations.

`test_projected_public_gate_matches_canonical_public_eligible_nodes` runs pytest
collection twice in subprocesses and takes minutes, so its assertion logic could
only ever be exercised end-to-end. These tests exercise that logic directly on
synthetic node sets, which is what makes the two clauses independently provable:

  * projection fidelity is exact (`canonical == projected`);
  * the non-collapse bound is a FLOOR, not an equality.

The floor distinction is the whole point. Set equality cannot catch a collapse
that reduces canonical and projected by the same amount — a broken selector or a
swallowed collection error does exactly that — so the count clause is real. But
expressing it as an equality made every test-adding merge fail until a human
bumped a literal, which is a ratchet, not a guard.
"""

from __future__ import annotations

import pytest

from tests.ci.public_mirror_contract import (
    PROJECTED_PUBLIC_CONTRACT_NODE_ID,
    evaluate_public_node_expectations,
    expected_dev_repo_only_failure_nodes,
)


def _nodes(prefix: str, count: int, *, offset: int = 0) -> set[str]:
    """Build `count` synthetic node ids under `prefix`, unique per offset."""
    return {f"{prefix}test_mod.py::test_case_{index + offset}" for index in range(count)}


FLOORS = {"api/": 2, "core/": 3}
TOTAL_FLOOR = 5


def _at_floor() -> set[str]:
    """The smallest node set that satisfies every floor exactly."""
    return _nodes("api/", 2) | _nodes("core/", 3)


def test_expected_dev_repo_only_failures_are_limited_to_selected_nodes() -> None:
    selected_classified_node = (
        "tests/test_debbie_post_sync_hook.py::test_projected_public_gate_matches_canonical_public_eligible_nodes"
    )
    selected_nodes = {selected_classified_node, "tests/public_runtime.py::test_public"}

    expected_failure_nodes = expected_dev_repo_only_failure_nodes(selected_nodes)

    assert expected_failure_nodes == {selected_classified_node}
    assert PROJECTED_PUBLIC_CONTRACT_NODE_ID not in expected_failure_nodes


def test_projection_only_document_contracts_are_classified_as_dev_repo_only() -> None:
    projection_only_nodes = {
        "tests/keel/test_gate_l3.py::test_repo_sources_registry_wa_emits_four_source_attributed_prototyped_artifacts",
        "tests/test_checkpoint_b_receipt_contract.py::test_aug15_closeout_preserves_the_red_verdict_without_private_paths",
        "tests/test_doc_system_v2_layout.py::test_codex_governance_routes_to_one_inactive_civibus_profile",
        "tests/test_jurisdiction_authority_ledger_contract.py::test_autonomous_docs_have_no_stale_routine_approval_or_planned_registry_gate",
        "tests/test_jurisdiction_authority_ledger_contract.py::test_canonical_docs_define_the_general_filing_authority_relation_contract",
        "tests/test_jurisdiction_authority_ledger_contract.py::test_geography_owner_remains_separate_from_filing_authority",
        "tests/test_jurisdiction_authority_ledger_contract.py::test_legacy_parent_boolean_bootstrap_evidence_is_explicit_debt",
    }

    assert expected_dev_repo_only_failure_nodes(projection_only_nodes) == projection_only_nodes


def test_node_set_at_the_floor_reports_no_violations() -> None:
    nodes = _at_floor()

    violations = evaluate_public_node_expectations(
        nodes,
        nodes,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    assert violations == ()


def test_growth_above_the_floor_is_accepted_without_editing_a_literal() -> None:
    """Adding public-eligible tests must never require a floor edit.

    This is the anti-ratchet clause. Under the previous exact-equality assertion
    this input was a failure; it must now be clean.
    """
    grown = _at_floor() | _nodes("api/", 40, offset=500) | _nodes("core/", 17, offset=500)

    violations = evaluate_public_node_expectations(
        grown,
        grown,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    assert violations == ()


def test_equal_but_collapsed_node_sets_are_reported() -> None:
    """The clause set-equality cannot cover: both sides shrink together.

    A broken `-m` selector or a swallowed collection error reduces canonical and
    projected identically, so `canonical == projected` still holds. Only the
    floor catches it. If this test ever passes with the floor clause removed,
    the floor was not load-bearing after all.
    """
    collapsed = _nodes("api/", 1) | _nodes("core/", 1)

    violations = evaluate_public_node_expectations(
        collapsed,
        collapsed,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    # Both sides are reported for each breached floor so the diagnosis names the
    # side that shrank: 2 total + 2 api/ + 2 core/.
    assert violations == (
        "canonical total below floor: collected 2, floor 5",
        "projected total below floor: collected 2, floor 5",
        "api/ canonical below floor: collected 1, floor 2",
        "api/ projected below floor: collected 1, floor 2",
        "core/ canonical below floor: collected 1, floor 3",
        "core/ projected below floor: collected 1, floor 3",
    )
    assert not any("projection drift" in violation for violation in violations)


def test_prefix_collapse_is_reported_even_when_the_total_floor_is_met() -> None:
    """One prefix can empty out while another grows enough to hide it in the total."""
    lopsided = _nodes("api/", 6)

    violations = evaluate_public_node_expectations(
        lopsided,
        lopsided,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    # The total floor (5) and the api/ floor (2) are both satisfied by the six
    # api/ nodes; only the emptied core/ prefix reds.
    assert violations == (
        "core/ canonical below floor: collected 0, floor 3",
        "core/ projected below floor: collected 0, floor 3",
    )


def test_projection_drift_is_reported_with_both_directions() -> None:
    canonical = _at_floor() | {"api/only_canonical.py::test_a"}
    projected = _at_floor() | {"core/only_projected.py::test_b"}

    violations = evaluate_public_node_expectations(
        canonical,
        projected,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    drift = [violation for violation in violations if "projection" in violation]
    assert len(drift) == 1
    assert "api/only_canonical.py::test_a" in drift[0]
    assert "core/only_projected.py::test_b" in drift[0]


def test_projection_drift_is_reported_independently_of_the_floors() -> None:
    """Drift must red even when both sides comfortably clear every floor."""
    shared = _at_floor() | _nodes("api/", 30, offset=900)
    canonical = shared | {"core/drift.py::test_only_here"}

    violations = evaluate_public_node_expectations(
        canonical,
        shared,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    assert len(violations) == 1
    assert "projection" in violations[0]
    assert "core/drift.py::test_only_here" in violations[0]


@pytest.mark.parametrize("empty_side", ["canonical", "projected"])
def test_an_empty_collection_side_is_never_silently_clean(empty_side: str) -> None:
    """A vacuous collection result must not read as a pass on either side."""
    populated = _at_floor()
    canonical = set() if empty_side == "canonical" else populated
    projected = set() if empty_side == "projected" else populated

    violations = evaluate_public_node_expectations(
        canonical,
        projected,
        minimum_total=TOTAL_FLOOR,
        minimum_prefix_totals=FLOORS,
    )

    assert violations != ()
