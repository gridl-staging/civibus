from __future__ import annotations

from uuid import uuid4

import pytest

from api.queries_graph import fetch_entity_relationships
from api.test_graph_support import create_graph_edge, create_graph_node
from core.graph.loader import (
    merge_candidacy_node,
    merge_candidate_node,
    merge_committee_node,
    merge_contest_node,
    merge_electoral_division_node,
    merge_filing_node,
    merge_office_node,
    merge_officeholding_node,
    merge_organization_node,
    merge_person_node,
)


@pytest.mark.integration
class TestFetchEntityRelationships:
    """Integration tests for the graph query helper that retrieves an entity's neighbors."""

    def test_returns_outbound_neighbor(self, graph_conn):
        person_id = uuid4()
        committee_id = uuid4()
        merge_person_node(graph_conn, person_id, "Alice Smith")
        merge_committee_node(graph_conn, committee_id, "Smith PAC")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )

        results = fetch_entity_relationships(graph_conn, "person", person_id)

        assert len(results) == 1
        neighbor = results[0]
        assert neighbor["entity_type"] == "committee"
        assert neighbor["entity_id"] == str(committee_id)
        assert neighbor["name"] == "Smith PAC"
        assert neighbor["relationship_type"] == "CONTRIBUTED_TO"
        assert neighbor["direction"] == "outbound"

    def test_returns_inbound_neighbor(self, graph_conn):
        person_id = uuid4()
        committee_id = uuid4()
        merge_person_node(graph_conn, person_id, "Bob Jones")
        merge_committee_node(graph_conn, committee_id, "Jones PAC")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )

        # Query from the committee's perspective — person should be inbound.
        results = fetch_entity_relationships(graph_conn, "committee", committee_id)

        assert len(results) == 1
        neighbor = results[0]
        assert neighbor["entity_type"] == "person"
        assert neighbor["entity_id"] == str(person_id)
        assert neighbor["name"] == "Bob Jones"
        assert neighbor["relationship_type"] == "CONTRIBUTED_TO"
        assert neighbor["direction"] == "inbound"

    def test_returns_both_directions(self, graph_conn):
        """A node with both inbound and outbound edges returns neighbors for each."""
        person_id = uuid4()
        committee_id = uuid4()
        candidate_id = uuid4()
        merge_person_node(graph_conn, person_id, "Carol Lee")
        merge_committee_node(graph_conn, committee_id, "Lee PAC")
        merge_candidate_node(graph_conn, candidate_id, "Carol Lee Candidate")
        # person → committee (outbound from committee is inbound)
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )
        # candidate → committee (outbound from committee is also inbound)
        create_graph_edge(
            graph_conn,
            source_label="Candidate",
            source_id=candidate_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="AFFILIATED_WITH",
        )

        results = fetch_entity_relationships(graph_conn, "committee", committee_id)

        assert len(results) == 2
        types = {r["entity_type"] for r in results}
        assert types == {"person", "candidate"}
        # Both are inbound to the committee.
        assert all(r["direction"] == "inbound" for r in results)

    def test_translates_organization_label_to_org(self, graph_conn):
        """AGE 'Organization' label must map to API-friendly 'org' in results."""
        org_id = uuid4()
        committee_id = uuid4()
        merge_organization_node(graph_conn, org_id, "Acme Corp")
        merge_committee_node(graph_conn, committee_id, "Acme PAC")
        create_graph_edge(
            graph_conn,
            source_label="Organization",
            source_id=org_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )

        results = fetch_entity_relationships(graph_conn, "committee", committee_id)

        assert len(results) == 1
        assert results[0]["entity_type"] == "org"

    def test_ignores_out_of_scope_graph_nodes_and_edges(self, graph_conn):
        person_id = uuid4()
        committee_id = uuid4()
        parcel_id = uuid4()
        merge_person_node(graph_conn, person_id, "Boundary Person")
        merge_committee_node(graph_conn, committee_id, "Boundary PAC")
        create_graph_node(
            graph_conn,
            label="Parcel",
            node_id=parcel_id,
            canonical_name="Boundary Parcel",
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

        results = fetch_entity_relationships(graph_conn, "person", person_id)

        assert len(results) == 1
        assert results[0]["entity_type"] == "committee"
        assert results[0]["relationship_type"] == "CONTRIBUTED_TO"

    def test_returns_empty_for_isolated_node(self, graph_conn):
        person_id = uuid4()
        merge_person_node(graph_conn, person_id, "Isolated Person")

        results = fetch_entity_relationships(graph_conn, "person", person_id)

        assert results == []

    def test_returns_empty_for_nonexistent_entity(self, graph_conn):
        fake_id = uuid4()

        with pytest.raises(LookupError, match="person"):
            fetch_entity_relationships(graph_conn, "person", fake_id)

    def test_returns_stable_ordering(self, graph_conn):
        committee_id = uuid4()
        person_id = uuid4()
        candidate_id = uuid4()
        filing_id = uuid4()
        merge_committee_node(graph_conn, committee_id, "Ordering PAC")
        merge_person_node(graph_conn, person_id, "Ordering Person")
        merge_candidate_node(graph_conn, candidate_id, "Ordering Candidate")
        merge_filing_node(graph_conn, filing_id, "Ordering Filing")
        create_graph_edge(
            graph_conn,
            source_label="Committee",
            source_id=committee_id,
            target_label="Filing",
            target_id=filing_id,
            edge_type="FILED",
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
            source_label="Candidate",
            source_id=candidate_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="AFFILIATED_WITH",
        )

        results = fetch_entity_relationships(graph_conn, "committee", committee_id)

        assert [neighbor["direction"] for neighbor in results] == ["inbound", "inbound", "outbound"]
        assert [neighbor["relationship_type"] for neighbor in results] == [
            "AFFILIATED_WITH",
            "CONTRIBUTED_TO",
            "FILED",
        ]

    def test_returns_holds_neighbor_for_office_entity(self, graph_conn):
        office_id = uuid4()
        person_id = uuid4()
        merge_office_node(graph_conn, office_id, "US House")
        merge_person_node(graph_conn, person_id, "Officeholder Person")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Office",
            target_id=office_id,
            edge_type="HOLDS",
        )

        results = fetch_entity_relationships(graph_conn, "office", office_id)

        assert len(results) == 1
        assert results[0]["entity_type"] == "person"
        assert results[0]["entity_id"] == str(person_id)
        assert results[0]["name"] == "Officeholder Person"
        assert results[0]["relationship_type"] == "HOLDS"
        assert results[0]["direction"] == "inbound"

    def test_returns_runs_in_neighbor_for_contest_entity(self, graph_conn):
        contest_id = uuid4()
        candidacy_id = uuid4()
        merge_contest_node(graph_conn, contest_id, "NC-01 General")
        merge_candidacy_node(graph_conn, candidacy_id, "Taylor for NC-01 General")
        create_graph_edge(
            graph_conn,
            source_label="Candidacy",
            source_id=candidacy_id,
            target_label="Contest",
            target_id=contest_id,
            edge_type="RUNS_IN",
        )

        results = fetch_entity_relationships(graph_conn, "contest", contest_id)

        assert len(results) == 1
        assert results[0]["entity_type"] == "candidacy"
        assert results[0]["entity_id"] == str(candidacy_id)
        assert results[0]["name"] == "Taylor for NC-01 General"
        assert results[0]["relationship_type"] == "RUNS_IN"
        assert results[0]["direction"] == "inbound"

    def test_returns_civic_neighbors_for_candidacy_entity(self, graph_conn):
        candidacy_id = uuid4()
        contest_id = uuid4()
        person_id = uuid4()
        merge_candidacy_node(graph_conn, candidacy_id, "Taylor for NC-01 General")
        merge_contest_node(graph_conn, contest_id, "NC-01 General")
        merge_person_node(graph_conn, person_id, "Taylor Person")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="Candidacy",
            target_id=candidacy_id,
            edge_type="CANDIDACY_OF",
        )
        create_graph_edge(
            graph_conn,
            source_label="Candidacy",
            source_id=candidacy_id,
            target_label="Contest",
            target_id=contest_id,
            edge_type="RUNS_IN",
        )

        results = fetch_entity_relationships(graph_conn, "candidacy", candidacy_id)

        assert len(results) == 2
        assert results == [
            {
                "direction": "inbound",
                "entity_id": str(person_id),
                "entity_type": "person",
                "name": "Taylor Person",
                "relationship_type": "CANDIDACY_OF",
            },
            {
                "direction": "outbound",
                "entity_id": str(contest_id),
                "entity_type": "contest",
                "name": "NC-01 General",
                "relationship_type": "RUNS_IN",
            },
        ]

    def test_returns_represents_neighbor_for_electoral_division_entity(self, graph_conn):
        division_id = uuid4()
        person_id = uuid4()
        merge_electoral_division_node(graph_conn, division_id, "NC-01")
        merge_person_node(graph_conn, person_id, "Representative Person")
        create_graph_edge(
            graph_conn,
            source_label="Person",
            source_id=person_id,
            target_label="ElectoralDivision",
            target_id=division_id,
            edge_type="REPRESENTS",
        )

        results = fetch_entity_relationships(graph_conn, "electoral_division", division_id)

        assert len(results) == 1
        assert results[0]["entity_type"] == "person"
        assert results[0]["entity_id"] == str(person_id)
        assert results[0]["name"] == "Representative Person"
        assert results[0]["relationship_type"] == "REPRESENTS"
        assert results[0]["direction"] == "inbound"

    def test_returns_empty_for_isolated_officeholding_entity(self, graph_conn):
        officeholding_id = uuid4()
        merge_officeholding_node(graph_conn, officeholding_id, "Taylor Person holds US House")

        results = fetch_entity_relationships(graph_conn, "officeholding", officeholding_id)

        assert results == []

    def test_rejects_invalid_entity_type(self, graph_conn):
        with pytest.raises(ValueError, match="entity_type"):
            fetch_entity_relationships(graph_conn, "filing", uuid4())
