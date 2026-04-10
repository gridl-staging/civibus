from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import (
    CommitteeRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_committee_row,
    insert_filing_row,
    insert_transaction_row,
)
from api.test_entity_resolution_support import ClusterMemberSeed, _insert_cluster, _insert_cluster_member
from api.test_property_support import (
    OwnershipRowSeed,
    ParcelRowSeed,
    insert_jurisdiction_for_test,
    insert_ownership_row,
    insert_parcel_row,
    insert_property_data_source_for_test,
    insert_property_source_record_for_test,
)
from core.db import insert_person
from core.types.python.models import Person

pytestmark = pytest.mark.integration


def _seed_donors_with_property_fixture(db_conn: psycopg.Connection) -> dict[str, UUID]:
    # Integration DBs may contain preloaded records; clear only the tables this endpoint reads.
    db_conn.execute("DELETE FROM cf.transaction")
    db_conn.execute("DELETE FROM prop.ownership")
    db_conn.execute("DELETE FROM prop.parcel")
    db_conn.execute("DELETE FROM core.cluster_member")
    db_conn.execute("DELETE FROM core.entity_cluster")

    committee_id = UUID("00000000-0000-0000-0000-000000005001")
    filing_id = UUID("00000000-0000-0000-0000-000000005002")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C99887766",
            name="Investigate Committee",
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="investigate-filing-1",
            committee_id=committee_id,
        ),
    )

    donor_pagination_alpha_id = UUID("00000000-0000-0000-0000-000000005101")
    donor_direct_id = UUID("00000000-0000-0000-0000-000000005102")
    donor_cluster_id = UUID("00000000-0000-0000-0000-000000005103")
    donor_nc_id = UUID("00000000-0000-0000-0000-000000005104")
    donor_pagination_zeta_id = UUID("00000000-0000-0000-0000-000000005105")
    donor_only_id = UUID("00000000-0000-0000-0000-000000005106")
    owner_cluster_id = UUID("00000000-0000-0000-0000-000000005107")
    owner_only_id = UUID("00000000-0000-0000-0000-000000005108")

    for person in [
        Person(id=donor_pagination_alpha_id, canonical_name="Aaron Pager"),
        Person(id=donor_direct_id, canonical_name="Alex Direct"),
        Person(id=donor_cluster_id, canonical_name="Blake Cluster Donor"),
        Person(id=donor_nc_id, canonical_name="Dana NC Direct"),
        Person(id=donor_pagination_zeta_id, canonical_name="Zoe Pager"),
        Person(id=donor_only_id, canonical_name="Donor Only"),
        Person(id=owner_cluster_id, canonical_name="Casey Cluster Owner"),
        Person(id=owner_only_id, canonical_name="Owner Only"),
    ]:
        insert_person(db_conn, person)

    co_data_source = insert_property_data_source_for_test(
        db_conn,
        jurisdiction="state/co",
        name_suffix=f"investigate-co-{uuid4()}",
    )
    nc_data_source = insert_property_data_source_for_test(
        db_conn,
        jurisdiction="state/nc",
        name_suffix=f"investigate-nc-{uuid4()}",
    )
    co_source_record = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000005201"),
        data_source_id=co_data_source.id,
        source_record_key="investigate-owner-co",
        source_url="https://example.org/property/investigate-owner-co",
        pull_date=datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc),
    )
    nc_source_record = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000005202"),
        data_source_id=nc_data_source.id,
        source_record_key="investigate-owner-nc",
        source_url="https://example.org/property/investigate-owner-nc",
        pull_date=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
    )

    jurisdiction_id = insert_jurisdiction_for_test(db_conn, fips="37135", name="Orange County")
    parcel_ids = [
        UUID("00000000-0000-0000-0000-000000005301"),
        UUID("00000000-0000-0000-0000-000000005302"),
        UUID("00000000-0000-0000-0000-000000005303"),
        UUID("00000000-0000-0000-0000-000000005304"),
        UUID("00000000-0000-0000-0000-000000005305"),
        UUID("00000000-0000-0000-0000-000000005306"),
    ]
    for index, parcel_id in enumerate(parcel_ids, start=1):
        insert_parcel_row(
            db_conn,
            ParcelRowSeed(
                id=parcel_id,
                reid=f"70000000{index}",
                pin=f"07777777{index:02d}",
                site_address=f"{index} INVESTIGATE ST",
                city="Durham",
                acreage=Decimal("1.0000"),
                jurisdiction_id=jurisdiction_id,
            ),
        )

    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000005401"),
            parcel_id=parcel_ids[0],
            owner_name="Alex Direct",
            owner_person_id=donor_direct_id,
            ownership_recorded_at=date(2025, 1, 1),
            source_record_id=co_source_record.id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000005402"),
            parcel_id=parcel_ids[1],
            owner_name="Casey Cluster Owner",
            owner_person_id=owner_cluster_id,
            ownership_recorded_at=date(2025, 1, 2),
            source_record_id=co_source_record.id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000005403"),
            parcel_id=parcel_ids[2],
            owner_name="Dana NC Direct",
            owner_person_id=donor_nc_id,
            ownership_recorded_at=date(2025, 1, 3),
            source_record_id=nc_source_record.id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000005404"),
            parcel_id=parcel_ids[3],
            owner_name="Aaron Pager",
            owner_person_id=donor_pagination_alpha_id,
            ownership_recorded_at=date(2025, 1, 4),
            source_record_id=co_source_record.id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000005405"),
            parcel_id=parcel_ids[4],
            owner_name="Zoe Pager",
            owner_person_id=donor_pagination_zeta_id,
            ownership_recorded_at=date(2025, 1, 5),
            source_record_id=co_source_record.id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000005406"),
            parcel_id=parcel_ids[5],
            owner_name="Owner Only",
            owner_person_id=owner_only_id,
            ownership_recorded_at=date(2025, 1, 6),
            source_record_id=co_source_record.id,
        ),
    )

    transactions = [
        (UUID("00000000-0000-0000-0000-000000005501"), donor_direct_id),
        (UUID("00000000-0000-0000-0000-000000005502"), donor_cluster_id),
        (UUID("00000000-0000-0000-0000-000000005503"), donor_nc_id),
        (UUID("00000000-0000-0000-0000-000000005504"), donor_pagination_alpha_id),
        (UUID("00000000-0000-0000-0000-000000005505"), donor_pagination_zeta_id),
        (UUID("00000000-0000-0000-0000-000000005506"), donor_only_id),
    ]
    for transaction_id, contributor_id in transactions:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="15",
                amount=Decimal("25.00"),
                amendment_indicator="N",
                contributor_person_id=contributor_id,
                transaction_date=date(2026, 3, 1),
            ),
        )

    cluster_id = UUID("00000000-0000-0000-0000-000000005601")
    _insert_cluster(
        db_conn,
        cluster_id=cluster_id,
        entity_type="person",
        canonical_entity_id=donor_cluster_id,
        cluster_confidence=0.92,
        member_count=3,
    )
    _insert_cluster_member(
        db_conn,
        ClusterMemberSeed(
            member_id=UUID("00000000-0000-0000-0000-000000005602"),
            cluster_id=cluster_id,
            entity_type="person",
            entity_id=donor_cluster_id,
            is_canonical=True,
        ),
    )
    _insert_cluster_member(
        db_conn,
        ClusterMemberSeed(
            member_id=UUID("00000000-0000-0000-0000-000000005603"),
            cluster_id=cluster_id,
            entity_type="person",
            entity_id=owner_cluster_id,
            is_canonical=False,
        ),
    )
    _insert_cluster_member(
        db_conn,
        ClusterMemberSeed(
            member_id=UUID("00000000-0000-0000-0000-000000005604"),
            cluster_id=cluster_id,
            entity_type="person",
            entity_id=donor_direct_id,
            is_canonical=False,
        ),
    )

    return {
        "donor_pagination_alpha_id": donor_pagination_alpha_id,
        "donor_direct_id": donor_direct_id,
        "donor_cluster_id": donor_cluster_id,
        "donor_nc_id": donor_nc_id,
        "donor_pagination_zeta_id": donor_pagination_zeta_id,
        "donor_only_id": donor_only_id,
        "owner_only_id": owner_only_id,
    }


def _seed_non_matching_donor_owner_fixture(db_conn: psycopg.Connection) -> None:
    db_conn.execute("DELETE FROM cf.transaction")
    db_conn.execute("DELETE FROM prop.ownership")
    db_conn.execute("DELETE FROM prop.parcel")
    db_conn.execute("DELETE FROM core.cluster_member")
    db_conn.execute("DELETE FROM core.entity_cluster")

    committee_id = UUID("00000000-0000-0000-0000-000000006001")
    filing_id = UUID("00000000-0000-0000-0000-000000006002")
    donor_only_id = UUID("00000000-0000-0000-0000-000000006003")
    owner_only_id = UUID("00000000-0000-0000-0000-000000006004")

    insert_person(db_conn, Person(id=donor_only_id, canonical_name="Donor Only"))
    insert_person(db_conn, Person(id=owner_only_id, canonical_name="Owner Only"))

    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12312312",
            name="Investigate Empty Committee",
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="investigate-empty-filing",
            committee_id=committee_id,
        ),
    )

    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("00000000-0000-0000-0000-000000006005"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="15",
            amount=Decimal("30.00"),
            amendment_indicator="N",
            contributor_person_id=donor_only_id,
            transaction_date=date(2026, 3, 2),
        ),
    )

    jurisdiction_id = insert_jurisdiction_for_test(db_conn, fips="37037", name="Chatham County")
    data_source = insert_property_data_source_for_test(
        db_conn,
        jurisdiction="state/co",
        name_suffix=f"investigate-empty-{uuid4()}",
    )
    source_record = insert_property_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000006006"),
        data_source_id=data_source.id,
        source_record_key="investigate-owner-only",
        source_url="https://example.org/property/investigate-owner-only",
        pull_date=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
    )
    parcel_id = UUID("00000000-0000-0000-0000-000000006007")
    insert_parcel_row(
        db_conn,
        ParcelRowSeed(
            id=parcel_id,
            reid="800000001",
            pin="0666666601",
            site_address="1 OWNER ONLY AVE",
            city="Durham",
            acreage=Decimal("1.0000"),
            jurisdiction_id=jurisdiction_id,
        ),
    )
    insert_ownership_row(
        db_conn,
        OwnershipRowSeed(
            id=UUID("00000000-0000-0000-0000-000000006008"),
            parcel_id=parcel_id,
            owner_name="Owner Only",
            owner_person_id=owner_only_id,
            source_record_id=source_record.id,
            ownership_recorded_at=date(2025, 2, 1),
        ),
    )


def test_investigate_donors_with_property_returns_direct_match(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = _seed_donors_with_property_fixture(db_conn)

    response = api_client.get("/v1/investigate/donors-with-property")

    assert response.status_code == 200
    payload = response.json()
    assert {
        "person_id": str(fixture_ids["donor_direct_id"]),
        "canonical_name": "Alex Direct",
        "match_type": "direct",
    } in payload


def test_investigate_donors_with_property_prefers_direct_match_when_both_paths_exist(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = _seed_donors_with_property_fixture(db_conn)

    response = api_client.get("/v1/investigate/donors-with-property")

    assert response.status_code == 200
    donor_rows = [row for row in response.json() if row["person_id"] == str(fixture_ids["donor_direct_id"])]
    assert donor_rows == [
        {
            "person_id": str(fixture_ids["donor_direct_id"]),
            "canonical_name": "Alex Direct",
            "match_type": "direct",
        }
    ]


def test_investigate_donors_with_property_returns_cluster_match(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = _seed_donors_with_property_fixture(db_conn)

    response = api_client.get("/v1/investigate/donors-with-property")

    assert response.status_code == 200
    payload = response.json()
    assert {
        "person_id": str(fixture_ids["donor_cluster_id"]),
        "canonical_name": "Blake Cluster Donor",
        "match_type": "cluster",
    } in payload


def test_investigate_donors_with_property_filters_property_jurisdiction_only(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = _seed_donors_with_property_fixture(db_conn)

    nc_response = api_client.get("/v1/investigate/donors-with-property", params={"jurisdiction": "state/nc"})
    co_response = api_client.get("/v1/investigate/donors-with-property", params={"jurisdiction": "state/co"})

    assert nc_response.status_code == 200
    assert co_response.status_code == 200

    assert [row["person_id"] for row in nc_response.json()] == [str(fixture_ids["donor_nc_id"])]
    assert str(fixture_ids["donor_nc_id"]) not in [row["person_id"] for row in co_response.json()]


def test_investigate_donors_with_property_paginates_with_deterministic_order(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = _seed_donors_with_property_fixture(db_conn)

    first_page = api_client.get("/v1/investigate/donors-with-property", params={"limit": 2, "offset": 0})
    second_page = api_client.get("/v1/investigate/donors-with-property", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    assert [row["person_id"] for row in first_page.json()] == [
        str(fixture_ids["donor_pagination_alpha_id"]),
        str(fixture_ids["donor_direct_id"]),
    ]
    assert [row["person_id"] for row in second_page.json()] == [
        str(fixture_ids["donor_cluster_id"]),
        str(fixture_ids["donor_nc_id"]),
    ]


def test_investigate_donors_with_property_returns_empty_for_non_matching_people(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _seed_non_matching_donor_owner_fixture(db_conn)

    response = api_client.get("/v1/investigate/donors-with-property")

    assert response.status_code == 200
    assert response.json() == []
