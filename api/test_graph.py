from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from api.models import (
    AGE_LABEL_TO_NEIGHBOR_TYPE,
    EntityRelationshipsResponse,
    GRAPH_ENTITY_TYPE_TO_AGE_LABEL,
    GRAPH_ENTITY_TYPE_TO_RELATIONAL_ENTITY_TYPE,
    GraphNeighbor,
)
from api.test_graph_support import create_graph_edge, create_graph_node
from core.graph.loader import (
    merge_candidate_node,
    merge_committee_node,
    merge_filing_node,
    merge_office_node,
    merge_officeholding_node,
    merge_organization_node,
    merge_person_node,
)


@pytest.mark.integration
class TestGraphRelationshipsRoute:
    """Integration tests for GET /v1/graph/{entity_type}/{entity_id}/relationships."""

    def test_returns_neighbors_for_person(self, graph_conn, graph_api_client):
        person_id = uuid4()
        committee_id = uuid4()
        same_as_id = uuid4()
        possible_match_id = uuid4()
        merge_person_node(graph_conn, person_id, "Route Test Person")
        merge_committee_node(graph_conn, committee_id, "Route Test PAC")
        merge_person_node(graph_conn, same_as_id, "Route SameAs Person")
        merge_person_node(graph_conn, possible_match_id, "Route PossibleMatch Person")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Person",
            target_id=same_as_id,
            edge_type="SAME_AS",
        )
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Person",
            target_id=possible_match_id,
            edge_type="POSSIBLE_MATCH",
        )

        resp = graph_api_client.get(f"/v1/graph/person/{person_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "person"
        assert body["entity_id"] == str(person_id)
        assert body["total_count"] == 3
        assert {neighbor["relationship_type"] for neighbor in body["neighbors"]} == {
            "CONTRIBUTED_TO",
            "SAME_AS",
            "POSSIBLE_MATCH",
        }
        assert all(neighbor["direction"] == "outbound" for neighbor in body["neighbors"])

    def test_returns_neighbors_for_org(self, graph_conn, graph_api_client):
        org_id = uuid4()
        committee_id = uuid4()
        merge_organization_node(graph_conn, org_id, "Route Test Org")
        merge_committee_node(graph_conn, committee_id, "Route Org PAC")
        create_graph_edge(
            graph_conn,
            source_label="Organization",
            source_id=org_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="SPENT_ON",
        )

        resp = graph_api_client.get(f"/v1/graph/org/{org_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "org"
        assert body["entity_id"] == str(org_id)
        assert body["total_count"] == 1
        assert body["neighbors"][0]["entity_type"] == "committee"
        assert body["neighbors"][0]["relationship_type"] == "SPENT_ON"

    def test_returns_neighbors_for_committee(self, graph_conn, graph_api_client):
        committee_id = uuid4()
        filing_id = uuid4()
        merge_committee_node(graph_conn, committee_id, "Route Test Committee")
        merge_filing_node(graph_conn, filing_id, "Route Test Filing")
        create_graph_edge(
            graph_conn,
            source_label="Committee",
            source_id=committee_id,
            target_label="Filing",
            target_id=filing_id,
            edge_type="FILED",
        )

        resp = graph_api_client.get(f"/v1/graph/committee/{committee_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "committee"
        assert body["entity_id"] == str(committee_id)
        assert body["total_count"] == 1
        assert body["neighbors"][0]["entity_type"] == "filing"
        assert body["neighbors"][0]["relationship_type"] == "FILED"

    def test_returns_neighbors_for_candidate(self, graph_conn, graph_api_client):
        candidate_id = uuid4()
        committee_id = uuid4()
        merge_candidate_node(graph_conn, candidate_id, "Route Test Candidate")
        merge_committee_node(graph_conn, committee_id, "Route Candidate Committee")
        create_graph_edge(
            graph_conn,
            source_label="Candidate",
            source_id=candidate_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="AFFILIATED_WITH",
        )

        resp = graph_api_client.get(f"/v1/graph/candidate/{candidate_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "candidate"
        assert body["entity_id"] == str(candidate_id)
        assert body["total_count"] == 1
        assert body["neighbors"][0]["entity_type"] == "committee"
        assert body["neighbors"][0]["relationship_type"] == "AFFILIATED_WITH"

    def test_returns_neighbors_for_office(self, graph_conn, graph_api_client):
        office_id = uuid4()
        person_id = uuid4()
        merge_office_node(graph_conn, office_id, "US Senate")
        merge_person_node(graph_conn, person_id, "Route Office Holder")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Office",
            target_id=office_id,
            edge_type="HOLDS",
        )

        resp = graph_api_client.get(f"/v1/graph/office/{office_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "office"
        assert body["entity_id"] == str(office_id)
        assert body["total_count"] == 1
        assert body["neighbors"][0]["entity_type"] == "person"
        assert body["neighbors"][0]["relationship_type"] == "HOLDS"
        assert body["neighbors"][0]["direction"] == "inbound"

    def test_returns_empty_neighbors_for_isolated_officeholding(self, graph_conn, graph_api_client):
        officeholding_id = uuid4()
        merge_officeholding_node(graph_conn, officeholding_id, "Route Office Holder holds US Senate")

        resp = graph_api_client.get(f"/v1/graph/officeholding/{officeholding_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "officeholding"
        assert body["entity_id"] == str(officeholding_id)
        assert body["neighbors"] == []
        assert body["total_count"] == 0

    def test_filters_out_of_scope_graph_nodes_and_edges(self, graph_conn, graph_api_client):
        person_id = uuid4()
        committee_id = uuid4()
        parcel_id = uuid4()
        merge_person_node(graph_conn, person_id, "Boundary Route Person")
        merge_committee_node(graph_conn, committee_id, "Boundary Route PAC")
        create_graph_node(
            graph_conn,
            label="Parcel",
            node_id=parcel_id,
            canonical_name="Boundary Route Parcel",
        )
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Parcel",
            target_id=parcel_id,
            edge_type="OWNS",
        )

        resp = graph_api_client.get(f"/v1/graph/person/{person_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["neighbors"][0]["entity_type"] == "committee"
        assert body["neighbors"][0]["relationship_type"] == "CONTRIBUTED_TO"

    def test_returns_empty_neighbors_for_isolated_node(self, graph_conn, graph_api_client):
        person_id = uuid4()
        merge_person_node(graph_conn, person_id, "Isolated Route Person")

        resp = graph_api_client.get(f"/v1/graph/person/{person_id}/relationships")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == "person"
        assert body["entity_id"] == str(person_id)
        assert body["neighbors"] == []
        assert body["total_count"] == 0

    @pytest.mark.parametrize(
        "entity_type",
        [
            "person",
            "org",
            "committee",
            "candidate",
            "office",
            "electoral_division",
            "contest",
            "candidacy",
            "officeholding",
        ],
    )
    def test_returns_404_for_nonexistent_entity(self, graph_api_client, entity_type):
        fake_id = uuid4()

        resp = graph_api_client.get(f"/v1/graph/{entity_type}/{fake_id}/relationships")

        assert resp.status_code == 404

    def test_rejects_invalid_entity_type(self, graph_api_client):
        fake_id = uuid4()

        resp = graph_api_client.get(f"/v1/graph/filing/{fake_id}/relationships")

        assert resp.status_code == 422

    def test_rejects_invalid_uuid(self, graph_api_client):
        resp = graph_api_client.get("/v1/graph/person/not-a-uuid/relationships")

        assert resp.status_code == 422

    def test_response_matches_entity_relationships_schema(self, graph_conn, graph_api_client):
        """Response body must validate against EntityRelationshipsResponse."""
        person_id = uuid4()
        committee_id = uuid4()
        merge_person_node(graph_conn, person_id, "Schema Test Person")
        merge_committee_node(graph_conn, committee_id, "Schema Test PAC")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )

        resp = graph_api_client.get(f"/v1/graph/person/{person_id}/relationships")

        assert resp.status_code == 200
        # Must parse without ValidationError.
        validated = EntityRelationshipsResponse.model_validate(resp.json())
        assert validated.entity_type == "person"
        assert len(validated.neighbors) == 1


def test_graph_entity_type_mapping_covers_all_api_types() -> None:
    expected_api_types = {
        "person",
        "org",
        "committee",
        "candidate",
        "office",
        "electoral_division",
        "contest",
        "candidacy",
        "officeholding",
    }
    assert set(GRAPH_ENTITY_TYPE_TO_AGE_LABEL.keys()) == expected_api_types
    assert set(GRAPH_ENTITY_TYPE_TO_RELATIONAL_ENTITY_TYPE.keys()) == expected_api_types

    for api_name, age_label in GRAPH_ENTITY_TYPE_TO_AGE_LABEL.items():
        assert AGE_LABEL_TO_NEIGHBOR_TYPE[age_label] == api_name


def test_graph_entity_type_mapping_includes_relational_entity_names() -> None:
    assert GRAPH_ENTITY_TYPE_TO_RELATIONAL_ENTITY_TYPE == {
        "person": "person",
        "org": "organization",
        "committee": "committee",
        "candidate": "candidate",
        "office": "office",
        "electoral_division": "electoral_division",
        "contest": "contest",
        "candidacy": "candidacy",
        "officeholding": "officeholding",
    }


def test_age_label_to_neighbor_type_includes_non_route_labels() -> None:
    assert "Filing" in AGE_LABEL_TO_NEIGHBOR_TYPE
    assert AGE_LABEL_TO_NEIGHBOR_TYPE["Filing"] == "filing"


def test_graph_neighbor_serializes_and_round_trips() -> None:
    neighbor_id = uuid4()
    neighbor = GraphNeighbor.model_validate(
        {
            "entity_type": "committee",
            "entity_id": neighbor_id,
            "name": "Civibus PAC",
            "relationship_type": "CONTRIBUTED_TO",
            "direction": "outbound",
        }
    )

    dumped = neighbor.model_dump(mode="json")

    assert dumped["entity_type"] == "committee"
    assert dumped["entity_id"] == str(neighbor_id)
    assert dumped["name"] == "Civibus PAC"
    assert dumped["relationship_type"] == "CONTRIBUTED_TO"
    assert dumped["direction"] == "outbound"
    assert GraphNeighbor.model_validate(dumped).model_dump(mode="json") == dumped


def test_graph_neighbor_name_is_optional() -> None:
    neighbor = GraphNeighbor.model_validate(
        {
            "entity_type": "person",
            "entity_id": str(uuid4()),
            "relationship_type": "SAME_AS",
            "direction": "inbound",
        }
    )
    assert neighbor.name is None


def test_graph_neighbor_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GraphNeighbor.model_validate(
            {
                "entity_type": "person",
                "entity_id": str(uuid4()),
                "relationship_type": "SAME_AS",
                "direction": "both",
            }
        )
    assert "direction" in str(exc_info.value)


def test_entity_relationships_response_serializes_and_round_trips() -> None:
    entity_id = uuid4()
    neighbor_id = uuid4()
    response = EntityRelationshipsResponse.model_validate(
        {
            "entity_type": "person",
            "entity_id": entity_id,
            "neighbors": [
                {
                    "entity_type": "committee",
                    "entity_id": neighbor_id,
                    "name": "Civibus PAC",
                    "relationship_type": "CONTRIBUTED_TO",
                    "direction": "outbound",
                }
            ],
            "total_count": 1,
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["entity_type"] == "person"
    assert dumped["entity_id"] == str(entity_id)
    assert len(dumped["neighbors"]) == 1
    assert dumped["total_count"] == 1
    assert EntityRelationshipsResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_entity_relationships_response_defaults_to_empty() -> None:
    response = EntityRelationshipsResponse.model_validate({"entity_type": "org", "entity_id": str(uuid4())})
    assert response.neighbors == []
    assert response.total_count == 0


def test_entity_relationships_response_rejects_invalid_entity_type() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EntityRelationshipsResponse.model_validate({"entity_type": "filing", "entity_id": str(uuid4())})
    assert "entity_type" in str(exc_info.value)
