from __future__ import annotations

from uuid import uuid4

import pytest

from core.db import get_connection
from core.graph import age_post_connect, delete_entity_nodes, ensure_graph, query_formatted_cypher
from core.graph.loader import create_contributed_to_edge, merge_organization_node, merge_person_node


@pytest.mark.integration
class TestAgePostConnect:
    def test_cypher_succeeds_with_hook(self):
        conn = get_connection(post_connect=age_post_connect)
        try:
            ensure_graph(conn)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM cypher('civibus', $$ RETURN 1 $$) AS (v agtype)")
                row = cur.fetchone()
            assert row is not None
        finally:
            conn.rollback()
            conn.close()

    def test_cypher_fails_without_hook(self):
        conn = get_connection()
        try:
            with pytest.raises(Exception):
                conn.execute("SELECT * FROM cypher('civibus', $$ RETURN 1 $$) AS (v agtype)")
        finally:
            conn.rollback()
            conn.close()


@pytest.mark.integration
class TestEnsureGraph:
    def test_creates_graph_when_absent(self):
        conn = get_connection(post_connect=age_post_connect)
        try:
            ensure_graph(conn)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus'")
                assert cur.fetchone() is not None
        finally:
            conn.rollback()
            conn.close()

    def test_idempotent_on_repeat_call(self):
        conn = get_connection(post_connect=age_post_connect)
        try:
            ensure_graph(conn)
            conn.commit()
            # Second call should not raise
            ensure_graph(conn)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus'")
                assert cur.fetchone() is not None
        finally:
            conn.rollback()
            conn.close()


@pytest.mark.integration
class TestQueryFormattedCypher:
    def test_returns_matching_node(self, graph_conn):
        person_id = uuid4()
        merge_person_node(graph_conn, person_id, "Query Test Person")

        results = query_formatted_cypher(
            graph_conn,
            """
                MATCH (p:Person {id: "%s"})
                RETURN p.id
            """,
            str(person_id),
        )

        assert len(results) == 1
        assert str(results[0]).strip('"') == str(person_id)

    def test_returns_empty_for_no_match(self, graph_conn):
        fake_id = uuid4()

        results = query_formatted_cypher(
            graph_conn,
            """
                MATCH (p:Person {id: "%s"})
                RETURN p.id
            """,
            str(fake_id),
        )

        assert results == []

    def test_zero_arg_static_cypher(self, graph_conn):
        results = query_formatted_cypher(
            graph_conn,
            """
                RETURN 1
            """,
        )

        assert len(results) == 1


@pytest.mark.integration
def test_delete_entity_nodes_detaches_edges_and_preserves_unselected_nodes(graph_conn):
    person_id = uuid4()
    organization_id = uuid4()
    source_record_id = uuid4()
    merge_person_node(graph_conn, person_id, "Deleted Graph Person")
    merge_organization_node(graph_conn, organization_id, "Preserved Graph Organization")
    create_contributed_to_edge(
        graph_conn,
        person_id,
        organization_id,
        amount=25.0,
        transaction_date="2026-08-16",
        source_record_id=source_record_id,
    )

    delete_entity_nodes(graph_conn, [person_id])

    assert query_formatted_cypher(graph_conn, 'MATCH (n {id: "%s"}) RETURN n.id', str(person_id)) == []
    assert (
        len(
            query_formatted_cypher(
                graph_conn,
                'MATCH (n {id: "%s"}) RETURN n.id',
                str(organization_id),
            )
        )
        == 1
    )
    assert (
        query_formatted_cypher(
            graph_conn,
            'MATCH ()-[edge]->() WHERE edge.source_record_id = "%s" RETURN edge',
            str(source_record_id),
        )
        == []
    )
