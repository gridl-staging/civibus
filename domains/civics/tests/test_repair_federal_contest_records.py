"""Tests for the federal contest record repair script.

The script exists because two ingest fixes do not retroactively clean data that
is already in the database:

* ``federal_contest_display_name`` now includes the district, but the ~515 rows
  loaded before that change still read "H CA General 2026" — 52 of them
  identically.
* ``load_federal_fec_races`` now refuses election years outside its window, but
  rows rejected at ingest ``continue`` before any supersession path, so contests
  dated 2089 and 2929 persist and keep serving live pages.

Both repairs are destructive-ish (an UPDATE and a DELETE against production), so
every behaviour here is pinned: what gets selected, what gets skipped, and that
dry-run changes nothing.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from domains.campaign_finance.ingest.fec_canonical_loader import federal_contest_display_name
from domains.civics.scripts.repair_federal_contest_records import (
    ContestNameRepair,
    plan_contest_name_repairs,
    plan_out_of_window_contest_removals,
    apply_contest_name_repairs,
    apply_out_of_window_contest_removals,
)

pytestmark = pytest.mark.integration

OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")


def _insert_division(
    conn: psycopg.Connection, *, name: str, division_type: str, state: str, district: str | None
) -> UUID:
    """Insert a division under a collision-proof name.

    The integration database is seeded with a real FEC bulk sample, which
    already owns the natural names ("ga", "nc_cd_09", ...). uq_electoral_division_canonical_key
    covers the name, so a fixture reusing one aborts the transaction. Only
    ``state`` and ``district`` feed the naming rules under test, so a unique
    name suffix costs the assertions nothing.
    """
    division_id = uuid4()
    conn.execute(
        """
        INSERT INTO civic.electoral_division (id, name, division_type, state, district_number)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (division_id, f"{name}_repairtest_{division_id.hex[:8]}", division_type, state, district),
    )
    return division_id


def _insert_contest(
    conn: psycopg.Connection,
    *,
    name: str,
    office_id: UUID,
    election_date: date,
    division_id: UUID | None = None,
) -> UUID:
    contest_id = uuid4()
    conn.execute(
        """
        INSERT INTO civic.contest (id, name, election_date, election_type, office_id, electoral_division_id)
        VALUES (%s, %s, %s, 'general', %s, %s)
        """,
        (contest_id, name, election_date, office_id, division_id),
    )
    return contest_id


class TestContestNameRepairPlan:
    def test_plans_a_district_qualified_name_for_a_stale_house_contest(self, db_conn: psycopg.Connection) -> None:
        division_id = _insert_division(
            db_conn, name="nc_cd_09", division_type="congressional_district", state="NC", district="09"
        )
        contest_id = _insert_contest(
            db_conn,
            name="H NC General 2024",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2024, 11, 5),
            division_id=division_id,
        )

        repairs = {repair.contest_id: repair for repair in plan_contest_name_repairs(db_conn)}

        assert contest_id in repairs
        assert repairs[contest_id].current_name == "H NC General 2024"
        # Derived from the one naming owner, not restated here.
        assert repairs[contest_id].repaired_name == federal_contest_display_name(
            office_code="H", state="NC", district="09", election_year=2024
        )
        assert repairs[contest_id].repaired_name.startswith("North Carolina 9th Congressional District")

    def test_two_house_contests_in_one_state_stop_sharing_a_name(self, db_conn: psycopg.Connection) -> None:
        """The whole point: 52 California House races were one indistinct string."""
        contest_ids = []
        for district in ("01", "02"):
            division_id = _insert_division(
                db_conn,
                name=f"ca_cd_{district}",
                division_type="congressional_district",
                state="CA",
                district=district,
            )
            contest_ids.append(
                _insert_contest(
                    db_conn,
                    name="H CA General 2026",
                    office_id=OFFICE_US_HOUSE,
                    election_date=date(2026, 11, 3),
                    division_id=division_id,
                )
            )

        repairs = {repair.contest_id: repair for repair in plan_contest_name_repairs(db_conn)}

        repaired = {repairs[contest_id].repaired_name for contest_id in contest_ids}
        assert len(repaired) == 2

    def test_senate_contest_uses_the_statewide_seat_name(self, db_conn: psycopg.Connection) -> None:
        division_id = _insert_division(db_conn, name="ga", division_type="statewide", state="GA", district=None)
        contest_id = _insert_contest(
            db_conn,
            name="S GA General 2026",
            office_id=OFFICE_US_SENATE,
            election_date=date(2026, 11, 3),
            division_id=division_id,
        )

        repairs = {repair.contest_id: repair for repair in plan_contest_name_repairs(db_conn)}

        assert repairs[contest_id].repaired_name == "Georgia U.S. Senate — 2026 General Election"

    def test_already_correct_names_are_not_planned(self, db_conn: psycopg.Connection) -> None:
        """A no-op UPDATE against production is not free; skip rows already right."""
        division_id = _insert_division(
            db_conn, name="wy_cd_00", division_type="congressional_district", state="WY", district="00"
        )
        contest_id = _insert_contest(
            db_conn,
            name="Wyoming At-Large Congressional District — 2026 General Election",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2026, 11, 3),
            division_id=division_id,
        )

        planned_ids = {repair.contest_id for repair in plan_contest_name_repairs(db_conn)}

        assert contest_id not in planned_ids

    def test_non_federal_contests_are_left_alone(self, db_conn: psycopg.Connection) -> None:
        """The naming owner is federal-only; state contests have other loaders."""
        state_office_id = uuid4()
        db_conn.execute(
            """
            INSERT INTO civic.office (id, name, office_level, title, state, is_elected, number_of_seats)
            VALUES (%s, %s, 'state', 'Attorney General', 'NC', TRUE, 1)
            """,
            (state_office_id, f"test_repair_state_office_{state_office_id.hex[:8]}"),
        )
        contest_id = _insert_contest(
            db_conn,
            name="NC Attorney General 2026",
            office_id=state_office_id,
            election_date=date(2026, 11, 3),
        )

        planned_ids = {repair.contest_id for repair in plan_contest_name_repairs(db_conn)}

        assert contest_id not in planned_ids


class TestContestNameRepairApply:
    def test_apply_writes_the_planned_names(self, db_conn: psycopg.Connection) -> None:
        division_id = _insert_division(
            db_conn, name="nc_cd_11", division_type="congressional_district", state="NC", district="11"
        )
        contest_id = _insert_contest(
            db_conn,
            name="H NC General 2026",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2026, 11, 3),
            division_id=division_id,
        )
        repairs = [repair for repair in plan_contest_name_repairs(db_conn) if repair.contest_id == contest_id]

        updated = apply_contest_name_repairs(db_conn, repairs)

        assert updated == 1
        stored_name = db_conn.execute("SELECT name FROM civic.contest WHERE id = %s", (contest_id,)).fetchone()[0]
        assert stored_name == "North Carolina 11th Congressional District — 2026 General Election"

    def test_apply_is_idempotent(self, db_conn: psycopg.Connection) -> None:
        division_id = _insert_division(
            db_conn, name="nc_cd_12", division_type="congressional_district", state="NC", district="12"
        )
        _insert_contest(
            db_conn,
            name="H NC General 2026",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2026, 11, 3),
            division_id=division_id,
        )
        apply_contest_name_repairs(db_conn, list(plan_contest_name_repairs(db_conn)))

        second_pass = list(plan_contest_name_repairs(db_conn))

        assert second_pass == []

    def test_apply_rejects_a_repair_whose_name_did_not_change(self, db_conn: psycopg.Connection) -> None:
        """Guard against a caller hand-building a no-op and reporting it as work."""
        with pytest.raises(ValueError, match="identical"):
            apply_contest_name_repairs(
                db_conn,
                [ContestNameRepair(contest_id=uuid4(), current_name="same", repaired_name="same")],
            )


class TestOutOfWindowRemoval:
    def test_plans_only_contests_beyond_the_ceiling(self, db_conn: psycopg.Connection) -> None:
        in_window = _insert_contest(
            db_conn,
            name="in window",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2030, 11, 5),
        )
        corrupt = _insert_contest(
            db_conn,
            name="corrupt",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2929, 11, 8),
        )

        planned_ids = {row.contest_id for row in plan_out_of_window_contest_removals(db_conn, max_election_year=2030)}

        assert corrupt in planned_ids
        assert in_window not in planned_ids

    def test_a_contest_with_candidacies_is_reported_not_silently_skipped(self, db_conn: psycopg.Connection) -> None:
        """Deleting a contest orphans its candidacies, so the plan must say so."""
        from core.db import insert_person
        from core.types.python.models import Person

        person = Person(canonical_name="Corrupt Year Filer")
        insert_person(db_conn, person)
        corrupt = _insert_contest(
            db_conn,
            name="corrupt with candidacy",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2089, 11, 8),
        )
        db_conn.execute(
            "INSERT INTO civic.candidacy (id, person_id, contest_id) VALUES (%s, %s, %s)",
            (uuid4(), person.id, corrupt),
        )

        planned = {row.contest_id: row for row in plan_out_of_window_contest_removals(db_conn, max_election_year=2030)}

        assert planned[corrupt].candidacy_count == 1

    def test_apply_removes_the_contest_and_its_candidacies(self, db_conn: psycopg.Connection) -> None:
        from core.db import insert_person
        from core.types.python.models import Person

        person = Person(canonical_name="Removed Filer")
        insert_person(db_conn, person)
        corrupt = _insert_contest(
            db_conn,
            name="corrupt to remove",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2820, 11, 4),
        )
        db_conn.execute(
            "INSERT INTO civic.candidacy (id, person_id, contest_id) VALUES (%s, %s, %s)",
            (uuid4(), person.id, corrupt),
        )
        removals = [
            row
            for row in plan_out_of_window_contest_removals(db_conn, max_election_year=2030)
            if row.contest_id == corrupt
        ]

        removed = apply_out_of_window_contest_removals(db_conn, removals)

        assert removed.contests == 1
        assert removed.candidacies == 1
        assert db_conn.execute("SELECT COUNT(*) FROM civic.contest WHERE id = %s", (corrupt,)).fetchone()[0] == 0
        assert (
            db_conn.execute("SELECT COUNT(*) FROM civic.candidacy WHERE contest_id = %s", (corrupt,)).fetchone()[0] == 0
        )

    def test_removal_leaves_the_person_record_intact(self, db_conn: psycopg.Connection) -> None:
        """Never delete historical data beyond the corrupt contest chain itself."""
        from core.db import insert_person
        from core.types.python.models import Person

        person = Person(canonical_name="Surviving Filer")
        insert_person(db_conn, person)
        corrupt = _insert_contest(
            db_conn,
            name="corrupt person survives",
            office_id=OFFICE_US_HOUSE,
            election_date=date(2040, 11, 6),
        )
        db_conn.execute(
            "INSERT INTO civic.candidacy (id, person_id, contest_id) VALUES (%s, %s, %s)",
            (uuid4(), person.id, corrupt),
        )
        removals = [
            row
            for row in plan_out_of_window_contest_removals(db_conn, max_election_year=2030)
            if row.contest_id == corrupt
        ]

        apply_out_of_window_contest_removals(db_conn, removals)

        assert db_conn.execute("SELECT COUNT(*) FROM core.person WHERE id = %s", (person.id,)).fetchone()[0] == 1
