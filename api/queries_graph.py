"""Graph query helpers for Apache AGE entity relationship lookups."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import psycopg

from api.models.graph import (
    AGE_LABEL_TO_NEIGHBOR_TYPE,
    GRAPH_ALLOWED_RELATIONSHIP_TYPES,
    GRAPH_ENTITY_TYPE_SPECS,
    GRAPH_ENTITY_TYPE_TO_AGE_LABEL,
)


def _graph_entity_exists(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_id: UUID,
) -> bool:
    """Check whether the graph contains the requested route subject node."""
    from core.graph import _escape_cypher_literal, query_formatted_cypher

    entity_spec = GRAPH_ENTITY_TYPE_SPECS.get(entity_type)
    if entity_spec is None:
        raise ValueError(f"entity_type must be one of {sorted(GRAPH_ENTITY_TYPE_TO_AGE_LABEL)}, got {entity_type!r}")

    safe_id = _escape_cypher_literal(str(entity_id))
    rows = query_formatted_cypher(
        conn,
        f"""
            MATCH (n:{entity_spec.age_label} {{id: "%s"}})
            RETURN {{id: n.id}}
            LIMIT 1
        """,
        safe_id,
    )
    return len(rows) > 0


def _normalize_graph_neighbor(raw_row: object) -> dict[str, Any] | None:
    """Convert agtype row payload to API-normalized neighbor fields."""
    row = json.loads(str(raw_row))
    relationship_type = row.get("relationship_type")
    if relationship_type not in GRAPH_ALLOWED_RELATIONSHIP_TYPES:
        return None

    age_neighbor_label = row.get("entity_type")
    api_neighbor_type = AGE_LABEL_TO_NEIGHBOR_TYPE.get(age_neighbor_label)
    if api_neighbor_type is None:
        return None
    row["entity_type"] = api_neighbor_type

    # AGE returns quoted strings for properties in agtype objects.
    if isinstance(row.get("entity_id"), str):
        row["entity_id"] = row["entity_id"].strip('"')
    if isinstance(row.get("name"), str):
        row["name"] = row["name"].strip('"')
    return row


def _graph_neighbor_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Stable ordering key for deterministic API responses."""
    return (
        str(row.get("direction") or ""),
        str(row.get("relationship_type") or ""),
        str(row.get("entity_type") or ""),
        str(row.get("name") or ""),
        str(row.get("entity_id") or ""),
    )


def _fetch_graph_neighbors_for_direction(
    conn: psycopg.Connection,
    *,
    age_label: str,
    safe_id: str,
    direction: str,
) -> list[object]:
    """Fetch graph neighbors in a single direction (outbound or inbound)."""
    from core.graph import query_formatted_cypher

    edge_pattern = "-[e]->" if direction == "outbound" else "<-[e]-"
    return query_formatted_cypher(
        conn,
        f"""
            MATCH (n:{age_label} {{id: "%s"}}){edge_pattern}(m)
            RETURN {{
                entity_type: label(m),
                entity_id: m.id,
                name: m.canonical_name,
                relationship_type: type(e),
                direction: "{direction}"
            }}
        """,
        safe_id,
    )


def fetch_entity_relationships(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
) -> list[dict[str, Any]]:
    """Fetch graph neighbors for an entity, returning dicts compatible with GraphNeighbor."""
    from core.graph import _escape_cypher_literal

    entity_spec = GRAPH_ENTITY_TYPE_SPECS.get(entity_type)
    if entity_spec is None:
        raise ValueError(f"entity_type must be one of {sorted(GRAPH_ENTITY_TYPE_TO_AGE_LABEL)}, got {entity_type!r}")
    if not _graph_entity_exists(conn, entity_type=entity_type, entity_id=entity_id):
        raise LookupError(f"{entity_type} not found for id={entity_id}")

    age_label = entity_spec.age_label
    safe_id = _escape_cypher_literal(str(entity_id))

    outbound_results = _fetch_graph_neighbors_for_direction(
        conn,
        age_label=age_label,
        safe_id=safe_id,
        direction="outbound",
    )
    inbound_results = _fetch_graph_neighbors_for_direction(
        conn,
        age_label=age_label,
        safe_id=safe_id,
        direction="inbound",
    )

    neighbors = [
        neighbor
        for raw in outbound_results + inbound_results
        if (neighbor := _normalize_graph_neighbor(raw)) is not None
    ]
    return sorted(neighbors, key=_graph_neighbor_sort_key)
