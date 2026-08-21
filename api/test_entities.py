from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.models.entities import PersonResponse
from api.test_campaign_finance_support import (
    CandidateRowSeed,
    insert_candidate_row,
    insert_data_source_for_test,
    insert_source_record_for_test,
)
from api.test_civics import (
    _database_current_date,
    _insert_candidacy,
    _insert_contest,
    _insert_office,
    _insert_officeholding,
)
from api.queries.civics import fetch_current_office_for_person
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

_SOURCE_RECORD_PULL_AT = datetime(2026, 7, 10, 9, 20, 44, tzinfo=timezone.utc)
_LATER_DATA_SOURCE_PULL_AT = datetime(2026, 7, 25, 7, 35, 34, tzinfo=timezone.utc)


def _ensure_durham_officeholder(db_conn: psycopg.Connection) -> UUID:
    person_row = db_conn.execute(
        "SELECT id FROM core.person WHERE canonical_name = %s ORDER BY id LIMIT 1",
        ("Carl Rist",),
    ).fetchone()
    if person_row is None:
        person = Person(canonical_name="Carl Rist", first_name="Carl", last_name="Rist")
        insert_person(db_conn, person)
        person_id = person.id
    else:
        person_id = person_row[0]

    current_office_row = db_conn.execute(
        """
        SELECT oh.id
        FROM civic.officeholding oh
        JOIN civic.office o ON o.id = oh.office_id
        WHERE oh.person_id = %s
          AND oh.valid_period @> CURRENT_DATE
          AND o.title = 'City Council Member'
          AND o.office_level = 'municipal'
        LIMIT 1
        """,
        (person_id,),
    ).fetchone()
    if current_office_row is None:
        office_id = _insert_office(
            db_conn,
            name=f"durham_nc_city_council_member_{uuid4().hex}",
            title="City Council Member",
            office_level="municipal",
            state="NC",
        )
        _insert_officeholding(db_conn, person_id=person_id, office_id=office_id)
    return person_id


def _get_person_sources_with_data_source_pull_state(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    *,
    last_pull_at: datetime | None,
    last_pull_status: str | None,
) -> list[dict[str, object]]:
    person = Person(canonical_name="Freshness Contract Person", first_name="Freshness", last_name="Contract")
    insert_person(db_conn, person)
    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="federal/fec",
        name_suffix=str(uuid4()),
        last_pull_at=last_pull_at,
        last_pull_status=last_pull_status,
    )
    source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=uuid4(),
        data_source_id=data_source.id,
        source_record_key=f"freshness-{uuid4()}",
        source_url="https://example.org/record/freshness-contract",
        pull_date=_SOURCE_RECORD_PULL_AT,
    )
    insert_entity_source(db_conn, "person", person.id, source_record.id, "candidate")

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code == 200
    return response.json()["sources"]


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


def test_get_person_returns_durham_current_office(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id = _ensure_durham_officeholder(db_conn)

    response = api_client.get(f"/v1/person/{person_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(person_id)
    assert payload["canonical_name"] == "Carl Rist"
    assert payload["current_office"]["office_name"] == "City Council Member"
    assert payload["current_office"]["office_level"] == "municipal"


@pytest.mark.parametrize(
    ("higher_level", "lower_level"),
    [
        ("federal", "state"),
        ("state", "county"),
        ("county", "municipal"),
        ("municipal", "judicial"),
        ("judicial", "school_board"),
        ("school_board", "special_district"),
    ],
)
def test_current_office_uses_canonical_level_order(
    db_conn: psycopg.Connection,
    higher_level: str,
    lower_level: str,
) -> None:
    person = Person(canonical_name=f"Office Priority {higher_level}")
    insert_person(db_conn, person)
    lower_office_id = _insert_office(
        db_conn,
        name=f"priority_lower_{uuid4().hex}",
        title=f"{lower_level} office",
        office_level=lower_level,
    )
    higher_office_id = _insert_office(
        db_conn,
        name=f"priority_higher_{uuid4().hex}",
        title=f"{higher_level} office",
        office_level=higher_level,
    )
    _insert_officeholding(db_conn, person_id=person.id, office_id=lower_office_id)
    _insert_officeholding(db_conn, person_id=person.id, office_id=higher_office_id)

    current_office = fetch_current_office_for_person(db_conn, person.id)

    assert current_office is not None
    assert current_office["office_name"] == f"{higher_level} office"
    assert current_office["office_level"] == higher_level


def test_current_office_breaks_level_ties_by_period_then_officeholding_id(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Office Period Priority")
    insert_person(db_conn, person)
    office_ids = [
        _insert_office(
            db_conn,
            name=f"period_priority_{uuid4().hex}",
            title="City Council Member",
            office_level="municipal",
        )
        for _ in range(3)
    ]
    older_id = UUID("10000000-0000-4000-8000-000000000001")
    higher_recent_id = UUID("10000000-0000-4000-8000-000000000003")
    lower_recent_id = UUID("10000000-0000-4000-8000-000000000002")
    _insert_officeholding(
        db_conn,
        id=older_id,
        person_id=person.id,
        office_id=office_ids[0],
        valid_period="[2024-01-01,)",
    )
    _insert_officeholding(
        db_conn,
        id=higher_recent_id,
        person_id=person.id,
        office_id=office_ids[1],
        valid_period="[2025-01-01,)",
    )
    _insert_officeholding(
        db_conn,
        id=lower_recent_id,
        person_id=person.id,
        office_id=office_ids[2],
        valid_period="[2025-01-01,)",
    )

    current_office = fetch_current_office_for_person(db_conn, person.id)

    assert current_office is not None
    assert current_office["officeholding_id"] == lower_recent_id


def test_get_person_uses_latest_successful_data_source_pull_for_effective_freshness(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    sources = _get_person_sources_with_data_source_pull_state(
        api_client,
        db_conn,
        last_pull_at=_LATER_DATA_SOURCE_PULL_AT,
        last_pull_status="success",
    )

    assert [source["pull_date"] for source in sources] == ["2026-07-25T07:35:34Z"]


@pytest.mark.parametrize(
    ("last_pull_status", "last_pull_at"),
    [
        pytest.param("failed", _LATER_DATA_SOURCE_PULL_AT, id="failed"),
        pytest.param("partial", _LATER_DATA_SOURCE_PULL_AT, id="partial"),
        pytest.param(None, _LATER_DATA_SOURCE_PULL_AT, id="null-status"),
        pytest.param("success", None, id="success-with-null-time"),
    ],
)
def test_get_person_does_not_advance_freshness_for_unsuccessful_source_state(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    last_pull_status: str | None,
    last_pull_at: datetime | None,
) -> None:
    sources = _get_person_sources_with_data_source_pull_state(
        api_client,
        db_conn,
        last_pull_at=last_pull_at,
        last_pull_status=last_pull_status,
    )

    assert [source["pull_date"] for source in sources] == ["2026-07-10T09:20:44Z"]


def test_get_person_does_not_move_freshness_backward(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    sources = _get_person_sources_with_data_source_pull_state(
        api_client,
        db_conn,
        last_pull_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
        last_pull_status="success",
    )

    assert [source["pull_date"] for source in sources] == ["2026-07-10T09:20:44Z"]


def test_get_person_returns_404_for_missing_person(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/person/{uuid4()}")

    assert response.status_code == 404


def test_get_person_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/person/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "person_id"]


def test_get_person_returns_typed_response_for_model_illegal_stored_identifiers(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """RED (Stage 3 turns green): the producer half of the raw-throw class.

    ``core.person.identifiers`` is ``NOT NULL jsonb`` but unconstrained in shape,
    while ``PersonResponse.identifiers`` requires a JSON object. A stored JSON
    array is schema-legal at the column and model-illegal at the response, so
    Without the producer boundary, ``_build_entity_response`` raises an unhandled
    ``pydantic.ValidationError`` that surfaces as a 500. Per the person_detail
    Error contract, the producer returns a valid payload or a typed JSON error
    response instead of letting the stored-shape defect escape unhandled.
    """
    person = Person(
        canonical_name="Model Illegal Identifiers Person",
        first_name="Model",
        last_name="Illegal",
    )
    insert_person(db_conn, person)
    db_conn.execute(
        "UPDATE core.person SET identifiers = %s::jsonb WHERE id = %s",
        ('["x"]', person.id),
    )

    response = api_client.get(f"/v1/person/{person.id}")

    assert response.status_code in (200, 502), (
        f"expected a valid payload or a typed 502-class JSON error, got {response.status_code}"
    )
    assert response.headers.get("content-type", "").startswith("application/json")
    if response.status_code == 200:
        PersonResponse.model_validate(response.json())
    else:
        assert "detail" in response.json()


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


# ---------------------------------------------------------------------------
# Person candidacies (civibus-x8b): the person -> race surface
# ---------------------------------------------------------------------------


def _unique_fec_candidate_ids(count: int) -> list[str]:
    """Unique FEC candidate ids satisfying ck_candidate_fec_candidate_id_format.

    Format: ^[HSP][0-9][A-Z0-9]{2}[0-9]{5}$. One random base plus offsets keeps
    the ids unique within a test without a cross-draw collision chance.
    """
    base = uuid4().int % 100000
    return [f"S8ZZ{(base + offset) % 100000:05d}" for offset in range(count)]


class TestPersonCandidacies:
    """`candidacies` on the person-detail payload (civibus-x8b).

    THE JOIN RULE UNDER TEST: a person's races must resolve through BOTH
    civic.candidacy.person_id (direct) AND the person's cf.candidate rows via
    candidacy.candidate_number -> cf.candidate.fec_candidate_id. Production
    holds chamber-switching incumbents as TWO person rows: the candidacy is
    bound to an FEC-only shadow person while cf.candidate.person_id points at
    the bioguide-anchored spine person (the aug20 shadow-person lesson,
    civibus-5lm). A person_id-only join returns nothing for exactly the
    highest-profile people; every value asserted here is hand-calculated.
    """

    def test_person_with_direct_candidacy_lists_the_race_with_contest_identity(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        suffix = uuid4().hex[:12]
        person = Person(canonical_name=f"Direct Candidacy Person {suffix}")
        insert_person(db_conn, person)
        (fec_candidate_id,) = _unique_fec_candidate_ids(1)

        current_date = _database_current_date(db_conn)
        election_date = current_date + timedelta(days=90)
        office_id = _insert_office(
            db_conn,
            name=f"test_x8b_senate_{suffix}",
            office_level="federal",
            title="Test Senator",
            state="ZZ",
        )
        contest_id = _insert_contest(
            db_conn,
            name=f"Zavala Test Senate — General ({suffix})",
            office_id=office_id,
            election_date=election_date,
            election_type="general",
        )
        candidacy_id = _insert_candidacy(
            db_conn,
            person_id=person.id,
            contest_id=contest_id,
            party="DEM",
            status="qualified",
            incumbent_challenge="C",
            candidate_number=fec_candidate_id,
        )

        response = api_client.get(f"/v1/person/{person.id}")

        assert response.status_code == 200
        candidacies = response.json()["candidacies"]
        assert candidacies == [
            {
                "candidacy_id": str(candidacy_id),
                "contest_id": str(contest_id),
                "contest_name": f"Zavala Test Senate — General ({suffix})",
                "election_date": election_date.isoformat(),
                "election_type": "general",
                "office_id": str(office_id),
                "office_name": "Test Senator",
                "office_level": "federal",
                "party": "DEM",
                "status": "qualified",
                "incumbent_challenge": "C",
                "fec_candidate_id": fec_candidate_id,
            }
        ]

    def test_spine_person_reaches_the_race_through_the_fec_candidate_id(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        """The two-row world: candidacy on the shadow row, money on the spine row.

        Red-capable proof of the join rule: the candidacy's person_id points at
        the FEC-only shadow person, while cf.candidate.person_id points at the
        bioguide-anchored spine person. A person_id-only join returns [] for
        the spine person — exactly the live Ossoff-class defect — so this test
        fails red under that implementation. Both rows must reach the race
        until the Tuesday spine convergence merges them.
        """
        suffix = uuid4().hex[:12]
        shadow_person = Person(canonical_name=f"OSSIFY SHADOW, T. {suffix}")
        spine_person = Person(canonical_name=f"Ossify Spine {suffix}")
        for row in (shadow_person, spine_person):
            insert_person(db_conn, row)
        (fec_candidate_id,) = _unique_fec_candidate_ids(1)

        current_date = _database_current_date(db_conn)
        election_date = current_date + timedelta(days=60)
        office_id = _insert_office(
            db_conn,
            name=f"test_x8b_shadow_senate_{suffix}",
            office_level="federal",
            title="Test Senator",
            state="ZZ",
        )
        contest_id = _insert_contest(
            db_conn,
            name=f"Zavala Test Senate Shadow Split ({suffix})",
            office_id=office_id,
            election_date=election_date,
            election_type="general",
        )
        insert_candidate_row(
            db_conn,
            CandidateRowSeed(
                id=uuid4(),
                fec_candidate_id=fec_candidate_id,
                name=f"OSSIFY SHADOW, T. {suffix}",
                office="S",
                state="ZZ",
                # The FEC-money row is bound to the SPINE person, not the
                # shadow person the candidacy points at.
                person_id=spine_person.id,
            ),
        )
        candidacy_id = _insert_candidacy(
            db_conn,
            person_id=shadow_person.id,
            contest_id=contest_id,
            party="DEM",
            status="qualified",
            incumbent_challenge="I",
            candidate_number=fec_candidate_id,
        )

        spine_payload = api_client.get(f"/v1/person/{spine_person.id}").json()
        shadow_payload = api_client.get(f"/v1/person/{shadow_person.id}").json()

        # The spine person reaches the race ONLY through its cf.candidate row's
        # fec_candidate_id; person_id alone finds nothing for this row.
        assert [row["candidacy_id"] for row in spine_payload["candidacies"]] == [str(candidacy_id)]
        assert spine_payload["candidacies"][0]["contest_id"] == str(contest_id)
        assert spine_payload["candidacies"][0]["fec_candidate_id"] == fec_candidate_id
        # The shadow person reaches the same race through the direct person_id
        # binding, and the union must not duplicate the row for either person.
        assert [row["candidacy_id"] for row in shadow_payload["candidacies"]] == [str(candidacy_id)]
        assert shadow_payload["candidacies"][0]["contest_id"] == str(contest_id)

    def test_candidacies_are_ordered_nearest_election_first(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        """Same distance-from-today rule as the office page's contest list.

        Hand-calculated distances: +30 days (upcoming), -120 days (past),
        +400 days (future) => expected order +30, -120, +400.
        """
        suffix = uuid4().hex[:12]
        person = Person(canonical_name=f"Serial Candidate {suffix}")
        insert_person(db_conn, person)

        current_date = _database_current_date(db_conn)
        office_id = _insert_office(
            db_conn,
            name=f"test_x8b_ordering_{suffix}",
            office_level="federal",
            title="Test Representative",
        )
        offsets_and_types = [
            (timedelta(days=30), "general"),
            (timedelta(days=-120), "primary"),
            (timedelta(days=400), "special"),
        ]
        contest_ids_by_offset: dict[int, UUID] = {}
        for offset, election_type in offsets_and_types:
            contest_id = _insert_contest(
                db_conn,
                name=f"Ordering Contest {offset.days} ({suffix})",
                office_id=office_id,
                election_date=current_date + offset,
                election_type=election_type,
            )
            contest_ids_by_offset[offset.days] = contest_id
            _insert_candidacy(db_conn, person_id=person.id, contest_id=contest_id)

        payload = api_client.get(f"/v1/person/{person.id}").json()

        assert [row["contest_id"] for row in payload["candidacies"]] == [
            str(contest_ids_by_offset[30]),
            str(contest_ids_by_offset[-120]),
            str(contest_ids_by_offset[400]),
        ]

    def test_candidacies_exclude_contests_beyond_the_publish_horizon(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        """A corrupt filer-typo date (2929-11-08 class) must not surface here.

        Serving already refuses these dates on /election/[date] and the
        upcoming timeline; the person payload must carry the same horizon bound
        or it becomes the one public surface still linking corrupt contests.
        """
        suffix = uuid4().hex[:12]
        person = Person(canonical_name=f"Horizon Person {suffix}")
        insert_person(db_conn, person)

        current_date = _database_current_date(db_conn)
        office_id = _insert_office(
            db_conn,
            name=f"test_x8b_horizon_{suffix}",
            office_level="federal",
            title="Test Senator",
        )
        legit_contest_id = _insert_contest(
            db_conn,
            name=f"Legit Contest ({suffix})",
            office_id=office_id,
            election_date=current_date + timedelta(days=45),
            election_type="general",
        )
        corrupt_contest_id = _insert_contest(
            db_conn,
            name=f"Corrupt Far Future Contest ({suffix})",
            office_id=office_id,
            # Beyond CURRENT_DATE + 6 years: the corrupt CAND_ELECTION_YR class.
            election_date=current_date + timedelta(days=365 * 100),
            election_type="general",
        )
        _insert_candidacy(db_conn, person_id=person.id, contest_id=legit_contest_id)
        _insert_candidacy(db_conn, person_id=person.id, contest_id=corrupt_contest_id)

        payload = api_client.get(f"/v1/person/{person.id}").json()

        assert [row["contest_id"] for row in payload["candidacies"]] == [str(legit_contest_id)]

    def test_person_with_no_candidacies_serves_an_empty_list(
        self, api_client: TestClient, db_conn: psycopg.Connection
    ) -> None:
        person = Person(canonical_name=f"No Races Person {uuid4().hex[:12]}")
        insert_person(db_conn, person)

        payload = api_client.get(f"/v1/person/{person.id}").json()

        assert payload["candidacies"] == []
