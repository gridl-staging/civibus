
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import insert_person
from core.db_ingest import find_person_by_identifier, insert_entity_source, try_insert_source_record
from core.types.python.models import (
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.federal_officeholder_loader import OFFICE_US_PRESIDENT
from domains.campaign_finance.ingest.field_mapper import map_candidate_fields
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.civics.constants import congressional_boundary_year
from domains.civics.ingest import (
    derive_incumbent_challenge,
    upsert_candidacy,
    upsert_contest,
    upsert_electoral_division,
)
from domains.civics.types.models import Candidacy, Contest, ElectoralDivision

LOGGER = logging.getLogger(__name__)

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
_OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
_OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")
_DIVISION_US_STATEWIDE = UUID("00000000-0000-4000-8000-000000000501")
_DIVISION_US_CONGRESSIONAL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000504")

_FEC_OFFICE_MAP: dict[str, UUID] = {
    "H": _OFFICE_US_HOUSE,
    "S": _OFFICE_US_SENATE,
    "P": OFFICE_US_PRESIDENT,
}


def federal_general_election_date(year: int) -> date:
    """First Tuesday after the first Monday in November of the given year."""
    # November 1 of the year
    nov1 = date(year, 11, 1)
    # Day of week: Monday=0 ... Sunday=6
    dow = nov1.weekday()
    # First Monday: if Nov 1 is Monday (dow=0), first Monday = 1
    # Otherwise first Monday = 1 + (7 - dow) % 7
    first_monday = 1 + (7 - dow) % 7
    # First Tuesday after first Monday
    return date(year, 11, first_monday + 1)


def _resolve_electoral_division(
    conn: psycopg.Connection,
    office_code: str,
    state: str | None,
    district: str | None,
    *,
    election_year: int,
) -> UUID | None:
    """Resolve or create the electoral division for a FEC candidate row."""
    if office_code == "P":
        return _DIVISION_US_STATEWIDE

    if office_code == "S" and state:
        state_lower = state.lower()
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=state_lower,
                division_type="statewide",
                state=state,
                parent_id=_DIVISION_US_STATEWIDE,
            ),
        )

    if office_code == "H" and state and district:
        district_padded = district.zfill(2)
        state_lower = state.lower()
        name = f"{state_lower}_cd_{district_padded}"
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=name,
                division_type="congressional_district",
                state=state,
                district_number=district_padded,
                parent_id=_DIVISION_US_CONGRESSIONAL_DISTRICTS,
                boundary_year=congressional_boundary_year(election_year),
            ),
        )

    return None


def _try_insert_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    raw_fields: dict[str, object],
) -> UUID | None:
    sr = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    return try_insert_source_record(conn, sr)


class ValidatedRow:
    """Intermediate representation after field extraction and validation."""

    __slots__ = (
        "fec_candidate_id",
        "candidate_name",
        "office_id",
        "office_code",
        "election_year",
        "raw_row",
        "mapped",
    )

    def __init__(
        self,
        *,
        fec_candidate_id: str,
        candidate_name: str,
        office_id: UUID,
        office_code: str,
        election_year: int,
        raw_row: dict[str, str | None],
        mapped: dict[str, object],
    ) -> None:
        self.fec_candidate_id = fec_candidate_id
        self.candidate_name = candidate_name
        self.office_id = office_id
        self.office_code = office_code
        self.election_year = election_year
        self.raw_row = raw_row
        self.mapped = mapped


def validate_candidate_row(raw_row: dict[str, str | None]) -> ValidatedRow | None:
    """Extract and validate required fields from a raw FEC candidate row.

    Returns a ValidatedRow on success, or None if the row should be skipped.
    Shared by the canonical loader and the federal races loader so both apply
    identical office resolution and election-year validation.
    """
    mapped = map_candidate_fields(raw_row)

    fec_candidate_id = normalize_optional_text(mapped.get("fec_candidate_id"))
    candidate_name = normalize_optional_text(mapped.get("name"))
    office_code = normalize_optional_text(mapped.get("office"))

    if fec_candidate_id is None or candidate_name is None or office_code is None:
        LOGGER.warning("Skipping row with missing required fields: %s", raw_row)
        return None

    office_id = _FEC_OFFICE_MAP.get(office_code)
    if office_id is None:
        LOGGER.warning("Unknown CAND_OFFICE code %r for %s", office_code, fec_candidate_id)
        return None

    election_year_raw = normalize_optional_text(raw_row.get("CAND_ELECTION_YR"))
    if election_year_raw is None:
        LOGGER.warning("Missing CAND_ELECTION_YR for %s", fec_candidate_id)
        return None

    try:
        election_year = int(election_year_raw)
    except ValueError:
        LOGGER.warning("Invalid CAND_ELECTION_YR %r for %s", election_year_raw, fec_candidate_id)
        return None

    return ValidatedRow(
        fec_candidate_id=fec_candidate_id,
        candidate_name=candidate_name,
        office_id=office_id,
        office_code=office_code,
        election_year=election_year,
        raw_row=raw_row,
        mapped=mapped,
    )


def resolve_candidate_person(conn: psycopg.Connection, row: ValidatedRow) -> UUID:
    """Reuse the canonical person for a FEC candidate id, creating one when absent."""
    person_id = find_person_by_identifier(conn, "fec_candidate_id", row.fec_candidate_id)
    if person_id is None:
        person_id = insert_person(
            conn,
            Person(
                canonical_name=row.candidate_name,
                identifiers={"fec_candidate_id": row.fec_candidate_id},
            ),
        )
    return person_id


def resolve_candidate_division(conn: psycopg.Connection, row: ValidatedRow) -> UUID | None:
    """Resolve the electoral division for a validated FEC candidate row."""
    state = normalize_optional_text(row.mapped.get("state"))
    district = normalize_optional_text(row.mapped.get("district"))
    return _resolve_electoral_division(conn, row.office_code, state, district, election_year=row.election_year)


def federal_contest_name(row: ValidatedRow) -> str:
    """Deterministic contest name shared by every FEC candidate-to-civic loader."""
    state = normalize_optional_text(row.mapped.get("state"))
    return f"{row.office_code} {state or 'US'} General {row.election_year}"


def resolve_candidate_incumbent_challenge(
    conn: psycopg.Connection,
    row: ValidatedRow,
    *,
    person_id: UUID,
    division_id: UUID | None,
    as_of: date,
) -> str | None:
    """Resolve FEC incumbent/challenger code, deriving only when House data is precise."""
    incumbent_challenge = normalize_optional_text(row.mapped.get("incumbent_challenge"))
    if incumbent_challenge is None and row.office_code == "H":
        # FEC candidate master does not expose a Senate seat/class discriminator,
        # so only House rows are precise enough for derived fallback.
        incumbent_challenge = derive_incumbent_challenge(
            conn,
            person_id,
            row.office_id,
            division_id,
            as_of=as_of,
        )
    return incumbent_challenge


def ingest_candidate_civic_rows(
    conn: psycopg.Connection,
    row: ValidatedRow,
    source_record_id: UUID,
    *,
    election_id: UUID | None = None,
    election_date: date | None = None,
    candidacy_status: str | None = None,
) -> UUID:
    """Ingest one validated FEC candidate row into person/division/contest/candidacy.

    Single owner for the FEC candidate-to-civic mapping. The canonical loader
    calls it with defaults; the federal races loader supplies ``election_id``
    (to link the contest to the newly-populated ``civic.election`` row) and
    ``candidacy_status`` (from the Stage 1 ``candidate_status`` mapper output).
    Returns the upserted contest id.
    """
    person_id = resolve_candidate_person(conn, row)
    insert_entity_source(conn, "person", person_id, source_record_id, "candidate")

    division_id = resolve_candidate_division(conn, row)
    resolved_election_date = (
        election_date if election_date is not None else federal_general_election_date(row.election_year)
    )
    contest_id = upsert_contest(
        conn,
        Contest(
            name=federal_contest_name(row),
            election_date=resolved_election_date,
            election_type="general",
            office_id=row.office_id,
            election_id=election_id,
            electoral_division_id=division_id,
            source_record_id=source_record_id,
        ),
    )

    party = normalize_optional_text(row.mapped.get("party"))
    incumbent_challenge = resolve_candidate_incumbent_challenge(
        conn,
        row,
        person_id=person_id,
        division_id=division_id,
        as_of=resolved_election_date,
    )
    upsert_candidacy(
        conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            party=party,
            status=candidacy_status,
            incumbent_challenge=incumbent_challenge,
            # fec_candidate_id as candidate_number is a copied source fact for display only
            candidate_number=row.fec_candidate_id,
            source_record_id=source_record_id,
        ),
    )
    return contest_id


def load_fec_candidates_canonical(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    """Load FEC candidate-master rows into canonical civic.* tables.

    Each row is mapped to: person -> office -> electoral_division -> contest -> candidacy.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    cycle_key = str(cycle)
    result = LoadResult()
    processed_since_commit = 0

    for raw_row in read_bulk_file(path, "cn", limit=limit):
        validated = validate_candidate_row(raw_row)
        if validated is None:
            result.errors += 1
            continue

        source_record_key = f"cn_canonical:{cycle_key}:{validated.fec_candidate_id}:{validated.election_year}"
        source_record_id = _try_insert_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_fields=dict(raw_row),
        )
        if source_record_id is None:
            result.skipped += 1
            continue

        ingest_candidate_civic_rows(conn, validated, source_record_id)

        result.inserted += 1
        processed_since_commit += 1
        if processed_since_commit >= batch_size:
            conn.commit()
            processed_since_commit = 0

    if processed_since_commit > 0:
        conn.commit()

    return result
