from __future__ import annotations

from uuid import UUID

import psycopg

from core.graph import _escape_cypher_literal, _execute_formatted_cypher


def create_graph_node(
    conn: psycopg.Connection,
    *,
    label: str,
    node_id: UUID,
    canonical_name: str,
) -> None:
    """Create or update a named graph node for contract tests."""
    safe_node_id = _escape_cypher_literal(str(node_id))
    safe_name = _escape_cypher_literal(canonical_name)
    _execute_formatted_cypher(
        conn,
        f"""
            MERGE (n:{label} {{id: "%s"}})
            SET n.canonical_name = "%s"
        """,
        safe_node_id,
        safe_name,
    )


def create_graph_edge(
    conn: psycopg.Connection,
    *,
    source_label: str,
    source_id: UUID,
    target_label: str,
    target_id: UUID,
    edge_type: str,
) -> None:
    """Create a directed edge between two pre-existing graph nodes."""
    safe_source = _escape_cypher_literal(str(source_id))
    safe_target = _escape_cypher_literal(str(target_id))
    _execute_formatted_cypher(
        conn,
        f"""
            MATCH (s:{source_label} {{id: "%s"}}), (t:{target_label} {{id: "%s"}})
            CREATE (s)-[:{edge_type}]->(t)
        """,
        safe_source,
        safe_target,
    )
