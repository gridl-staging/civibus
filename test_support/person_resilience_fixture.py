"""Dedicated person-page resilience specimen: seed, poison, restore, cleanup.

The browser journey web/tests/smoke/person_resilience.spec.ts (civibus-e7v)
owns the degradation contract of docs/reference/screen_specs/person_detail.md
at the browser level: a finance-section backend failure must leave the person
page HTTP 200 with bio/office content and render the section's explicit
unavailable notice, never a raw 500.

The poison targets the failure class civibus-ga8 diagnosed (arm C at the
contract seam: a stored value that is schema-legal at the column but illegal
at the response contract). ``cf.candidate.total_receipts`` is ``NUMERIC(14,2)``
and PostgreSQL numerics accept ``NaN``, while the API's
``CandidateFundraisingSummary.total_raised`` is a pydantic ``Decimal`` that
rejects non-finite values — so ``GET /v1/candidates/{id}/summary`` fails while
``GET /v1/person/{id}`` stays valid, which is exactly the partial-failure shape
the degradation contract exists for.

This specimen is DEDICATED: no other spec may reference it (the journey's
contract test greps web/tests/smoke/ for exactly that), so the poisoned window
inside the journey's try/finally can never be observed by a parallel worker.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg

from api.test_campaign_finance_support import (
    CandidateRowSeed,
    insert_candidate_row,
    insert_electoral_division_row,
    insert_office_row,
    insert_officeholding_row,
)
from core.db import get_connection, insert_person
from core.types.python.models import Person

# Canonical literals, mirrored (not imported — the TS fixture cannot import
# Python) in web/tests/smoke/person_resilience_fixture.ts. Digit-free names:
# the identity predicate silently suppresses digit-bearing names.
SMOKE_RESILIENCE_PERSON_ID = "e5111111-1111-4111-8111-111111111111"
SMOKE_RESILIENCE_PERSON_CANONICAL_NAME = "Riley Resilience"
SMOKE_RESILIENCE_CANDIDATE_ID = "e5222222-2222-4222-8222-222222222222"
SMOKE_RESILIENCE_CANDIDATE_FEC_ID = "H6NC05901"
SMOKE_RESILIENCE_CANDIDATE_NAME = "Resilience, Riley"
SMOKE_RESILIENCE_TOTAL_RECEIPTS = Decimal("400.00")

_DIVISION_ID = UUID("e5333333-3333-4333-8333-333333333333")
_OFFICEHOLDING_ID = UUID("e5444444-4444-4444-8444-444444444444")
# Fallback office id, used only when no shared us_house office row exists yet.
_OFFICE_ID = UUID("e5555555-5555-4555-8555-555555555555")


def seed_person_resilience_fixture(conn: psycopg.Connection) -> None:
    """Idempotently (re)seed the dedicated specimen: person, office context, candidate."""
    cleanup_person_resilience_fixture(conn)
    insert_person(
        conn,
        Person(
            id=UUID(SMOKE_RESILIENCE_PERSON_ID),
            canonical_name=SMOKE_RESILIENCE_PERSON_CANONICAL_NAME,
            first_name="Riley",
            last_name="Resilience",
        ),
    )
    insert_electoral_division_row(
        conn,
        division_id=_DIVISION_ID,
        name="resilience_nc_cd_05",
        division_type="congressional_district",
        state="NC",
        district_number="05",
    )
    insert_officeholding_row(
        conn,
        officeholding_id=_OFFICEHOLDING_ID,
        person_id=UUID(SMOKE_RESILIENCE_PERSON_ID),
        office_id=_resolve_or_seed_house_office(conn),
        electoral_division_id=_DIVISION_ID,
        valid_period="[2025-01-03,2100-01-01)",
    )
    # Official FEC totals with in-cycle coverage: the summary endpoint serves
    # the weball path, which is where the poisoned NaN must surface.
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=UUID(SMOKE_RESILIENCE_CANDIDATE_ID),
            fec_candidate_id=SMOKE_RESILIENCE_CANDIDATE_FEC_ID,
            name=SMOKE_RESILIENCE_CANDIDATE_NAME,
            office="H",
            person_id=UUID(SMOKE_RESILIENCE_PERSON_ID),
            principal_committee_id=None,
            source_record_id=None,
            party="DEM",
            state="NC",
            district="05",
            incumbent_challenge="I",
            total_receipts=SMOKE_RESILIENCE_TOTAL_RECEIPTS,
            total_disbursements=Decimal("150.00"),
            cash_on_hand=Decimal("250.00"),
            summary_coverage_end_date=date(2026, 3, 31),
        ),
    )


def poison_person_resilience_candidate(conn: psycopg.Connection) -> None:
    """Write the ga8-class poison: column-legal, response-contract-illegal.

    ``NUMERIC`` accepts ``NaN`` at the column while the response model requires
    a finite Decimal, so the candidate summary producer fails and the person
    page's selected-cycle money section degrades — the seam the journey guards.
    """
    updated = conn.execute(
        "UPDATE cf.candidate SET total_receipts = 'NaN'::numeric WHERE id = %s",
        (UUID(SMOKE_RESILIENCE_CANDIDATE_ID),),
    ).rowcount
    if updated != 1:
        raise RuntimeError(f"Resilience poison expected exactly 1 candidate row, updated {updated}")


def restore_person_resilience_candidate(conn: psycopg.Connection) -> None:
    """Undo the poison, restoring the seeded official total."""
    updated = conn.execute(
        "UPDATE cf.candidate SET total_receipts = %s WHERE id = %s",
        (SMOKE_RESILIENCE_TOTAL_RECEIPTS, UUID(SMOKE_RESILIENCE_CANDIDATE_ID)),
    ).rowcount
    if updated != 1:
        raise RuntimeError(f"Resilience restore expected exactly 1 candidate row, updated {updated}")


def cleanup_person_resilience_fixture(conn: psycopg.Connection) -> None:
    """Remove every specimen row; keep the shared us_house office if others use it."""
    conn.execute("DELETE FROM cf.candidate WHERE id = %s", (UUID(SMOKE_RESILIENCE_CANDIDATE_ID),))
    conn.execute(
        "DELETE FROM civic.officeholding WHERE id = %s OR person_id = %s",
        (_OFFICEHOLDING_ID, UUID(SMOKE_RESILIENCE_PERSON_ID)),
    )
    conn.execute(
        """
        DELETE FROM civic.office
        WHERE id = %s
          AND NOT EXISTS (
              SELECT 1
              FROM civic.officeholding officeholding
              WHERE officeholding.office_id = civic.office.id
          )
        """,
        (_OFFICE_ID,),
    )
    conn.execute("DELETE FROM civic.electoral_division WHERE id = %s", (_DIVISION_ID,))
    conn.execute("DELETE FROM core.person WHERE id = %s", (UUID(SMOKE_RESILIENCE_PERSON_ID),))


def _resolve_or_seed_house_office(conn: psycopg.Connection) -> UUID:
    """Reuse the shared federal us_house office row; seed a fallback if absent.

    Same resolution contract as test_support/browser_smoke_seed.py: the live
    smoke database keeps ONE canonical us_house office, and a second row would
    split the /congress directory's office join.
    """
    row = conn.execute(
        """
        SELECT id
        FROM civic.office
        WHERE office_level = 'federal'
          AND state IS NULL
          AND name = 'us_house'
          AND electoral_division_id IS NULL
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        return row[0]

    insert_office_row(
        conn,
        office_id=_OFFICE_ID,
        name="us_house",
        title="Representative",
        state=None,
        electoral_division_id=None,
    )
    return _OFFICE_ID


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed, poison, restore, or remove the person-resilience specimen.")
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--cleanup", action="store_true", help="Delete the specimen rows.")
    action_group.add_argument(
        "--poison",
        action="store_true",
        help="Write the response-contract-illegal NaN into the specimen candidate's official total.",
    )
    action_group.add_argument("--restore", action="store_true", help="Undo the poison.")
    arguments = parser.parse_args()

    with get_connection() as conn:
        with conn.transaction():
            if arguments.cleanup:
                cleanup_person_resilience_fixture(conn)
            elif arguments.poison:
                poison_person_resilience_candidate(conn)
            elif arguments.restore:
                restore_person_resilience_candidate(conn)
            else:
                seed_person_resilience_fixture(conn)

    if arguments.cleanup:
        print("cleaned up person resilience fixture")
    elif arguments.poison:
        print("poisoned person resilience candidate official total")
    elif arguments.restore:
        print("restored person resilience candidate official total")
    else:
        print(f"SMOKE_RESILIENCE_PERSON_ID={SMOKE_RESILIENCE_PERSON_ID}")


if __name__ == "__main__":
    main()
