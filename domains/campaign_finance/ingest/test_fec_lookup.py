from __future__ import annotations

from datetime import date
from uuid import UUID

import psycopg
import pytest

from core.db import insert_person
from core.types.python.models import Person, ValidDateRange
from domains.campaign_finance.ingest import fec_lookup
from domains.campaign_finance.ingest.fec_lookup import current_federal_officeholder_committee_fec_ids
from domains.civics.ingest import upsert_office, upsert_officeholding
from domains.civics.types.models import Office, Officeholding


def _insert_committee(
    conn: psycopg.Connection,
    *,
    fec_committee_id: str,
    designation: str | None,
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (fec_committee_id, name, committee_designation)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (fec_committee_id, f"Committee {fec_committee_id}", designation),
        )
        return cursor.fetchone()[0]


def _insert_candidate(
    conn: psycopg.Connection,
    *,
    fec_candidate_id: str,
    person_id: UUID,
    principal_committee_id: UUID | None,
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate (
                fec_candidate_id,
                name,
                person_id,
                office,
                state,
                district,
                principal_committee_id
            )
            VALUES (%s, %s, %s, 'H', 'NC', '01', %s)
            RETURNING id
            """,
            (fec_candidate_id, f"Candidate {fec_candidate_id}", person_id, principal_committee_id),
        )
        return cursor.fetchone()[0]


def _insert_candidate_committee_link(
    conn: psycopg.Connection,
    *,
    candidate_id: UUID,
    committee_id: UUID,
    designation: str,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate_committee_link (
                candidate_id,
                committee_id,
                designation,
                valid_period
            )
            VALUES (%s, %s, %s, daterange('2024-01-01', NULL, '[)'))
            """,
            (candidate_id, committee_id, designation),
        )


def _insert_officeholder_candidate(
    conn: psycopg.Connection,
    *,
    name: str,
    candidate_fec_id: str,
    office_level: str,
    principal_committee_id: UUID | None,
    active: bool = True,
) -> UUID:
    person = Person(canonical_name=name)
    person_id = insert_person(conn, person)
    office_id = upsert_office(conn, Office(name=f"{name} Office", office_level=office_level, title="Representative"))
    end_date = None if active else date(2023, 1, 3)
    upsert_officeholding(
        conn,
        Officeholding(
            person_id=person_id,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2021, 1, 3), end_date=end_date),
        ),
    )
    return _insert_candidate(
        conn,
        fec_candidate_id=candidate_fec_id,
        person_id=person_id,
        principal_committee_id=principal_committee_id,
    )


@pytest.mark.integration
def test_current_federal_officeholder_committee_fec_ids_scopes_active_non_joint_committees(
    db_conn: psycopg.Connection,
) -> None:
    principal = _insert_committee(db_conn, fec_committee_id="C31000001", designation="P")
    authorized = _insert_committee(db_conn, fec_committee_id="C31000002", designation="A")
    linked_joint = _insert_committee(db_conn, fec_committee_id="C31000003", designation="J")
    joint_principal = _insert_committee(db_conn, fec_committee_id="C31000004", designation="J")
    inactive_principal = _insert_committee(db_conn, fec_committee_id="C31000005", designation="P")
    state_principal = _insert_committee(db_conn, fec_committee_id="C31000006", designation="P")
    linked_non_authorized = _insert_committee(db_conn, fec_committee_id="C31000007", designation="P")

    active_candidate = _insert_officeholder_candidate(
        db_conn,
        name="Active Federal",
        candidate_fec_id="H0AA10001",
        office_level="federal",
        principal_committee_id=principal,
    )
    _insert_candidate_committee_link(db_conn, candidate_id=active_candidate, committee_id=authorized, designation="A")
    _insert_candidate_committee_link(db_conn, candidate_id=active_candidate, committee_id=linked_joint, designation="A")
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=active_candidate,
        committee_id=linked_non_authorized,
        designation="J",
    )
    _insert_officeholder_candidate(
        db_conn,
        name="Joint Principal Federal",
        candidate_fec_id="H0AA10002",
        office_level="federal",
        principal_committee_id=joint_principal,
    )
    _insert_officeholder_candidate(
        db_conn,
        name="Inactive Federal",
        candidate_fec_id="H0AA10003",
        office_level="federal",
        principal_committee_id=inactive_principal,
        active=False,
    )
    _insert_officeholder_candidate(
        db_conn,
        name="State Holder",
        candidate_fec_id="H0AA10004",
        office_level="state",
        principal_committee_id=state_principal,
    )

    committee_fec_ids = current_federal_officeholder_committee_fec_ids(db_conn)

    assert {"C31000001", "C31000002"}.issubset(committee_fec_ids)
    assert "C31000003" not in committee_fec_ids
    assert "C31000004" not in committee_fec_ids
    assert "C31000005" not in committee_fec_ids
    assert "C31000006" not in committee_fec_ids
    assert "C31000007" not in committee_fec_ids


def test_current_federal_officeholder_committee_fec_ids_delegates_active_candidate_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed_sql: list[str] = []

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            executed_sql.append(sql)

        def fetchall(self) -> list[tuple[str]]:
            return [("C31000001",)]

    class _Connection:
        def cursor(self) -> _Cursor:
            return _Cursor()

    monkeypatch.setattr(
        fec_lookup,
        "active_federal_candidate_scope_cte",
        lambda cte_name="active_federal_candidates": (
            f"{cte_name} AS (SELECT 'shared-officeholder-scope' AS marker, NULL::uuid AS id, "
            "NULL::uuid AS principal_committee_id)"
        ),
    )

    assert current_federal_officeholder_committee_fec_ids(_Connection()) == frozenset({"C31000001"})
    assert "shared-officeholder-scope" in executed_sql[0]
