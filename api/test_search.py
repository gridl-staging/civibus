from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.test_campaign_finance_support import (
    CandidateRowSeed,
    CommitteeRowSeed,
    insert_candidate_row,
    insert_committee_row,
)
from api.test_entities import _ensure_durham_officeholder
from api.test_civics import (
    _insert_candidacy,
    _insert_contest,
    _insert_namesake_challenger_candidacy,
    _insert_office,
    _insert_officeholding,
    _seed_current_federal_members_mix,
)
from core.db import insert_organization, insert_person
from core.types.python.models import Organization, Person
from test_support.donor_search_fixture import seed_donor_search_fixture

pytestmark = pytest.mark.integration


def test_search_returns_durham_municipal_office_context(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id = _ensure_durham_officeholder(db_conn)

    response = api_client.get(
        "/v1/search",
        params={"q": "Carl Rist", "entity_type": "person"},
    )

    assert response.status_code == 200
    result = next(row for row in response.json() if row["entity_id"] == str(person_id))
    assert result == {
        "entity_type": "person",
        "entity_id": str(person_id),
        "name": "Carl Rist",
        "state": "NC",
        "party": None,
        "office_name": "City Council Member",
        "committee_type": None,
        "total_raised": None,
    }


def test_federal_counts_unchanged_after_nc_load(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn)
    before = api_client.get("/v1/congress/members")
    assert before.status_code == 200
    before_member_ids = {row["person_id"] for row in before.json()}
    assert before_member_ids

    person_id = _ensure_durham_officeholder(db_conn)
    extra_municipal_office_id = _insert_office(
        db_conn,
        name=f"durham_nc_city_council_at_large_{uuid4().hex}",
        title="City Council Member",
        office_level="municipal",
        state="NC",
    )
    _insert_officeholding(db_conn, person_id=person_id, office_id=extra_municipal_office_id)

    after = api_client.get("/v1/congress/members")
    assert after.status_code == 200
    assert after.content == before.content
    assert {row["person_id"] for row in after.json()} == before_member_ids


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
    """civibus-o9n: assert the seeded row, never the whole collection.

    The committee lane matches on trigram similarity >= 0.3 as well as ILIKE,
    so ANY committee row in the database whose name is trigram-close to the
    query is a legitimate member of the response. The previous whole-body
    equality flaked on accumulated databases (a leftover ``Committee B`` from a
    prior integration run matched and broke it). The second seed below bakes
    that failure mode into every run: it is deliberately trigram-close to the
    query, so a whole-collection assertion cannot come back — the test now
    fails the moment someone reverts the scoping, on a fresh database too.
    """
    seeded_id = UUID("00000000-0000-0000-0000-000000000560")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=seeded_id,
            fec_committee_id="C20000020",
            name="Context Search Committee",
            state="CA",
            party="DEM",
            committee_type="Q",
        ),
    )
    # Trigram-close neighbour standing in for the accumulated-database rows
    # that made the old assertion flake.
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000559"),
            fec_committee_id="C20000021",
            name="Context Search Committee Beta",
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "context search committee", "entity_type": "committee"},
    )

    assert response.status_code == 200
    assert [row for row in response.json() if row["entity_id"] == str(seeded_id)] == [
        {
            "entity_type": "committee",
            "entity_id": str(seeded_id),
            "name": "Context Search Committee",
            "state": "CA",
            "party": "DEM",
            "office_name": None,
            "committee_type": "Q",
            "total_raised": None,
        }
    ]


def test_search_candidate_filter_finds_fec_candidate_without_candidacy(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """civibus-x9d: the explicit candidate filter covers ``cf.candidate``.

    The pre-fix lane read ``civic.candidacy JOIN core.person`` only, so an FEC
    candidate with no civic candidacy — most of the dataset ``/candidates``
    browses — was invisible under ``entity_type=candidate``. Measured on
    production 2026-08-19: ``?q=ossoff&entity_type=candidate`` returned one row
    and hid the sitting senator.

    Context expectations are hand-picked from the seed: ``office_name`` carries
    the raw FEC office code (``H``/``S``/``P``) that the web layer expands
    through its existing ``FEC_CANDIDATE_OFFICE_OPTIONS`` owner, and
    ``total_raised`` carries the official FEC total so same-named candidates
    stay distinguishable in results. Fixture name is digit-free (the identity
    predicate rejects digit-bearing names) and carries a unique token.
    """
    candidate_id = UUID("00000000-0000-0000-0000-000000000601")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0GA00601",
            name="FECFILER, QUORNELIA MAE",
            office="H",
            state="GA",
            district="03",
            party="DEM",
            total_receipts=Decimal("1234.56"),
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "quornelia", "entity_type": "candidate"},
    )

    assert response.status_code == 200
    assert [row for row in response.json() if row["entity_id"] == str(candidate_id)] == [
        {
            "entity_type": "candidate",
            "entity_id": str(candidate_id),
            "name": "FECFILER, QUORNELIA MAE",
            "state": "GA",
            "party": "DEM",
            "office_name": "H",
            "committee_type": None,
            "total_raised": "1234.56",
        }
    ]


def test_search_candidate_filter_omits_identity_unsafe_fec_names(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """The candidate lane reuses the browse identity predicate, not a copy.

    ``_CANDIDATE_IDENTITY_IS_SAFE_EXPR`` is the single owner that keeps
    address-like FEC source strings off browse surfaces; search is a browse
    surface, so the same rows must stay out here. The digit-bearing name below
    is the tested specimen, and the safe sibling sharing the query token proves
    the query itself matched — the unsafe row is missing because it was
    suppressed, not because nothing matched.
    """
    unsafe_id = UUID("00000000-0000-0000-0000-000000000602")
    safe_id = UUID("00000000-0000-0000-0000-000000000603")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=unsafe_id,
            fec_candidate_id="H0GA00602",
            name="212 QUIBBLETON DR, FECFILER",
            office="H",
            state="GA",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=safe_id,
            fec_candidate_id="H0GA00603",
            name="FECFILER, QUIBBLETON SAFE",
            office="H",
            state="GA",
        ),
    )

    response = api_client.get(
        "/v1/search",
        params={"q": "quibbleton", "entity_type": "candidate"},
    )

    assert response.status_code == 200
    returned_ids = {row["entity_id"] for row in response.json()}
    assert str(safe_id) in returned_ids
    assert str(unsafe_id) not in returned_ids


def test_search_union_covers_spine_orphan_fec_candidate_and_dedupes_spine_linked(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """The union shows an FEC candidate exactly once, whichever lane owns it.

    A ``cf.candidate`` row with no ``person_id`` has no ``core.person`` row to
    represent it, so before civibus-x9d the default (union) search could not
    find it at all. It now appears through the candidate arm. A spine-linked
    row is the opposite case: its human already surfaces through the person
    lane, so the union suppresses the candidate row rather than rendering one
    human twice — but the explicit ``entity_type=candidate`` filter still
    serves the FEC record itself.
    """
    orphan_id = UUID("00000000-0000-0000-0000-000000000604")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=orphan_id,
            fec_candidate_id="S0OR00604",
            name="SEARCHFILER, ORPHANIA VEE",
            office="S",
            state="OR",
        ),
    )
    linked_person = Person(
        id=UUID("00000000-0000-0000-0000-000000000605"),
        canonical_name="Searchfiler, Linkelda",
    )
    insert_person(db_conn, linked_person)
    linked_candidate_id = UUID("00000000-0000-0000-0000-000000000606")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=linked_candidate_id,
            fec_candidate_id="S0OR00605",
            name="SEARCHFILER, LINKELDA",
            office="S",
            state="OR",
            person_id=linked_person.id,
        ),
    )

    union_response = api_client.get("/v1/search", params={"q": "searchfiler", "limit": 20})

    assert union_response.status_code == 200
    union_keys = {(row["entity_type"], row["entity_id"]) for row in union_response.json()}
    assert ("candidate", str(orphan_id)) in union_keys
    assert ("person", str(linked_person.id)) in union_keys
    # One human, one row: the linked FEC record must not add a second row for a
    # person the union already lists.
    assert ("candidate", str(linked_candidate_id)) not in union_keys

    filtered_response = api_client.get(
        "/v1/search",
        params={"q": "searchfiler", "entity_type": "candidate"},
    )

    assert filtered_response.status_code == 200
    filtered_keys = {(row["entity_type"], row["entity_id"]) for row in filtered_response.json()}
    # The explicit filter answers "which FEC candidate records match", so the
    # spine-linked record itself is served here even though the union collapses
    # it into its person row.
    assert ("candidate", str(orphan_id)) in filtered_keys
    assert ("candidate", str(linked_candidate_id)) in filtered_keys


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


def test_search_candidate_filter_does_not_cover_candidacy_only_humans(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """A civic candidacy without an FEC record is a person, not a candidate row.

    civibus-x9d moved the explicit candidate filter onto ``cf.candidate`` — the
    dataset ``/candidates`` browses — so a human whose only trace is a
    ``civic.candidacy`` is served by the person lane (union and
    ``entity_type=person``), where their candidacy already supplies party and
    sought-office context. Keeping them out of the candidate filter is what
    stops one human from carrying two badges with two different hrefs.
    """
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

    candidate_response = api_client.get(
        "/v1/search",
        params={"q": "candidate searchable", "entity_type": "candidate"},
    )

    assert candidate_response.status_code == 200
    assert [row for row in candidate_response.json() if row["entity_id"] == str(person.id)] == []

    # The person lane still finds the human, carrying the candidacy context the
    # old candidate lane used to duplicate onto a second row.
    person_response = api_client.get(
        "/v1/search",
        params={"q": "candidate searchable", "entity_type": "person"},
    )

    assert person_response.status_code == 200
    assert [row for row in person_response.json() if row["entity_id"] == str(person.id)] == [
        {
            "entity_type": "person",
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


def test_search_union_returns_one_row_per_person_with_several_candidacies(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """civibus-9hv: the union emits one row per human, not one row per candidacy.

    Before the fix this person rendered THREE rows in the cross-entity union: one
    from the person lane and one per candidacy from the candidate lane, all three
    carrying the same entity_id and therefore the same `/person/<uuid>` href
    (SEARCH_ROUTE_SEGMENT_BY_ENTITY_TYPE maps both badges to `/person/`).
    Production showed exactly this shape for `?q=ossoff` on 2026-08-19.

    The surviving row is the person lane's, and it absorbs the candidacy context
    from the MOST RECENT contest — so `state`, `party` and `office_name` here are
    the Northshore ones (2026), not the Bayside ones (2024). Asserting the later
    triple is what proves the context merge is ordered rather than arbitrary.

    Fixture names are digit-free (the campaign-finance identity predicate rejects
    names containing a digit) and carry unique tokens so they cannot collide with
    the bundled FEC sample data; every assertion is scoped to the seeded ids.
    """
    person = Person(
        id=UUID("00000000-0000-0000-0000-000000000570"),
        canonical_name="Twicefiled Searchperson",
    )
    insert_person(db_conn, person)

    # Two offices rather than two contests on one office: civic.contest is unique
    # on (office, division, election_date, election_type), and separate offices
    # let the assertion below discriminate state and office_name as well as party.
    earlier_office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000571"),
        name="Bayside Comptroller Seat",
        office_level="state",
        state="OR",
    )
    later_office_id = _insert_office(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000572"),
        name="Northshore Treasurer Seat",
        office_level="state",
        state="WA",
    )
    earlier_contest_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000573"),
        name="Bayside Cycle Alpha",
        office_id=earlier_office_id,
        election_date=date(2024, 11, 5),
    )
    later_contest_id = _insert_contest(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000574"),
        name="Northshore Cycle Beta",
        office_id=later_office_id,
        election_date=date(2026, 11, 3),
    )
    _insert_candidacy(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000575"),
        person_id=person.id,
        contest_id=earlier_contest_id,
        party="GRN",
        status="lost",
    )
    _insert_candidacy(
        db_conn,
        id=UUID("00000000-0000-0000-0000-000000000576"),
        person_id=person.id,
        contest_id=later_contest_id,
        party="LIB",
        status="qualified",
    )

    response = api_client.get("/v1/search", params={"q": "twicefiled searchperson", "limit": 10})

    assert response.status_code == 200
    rows_for_person = [row for row in response.json() if row["entity_id"] == str(person.id)]
    assert rows_for_person == [
        {
            "entity_type": "person",
            "entity_id": "00000000-0000-0000-0000-000000000570",
            "name": "Twicefiled Searchperson",
            "state": "WA",
            "party": "LIB",
            "office_name": "Northshore Treasurer Seat",
            "committee_type": None,
            "total_raised": None,
        }
    ]

    # The explicit candidate filter no longer reads civic.candidacy (civibus-x9d):
    # it covers cf.candidate, and this person has no FEC record. Their candidacies
    # stay readable as context on the single person row above, so nothing a user
    # could reach is lost — and the one-href-per-human rule now holds under the
    # filter as well as in the union.
    candidate_response = api_client.get(
        "/v1/search",
        params={"q": "twicefiled searchperson", "entity_type": "candidate"},
    )
    assert candidate_response.status_code == 200
    assert [row for row in candidate_response.json() if row["entity_id"] == str(person.id)] == []


def test_search_union_covers_every_routable_entity_type_without_duplicating_a_person(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """The union emits all six entity types, one row per underlying record.

    Rewritten 2026-08-19 for civibus-9hv, and again 2026-08-20 for civibus-x9d.
    The 9hv rewrite removed the old candidacy-based candidate arm because every
    row it emitted duplicated a person row (byte-identical name predicate, same
    entity_id, same `/person/<uuid>` href). The x9d candidate arm reads
    ``cf.candidate`` instead — records that mostly have NO ``core.person`` row —
    so a spine-orphan FEC candidate is new reach, not duplication, and belongs
    in the union. The spine-LINKED case (where a candidate row would double a
    person row) is covered by
    test_search_union_covers_spine_orphan_fec_candidate_and_dedupes_spine_linked.
    """
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("00000000-0000-0000-0000-000000000526"),
            fec_candidate_id="H0NC00526",
            name="FIVEWAY MATCH FECFILER",
            office="H",
            state="NC",
        ),
    )
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
    payload = response.json()
    result_types = {r["entity_type"] for r in payload}
    assert result_types == {"person", "org", "committee", "office", "contest", "candidate"}

    # The candidate seed still appears — once, as a person, carrying the context
    # the candidate lane used to contribute on a second row. `Fiveway Match Office`
    # is federal with no state, so `state` is None while party and office survive.
    assert [row for row in payload if row["entity_id"] == str(cand_person.id)] == [
        {
            "entity_type": "person",
            "entity_id": str(cand_person.id),
            "name": "Fiveway Match Candidate",
            "state": None,
            "party": "IND",
            "office_name": "Fiveway Match Office",
            "committee_type": None,
            "total_raised": None,
        }
    ]


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


def test_search_officeholder_person_ranks_before_namesake_challenger(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    officeholder = next(row for row in expectations if row.person_name == "Alice Representative")
    challenger_id = _insert_namesake_challenger_candidacy(
        db_conn,
        officeholder,
        person_id=UUID("00000000-0000-0000-0000-000000000044"),
    )

    response = api_client.get("/v1/search", params={"q": officeholder.person_name, "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    officeholder_key = ("person", str(officeholder.person_id))
    challenger_person_key = ("person", str(challenger_id))
    indexed_keys = {(row["entity_type"], row["entity_id"]): index for index, row in enumerate(payload)}

    assert payload[indexed_keys[officeholder_key]] == {
        "entity_type": "person",
        "entity_id": str(officeholder.person_id),
        "name": "Alice Representative",
        "state": "NC-01",
        "party": "DEM",
        "office_name": "U.S. Representative",
        "committee_type": None,
        "total_raised": None,
    }
    # The challenger's own candidacy now supplies party and sought-office on the
    # single person row (civibus-9hv). Before the union dropped the duplicate
    # candidate lane these two facts lived on a SECOND row with an identical href;
    # keeping them here is what still lets a reader tell the namesakes apart —
    # sitting member "NC-01 · DEM · U.S. Representative" versus challenger
    # "IND · us_house" — without rendering the same link twice.
    assert payload[indexed_keys[challenger_person_key]] == {
        "entity_type": "person",
        "entity_id": str(challenger_id),
        "name": "Alice Representative",
        "state": None,
        "party": "IND",
        "office_name": "us_house",
        "committee_type": None,
        "total_raised": None,
    }
    assert ("candidate", str(challenger_id)) not in indexed_keys
    assert indexed_keys[officeholder_key] < indexed_keys[challenger_person_key]


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
