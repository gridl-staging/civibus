from __future__ import annotations

from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import CommitteeRowSeed, insert_committee_row
from api.test_civics import _insert_candidacy, _insert_contest, _insert_office, _insert_officeholding
from core.db import insert_organization, insert_person
from core.types.python.models import Organization, Person

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("entity_type", "expected_id", "expected_name"),
    [
        ("person", UUID("00000000-0000-0000-0000-000000000301"), "Filter Match Person"),
        ("org", UUID("00000000-0000-0000-0000-000000000302"), "Filter Match Org"),
        ("committee", UUID("00000000-0000-0000-0000-000000000303"), "Filter Match Committee"),
    ],
)
def test_search_filters_by_entity_type(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    entity_type: str,
    expected_id: UUID,
    expected_name: str,
) -> None:
    insert_person(
        db_conn,
        Person(
            id=UUID("00000000-0000-0000-0000-000000000301"),
            canonical_name="Filter Match Person",
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            id=UUID("00000000-0000-0000-0000-000000000302"),
            canonical_name="Filter Match Org",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000303"),
            fec_committee_id="C20000001",
            name="Filter Match Committee",
        ),
    )

    response = api_client.get("/v1/search", params={"q": "filter", "entity_type": entity_type})

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": entity_type,
            "entity_id": str(expected_id),
            "name": expected_name,
        }
    ]


def test_search_without_entity_type_returns_union_with_stable_order_and_pagination(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_organization(
        db_conn,
        Organization(
            id=UUID("00000000-0000-0000-0000-000000000090"),
            canonical_name="Civibus Alliance",
        ),
    )
    insert_person(
        db_conn,
        Person(
            id=UUID("00000000-0000-0000-0000-000000000100"),
            canonical_name="Civibus Alliance",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000110"),
            fec_committee_id="C20000002",
            name="Civibus Alliance",
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            id=UUID("00000000-0000-0000-0000-000000000200"),
            canonical_name="Civibus Network",
        ),
    )

    first_page = api_client.get("/v1/search", params={"q": "civ", "limit": 2, "offset": 0})
    second_page = api_client.get("/v1/search", params={"q": "civ", "limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json() == [
        {
            "entity_type": "org",
            "entity_id": "00000000-0000-0000-0000-000000000090",
            "name": "Civibus Alliance",
        },
        {
            "entity_type": "person",
            "entity_id": "00000000-0000-0000-0000-000000000100",
            "name": "Civibus Alliance",
        },
    ]
    assert second_page.json() == [
        {
            "entity_type": "committee",
            "entity_id": "00000000-0000-0000-0000-000000000110",
            "name": "Civibus Alliance",
        },
        {
            "entity_type": "org",
            "entity_id": "00000000-0000-0000-0000-000000000200",
            "name": "Civibus Network",
        },
    ]


def test_search_single_entity_hybrid_contains_outranks_trigram_fallback(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    contains_match_id = UUID("00000000-0000-0000-0000-000000000320")
    trigram_only_id = UUID("00000000-0000-0000-0000-000000000321")
    insert_person(
        db_conn,
        Person(
            id=contains_match_id,
            canonical_name="Alexandria Stone",
        ),
    )
    insert_person(
        db_conn,
        Person(
            id=trigram_only_id,
            canonical_name="Stone, Alexandria",
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "alexandria stone", "entity_type": "person"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "person",
            "entity_id": str(contains_match_id),
            "name": "Alexandria Stone",
        },
        {
            "entity_type": "person",
            "entity_id": str(trigram_only_id),
            "name": "Stone, Alexandria",
        },
    ]


def test_search_union_hybrid_contains_outranks_trigram_fallback(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    contains_match_id = UUID("00000000-0000-0000-0000-000000000330")
    trigram_only_id = UUID("00000000-0000-0000-0000-000000000331")
    insert_organization(
        db_conn,
        Organization(
            id=contains_match_id,
            canonical_name="Alexandria Stone Project",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=trigram_only_id,
            fec_committee_id="C20000003",
            name="Stone Alexandria PAC",
        ),
    )

    response = api_client.get("/v1/search", params={"q": "alexandria stone"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "org",
            "entity_id": str(contains_match_id),
            "name": "Alexandria Stone Project",
        },
        {
            "entity_type": "committee",
            "entity_id": str(trigram_only_id),
            "name": "Stone Alexandria PAC",
        },
    ]


def test_search_trigram_similarity_tie_breaks_by_name_then_entity_id(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    lower_id = UUID("00000000-0000-0000-0000-000000000340")
    higher_id = UUID("00000000-0000-0000-0000-000000000341")
    insert_organization(
        db_conn,
        Organization(
            id=higher_id,
            canonical_name="Civibus Alliance",
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            id=lower_id,
            canonical_name="Civibus Alliance",
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "civibus allaince", "entity_type": "org"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "org",
            "entity_id": str(lower_id),
            "name": "Civibus Alliance",
        },
        {
            "entity_type": "org",
            "entity_id": str(higher_id),
            "name": "Civibus Alliance",
        },
    ]


def test_search_treats_like_wildcards_as_literal_characters(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    percent_name_id = UUID("00000000-0000-0000-0000-000000000410")
    broad_match_id = UUID("00000000-0000-0000-0000-000000000411")
    insert_person(
        db_conn,
        Person(
            id=percent_name_id,
            canonical_name="Donor 100% Group",
        ),
    )
    insert_person(
        db_conn,
        Person(
            id=broad_match_id,
            canonical_name="Donor 1000 Group",
        ),
    )

    response = api_client.get("/v1/search", params={"q": "100%", "entity_type": "person"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "person",
            "entity_id": str(percent_name_id),
            "name": "Donor 100% Group",
        }
    ]


@pytest.mark.parametrize(
    "q_value",
    ["a%", "a_", "o'", "a--", "'; DROP TABLE"],
)
def test_search_hostile_input_returns_200_without_sql_errors(
    api_client: TestClient,
    q_value: str,
) -> None:
    response = api_client.get("/v1/search", params={"q": q_value})

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize(
    ("params", "field_name"),
    [
        ({"q": "a"}, "q"),
        ({"q": "ci", "entity_type": "invalid_type"}, "entity_type"),
        ({"q": "ci", "limit": 0}, "limit"),
        ({"q": "ci", "offset": -1}, "offset"),
        ({"q": "x" * 101}, "q"),
    ],
)
def test_search_invalid_query_params_return_422(
    api_client: TestClient,
    params: dict[str, str | int],
    field_name: str,
) -> None:
    response = api_client.get("/v1/search", params=params)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", field_name]


# ---------------------------------------------------------------------------
# Sprint 2: Candidate and office search
# ---------------------------------------------------------------------------


def test_search_candidate_entity_type(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(
        id=UUID("00000000-0000-0000-0000-000000000501"),
        canonical_name="Candidate Searchable",
    )
    insert_person(db_conn, person)
    office_id = _insert_office(db_conn, name="test_search_office_cand", office_level="federal")
    contest_id = _insert_contest(db_conn, name="Test Search Contest", office_id=office_id)
    _insert_candidacy(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000502"),
        person_id=person.id,
        contest_id=contest_id,
        party="DEM",
        status="qualified",
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "candidate searchable", "entity_type": "candidate"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "candidate",
            "entity_id": str(person.id),
            "name": "Candidate Searchable",
        }
    ]


def test_search_office_entity_type(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000510"),
        name="test_xyzunique_quartzelbow",
        office_level="federal",
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "xyzunique quartzelbow", "entity_type": "office"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "office",
            "entity_id": str(office_id),
            "name": "test_xyzunique_quartzelbow",
        }
    ]


def test_search_union_includes_all_five_entity_types(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_person(
        db_conn,
        Person(
            id=UUID("00000000-0000-0000-0000-000000000520"),
            canonical_name="Fiveway Match Person",
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            id=UUID("00000000-0000-0000-0000-000000000521"),
            canonical_name="Fiveway Match Org",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000522"),
            fec_committee_id="C20000010",
            name="Fiveway Match Committee",
        ),
    )
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000523"),
        name="Fiveway Match Office",
        office_level="federal",
    )
    # candidate: person + candidacy
    cand_person = Person(
        id=UUID("00000000-0000-0000-0000-000000000524"),
        canonical_name="Fiveway Match Candidate",
    )
    insert_person(db_conn, cand_person)
    contest_id = _insert_contest(db_conn, name="Fiveway Contest", office_id=office_id)
    _insert_candidacy(
        db_conn,
        person_id=cand_person.id,
        contest_id=contest_id,
        party="IND",
        status="filed",
    )

    response = api_client.get("/v1/search", params={"q": "fiveway match", "limit": 10})

    assert response.status_code == 200
    result_types = {r["entity_type"] for r in response.json()}
    assert result_types == {"person", "org", "committee", "office", "candidate"}


def test_search_candidate_does_not_return_non_candidate_persons(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """A person who is NOT a candidate should not appear in entity_type=candidate results."""
    insert_person(
        db_conn,
        Person(
            id=UUID("00000000-0000-0000-0000-000000000530"),
            canonical_name="Noncand Searchperson",
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "noncand searchperson", "entity_type": "candidate"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_search_officeholder_not_confused_with_candidate(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Officeholder-only person should not appear in candidate search, and vice versa."""
    holder_person = Person(
        id=UUID("00000000-0000-0000-0000-000000000540"),
        canonical_name="Holderonly Searchperson",
    )
    insert_person(db_conn, holder_person)
    office_id = _insert_office(db_conn, name="test_search_holder_office", office_level="state", state="WA")
    _insert_officeholding(db_conn, person_id=holder_person.id, office_id=office_id)

    response = api_client.get(
        "/v1/search",
        params={"q": "holderonly searchperson", "entity_type": "candidate"},
    )

    assert response.status_code == 200
    assert response.json() == []
