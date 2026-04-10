from __future__ import annotations

import math
from typing import Any

from core.entity_resolution.splink_config import (
    THRESHOLD_AUTO_MERGE,
    THRESHOLD_POSSIBLE,
    THRESHOLD_PROBABLE,
)


def resolve_auto_merge_threshold(auto_merge_threshold: float | None) -> float:
    """Return the effective auto-merge threshold after validating override semantics."""
    if auto_merge_threshold is None:
        return THRESHOLD_AUTO_MERGE

    if not math.isfinite(auto_merge_threshold):
        raise ValueError("auto_merge_threshold must be a finite float.")

    if auto_merge_threshold <= THRESHOLD_PROBABLE or auto_merge_threshold > 1.0:
        raise ValueError(
            f"auto_merge_threshold must be greater than THRESHOLD_PROBABLE ({THRESHOLD_PROBABLE}) and at most 1.0."
        )

    return auto_merge_threshold


def classify_confidence(
    confidence: float,
    *,
    auto_merge_threshold: float | None = None,
) -> str:
    """Map a numeric confidence score to a decision label.

    Uses thresholds from ``splink_config.py`` as the single source of truth.
    """
    effective_auto_merge_threshold = resolve_auto_merge_threshold(auto_merge_threshold)

    if confidence >= effective_auto_merge_threshold:
        return "match"
    if confidence >= THRESHOLD_PROBABLE:
        return "probable_match"
    if confidence >= THRESHOLD_POSSIBLE:
        return "possible_match"
    return "no_match"


def classify_scored_pairs(
    pairs: list[dict[str, Any]],
    *,
    auto_merge_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Add a ``decision`` label to each scored pair.

    Preserves all existing metadata. Does not branch on ``decision_method`` —
    both deterministic and probabilistic pairs flow through the same thresholds.
    """
    return [
        {
            **pair,
            "decision": classify_confidence(
                pair["confidence"],
                auto_merge_threshold=auto_merge_threshold,
            ),
        }
        for pair in pairs
    ]
