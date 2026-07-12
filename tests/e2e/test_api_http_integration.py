from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.test_graph_support import create_graph_edge
from core.db import get_connection
from core.graph import age_post_connect, ensure_graph
from core.graph.loader import merge_committee_node, merge_person_node
from core.graph.loader_test_support import seed_committee, seed_person
from test_support.api_real_path import (
    build_real_path_client,
    configure_real_path_environment,
    restore_environment,
)

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


@dataclass(frozen=True)
class SeededRouteFixture:
    search_query: str


def _build_real_path_client() -> tuple[TestClient, dict[str, str], dict[str, str]]:
    return build_real_path_client()


def _seed_route_fixture_data() -> SeededRouteFixture:
    unique_suffix = uuid4().hex[:12]
    search_query = unique_suffix
    person_name = f"Stage1 Http Person {unique_suffix}"
    committee_name = f"Stage1 Http Committee {unique_suffix}"

    connection = get_connection(post_connect=age_post_connect)
    try:
        ensure_graph(connection)

        person_id = seed_person(connection, name=person_name)
        committee_id = seed_committee(connection, name=committee_name)
        merge_person_node(connection, person_id, person_name)
        merge_committee_node(connection, committee_id, committee_name)
        create_graph_edge(
            connection,
            source_label="Person",
            source_id=person_id,
            target_label="Committee",
            target_id=committee_id,
            edge_type="CONTRIBUTED_TO",
        )
        connection.commit()
    finally:
        connection.close()

    return SeededRouteFixture(search_query=search_query)


@pytest.fixture
def real_path_client(real_path_environment: None) -> tuple[TestClient, dict[str, str], dict[str, str]]:
    client, public_headers, admin_headers = _build_real_path_client()
    try:
        with client:
            yield client, public_headers, admin_headers
    finally:
        client.close()


@pytest.fixture(scope="module")
def real_path_environment() -> Iterator[None]:
    previous_environment = configure_real_path_environment()
    try:
        yield
    finally:
        restore_environment(previous_environment)
        sys.modules.pop("api.main", None)


@pytest.fixture(scope="module")
def seeded_route_fixture(real_path_environment: None) -> SeededRouteFixture:
    return _seed_route_fixture_data()


def test_health_is_public(real_path_client: tuple[TestClient, dict[str, str], dict[str, str]]) -> None:
    client, _, _ = real_path_client

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_accepts_public_api_key(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
) -> None:
    client, public_headers, _ = real_path_client

    response = client.get("/v1/search", params={"q": "zzstage1"}, headers=public_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_transactions_accepts_public_api_key(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
) -> None:
    client, public_headers, _ = real_path_client

    response = client.get("/v1/transactions", headers=public_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_parcels_accepts_public_api_key(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
) -> None:
    client, public_headers, _ = real_path_client

    response = client.get("/v1/parcels", headers=public_headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_person_endpoint_uses_discovered_search_id(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
    seeded_route_fixture: SeededRouteFixture,
) -> None:
    client, public_headers, _ = real_path_client

    search_response = client.get(
        "/v1/search",
        params={"q": seeded_route_fixture.search_query, "entity_type": "person"},
        headers=public_headers,
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload

    person_id = search_payload[0]["entity_id"]
    person_response = client.get(f"/v1/person/{person_id}", headers=public_headers)

    assert person_response.status_code == 200
    assert person_response.json()["id"] == person_id


def test_graph_relationships_uses_discovered_person_id(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
    seeded_route_fixture: SeededRouteFixture,
) -> None:
    client, public_headers, _ = real_path_client

    search_response = client.get(
        "/v1/search",
        params={"q": seeded_route_fixture.search_query, "entity_type": "person"},
        headers=public_headers,
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload

    person_id = search_payload[0]["entity_id"]
    graph_response = client.get(f"/v1/graph/person/{person_id}/relationships", headers=public_headers)

    assert graph_response.status_code == 200
    graph_payload = graph_response.json()
    assert graph_payload["entity_id"] == person_id
    assert graph_payload["total_count"] >= 1


def test_entity_resolution_summary_accepts_admin_key(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
) -> None:
    client, _, admin_headers = real_path_client

    response = client.get("/v1/er/summary", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert "total_active_clusters" in payload
    assert "total_active_members" in payload
    assert "total_active_matches" in payload
    assert "decision_counts" in payload


def test_entity_resolution_summary_rejects_public_key(
    real_path_client: tuple[TestClient, dict[str, str], dict[str, str]],
) -> None:
    client, public_headers, _ = real_path_client

    response = client.get("/v1/er/summary", headers=public_headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
