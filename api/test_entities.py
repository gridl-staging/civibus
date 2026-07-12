from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import insert_data_source_for_test, insert_source_record_for_test
from core.db import (
    insert_data_source,
    insert_entity_source,
    insert_organization,
    insert_person,
    insert_person_portrait,
    insert_source_record,
)
from core.types.python.models import DataSource, Organization, Person, PersonPortrait, SourceRecord


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
        occupation="Attorney",
        education="State University",
        bio_text="Jane Doe currently serves in the state house.",
        bio_source_url="https://www.ncleg.gov/Members/Biography/H/57",
        bio_license="licensed",
        bio_pulled_at=datetime(2026, 4, 29, 14, 30, tzinfo=timezone.utc),
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
    required_bio_keys = {"bio_text", "bio_source_url", "bio_license", "bio_pulled_at"}
    assert required_bio_keys.issubset(payload.keys())
    assert payload["id"] == str(person.id)
    assert payload["canonical_name"] == person.canonical_name
    assert payload["name_variants"] == person.name_variants
    assert payload["first_name"] == person.first_name
    assert payload["middle_name"] == person.middle_name
    assert payload["last_name"] == person.last_name
    assert payload["suffix"] == person.suffix
    assert payload["occupation"] == person.occupation
    assert payload["education"] == person.education
    assert payload["date_of_birth"] == "1980-01-02"
    assert payload["year_of_birth"] == person.year_of_birth
    assert payload["bio_text"] == person.bio_text
    assert payload["bio_source_url"] == person.bio_source_url
    assert payload["bio_license"] == person.bio_license
    assert payload["bio_pulled_at"] in {"2026-04-29T14:30:00Z", "2026-04-29T14:30:00+00:00"}
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

    person_without_bio = Person(
        canonical_name="Bio Missing Person",
        first_name="Bio",
        last_name="Missing",
        occupation="Teacher",
        education="UNC",
        identifiers={"fec_candidate_id": "H0NC02001"},
    )
    insert_person(db_conn, person_without_bio)
    missing_bio_response = api_client.get(f"/v1/person/{person_without_bio.id}")
    assert missing_bio_response.status_code == 200
    missing_bio_payload = missing_bio_response.json()
    assert required_bio_keys.issubset(missing_bio_payload.keys())
    assert missing_bio_payload["occupation"] == person_without_bio.occupation
    assert missing_bio_payload["education"] == person_without_bio.education
    assert missing_bio_payload["bio_text"] is None
    assert missing_bio_payload["bio_source_url"] is None
    assert missing_bio_payload["bio_license"] is None
    assert missing_bio_payload["bio_pulled_at"] is None


def test_get_person_returns_404_for_missing_person(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/person/{uuid4()}")

    assert response.status_code == 404


def test_get_person_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/person/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "person_id"]


def test_get_person_returns_active_portrait_payload_when_present(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Portrait Active Person", first_name="Portrait", last_name="Active")
    insert_person(db_conn, person)
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"Portrait Source {uuid4()}",
        source_url="https://example.org/portrait/source",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"portrait-{uuid4()}",
        source_url="https://example.org/portrait/record",
        raw_fields={"fixture": "portrait-active"},
        pull_date=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, source_record)
    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=source_record.id,
            status="active",
            rights_status="licensed",
            image_hash="a" * 64,
            mime_type="image/jpeg",
            width_px=640,
            height_px=480,
            source_image_url="https://images.example.org/portrait-active.jpg",
        ),
    )

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    assert response.json()["portrait"] == {
        "status": "active",
        "rights_status": "licensed",
        "source_image_url": "https://images.example.org/portrait-active.jpg",
        "mime_type": "image/jpeg",
        "width_px": 640,
        "height_px": 480,
    }
    assert set(response.json()["portrait"].keys()) == {
        "status",
        "rights_status",
        "source_image_url",
        "mime_type",
        "width_px",
        "height_px",
    }
    assert "storage_uri" not in response.json()["portrait"]

    restricted_person = Person(
        canonical_name="Portrait Restricted Person",
        first_name="Portrait",
        last_name="Restricted",
    )
    insert_person(db_conn, restricted_person)
    restricted_source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"portrait-restricted-{uuid4()}",
        source_url="https://example.org/portrait/restricted-record",
        raw_fields={"fixture": "portrait-restricted"},
        pull_date=datetime(2026, 4, 1, 12, 5, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, restricted_source_record)
    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=restricted_person.id,
            source_record_id=restricted_source_record.id,
            status="active",
            rights_status="restricted",
            image_hash="c" * 64,
            mime_type="image/jpeg",
            width_px=600,
            height_px=450,
            source_image_url="https://images.example.org/portrait-restricted.jpg",
        ),
    )

    restricted_response = api_client.get(f"/v1/person/{restricted_person.id}")

    assert restricted_response.status_code == 200
    assert restricted_response.json()["portrait"] == {
        "status": "active",
        "rights_status": "restricted",
        "source_image_url": None,
        "mime_type": "image/jpeg",
        "width_px": 600,
        "height_px": 450,
    }


def test_get_person_returns_roster_sourced_active_portrait_from_existing_person_portrait_join(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Roster Portrait Person", first_name="Roster", last_name="Portrait")
    insert_person(db_conn, person)
    data_source = DataSource(
        domain="civics",
        jurisdiction="state/NC",
        name=f"Official Roster {uuid4()}",
        source_url="https://www.ncleg.gov/Members/MemberList/H",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"official-roster-{uuid4()}",
        source_url="https://www.ncleg.gov/Members/MemberList/H",
        raw_fields={"fixture": "official-roster"},
        pull_date=datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, source_record)
    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=source_record.id,
            status="active",
            rights_status="licensed",
            image_hash="e" * 64,
            mime_type="image/jpeg",
            width_px=320,
            height_px=400,
            source_image_url="https://www.ncleg.gov/Members/MemberImage/H/57/Low",
        ),
    )

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    assert response.json()["portrait"] == {
        "status": "active",
        "rights_status": "licensed",
        "source_image_url": "https://www.ncleg.gov/Members/MemberImage/H/57/Low",
        "mime_type": "image/jpeg",
        "width_px": 320,
        "height_px": 400,
    }
    assert set(response.json()["portrait"].keys()) == {
        "status",
        "rights_status",
        "source_image_url",
        "mime_type",
        "width_px",
        "height_px",
    }


def test_get_person_filters_non_active_portrait_row_from_response(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Portrait Non Active Person", first_name="Portrait", last_name="Inactive")
    insert_person(db_conn, person)
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"Portrait Source {uuid4()}",
        source_url="https://example.org/portrait/source",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"portrait-{uuid4()}",
        source_url="https://example.org/portrait/record",
        raw_fields={"fixture": "portrait-not-found"},
        pull_date=datetime(2026, 4, 1, 13, 0, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, source_record)
    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=source_record.id,
            status="not_found",
            rights_status="unknown",
            image_hash="b" * 64,
            source_image_url="https://images.example.org/portrait-not-found.jpg",
        ),
    )

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    assert response.json()["portrait"] is None


def test_get_person_filters_takedown_requested_portrait_row_from_response(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Portrait Takedown Person", first_name="Portrait", last_name="Takedown")
    insert_person(db_conn, person)
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"Portrait Source {uuid4()}",
        source_url="https://example.org/portrait/source",
    )
    insert_data_source(db_conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"portrait-{uuid4()}",
        source_url="https://example.org/portrait/record",
        raw_fields={"fixture": "portrait-takedown-requested"},
        pull_date=datetime(2026, 4, 1, 13, 5, tzinfo=timezone.utc),
    )
    insert_source_record(db_conn, source_record)
    insert_person_portrait(
        db_conn,
        PersonPortrait(
            person_id=person.id,
            source_record_id=source_record.id,
            status="takedown_requested",
            rights_status="restricted",
            image_hash="d" * 64,
            source_image_url="https://images.example.org/portrait-takedown-requested.jpg",
        ),
    )

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    assert response.json()["portrait"] is None


def test_get_person_returns_null_portrait_when_no_portrait_row_exists(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Portrait Missing Person", first_name="Portrait", last_name="Missing")
    insert_person(db_conn, person)

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    assert response.json()["portrait"] is None


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
