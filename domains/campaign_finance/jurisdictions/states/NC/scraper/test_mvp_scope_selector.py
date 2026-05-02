"""Integration tests for NC MVP committee scope selector."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import psycopg
import pytest

from core.db import insert_data_source, insert_organization, insert_person
from core.types.python.models import DataSource, Organization, Person
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    _match_and_update_nc_candidacy_committee,
    _resolve_nc_committee_bridge,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.mvp_scope_selector import (
    select_mvp_scope_committees,
)
from domains.civics.ingest import upsert_candidacy
from domains.civics.types import Candidacy

pytestmark = pytest.mark.integration


def _insert_nc_registry_row(
    conn: psycopg.Connection,
    *,
    org_group_id: int,
    sboe_id: str,
    committee_name: str,
    candidate_name: str | None = None,
) -> None:
    data_source_id = insert_data_source(
        conn,
        DataSource(
            domain="campaign_finance",
            jurisdiction="NC",
            name=f"nc-registry-{org_group_id}",
            source_url=f"https://example.test/nc-registry/{org_group_id}",
        ),
    )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.nc_committee_registry (
                org_group_id,
                sboe_id,
                committee_name,
                status_desc,
                old_id,
                candidate_name,
                data_source_id,
                first_seen_at,
                last_seen_at
            )
            VALUES (%s, %s, %s, 'ACTIVE (EXEMPT)', NULL, %s, %s, %s, %s)
            """,
            (
                org_group_id,
                sboe_id,
                committee_name,
                candidate_name,
                data_source_id,
                datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
                datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
            ),
        )


def _create_committee(
    conn: psycopg.Connection,
    *,
    sboe_id: str,
    committee_name: str,
    candidate_name: str | None = None,
) -> UUID:
    insert_organization(
        conn,
        Organization(
            canonical_name=f"{committee_name} {sboe_id}",
            identifiers={"nc_sboe_id": sboe_id},
        ),
    )
    _insert_nc_registry_row(
        conn,
        org_group_id=90000 + int(sboe_id.split("-")[-1]),
        sboe_id=sboe_id,
        committee_name=committee_name,
        candidate_name=candidate_name,
    )
    return _resolve_nc_committee_bridge(conn, sboe_id, committee_name=committee_name)


def _insert_unrelated_committee(
    conn: psycopg.Connection,
    *,
    fec_committee_id: str,
    committee_name: str,
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (fec_committee_id, name, state)
            VALUES (%s, %s, 'SC')
            RETURNING id
            """,
            (fec_committee_id, committee_name),
        )
        return cursor.fetchone()[0]


def _seed_candidacy(
    conn: psycopg.Connection,
    *,
    person_name: str,
    committee_id: UUID | None,
    jurisdiction_scope: str,
    state: str | None,
    county: str | None,
    seed_election_link: bool = True,
) -> None:
    person_id = insert_person(
        conn,
        Person(
            canonical_name=person_name,
            first_name=person_name.split()[0],
            last_name=person_name.split()[-1],
        ),
    )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO civic.office (name, office_level, state)
            VALUES (%s, 'state', %s)
            RETURNING id
            """,
            (f"Office {person_name}", state),
        )
        office_id: UUID = cursor.fetchone()[0]
        election_id: UUID | None = None
        if seed_election_link:
            cursor.execute(
                """
                INSERT INTO civic.election (
                    jurisdiction_scope,
                    state,
                    county,
                    election_date,
                    election_type,
                    is_special,
                    office_id
                )
                VALUES (%s, %s, %s, %s, 'general', FALSE, %s)
                RETURNING id
                """,
                (jurisdiction_scope, state, county, date(2024, 11, 5), office_id),
            )
            election_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.contest (
                name,
                election_date,
                election_type,
                office_id,
                election_id
            )
            VALUES (%s, %s, 'general', %s, %s)
            RETURNING id
            """,
            (
                f"Contest {person_name}",
                date(2024, 11, 5),
                office_id,
                election_id,
            ),
        )
        contest_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.candidacy (
                person_id,
                contest_id,
                name_on_ballot,
                committee_id
            )
            VALUES (%s, %s, %s, %s)
            """,
            (person_id, contest_id, person_name, committee_id),
        )


def _mark_candidacy_as_stage1_bridged(
    conn: psycopg.Connection,
    *,
    person_name: str,
    committee_id: UUID,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET committee_id = NULL
            WHERE name_on_ballot = %s
              AND committee_id = %s
            RETURNING id
            """,
            (person_name, committee_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise AssertionError("expected candidacy row to mark as Stage 1 bridged")
        candidacy_id: UUID = row[0]
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET committee_id = %s,
                raw_fields = COALESCE(raw_fields, '{}'::jsonb) || '{"nc_stage1_bridge_owned": true}'::jsonb,
                updated_at = NOW()
            WHERE id = %s
            """,
            (committee_id, candidacy_id),
        )


def test_select_mvp_scope_committees_returns_sorted_distinct_sboe_ids(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-001",
        committee_name="STATE INCLUDED",
    )
    include_county = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-002",
        committee_name="COUNTY INCLUDED",
    )
    exclude_county = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-003",
        committee_name="COUNTY EXCLUDED",
    )
    exclude_non_nc = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-004",
        committee_name="NON NC EXCLUDED",
    )

    _seed_candidacy(
        db_conn,
        person_name="Pat State",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat County",
        committee_id=include_county,
        jurisdiction_scope="county",
        state="NC",
        county="Wake",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat County Duplicate",
        committee_id=include_county,
        jurisdiction_scope="county",
        state="NC",
        county="Durham",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat County Excluded",
        committee_id=exclude_county,
        jurisdiction_scope="county",
        state="NC",
        county="Mecklenburg",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Out Of State",
        committee_id=exclude_non_nc,
        jurisdiction_scope="state",
        state="SC",
        county=None,
    )

    assert select_mvp_scope_committees(db_conn) == ["STA-MVP-C-001", "STA-MVP-C-002"]


def test_select_mvp_scope_committees_returns_empty_without_bridged_candidacies(
    db_conn: psycopg.Connection,
) -> None:
    assert select_mvp_scope_committees(db_conn) == []


def test_select_mvp_scope_committees_handles_stage1_shape_without_election_link(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-101",
        committee_name="STATE INCLUDED NO ELECTION LINK",
        candidate_name="Pat Stage1 State",
    )
    include_county = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-102",
        committee_name="COUNTY INCLUDED NO ELECTION LINK",
        candidate_name="Pat Stage1 County",
    )
    exclude_county = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-103",
        committee_name="COUNTY EXCLUDED NO ELECTION LINK",
        candidate_name="Pat Stage1 Excluded",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Stage1 State",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
        seed_election_link=False,
    )
    _mark_candidacy_as_stage1_bridged(
        db_conn,
        person_name="Pat Stage1 State",
        committee_id=include_state,
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Stage1 County",
        committee_id=include_county,
        jurisdiction_scope="county",
        state="NC",
        county="Orange",
        seed_election_link=False,
    )
    _mark_candidacy_as_stage1_bridged(
        db_conn,
        person_name="Pat Stage1 County",
        committee_id=include_county,
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Stage1 Excluded",
        committee_id=exclude_county,
        jurisdiction_scope="county",
        state="NC",
        county="Mecklenburg",
        seed_election_link=False,
    )
    _mark_candidacy_as_stage1_bridged(
        db_conn,
        person_name="Pat Stage1 Excluded",
        committee_id=exclude_county,
    )

    with pytest.raises(
        ValueError,
        match="requires contest.election_id for bridged candidacies",
    ):
        select_mvp_scope_committees(db_conn)


def test_select_mvp_scope_committees_ignores_unrelated_missing_election_link_rows(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-201",
        committee_name="STATE INCLUDED ELECTION LINK",
    )
    unrelated_committee = _insert_unrelated_committee(
        db_conn,
        fec_committee_id="C90000001",
        committee_name="UNRELATED COMMITTEE",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Included",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Unrelated Missing Election",
        committee_id=unrelated_committee,
        jurisdiction_scope="state",
        state="SC",
        county=None,
        seed_election_link=False,
    )

    assert select_mvp_scope_committees(db_conn) == ["STA-MVP-C-201"]


def test_select_mvp_scope_committees_ignores_non_bridge_upserted_missing_election_link_rows(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-301",
        committee_name="STATE INCLUDED WITH ELECTION LINK",
        candidate_name="Pat Included State",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Included State",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
    )

    person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Casey Civics Upsert",
            first_name="Casey",
            last_name="Upsert",
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO civic.office (name, office_level, state)
            VALUES ('Office Casey Civics Upsert', 'state', 'NC')
            RETURNING id
            """
        )
        office_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.contest (
                name,
                election_date,
                election_type,
                office_id,
                election_id
            )
            VALUES (%s, %s, 'general', %s, NULL)
            RETURNING id
            """,
            ("Contest Casey Civics Upsert", date(2024, 11, 5), office_id),
        )
        contest_id: UUID = cursor.fetchone()[0]

    upserted_candidacy_id = upsert_candidacy(
        db_conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            name_on_ballot="  Pat   Included   State  ",
            committee_id=include_state,
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET created_at = %s
            WHERE id = %s
            """,
            (datetime(2026, 4, 30, 12, 5, tzinfo=UTC), upserted_candidacy_id),
        )

    assert select_mvp_scope_committees(db_conn) == ["STA-MVP-C-301"]


def test_select_mvp_scope_committees_raises_when_same_name_duplicate_hides_missing_bridge_election_link(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-302",
        committee_name="STATE MISSING ELECTION LINK",
        candidate_name="Pat Missing Election",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Missing Election",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
        seed_election_link=False,
    )
    _mark_candidacy_as_stage1_bridged(
        db_conn,
        person_name="Pat Missing Election",
        committee_id=include_state,
    )

    person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Pat Missing Election Duplicate",
            first_name="Pat",
            last_name="Duplicate",
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO civic.office (name, office_level, state)
            VALUES ('Office Pat Missing Election Duplicate', 'state', 'NC')
            RETURNING id
            """
        )
        office_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.election (
                jurisdiction_scope,
                state,
                county,
                election_date,
                election_type,
                is_special,
                office_id
            )
            VALUES ('state', 'NC', NULL, %s, 'general', FALSE, %s)
            RETURNING id
            """,
            (date(2024, 11, 5), office_id),
        )
        election_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.contest (
                name,
                election_date,
                election_type,
                office_id,
                election_id
            )
            VALUES (%s, %s, 'general', %s, %s)
            RETURNING id
            """,
            (
                "Contest Pat Missing Election Duplicate",
                date(2024, 11, 5),
                office_id,
                election_id,
            ),
        )
        contest_id: UUID = cursor.fetchone()[0]

    upserted_candidacy_id = upsert_candidacy(
        db_conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            name_on_ballot="Pat Missing Election",
            committee_id=include_state,
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET created_at = %s
            WHERE id = %s
            """,
            (datetime(2026, 4, 30, 12, 5, tzinfo=UTC), upserted_candidacy_id),
        )

    with pytest.raises(
        ValueError,
        match="requires contest.election_id for bridged candidacies",
    ):
        select_mvp_scope_committees(db_conn)


def test_select_mvp_scope_committees_does_not_raise_when_non_stage1_row_is_created_earlier(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-303",
        committee_name="STATE INCLUDED PROVENANCE GUARD",
        candidate_name="Pat Provenance Guard",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Provenance Guard",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
    )
    _mark_candidacy_as_stage1_bridged(
        db_conn,
        person_name="Pat Provenance Guard",
        committee_id=include_state,
    )

    person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Pat Provenance Guard Upsert",
            first_name="Pat",
            last_name="Upsert",
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO civic.office (name, office_level, state)
            VALUES ('Office Pat Provenance Guard Upsert', 'state', 'NC')
            RETURNING id
            """
        )
        office_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.contest (
                name,
                election_date,
                election_type,
                office_id,
                election_id
            )
            VALUES (%s, %s, 'general', %s, NULL)
            RETURNING id
            """,
            ("Contest Pat Provenance Guard Upsert", date(2024, 11, 5), office_id),
        )
        contest_id: UUID = cursor.fetchone()[0]

    upserted_candidacy_id = upsert_candidacy(
        db_conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            name_on_ballot=" Pat   Provenance   Guard ",
            committee_id=include_state,
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET created_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
                datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
                upserted_candidacy_id,
            ),
        )

    assert select_mvp_scope_committees(db_conn) == ["STA-MVP-C-303"]


def test_select_mvp_scope_committees_raises_for_prelinked_stage1_row_after_idempotent_stamp(
    db_conn: psycopg.Connection,
) -> None:
    include_state = _create_committee(
        db_conn,
        sboe_id="STA-MVP-C-304",
        committee_name="STATE PRELINKED STAMP",
        candidate_name="Pat Prelinked Stage1",
    )
    _seed_candidacy(
        db_conn,
        person_name="Pat Prelinked Stage1",
        committee_id=include_state,
        jurisdiction_scope="state",
        state="NC",
        county=None,
        seed_election_link=False,
    )

    assert (
        _match_and_update_nc_candidacy_committee(
            db_conn,
            candidate_name="Pat Prelinked Stage1",
            committee_id=include_state,
        )
        == 1
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE((raw_fields ->> 'nc_stage1_bridge_owned')::boolean, FALSE)
            FROM civic.candidacy
            WHERE name_on_ballot = %s
            """,
            ("Pat Prelinked Stage1",),
        )
        assert cursor.fetchone()[0] is True

    with pytest.raises(
        ValueError,
        match="requires contest.election_id for bridged candidacies",
    ):
        select_mvp_scope_committees(db_conn)
