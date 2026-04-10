
from __future__ import annotations

from datetime import date
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg.types.range import DateRange

from core.db_ingest import insert_entity_source
from domains.civics.types.models import Candidacy, Contest, ElectoralDivision, Office, Officeholding

_UNSET_ELECTORAL_DIVISION = object()


def _find_existing_officeholding_id(
    cur: psycopg.Cursor[object],
    *,
    person_id: UUID,
    office_id: UUID,
    valid_period: DateRange,
) -> UUID | None:
    """Look up the canonical officeholding row for one temporal natural key."""
    cur.execute(
        """
        SELECT id
        FROM civic.officeholding
        WHERE person_id = %s
          AND office_id = %s
          AND valid_period IS NOT DISTINCT FROM %s
        LIMIT 1
        """,
        (person_id, office_id, valid_period),
    )
    row = cur.fetchone()
    return None if row is None else row[0]


def _update_existing_officeholding(
    cur: psycopg.Cursor[object],
    *,
    officeholding_id: UUID,
    officeholding: Officeholding,
) -> UUID:
    """Update mutable officeholding fields on an already-matched row."""
    cur.execute(
        """
        UPDATE civic.officeholding
        SET electoral_division_id = COALESCE(%s, electoral_division_id),
            holder_status = %s,
            date_precision = %s,
            source_record_id = COALESCE(%s, source_record_id),
            updated_at = NOW()
        WHERE id = %s
        RETURNING id
        """,
        (
            officeholding.electoral_division_id,
            officeholding.holder_status,
            officeholding.date_precision,
            officeholding.source_record_id,
            officeholding_id,
        ),
    )
    return cur.fetchone()[0]


def retire_officeholdings_for_vacancy(
    conn: psycopg.Connection,
    office_id: UUID,
    electoral_division_id: UUID | None,
    vacancy_source_filters: dict[str, str] | None = None,
) -> int:
    """Set active officeholdings to 'former' when a vacancy is reported for a seat.

    Matches active officeholdings for the given office + division and, when
    provided, narrows to rows whose linked source_record.raw_fields contains all
    key/value pairs from ``vacancy_source_filters``. This keeps vacancy retirements
    seat-specific for multi-seat offices that share one office/division.
    """
    query = """
        UPDATE civic.officeholding AS oh
        SET holder_status = 'former',
            updated_at = NOW()
        WHERE oh.office_id = %s
          AND oh.electoral_division_id IS NOT DISTINCT FROM %s
          AND oh.holder_status IN ('elected', 'appointed', 'acting')
    """
    params: list[object] = [office_id, electoral_division_id]
    if vacancy_source_filters:
        query += """
          AND EXISTS (
              SELECT 1
              FROM core.source_record AS sr
              WHERE sr.id = oh.source_record_id
                AND sr.raw_fields @> %s::jsonb
          )
        """
        params.append(Jsonb(vacancy_source_filters))

    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.rowcount


def upsert_office(conn: psycopg.Connection, office: Office) -> UUID:
    """Upsert an office row keyed by (office_level, COALESCE(state,''), name)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.office (
                id, name, office_level, title, jurisdiction_id, state,
                is_elected, number_of_seats, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (office_level, COALESCE(state, ''), name)
            DO UPDATE SET
                title = EXCLUDED.title,
                jurisdiction_id = EXCLUDED.jurisdiction_id,
                is_elected = EXCLUDED.is_elected,
                number_of_seats = EXCLUDED.number_of_seats,
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.office.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                office.id,
                office.name,
                office.office_level,
                office.title,
                office.jurisdiction_id,
                office.state,
                office.is_elected,
                office.number_of_seats,
                office.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if office.source_record_id is not None:
        insert_entity_source(conn, "office", row_id, office.source_record_id, "office")

    return row_id


def upsert_electoral_division(conn: psycopg.Connection, division: ElectoralDivision) -> UUID:
    """Upsert an electoral division keyed by (division_type, COALESCE(state,''), name, COALESCE(boundary_year,0))."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.electoral_division (
                id, name, division_type, state, district_number, ocd_id,
                is_container, parent_id, boundary_year, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (division_type, COALESCE(state, ''), name, COALESCE(boundary_year, 0))
            DO UPDATE SET
                district_number = COALESCE(EXCLUDED.district_number, civic.electoral_division.district_number),
                ocd_id = COALESCE(EXCLUDED.ocd_id, civic.electoral_division.ocd_id),
                is_container = EXCLUDED.is_container,
                parent_id = COALESCE(EXCLUDED.parent_id, civic.electoral_division.parent_id),
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.electoral_division.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                division.id,
                division.name,
                division.division_type,
                division.state,
                division.district_number,
                division.ocd_id,
                division.is_container,
                division.parent_id,
                division.boundary_year,
                division.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if division.source_record_id is not None:
        insert_entity_source(conn, "electoral_division", row_id, division.source_record_id, "electoral_division")

    return row_id


def upsert_contest(conn: psycopg.Connection, contest: Contest) -> UUID:
    """Upsert a contest keyed by (office_id, COALESCE(electoral_division_id, NULL_UUID), COALESCE(election_date, 0001-01-01), election_type)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.contest (
                id, name, election_date, election_type, office_id,
                electoral_division_id, number_of_seats, filing_deadline,
                is_partisan, candidate_list_incomplete, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                office_id,
                COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(election_date, '0001-01-01'::date),
                election_type
            )
            DO UPDATE SET
                name = EXCLUDED.name,
                number_of_seats = EXCLUDED.number_of_seats,
                filing_deadline = COALESCE(EXCLUDED.filing_deadline, civic.contest.filing_deadline),
                is_partisan = EXCLUDED.is_partisan,
                candidate_list_incomplete = EXCLUDED.candidate_list_incomplete,
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.contest.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                contest.id,
                contest.name,
                contest.election_date,
                contest.election_type,
                contest.office_id,
                contest.electoral_division_id,
                contest.number_of_seats,
                contest.filing_deadline,
                contest.is_partisan,
                contest.candidate_list_incomplete,
                contest.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if contest.source_record_id is not None:
        insert_entity_source(conn, "contest", row_id, contest.source_record_id, "contest")

    return row_id


def upsert_candidacy(conn: psycopg.Connection, candidacy: Candidacy) -> UUID:
    """Upsert a candidacy keyed by (person_id, contest_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.candidacy (
                id, person_id, contest_id, party, filing_date, status,
                incumbent_challenge, candidate_number, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (person_id, contest_id)
            DO UPDATE SET
                party = COALESCE(EXCLUDED.party, civic.candidacy.party),
                filing_date = COALESCE(EXCLUDED.filing_date, civic.candidacy.filing_date),
                status = COALESCE(EXCLUDED.status, civic.candidacy.status),
                incumbent_challenge = COALESCE(EXCLUDED.incumbent_challenge, civic.candidacy.incumbent_challenge),
                candidate_number = COALESCE(EXCLUDED.candidate_number, civic.candidacy.candidate_number),
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.candidacy.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                candidacy.id,
                candidacy.person_id,
                candidacy.contest_id,
                candidacy.party,
                candidacy.filing_date,
                candidacy.status,
                candidacy.incumbent_challenge,
                candidacy.candidate_number,
                candidacy.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if candidacy.source_record_id is not None:
        insert_entity_source(conn, "candidacy", row_id, candidacy.source_record_id, "candidacy")

    return row_id


def upsert_officeholding(conn: psycopg.Connection, officeholding: Officeholding) -> UUID:
    valid_period = DateRange(officeholding.valid_period.start_date, officeholding.valid_period.end_date)

    with conn.cursor() as cur:
        existing_id = _find_existing_officeholding_id(
            cur,
            person_id=officeholding.person_id,
            office_id=officeholding.office_id,
            valid_period=valid_period,
        )
        if existing_id is not None:
            row_id = _update_existing_officeholding(
                cur,
                officeholding_id=existing_id,
                officeholding=officeholding,
            )
        else:
            try:
                with conn.transaction():
                    cur.execute(
                        """
                        INSERT INTO civic.officeholding (
                            id, person_id, office_id, electoral_division_id,
                            holder_status, valid_period, date_precision, source_record_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            officeholding.id,
                            officeholding.person_id,
                            officeholding.office_id,
                            officeholding.electoral_division_id,
                            officeholding.holder_status,
                            valid_period,
                            officeholding.date_precision,
                            officeholding.source_record_id,
                        ),
                    )
                    row_id = cur.fetchone()[0]
            except (psycopg.errors.ExclusionViolation, psycopg.errors.UniqueViolation):
                # Temporal uniqueness for officeholding is enforced by WITHOUT OVERLAPS,
                # so exclusion conflicts are expected under races and retried as lookups.
                existing_id = _find_existing_officeholding_id(
                    cur,
                    person_id=officeholding.person_id,
                    office_id=officeholding.office_id,
                    valid_period=valid_period,
                )
                if existing_id is None:
                    raise
                row_id = _update_existing_officeholding(
                    cur,
                    officeholding_id=existing_id,
                    officeholding=officeholding,
                )

    if officeholding.source_record_id is not None:
        insert_entity_source(conn, "officeholding", row_id, officeholding.source_record_id, "officeholding")

    return row_id


def derive_incumbent_challenge(
    conn: psycopg.Connection,
    person_id: UUID,
    office_id: UUID,
    electoral_division_id: UUID | None | object = _UNSET_ELECTORAL_DIVISION,
    *,
    as_of: date | None = None,
) -> str | None:
    """Derive FEC-style incumbent/challenger code from canonical officeholding.

    Returns "I" if person_id currently holds the requested office as of `as_of`,
    None otherwise. When callers pass an electoral_division_id, the match is
    seat-specific (office_id + electoral_division_id) so district-scoped races
    do not leak incumbency across seats. Callers that omit the division filter
    keep the older office-level behavior used by officeholder-focused tests.
    Does NOT persist anything; callers decide whether to store the result.

    When `as_of` is None, defaults to today.
    """
    check_date = as_of or date.today()
    query = """
        SELECT 1
        FROM civic.officeholding
        WHERE person_id = %s
          AND office_id = %s
          AND holder_status IN ('elected', 'appointed', 'acting')
          AND (
              valid_period IS NULL
              OR valid_period @> %s::date
          )
    """
    params: list[object] = [person_id, office_id, check_date]
    if electoral_division_id is not _UNSET_ELECTORAL_DIVISION:
        query += "\n          AND electoral_division_id IS NOT DISTINCT FROM %s"
        params.append(electoral_division_id)
    query += "\n        LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(query, params)
        if cur.fetchone() is not None:
            return "I"
    return None
