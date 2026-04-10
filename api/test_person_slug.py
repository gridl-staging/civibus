from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.db import insert_person
from core.types.python.models import Person

pytestmark = pytest.mark.integration


def test_slug_lookup_returns_single_match(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    matched_person = Person(
        id=UUID("00000000-0000-0000-0000-000000000401"),
        canonical_name="Jane A Doe",
        first_name="Jane",
        last_name="Doe",
        suffix="Jr",
    )
    insert_person(db_conn, matched_person)
    insert_person(
        db_conn,
        Person(
            id=UUID("00000000-0000-0000-0000-000000000402"),
            canonical_name="Janet Doe",
            first_name="Janet",
            last_name="Doe",
        ),
    )

    response = api_client.get("/v1/person/by-slug/jane-a-doe")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(matched_person.id),
            "canonical_name": matched_person.canonical_name,
            "first_name": matched_person.first_name,
            "last_name": matched_person.last_name,
            "suffix": matched_person.suffix,
        }
    ]


def test_slug_lookup_returns_ordered_array_for_collision(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    first_tie_id = UUID("00000000-0000-0000-0000-000000000411")
    second_tie_id = UUID("00000000-0000-0000-0000-000000000410")
    punctuation_id = UUID("00000000-0000-0000-0000-000000000412")
    insert_person(
        db_conn,
        Person(id=first_tie_id, canonical_name="Alice Smith", first_name="Alice", last_name="Smith"),
    )
    insert_person(
        db_conn,
        Person(id=second_tie_id, canonical_name="Alice Smith", first_name="Alice", last_name="Smith"),
    )
    insert_person(
        db_conn,
        Person(id=punctuation_id, canonical_name="Alice*Smith", first_name="Alice", last_name="Smith"),
    )

    response = api_client.get("/v1/person/by-slug/alice-smith")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(second_tie_id),
            "canonical_name": "Alice Smith",
            "first_name": "Alice",
            "last_name": "Smith",
            "suffix": None,
        },
        {
            "id": str(first_tie_id),
            "canonical_name": "Alice Smith",
            "first_name": "Alice",
            "last_name": "Smith",
            "suffix": None,
        },
        {
            "id": str(punctuation_id),
            "canonical_name": "Alice*Smith",
            "first_name": "Alice",
            "last_name": "Smith",
            "suffix": None,
        },
    ]


def test_slug_lookup_returns_empty_list_for_unknown_slug(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_person(db_conn, Person(canonical_name="Known Person"))

    response = api_client.get("/v1/person/by-slug/non-existent-person")

    assert response.status_code == 200
    assert response.json() == []


def test_slug_lookup_handles_special_characters(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    insert_person(db_conn, Person(canonical_name="Known Person"))
    hostile_slug = quote("!@;$[]{}()\"'\\", safe="")

    response = api_client.get(f"/v1/person/by-slug/{hostile_slug}")

    assert response.status_code == 200
    assert response.json() == []


def test_slug_lookup_trims_leading_and_trailing_non_alnum_characters(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(
        id=UUID("00000000-0000-0000-0000-000000000419"),
        canonical_name="  !!!Jane Doe???  ",
        first_name="Jane",
        last_name="Doe",
    )
    insert_person(db_conn, person)
    padded_slug = quote("---jane-doe!!!", safe="")

    response = api_client.get(f"/v1/person/by-slug/{padded_slug}")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(person.id),
            "canonical_name": person.canonical_name,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "suffix": person.suffix,
        }
    ]


def test_slug_route_does_not_shadow_person_id_route(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(
        id=UUID("00000000-0000-0000-0000-000000000420"),
        canonical_name="Route Probe",
        first_name="Route",
        last_name="Probe",
    )
    insert_person(db_conn, person)

    by_slug_response = api_client.get("/v1/person/by-slug/route-probe")
    by_id_response = api_client.get(f"/v1/person/{person.id}")

    assert by_slug_response.status_code == 200
    assert by_slug_response.json() == [
        {
            "id": str(person.id),
            "canonical_name": person.canonical_name,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "suffix": person.suffix,
        }
    ]
    assert by_id_response.status_code == 200
    assert by_id_response.json()["id"] == str(person.id)
