"""Regression tests for the NC candidacy committee bridge pass.

Stage 1 of the D/W/O CF fanout (apr29_pm_6) extends
``load_nc_committee_registry_rows()`` so that after each registry row is
upserted into ``cf.nc_committee_registry`` the loader writes
``civic.candidacy.committee_id`` for the unique NC candidacy whose
``name_on_ballot`` matches the registry ``candidate_name`` (exact match
after whitespace trim + internal-whitespace collapse). Ambiguous-name
collisions are skipped and reruns are idempotent.

These tests exercise the same-module bridge helper directly plus one
integration test against ``load_nc_committee_registry_rows()`` to keep
``cf.nc_committee_registry`` as the persisted SSOT for the pass.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_organization, insert_person
from core.types.python.models import Organization, Person
from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_registry import (
    NCCommitteeRegistryRow,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    _bridge_nc_registry_row_to_candidacy,
    _match_and_update_nc_candidacy_committee,
    _resolve_nc_committee_bridge,
    _select_unique_nc_candidacy_id_for_bridge_name,
    load_nc_committee_registry_rows,
)

pytestmark = pytest.mark.integration


def _materialize_nc_committee(
    conn: psycopg.Connection,
    *,
    sboe_id: str,
    committee_name: str,
) -> UUID:
    """Materialize an NC ``cf.committee`` row through the existing bridge owner."""
    return _resolve_nc_committee_bridge(
        conn,
        sboe_id,
        committee_name=committee_name,
    )


def _seed_nc_candidacy(
    conn: psycopg.Connection,
    *,
    person_name: str,
    name_on_ballot: str,
    office_name: str | None = None,
) -> UUID:
    """Seed core.person + civic.office (state=NC) + civic.contest + civic.candidacy.

    Returns the candidacy id.
    """
    person_id = insert_person(
        conn,
        Person(
            canonical_name=person_name,
            first_name=person_name.split()[0],
            last_name=person_name.split()[-1],
        ),
    )
    resolved_office_name = office_name or f"NC State Senate District {uuid4().hex[:6]}"
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO civic.office (name, office_level, state)
            VALUES (%s, 'state', 'NC')
            RETURNING id
            """,
            (resolved_office_name,),
        )
        office_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.contest (
                name, election_date, election_type, office_id
            )
            VALUES (%s, %s, 'general', %s)
            RETURNING id
            """,
            (f"{resolved_office_name} 2024 General", date(2024, 11, 5), office_id),
        )
        contest_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.candidacy (
                person_id, contest_id, name_on_ballot
            )
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (person_id, contest_id, name_on_ballot),
        )
        candidacy_id: UUID = cursor.fetchone()[0]
    return candidacy_id


def _seed_nc_candidacy_in_existing_office(
    conn: psycopg.Connection,
    *,
    person_name: str,
    name_on_ballot: str,
    office_id: UUID,
) -> UUID:
    """Seed a second candidacy inside an existing office, on a distinct contest."""
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
            INSERT INTO civic.contest (
                name, election_date, election_type, office_id
            )
            VALUES (%s, %s, 'primary', %s)
            RETURNING id
            """,
            (
                f"NC Office Contest Distinct {uuid4().hex[:6]}",
                date(2024, 3, 5),
                office_id,
            ),
        )
        contest_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.candidacy (
                person_id, contest_id, name_on_ballot
            )
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (person_id, contest_id, name_on_ballot),
        )
        candidacy_id: UUID = cursor.fetchone()[0]
    return candidacy_id


def _seed_non_nc_candidacy(
    conn: psycopg.Connection,
    *,
    person_name: str,
    name_on_ballot: str,
) -> UUID:
    """Seed a candidacy whose office is in a non-NC state.

    Used to confirm the matcher restricts updates to NC offices.
    """
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
            VALUES (%s, 'state', 'SC')
            RETURNING id
            """,
            (f"SC State Senate District {uuid4().hex[:6]}",),
        )
        office_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.contest (
                name, election_date, election_type, office_id
            )
            VALUES (%s, %s, 'general', %s)
            RETURNING id
            """,
            (f"SC 2024 General {uuid4().hex[:6]}", date(2024, 11, 5), office_id),
        )
        contest_id: UUID = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO civic.candidacy (
                person_id, contest_id, name_on_ballot
            )
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (person_id, contest_id, name_on_ballot),
        )
        candidacy_id: UUID = cursor.fetchone()[0]
    return candidacy_id


def _select_candidacy_committee_id(conn: psycopg.Connection, candidacy_id: UUID) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT committee_id FROM civic.candidacy WHERE id = %s",
            (candidacy_id,),
        )
        return cursor.fetchone()[0]


def _select_stage1_bridge_owned(conn: psycopg.Connection, candidacy_id: UUID) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE((raw_fields ->> 'nc_stage1_bridge_owned')::boolean, FALSE)
            FROM civic.candidacy
            WHERE id = %s
            """,
            (candidacy_id,),
        )
        return cursor.fetchone()[0]


def _select_nc_committee_count(conn: psycopg.Connection, *, native_committee_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM cf.committee c
            JOIN core.organization o ON o.id = c.organization_id
            WHERE c.state = 'NC'
              AND o.identifiers ->> 'nc_sboe_id' = %s
            """,
            (native_committee_id,),
        )
        return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# Direct matcher helper tests
# ---------------------------------------------------------------------------


def test_match_unique_normalized_whitespace_updates_exactly_one_candidacy(
    db_conn: psycopg.Connection,
) -> None:
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Alex Example",
        name_on_ballot="ALEX  EXAMPLE",  # internal double space
    )
    committee_id = _materialize_nc_committee(
        db_conn,
        sboe_id="STA-ALEX-C-001",
        committee_name="ALEX EXAMPLE COMMITTEE",
    )

    updated = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="  ALEX EXAMPLE  ",  # external whitespace
        committee_id=committee_id,
    )

    assert updated == 1
    assert _select_candidacy_committee_id(db_conn, candidacy_id) == committee_id


def test_match_duplicate_name_on_ballot_skips_with_zero_updates(
    db_conn: psycopg.Connection,
) -> None:
    first_id = _seed_nc_candidacy(
        db_conn,
        person_name="Sam Twin",
        name_on_ballot="SAM TWIN",
        office_name="NC State Senate District Twin",
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT office_id FROM civic.contest WHERE id = (SELECT contest_id FROM civic.candidacy WHERE id = %s)",
            (first_id,),
        )
        shared_office_id: UUID = cursor.fetchone()[0]
    second_id = _seed_nc_candidacy_in_existing_office(
        db_conn,
        person_name="Samm Twinn",
        name_on_ballot="SAM TWIN",
        office_id=shared_office_id,
    )
    committee_id = _materialize_nc_committee(
        db_conn,
        sboe_id="STA-TWIN-C-001",
        committee_name="SAM TWIN COMMITTEE",
    )

    updated = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="SAM TWIN",
        committee_id=committee_id,
    )

    assert updated == 0
    assert _select_candidacy_committee_id(db_conn, first_id) is None
    assert _select_candidacy_committee_id(db_conn, second_id) is None


def test_match_rerun_against_already_bridged_returns_zero_updates(
    db_conn: psycopg.Connection,
) -> None:
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Robin Solo",
        name_on_ballot="ROBIN SOLO",
    )
    committee_id = _materialize_nc_committee(
        db_conn,
        sboe_id="STA-SOLO-C-001",
        committee_name="ROBIN SOLO COMMITTEE",
    )

    first = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="ROBIN SOLO",
        committee_id=committee_id,
    )
    second = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="ROBIN SOLO",
        committee_id=committee_id,
    )

    assert first == 1
    assert second == 0
    assert _select_candidacy_committee_id(db_conn, candidacy_id) == committee_id


def test_match_prelinked_row_stamps_stage1_bridge_ownership_idempotently(
    db_conn: psycopg.Connection,
) -> None:
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Casey Prelinked",
        name_on_ballot="CASEY PRELINKED",
    )
    committee_id = _materialize_nc_committee(
        db_conn,
        sboe_id="STA-PRELINK-C-001",
        committee_name="CASEY PRELINKED COMMITTEE",
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET committee_id = %s,
                raw_fields = '{}'::jsonb
            WHERE id = %s
            """,
            (committee_id, candidacy_id),
        )

    first = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="CASEY PRELINKED",
        committee_id=committee_id,
    )
    second = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="CASEY PRELINKED",
        committee_id=committee_id,
    )

    assert first == 1
    assert second == 0
    assert _select_candidacy_committee_id(db_conn, candidacy_id) == committee_id
    assert _select_stage1_bridge_owned(db_conn, candidacy_id) is True


def test_match_skips_non_nc_candidacy_with_same_name(
    db_conn: psycopg.Connection,
) -> None:
    """The matcher must filter to NC offices only — non-NC candidacies are ignored."""
    sc_candidacy_id = _seed_non_nc_candidacy(
        db_conn,
        person_name="Pat Shared",
        name_on_ballot="PAT SHARED",
    )
    committee_id = _materialize_nc_committee(
        db_conn,
        sboe_id="STA-SHARED-C-001",
        committee_name="PAT SHARED COMMITTEE",
    )

    updated = _match_and_update_nc_candidacy_committee(
        db_conn,
        candidate_name="PAT SHARED",
        committee_id=committee_id,
    )

    assert updated == 0
    assert _select_candidacy_committee_id(db_conn, sc_candidacy_id) is None


def test_match_blank_or_none_candidate_name_is_a_noop(
    db_conn: psycopg.Connection,
) -> None:
    """Registry rows with no candidate_name (e.g. party committees) must not match anything."""
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Casey Empty",
        name_on_ballot="CASEY EMPTY",
    )
    committee_id = _materialize_nc_committee(
        db_conn,
        sboe_id="STA-EMPTY-C-001",
        committee_name="STATE PARTY COMMITTEE",
    )

    assert _match_and_update_nc_candidacy_committee(db_conn, candidate_name=None, committee_id=committee_id) == 0
    assert _match_and_update_nc_candidacy_committee(db_conn, candidate_name="   ", committee_id=committee_id) == 0
    assert _select_candidacy_committee_id(db_conn, candidacy_id) is None


def test_unique_candidacy_selector_matches_matcher_semantics(
    db_conn: psycopg.Connection,
) -> None:
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Selector Solo",
        name_on_ballot="SELECTOR  SOLO",
    )
    assert _select_unique_nc_candidacy_id_for_bridge_name(db_conn, candidate_name=" SELECTOR SOLO ") == candidacy_id

    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT office_id FROM civic.contest WHERE id = (SELECT contest_id FROM civic.candidacy WHERE id = %s)",
            (candidacy_id,),
        )
        office_id: UUID = cursor.fetchone()[0]
    _seed_nc_candidacy_in_existing_office(
        db_conn,
        person_name="Selector Two",
        name_on_ballot="SELECTOR SOLO",
        office_id=office_id,
    )
    assert _select_unique_nc_candidacy_id_for_bridge_name(db_conn, candidate_name="SELECTOR SOLO") is None


def test_bridge_blank_candidate_without_clear_does_not_materialize_committee(
    db_conn: psycopg.Connection,
) -> None:
    row = NCCommitteeRegistryRow(
        org_group_id=99123,
        sboe_id="STA-BLANK-C-001",
        committee_name="BLANK CANDIDATE COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-BLANK",
        candidate_name="   ",
    )

    updated = _bridge_nc_registry_row_to_candidacy(
        db_conn,
        row,
        clear_stale_links=False,
    )

    assert updated == 0
    assert _select_nc_committee_count(db_conn, native_committee_id="STA-BLANK-C-001") == 0


# ---------------------------------------------------------------------------
# Integration: load_nc_committee_registry_rows runs the bridge pass
# ---------------------------------------------------------------------------


def test_load_nc_committee_registry_rows_runs_candidacy_bridge_pass(
    db_conn: psycopg.Connection,
) -> None:
    """``load_nc_committee_registry_rows`` must run the bridge after registry upsert.

    The persisted ``cf.nc_committee_registry`` row remains the single source of
    truth for the bridge pass; this test asserts the side effect on
    ``civic.candidacy.committee_id`` after the loader finishes.
    """
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Drew Bridge",
        name_on_ballot="DREW BRIDGE",
    )
    # Pre-create the org bridge so _resolve_nc_committee_bridge can use the
    # registered NC committee_name instead of failing the no-name path.
    insert_organization(
        db_conn,
        Organization(
            canonical_name="DREW BRIDGE COMMITTEE STA-BRIDGE-C-001",
            identifiers={"nc_sboe_id": "STA-BRIDGE-C-001"},
        ),
    )
    row = NCCommitteeRegistryRow(
        org_group_id=99001,
        sboe_id="STA-BRIDGE-C-001",
        committee_name="DREW BRIDGE COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-BRIDGE",
        candidate_name="  DREW   BRIDGE  ",  # exercise normalization
    )

    result = load_nc_committee_registry_rows(
        db_conn,
        [row],
        seen_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )

    assert result.inserted == 1
    assert result.errors == 0

    # Verify the registry row landed (SSOT for the bridge pass).
    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT candidate_name FROM cf.nc_committee_registry WHERE org_group_id = %s",
            (99001,),
        )
        registry_candidate_name = cursor.fetchone()[0]
    assert registry_candidate_name == "  DREW   BRIDGE  "

    # Verify the NC bridge owner materialized the committee row.
    bridged_committee_id = _resolve_nc_committee_bridge(
        db_conn, "STA-BRIDGE-C-001", committee_name="DREW BRIDGE COMMITTEE"
    )
    assert _select_candidacy_committee_id(db_conn, candidacy_id) == bridged_committee_id


def test_load_nc_committee_registry_rows_bridge_pass_is_idempotent(
    db_conn: psycopg.Connection,
) -> None:
    """Re-running the loader against the same row must leave committee_id stable."""
    candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Jamie Stable",
        name_on_ballot="JAMIE STABLE",
    )
    insert_organization(
        db_conn,
        Organization(
            canonical_name="JAMIE STABLE COMMITTEE STA-STABLE-C-001",
            identifiers={"nc_sboe_id": "STA-STABLE-C-001"},
        ),
    )
    row = NCCommitteeRegistryRow(
        org_group_id=99002,
        sboe_id="STA-STABLE-C-001",
        committee_name="JAMIE STABLE COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-STABLE",
        candidate_name="JAMIE STABLE",
    )

    load_nc_committee_registry_rows(
        db_conn,
        [row],
        seen_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )
    bridged_committee_id = _resolve_nc_committee_bridge(
        db_conn, "STA-STABLE-C-001", committee_name="JAMIE STABLE COMMITTEE"
    )
    first_committee_id = _select_candidacy_committee_id(db_conn, candidacy_id)
    assert first_committee_id == bridged_committee_id

    # Second run.
    load_nc_committee_registry_rows(
        db_conn,
        [row],
        seen_at=datetime(2026, 4, 29, 13, 0, tzinfo=UTC),
    )
    second_committee_id = _select_candidacy_committee_id(db_conn, candidacy_id)
    assert second_committee_id == bridged_committee_id


def test_load_nc_committee_registry_rows_rerun_candidate_name_change_clears_stale_bridge(
    db_conn: psycopg.Connection,
) -> None:
    """Rerun corrections must remove stale committee bridge from prior candidate_name."""
    old_candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Taylor Old",
        name_on_ballot="TAYLOR OLD",
    )
    new_candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Taylor New",
        name_on_ballot="TAYLOR NEW",
    )
    insert_organization(
        db_conn,
        Organization(
            canonical_name="TAYLOR COMMITTEE STA-CORRECT-C-001",
            identifiers={"nc_sboe_id": "STA-CORRECT-C-001"},
        ),
    )
    original_row = NCCommitteeRegistryRow(
        org_group_id=99003,
        sboe_id="STA-CORRECT-C-001",
        committee_name="TAYLOR COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-CORRECT",
        candidate_name="TAYLOR OLD",
    )
    corrected_row = NCCommitteeRegistryRow(
        org_group_id=99003,
        sboe_id="STA-CORRECT-C-001",
        committee_name="TAYLOR COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-CORRECT",
        candidate_name="TAYLOR NEW",
    )

    load_nc_committee_registry_rows(
        db_conn,
        [original_row],
        seen_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )
    committee_id = _resolve_nc_committee_bridge(db_conn, "STA-CORRECT-C-001", committee_name="TAYLOR COMMITTEE")
    assert _select_candidacy_committee_id(db_conn, old_candidacy_id) == committee_id
    assert _select_candidacy_committee_id(db_conn, new_candidacy_id) is None

    load_nc_committee_registry_rows(
        db_conn,
        [corrected_row],
        seen_at=datetime(2026, 4, 29, 13, 0, tzinfo=UTC),
    )

    assert _select_candidacy_committee_id(db_conn, old_candidacy_id) is None
    assert _select_candidacy_committee_id(db_conn, new_candidacy_id) == committee_id


def test_load_nc_committee_registry_rows_rerun_same_name_ambiguous_preserves_existing_bridge(
    db_conn: psycopg.Connection,
) -> None:
    """Unchanged-name reruns must preserve an existing bridge on ambiguous matches."""
    first_candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Riley One",
        name_on_ballot="RILEY SAME",
        office_name="NC State Senate District Riley",
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT office_id FROM civic.contest WHERE id = (SELECT contest_id FROM civic.candidacy WHERE id = %s)",
            (first_candidacy_id,),
        )
        shared_office_id: UUID = cursor.fetchone()[0]
    insert_organization(
        db_conn,
        Organization(
            canonical_name="RILEY SAME COMMITTEE STA-SAME-C-001",
            identifiers={"nc_sboe_id": "STA-SAME-C-001"},
        ),
    )
    row = NCCommitteeRegistryRow(
        org_group_id=99004,
        sboe_id="STA-SAME-C-001",
        committee_name="RILEY SAME COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-SAME",
        candidate_name="RILEY SAME",
    )

    load_nc_committee_registry_rows(
        db_conn,
        [row],
        seen_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )
    committee_id = _resolve_nc_committee_bridge(db_conn, "STA-SAME-C-001", committee_name="RILEY SAME COMMITTEE")
    assert _select_candidacy_committee_id(db_conn, first_candidacy_id) == committee_id

    second_candidacy_id = _seed_nc_candidacy_in_existing_office(
        db_conn,
        person_name="Riley Two",
        name_on_ballot="RILEY SAME",
        office_id=shared_office_id,
    )
    assert _select_candidacy_committee_id(db_conn, second_candidacy_id) is None

    load_nc_committee_registry_rows(
        db_conn,
        [row],
        seen_at=datetime(2026, 4, 29, 13, 0, tzinfo=UTC),
    )

    # Same authoritative registry name, now ambiguous: keep prior valid bridge.
    assert _select_candidacy_committee_id(db_conn, first_candidacy_id) == committee_id
    assert _select_candidacy_committee_id(db_conn, second_candidacy_id) is None


def test_load_nc_committee_registry_rows_rerun_sboe_change_clears_stale_old_committee_link(
    db_conn: psycopg.Connection,
) -> None:
    """SBoE id corrections must clear stale links tied to the prior committee id."""
    old_candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Morgan Prior",
        name_on_ballot="MORGAN PRIOR",
    )
    new_candidacy_id = _seed_nc_candidacy(
        db_conn,
        person_name="Morgan Current",
        name_on_ballot="MORGAN CURRENT",
    )
    insert_organization(
        db_conn,
        Organization(
            canonical_name="MORGAN COMMITTEE STA-MORGAN-C-OLD",
            identifiers={"nc_sboe_id": "STA-MORGAN-C-OLD"},
        ),
    )
    insert_organization(
        db_conn,
        Organization(
            canonical_name="MORGAN COMMITTEE STA-MORGAN-C-NEW",
            identifiers={"nc_sboe_id": "STA-MORGAN-C-NEW"},
        ),
    )
    original_row = NCCommitteeRegistryRow(
        org_group_id=99005,
        sboe_id="STA-MORGAN-C-OLD",
        committee_name="MORGAN COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-MORGAN",
        candidate_name="MORGAN PRIOR",
    )
    corrected_row = NCCommitteeRegistryRow(
        org_group_id=99005,
        sboe_id="STA-MORGAN-C-NEW",
        committee_name="MORGAN COMMITTEE",
        status_desc="ACTIVE (EXEMPT)",
        old_id="OLD-MORGAN",
        candidate_name="MORGAN CURRENT",
    )

    load_nc_committee_registry_rows(
        db_conn,
        [original_row],
        seen_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )
    old_committee_id = _resolve_nc_committee_bridge(db_conn, "STA-MORGAN-C-OLD", committee_name="MORGAN COMMITTEE")
    assert _select_candidacy_committee_id(db_conn, old_candidacy_id) == old_committee_id
    assert _select_candidacy_committee_id(db_conn, new_candidacy_id) is None

    load_nc_committee_registry_rows(
        db_conn,
        [corrected_row],
        seen_at=datetime(2026, 4, 29, 13, 0, tzinfo=UTC),
    )
    new_committee_id = _resolve_nc_committee_bridge(db_conn, "STA-MORGAN-C-NEW", committee_name="MORGAN COMMITTEE")

    assert _select_candidacy_committee_id(db_conn, old_candidacy_id) is None
    assert _select_candidacy_committee_id(db_conn, new_candidacy_id) == new_committee_id
