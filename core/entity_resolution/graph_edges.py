"""
Stub summary for MAR18_cross_domain_er_and_property_graph/civibus_dev/core/entity_resolution/graph_edges.py.
"""

from __future__ import annotations

from typing import Any

import psycopg

from core.entity_resolution.pairing import canonicalize_entity_pair
from core.graph import _escape_cypher_literal, _execute_formatted_cypher

_EDGE_LABEL_BY_DECISION = {
    "probable_match": "SAME_AS",
    "possible_match": "POSSIBLE_MATCH",
}

_NODE_LABEL_BY_ENTITY_TYPE = {
    "person": "Person",
    "organization": "Organization",
}


def _node_label(entity_type: str) -> str:
    try:
        return _NODE_LABEL_BY_ENTITY_TYPE[entity_type]
    except KeyError as exc:
        raise ValueError(f"entity_type must be 'person' or 'organization', got {entity_type!r}") from exc


def _delete_uncertain_er_edges(
    conn: psycopg.Connection,
    *,
    node_label: str,
    pair_id_a: str,
    pair_id_b: str,
) -> None:
    for edge_label in _EDGE_LABEL_BY_DECISION.values():
        _execute_formatted_cypher(
            conn,
            f"""
                MATCH (a:{node_label} {{id: "%s"}})-[e:{edge_label}]->(b:{node_label} {{id: "%s"}})
                DELETE e
            """,
            pair_id_a,
            pair_id_b,
        )


def materialize_er_edges(
    conn: psycopg.Connection,
    classified_pairs: list[dict[str, Any]],
    entity_type: str,
) -> None:
    node_label = _node_label(entity_type)

    for pair in classified_pairs:
        entity_id_a, entity_id_b = canonicalize_entity_pair(pair["entity_id_a"], pair["entity_id_b"])
        pair_id_a = _escape_cypher_literal(str(entity_id_a))
        pair_id_b = _escape_cypher_literal(str(entity_id_b))
        _delete_uncertain_er_edges(
            conn,
            node_label=node_label,
            pair_id_a=pair_id_a,
            pair_id_b=pair_id_b,
        )

        edge_label = _EDGE_LABEL_BY_DECISION.get(pair["decision"])
        if edge_label is None:
            continue

        decision = _escape_cypher_literal(pair["decision"])
        confidence = float(pair["confidence"])
        _execute_formatted_cypher(
            conn,
            f"""
                MATCH (a:{node_label} {{id: "%s"}}), (b:{node_label} {{id: "%s"}})
                MERGE (a)-[e:{edge_label}]->(b)
                SET e.decision = "%s",
                    e.confidence = %s,
                    e.entity_id_a = "%s",
                    e.entity_id_b = "%s"
            """,
            pair_id_a,
            pair_id_b,
            decision,
            confidence,
            pair_id_a,
            pair_id_b,
        )
