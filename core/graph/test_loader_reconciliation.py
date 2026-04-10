from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from psycopg.rows import dict_row

from core.graph.cli import _load_mixed_domain_edges
from core.graph.loader import (
    CONTRIBUTION_LIKE_TYPES,
    EXPENDITURE_LIKE_TYPES,
    classify_transaction_type,
    load_affiliated_with_edges,
    load_contributed_to_edges,
    load_filed_edges,
    load_ie_edges,
    load_spent_on_edges,
)
from core.graph.loader_test_support import (
    count_edge,
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
from domains.property.ingest.durham_source import load_durham_fixture_records, normalize_durham_raw_records
from domains.property.ingest.loader import ensure_durham_data_source, ensure_durham_jurisdiction, load_durham_records


@dataclass
class _ReconciliationFixture:
    committee_id: UUID
    donor_id: UUID
    vendor_id: UUID
    candidate_id: UUID
    filing_ids: tuple[UUID, UUID, UUID, UUID]


@dataclass
class _CivicReconciliationFixture:
    office_id: UUID
    electoral_division_id: UUID
    contest_id: UUID
    candidacy_id: UUID


def _seed_reconciliation_fixture(graph_conn) -> _ReconciliationFixture:
    data_source_id = seed_data_source(graph_conn, label="reconciliation")
    committee_org_id = seed_org(graph_conn, name="Reconciliation Committee Org")
    committee_id = seed_committee(graph_conn, name="Reconciliation Committee", organization_id=committee_org_id)
    donor_id = seed_person(graph_conn, name="Reconciliation Donor")
    vendor_id = seed_org(graph_conn, name="Reconciliation Vendor")
    candidate_id = seed_candidate(graph_conn, name="Reconciliation Candidate")

    contribution_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="recon-contrib")
    expenditure_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="recon-spent")
    ie_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="recon-ie")
    unsupported_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="recon-skip")
    affiliated_source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="recon-aff")

    contribution_filing_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=contribution_source_record_id,
        filing_fec_id="FEC-RECON-CONTRIB",
    )
    expenditure_filing_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=expenditure_source_record_id,
        filing_fec_id="FEC-RECON-SPENT",
    )
    ie_filing_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=ie_source_record_id,
        filing_fec_id="FEC-RECON-IE",
    )
    unsupported_filing_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=unsupported_source_record_id,
        filing_fec_id="FEC-RECON-SKIP",
    )

    seed_transaction(
        graph_conn,
        filing_id=contribution_filing_id,
        committee_id=committee_id,
        source_record_id=contribution_source_record_id,
        contributor_person_id=donor_id,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("15.00"),
        transaction_date=date(2024, 4, 1),
    )
    seed_transaction(
        graph_conn,
        filing_id=expenditure_filing_id,
        committee_id=committee_id,
        source_record_id=expenditure_source_record_id,
        contributor_organization_id=vendor_id,
        transaction_type="Expenditure (Itemized)",
        amount=Decimal("20.00"),
        transaction_date=date(2024, 4, 2),
    )
    seed_transaction(
        graph_conn,
        filing_id=ie_filing_id,
        committee_id=committee_id,
        source_record_id=ie_source_record_id,
        recipient_candidate_id=candidate_id,
        support_oppose="S",
        transaction_type="Independent Expenditure",
        amount=Decimal("25.00"),
        transaction_date=date(2024, 4, 4),
    )
    seed_transaction(
        graph_conn,
        filing_id=unsupported_filing_id,
        committee_id=committee_id,
        source_record_id=unsupported_source_record_id,
        contributor_organization_id=vendor_id,
        transaction_type="UNKNOWN_TYPE",
        amount=Decimal("99.00"),
        transaction_date=date(2024, 4, 3),
    )
    seed_candidate_committee_link(
        graph_conn,
        candidate_id=candidate_id,
        committee_id=committee_id,
        source_record_id=affiliated_source_record_id,
        designation="P",
        candidate_election_year=2024,
        fec_election_year=2024,
        valid_period_start=date(2024, 1, 1),
        valid_period_end=date(2025, 1, 1),
    )
    return _ReconciliationFixture(
        committee_id=committee_id,
        donor_id=donor_id,
        vendor_id=vendor_id,
        candidate_id=candidate_id,
        filing_ids=(contribution_filing_id, expenditure_filing_id, ie_filing_id, unsupported_filing_id),
    )


def _seed_civic_reconciliation_fixture(graph_conn, *, person_id: UUID) -> _CivicReconciliationFixture:
    data_source_id = seed_data_source(graph_conn, label="reconciliation-civic")
    source_record_id = seed_source_record(graph_conn, data_source_id=data_source_id, key="recon-civic")
    office_id = uuid4()
    electoral_division_id = uuid4()
    contest_id = uuid4()
    candidacy_id = uuid4()

    graph_conn.execute(
        """
        INSERT INTO civic.office (id, name, office_level, state, source_record_id)
        VALUES (%s, %s, 'state', 'NC', %s)
        """,
        (office_id, f"reconciliation_office_{office_id.hex[:8]}", source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO civic.electoral_division (id, name, division_type, state, source_record_id)
        VALUES (%s, %s, 'congressional_district', 'NC', %s)
        """,
        (electoral_division_id, f"reconciliation_division_{electoral_division_id.hex[:8]}", source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO civic.contest (
            id, name, election_type, office_id, electoral_division_id, election_date, source_record_id
        )
        VALUES (%s, %s, 'general', %s, %s, %s, %s)
        """,
        (
            contest_id,
            f"reconciliation_contest_{contest_id.hex[:8]}",
            office_id,
            electoral_division_id,
            date(2026, 11, 3),
            source_record_id,
        ),
    )
    graph_conn.execute(
        """
        INSERT INTO civic.candidacy (id, person_id, contest_id, party, source_record_id)
        VALUES (%s, %s, %s, 'DEM', %s)
        """,
        (candidacy_id, person_id, contest_id, source_record_id),
    )
    graph_conn.execute(
        """
        INSERT INTO civic.officeholding (
            id, person_id, office_id, electoral_division_id, holder_status, valid_period, source_record_id
        )
        VALUES (%s, %s, %s, %s, 'elected', daterange(%s, %s, '[)'), %s)
        """,
        (
            uuid4(),
            person_id,
            office_id,
            electoral_division_id,
            date(2025, 1, 3),
            None,
            source_record_id,
        ),
    )
    return _CivicReconciliationFixture(
        office_id=office_id,
        electoral_division_id=electoral_division_id,
        contest_id=contest_id,
        candidacy_id=candidacy_id,
    )


def _transaction_route_counts(graph_conn, *, committee_id: UUID) -> dict[str, int]:
    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction_type, support_oppose
            FROM cf.transaction
            WHERE committee_id = %s
            ORDER BY id
            """,
            (committee_id,),
        )
        rows = cursor.fetchall()

    counts = {"contribution": 0, "spent_on": 0, "supports": 0, "opposes": 0}
    for row in rows:
        route_name = classify_transaction_type(row["transaction_type"])
        if route_name == "contribution":
            counts[route_name] += 1
            continue
        if route_name != "expenditure":
            continue

        support_oppose = row["support_oppose"]
        if support_oppose == "S":
            counts["supports"] += 1
        elif support_oppose == "O":
            counts["opposes"] += 1
        else:
            counts["spent_on"] += 1
    return counts


def _loader_limits(graph_conn) -> dict[str, int]:
    contribution_limit = graph_conn.execute(
        "SELECT COUNT(*) FROM cf.transaction WHERE transaction_type = ANY(%s)",
        (sorted(CONTRIBUTION_LIKE_TYPES),),
    ).fetchone()[0]
    expenditure_limit = graph_conn.execute(
        "SELECT COUNT(*) FROM cf.transaction WHERE transaction_type = ANY(%s)",
        (sorted(EXPENDITURE_LIKE_TYPES),),
    ).fetchone()[0]
    ie_limit = graph_conn.execute("SELECT COUNT(*) FROM cf.transaction WHERE support_oppose IS NOT NULL").fetchone()[0]
    affiliated_limit = graph_conn.execute("SELECT COUNT(*) FROM cf.candidate_committee_link").fetchone()[0]
    filed_limit = graph_conn.execute("SELECT COUNT(*) FROM cf.filing").fetchone()[0]
    return {
        "contributed": max(contribution_limit, 1),
        "spent": max(expenditure_limit, 1),
        "ie": max(ie_limit, 1),
        "affiliated": max(affiliated_limit, 1),
        "filed": max(filed_limit, 1),
    }


def _count_edges_by_type(graph_conn, *, edge_type: str) -> int:
    with graph_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM cypher('civibus', $$
                MATCH ()-[e:%s]->()
                RETURN e
            $$) AS (v agtype)
            """
            % edge_type
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _property_relational_edge_counts(graph_conn, *, data_source_id: UUID) -> dict[str, int]:
    owns_count = graph_conn.execute(
        """
        SELECT COUNT(*)
        FROM prop.ownership o
        JOIN prop.parcel p ON p.id = o.parcel_id
        JOIN core.source_record sr ON sr.id = o.source_record_id
        LEFT JOIN core.person p_owner ON p_owner.id = o.owner_person_id
        LEFT JOIN core.organization o_owner ON o_owner.id = o.owner_organization_id
        WHERE sr.data_source_id = %s
          AND o.source_record_id IS NOT NULL
          AND NULLIF(BTRIM(p.reid), '') IS NOT NULL
          AND (
                (o.owner_person_id IS NOT NULL AND NULLIF(BTRIM(p_owner.canonical_name), '') IS NOT NULL)
             OR (o.owner_organization_id IS NOT NULL AND NULLIF(BTRIM(o_owner.canonical_name), '') IS NOT NULL)
          )
        """,
        (data_source_id,),
    ).fetchone()[0]
    located_in_count = graph_conn.execute(
        """
        SELECT COUNT(*)
        FROM prop.parcel p
        JOIN core.jurisdiction j ON j.id = p.jurisdiction_id
        JOIN core.source_record sr ON sr.id = p.source_record_id
        WHERE sr.data_source_id = %s
          AND p.source_record_id IS NOT NULL
          AND NULLIF(BTRIM(p.reid), '') IS NOT NULL
          AND NULLIF(BTRIM(j.name), '') IS NOT NULL
        """,
        (data_source_id,),
    ).fetchone()[0]
    zoned_as_count = graph_conn.execute(
        """
        SELECT COUNT(*)
        FROM prop.parcel p
        JOIN core.source_record sr ON sr.id = p.source_record_id
        WHERE sr.data_source_id = %s
          AND p.source_record_id IS NOT NULL
          AND NULLIF(BTRIM(p.reid), '') IS NOT NULL
          AND NULLIF(BTRIM(p.zoning_class), '') IS NOT NULL
        """,
        (data_source_id,),
    ).fetchone()[0]
    assessed_at_count = graph_conn.execute(
        """
        SELECT COUNT(*)
        FROM prop.assessment a
        JOIN prop.parcel p ON p.id = a.parcel_id
        JOIN core.source_record sr ON sr.id = a.source_record_id
        WHERE sr.data_source_id = %s
          AND a.source_record_id IS NOT NULL
          AND NULLIF(BTRIM(p.reid), '') IS NOT NULL
          AND a.tax_year IS NOT NULL
        """,
        (data_source_id,),
    ).fetchone()[0]
    return {
        "OWNS": owns_count,
        "LOCATED_IN": located_in_count,
        "ZONED_AS": zoned_as_count,
        "ASSESSED_AT": assessed_at_count,
    }


@pytest.mark.integration
def test_stage3_loaders_reconcile_age_counts_to_relational_inputs(graph_conn) -> None:
    fixture = _seed_reconciliation_fixture(graph_conn)
    route_counts = _transaction_route_counts(graph_conn, committee_id=fixture.committee_id)
    limits = _loader_limits(graph_conn)

    expected_affiliated_count = graph_conn.execute(
        "SELECT COUNT(*) FROM cf.candidate_committee_link WHERE committee_id = %s",
        (fixture.committee_id,),
    ).fetchone()[0]
    expected_filed_count = graph_conn.execute(
        "SELECT COUNT(*) FROM cf.filing WHERE committee_id = %s",
        (fixture.committee_id,),
    ).fetchone()[0]

    contributed_count = load_contributed_to_edges(graph_conn, limit=limits["contributed"])
    spent_count = load_spent_on_edges(graph_conn, limit=limits["spent"])
    ie_count = load_ie_edges(graph_conn, limit=limits["ie"])
    affiliated_count = load_affiliated_with_edges(graph_conn, limit=limits["affiliated"])
    filed_count = load_filed_edges(graph_conn, limit=limits["filed"])

    assert contributed_count >= route_counts["contribution"]
    assert spent_count >= route_counts["spent_on"]
    assert ie_count >= route_counts["supports"] + route_counts["opposes"]
    assert affiliated_count >= expected_affiliated_count
    assert filed_count >= expected_filed_count

    filed_edge_count = 0
    for filing_id in fixture.filing_ids:
        filed_edge_count += count_edge(
            graph_conn,
            source_label="Committee",
            source_id=fixture.committee_id,
            edge_type="FILED",
            target_label="Filing",
            target_id=filing_id,
        )

    assert (
        count_edge(
            graph_conn,
            source_label="Person",
            source_id=fixture.donor_id,
            edge_type="CONTRIBUTED_TO",
            target_label="Committee",
            target_id=fixture.committee_id,
        )
        == route_counts["contribution"]
    )
    assert (
        count_edge(
            graph_conn,
            source_label="Committee",
            source_id=fixture.committee_id,
            edge_type="SPENT_ON",
            target_label="Organization",
            target_id=fixture.vendor_id,
        )
        == route_counts["spent_on"]
    )
    assert (
        count_edge(
            graph_conn,
            source_label="Committee",
            source_id=fixture.committee_id,
            edge_type="SUPPORTS",
            target_label="Candidate",
            target_id=fixture.candidate_id,
        )
        == route_counts["supports"]
    )
    assert (
        count_edge(
            graph_conn,
            source_label="Candidate",
            source_id=fixture.candidate_id,
            edge_type="AFFILIATED_WITH",
            target_label="Committee",
            target_id=fixture.committee_id,
        )
        == expected_affiliated_count
    )
    assert filed_edge_count == expected_filed_count
    assert (
        count_edge(
            graph_conn,
            source_label="Person",
            source_id=fixture.donor_id,
            edge_type="CONTRIBUTED_TO",
            target_label="Committee",
            target_id=fixture.committee_id,
        )
        + count_edge(
            graph_conn,
            source_label="Committee",
            source_id=fixture.committee_id,
            edge_type="SPENT_ON",
            target_label="Organization",
            target_id=fixture.vendor_id,
        )
        + count_edge(
            graph_conn,
            source_label="Committee",
            source_id=fixture.committee_id,
            edge_type="SUPPORTS",
            target_label="Candidate",
            target_id=fixture.candidate_id,
        )
        + count_edge(
            graph_conn,
            source_label="Candidate",
            source_id=fixture.candidate_id,
            edge_type="AFFILIATED_WITH",
            target_label="Committee",
            target_id=fixture.committee_id,
        )
        + filed_edge_count
    ) == (
        route_counts["contribution"]
        + route_counts["spent_on"]
        + route_counts["supports"]
        + expected_affiliated_count
        + expected_filed_count
    )


@pytest.mark.integration
def test_stage3_mixed_domain_graph_load_reconciles_and_is_idempotent(graph_conn) -> None:
    fixture = _seed_reconciliation_fixture(graph_conn)
    civic_fixture = _seed_civic_reconciliation_fixture(graph_conn, person_id=fixture.donor_id)
    durham_records = normalize_durham_raw_records(load_durham_fixture_records())
    durham_data_source_id = ensure_durham_data_source(graph_conn)
    durham_jurisdiction_id = ensure_durham_jurisdiction(graph_conn)
    inserted, skipped, errors = load_durham_records(
        graph_conn,
        durham_data_source_id,
        durham_jurisdiction_id,
        durham_records,
    )
    assert (inserted, skipped, errors) == (len(durham_records), 0, 0)

    route_counts = _transaction_route_counts(graph_conn, committee_id=fixture.committee_id)
    expected_counts = {
        "CONTRIBUTED_TO": route_counts["contribution"],
        "SPENT_ON": route_counts["spent_on"],
        "SUPPORTS": route_counts["supports"],
        "OPPOSES": route_counts["opposes"],
        "AFFILIATED_WITH": graph_conn.execute("SELECT COUNT(*) FROM cf.candidate_committee_link").fetchone()[0],
        "FILED": graph_conn.execute("SELECT COUNT(*) FROM cf.filing").fetchone()[0],
    }
    expected_counts.update(_property_relational_edge_counts(graph_conn, data_source_id=durham_data_source_id))
    expected_counts.update(
        {
            "HOLDS": 1,
            "RUNS_IN": 1,
            "CANDIDACY_OF": 1,
            "REPRESENTS": 1,
        }
    )
    expected_total = sum(expected_counts.values())

    campaign_finance_count, property_count, civic_count, total_count = _load_mixed_domain_edges(graph_conn, limit=1000)

    assert campaign_finance_count == (
        expected_counts["CONTRIBUTED_TO"]
        + expected_counts["SPENT_ON"]
        + expected_counts["SUPPORTS"]
        + expected_counts["OPPOSES"]
        + expected_counts["AFFILIATED_WITH"]
        + expected_counts["FILED"]
    )
    assert property_count == (
        expected_counts["OWNS"]
        + expected_counts["LOCATED_IN"]
        + expected_counts["ZONED_AS"]
        + expected_counts["ASSESSED_AT"]
    )
    assert civic_count == (
        expected_counts["HOLDS"]
        + expected_counts["RUNS_IN"]
        + expected_counts["CANDIDACY_OF"]
        + expected_counts["REPRESENTS"]
    )
    assert total_count == expected_total
    assert (
        count_edge(
            graph_conn,
            source_label="Person",
            source_id=fixture.donor_id,
            edge_type="HOLDS",
            target_label="Office",
            target_id=civic_fixture.office_id,
        )
        == 1
    )
    assert (
        count_edge(
            graph_conn,
            source_label="Candidacy",
            source_id=civic_fixture.candidacy_id,
            edge_type="RUNS_IN",
            target_label="Contest",
            target_id=civic_fixture.contest_id,
        )
        == 1
    )
    assert (
        count_edge(
            graph_conn,
            source_label="Person",
            source_id=fixture.donor_id,
            edge_type="CANDIDACY_OF",
            target_label="Candidacy",
            target_id=civic_fixture.candidacy_id,
        )
        == 1
    )
    assert (
        count_edge(
            graph_conn,
            source_label="Person",
            source_id=fixture.donor_id,
            edge_type="REPRESENTS",
            target_label="ElectoralDivision",
            target_id=civic_fixture.electoral_division_id,
        )
        == 1
    )

    first_snapshot = {edge_type: _count_edges_by_type(graph_conn, edge_type=edge_type) for edge_type in expected_counts}
    assert first_snapshot == expected_counts

    rerun_campaign_finance_count, rerun_property_count, rerun_civic_count, rerun_total_count = _load_mixed_domain_edges(
        graph_conn, limit=1000
    )
    second_snapshot = {
        edge_type: _count_edges_by_type(graph_conn, edge_type=edge_type) for edge_type in expected_counts
    }

    assert rerun_campaign_finance_count == campaign_finance_count
    assert rerun_property_count == property_count
    assert rerun_civic_count == civic_count
    assert rerun_total_count == total_count
    assert second_snapshot == first_snapshot
