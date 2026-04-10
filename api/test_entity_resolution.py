from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_entity_resolution_support import seed_er_read_fixture

pytestmark = pytest.mark.integration


def test_list_er_clusters_filters_active_members_and_paginates_deterministically(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_er_read_fixture(db_conn)

    first_page = api_client.get("/v1/er/clusters", params={"limit": 2, "offset": 0})
    second_page = api_client.get("/v1/er/clusters", params={"limit": 2, "offset": 2})
    person_only = api_client.get("/v1/er/clusters", params={"entity_type": "person"})

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert person_only.status_code == 200

    first_payload = first_page.json()
    second_payload = second_page.json()
    person_payload = person_only.json()

    assert [row["id"] for row in first_payload] == [
        str(fixture_ids["cluster_person_top_id"]),
        str(fixture_ids["cluster_org_id"]),
    ]
    assert [row["id"] for row in second_payload] == [str(fixture_ids["cluster_person_low_id"])]
    assert [row["id"] for row in person_payload] == [
        str(fixture_ids["cluster_person_top_id"]),
        str(fixture_ids["cluster_person_low_id"]),
    ]
    assert first_payload[0]["member_count"] == 2
    assert first_payload[0]["canonical_name"] == "Jane Canonical"
    assert first_payload[1]["canonical_name"] == "Civibus Action Org"


def test_get_er_cluster_returns_active_members_with_canonical_first_and_sorted_ids(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_er_read_fixture(db_conn)

    response = api_client.get(f"/v1/er/clusters/{fixture_ids['cluster_person_top_id']}")

    assert response.status_code == 200
    payload = response.json()

    assert payload["id"] == str(fixture_ids["cluster_person_top_id"])
    assert payload["member_count"] == 2
    assert [row["entity_id"] for row in payload["members"]] == [
        str(fixture_ids["person_canonical_id"]),
        str(fixture_ids["person_alias_id"]),
    ]
    assert payload["members"][0]["is_canonical"] is True
    assert payload["members"][1]["is_canonical"] is False
    assert payload["members"][0]["canonical_name"] == "Jane Canonical"
    assert payload["members"][1]["canonical_name"] == "J. Canonical"
    assert str(fixture_ids["person_split_member_id"]) not in [row["entity_id"] for row in payload["members"]]


def test_get_er_cluster_returns_404_for_unknown_cluster(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/er/clusters/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "ER cluster not found"}


def test_get_er_cluster_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/er/clusters/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "cluster_id"]


def test_get_er_summary_counts_only_active_memberships_and_active_decisions(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    seed_er_read_fixture(db_conn)

    response = api_client.get("/v1/er/summary")

    assert response.status_code == 200
    payload = response.json()

    assert payload["total_active_clusters"] == 3
    assert payload["total_active_members"] == 4
    assert payload["total_active_matches"] == 3
    assert payload["decision_counts"] == {
        "match": 1,
        "probable_match": 0,
        "possible_match": 1,
        "no_match": 1,
    }


def test_get_entity_matches_filters_superseded_rows_and_orders_by_confidence(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_er_read_fixture(db_conn)

    response = api_client.get(
        f"/v1/er/person/{fixture_ids['person_canonical_id']}/matches",
    )

    assert response.status_code == 200
    payload = response.json()
    assert [row["confidence"] for row in payload] == [pytest.approx(0.97), pytest.approx(0.71)]
    assert [row["decision"] for row in payload] == ["match", "possible_match"]
    assert payload[0]["match_evidence"] == {"name_similarity": pytest.approx(0.98)}
    assert payload[1]["match_evidence"] == {"name_similarity": pytest.approx(0.73)}
    assert "superseded_by" not in payload[0]
    assert "superseded_at" not in payload[0]


def test_get_entity_matches_returns_results_for_entity_b_participation(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_er_read_fixture(db_conn)

    response = api_client.get(
        f"/v1/er/person/{fixture_ids['person_alias_id']}/matches",
    )

    assert response.status_code == 200
    payload = response.json()
    assert [row["entity_id_a"] for row in payload] == [str(fixture_ids["person_canonical_id"])]
    assert [row["entity_id_b"] for row in payload] == [str(fixture_ids["person_alias_id"])]
    assert [row["decision"] for row in payload] == ["match"]


def test_get_entity_matches_returns_results_for_organization_entity_type(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_er_read_fixture(db_conn)

    response = api_client.get(
        f"/v1/er/organization/{fixture_ids['org_canonical_id']}/matches",
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["entity_type"] == "organization"
    assert payload[0]["entity_id_a"] == str(fixture_ids["org_canonical_id"])
    assert payload[0]["decision"] == "no_match"


def test_get_entity_matches_returns_empty_list_when_entity_has_no_active_matches(
    api_client: TestClient,
) -> None:
    response = api_client.get(f"/v1/er/person/{uuid4()}/matches")

    assert response.status_code == 200
    assert response.json() == []


def test_get_entity_matches_rejects_unsupported_entity_type(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/er/org/{uuid4()}/matches")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "entity_type"]
