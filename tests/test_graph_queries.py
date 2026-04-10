from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.rows import dict_row

from core.entity_resolution.graph_edges import materialize_er_edges
from core.graph.loader import load_contributed_to_edges
from core.graph import query_formatted_cypher
from core.graph.loader_test_support import (
    seed_committee,
    seed_data_source,
    seed_entity_source,
    seed_filing,
    seed_person,
    seed_source_record,
    seed_transaction,
)
from domains.campaign_finance.ingest.loader import ensure_fec_data_source, load_contribution
from test_support.cross_domain_graph import (
    assert_cross_domain_possible_match_provenance,
    seed_cross_domain_possible_match_fixture,
)
from test_support.fec_fixtures import clone_with_unique_sub_id, load_fixture_results

pytestmark = pytest.mark.integration


def _first_ind_record() -> dict:
    return next(r for r in load_fixture_results() if r.get("entity_type") == "IND")


def _seed_committee_graph_fixture(graph_conn) -> tuple[str, tuple[str, str], tuple[str, str]]:
    data_source_id = seed_data_source(graph_conn, label="graph-queries")
    donor_id = seed_person(graph_conn, name="Jamie Donor")
    source_record_ids: list[str] = []
    committee_ids: list[str] = []

    for suffix, committee_name in (("a", "TEST COMMITTEE A"), ("b", "TEST COMMITTEE B")):
        source_record_key = f"graph-query-contrib-{suffix}-{uuid4().hex}"
        source_record_id = seed_source_record(
            graph_conn,
            data_source_id=data_source_id,
            key=source_record_key,
        )
        committee_id = seed_committee(graph_conn, name=committee_name)
        filing_id = seed_filing(
            graph_conn,
            committee_id=committee_id,
            source_record_id=source_record_id,
        )
        seed_transaction(
            graph_conn,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            contributor_person_id=donor_id,
            transaction_type="Monetary (Itemized)",
            amount=Decimal("25.00"),
            transaction_date=date(2024, 1, 15),
        )
        seed_entity_source(
            graph_conn,
            entity_type="person",
            entity_id=donor_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )
        source_record_ids.append(str(source_record_id))
        committee_ids.append(str(committee_id))

    loaded = load_contributed_to_edges(graph_conn, limit=100)
    assert loaded >= 2
    return str(donor_id), tuple(source_record_ids), tuple(committee_ids)


class TestCypherPersonToCommittees:
    def test_person_connected_to_two_committees(self, graph_conn):
        person_uuid, source_record_ids, expected_committee_ids = _seed_committee_graph_fixture(graph_conn)

        results = query_formatted_cypher(
            graph_conn,
            """
                MATCH (p:Person {id: "%s"})-[e:CONTRIBUTED_TO]->(c:Committee)
                WHERE e.source_record_id IN ["%s", "%s"]
                RETURN c.id
            """,
            person_uuid,
            source_record_ids[0],
            source_record_ids[1],
        )
        committee_ids = [str(v).strip('"') for v in results]

        assert set(committee_ids) == set(expected_committee_ids)


class TestCypherCteHybrid:
    def test_cte_hybrid_filters_by_state(self, graph_conn):
        base = _first_ind_record()
        data_source_id = ensure_fec_data_source(graph_conn)
        contribution = clone_with_unique_sub_id(base)
        load_contribution(graph_conn, data_source_id, contribution, graph_enabled=True)

        # Find the person ID
        with graph_conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT p.id
                FROM core.person p
                JOIN core.entity_source es ON es.entity_type = 'person' AND es.entity_id = p.id
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key = %s
                """,
                (contribution["sub_id"],),
            )
            person_row = cur.fetchone()

        assert person_row is not None
        person_uuid = str(person_row["id"])
        expected_state = contribution.get("contributor_state", "NC")

        # CTE hybrid: Cypher in CTE → JOIN with core.address → filter by state
        with graph_conn.cursor(row_factory=dict_row) as cur:
            statement = sql.SQL(
                """
                WITH graph_persons AS (
                    SELECT person_id::text AS person_id
                    FROM cypher('civibus', $$
                        MATCH (p:Person {{id: {person_uuid}}})
                        RETURN p.id AS person_id
                    $$) AS (person_id agtype)
                )
                SELECT a.state, a.city
                FROM graph_persons gp
                JOIN core.entity_address ea
                    ON ea.entity_type = 'person'
                    AND ea.entity_id = trim(both '"' from gp.person_id)::uuid
                JOIN core.address a ON a.id = ea.address_id
                WHERE a.state = %s
                """
            ).format(person_uuid=sql.Literal(person_uuid))
            cur.execute(
                statement,
                (expected_state,),
            )
            rows = cur.fetchall()

        assert len(rows) >= 1
        for row in rows:
            assert row["state"] == expected_state


class TestCrossDomainDonorToParcel:
    def test_cte_hybrid_returns_cross_domain_donor_to_parcel_row(self, graph_conn):
        fixture = seed_cross_domain_possible_match_fixture(graph_conn)
        materialize_er_edges(
            graph_conn,
            [
                {
                    "entity_id_a": fixture.campaign_person_id,
                    "entity_id_b": fixture.property_person_id,
                    "decision": "possible_match",
                    "confidence": 0.67,
                }
            ],
            "person",
        )

        with graph_conn.cursor(row_factory=dict_row) as cur:
            statement = sql.SQL(
                """
                WITH donor_owner_parcel AS (
                    SELECT donor_id::text AS donor_id, owner_id::text AS owner_id, parcel_id::text AS parcel_id
                    FROM cypher('civibus', $$
                        MATCH (donor:Person {{id: {donor_person_id}}})-[:CONTRIBUTED_TO]->(cmte:Committee)
                        MATCH (donor)-[:SAME_AS]-(owner:Person)-[:OWNS]->(parcel:Parcel)
                        RETURN donor.id AS donor_id, owner.id AS owner_id, parcel.id AS parcel_id
                        UNION
                        MATCH (donor:Person {{id: {donor_person_id}}})-[:CONTRIBUTED_TO]->(cmte:Committee)
                        MATCH (donor)-[:POSSIBLE_MATCH]-(owner:Person)-[:OWNS]->(parcel:Parcel)
                        RETURN donor.id AS donor_id, owner.id AS owner_id, parcel.id AS parcel_id
                    $$) AS (donor_id agtype, owner_id agtype, parcel_id agtype)
                )
                SELECT
                    trim(both '"' from dop.donor_id)::uuid AS donor_person_id,
                    trim(both '"' from dop.owner_id)::uuid AS owner_person_id,
                    p.reid AS parcel_reid,
                    p.site_address AS parcel_site_address,
                    j.name AS jurisdiction_name
                FROM donor_owner_parcel dop
                JOIN prop.parcel p ON p.id = trim(both '"' from dop.parcel_id)::uuid
                JOIN core.jurisdiction j ON j.id = p.jurisdiction_id
                """
            ).format(donor_person_id=sql.Literal(str(fixture.campaign_person_id)))
            cur.execute(statement)
            rows = cur.fetchall()

        assert len(rows) == 1
        row = rows[0]
        assert row["donor_person_id"] == fixture.campaign_person_id
        assert row["owner_person_id"] == fixture.property_person_id
        assert row["parcel_reid"] == fixture.property_source_record_key
        assert row["parcel_site_address"] is not None
        assert row["jurisdiction_name"] == "Durham County"

        assert_cross_domain_possible_match_provenance(
            graph_conn,
            fixtures=fixture,
            donor_person_id=row["donor_person_id"],
            owner_person_id=row["owner_person_id"],
        )
