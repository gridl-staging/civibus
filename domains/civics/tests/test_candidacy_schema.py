"""Integration contract tests for civic.candidacy MVP schema columns."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from core.db import insert_person
from core.types.python.models import Person
from domains.civics.tests.model_payload_builders import build_candidacy_mvp_fields_payload, build_candidacy_payload
from domains.civics.types import Candidacy


pytestmark = pytest.mark.integration


def _seed_person(conn: psycopg.Connection) -> UUID:
    person = Person(canonical_name=f"Schema Test Person {uuid4()}", first_name="Schema", last_name="Person")
    return insert_person(conn, person)


def _seed_office_and_contest(conn: psycopg.Connection) -> tuple[UUID, UUID]:
    office_id = uuid4()
    contest_id = uuid4()
    conn.execute(
        """
        INSERT INTO civic.office (id, name, office_level, state)
        VALUES (%s, %s, 'state', 'NC')
        """,
        (office_id, f"schema_test_office_{uuid4().hex[:12]}"),
    )
    conn.execute(
        """
        INSERT INTO civic.contest (id, name, election_type, office_id)
        VALUES (%s, %s, 'general', %s)
        """,
        (contest_id, f"Schema Test Contest {uuid4().hex[:12]}", office_id),
    )
    return office_id, contest_id


def _seed_committee(conn: psycopg.Connection) -> UUID:
    committee_id = uuid4()
    fec_committee_id = f"C{committee_id.int % 100_000_000:08d}"
    conn.execute(
        """
        INSERT INTO cf.committee (id, fec_committee_id, name, state)
        VALUES (%s, %s, %s, 'NC')
        """,
        (committee_id, fec_committee_id, f"Schema Test Committee {uuid4().hex[:12]}"),
    )
    return committee_id


def _row_mapping_from_cursor(cursor: psycopg.Cursor[tuple[object, ...]], row: tuple[object, ...]) -> dict[str, object]:
    assert cursor.description is not None
    column_names = [column.name for column in cursor.description]
    return dict(zip(column_names, row, strict=True))


def test_candidacy_mvp_columns_round_trip_and_model_contract(db_conn: psycopg.Connection) -> None:
    person_id = _seed_person(db_conn)
    _, contest_id = _seed_office_and_contest(db_conn)
    committee_id = _seed_committee(db_conn)
    candidacy_id = uuid4()
    optional_fields = build_candidacy_mvp_fields_payload(committee_id=str(committee_id))

    candidacy_payload = build_candidacy_payload(
        person_id=str(person_id),
        contest_id=str(contest_id),
        name_on_ballot=optional_fields["name_on_ballot"],
        is_unexpired_term=optional_fields["is_unexpired_term"],
        raw_fields=optional_fields["raw_fields"],
        committee_id=optional_fields["committee_id"],
    )

    db_conn.execute(
        """
        INSERT INTO civic.candidacy (
            id,
            person_id,
            contest_id,
            name_on_ballot,
            is_unexpired_term,
            raw_fields,
            committee_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            candidacy_id,
            UUID(str(candidacy_payload["person_id"])),
            UUID(str(candidacy_payload["contest_id"])),
            candidacy_payload["name_on_ballot"],
            candidacy_payload["is_unexpired_term"],
            Jsonb(candidacy_payload["raw_fields"]),
            UUID(str(candidacy_payload["committee_id"])),
        ),
    )

    stored_columns = db_conn.execute(
        """
        SELECT name_on_ballot, is_unexpired_term, raw_fields, committee_id
        FROM civic.candidacy
        WHERE id = %s
        """,
        (candidacy_id,),
    ).fetchone()
    assert stored_columns is not None
    assert stored_columns[0] == candidacy_payload["name_on_ballot"]
    assert stored_columns[1] is candidacy_payload["is_unexpired_term"]
    assert stored_columns[2] == candidacy_payload["raw_fields"]
    assert stored_columns[3] == UUID(str(candidacy_payload["committee_id"]))

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT * FROM civic.candidacy WHERE id = %s", (candidacy_id,))
        row = cursor.fetchone()
        assert row is not None
        candidacy = Candidacy.model_validate(_row_mapping_from_cursor(cursor, row))

    assert candidacy.id == candidacy_id
    assert candidacy.person_id == person_id
    assert candidacy.contest_id == contest_id
    assert candidacy.name_on_ballot == candidacy_payload["name_on_ballot"]
    assert candidacy.is_unexpired_term is True
    assert candidacy.raw_fields == candidacy_payload["raw_fields"]
    assert candidacy.committee_id == committee_id
