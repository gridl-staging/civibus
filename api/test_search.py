from __future__ import annotations

from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import CommitteeRowSeed, insert_committee_row
from api.test_civics import (
    _insert_candidacy,
    _insert_contest,
    _insert_office,
    _insert_officeholding,
    _seed_current_federal_members_mix,
)
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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "person",
            "entity_id": "00000000-0000-0000-0000-000000000100",
            "name": "Civibus Alliance",
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
    ]
    assert second_page.json() == [
        {
            "entity_type": "committee",
            "entity_id": "00000000-0000-0000-0000-000000000110",
            "name": "Civibus Alliance",
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "org",
            "entity_id": "00000000-0000-0000-0000-000000000200",
            "name": "Civibus Network",
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "person",
            "entity_id": str(trigram_only_id),
            "name": "Stone, Alexandria",
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "committee",
            "entity_id": str(trigram_only_id),
            "name": "Stone Alexandria PAC",
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
    ]


def test_search_office_contains_outranks_trigram_fallback(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    contains_match_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000370"),
        name="Alpha Beta Office",
        office_level="state",
        state="OR",
    )
    trigram_only_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000371"),
        name="Office, Beta Alpha",
        office_level="state",
        state="OR",
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "alpha beta office", "entity_type": "office"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "office",
            "entity_id": str(contains_match_id),
            "name": "Alpha Beta Office",
            "state": "OR",
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "office",
            "entity_id": str(trigram_only_id),
            "name": "Office, Beta Alpha",
            "state": "OR",
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
    ]


def test_search_contest_contains_outranks_trigram_fallback(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000372"),
        name="Ranking Contest Office",
        office_level="state",
        state="OR",
    )
    contains_match_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000373"),
        name="Alpha Beta Contest",
        office_id=office_id,
        election_type="general",
    )
    trigram_only_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000374"),
        name="Contest Beta Alpha",
        office_id=office_id,
        election_type="primary",
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "alpha beta contest", "entity_type": "contest"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "contest",
            "entity_id": str(contains_match_id),
            "name": "Alpha Beta Contest",
            "state": "OR",
            "party": None,
            "office_name": "Ranking Contest Office",
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "contest",
            "entity_id": str(trigram_only_id),
            "name": "Contest Beta Alpha",
            "state": "OR",
            "party": None,
            "office_name": "Ranking Contest Office",
            "committee_type": None,
            "total_raised": None,
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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        },
        {
            "entity_type": "org",
            "entity_id": str(higher_id),
            "name": "Civibus Alliance",
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
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


def test_search_populates_committee_context_fields(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000560"),
            fec_committee_id="C20000020",
            name="Context Search Committee",
            state="CA",
            party="DEM",
            committee_type="Q",
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "context search committee", "entity_type": "committee"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "committee",
            "entity_id": "00000000-0000-0000-0000-000000000560",
            "name": "Context Search Committee",
            "state": "CA",
            "party": "DEM",
            "office_name": None,
            "committee_type": "Q",
            "total_raised": None,
        }
    ]


def test_search_populates_candidate_context_fields(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_person = Person(
        id=UUID("00000000-0000-0000-0000-000000000561"),
        canonical_name="Context Candidate Person",
    )
    insert_person(db_conn, candidate_person)
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000562"),
        name="Context Candidate Office",
        office_level="state",
        state="OR",
    )
    contest_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000563"),
        name="Candidate Election 2026",
        office_id=office_id,
    )
    _insert_candidacy(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000564"),
        person_id=candidate_person.id,
        contest_id=contest_id,
        party="NPP",
        status="qualified",
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "context candidate person", "entity_type": "candidate"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "candidate",
            "entity_id": "00000000-0000-0000-0000-000000000561",
            "name": "Context Candidate Person",
            "state": "OR",
            "party": "NPP",
            "office_name": "Context Candidate Office",
            "committee_type": None,
            "total_raised": None,
        }
    ]


def test_search_populates_contest_context_fields(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000565"),
        name="Context Contest Office",
        office_level="state",
        state="WA",
    )
    contest_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000566"),
        name="Context Contest Name",
        office_id=office_id,
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "context contest name", "entity_type": "contest"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "contest",
            "entity_id": str(contest_id),
            "name": "Context Contest Name",
            "state": "WA",
            "party": None,
            "office_name": "Context Contest Office",
            "committee_type": None,
            "total_raised": None,
        }
    ]


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
            "state": None,
            "party": "DEM",
            "office_name": "test_search_office_cand",
            "committee_type": None,
            "total_raised": None,
        }
    ]


def test_search_contest_entity_type(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000505"),
        name="Contest Search Office",
        office_level="federal",
    )
    contest_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000506"),
        name="Contest Searchable Name",
        office_id=office_id,
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "contest searchable", "entity_type": "contest"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "entity_type": "contest",
            "entity_id": str(contest_id),
            "name": "Contest Searchable Name",
            "state": None,
            "party": None,
            "office_name": "Contest Search Office",
            "committee_type": None,
            "total_raised": None,
        }
    ]


def test_search_contest_matches_via_office_name(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Contest search should match on the joined office name, not just the contest name."""
    office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000507"),
        name="Xylophone Marsupial Tribunal",
        office_level="state",
        state="WA",
    )
    contest_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000508"),
        name="WA General 2026",
        office_id=office_id,
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "xylophone marsupial", "entity_type": "contest"},
    )

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0] == {
        "entity_type": "contest",
        "entity_id": str(contest_id),
        "name": "WA General 2026",
        "state": "WA",
        "party": None,
        "office_name": "Xylophone Marsupial Tribunal",
        "committee_type": None,
        "total_raised": None,
    }


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
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        }
    ]


def test_search_union_includes_all_six_entity_types(
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
    _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000525"),
        name="Fiveway Match Contest",
        office_id=office_id,
        election_type="primary",
    )

    response = api_client.get("/v1/search", params={"q": "fiveway match", "limit": 10})

    assert response.status_code == 200
    result_types = {r["entity_type"] for r in response.json()}
    assert result_types == {"person", "org", "committee", "office", "candidate", "contest"}


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


def test_search_officeholder_person_ranks_before_same_name_committee_and_bare_person(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    officeholder = next(row for row in expectations if row.person_name == "Alice Representative")
    bare_person_id = UUID("00000000-0000-0000-0000-000000000041")
    committee_id = UUID("00000000-0000-0000-0000-000000000042")
    insert_person(db_conn, Person(id=bare_person_id, canonical_name=officeholder.person_name))
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C20000041",
            name=officeholder.person_name,
        ),
    )

    response = api_client.get("/v1/search", params={"q": officeholder.person_name, "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0] == {
        "entity_type": "person",
        "entity_id": str(officeholder.person_id),
        "name": "Alice Representative",
        "state": "NC-01",
        "party": "DEM",
        "office_name": "U.S. Representative",
        "committee_type": None,
        "total_raised": None,
    }
    result_keys = {(row["entity_type"], row["entity_id"]) for row in payload}
    assert ("committee", str(committee_id)) in result_keys
    assert ("person", str(bare_person_id)) in result_keys


def test_search_officeholder_person_context_values_do_not_enrich_bare_person(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    president = next(row for row in expectations if row.person_name == "Dana President")
    bare_person_id = UUID("00000000-0000-0000-0000-000000000043")
    insert_person(db_conn, Person(id=bare_person_id, canonical_name="Dana President Bare"))

    president_response = api_client.get("/v1/search", params={"q": president.person_name, "limit": 10})
    bare_response = api_client.get("/v1/search", params={"q": "Dana President Bare", "limit": 10})

    assert president_response.status_code == 200
    assert bare_response.status_code == 200
    president_rows = president_response.json()
    assert {
        "entity_type": "person",
        "entity_id": str(president.person_id),
        "name": "Dana President",
        "state": None,
        "party": "DEM",
        "office_name": "President of the United States",
        "committee_type": None,
        "total_raised": None,
    } in president_rows
    assert bare_response.json()[0] == {
        "entity_type": "person",
        "entity_id": str(bare_person_id),
        "name": "Dana President Bare",
        "state": None,
        "party": None,
        "office_name": None,
        "committee_type": None,
        "total_raised": None,
    }
