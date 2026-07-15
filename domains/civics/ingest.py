
from __future__ import annotations

import json
from datetime import date
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg.types.range import DateRange

from core.db_ingest import insert_entity_source
from domains.civics.types.models import (
    Candidacy,
    Contest,
    Election,
    ElectoralDivision,
    FilingDeadline,
    Office,
    OfficeRosterLink,
    Officeholding,
    ReportingPeriod,
)

_UNSET_ELECTORAL_DIVISION = object()
_ELECTORAL_DIVISION_HAS_GEOMETRY: bool | None = None
_OFFICE_HAS_ELECTORAL_DIVISION_COLUMN: bool | None = None
_FEDERAL_HOUSE_OFFICE_ID = UUID("00000000-0000-4000-8000-000000000101")


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


def supersede_officeholdings_for_successor(
    conn: psycopg.Connection,
    *,
    office_id: UUID,
    electoral_division_id: UUID | None,
    successor_person_id: UUID,
    successor_start_date: date,
) -> int:
    """Close active same-seat officeholdings when a successor starts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE civic.officeholding AS oh
            SET holder_status = 'former',
                valid_period = daterange(lower(oh.valid_period), %s, '[)'),
                updated_at = NOW()
            WHERE oh.office_id = %s
              AND oh.electoral_division_id IS NOT DISTINCT FROM %s
              AND oh.person_id <> %s
              AND oh.holder_status IN ('elected', 'appointed', 'acting')
              AND oh.valid_period @> %s::date
              AND (lower_inf(oh.valid_period) OR lower(oh.valid_period) < %s::date)
            """,
            (
                successor_start_date,
                office_id,
                electoral_division_id,
                successor_person_id,
                successor_start_date,
                successor_start_date,
            ),
        )
        return cur.rowcount


def upsert_office(conn: psycopg.Connection, office: Office) -> UUID:
    """Upsert an office row keyed by the canonical office natural key."""
    office_has_electoral_division_column = _office_has_electoral_division_column(conn)
    if office_has_electoral_division_column and office.electoral_division_id is not None:
        with conn.cursor() as cur:
            # Preserve legacy office identity rows that were inserted before division ids were known.
            cur.execute(
                """
                UPDATE civic.office
                SET
                    title = %s,
                    jurisdiction_id = %s,
                    is_elected = %s,
                    number_of_seats = %s,
                    source_record_id = COALESCE(%s, civic.office.source_record_id),
                    electoral_division_id = %s,
                    updated_at = NOW()
                WHERE office_level = %s
                  AND COALESCE(state, '') = COALESCE(%s, '')
                  AND name = %s
                  AND electoral_division_id IS NULL
                RETURNING civic.office.id
                """,
                (
                    office.title,
                    office.jurisdiction_id,
                    office.is_elected,
                    office.number_of_seats,
                    office.source_record_id,
                    office.electoral_division_id,
                    office.office_level,
                    office.state,
                    office.name,
                ),
            )
            promoted_row = cur.fetchone()
            if promoted_row is not None:
                row_id: UUID = promoted_row[0]
                if office.source_record_id is not None:
                    insert_entity_source(conn, "office", row_id, office.source_record_id, "office")
                return row_id

    with conn.cursor() as cur:
        if office_has_electoral_division_column:
            cur.execute(
                """
                INSERT INTO civic.office (
                    id, name, office_level, title, jurisdiction_id, state,
                    electoral_division_id, is_elected, number_of_seats, source_record_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    office_level,
                    COALESCE(state, ''),
                    name,
                    COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid)
                )
                DO UPDATE SET
                    title = EXCLUDED.title,
                    jurisdiction_id = EXCLUDED.jurisdiction_id,
                    is_elected = EXCLUDED.is_elected,
                    number_of_seats = EXCLUDED.number_of_seats,
                    electoral_division_id = COALESCE(EXCLUDED.electoral_division_id, civic.office.electoral_division_id),
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
                    office.electoral_division_id,
                    office.is_elected,
                    office.number_of_seats,
                    office.source_record_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO civic.office (
                    id, name, office_level, title, jurisdiction_id, state,
                    is_elected, number_of_seats, source_record_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    office_level,
                    COALESCE(state, ''),
                    name
                )
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
    global _ELECTORAL_DIVISION_HAS_GEOMETRY
    if _ELECTORAL_DIVISION_HAS_GEOMETRY is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'civic'
                      AND table_name = 'electoral_division'
                      AND column_name = 'geometry'
                )
                """
            )
            _ELECTORAL_DIVISION_HAS_GEOMETRY = bool(cur.fetchone()[0])

    geometry_geojson = json.dumps(division.geometry) if division.geometry is not None else None
    with conn.cursor() as cur:
        if _ELECTORAL_DIVISION_HAS_GEOMETRY:
            cur.execute(
                """
                INSERT INTO civic.electoral_division (
                    id, name, division_type, state, district_number, ocd_id,
                    is_container, parent_id, boundary_year, geometry, source_record_id
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s::json), 4326)),
                    %s
                )
                ON CONFLICT (division_type, COALESCE(state, ''), name, COALESCE(boundary_year, 0))
                DO UPDATE SET
                    district_number = COALESCE(EXCLUDED.district_number, civic.electoral_division.district_number),
                    ocd_id = COALESCE(EXCLUDED.ocd_id, civic.electoral_division.ocd_id),
                    is_container = EXCLUDED.is_container,
                    parent_id = COALESCE(EXCLUDED.parent_id, civic.electoral_division.parent_id),
                    geometry = COALESCE(EXCLUDED.geometry, civic.electoral_division.geometry),
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
                    geometry_geojson,
                    division.source_record_id,
                ),
            )
        else:
            # Some stage bootstrap snapshots predate the geometry column migration.
            # Keep the canonical upsert owner usable in both schema states.
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


def _office_has_electoral_division_column(conn: psycopg.Connection) -> bool:
    global _OFFICE_HAS_ELECTORAL_DIVISION_COLUMN
    if _OFFICE_HAS_ELECTORAL_DIVISION_COLUMN is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'civic'
                      AND table_name = 'office'
                      AND column_name = 'electoral_division_id'
                )
                """
            )
            _OFFICE_HAS_ELECTORAL_DIVISION_COLUMN = bool(cur.fetchone()[0])
    return _OFFICE_HAS_ELECTORAL_DIVISION_COLUMN


def upsert_contest(conn: psycopg.Connection, contest: Contest) -> UUID:
    """Upsert a contest keyed by (office_id, COALESCE(electoral_division_id, NULL_UUID), COALESCE(election_date, 0001-01-01), election_type)."""
    if contest.electoral_division_id is not None:
        with conn.cursor() as cur:
            # Promote legacy contest rows created before division ids were populated.
            cur.execute(
                """
                UPDATE civic.contest AS legacy
                SET
                    name = %s,
                    election_id = COALESCE(%s, legacy.election_id),
                    electoral_division_id = %s,
                    number_of_seats = %s,
                    filing_deadline = COALESCE(%s, legacy.filing_deadline),
                    is_partisan = %s,
                    candidate_list_incomplete = %s,
                    source_record_id = COALESCE(%s, legacy.source_record_id),
                    updated_at = NOW()
                WHERE legacy.office_id = %s
                  AND legacy.election_date IS NOT DISTINCT FROM %s
                  AND legacy.election_type = %s
                  AND legacy.electoral_division_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM civic.contest AS existing
                      WHERE existing.office_id = legacy.office_id
                        AND existing.election_date IS NOT DISTINCT FROM legacy.election_date
                        AND existing.election_type = legacy.election_type
                        AND existing.electoral_division_id = %s
                  )
                RETURNING id
                """,
                (
                    contest.name,
                    contest.election_id,
                    contest.electoral_division_id,
                    contest.number_of_seats,
                    contest.filing_deadline,
                    contest.is_partisan,
                    contest.candidate_list_incomplete,
                    contest.source_record_id,
                    contest.office_id,
                    contest.election_date,
                    contest.election_type,
                    contest.electoral_division_id,
                ),
            )
            promoted_row = cur.fetchone()
            if promoted_row is not None:
                row_id: UUID = promoted_row[0]
                if contest.source_record_id is not None:
                    insert_entity_source(conn, "contest", row_id, contest.source_record_id, "contest")
                return row_id

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.contest (
                id, name, election_date, election_type, office_id,
                election_id, electoral_division_id, number_of_seats, filing_deadline,
                is_partisan, candidate_list_incomplete, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                office_id,
                COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(election_date, '0001-01-01'::date),
                election_type
            )
            DO UPDATE SET
                name = EXCLUDED.name,
                election_id = COALESCE(EXCLUDED.election_id, civic.contest.election_id),
                electoral_division_id = COALESCE(EXCLUDED.electoral_division_id, civic.contest.electoral_division_id),
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
                contest.election_id,
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


def upsert_election(conn: psycopg.Connection, election: Election) -> UUID:
    """Upsert an election keyed by uq_election_natural_key index columns."""
    if election.electoral_division_id is not None:
        with conn.cursor() as cur:
            # Promote legacy election rows created before district linkage was available.
            cur.execute(
                """
                UPDATE civic.election
                SET
                    office_id = COALESCE(%s, civic.election.office_id),
                    electoral_division_id = %s,
                    source_record_id = COALESCE(%s, civic.election.source_record_id),
                    updated_at = NOW()
                WHERE jurisdiction_scope = %s
                  AND COALESCE(state, '') = COALESCE(%s, '')
                  AND election_date = %s
                  AND election_type = %s
                  AND is_special = %s
                  AND COALESCE(office_id, '00000000-0000-0000-0000-000000000000'::uuid) = COALESCE(%s, '00000000-0000-0000-0000-000000000000'::uuid)
                  AND electoral_division_id IS NULL
                RETURNING id
                """,
                (
                    election.office_id,
                    election.electoral_division_id,
                    election.source_record_id,
                    election.jurisdiction_scope,
                    election.state,
                    election.election_date,
                    election.election_type,
                    election.is_special,
                    election.office_id,
                ),
            )
            promoted_row = cur.fetchone()
            if promoted_row is not None:
                row_id: UUID = promoted_row[0]
                if election.source_record_id is not None:
                    insert_entity_source(conn, "election", row_id, election.source_record_id, "election")
                return row_id

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.election (
                id, jurisdiction_scope, state, county, municipality,
                election_date, election_type, is_special, office_id,
                electoral_division_id, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                jurisdiction_scope,
                COALESCE(state, ''),
                COALESCE(county, ''),
                COALESCE(municipality, ''),
                election_date,
                election_type,
                is_special,
                COALESCE(office_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid)
            )
            DO UPDATE SET
                state = COALESCE(EXCLUDED.state, civic.election.state),
                county = COALESCE(EXCLUDED.county, civic.election.county),
                municipality = COALESCE(EXCLUDED.municipality, civic.election.municipality),
                office_id = COALESCE(EXCLUDED.office_id, civic.election.office_id),
                electoral_division_id = COALESCE(EXCLUDED.electoral_division_id, civic.election.electoral_division_id),
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.election.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                election.id,
                election.jurisdiction_scope,
                election.state,
                election.county,
                election.municipality,
                election.election_date,
                election.election_type,
                election.is_special,
                election.office_id,
                election.electoral_division_id,
                election.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if election.source_record_id is not None:
        insert_entity_source(conn, "election", row_id, election.source_record_id, "election")

    return row_id


def upsert_filing_deadline(conn: psycopg.Connection, filing_deadline: FilingDeadline) -> UUID:
    """Upsert a filing deadline keyed by uq_filing_deadline_natural_key index columns."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.filing_deadline (
                id, election_id, office_id, electoral_division_id,
                jurisdiction_scope, state, county, municipality,
                deadline_date, deadline_kind, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                election_id,
                office_id,
                COALESCE(electoral_division_id, '00000000-0000-0000-0000-000000000000'::uuid),
                deadline_kind
            )
            DO UPDATE SET
                jurisdiction_scope = EXCLUDED.jurisdiction_scope,
                state = COALESCE(EXCLUDED.state, civic.filing_deadline.state),
                county = COALESCE(EXCLUDED.county, civic.filing_deadline.county),
                municipality = COALESCE(EXCLUDED.municipality, civic.filing_deadline.municipality),
                deadline_date = EXCLUDED.deadline_date,
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.filing_deadline.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                filing_deadline.id,
                filing_deadline.election_id,
                filing_deadline.office_id,
                filing_deadline.electoral_division_id,
                filing_deadline.jurisdiction_scope,
                filing_deadline.state,
                filing_deadline.county,
                filing_deadline.municipality,
                filing_deadline.deadline_date,
                filing_deadline.deadline_kind,
                filing_deadline.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if filing_deadline.source_record_id is not None:
        insert_entity_source(conn, "filing_deadline", row_id, filing_deadline.source_record_id, "filing_deadline")

    return row_id


def upsert_reporting_period(conn: psycopg.Connection, reporting_period: ReportingPeriod) -> UUID:
    """Upsert a reporting period keyed by uq_reporting_period_natural_key index columns."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.reporting_period (
                id, election_id, period_name, period_start, period_end,
                report_due_date, is_pre_election, is_post_election,
                disclosure_kind, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (election_id, period_name)
            DO UPDATE SET
                period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                report_due_date = EXCLUDED.report_due_date,
                is_pre_election = EXCLUDED.is_pre_election,
                is_post_election = EXCLUDED.is_post_election,
                disclosure_kind = COALESCE(EXCLUDED.disclosure_kind, civic.reporting_period.disclosure_kind),
                source_record_id = COALESCE(EXCLUDED.source_record_id, civic.reporting_period.source_record_id),
                updated_at = NOW()
            RETURNING id
            """,
            (
                reporting_period.id,
                reporting_period.election_id,
                reporting_period.period_name,
                reporting_period.period_start,
                reporting_period.period_end,
                reporting_period.report_due_date,
                reporting_period.is_pre_election,
                reporting_period.is_post_election,
                reporting_period.disclosure_kind,
                reporting_period.source_record_id,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if reporting_period.source_record_id is not None:
        insert_entity_source(conn, "reporting_period", row_id, reporting_period.source_record_id, "reporting_period")

    return row_id


def upsert_candidacy(conn: psycopg.Connection, candidacy: Candidacy) -> UUID:
    """Upsert a candidacy keyed by (person_id, contest_id)."""
    should_update_is_unexpired_term = "is_unexpired_term" in candidacy.model_fields_set
    should_update_raw_fields = "raw_fields" in candidacy.model_fields_set

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.candidacy (
                id, person_id, contest_id, party, name_on_ballot,
                is_unexpired_term, raw_fields, committee_id,
                filing_date, status, incumbent_challenge, candidate_number, source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (person_id, contest_id)
            DO UPDATE SET
                party = COALESCE(EXCLUDED.party, civic.candidacy.party),
                name_on_ballot = COALESCE(EXCLUDED.name_on_ballot, civic.candidacy.name_on_ballot),
                is_unexpired_term = CASE WHEN %s THEN EXCLUDED.is_unexpired_term ELSE civic.candidacy.is_unexpired_term END,
                raw_fields = CASE WHEN %s THEN EXCLUDED.raw_fields ELSE civic.candidacy.raw_fields END,
                committee_id = COALESCE(EXCLUDED.committee_id, civic.candidacy.committee_id),
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
                candidacy.name_on_ballot,
                candidacy.is_unexpired_term,
                Jsonb(candidacy.raw_fields),
                candidacy.committee_id,
                candidacy.filing_date,
                candidacy.status,
                candidacy.incumbent_challenge,
                candidacy.candidate_number,
                candidacy.source_record_id,
                should_update_is_unexpired_term,
                should_update_raw_fields,
            ),
        )
        row_id: UUID = cur.fetchone()[0]

    if candidacy.source_record_id is not None:
        insert_entity_source(conn, "candidacy", row_id, candidacy.source_record_id, "candidacy")

    return row_id


def repoint_candidacy_person(
    conn: psycopg.Connection,
    *,
    candidacy_id: UUID,
    expected_person_id: UUID,
    target_person_id: UUID,
) -> bool:
    """Move one candidacy row to a canonical person with conflict-safe merge semantics.

    When the target person already has a candidacy in the same contest, we merge
    the source row into the canonical target row and copy the source provenance
    links before deleting the now-redundant source row.
    """
    if expected_person_id == target_person_id:
        return False

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT contest_id
            FROM civic.candidacy
            WHERE id = %s
              AND person_id = %s
            """,
            (candidacy_id, expected_person_id),
        )
        source_row = cur.fetchone()
        if source_row is None:
            return False
        contest_id = source_row[0]

        cur.execute(
            """
            SELECT id
            FROM civic.candidacy
            WHERE person_id = %s
              AND contest_id = %s
            LIMIT 1
            """,
            (target_person_id, contest_id),
        )
        existing_target_row = cur.fetchone()

        if existing_target_row is not None:
            target_candidacy_id = existing_target_row[0]
            cur.execute(
                """
                UPDATE civic.candidacy AS target
                SET
                    party = COALESCE(target.party, source.party),
                    name_on_ballot = COALESCE(target.name_on_ballot, source.name_on_ballot),
                    is_unexpired_term = COALESCE(target.is_unexpired_term, source.is_unexpired_term),
                    raw_fields = COALESCE(target.raw_fields, source.raw_fields),
                    committee_id = COALESCE(target.committee_id, source.committee_id),
                    filing_date = COALESCE(target.filing_date, source.filing_date),
                    status = COALESCE(target.status, source.status),
                    incumbent_challenge = COALESCE(target.incumbent_challenge, source.incumbent_challenge),
                    candidate_number = COALESCE(target.candidate_number, source.candidate_number),
                    source_record_id = COALESCE(target.source_record_id, source.source_record_id),
                    updated_at = NOW()
                FROM civic.candidacy AS source
                WHERE target.id = %s
                  AND source.id = %s
                """,
                (target_candidacy_id, candidacy_id),
            )
            # Preserve every source link that pointed at the redundant source row.
            cur.execute(
                """
                INSERT INTO core.entity_source (
                    entity_type,
                    entity_id,
                    source_record_id,
                    extraction_role,
                    confidence,
                    extracted_fields
                )
                SELECT
                    entity_type,
                    %s,
                    source_record_id,
                    extraction_role,
                    confidence,
                    extracted_fields
                FROM core.entity_source
                WHERE entity_type = 'candidacy'
                  AND entity_id = %s
                ON CONFLICT (entity_type, entity_id, source_record_id, extraction_role)
                DO NOTHING
                """,
                (target_candidacy_id, candidacy_id),
            )
            cur.execute(
                """
                DELETE FROM civic.candidacy
                WHERE id = %s
                """,
                (candidacy_id,),
            )
            return True

        cur.execute(
            """
            UPDATE civic.candidacy
            SET person_id = %s,
                updated_at = NOW()
            WHERE id = %s
              AND person_id = %s
            """,
            (target_person_id, candidacy_id, expected_person_id),
        )
        return cur.rowcount == 1


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


def upsert_office_roster_link(conn: psycopg.Connection, office_roster_link: OfficeRosterLink) -> UUID:
    """Upsert a bridge row keyed by (office_id, data_source_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic.office_roster_link (
                id, office_id, data_source_id
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (office_id, data_source_id)
            DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            (
                office_roster_link.id,
                office_roster_link.office_id,
                office_roster_link.data_source_id,
            ),
        )
        return cur.fetchone()[0]


def derive_incumbent_challenge(
    conn: psycopg.Connection,
    person_id: UUID,
    office_id: UUID,
    electoral_division_id: UUID | None | object = _UNSET_ELECTORAL_DIVISION,
    *,
    as_of: date | None = None,
) -> str | None:
    """Derive FEC-style incumbent/challenger code from canonical officeholding.

    Returns "I" if person_id holds the requested office as of `as_of`, None
    otherwise. Same-seat House successor rows are stored as bounded former rows
    and still count for pre-successor dates when the caller supplies the seat.
    Generic former rows do not derive incumbency.
    When callers pass an electoral_division_id, the match is seat-specific
    (office_id + electoral_division_id) so district-scoped races do not leak
    incumbency across seats. Callers that omit the division filter keep the older
    office-level behavior used by officeholder-focused tests. Does NOT persist
    anything; callers decide whether to store the result.

    When `as_of` is None, defaults to today.
    """
    check_date = as_of or date.today()
    include_bounded_house_former = (
        office_id == _FEDERAL_HOUSE_OFFICE_ID
        and electoral_division_id is not _UNSET_ELECTORAL_DIVISION
        and electoral_division_id is not None
    )
    holder_status_filter = "holder_status IN ('elected', 'appointed', 'acting')"
    if include_bounded_house_former:
        holder_status_filter = f"({holder_status_filter} OR (holder_status = 'former' AND NOT upper_inf(valid_period)))"

    query = f"""
        SELECT 1
        FROM civic.officeholding
        WHERE person_id = %s
          AND office_id = %s
          AND {holder_status_filter}
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
