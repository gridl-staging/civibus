"""Integration tests for campaign-finance slug lookup and paginated list endpoints."""

from __future__ import annotations

from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import (
    CandidateRowSeed,
    CommitteeRowSeed,
    insert_candidate_row,
    insert_committee_row,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Candidate slug-lookup tests
# ---------------------------------------------------------------------------


def test_candidate_slug_returns_single_match(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000501"),
            fec_candidate_id="H0GA01001",
            name="Jane A Doe",
            office="H",
            state="GA",
            party="DEM",
        ),
    )
    # Different name — should not match slug "jane-a-doe"
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000502"),
            fec_candidate_id="H0GA01002",
            name="Janet Doe",
            office="H",
            state="GA",
        ),
    )

    response = api_client.get("/v1/candidates/by-slug/jane-a-doe")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == "00000000-0000-0000-0000-000000000501"
    assert items[0]["slug"] == "jane-a-doe"
    assert items[0]["slug_is_unique"] is True
    assert items[0]["name"] == "Jane A Doe"
    assert items[0]["party"] == "DEM"
    assert items[0]["office"] == "H"
    assert items[0]["state"] == "GA"


def test_candidate_slug_collision_returns_multiple_with_unique_false(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000511"),
            fec_candidate_id="H0NC01001",
            name="Alice Smith",
            office="H",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000510"),
            fec_candidate_id="S0OH00001",
            name="Alice Smith",
            office="S",
            state="OH",
        ),
    )

    response = api_client.get("/v1/candidates/by-slug/alice-smith")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    # Ordered by name ASC, id ASC — both have same name, so id ordering
    assert items[0]["id"] == "00000000-0000-0000-0000-000000000510"
    assert items[1]["id"] == "00000000-0000-0000-0000-000000000511"
    assert items[0]["slug_is_unique"] is False
    assert items[1]["slug_is_unique"] is False


# ---------------------------------------------------------------------------
# Committee slug-lookup tests
# ---------------------------------------------------------------------------


def test_committee_slug_returns_single_match(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000521"),
            fec_committee_id="C00000001",
            name="Friends Of Jane",
            committee_type="H",
            state="GA",
        ),
    )

    response = api_client.get("/v1/committees/by-slug/friends-of-jane")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == "00000000-0000-0000-0000-000000000521"
    assert items[0]["slug"] == "friends-of-jane"
    assert items[0]["slug_is_unique"] is True
    assert items[0]["name"] == "Friends Of Jane"


def test_committee_slug_collision_returns_multiple_with_unique_false(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000531"),
            fec_committee_id="C00000010",
            name="Victory Fund",
            state="GA",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000530"),
            fec_committee_id="C00000011",
            name="Victory Fund",
            state="OH",
        ),
    )

    response = api_client.get("/v1/committees/by-slug/victory-fund")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert items[0]["slug_is_unique"] is False
    assert items[1]["slug_is_unique"] is False


def test_slug_returns_empty_list_for_unknown(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000540"),
            fec_candidate_id="H0GA09001",
            name="Known Candidate",
            office="H",
        ),
    )

    response = api_client.get("/v1/candidates/by-slug/non-existent-person")

    assert response.status_code == 200
    assert response.json() == []


def test_slug_routes_do_not_shadow_uuid_detail_routes(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("00000000-0000-0000-0000-000000000550")
    committee_id = UUID("00000000-0000-0000-0000-000000000551")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0GA10001",
            name="Route Probe Candidate",
            office="H",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C00000020",
            name="Route Probe Committee",
        ),
    )

    # by-slug should work
    slug_resp = api_client.get("/v1/candidates/by-slug/route-probe-candidate")
    assert slug_resp.status_code == 200
    assert len(slug_resp.json()) == 1

    # by-id should still work (not shadowed)
    id_resp = api_client.get(f"/v1/candidates/{candidate_id}")
    assert id_resp.status_code == 200
    assert id_resp.json()["id"] == str(candidate_id)
    assert id_resp.json()["slug"] == "route-probe-candidate"
    assert id_resp.json()["slug_is_unique"] is True

    # Same for committees
    slug_resp_c = api_client.get("/v1/committees/by-slug/route-probe-committee")
    assert slug_resp_c.status_code == 200
    assert len(slug_resp_c.json()) == 1

    id_resp_c = api_client.get(f"/v1/committees/{committee_id}")
    assert id_resp_c.status_code == 200
    assert id_resp_c.json()["id"] == str(committee_id)
    assert id_resp_c.json()["slug"] == "route-probe-committee"
    assert id_resp_c.json()["slug_is_unique"] is True


# ---------------------------------------------------------------------------
# Paginated list endpoint tests
# ---------------------------------------------------------------------------


def _insert_candidates_for_list_tests(db_conn: psycopg.Connection) -> None:
    """Insert a small set of candidates for list/pagination testing."""
    for i in range(1, 6):
        insert_candidate_row(
            db_conn,
            CandidateRowSeed(
                id=UUID(f"00000000-0000-0000-0000-000000000{600 + i:03d}"),
                fec_candidate_id=f"H0GA{i:05d}",
                name=f"List Candidate {i}",
                office="H",
                state="GA",
                party="DEM",
            ),
        )
    # Two more in a different state
    for i in range(6, 8):
        insert_candidate_row(
            db_conn,
            CandidateRowSeed(
                id=UUID(f"00000000-0000-0000-0000-000000000{600 + i:03d}"),
                fec_candidate_id=f"S0OH{i:05d}",
                name=f"List Candidate {i}",
                office="S",
                state="OH",
            ),
        )


def test_candidate_list_returns_pagination_envelope(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?limit=50")

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "has_next" in body
    assert "offset" in body
    assert "limit" in body
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 7


def test_candidate_list_has_next_true_when_more_exist(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?limit=3&offset=0")

    body = response.json()
    assert body["has_next"] is True
    assert len(body["items"]) == 3
    assert body["limit"] == 3
    assert body["offset"] == 0


def test_candidate_list_has_next_false_on_last_page(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?limit=50&offset=0")

    body = response.json()
    assert body["has_next"] is False
    assert len(body["items"]) == 7


def test_candidate_list_items_include_slug_fields(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?limit=3")

    body = response.json()
    for item in body["items"]:
        assert "slug" in item
        assert "slug_is_unique" in item
        assert isinstance(item["slug"], str)
        assert isinstance(item["slug_is_unique"], bool)


def test_candidate_list_state_filter(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?state=OH")

    body = response.json()
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["state"] == "OH"


def test_candidate_list_office_filter(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?office=S")

    body = response.json()
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["office"] == "S"


def test_candidate_list_combined_filters_with_pagination(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_candidates_for_list_tests(db_conn)

    response = api_client.get("/v1/candidates?state=GA&office=H&limit=2&offset=0")

    body = response.json()
    assert len(body["items"]) == 2
    assert body["has_next"] is True
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_candidate_list_slug_is_unique_reflects_global_uniqueness(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """slug_is_unique must reflect global (unfiltered) uniqueness.

    Insert two candidates named "John Smith" in different states, filter to one
    state. The single "John Smith" in filtered results must still show
    slug_is_unique=False because the other "John Smith" exists globally.
    """
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000701"),
            fec_candidate_id="H0GA99001",
            name="John Smith",
            office="H",
            state="GA",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000702"),
            fec_candidate_id="S0OH99001",
            name="John Smith",
            office="S",
            state="OH",
        ),
    )

    response = api_client.get("/v1/candidates?state=GA")

    body = response.json()
    john_smiths = [item for item in body["items"] if item["name"] == "John Smith"]
    assert len(john_smiths) == 1
    # Must be False because there's a global collision with the OH "John Smith"
    assert john_smiths[0]["slug_is_unique"] is False


# ---------------------------------------------------------------------------
# Committee list endpoint tests
# ---------------------------------------------------------------------------


def _insert_committees_for_list_tests(db_conn: psycopg.Connection) -> None:
    """Insert a small set of committees for list/pagination testing."""
    for i in range(1, 5):
        insert_committee_row(
            db_conn,
            CommitteeRowSeed(
                id=UUID(f"00000000-0000-0000-0000-000000000{800 + i:03d}"),
                fec_committee_id=f"C0000{i:04d}",
                name=f"List Committee {i}",
                committee_type="H",
                state="GA",
                party="DEM",
            ),
        )
    for i in range(5, 7):
        insert_committee_row(
            db_conn,
            CommitteeRowSeed(
                id=UUID(f"00000000-0000-0000-0000-000000000{800 + i:03d}"),
                fec_committee_id=f"C0000{i:04d}",
                name=f"List Committee {i}",
                committee_type="P",
                state="OH",
            ),
        )


def test_committee_list_returns_pagination_envelope(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?limit=50")

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "has_next" in body
    assert len(body["items"]) == 6


def test_committee_list_has_next_true_when_more_exist(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?limit=2")

    body = response.json()
    assert body["has_next"] is True
    assert len(body["items"]) == 2


def test_committee_list_committee_type_filter(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?committee_type=P")

    body = response.json()
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["committee_type"] == "P"


def test_committee_list_state_filter(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?state=OH")

    body = response.json()
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert item["state"] == "OH"


def test_committee_list_has_next_false_on_last_page(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?limit=50")

    body = response.json()
    assert body["has_next"] is False
    assert len(body["items"]) == 6


def test_committee_list_items_include_slug_fields(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?limit=3")

    body = response.json()
    for item in body["items"]:
        assert "slug" in item
        assert "slug_is_unique" in item
        assert isinstance(item["slug"], str)
        assert isinstance(item["slug_is_unique"], bool)


def test_committee_list_combined_filters_with_pagination(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _insert_committees_for_list_tests(db_conn)

    response = api_client.get("/v1/committees?state=GA&committee_type=H&limit=2&offset=0")

    body = response.json()
    assert len(body["items"]) == 2
    assert body["has_next"] is True
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_committee_list_slug_is_unique_reflects_global_uniqueness(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """slug_is_unique must reflect global (unfiltered) uniqueness.

    Insert two committees named "Victory PAC" in different states, filter to one
    state. The single "Victory PAC" in filtered results must still show
    slug_is_unique=False because the other "Victory PAC" exists globally.
    """
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000901"),
            fec_committee_id="C00099001",
            name="Victory PAC",
            committee_type="P",
            state="GA",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000902"),
            fec_committee_id="C00099002",
            name="Victory PAC",
            committee_type="P",
            state="OH",
        ),
    )

    response = api_client.get("/v1/committees?state=GA")

    body = response.json()
    victory_pacs = [item for item in body["items"] if item["name"] == "Victory PAC"]
    assert len(victory_pacs) == 1
    # Must be False because there's a global collision with the OH "Victory PAC"
    assert victory_pacs[0]["slug_is_unique"] is False
