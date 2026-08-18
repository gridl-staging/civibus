"""Reconcile stored federal contest rows with the current ingest rules.

Two ingest fixes do not clean data that is already in the database, so this
script closes the gap:

1. **Names.** ``federal_contest_display_name`` now includes the district, but
   rows written before that change still read ``H CA General 2026`` — 52 of them
   identically. ``civic.contest.name`` is read by search, election lists, page
   titles and JSON-LD, so until those rows are rewritten every California House
   race is indistinguishable everywhere it appears.

2. **Election years.** ``load_federal_fec_races`` now refuses years outside its
   window, but rejected rows ``continue`` before any supersession path, so
   contests dated 2089 and 2929 persist. They serve HTTP 200 race pages, appear
   on /calendar, and sort to the TOP of ``/office/[id]``'s recent-contests list
   because that query orders by election_date descending.

Both operations write to production, so both are dry-run by default and print
exactly what they would do. The repaired names are produced by the one naming
owner — this script never restates the naming rules.

Lives under ``domains/civics/scripts`` rather than the repo-root ``scripts``
directory because only ``api``, ``core``, ``domains`` and ``tests`` are in
pytest's ``testpaths``. A repair that writes to production must have tests that
actually run in CI, and root-level ``scripts/test_*.py`` files are collected by
nothing.

Usage (dry run by default — it writes only when told to):

    uv run python -m domains.civics.scripts.repair_federal_contest_records \
        --max-election-year 2030
    uv run python -m domains.civics.scripts.repair_federal_contest_records \
        --max-election-year 2030 --apply-names --apply-removals
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.ingest.fec_canonical_loader import federal_contest_display_name

# The three federal offices the FEC candidate-to-civic mapping creates contests
# for. Scoping by office id rather than office_level is deliberate: office_level
# 'federal' also covers rows other loaders own, and the naming rules here are
# specific to the FEC House/Senate/President mapping.
_OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
_OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")
_OFFICE_US_PRESIDENT = UUID("00000000-0000-4000-8000-000000000103")
_FEDERAL_OFFICE_CODE_BY_ID = {
    _OFFICE_US_HOUSE: "H",
    _OFFICE_US_SENATE: "S",
    _OFFICE_US_PRESIDENT: "P",
}

_FEDERAL_CONTESTS_SQL = """
    SELECT
        c.id AS contest_id,
        c.name,
        c.office_id,
        c.election_date,
        ed.state AS division_state,
        ed.district_number
    FROM civic.contest c
    LEFT JOIN civic.electoral_division ed ON ed.id = c.electoral_division_id
    WHERE c.office_id = ANY(%s::uuid[])
      AND c.election_date IS NOT NULL
      AND c.election_type = 'general'
    ORDER BY c.election_date, c.name, c.id
"""

_OUT_OF_WINDOW_CONTESTS_SQL = """
    SELECT
        c.id AS contest_id,
        c.name,
        c.election_date,
        COUNT(cd.id)::int AS candidacy_count
    FROM civic.contest c
    LEFT JOIN civic.candidacy cd ON cd.contest_id = c.id
    WHERE c.office_id = ANY(%s::uuid[])
      AND c.election_date IS NOT NULL
      AND EXTRACT(YEAR FROM c.election_date) > %s
    GROUP BY c.id, c.name, c.election_date
    ORDER BY c.election_date, c.id
"""


@dataclass(frozen=True, slots=True)
class ContestNameRepair:
    contest_id: UUID
    current_name: str
    repaired_name: str


@dataclass(frozen=True, slots=True)
class OutOfWindowContest:
    contest_id: UUID
    name: str
    election_year: int
    # Surfaced rather than silently swallowed: removing a contest also removes
    # its candidacies, and the operator should see that cost before approving.
    candidacy_count: int


@dataclass(frozen=True, slots=True)
class RemovalCounts:
    contests: int
    candidacies: int


def _repaired_name_for_row(row: dict[str, Any]) -> str | None:
    """Rebuild one contest's canonical name, or None when it is not ours to name."""
    office_code = _FEDERAL_OFFICE_CODE_BY_ID.get(row["office_id"])
    if office_code is None:
        return None

    return federal_contest_display_name(
        office_code=office_code,
        state=row["division_state"],
        district=row["district_number"],
        election_year=row["election_date"].year,
    )


def plan_contest_name_repairs(conn: psycopg.Connection) -> list[ContestNameRepair]:
    """Return every federal contest whose stored name differs from the canonical one.

    Rows already carrying the canonical name are excluded: a no-op UPDATE against
    production is not free, and reporting one as work would overstate the repair.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_FEDERAL_CONTESTS_SQL, (list(_FEDERAL_OFFICE_CODE_BY_ID),))
        rows = list(cursor.fetchall())

    repairs: list[ContestNameRepair] = []
    for row in rows:
        repaired_name = _repaired_name_for_row(row)
        if repaired_name is None or repaired_name == row["name"]:
            continue
        repairs.append(
            ContestNameRepair(
                contest_id=row["contest_id"],
                current_name=row["name"],
                repaired_name=repaired_name,
            )
        )
    return repairs


def apply_contest_name_repairs(conn: psycopg.Connection, repairs: list[ContestNameRepair]) -> int:
    """Write the planned names. Returns the number of rows updated."""
    for repair in repairs:
        if repair.current_name == repair.repaired_name:
            raise ValueError(
                f"Refusing a no-op name repair for {repair.contest_id}: current and repaired names are identical"
            )

    updated = 0
    with conn.cursor() as cursor:
        for repair in repairs:
            cursor.execute(
                "UPDATE civic.contest SET name = %s, updated_at = NOW() WHERE id = %s",
                (repair.repaired_name, repair.contest_id),
            )
            updated += cursor.rowcount
    return updated


def plan_out_of_window_contest_removals(
    conn: psycopg.Connection, *, max_election_year: int
) -> list[OutOfWindowContest]:
    """Return federal contests dated beyond the loader's election-year ceiling."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _OUT_OF_WINDOW_CONTESTS_SQL,
            (list(_FEDERAL_OFFICE_CODE_BY_ID), max_election_year),
        )
        rows = list(cursor.fetchall())

    return [
        OutOfWindowContest(
            contest_id=row["contest_id"],
            name=row["name"],
            election_year=row["election_date"].year,
            candidacy_count=row["candidacy_count"],
        )
        for row in rows
    ]


def apply_out_of_window_contest_removals(conn: psycopg.Connection, removals: list[OutOfWindowContest]) -> RemovalCounts:
    """Delete the planned contests and their candidacies.

    Only the contest and its candidacy rows go. Person records stay: the person
    is real even when the filer-supplied election year was a typo, and the
    project rule is never to delete historical data beyond the corrupt chain.
    """
    if not removals:
        return RemovalCounts(contests=0, candidacies=0)

    contest_ids = [removal.contest_id for removal in removals]
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM civic.candidacy WHERE contest_id = ANY(%s::uuid[])", (contest_ids,))
        removed_candidacies = cursor.rowcount
        cursor.execute("DELETE FROM civic.contest WHERE id = ANY(%s::uuid[])", (contest_ids,))
        removed_contests = cursor.rowcount
    return RemovalCounts(contests=removed_contests, candidacies=removed_candidacies)


def _print_plan(repairs: list[ContestNameRepair], removals: list[OutOfWindowContest], *, sample: int) -> None:
    print(f"contest name repairs planned: {len(repairs)}")
    for repair in repairs[:sample]:
        print(f"  {repair.contest_id}  {repair.current_name!r} -> {repair.repaired_name!r}")
    if len(repairs) > sample:
        print(f"  ... {len(repairs) - sample} more")

    total_candidacies = sum(removal.candidacy_count for removal in removals)
    print(f"out-of-window contest removals planned: {len(removals)} ({total_candidacies} candidacies)")
    for removal in removals[:sample]:
        print(
            f"  {removal.contest_id}  {removal.election_year}  {removal.name!r}  candidacies={removal.candidacy_count}"
        )
    if len(removals) > sample:
        print(f"  ... {len(removals) - sample} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-election-year",
        type=int,
        required=True,
        help="Ceiling matching the loader's window (fec_cycle + 4).",
    )
    parser.add_argument("--apply-names", action="store_true", help="Write the repaired contest names.")
    parser.add_argument(
        "--apply-removals", action="store_true", help="Delete out-of-window contests and their candidacies."
    )
    parser.add_argument("--sample", type=int, default=10, help="Rows to print per section.")
    args = parser.parse_args(argv)

    connection = get_connection()
    try:
        repairs = plan_contest_name_repairs(connection)
        removals = plan_out_of_window_contest_removals(connection, max_election_year=args.max_election_year)
        _print_plan(repairs, removals, sample=args.sample)

        if not args.apply_names and not args.apply_removals:
            print("dry run: nothing written (pass --apply-names and/or --apply-removals)")
            return 0

        if args.apply_names:
            updated = apply_contest_name_repairs(connection, repairs)
            print(f"contest names updated: {updated}")
        if args.apply_removals:
            counts = apply_out_of_window_contest_removals(connection, removals)
            print(f"contests removed: {counts.contests}, candidacies removed: {counts.candidacies}")
        connection.commit()
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
