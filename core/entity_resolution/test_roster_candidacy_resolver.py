from __future__ import annotations

import json
from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_person, insert_source_record
from core.types.python.models import DataSource, Person, SourceRecord, ValidDateRange, compute_record_hash, utc_now
from domains.civics.ingest import upsert_candidacy, upsert_contest, upsert_office, upsert_officeholding
from domains.civics.types.models import Candidacy, Contest, Office, Officeholding

from core.entity_resolution.roster_candidacy_resolver import resolve_roster_candidacy_people


pytestmark = pytest.mark.integration


def _make_data_source(conn: psycopg.Connection, *, source_id: str, is_roster: bool) -> DataSource:
    notes_payload: dict[str, object] = {"registry_source_id": source_id}
    if is_roster:
        notes_payload["body_key"] = "nc_house"
    data_source = DataSource(
        domain="civics" if is_roster else "campaign_finance",
        jurisdiction="state/nc",
        name=f"resolver_test_{source_id}_{uuid4().hex}",
        source_url="https://example.com/source",
        notes=json.dumps(notes_payload),
    )
    insert_data_source(conn, data_source)
    return data_source


def _make_source_record(conn: psycopg.Connection, *, data_source_id: UUID, key: str) -> SourceRecord:
    raw_fields: dict[str, object] = {"record_key": key}
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(conn, source_record)
    return source_record


def _seed_pair(
    conn: psycopg.Connection,
    *,
    office_name: str,
    roster_person_name: str,
    candidacy_person_name: str,
    roster_source_record_id: UUID,
    candidacy_source_record_id: UUID,
    shared_voter_reg_id: str | None = None,
) -> tuple[UUID, UUID, UUID]:
    office_id = upsert_office(
        conn,
        Office(
            name=office_name,
            office_level="state",
            state="NC",
            title="State Representative",
        ),
    )
    contest_id = upsert_contest(
        conn,
        Contest(
            name=f"contest_{office_name}",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_id,
        ),
    )

    roster_person_id = insert_person(
        conn,
        Person(
            canonical_name=roster_person_name,
            first_name=roster_person_name.split(" ", 1)[0],
            last_name=roster_person_name.split(" ", 1)[1],
            identifiers={"voter_reg_id": shared_voter_reg_id} if shared_voter_reg_id is not None else {},
        ),
    )
    candidacy_person_id = insert_person(
        conn,
        Person(
            canonical_name=candidacy_person_name,
            first_name=candidacy_person_name.split(" ", 1)[0],
            last_name=candidacy_person_name.split(" ", 1)[1],
            identifiers={"voter_reg_id": shared_voter_reg_id} if shared_voter_reg_id is not None else {},
        ),
    )

    upsert_officeholding(
        conn,
        Officeholding(
            person_id=roster_person_id,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=None),
            source_record_id=roster_source_record_id,
        ),
    )
    upsert_candidacy(
        conn,
        Candidacy(
            person_id=candidacy_person_id,
            contest_id=contest_id,
            status="filed",
            source_record_id=candidacy_source_record_id,
        ),
    )
    return office_id, roster_person_id, candidacy_person_id


def _current_pair_person_ids(conn: psycopg.Connection, *, office_id: UUID) -> tuple[UUID, UUID]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT oh.person_id, cd.person_id
            FROM civic.officeholding oh
            JOIN civic.contest ct ON ct.office_id = oh.office_id
            JOIN civic.candidacy cd ON cd.contest_id = ct.id
            WHERE oh.office_id = %s
            ORDER BY oh.created_at ASC, cd.created_at ASC
            LIMIT 1
            """,
            (office_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def _row_timestamps(conn: psycopg.Connection, *, office_id: UUID) -> tuple[object, object]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT MAX(oh.updated_at), MAX(cd.updated_at)
            FROM civic.officeholding oh
            JOIN civic.contest ct ON ct.office_id = oh.office_id
            JOIN civic.candidacy cd ON cd.contest_id = ct.id
            WHERE oh.office_id = %s
            """,
            (office_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def test_resolver_links_known_match_and_preserves_known_nonmatch(
    db_conn: psycopg.Connection,
) -> None:
    roster_source = _make_data_source(db_conn, source_id="resolver_roster", is_roster=True)
    candidacy_source = _make_data_source(db_conn, source_id="resolver_candidacy", is_roster=False)
    roster_source_record = _make_source_record(
        db_conn,
        data_source_id=roster_source.id,
        key="official_roster:resolver_roster:snapshot",
    )
    candidacy_source_record = _make_source_record(
        db_conn,
        data_source_id=candidacy_source.id,
        key="candidacy:resolver_test",
    )

    matched_office_id, matched_roster_person_id, _ = _seed_pair(
        db_conn,
        office_name=f"nc_house_match_{uuid4().hex}",
        roster_person_name="Alice Match",
        candidacy_person_name="Alicia Match",
        roster_source_record_id=roster_source_record.id,
        candidacy_source_record_id=candidacy_source_record.id,
        shared_voter_reg_id="VR-MATCH-001",
    )
    nonmatch_office_id, nonmatch_roster_person_id, nonmatch_candidacy_person_id = _seed_pair(
        db_conn,
        office_name=f"nc_house_nonmatch_{uuid4().hex}",
        roster_person_name="Bob Nonmatch",
        candidacy_person_name="Charlie Nonmatch",
        roster_source_record_id=roster_source_record.id,
        candidacy_source_record_id=candidacy_source_record.id,
    )

    summary = resolve_roster_candidacy_people(db_conn)

    assert summary["candidate_pairs"] == 2
    assert summary["linked_rows"] == 1
    assert summary["skipped_rows"] == 1
    assert summary["already_linked_rows"] == 0
    assert summary["mutated_rows"] == 1

    matched_pair = _current_pair_person_ids(db_conn, office_id=matched_office_id)
    assert matched_pair == (matched_roster_person_id, matched_roster_person_id)

    nonmatch_pair = _current_pair_person_ids(db_conn, office_id=nonmatch_office_id)
    assert nonmatch_pair == (nonmatch_roster_person_id, nonmatch_candidacy_person_id)


def test_resolver_second_run_is_idempotent_with_stable_summary(
    db_conn: psycopg.Connection,
) -> None:
    roster_source = _make_data_source(db_conn, source_id="resolver_roster_idempotent", is_roster=True)
    candidacy_source = _make_data_source(db_conn, source_id="resolver_candidacy_idempotent", is_roster=False)
    roster_source_record = _make_source_record(
        db_conn,
        data_source_id=roster_source.id,
        key="official_roster:resolver_roster_idempotent:snapshot",
    )
    candidacy_source_record = _make_source_record(
        db_conn,
        data_source_id=candidacy_source.id,
        key="candidacy:resolver_test_idempotent",
    )

    matched_office_id, _, _ = _seed_pair(
        db_conn,
        office_name=f"nc_house_match_idempotent_{uuid4().hex}",
        roster_person_name="Donna Match",
        candidacy_person_name="Dawn Match",
        roster_source_record_id=roster_source_record.id,
        candidacy_source_record_id=candidacy_source_record.id,
        shared_voter_reg_id="VR-MATCH-002",
    )
    nonmatch_office_id, _, _ = _seed_pair(
        db_conn,
        office_name=f"nc_house_nonmatch_idempotent_{uuid4().hex}",
        roster_person_name="Eddie Nonmatch",
        candidacy_person_name="Frank Nonmatch",
        roster_source_record_id=roster_source_record.id,
        candidacy_source_record_id=candidacy_source_record.id,
    )

    first_summary = resolve_roster_candidacy_people(db_conn)
    before_second_match_timestamps = _row_timestamps(db_conn, office_id=matched_office_id)
    before_second_nonmatch_timestamps = _row_timestamps(db_conn, office_id=nonmatch_office_id)

    second_summary = resolve_roster_candidacy_people(db_conn)
    after_second_match_timestamps = _row_timestamps(db_conn, office_id=matched_office_id)
    after_second_nonmatch_timestamps = _row_timestamps(db_conn, office_id=nonmatch_office_id)

    assert first_summary == {
        "candidate_pairs": 2,
        "linked_rows": 1,
        "skipped_rows": 1,
        "already_linked_rows": 0,
        "mutated_rows": 1,
    }
    assert second_summary == {
        "candidate_pairs": 2,
        "linked_rows": 1,
        "skipped_rows": 1,
        "already_linked_rows": 1,
        "mutated_rows": 0,
    }

    assert before_second_match_timestamps == after_second_match_timestamps
    assert before_second_nonmatch_timestamps == after_second_nonmatch_timestamps


def test_resolver_ignores_stale_officeholdings_for_same_office(
    db_conn: psycopg.Connection,
) -> None:
    roster_source = _make_data_source(db_conn, source_id="resolver_roster_stale", is_roster=True)
    candidacy_source = _make_data_source(db_conn, source_id="resolver_candidacy_stale", is_roster=False)
    roster_source_record = _make_source_record(
        db_conn,
        data_source_id=roster_source.id,
        key="official_roster:resolver_roster_stale:snapshot",
    )
    candidacy_source_record = _make_source_record(
        db_conn,
        data_source_id=candidacy_source.id,
        key="candidacy:resolver_test_stale",
    )

    office_id = upsert_office(
        db_conn,
        Office(
            name=f"nc_house_stale_filter_{uuid4().hex}",
            office_level="state",
            state="NC",
            title="State Representative",
        ),
    )
    contest_id = upsert_contest(
        db_conn,
        Contest(
            name=f"contest_stale_filter_{uuid4().hex}",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_id,
        ),
    )

    stale_roster_person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Harold Stale",
            first_name="Harold",
            last_name="Stale",
            identifiers={"voter_reg_id": "VR-STALE-HIST"},
        ),
    )
    current_roster_person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Carla Current",
            first_name="Carla",
            last_name="Current",
            identifiers={"voter_reg_id": "VR-CURRENT-001"},
        ),
    )
    candidacy_person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Carla Candidate",
            first_name="Carla",
            last_name="Candidate",
            identifiers={"voter_reg_id": "VR-CURRENT-001"},
        ),
    )

    upsert_officeholding(
        db_conn,
        Officeholding(
            person_id=stale_roster_person_id,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2021, 1, 1), end_date=date(2023, 1, 1)),
            source_record_id=roster_source_record.id,
        ),
    )
    upsert_officeholding(
        db_conn,
        Officeholding(
            person_id=current_roster_person_id,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=None),
            source_record_id=roster_source_record.id,
        ),
    )
    candidacy_id = upsert_candidacy(
        db_conn,
        Candidacy(
            person_id=candidacy_person_id,
            contest_id=contest_id,
            status="filed",
            source_record_id=candidacy_source_record.id,
        ),
    )

    summary = resolve_roster_candidacy_people(db_conn)

    assert summary == {
        "candidate_pairs": 1,
        "linked_rows": 1,
        "skipped_rows": 0,
        "already_linked_rows": 0,
        "mutated_rows": 1,
    }
    candidacy_person = db_conn.execute(
        "SELECT person_id FROM civic.candidacy WHERE id = %s",
        (candidacy_id,),
    ).fetchone()
    assert candidacy_person == (current_roster_person_id,)


def test_resolver_skips_ambiguous_multi_match_candidacy(
    db_conn: psycopg.Connection,
) -> None:
    roster_source = _make_data_source(db_conn, source_id="resolver_roster_ambiguous", is_roster=True)
    candidacy_source = _make_data_source(db_conn, source_id="resolver_candidacy_ambiguous", is_roster=False)
    roster_source_record = _make_source_record(
        db_conn,
        data_source_id=roster_source.id,
        key="official_roster:resolver_roster_ambiguous:snapshot",
    )
    candidacy_source_record = _make_source_record(
        db_conn,
        data_source_id=candidacy_source.id,
        key="candidacy:resolver_test_ambiguous",
    )

    office_id = upsert_office(
        db_conn,
        Office(
            name=f"nc_house_ambiguous_{uuid4().hex}",
            office_level="state",
            state="NC",
            title="State Representative",
        ),
    )
    contest_id = upsert_contest(
        db_conn,
        Contest(
            name=f"contest_ambiguous_{uuid4().hex}",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_id,
        ),
    )

    roster_person_a = insert_person(
        db_conn,
        Person(
            canonical_name="Amber Ambiguous",
            first_name="Amber",
            last_name="Ambiguous",
            identifiers={"voter_reg_id": "VR-AMB-001"},
        ),
    )
    roster_person_b = insert_person(
        db_conn,
        Person(
            canonical_name="Avery Ambiguous",
            first_name="Avery",
            last_name="Ambiguous",
            identifiers={"voter_reg_id": "VR-AMB-001"},
        ),
    )
    candidacy_person_id = insert_person(
        db_conn,
        Person(
            canonical_name="Alex Ambiguous Candidate",
            first_name="Alex",
            last_name="Candidate",
            identifiers={"voter_reg_id": "VR-AMB-001"},
        ),
    )

    upsert_officeholding(
        db_conn,
        Officeholding(
            person_id=roster_person_a,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=None),
            source_record_id=roster_source_record.id,
        ),
    )
    upsert_officeholding(
        db_conn,
        Officeholding(
            person_id=roster_person_b,
            office_id=office_id,
            valid_period=ValidDateRange(start_date=date(2025, 1, 1), end_date=None),
            source_record_id=roster_source_record.id,
        ),
    )
    candidacy_id = upsert_candidacy(
        db_conn,
        Candidacy(
            person_id=candidacy_person_id,
            contest_id=contest_id,
            status="filed",
            source_record_id=candidacy_source_record.id,
        ),
    )

    summary = resolve_roster_candidacy_people(db_conn)

    assert summary == {
        "candidate_pairs": 2,
        "linked_rows": 0,
        "skipped_rows": 2,
        "already_linked_rows": 0,
        "mutated_rows": 0,
    }
    candidacy_person = db_conn.execute(
        "SELECT person_id FROM civic.candidacy WHERE id = %s",
        (candidacy_id,),
    ).fetchone()
    assert candidacy_person == (candidacy_person_id,)
