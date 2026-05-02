
from __future__ import annotations

from datetime import date
from decimal import Decimal
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from core.graph.cli import _load_mixed_domain_edges
from core.graph.loader_test_support import (
    seed_committee,
    seed_data_source,
    seed_entity_source,
    seed_filing,
    seed_person,
    seed_source_record,
    seed_transaction,
)
from domains.property.ingest.durham_source import (
    build_durham_source_url,
    load_durham_fixture_records,
    normalize_durham_raw_records,
)
from domains.property.ingest.loader import ensure_durham_data_source, ensure_durham_jurisdiction, load_durham_records


@dataclass
class CrossDomainPossibleMatchFixtureSet:
    campaign_person_id: UUID
    property_person_id: UUID
    campaign_source_record_key: str
    property_source_record_key: str


def _person_id_by_source_record_key(
    graph_conn: psycopg.Connection,
    *,
    source_record_key: str,
    extraction_role: str,
) -> UUID:
    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT es.entity_id
            FROM core.entity_source es
            JOIN core.source_record sr ON sr.id = es.source_record_id
            WHERE es.entity_type = 'person'
              AND es.extraction_role = %s
              AND sr.source_record_key = %s
            ORDER BY es.created_at, es.id
            """,
            (extraction_role, source_record_key),
        )
        rows = cursor.fetchall()

    assert len(rows) == 1
    entity_id = rows[0]["entity_id"]
    assert isinstance(entity_id, UUID)
    return entity_id


def seed_cross_domain_possible_match_fixture(graph_conn: psycopg.Connection) -> CrossDomainPossibleMatchFixtureSet:
    contribution_sub_id = f"stage4-cross-domain-{uuid4().hex}"
    campaign_data_source_id = seed_data_source(graph_conn, label="cross-domain")
    campaign_source_record_id = seed_source_record(
        graph_conn,
        data_source_id=campaign_data_source_id,
        key=contribution_sub_id,
    )
    campaign_person_id = seed_person(graph_conn, name="John Smith")
    committee_id = seed_committee(graph_conn, name="STAGE4 TEST COMMITTEE")
    filing_id = seed_filing(
        graph_conn,
        committee_id=committee_id,
        source_record_id=campaign_source_record_id,
        filing_fec_id="FEC-STAGE4-CROSS-DOMAIN",
    )
    seed_transaction(
        graph_conn,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=campaign_source_record_id,
        contributor_person_id=campaign_person_id,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("25.00"),
        transaction_date=date(2024, 1, 15),
    )
    seed_entity_source(
        graph_conn,
        entity_type="person",
        entity_id=campaign_person_id,
        source_record_id=campaign_source_record_id,
        extraction_role="donor",
    )

    normalized_record = normalize_durham_raw_records(load_durham_fixture_records())[0]
    unique_reid = f"stage4-{uuid4().hex[:20]}"
    unique_pin = f"9{uuid4().hex[:9]}".upper()
    normalized_record = {
        **normalized_record,
        "reid": unique_reid,
        "pin": unique_pin,
        "source_url": build_durham_source_url(unique_pin),
        "raw_record": {
            **dict(normalized_record["raw_record"]),
            "REID": unique_reid,
            "PIN": unique_pin,
        },
    }
    property_data_source_id = ensure_durham_data_source(graph_conn)
    property_jurisdiction_id = ensure_durham_jurisdiction(graph_conn)
    inserted, skipped, errors = load_durham_records(
        graph_conn,
        property_data_source_id,
        property_jurisdiction_id,
        [normalized_record],
    )
    assert (inserted, skipped, errors) == (1, 0, 0)

    campaign_count, property_count, _, _ = _load_mixed_domain_edges(graph_conn, limit=1000)
    assert campaign_count >= 1
    assert property_count >= 1

    property_person_id = _person_id_by_source_record_key(
        graph_conn,
        source_record_key=unique_reid,
        extraction_role="owner",
    )

    return CrossDomainPossibleMatchFixtureSet(
        campaign_person_id=campaign_person_id,
        property_person_id=property_person_id,
        campaign_source_record_key=contribution_sub_id,
        property_source_record_key=unique_reid,
    )


def assert_cross_domain_possible_match_provenance(
    graph_conn: psycopg.Connection,
    *,
    fixtures: CrossDomainPossibleMatchFixtureSet,
    donor_person_id: UUID | None = None,
    owner_person_id: UUID | None = None,
) -> None:
    resolved_donor_person_id = donor_person_id or fixtures.campaign_person_id
    resolved_owner_person_id = owner_person_id or fixtures.property_person_id

    assert resolved_donor_person_id == fixtures.campaign_person_id
    assert resolved_owner_person_id == fixtures.property_person_id

    with graph_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                es.entity_id,
                es.extraction_role,
                ds.domain,
                sr.source_record_key
            FROM core.entity_source es
            JOIN core.source_record sr ON sr.id = es.source_record_id
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE es.entity_type = 'person'
              AND es.entity_id = ANY(%s)
            ORDER BY es.entity_id, sr.source_record_key
            """,
            ([resolved_donor_person_id, resolved_owner_person_id],),
        )
        source_rows = cursor.fetchall()

    assert {
        (row["entity_id"], row["extraction_role"], row["domain"], row["source_record_key"]) for row in source_rows
    } == {
        (resolved_donor_person_id, "donor", "campaign_finance", fixtures.campaign_source_record_key),
        (resolved_owner_person_id, "owner", "property", fixtures.property_source_record_key),
    }
