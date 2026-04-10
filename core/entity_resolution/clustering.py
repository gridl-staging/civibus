from __future__ import annotations

from typing import Any
from uuid import UUID


def build_connected_components(
    classified_pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build connected components from classified pairs using union-find.

    Drops ``no_match`` pairs. Each component carries ``member_ids``,
    ``min_confidence``, ``min_decision``, and ``links``.
    """
    retained = [p for p in classified_pairs if p["decision"] != "no_match"]
    if not retained:
        return []

    parent: dict[UUID, UUID] = {}

    def find(x: UUID) -> UUID:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: UUID, b: UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pair in retained:
        entity_a = pair["entity_id_a"]
        entity_b = pair["entity_id_b"]
        parent.setdefault(entity_a, entity_a)
        parent.setdefault(entity_b, entity_b)
        union(entity_a, entity_b)

    # Group entities by root
    root_to_members: dict[UUID, set[UUID]] = {}
    for entity_id in parent:
        root = find(entity_id)
        root_to_members.setdefault(root, set()).add(entity_id)

    # Group links by root
    root_to_links: dict[UUID, list[dict[str, Any]]] = {}
    for pair in retained:
        root = find(pair["entity_id_a"])
        root_to_links.setdefault(root, []).append(pair)

    components: list[dict[str, Any]] = []
    for root, members in root_to_members.items():
        links = root_to_links.get(root, [])
        min_conf = min(link["confidence"] for link in links)
        min_decision = min(
            (link["decision"] for link in links),
            key=_decision_rank,
        )
        components.append(
            {
                "member_ids": members,
                "min_confidence": min_conf,
                "min_decision": min_decision,
                "links": links,
            }
        )

    return components


_DECISION_RANKS = {
    "match": 3,
    "probable_match": 2,
    "possible_match": 1,
    "no_match": 0,
}


def _decision_rank(decision: str) -> int:
    return _DECISION_RANKS.get(decision, -1)


def select_canonical_entity_id(
    entity_rows: list[dict[str, Any]],
    member_ids: set[UUID],
) -> UUID:
    """Pick the canonical entity from a component by completeness then UUID tiebreak.

    Deduplicates rows by entity ID first so multi-row extracts (from
    ``identifier_key`` unnesting) do not inflate non-null field counts.
    """
    best_by_id: dict[UUID, dict[str, Any]] = {}
    for row in entity_rows:
        entity_id = row["id"]
        if entity_id not in member_ids:
            continue
        current_best_row = best_by_id.get(entity_id)
        if current_best_row is None or _non_null_count(row) > _non_null_count(current_best_row):
            best_by_id[entity_id] = row

    return min(best_by_id, key=lambda entity_id: (-_non_null_count(best_by_id[entity_id]), entity_id))


def _non_null_count(row: dict[str, Any]) -> int:
    return sum(1 for v in row.values() if v is not None)


def cluster_scored_pairs(
    classified_pairs: list[dict[str, Any]],
    entity_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Split classified pairs into auto-merge clusters and review components.

    Returns a dict with:
    - ``auto_merge_clusters``: components where weakest link is ``match``
    - ``review_components``: components with any sub-match link and no
      canonical assignment metadata
    - ``pairwise_decisions``: all classified pairs (pass-through for Stage 4)
    """
    components = build_connected_components(classified_pairs)

    auto_merge: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for comp in components:
        if comp["min_decision"] == "match":
            auto_merge.append(
                {
                    **comp,
                    "canonical_entity_id": select_canonical_entity_id(
                        entity_rows,
                        comp["member_ids"],
                    ),
                }
            )
            continue

        review.append(dict(comp))

    return {
        "auto_merge_clusters": auto_merge,
        "review_components": review,
        "pairwise_decisions": classified_pairs,
    }
