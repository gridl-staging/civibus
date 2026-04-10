from __future__ import annotations

from uuid import uuid4

import pytest

from core.entity_resolution.confidence import (
    classify_confidence,
    classify_scored_pairs,
)


# ===========================================================================
# classify_confidence — threshold boundary tests
# ===========================================================================


@pytest.mark.parametrize(
    ("confidence", "expected_decision"),
    [
        (1.0, "match"),
        (0.99, "match"),
        (0.95, "match"),
        (0.9499, "probable_match"),
        (0.90, "probable_match"),
        (0.80, "probable_match"),
        (0.7999, "possible_match"),
        (0.70, "possible_match"),
        (0.60, "possible_match"),
        (0.5999, "no_match"),
        (0.30, "no_match"),
        (0.0, "no_match"),
    ],
)
def test_classify_confidence_threshold_boundaries(
    confidence: float,
    expected_decision: str,
) -> None:
    assert classify_confidence(confidence) == expected_decision


# ===========================================================================
# classify_scored_pairs — metadata preservation + both tiers
# ===========================================================================


def test_classify_scored_pairs_deterministic_match() -> None:
    """Deterministic pairs (confidence=1.0) classify as 'match' with all metadata preserved."""
    id_a = uuid4()
    id_b = uuid4()

    pairs = [
        {
            "entity_id_a": min(id_a, id_b),
            "entity_id_b": max(id_a, id_b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        }
    ]

    classified = classify_scored_pairs(pairs)

    assert len(classified) == 1
    result = classified[0]
    assert result["decision"] == "match"
    assert result["entity_id_a"] == min(id_a, id_b)
    assert result["entity_id_b"] == max(id_a, id_b)
    assert result["confidence"] == 1.0
    assert result["decision_method"] == "deterministic"
    assert result["decided_by"] == "deterministic_fec_id_match"
    assert result["matched_rule_names"] == ["deterministic_fec_id_match"]


def test_classify_scored_pairs_probabilistic_tiers() -> None:
    """Probabilistic pairs get classified by threshold without branching on decision_method."""
    id_a, id_b, id_c, id_d = uuid4(), uuid4(), uuid4(), uuid4()

    pairs = [
        {
            "entity_id_a": min(id_a, id_b),
            "entity_id_b": max(id_a, id_b),
            "confidence": 0.97,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
        {
            "entity_id_a": min(id_a, id_c),
            "entity_id_b": max(id_a, id_c),
            "confidence": 0.85,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
        {
            "entity_id_a": min(id_a, id_d),
            "entity_id_b": max(id_a, id_d),
            "confidence": 0.65,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
    ]

    classified = classify_scored_pairs(pairs)
    decisions = [c["decision"] for c in classified]
    assert decisions == ["match", "probable_match", "possible_match"]

    # Metadata preserved
    for original, result in zip(pairs, classified):
        assert result["decision_method"] == "probabilistic"
        assert result["decided_by"] == "splink_v1"
        assert result["entity_id_a"] == original["entity_id_a"]
        assert result["entity_id_b"] == original["entity_id_b"]
        assert result["confidence"] == original["confidence"]


def test_classify_scored_pairs_does_not_mutate_input() -> None:
    """Input dicts are not modified; output is a new list of new dicts."""
    pair = {
        "entity_id_a": uuid4(),
        "entity_id_b": uuid4(),
        "confidence": 0.50,
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }
    original_keys = set(pair.keys())

    classified = classify_scored_pairs([pair])

    assert "decision" not in pair  # input unchanged
    assert set(pair.keys()) == original_keys
    assert classified[0] is not pair  # different object


def test_classify_scored_pairs_empty_input() -> None:
    """Empty list returns empty list."""
    assert classify_scored_pairs([]) == []


def test_classify_scored_pairs_multi_rule_deterministic() -> None:
    """Multi-rule deterministic pairs preserve matched_rule_names list."""
    id_a = uuid4()
    id_b = uuid4()

    pairs = [
        {
            "entity_id_a": min(id_a, id_b),
            "entity_id_b": max(id_a, id_b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_multi_rule",
            "matched_rule_names": [
                "deterministic_fec_id_match",
                "deterministic_voter_reg_match",
            ],
        }
    ]

    classified = classify_scored_pairs(pairs)

    assert classified[0]["decision"] == "match"
    assert classified[0]["matched_rule_names"] == [
        "deterministic_fec_id_match",
        "deterministic_voter_reg_match",
    ]


def test_classify_confidence_auto_merge_threshold_override() -> None:
    assert classify_confidence(0.91, auto_merge_threshold=0.92) == "probable_match"
    assert classify_confidence(0.92, auto_merge_threshold=0.92) == "match"


def test_classify_scored_pairs_applies_auto_merge_threshold_override() -> None:
    id_a = uuid4()
    id_b = uuid4()
    pairs = [
        {
            "entity_id_a": min(id_a, id_b),
            "entity_id_b": max(id_a, id_b),
            "confidence": 0.95,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]

    default_classified = classify_scored_pairs(pairs)
    overridden_classified = classify_scored_pairs(pairs, auto_merge_threshold=0.96)

    assert default_classified[0]["decision"] == "match"
    assert overridden_classified[0]["decision"] == "probable_match"


@pytest.mark.parametrize(
    "invalid_threshold",
    [0.80, -0.10, 1.01, float("nan"), float("inf")],
)
def test_classify_confidence_rejects_invalid_threshold_override(
    invalid_threshold: float,
) -> None:
    with pytest.raises(ValueError, match="auto_merge_threshold"):
        classify_confidence(0.90, auto_merge_threshold=invalid_threshold)


def test_classify_scored_pairs_rejects_invalid_threshold_override() -> None:
    pairs = [
        {
            "entity_id_a": uuid4(),
            "entity_id_b": uuid4(),
            "confidence": 0.90,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]

    with pytest.raises(ValueError, match="auto_merge_threshold"):
        classify_scored_pairs(pairs, auto_merge_threshold=1.01)
