from __future__ import annotations

from uuid import UUID, uuid4

from core.entity_resolution.clustering import (
    build_connected_components,
    cluster_scored_pairs,
    select_canonical_entity_id,
)


# ===========================================================================
# build_connected_components — union-find + transitive closure
# ===========================================================================


def _classified_pair(
    id_a: UUID,
    id_b: UUID,
    confidence: float,
    decision: str,
    decision_method: str = "probabilistic",
    decided_by: str = "splink_v1",
) -> dict:
    return {
        "entity_id_a": min(id_a, id_b),
        "entity_id_b": max(id_a, id_b),
        "confidence": confidence,
        "decision": decision,
        "decision_method": decision_method,
        "decided_by": decided_by,
    }


def test_build_connected_components_transitive_closure() -> None:
    """A-B and B-C form one component {A, B, C} via transitive closure."""
    a, b, c = uuid4(), uuid4(), uuid4()

    pairs = [
        _classified_pair(a, b, 0.97, "match"),
        _classified_pair(b, c, 0.96, "match"),
    ]

    components = build_connected_components(pairs)

    assert len(components) == 1
    comp = components[0]
    assert comp["member_ids"] == {a, b, c}
    assert comp["min_confidence"] == 0.96
    assert comp["min_decision"] == "match"
    assert len(comp["links"]) == 2


def test_build_connected_components_drops_no_match() -> None:
    """no_match pairs are excluded from components entirely."""
    a, b, c = uuid4(), uuid4(), uuid4()

    pairs = [
        _classified_pair(a, b, 0.97, "match"),
        _classified_pair(a, c, 0.40, "no_match"),
    ]

    components = build_connected_components(pairs)

    assert len(components) == 1
    assert components[0]["member_ids"] == {a, b}
    # c is not in any component


def test_build_connected_components_separate_components() -> None:
    """Disconnected pairs form separate components."""
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()

    pairs = [
        _classified_pair(a, b, 0.97, "match"),
        _classified_pair(c, d, 0.85, "probable_match"),
    ]

    components = build_connected_components(pairs)

    assert len(components) == 2
    member_sets = [comp["member_ids"] for comp in components]
    assert {a, b} in member_sets
    assert {c, d} in member_sets


def test_build_connected_components_min_confidence_across_links() -> None:
    """Component confidence is the minimum across all retained links."""
    a, b, c = uuid4(), uuid4(), uuid4()

    pairs = [
        _classified_pair(a, b, 0.97, "match"),
        _classified_pair(b, c, 0.82, "probable_match"),
    ]

    components = build_connected_components(pairs)

    assert len(components) == 1
    assert components[0]["min_confidence"] == 0.82
    assert components[0]["min_decision"] == "probable_match"


def test_build_connected_components_retains_probable_and_possible() -> None:
    """probable_match and possible_match links are retained (not just match)."""
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()

    pairs = [
        _classified_pair(a, b, 0.85, "probable_match"),
        _classified_pair(c, d, 0.65, "possible_match"),
    ]

    components = build_connected_components(pairs)

    assert len(components) == 2
    min_decisions = {comp["min_decision"] for comp in components}
    assert min_decisions == {"probable_match", "possible_match"}


def test_build_connected_components_empty_input() -> None:
    """Empty pairs returns empty components."""
    assert build_connected_components([]) == []


def test_build_connected_components_all_no_match() -> None:
    """If all pairs are no_match, no components are formed."""
    a, b = uuid4(), uuid4()

    pairs = [_classified_pair(a, b, 0.40, "no_match")]

    assert build_connected_components(pairs) == []


# ===========================================================================
# select_canonical_entity_id — completeness scoring
# ===========================================================================


def test_select_canonical_most_non_null_fields() -> None:
    """Entity with the most non-null fields wins canonical selection."""
    sparse = uuid4()
    dense = uuid4()

    entity_rows = [
        {"id": sparse, "canonical_name": "Sparse", "first_name": None, "last_name": None},
        {"id": dense, "canonical_name": "Dense", "first_name": "Alice", "last_name": "Smith"},
    ]

    assert select_canonical_entity_id(entity_rows, {sparse, dense}) == dense


def test_select_canonical_deduplicates_multi_row_extracts() -> None:
    """Multiple rows per entity (from identifier_key unnesting) do not inflate non-null counts."""
    entity_with_two_rows = uuid4()
    entity_with_one_row = uuid4()

    entity_rows = [
        # Two rows for the same entity (different identifier_key values)
        {"id": entity_with_two_rows, "canonical_name": "A", "first_name": "Alice", "identifier_key": "fec_id:FEC-001"},
        {
            "id": entity_with_two_rows,
            "canonical_name": "A",
            "first_name": "Alice",
            "identifier_key": "voter_reg_id:VR-001",
        },
        # One row for a different entity with more non-null fields
        {
            "id": entity_with_one_row,
            "canonical_name": "B",
            "first_name": "Bob",
            "last_name": "Smith",
            "identifier_key": "fec_id:FEC-002",
        },
    ]

    result = select_canonical_entity_id(entity_rows, {entity_with_two_rows, entity_with_one_row})
    # entity_with_one_row has more non-null fields when deduplicated
    assert result == entity_with_one_row


def test_select_canonical_tiebreak_smallest_uuid() -> None:
    """Equal non-null counts break ties on smallest UUID."""
    id_small = UUID("00000000-0000-0000-0000-000000000001")
    id_large = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

    entity_rows = [
        {"id": id_small, "canonical_name": "A", "first_name": "Alice"},
        {"id": id_large, "canonical_name": "B", "first_name": "Bob"},
    ]

    assert select_canonical_entity_id(entity_rows, {id_small, id_large}) == id_small


def test_select_canonical_ignores_entities_not_in_member_ids() -> None:
    """Only rows whose id is in member_ids are considered."""
    member = uuid4()
    outsider = uuid4()

    entity_rows = [
        {"id": member, "canonical_name": "Member"},
        {"id": outsider, "canonical_name": "Outsider", "first_name": "Bob", "last_name": "Smith", "employer": "Acme"},
    ]

    assert select_canonical_entity_id(entity_rows, {member}) == member


# ===========================================================================
# cluster_scored_pairs — auto_merge vs review split
# ===========================================================================


def test_cluster_scored_pairs_all_match_is_auto_merge() -> None:
    """Components where all links are 'match' go to auto_merge_clusters."""
    a, b, c = uuid4(), uuid4(), uuid4()

    classified_pairs = [
        _classified_pair(a, b, 1.0, "match", "deterministic", "deterministic_fec_id_match"),
        _classified_pair(b, c, 0.97, "match"),
    ]
    entity_rows = [
        {"id": a, "canonical_name": "A", "first_name": "Alice"},
        {"id": b, "canonical_name": "B", "first_name": "Bob"},
        {"id": c, "canonical_name": "C"},
    ]

    result = cluster_scored_pairs(classified_pairs, entity_rows)

    assert len(result["auto_merge_clusters"]) == 1
    assert len(result["review_components"]) == 0

    cluster = result["auto_merge_clusters"][0]
    assert cluster["member_ids"] == {a, b, c}
    assert cluster["canonical_entity_id"] is not None
    assert cluster["min_confidence"] == 0.97


def test_cluster_scored_pairs_probable_link_goes_to_review() -> None:
    """A component with a probable_match link is review-only, not auto-merge."""
    a, b, c = uuid4(), uuid4(), uuid4()

    classified_pairs = [
        _classified_pair(a, b, 1.0, "match", "deterministic", "deterministic_fec_id_match"),
        _classified_pair(b, c, 0.85, "probable_match"),
    ]
    entity_rows = [
        {"id": a, "canonical_name": "A"},
        {"id": b, "canonical_name": "B"},
        {"id": c, "canonical_name": "C"},
    ]

    result = cluster_scored_pairs(classified_pairs, entity_rows)

    assert len(result["auto_merge_clusters"]) == 0
    assert len(result["review_components"]) == 1
    review_component = result["review_components"][0]
    assert review_component["member_ids"] == {a, b, c}
    assert "canonical_entity_id" not in review_component


def test_cluster_scored_pairs_mixed_auto_merge_and_review() -> None:
    """Independent clusters can split between auto-merge and review."""
    a, b = uuid4(), uuid4()
    c, d = uuid4(), uuid4()

    classified_pairs = [
        _classified_pair(a, b, 0.98, "match"),
        _classified_pair(c, d, 0.75, "possible_match"),
    ]
    entity_rows = [
        {"id": a, "canonical_name": "A"},
        {"id": b, "canonical_name": "B"},
        {"id": c, "canonical_name": "C"},
        {"id": d, "canonical_name": "D"},
    ]

    result = cluster_scored_pairs(classified_pairs, entity_rows)

    assert len(result["auto_merge_clusters"]) == 1
    assert len(result["review_components"]) == 1
    assert result["auto_merge_clusters"][0]["member_ids"] == {a, b}
    review_component = result["review_components"][0]
    assert review_component["member_ids"] == {c, d}
    assert "canonical_entity_id" not in review_component


def test_cluster_scored_pairs_no_match_excluded() -> None:
    """no_match pairs don't form components at all."""
    a, b = uuid4(), uuid4()

    classified_pairs = [_classified_pair(a, b, 0.40, "no_match")]
    entity_rows = [
        {"id": a, "canonical_name": "A"},
        {"id": b, "canonical_name": "B"},
    ]

    result = cluster_scored_pairs(classified_pairs, entity_rows)

    assert len(result["auto_merge_clusters"]) == 0
    assert len(result["review_components"]) == 0


def test_cluster_scored_pairs_returns_all_classified_pairs() -> None:
    """The pairwise_decisions list contains all input pairs with their decisions intact."""
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()

    classified_pairs = [
        _classified_pair(a, b, 0.97, "match"),
        _classified_pair(c, d, 0.40, "no_match"),
    ]
    entity_rows = [
        {"id": a, "canonical_name": "A"},
        {"id": b, "canonical_name": "B"},
        {"id": c, "canonical_name": "C"},
        {"id": d, "canonical_name": "D"},
    ]

    result = cluster_scored_pairs(classified_pairs, entity_rows)

    assert len(result["pairwise_decisions"]) == 2
    decisions = {(p["entity_id_a"], p["entity_id_b"]): p["decision"] for p in result["pairwise_decisions"]}
    assert decisions[min(a, b), max(a, b)] == "match"
    assert decisions[min(c, d), max(c, d)] == "no_match"


def test_cluster_scored_pairs_empty_input() -> None:
    """Empty classified pairs produces empty results."""
    result = cluster_scored_pairs([], [])

    assert result["auto_merge_clusters"] == []
    assert result["review_components"] == []
    assert result["pairwise_decisions"] == []


# ===========================================================================
# Cross-module regression: Stage 2 ScoredPair → classify → cluster pipeline
# ===========================================================================


def test_end_to_end_deterministic_and_probabilistic_pipeline() -> None:
    """Realistic Stage 2 output flows through classify → cluster preserving all metadata."""
    from core.entity_resolution.confidence import classify_scored_pairs

    # Simulate Stage 2 output: 2 deterministic matches + 1 probabilistic probable
    a, b, c, d, e = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()

    scored_pairs = [
        # Deterministic: A-B share fec_id
        {
            "entity_id_a": min(a, b),
            "entity_id_b": max(a, b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        },
        # Deterministic: B-C share voter_reg_id (transitive with A-B)
        {
            "entity_id_a": min(b, c),
            "entity_id_b": max(b, c),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_voter_reg_match",
            "matched_rule_names": ["deterministic_voter_reg_match"],
        },
        # Probabilistic: D-E are probable (below auto-merge)
        {
            "entity_id_a": min(d, e),
            "entity_id_b": max(d, e),
            "confidence": 0.88,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
    ]

    entity_rows = [
        {
            "id": a,
            "canonical_name": "Alice Smith",
            "first_name": "Alice",
            "last_name": "Smith",
            "date_of_birth": "1985-04-12",
        },
        {
            "id": b,
            "canonical_name": "Alice J Smith",
            "first_name": "Alice",
            "last_name": "Smith",
            "date_of_birth": None,
        },
        {"id": c, "canonical_name": "A Smith", "first_name": None, "last_name": "Smith", "date_of_birth": None},
        {
            "id": d,
            "canonical_name": "Bob Jones",
            "first_name": "Bob",
            "last_name": "Jones",
            "date_of_birth": "1990-01-01",
        },
        {
            "id": e,
            "canonical_name": "Robert Jones",
            "first_name": "Robert",
            "last_name": "Jones",
            "date_of_birth": "1990-01-01",
        },
    ]

    # Pipeline: classify → cluster
    classified = classify_scored_pairs(scored_pairs)
    result = cluster_scored_pairs(classified, entity_rows)

    # A-B-C form an auto-merge cluster (all links are match, confidence >= 0.95)
    assert len(result["auto_merge_clusters"]) == 1
    auto_cluster = result["auto_merge_clusters"][0]
    assert auto_cluster["member_ids"] == {a, b, c}
    assert auto_cluster["min_confidence"] == 1.0
    assert auto_cluster["min_decision"] == "match"
    # Canonical should be entity 'a' (most non-null fields: 4 vs 3 vs 2)
    assert auto_cluster["canonical_entity_id"] == a

    # D-E form a review component (probable_match, not auto-merge)
    assert len(result["review_components"]) == 1
    review_comp = result["review_components"][0]
    assert review_comp["member_ids"] == {d, e}
    assert review_comp["min_decision"] == "probable_match"
    assert "canonical_entity_id" not in review_comp

    # All 3 pairwise decisions preserved with original metadata
    assert len(result["pairwise_decisions"]) == 3
    for original, classified_pair in zip(scored_pairs, result["pairwise_decisions"]):
        assert classified_pair["entity_id_a"] == original["entity_id_a"]
        assert classified_pair["entity_id_b"] == original["entity_id_b"]
        assert classified_pair["confidence"] == original["confidence"]
        assert classified_pair["decision_method"] == original["decision_method"]
        assert classified_pair["decided_by"] == original["decided_by"]
        assert "decision" in classified_pair

    # Deterministic pairs preserve matched_rule_names
    det_pairs = [p for p in result["pairwise_decisions"] if p["decision_method"] == "deterministic"]
    for p in det_pairs:
        assert "matched_rule_names" in p


def test_end_to_end_review_components_never_get_cluster_assignment() -> None:
    """Review components have no canonical_entity_id that implies er_cluster_id persistence."""
    from core.entity_resolution.confidence import classify_scored_pairs

    a, b = uuid4(), uuid4()

    scored_pairs = [
        {
            "entity_id_a": min(a, b),
            "entity_id_b": max(a, b),
            "confidence": 0.70,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
    ]
    entity_rows = [
        {"id": a, "canonical_name": "A"},
        {"id": b, "canonical_name": "B"},
    ]

    classified = classify_scored_pairs(scored_pairs)
    result = cluster_scored_pairs(classified, entity_rows)

    # No auto-merge clusters
    assert len(result["auto_merge_clusters"]) == 0
    # Review component exists but Stage 4 must NOT use it for er_cluster_id
    assert len(result["review_components"]) == 1
    review_component = result["review_components"][0]
    assert review_component["member_ids"] == {a, b}
    assert review_component["min_decision"] == "possible_match"
    assert "canonical_entity_id" not in review_component
