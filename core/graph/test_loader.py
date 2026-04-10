from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from psycopg.rows import dict_row

from core.graph.loader import (
    CONTRIBUTION_LIKE_TYPES,
    EXPENDITURE_LIKE_TYPES,
    classify_transaction_type,
    create_contributed_to_edge,
    load_affiliated_with_edges,
    load_contributed_to_edges,
    load_filed_edges,
    load_ie_edges,
    load_spent_on_edges,
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
from core.graph.loader_test_support import (
    count_edge,
    edge_properties,
    seed_candidate,
    seed_candidate_committee_link,
    seed_committee,
    seed_data_source,
    seed_filing,
    seed_org,
    seed_person,
    seed_source_record,
    seed_transaction,
)


def count_nodes_by_label(conn, *, label: str, node_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (n:%s {id: "%s"})
                RETURN n
            $$) AS (v agtype)
            """
            % (label, node_id)
        )
        return cur.fetchone()[0]


def assert_node_count(conn, *, label: str, node_id: UUID) -> None:
    assert count_nodes_by_label(conn, label=label, node_id=node_id) == 1


def assert_edge_count(
    conn,
    *,
    source_label: str,
    source_id: UUID,
    edge_type: str,
    target_label: str,
    target_id: UUID,
) -> None:
    assert (
        count_edge(
            conn,
            source_label=source_label,
            source_id=source_id,
            edge_type=edge_type,
            target_label=target_label,
            target_id=target_id,
        )
        == 1
    )


def _count_contributed_to_edges(conn, person_id: str, org_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH (p:Person {id: "%s"})-[e:CONTRIBUTED_TO]->(o:Organization {id: "%s"})
                RETURN e
            $$) AS (v agtype)
            """
            % (person_id, org_id)
        )
        return cur.fetchone()[0]


@dataclass
class _CombinedLoaderFixture:
    donor_id: UUID
    vendor_id: UUID
    committee_id: UUID
    candidate_id: UUID
    filing_edge_id: UUID


def _seed_combined_loader_fixture(graph_conn) -> _CombinedLoaderFixture:
    data_source_id = seed_data_source(graph_conn, label="combined")
    sr_contrib = seed_source_record(graph_conn, data_source_id=data_source_id, key="combined-contrib")
    sr_spent = seed_source_record(graph_conn, data_source_id=data_source_id, key="combined-spent")
    sr_aff = seed_source_record(graph_conn, data_source_id=data_source_id, key="combined-aff")
    sr_filed = seed_source_record(graph_conn, data_source_id=data_source_id, key="combined-filed")

    donor_id = seed_person(graph_conn, name="Combined Donor")
    vendor_id = seed_org(graph_conn, name="Combined Vendor")
    committee_org_id = seed_org(graph_conn, name="Combined Committee Org")
    committee_id = seed_committee(graph_conn, name="Combined Committee", organization_id=committee_org_id)
    candidate_id = seed_candidate(graph_conn, name="Combined Candidate")

    filing_contrib_id = seed_filing(graph_conn, committee_id=committee_id, source_record_id=sr_contrib)
    filing_spent_id = seed_filing(graph_conn, committee_id=committee_id, source_record_id=sr_spent)
    filing_edge_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=sr_filed,
        filing_fec_id="FEC-COMBINED-FILED",
    )

    seed_transaction(
        graph_conn,
        filing_id=filing_contrib_id,
        committee_id=committee_id,
        source_record_id=sr_contrib,
        contributor_person_id=donor_id,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("33.00"),
        transaction_date=date(2024, 3, 1),
    )
    seed_transaction(
        graph_conn,
        filing_id=filing_spent_id,
        committee_id=committee_id,
        source_record_id=sr_spent,
        contributor_organization_id=vendor_id,
        transaction_type="Expenditure (Itemized)",
        amount=Decimal("44.00"),
        transaction_date=date(2024, 3, 2),
    )
    seed_candidate_committee_link(
        graph_conn,
        candidate_id=candidate_id,
        committee_id=committee_id,
        source_record_id=sr_aff,
        designation="A",
        candidate_election_year=2026,
        fec_election_year=2026,
        valid_period_start=date(2026, 1, 1),
        valid_period_end=date(2027, 1, 1),
    )
    return _CombinedLoaderFixture(
        donor_id=donor_id,
        vendor_id=vendor_id,
        committee_id=committee_id,
        candidate_id=candidate_id,
        filing_edge_id=filing_edge_id,
    )


def _assert_combined_loader_state(graph_conn, fixture: _CombinedLoaderFixture) -> None:
    assert_node_count(graph_conn, label="Person", node_id=fixture.donor_id)
    assert_node_count(graph_conn, label="Organization", node_id=fixture.vendor_id)
    assert_node_count(graph_conn, label="Committee", node_id=fixture.committee_id)
    assert_node_count(graph_conn, label="Candidate", node_id=fixture.candidate_id)
    assert_node_count(graph_conn, label="Filing", node_id=fixture.filing_edge_id)
    assert_edge_count(
        graph_conn,
        source_label="Person",
        source_id=fixture.donor_id,
        edge_type="CONTRIBUTED_TO",
        target_label="Committee",
        target_id=fixture.committee_id,
    )
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=fixture.committee_id,
        edge_type="SPENT_ON",
        target_label="Organization",
        target_id=fixture.vendor_id,
    )
    assert_edge_count(
        graph_conn,
        source_label="Candidate",
        source_id=fixture.candidate_id,
        edge_type="AFFILIATED_WITH",
        target_label="Committee",
        target_id=fixture.committee_id,
    )


_MERGE_NODE_CASES = [
    pytest.param("Person", merge_person_node, "Smith, John", id="person"),
    pytest.param("Organization", merge_organization_node, "ACTBLUE", id="organization"),
    pytest.param("Committee", merge_committee_node, "ACTBLUE", id="committee"),
    pytest.param("Candidate", merge_candidate_node, "DOE, JOHN", id="candidate"),
    pytest.param("Filing", merge_filing_node, "FEC-12345", id="filing"),
    pytest.param("Office", merge_office_node, "us_senate", id="office"),
    pytest.param("ElectoralDivision", merge_electoral_division_node, "NC-01", id="electoral_division"),
    pytest.param("Contest", merge_contest_node, "NC-01 2026 General", id="contest"),
    pytest.param("Candidacy", merge_candidacy_node, "Smith for NC-01", id="candidacy"),
    pytest.param("Officeholding", merge_officeholding_node, "Smith holds us_senate", id="officeholding"),
]


@pytest.mark.integration
@pytest.mark.parametrize(("label", "merge_fn", "canonical_name"), _MERGE_NODE_CASES)
def test_merge_node_creates_node(graph_conn, label: str, merge_fn, canonical_name: str):
    node_id = uuid4()
    merge_fn(graph_conn, node_id, canonical_name)
    assert count_nodes_by_label(graph_conn, label=label, node_id=node_id) == 1


@pytest.mark.integration
@pytest.mark.parametrize(("label", "merge_fn", "canonical_name"), _MERGE_NODE_CASES)
def test_merge_node_is_idempotent(graph_conn, label: str, merge_fn, canonical_name: str):
    node_id = uuid4()
    merge_fn(graph_conn, node_id, canonical_name)
    merge_fn(graph_conn, node_id, canonical_name)
    assert count_nodes_by_label(graph_conn, label=label, node_id=node_id) == 1


@pytest.mark.integration
class TestCreateContributedToEdge:
    def test_creates_edge_with_properties(self, graph_conn):
        pid = uuid4()
        oid = uuid4()
        srid = uuid4()
        merge_person_node(graph_conn, pid, "Doe, Jane")
        merge_organization_node(graph_conn, oid, "ACME PAC")
        create_contributed_to_edge(graph_conn, pid, oid, 250.0, "2024-06-15", srid)
        assert _count_contributed_to_edges(graph_conn, str(pid), str(oid)) == 1

    def test_edge_properties_correct(self, graph_conn):
        pid = uuid4()
        oid = uuid4()
        srid = uuid4()
        merge_person_node(graph_conn, pid, "Doe, Jane")
        merge_organization_node(graph_conn, oid, "ACME PAC")
        create_contributed_to_edge(graph_conn, pid, oid, 500.0, "2024-01-01", srid)
        with graph_conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM cypher('civibus', $$
                    MATCH (p:Person {id: "%s"})-[e:CONTRIBUTED_TO]->(o:Organization {id: "%s"})
                    RETURN e.amount, e.transaction_date, e.source_record_id
                $$) AS (amount agtype, transaction_date agtype, sr_id agtype)
                """
                % (str(pid), str(oid))
            )
            row = cur.fetchone()
        assert row is not None
        assert float(str(row[0])) == 500.0
        assert str(row[1]).strip('"') == "2024-01-01"
        assert str(row[2]).strip('"') == str(srid)

    def test_skips_when_person_id_none(self, graph_conn):
        oid = uuid4()
        srid = uuid4()
        merge_organization_node(graph_conn, oid, "ACME PAC")
        create_contributed_to_edge(graph_conn, None, oid, 100.0, "2024-03-01", srid)
        with graph_conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM cypher('civibus', $$
                    MATCH ()-[e:CONTRIBUTED_TO]->(:Organization {id: "%s"})
                    RETURN e
                $$) AS (v agtype)
                """
                % str(oid)
            )
            assert cur.fetchone()[0] == 0


class TestTransactionTypeRoutingAPI:
    """Verify the routing API is importable from core.graph.loader."""

    def test_contribution_like_types_exported(self):
        assert isinstance(CONTRIBUTION_LIKE_TYPES, frozenset)
        assert len(CONTRIBUTION_LIKE_TYPES) > 0

    def test_expenditure_like_types_exported(self):
        assert isinstance(EXPENDITURE_LIKE_TYPES, frozenset)
        assert len(EXPENDITURE_LIKE_TYPES) > 0

    def test_classify_transaction_type_callable(self):
        assert callable(classify_transaction_type)
        assert classify_transaction_type("Monetary (Itemized)") == "contribution"
        assert classify_transaction_type("NONSENSE") is None


@pytest.mark.integration
def test_load_affiliated_with_edges_properties_and_valid_period_serialization(graph_conn):
    data_source_id = seed_data_source(graph_conn, label="affiliated")
    source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="affiliated-link")
    candidate_id = seed_candidate(graph_conn, name="Candidate Person")
    committee_org_id = seed_org(graph_conn, name="Candidate Committee Org")
    committee_id = seed_committee(graph_conn, name="Candidate Committee", organization_id=committee_org_id)
    seed_candidate_committee_link(
        graph_conn,
        candidate_id=candidate_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
        designation="P",
        candidate_election_year=2024,
        fec_election_year=2024,
        valid_period_start=date(2024, 1, 1),
        valid_period_end=date(2025, 1, 1),
    )

    processed = load_affiliated_with_edges(graph_conn, limit=10)
    assert processed >= 1
    assert_edge_count(
        graph_conn,
        source_label="Candidate",
        source_id=candidate_id,
        edge_type="AFFILIATED_WITH",
        target_label="Committee",
        target_id=committee_id,
    )

    props = edge_properties(
        graph_conn,
        edge_type="AFFILIATED_WITH",
        source_record_id=source_record_id,
        projection="e.designation, e.candidate_election_year, e.fec_election_year, e.valid_period",
        aliases="designation agtype, candidate_election_year agtype, fec_election_year agtype, valid_period agtype",
    )
    assert props["designation"] == "P"
    assert props["candidate_election_year"] == "2024"
    assert props["fec_election_year"] == "2024"
    assert props["valid_period"] == "[2024-01-01,2025-01-01)"

    rerun = load_affiliated_with_edges(graph_conn, limit=10)
    assert rerun >= 1
    assert_edge_count(
        graph_conn,
        source_label="Candidate",
        source_id=candidate_id,
        edge_type="AFFILIATED_WITH",
        target_label="Committee",
        target_id=committee_id,
    )


@pytest.mark.integration
def test_load_filed_edges_properties_and_updates_on_rerun(graph_conn):
    data_source_id = seed_data_source(graph_conn, label="filed")
    source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="filed-edge")
    committee_org_id = seed_org(graph_conn, name="Filed Committee Org")
    committee_id = seed_committee(graph_conn, name="Filed Committee", organization_id=committee_org_id)
    filing_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=source_record_id,
        filing_fec_id="FEC-TEST-FILING-1",
        report_type="Q1",
        receipt_date=date(2024, 4, 10),
        due_date=date(2024, 4, 15),
        accepted_date=date(2024, 4, 11),
    )

    processed = load_filed_edges(graph_conn, limit=10)
    assert processed >= 1
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=committee_id,
        edge_type="FILED",
        target_label="Filing",
        target_id=filing_id,
    )

    graph_conn.execute(
        "UPDATE cf.filing SET report_type = %s, due_date = %s WHERE id = %s",
        ("Q2", date(2024, 5, 15), filing_id),
    )
    rerun = load_filed_edges(graph_conn, limit=10)
    assert rerun >= 1
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=committee_id,
        edge_type="FILED",
        target_label="Filing",
        target_id=filing_id,
    )

    props = edge_properties(
        graph_conn,
        edge_type="FILED",
        source_record_id=source_record_id,
        projection="e.receipt_date, e.due_date, e.accepted_date, e.report_type",
        aliases="receipt_date agtype, due_date agtype, accepted_date agtype, report_type agtype",
    )
    assert props["receipt_date"] == "2024-04-10"
    assert props["due_date"] == "2024-05-15"
    assert props["accepted_date"] == "2024-04-11"
    assert props["report_type"] == "Q2"


@pytest.mark.integration
def test_load_ie_edges_supports_opposes_and_is_idempotent(graph_conn):
    data_source_id = seed_data_source(graph_conn, label="ie")
    committee_org_id = seed_org(graph_conn, name="IE Committee Org")
    committee_id = seed_committee(graph_conn, name="IE Committee", organization_id=committee_org_id)
    candidate_id = seed_candidate(graph_conn, name="IE Candidate")

    supports_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="ie-supports")
    opposes_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="ie-opposes")
    supports_filing_id = seed_filing(graph_conn, committee_id=committee_id, source_record_id=supports_source_record_id)
    opposes_filing_id = seed_filing(graph_conn, committee_id=committee_id, source_record_id=opposes_source_record_id)

    seed_transaction(
        graph_conn,
        filing_id=supports_filing_id,
        committee_id=committee_id,
        source_record_id=supports_source_record_id,
        transaction_type="Independent Expenditure",
        amount=Decimal("91.00"),
        transaction_date=date(2024, 8, 3),
        support_oppose="S",
        recipient_candidate_id=candidate_id,
    )
    seed_transaction(
        graph_conn,
        filing_id=opposes_filing_id,
        committee_id=committee_id,
        source_record_id=opposes_source_record_id,
        transaction_type="Independent Expenditure",
        amount=Decimal("92.00"),
        transaction_date=date(2024, 8, 4),
        support_oppose="O",
        recipient_candidate_id=candidate_id,
    )

    processed = load_ie_edges(graph_conn, limit=10)
    assert processed >= 2
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=committee_id,
        edge_type="SUPPORTS",
        target_label="Candidate",
        target_id=candidate_id,
    )
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=committee_id,
        edge_type="OPPOSES",
        target_label="Candidate",
        target_id=candidate_id,
    )

    supports_props = edge_properties(
        graph_conn,
        edge_type="SUPPORTS",
        source_record_id=supports_source_record_id,
        projection="e.amount, e.transaction_date, e.transaction_type, e.filing_id",
        aliases="amount agtype, transaction_date agtype, transaction_type agtype, filing_id agtype",
    )
    assert float(supports_props["amount"]) == 91.0
    assert supports_props["transaction_date"] == "2024-08-03"
    assert supports_props["transaction_type"] == "Independent Expenditure"
    assert supports_props["filing_id"] == str(supports_filing_id)

    opposes_props = edge_properties(
        graph_conn,
        edge_type="OPPOSES",
        source_record_id=opposes_source_record_id,
        projection="e.amount, e.transaction_date, e.transaction_type, e.filing_id",
        aliases="amount agtype, transaction_date agtype, transaction_type agtype, filing_id agtype",
    )
    assert float(opposes_props["amount"]) == 92.0
    assert opposes_props["transaction_date"] == "2024-08-04"
    assert opposes_props["transaction_type"] == "Independent Expenditure"
    assert opposes_props["filing_id"] == str(opposes_filing_id)

    rerun = load_ie_edges(graph_conn, limit=10)
    assert rerun >= 2
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=committee_id,
        edge_type="SUPPORTS",
        target_label="Candidate",
        target_id=candidate_id,
    )
    assert_edge_count(
        graph_conn,
        source_label="Committee",
        source_id=committee_id,
        edge_type="OPPOSES",
        target_label="Candidate",
        target_id=candidate_id,
    )


@pytest.mark.integration
def test_stage3_loaders_combined_regression(graph_conn):
    fixture = _seed_combined_loader_fixture(graph_conn)

    assert load_contributed_to_edges(graph_conn, limit=100) >= 1
    assert load_spent_on_edges(graph_conn, limit=100) >= 1
    assert load_affiliated_with_edges(graph_conn, limit=100) >= 1
    assert load_filed_edges(graph_conn, limit=100) >= 1
    _assert_combined_loader_state(graph_conn, fixture)

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT * FROM cypher('civibus', $$
                MATCH (s:Committee {id: "%s"})-[e:FILED]->(f:Filing {id: "%s"})
                RETURN e.transaction_type, e.valid_period
            $$) AS (transaction_type agtype, valid_period agtype)
            """
            % (fixture.committee_id, fixture.filing_edge_id)
        )
        filed_row = cursor.fetchone()
    assert filed_row is not None
    assert filed_row["transaction_type"] is None
    assert filed_row["valid_period"] is None
