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
    principal_committee_id: UUID | None = None,
    person_id: UUID | None = None,
    office: str = "H",
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
            VALUES (%s, %s, %s, %s, 'NC', '01', %s)
            RETURNING id
            """,
            (fec_candidate_id, f"Candidate {fec_candidate_id}", person_id, office, principal_committee_id),
        )
        return cursor.fetchone()[0]


def _insert_candidate_committee_link(
    conn: psycopg.Connection,
    *,
    candidate_id: UUID,
    committee_id: UUID,
    designation: str,
    candidate_election_year: int | None = 2024,
    fec_election_year: int | None = 2024,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate_committee_link (
                candidate_id,
                committee_id,
                designation,
                candidate_election_year,
                fec_election_year,
                valid_period
            )
            VALUES (%s, %s, %s, %s, %s, daterange('2024-01-01', NULL, '[)'))
            """,
            (candidate_id, committee_id, designation, candidate_election_year, fec_election_year),
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


# Every committee this test inserts, including the three it expects the resolver to
# exclude. Used to scope assertions away from data seeded by the CI Integration job.
_FIXTURE_COMMITTEE_FEC_IDS = frozenset(
    {
        "C32000001",
        "C32000002",
        "C32000003",
        "C32000004",
        "C32000005",
        "C32000006",
        "C32000007",
    }
)


@pytest.mark.integration
def test_pa_union_committee_fec_ids_for_election_years_scopes_principal_and_authorized_links(
    db_conn: psycopg.Connection,
) -> None:
    house_principal = _insert_committee(db_conn, fec_committee_id="C32000001", designation="P")
    senate_authorized = _insert_committee(db_conn, fec_committee_id="C32000002", designation="A")
    presidential_authorized = _insert_committee(db_conn, fec_committee_id="C32000003", designation="A")
    shared_authorized = _insert_committee(db_conn, fec_committee_id="C32000004", designation="A")
    excluded_link_designation = _insert_committee(db_conn, fec_committee_id="C32000005", designation="P")
    excluded_joint = _insert_committee(db_conn, fec_committee_id="C32000006", designation="J")
    excluded_wrong_year = _insert_committee(db_conn, fec_committee_id="C32000007", designation="P")

    house_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="H2AA10001",
        office="H",
        principal_committee_id=None,
    )
    senate_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="S4AA10002",
        office="S",
        principal_committee_id=None,
    )
    presidential_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="P6AA10003",
        office="P",
        principal_committee_id=None,
    )
    shared_house_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="H6AA10004",
        office="H",
        principal_committee_id=None,
    )
    shared_senate_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="S4AA10005",
        office="S",
        principal_committee_id=None,
    )
    excluded_link_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="H6AA10006",
        office="H",
        principal_committee_id=None,
    )
    excluded_joint_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="S6AA10007",
        office="S",
        principal_committee_id=None,
    )
    excluded_year_candidate = _insert_candidate(
        db_conn,
        fec_candidate_id="P6AA10008",
        office="P",
        principal_committee_id=None,
    )

    _insert_candidate_committee_link(
        db_conn,
        candidate_id=house_candidate,
        committee_id=house_principal,
        designation="P",
        candidate_election_year=2022,
        fec_election_year=2022,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=senate_candidate,
        committee_id=senate_authorized,
        designation="A",
        candidate_election_year=2024,
        fec_election_year=2024,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=presidential_candidate,
        committee_id=presidential_authorized,
        designation="A",
        candidate_election_year=2026,
        fec_election_year=2026,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=shared_house_candidate,
        committee_id=shared_authorized,
        designation="A",
        candidate_election_year=2026,
        fec_election_year=2026,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=shared_senate_candidate,
        committee_id=shared_authorized,
        designation="P",
        candidate_election_year=2024,
        fec_election_year=2024,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=excluded_link_candidate,
        committee_id=excluded_link_designation,
        designation="J",
        candidate_election_year=2026,
        fec_election_year=2026,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=excluded_joint_candidate,
        committee_id=excluded_joint,
        designation="A",
        candidate_election_year=2026,
        fec_election_year=2026,
    )
    _insert_candidate_committee_link(
        db_conn,
        candidate_id=excluded_year_candidate,
        committee_id=excluded_wrong_year,
        designation="A",
        candidate_election_year=2020,
        fec_election_year=2020,
    )

    committee_fec_ids = fec_lookup.pa_union_committee_fec_ids_for_election_years(
        db_conn,
        election_years=(2022, 2024, 2026),
    )

    # The resolver reads the whole cf.candidate_committee_link table, and the CI
    # Integration job seeds tests/fixtures/bulk before this suite runs, so the
    # result legitimately contains committees this test never inserted. Scope the
    # comparison to this test's own C320000xx universe instead of asserting over
    # the global set; that keeps both failure directions live -- a dropped
    # C32000001-4 and a wrongly included C32000005/6/7 each still red -- without
    # depending on an empty database.
    assert committee_fec_ids & _FIXTURE_COMMITTEE_FEC_IDS == frozenset(
        {"C32000001", "C32000002", "C32000003", "C32000004"}
    )
    assert (
        fec_lookup.pa_union_committee_fec_ids_for_election_years(
            db_conn,
            election_years=(2026, 2022, 2024, 2026),
        )
        == committee_fec_ids
    )
    assert fec_lookup.pa_union_committee_fec_ids_for_election_years(db_conn, election_years=()) == frozenset()


def test_pa_union_committee_fec_ids_sql_keeps_schema_guarded_filters() -> None:
    executed: list[tuple[str, object]] = []

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, sql: str, params: object) -> None:
            executed.append((sql, params))

        def fetchall(self) -> list[tuple[str]]:
            return [("C32000001",)]

    class _Connection:
        def cursor(self) -> _Cursor:
            return _Cursor()

    assert fec_lookup.pa_union_committee_fec_ids_for_election_years(
        _Connection(),
        election_years=(2026, 2022, 2022),
    ) == frozenset({"C32000001"})

    sql, params = executed[0]
    assert "cand.office IN ('H', 'S', 'P')" in sql
    assert "cm.fec_committee_id IS NOT NULL" in sql
    assert params == ([2022, 2026],)


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
