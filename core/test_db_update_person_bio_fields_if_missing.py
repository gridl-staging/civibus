from __future__ import annotations

import psycopg
import pytest

from core.db import insert_person, update_person_bio_fields_if_missing
from core.types.python.models import Person


pytestmark = pytest.mark.integration


def test_update_person_bio_fields_if_missing_first_write_sets_bio_companion_fields(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Morgan Candidate")
    insert_person(db_conn, person)

    updated_fields = update_person_bio_fields_if_missing(
        db_conn,
        person_id=person.id,
        occupation="Teacher",
        education="UNC Chapel Hill",
        bio_text="Morgan Candidate served on the school board.",
        bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
        bio_license="public_domain",
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT occupation, education, bio_text, bio_source_url, bio_license, bio_pulled_at
            FROM core.person
            WHERE id = %s
            """,
            (person.id,),
        )
        row = cursor.fetchone()

    assert updated_fields == ("occupation", "education", "bio_text", "bio_source_url", "bio_license")
    assert row is not None
    assert row[0] == "Teacher"
    assert row[1] == "UNC Chapel Hill"
    assert row[2] == "Morgan Candidate served on the school board."
    assert row[3] == "https://www.ncleg.gov/Members/Biography/H/149"
    assert row[4] == "public_domain"
    assert row[5] is not None


def test_update_person_bio_fields_if_missing_is_idempotent_for_non_empty_fields(
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Morgan Candidate")
    insert_person(db_conn, person)

    update_person_bio_fields_if_missing(
        db_conn,
        person_id=person.id,
        occupation="Teacher",
        education="UNC Chapel Hill",
        bio_text="First biography.",
        bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
        bio_license="public_domain",
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT occupation, education, bio_text, bio_source_url, bio_license, bio_pulled_at
            FROM core.person
            WHERE id = %s
            """,
            (person.id,),
        )
        before = cursor.fetchone()

    second_updated_fields = update_person_bio_fields_if_missing(
        db_conn,
        person_id=person.id,
        occupation="Attorney",
        education="Duke University",
        bio_text="Second biography should not overwrite.",
        bio_source_url="https://example.org/alt-bio",
        bio_license="cc-by-4.0",
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT occupation, education, bio_text, bio_source_url, bio_license, bio_pulled_at
            FROM core.person
            WHERE id = %s
            """,
            (person.id,),
        )
        after = cursor.fetchone()

    assert second_updated_fields == ()
    assert before is not None
    assert after is not None
    assert after[0] == "Teacher"
    assert after[1] == "UNC Chapel Hill"
    assert after[2] == "First biography."
    assert after[3] == "https://www.ncleg.gov/Members/Biography/H/149"
    assert after[4] == "public_domain"
    assert before[5] == after[5]
