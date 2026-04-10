from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import insert_data_source_for_test, insert_source_record_for_test
from core.db import (
    insert_entity_source,
    insert_organization,
    insert_person,
)
from core.types.python.models import Organization, Person


pytestmark = pytest.mark.integration


def test_get_person_returns_person_response_with_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(
        canonical_name="Jane A Doe",
        name_variants=["JANE DOE"],
        first_name="JANE",
        middle_name="A",
        last_name="DOE",
        suffix="JR",
        date_of_birth=date(1980, 1, 2),
        year_of_birth=1980,
        identifiers={"fec_candidate_id": "H0NC01001"},
        primary_address_id=None,
        er_cluster_id=UUID("00000000-0000-0000-0000-000000000022"),
        er_confidence=0.93,
    )
    insert_person(db_conn, person)

    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="federal/fec",
        name_suffix=str(uuid4()),
    )
    newer_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000102"),
        data_source_id=data_source.id,
        source_record_key="person-newer",
        source_url="https://example.org/record/person-newer",
        pull_date=datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc),
    )
    tie_break_first = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000001"),
        data_source_id=data_source.id,
        source_record_key="person-tie-a",
        source_url="https://example.org/record/person-tie-a",
        pull_date=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    )
    tie_break_second = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000002"),
        data_source_id=data_source.id,
        source_record_key="person-tie-b",
        source_url="https://example.org/record/person-tie-b",
        pull_date=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "person", person.id, newer_record.id, "donor")
    insert_entity_source(db_conn, "person", person.id, newer_record.id, "candidate")
    insert_entity_source(db_conn, "person", person.id, tie_break_first.id, "donor")
    insert_entity_source(db_conn, "person", person.id, tie_break_second.id, "donor")

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(person.id)
    assert payload["canonical_name"] == person.canonical_name
    assert payload["name_variants"] == person.name_variants
    assert payload["first_name"] == person.first_name
    assert payload["middle_name"] == person.middle_name
    assert payload["last_name"] == person.last_name
    assert payload["suffix"] == person.suffix
    assert payload["date_of_birth"] == "1980-01-02"
    assert payload["year_of_birth"] == person.year_of_birth
    assert payload["identifiers"] == person.identifiers
    assert payload["primary_address_id"] is None
    assert payload["er_cluster_id"] == str(person.er_cluster_id)
    assert payload["er_confidence"] == person.er_confidence
    assert len(payload["sources"]) == 3
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "person-newer",
        "person-tie-a",
        "person-tie-b",
    ]
    assert payload["sources"][0]["data_source_name"] == data_source.name
    assert payload["sources"][0]["data_source_url"] == data_source.source_url
    assert payload["sources"][0]["domain"] == data_source.domain
    assert payload["sources"][0]["jurisdiction"] == data_source.jurisdiction
    assert payload["sources"][0]["record_url"] == "https://example.org/record/person-newer"
    assert "created_at" not in payload
    assert "updated_at" not in payload


def test_get_person_returns_404_for_missing_person(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/person/{uuid4()}")

    assert response.status_code == 404


def test_get_person_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/person/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "person_id"]


def test_get_org_returns_org_response_with_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    organization = Organization(
        canonical_name="Civibus Action Committee",
        name_variants=["CIVIBUS AC"],
        org_type="pac",
        identifiers={"fec_committee_id": "C12345678"},
        registered_state="NC",
        formation_date=date(2014, 5, 1),
        dissolution_date=None,
        primary_address_id=None,
        er_cluster_id=UUID("00000000-0000-0000-0000-000000000033"),
        er_confidence=0.91,
    )
    insert_organization(db_conn, organization)

    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="federal/fec",
        name_suffix=str(uuid4()),
    )
    source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000201"),
        data_source_id=data_source.id,
        source_record_key="org-key",
        source_url="https://example.org/record/org-key",
        pull_date=datetime(2026, 3, 16, 11, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "organization", organization.id, source_record.id, "recipient")

    response = api_client.get(f"/v1/org/{organization.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(organization.id)
    assert payload["canonical_name"] == organization.canonical_name
    assert payload["name_variants"] == organization.name_variants
    assert payload["org_type"] == organization.org_type
    assert payload["identifiers"] == organization.identifiers
    assert payload["registered_state"] == organization.registered_state
    assert payload["formation_date"] == "2014-05-01"
    assert payload["dissolution_date"] is None
    assert payload["primary_address_id"] is None
    assert payload["er_cluster_id"] == str(organization.er_cluster_id)
    assert payload["er_confidence"] == organization.er_confidence
    assert payload["sources"] == [
        {
            "domain": data_source.domain,
            "jurisdiction": data_source.jurisdiction,
            "data_source_name": data_source.name,
            "data_source_url": data_source.source_url,
            "source_record_key": "org-key",
            "record_url": "https://example.org/record/org-key",
            "pull_date": "2026-03-16T11:00:00Z",
        }
    ]
    assert "created_at" not in payload
    assert "updated_at" not in payload


def test_get_org_returns_404_for_missing_org(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/org/{uuid4()}")

    assert response.status_code == 404


def test_get_org_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/org/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "organization_id"]
