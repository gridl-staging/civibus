from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_property_support import seed_parcel_detail_fixture, seed_parcel_list_fixture

pytestmark = pytest.mark.integration


def test_get_parcel_returns_detail_with_nested_rows_and_row_level_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_parcel_detail_fixture(db_conn)

    response = api_client.get(f"/v1/parcels/{fixture_ids['parcel_id']}")

    assert response.status_code == 200
    payload = response.json()

    assert payload["id"] == str(fixture_ids["parcel_id"])
    assert payload["reid"] == "200000001"
    assert payload["pin"] == "0999999999"
    assert payload["site_address"] == "123 MAIN ST"
    assert payload["property_description"] == "Single family home"
    assert payload["city"] == "Durham"
    assert payload["zoning_class"] == "R-20"
    assert payload["land_class"] == "Residential"
    assert payload["acreage"] == "1.2500"
    assert payload["deed_date"] == "2024-01-15"
    assert payload["deed_book"] == "1234"
    assert payload["deed_page"] == "567"
    assert payload["is_pending"] is False
    assert [source["source_record_key"] for source in payload["sources"]] == ["parcel-detail"]

    assert [row["id"] for row in payload["assessments"]] == [
        str(fixture_ids["assessment_ids_in_order"][0]),
        str(fixture_ids["assessment_ids_in_order"][1]),
    ]
    assert [row["tax_year"] for row in payload["assessments"]] == [2025, 2024]
    assert [row["source_record_key"] for row in (item["sources"][0] for item in payload["assessments"])] == [
        "assessment-2025",
        "assessment-2024",
    ]

    assert [row["id"] for row in payload["ownership"]] == [
        str(fixture_ids["ownership_ids_in_order"][0]),
        str(fixture_ids["ownership_ids_in_order"][1]),
    ]
    assert payload["ownership"][0]["owner_person_id"] == str(fixture_ids["owner_person_id"])
    assert payload["ownership"][0]["owner_organization_id"] is None
    assert payload["ownership"][0]["owner_address_id"] == str(fixture_ids["owner_address_id"])
    assert payload["ownership"][0]["valid_period"] == "[2025-02-01,)"
    assert payload["ownership"][0]["date_precision"] == "day"
    assert payload["ownership"][1]["owner_person_id"] is None
    assert payload["ownership"][1]["owner_organization_id"] == str(fixture_ids["owner_organization_id"])
    assert payload["ownership"][1]["owner_address_id"] == str(fixture_ids["owner_address_id"])
    assert payload["ownership"][1]["owner_mail_line3"] == "SUITE 10"
    assert payload["ownership"][1]["valid_period"] == "[2024-02-01,2025-02-01)"
    assert payload["ownership"][1]["date_precision"] == "month"
    assert [row["source_record_key"] for row in (item["sources"][0] for item in payload["ownership"])] == [
        "ownership-person",
        "ownership-org",
    ]

    assert "source_record_id" not in payload
    assert "created_at" not in payload
    assert "updated_at" not in payload


def test_get_parcel_returns_404_for_unknown_parcel(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/parcels/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Parcel not found"}


def test_get_parcel_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/parcels/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "parcel_id"]


def test_list_parcels_uses_deterministic_default_sort_and_stable_pagination(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_parcel_list_fixture(db_conn)

    first_page = api_client.get("/v1/parcels", params={"limit": 2, "offset": 0})
    second_page = api_client.get("/v1/parcels", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    first_page_payload = first_page.json()
    second_page_payload = second_page.json()

    assert [row["id"] for row in first_page_payload] == [
        str(fixture_ids["parcel_alpha_a"]),
        str(fixture_ids["parcel_alpha_b"]),
    ]
    assert [row["id"] for row in second_page_payload] == [
        str(fixture_ids["parcel_beta"]),
        str(fixture_ids["parcel_gamma"]),
    ]
    assert first_page_payload[0]["sources"][0]["source_record_key"] == "parcel-alpha-a"
    assert first_page_payload[1]["sources"][0]["source_record_key"] == "parcel-alpha-b"
    assert second_page_payload[0]["sources"][0]["source_record_key"] == "parcel-beta"
    assert second_page_payload[1]["sources"] == []


def test_list_parcels_filters_city_zoning_and_acreage(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_parcel_list_fixture(db_conn)

    city_filtered = api_client.get("/v1/parcels", params={"city": "Durham"})
    zoning_filtered = api_client.get("/v1/parcels", params={"zoning_class": "C-2"})
    acreage_filtered = api_client.get("/v1/parcels", params={"min_acreage": "1.8", "max_acreage": "3.1"})

    assert city_filtered.status_code == 200
    assert zoning_filtered.status_code == 200
    assert acreage_filtered.status_code == 200

    assert [row["id"] for row in city_filtered.json()] == [
        str(fixture_ids["parcel_alpha_a"]),
        str(fixture_ids["parcel_alpha_b"]),
        str(fixture_ids["parcel_gamma"]),
    ]
    assert [row["id"] for row in zoning_filtered.json()] == [str(fixture_ids["parcel_beta"])]
    assert [row["id"] for row in acreage_filtered.json()] == [
        str(fixture_ids["parcel_alpha_b"]),
        str(fixture_ids["parcel_beta"]),
    ]


def test_list_parcels_returns_empty_result_set(api_client: TestClient, db_conn: psycopg.Connection) -> None:
    seed_parcel_list_fixture(db_conn)

    response = api_client.get("/v1/parcels", params={"city": "Charlotte"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    ("params", "message_fragment", "query_key"),
    [
        ({"min_acreage": "4.0", "max_acreage": "2.0"}, "min_acreage must be less than or equal to max_acreage", None),
        ({"limit": "0"}, "greater than or equal to 1", "limit"),
        ({"limit": "201"}, "less than or equal to 200", "limit"),
        ({"offset": "-1"}, "greater than or equal to 0", "offset"),
    ],
)
def test_list_parcels_rejects_invalid_query_ranges_and_bounds(
    api_client: TestClient,
    params: dict[str, str],
    message_fragment: str,
    query_key: str | None,
) -> None:
    response = api_client.get("/v1/parcels", params=params)

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert message_fragment in detail["msg"]
    assert detail["loc"][0] == "query"
    if query_key is not None:
        assert detail["loc"][1] == query_key
