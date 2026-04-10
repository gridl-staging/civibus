from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.entity_resolution.clustering import cluster_scored_pairs
from core.entity_resolution.confidence import classify_scored_pairs
from core.entity_resolution.graph_edges import materialize_er_edges
from core.entity_resolution.persist import (
    persist_auto_merge_clusters,
    persist_match_decisions,
)
from core.entity_resolution.test_persist import _create_org, _create_person
from core.graph.loader import merge_organization_node, merge_person_node

pytestmark = pytest.mark.integration


def _setup_person_nodes(conn: psycopg.Connection, people: dict[UUID, str]) -> None:
    for entity_id, name in people.items():
        _create_person(conn, person_id=entity_id, name=name)
        merge_person_node(conn, entity_id, name)


def _fetch_active_matches(conn: psycopg.Connection) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id_a, entity_id_b, decision, decided_by, decision_method, match_evidence
            FROM core.active_matches
            WHERE entity_type = 'person'
            ORDER BY entity_id_a, entity_id_b
            """
        )
        return cursor.fetchall()


def _fetch_person_cluster_assignments(
    conn: psycopg.Connection,
    *,
    entity_ids: tuple[UUID, ...],
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id
            FROM core.person
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (list(entity_ids),),
        )
        return cursor.fetchall()


def _fetch_active_cluster_rows(conn: psycopg.Connection) -> list[tuple[UUID, UUID, bool]]:
    return conn.execute(
        """
        SELECT cluster_id, entity_id, is_canonical
        FROM core.cluster_member
        WHERE entity_type = 'person'
          AND split_at IS NULL
        ORDER BY entity_id
        """
    ).fetchall()


def _edge_count(
    conn: psycopg.Connection,
    *,
    node_label: str,
    edge_label: str,
    entity_id_a: UUID,
    entity_id_b: UUID,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (a:%s {id: "%s"})-[e:%s]->(b:%s {id: "%s"})
                RETURN e
            $$) AS (v agtype)
            """
            % (node_label, str(entity_id_a), edge_label, node_label, str(entity_id_b))
        )
        return cursor.fetchone()[0]


def _edge_properties(
    conn: psycopg.Connection,
    *,
    node_label: str,
    edge_label: str,
    entity_id_a: UUID,
    entity_id_b: UUID,
) -> tuple[str, float, str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM cypher('civibus', $$
                MATCH (a:%s {id: "%s"})-[e:%s]->(b:%s {id: "%s"})
                RETURN e.decision, e.confidence, e.entity_id_a, e.entity_id_b
            $$) AS (decision agtype, confidence agtype, entity_id_a agtype, entity_id_b agtype)
            """
            % (node_label, str(entity_id_a), edge_label, node_label, str(entity_id_b))
        )
        row = cursor.fetchone()

    assert row is not None
    return (
        str(row[0]).strip('"'),
        float(str(row[1])),
        str(row[2]).strip('"'),
        str(row[3]).strip('"'),
    )


def test_materialize_er_edges_creates_expected_labels_and_properties_for_person_pairs(
    graph_conn: psycopg.Connection,
) -> None:
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
    _create_person(graph_conn, person_id=a, name="Edge A")
    _create_person(graph_conn, person_id=b, name="Edge B")
    _create_person(graph_conn, person_id=c, name="Edge C")
    _create_person(graph_conn, person_id=d, name="Edge D")
    merge_person_node(graph_conn, a, "Edge A")
    merge_person_node(graph_conn, b, "Edge B")
    merge_person_node(graph_conn, c, "Edge C")
    merge_person_node(graph_conn, d, "Edge D")

    classified_pairs = [
        {
            "entity_id_a": min(a, b),
            "entity_id_b": max(a, b),
            "confidence": 0.88,
            "decision": "probable_match",
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
        {
            "entity_id_a": min(c, d),
            "entity_id_b": max(c, d),
            "confidence": 0.70,
            "decision": "possible_match",
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
        {
            "entity_id_a": min(a, c),
            "entity_id_b": max(a, c),
            "confidence": 0.99,
            "decision": "match",
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
        },
        {
            "entity_id_a": min(b, d),
            "entity_id_b": max(b, d),
            "confidence": 0.25,
            "decision": "no_match",
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
    ]

    materialize_er_edges(graph_conn, classified_pairs, "person")

    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 1
    )
    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="POSSIBLE_MATCH",
            entity_id_a=min(c, d),
            entity_id_b=max(c, d),
        )
        == 1
    )
    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(a, c),
            entity_id_b=max(a, c),
        )
        == 0
    )
    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="POSSIBLE_MATCH",
            entity_id_a=min(b, d),
            entity_id_b=max(b, d),
        )
        == 0
    )

    decision, confidence, entity_id_a, entity_id_b = _edge_properties(
        graph_conn,
        node_label="Person",
        edge_label="SAME_AS",
        entity_id_a=min(a, b),
        entity_id_b=max(a, b),
    )
    assert decision == "probable_match"
    assert confidence == pytest.approx(0.88)
    assert entity_id_a == str(min(a, b))
    assert entity_id_b == str(max(a, b))


def test_materialize_er_edges_is_idempotent_and_updates_edge_properties_on_rerun(
    graph_conn: psycopg.Connection,
) -> None:
    a, b = uuid4(), uuid4()
    _create_person(graph_conn, person_id=a, name="Rerun Edge A")
    _create_person(graph_conn, person_id=b, name="Rerun Edge B")
    merge_person_node(graph_conn, a, "Rerun Edge A")
    merge_person_node(graph_conn, b, "Rerun Edge B")

    pair = {
        "entity_id_a": min(a, b),
        "entity_id_b": max(a, b),
        "confidence": 0.81,
        "decision": "probable_match",
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }

    materialize_er_edges(graph_conn, [pair], "person")
    pair["confidence"] = 0.93
    materialize_er_edges(graph_conn, [pair], "person")

    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 1
    )

    decision, confidence, _, _ = _edge_properties(
        graph_conn,
        node_label="Person",
        edge_label="SAME_AS",
        entity_id_a=min(a, b),
        entity_id_b=max(a, b),
    )
    assert decision == "probable_match"
    assert confidence == pytest.approx(0.93)


def test_materialize_er_edges_removes_stale_uncertain_edge_when_pair_becomes_match(
    graph_conn: psycopg.Connection,
) -> None:
    a, b = uuid4(), uuid4()
    _create_person(graph_conn, person_id=a, name="Transition Match A")
    _create_person(graph_conn, person_id=b, name="Transition Match B")
    merge_person_node(graph_conn, a, "Transition Match A")
    merge_person_node(graph_conn, b, "Transition Match B")

    pair = {
        "entity_id_a": min(a, b),
        "entity_id_b": max(a, b),
        "confidence": 0.68,
        "decision": "possible_match",
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }

    materialize_er_edges(graph_conn, [pair], "person")
    pair["confidence"] = 0.99
    pair["decision"] = "match"
    pair["decision_method"] = "deterministic"
    pair["decided_by"] = "deterministic_fec_id_match"
    materialize_er_edges(graph_conn, [pair], "person")

    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="POSSIBLE_MATCH",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 0
    )
    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 0
    )


def test_materialize_er_edges_replaces_uncertain_label_when_decision_tier_changes(
    graph_conn: psycopg.Connection,
) -> None:
    a, b = uuid4(), uuid4()
    _create_person(graph_conn, person_id=a, name="Transition Tier A")
    _create_person(graph_conn, person_id=b, name="Transition Tier B")
    merge_person_node(graph_conn, a, "Transition Tier A")
    merge_person_node(graph_conn, b, "Transition Tier B")

    pair = {
        "entity_id_a": min(a, b),
        "entity_id_b": max(a, b),
        "confidence": 0.66,
        "decision": "possible_match",
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }

    materialize_er_edges(graph_conn, [pair], "person")
    pair["confidence"] = 0.88
    pair["decision"] = "probable_match"
    materialize_er_edges(graph_conn, [pair], "person")

    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="POSSIBLE_MATCH",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 0
    )
    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 1
    )

    decision, confidence, _, _ = _edge_properties(
        graph_conn,
        node_label="Person",
        edge_label="SAME_AS",
        entity_id_a=min(a, b),
        entity_id_b=max(a, b),
    )
    assert decision == "probable_match"
    assert confidence == pytest.approx(0.88)


def test_materialize_er_edges_removes_stale_uncertain_edge_when_probable_pair_becomes_no_match(
    graph_conn: psycopg.Connection,
) -> None:
    a, b = uuid4(), uuid4()
    _create_person(graph_conn, person_id=a, name="Transition No Match A")
    _create_person(graph_conn, person_id=b, name="Transition No Match B")
    merge_person_node(graph_conn, a, "Transition No Match A")
    merge_person_node(graph_conn, b, "Transition No Match B")

    pair = {
        "entity_id_a": min(a, b),
        "entity_id_b": max(a, b),
        "confidence": 0.84,
        "decision": "probable_match",
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }

    materialize_er_edges(graph_conn, [pair], "person")
    pair["confidence"] = 0.33
    pair["decision"] = "no_match"
    materialize_er_edges(graph_conn, [pair], "person")

    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 0
    )
    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="POSSIBLE_MATCH",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 0
    )


def test_materialize_er_edges_supports_organization_nodes(
    graph_conn: psycopg.Connection,
) -> None:
    a, b = uuid4(), uuid4()
    _create_org(graph_conn, organization_id=a, name="Org Edge A")
    _create_org(graph_conn, organization_id=b, name="Org Edge B")
    merge_organization_node(graph_conn, a, "Org Edge A")
    merge_organization_node(graph_conn, b, "Org Edge B")

    materialize_er_edges(
        graph_conn,
        [
            {
                "entity_id_a": min(a, b),
                "entity_id_b": max(a, b),
                "confidence": 0.67,
                "decision": "possible_match",
                "decision_method": "probabilistic",
                "decided_by": "splink_v1",
            }
        ],
        "organization",
    )

    assert (
        _edge_count(
            graph_conn,
            node_label="Organization",
            edge_label="POSSIBLE_MATCH",
            entity_id_a=min(a, b),
            entity_id_b=max(a, b),
        )
        == 1
    )


@pytest.mark.parametrize(
    "unsupported_entity_type",
    ["office", "electoral_division", "contest", "candidacy", "officeholding"],
)
def test_materialize_er_edges_rejects_civic_entity_types(unsupported_entity_type: str) -> None:
    with pytest.raises(
        ValueError,
        match=rf"entity_type must be 'person' or 'organization', got '{unsupported_entity_type}'",
    ):
        materialize_er_edges(object(), [], unsupported_entity_type)


def test_stage4_pipeline_persists_decisions_clusters_and_edges_end_to_end(
    graph_conn: psycopg.Connection,
) -> None:
    a, b, c, d, e = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    _setup_person_nodes(
        graph_conn,
        {
            a: "Pipeline A",
            b: "Pipeline B",
            c: "Pipeline C",
            d: "Pipeline D",
            e: "Pipeline E",
        },
    )

    scored_pairs = [
        {
            "entity_id_a": min(a, b),
            "entity_id_b": max(a, b),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_fec_id_match",
            "matched_rule_names": ["deterministic_fec_id_match"],
        },
        {
            "entity_id_a": min(b, c),
            "entity_id_b": max(b, c),
            "confidence": 1.0,
            "decision_method": "deterministic",
            "decided_by": "deterministic_voter_reg_match",
            "matched_rule_names": ["deterministic_voter_reg_match"],
        },
        {
            "entity_id_a": min(d, e),
            "entity_id_b": max(d, e),
            "confidence": 0.87,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        },
    ]
    entity_rows = [
        {"id": a, "canonical_name": "Pipeline A", "first_name": "Pipeline", "last_name": "A"},
        {"id": b, "canonical_name": "Pipeline B", "first_name": "Pipeline", "last_name": "B"},
        {"id": c, "canonical_name": "Pipeline C", "first_name": "Pipeline", "last_name": None},
        {"id": d, "canonical_name": "Pipeline D", "first_name": "Pipeline", "last_name": "D"},
        {"id": e, "canonical_name": "Pipeline E", "first_name": "Pipeline", "last_name": "E"},
    ]

    classified_pairs = classify_scored_pairs(scored_pairs)
    clustered = cluster_scored_pairs(classified_pairs, entity_rows)

    persist_match_decisions(graph_conn, clustered["pairwise_decisions"], "person")
    persist_auto_merge_clusters(graph_conn, clustered["auto_merge_clusters"], "person")
    materialize_er_edges(graph_conn, clustered["pairwise_decisions"], "person")

    active_matches = _fetch_active_matches(graph_conn)
    assert len(active_matches) == 3
    decisions = {(row["entity_id_a"], row["entity_id_b"]): row["decision"] for row in active_matches}
    assert decisions[min(a, b), max(a, b)] == "match"
    assert decisions[min(b, c), max(b, c)] == "match"
    assert decisions[min(d, e), max(d, e)] == "probable_match"

    deterministic = [row for row in active_matches if row["decision_method"] == "deterministic"]
    assert len(deterministic) == 2
    assert deterministic[0]["match_evidence"]["matched_rule_names"] is not None

    cluster_rows = _fetch_active_cluster_rows(graph_conn)
    assert len(cluster_rows) == 3
    cluster_ids = {row[0] for row in cluster_rows}
    assert len(cluster_ids) == 1
    canonical_entity_id = next(row[1] for row in cluster_rows if row[2] is True)
    expected_canonical = clustered["auto_merge_clusters"][0]["canonical_entity_id"]
    assert canonical_entity_id == expected_canonical

    people = _fetch_person_cluster_assignments(
        graph_conn,
        entity_ids=(a, b, c, d, e),
    )
    assigned_cluster_id = next(row["er_cluster_id"] for row in people if row["id"] == a)
    assert assigned_cluster_id is not None
    for row in people:
        if row["id"] in {a, b, c}:
            assert row["er_cluster_id"] == assigned_cluster_id
        else:
            assert row["er_cluster_id"] is None

    assert (
        _edge_count(
            graph_conn,
            node_label="Person",
            edge_label="SAME_AS",
            entity_id_a=min(d, e),
            entity_id_b=max(d, e),
        )
        == 1
    )
