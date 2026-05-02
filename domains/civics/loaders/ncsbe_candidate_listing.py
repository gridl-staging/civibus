
from __future__ import annotations

import csv
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.request import urlretrieve
from uuid import UUID

import psycopg

from core.db import (
    get_connection,
    resolve_person_by_name_and_zip,
    select_active_source_record_by_key,
    try_insert_data_source,
)
from core.db_ingest import try_insert_source_record
from core.types.python.models import DataSource, Person, SourceRecord, compute_record_hash, utc_now
from domains.civics.ingest import (
    upsert_candidacy,
    upsert_contest,
    upsert_electoral_division,
    upsert_office,
)
from domains.civics.types import Candidacy, Contest, ElectoralDivision, Office


_NCSBE_DATA_SOURCE_DOMAIN = "civics"
_NCSBE_DATA_SOURCE_JURISDICTION = "NC"
_NCSBE_DATA_SOURCE_NAME = "ncsbe_candidate_listing_2026"
_NCSBE_SOURCE_RECORD_KEY_PREFIX = "ncsbe_candidate_listing_2026"
_NCSBE_CANDIDATE_LISTING_SOURCE_URL = (
    "https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv"
)
_STUB_IDENTIFIERS = {"civic_candidacy_stub": "true"}


@dataclass(frozen=True)
class CandidateListingLoadSummary:
    """Deterministic write/skip counters emitted by one loader run."""

    rows_read: int
    rows_loaded: int
    rows_skipped_out_of_window: int
    offices_upserted: int
    electoral_divisions_upserted: int
    contests_upserted: int
    candidacies_upserted: int
    source_records_inserted: int
    source_records_reused: int


@dataclass(frozen=True)
class CandidateListingRow:
    """Normalized candidate row used by Stage 1 parser contract tests."""

    election_date: datetime.date
    county_name: str
    contest_name: str
    name_on_ballot: str
    candidate_display_name: str
    party_candidate: str
    has_primary: bool
    is_partisan: bool
    vote_for: int


@dataclass(frozen=True)
class CandidateListingParseSummary:
    """Deterministic counts and key maps emitted by one parser run."""

    row_count: int
    county_count: int
    contest_count: int
    rows_by_county: dict[str, int]
    rows_by_party_candidate: dict[str, int]


@dataclass(frozen=True)
class CandidateListingParseResult:
    """Parser output bundle containing header contract, rows, and summary."""

    header: list[str]
    rows: list[CandidateListingRow]
    summary: CandidateListingParseSummary

    def require_row(self, *, county_name: str, contest_name: str, name_on_ballot: str) -> CandidateListingRow:
        """Return one exact row or raise an explicit error for contract mismatches."""
        for row in self.rows:
            if (
                row.county_name == county_name
                and row.contest_name == contest_name
                and row.name_on_ballot == name_on_ballot
            ):
                return row
        raise ValueError(
            "Candidate listing fixture row not found for "
            f"county_name={county_name}, contest_name={contest_name}, name_on_ballot={name_on_ballot}"
        )


def _parse_bool(raw_value: str) -> bool:
    return raw_value.strip().upper() == "TRUE"


def _normalize_display_name(name_on_ballot: str) -> str:
    return " ".join(name_on_ballot.split())


def parse_ncsbe_candidate_listing(csv_path: Path) -> CandidateListingParseResult:
    """Parse a captured NCSBE candidate-listing CSV into normalized contract rows."""
    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"Candidate listing CSV missing header row: {csv_path}")

        header = list(reader.fieldnames)
        rows: list[CandidateListingRow] = []
        by_county: Counter[str] = Counter()
        by_party_candidate: Counter[str] = Counter()
        contests: set[str] = set()

        for source_row in reader:
            county_name = source_row["county_name"].strip()
            contest_name = source_row["contest_name"].strip()
            name_on_ballot = source_row["name_on_ballot"].strip()
            party_candidate = source_row["party_candidate"].strip()

            parsed_row = CandidateListingRow(
                election_date=datetime.strptime(source_row["election_dt"].strip(), "%m/%d/%Y").date(),
                county_name=county_name,
                contest_name=contest_name,
                name_on_ballot=name_on_ballot,
                candidate_display_name=_normalize_display_name(name_on_ballot),
                party_candidate=party_candidate,
                has_primary=_parse_bool(source_row["has_primary"]),
                is_partisan=_parse_bool(source_row["is_partisan"]),
                vote_for=int(source_row["vote_for"].strip()),
            )
            rows.append(parsed_row)
            by_county[county_name] += 1
            by_party_candidate[party_candidate] += 1
            contests.add(contest_name)

    return CandidateListingParseResult(
        header=header,
        rows=rows,
        summary=CandidateListingParseSummary(
            row_count=len(rows),
            county_count=len(by_county),
            contest_count=len(contests),
            rows_by_county=dict(sorted(by_county.items())),
            rows_by_party_candidate=dict(sorted(by_party_candidate.items())),
        ),
    )


def _normalize_raw_row(source_row: dict[str, str], *, header: list[str]) -> dict[str, str]:
    return {column_name: (source_row.get(column_name, "") or "").strip() for column_name in header}


def _non_empty_or_none(raw_value: str) -> str | None:
    cleaned = raw_value.strip()
    return cleaned if cleaned else None


def _parse_optional_mmddyyyy(raw_value: str) -> date | None:
    cleaned = raw_value.strip()
    if not cleaned:
        return None
    return datetime.strptime(cleaned, "%m/%d/%Y").date()


def _parse_optional_uuid(raw_value: str) -> UUID | None:
    cleaned = raw_value.strip()
    if not cleaned:
        return None
    try:
        return UUID(cleaned)
    except ValueError:
        return None


def _parse_committee_id(raw_fields: dict[str, str]) -> UUID | None:
    """Parse committee UUID only from explicit committee-id columns."""
    for field_name in ("committee_id", "committee_uuid", "candidate_committee_id"):
        if field_name in raw_fields:
            return _parse_optional_uuid(raw_fields[field_name])
    return None


def _in_five_year_window(election_date: date, *, today: date) -> bool:
    return election_date >= date(today.year - 4, 1, 1)


def _in_supported_window(
    election_date: date,
    *,
    today: date,
    year_from: int | None,
) -> bool:
    """Apply the standard 5-year window or an explicit year-from override."""
    if year_from is not None:
        return election_date >= date(year_from, 1, 1)
    return _in_five_year_window(election_date, today=today)


def _office_level_for_contest(contest_name: str) -> str:
    uppercase_name = contest_name.upper()
    if uppercase_name.startswith("US "):
        return "federal"
    if "BOARD OF EDUCATION" in uppercase_name or "SCHOOL" in uppercase_name:
        return "school_board"
    if (
        "COURT" in uppercase_name
        or "JUDGE" in uppercase_name
        or "DISTRICT ATTORNEY" in uppercase_name
    ):
        return "judicial"
    if "CITY OF" in uppercase_name or "TOWN OF" in uppercase_name or "COUNCIL" in uppercase_name:
        return "municipal"
    if "COUNTY" in uppercase_name:
        return "county"
    return "state"


def _candidacy_election_type(row: CandidateListingRow) -> str:
    return "primary" if row.has_primary else "general"


@dataclass(frozen=True)
class _DivisionScope:
    division_name: str
    division_type: str
    district_number: str | None = None


def _extract_trailing_district_number(contest_name: str) -> str | None:
    match = re.search(r"\bDISTRICT\s+(\d+)\b", contest_name.upper())
    if match is None:
        return None
    return str(int(match.group(1)))


def _derive_division_scope(parsed_row: CandidateListingRow) -> _DivisionScope:
    uppercase_name = parsed_row.contest_name.upper()
    county_name = parsed_row.county_name.upper()

    if uppercase_name.startswith("US HOUSE OF REPRESENTATIVES DISTRICT "):
        district_number = _extract_trailing_district_number(uppercase_name)
        if district_number is not None:
            return _DivisionScope(
                division_name=f"NC US HOUSE DISTRICT {district_number}",
                division_type="congressional_district",
                district_number=district_number,
            )

    if uppercase_name.startswith("NC SENATE DISTRICT ") or uppercase_name.startswith(
        "NC STATE SENATE DISTRICT "
    ):
        district_number = _extract_trailing_district_number(uppercase_name)
        if district_number is not None:
            return _DivisionScope(
                division_name=f"NC SENATE DISTRICT {district_number}",
                division_type="state_legislative_upper",
                district_number=district_number,
            )

    if uppercase_name.startswith("NC HOUSE OF REPRESENTATIVES DISTRICT "):
        district_number = _extract_trailing_district_number(uppercase_name)
        if district_number is not None:
            return _DivisionScope(
                division_name=f"NC HOUSE DISTRICT {district_number}",
                division_type="state_legislative_lower",
                district_number=district_number,
            )

    if "DISTRICT COURT JUDGE DISTRICT" in uppercase_name or "SUPERIOR COURT JUDGE DISTRICT" in uppercase_name:
        district_number = _extract_trailing_district_number(uppercase_name)
        if district_number is not None:
            return _DivisionScope(
                division_name=f"NC JUDICIAL DISTRICT {district_number}",
                division_type="judicial_district",
                district_number=district_number,
            )

    if (
        "CITY OF " in uppercase_name
        or "TOWN OF " in uppercase_name
        or "VILLAGE OF " in uppercase_name
    ):
        return _DivisionScope(division_name=f"NC {parsed_row.county_name}", division_type="municipal")

    if (
        county_name in uppercase_name
        or f"{county_name}-" in uppercase_name
        or " COUNTY " in uppercase_name
    ):
        return _DivisionScope(division_name=f"NC {parsed_row.county_name}", division_type="county")

    return _DivisionScope(division_name="NC", division_type="statewide")


def _lookup_existing_data_source_id(conn: psycopg.Connection) -> UUID:
    row = conn.execute(
        """
        SELECT id
        FROM core.data_source
        WHERE domain = %s
          AND jurisdiction = %s
          AND name = %s
        LIMIT 1
        """,
        (
            _NCSBE_DATA_SOURCE_DOMAIN,
            _NCSBE_DATA_SOURCE_JURISDICTION,
            _NCSBE_DATA_SOURCE_NAME,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("NCSBE data source upsert conflict occurred without an existing row")
    return row[0]


def _ensure_ncsbe_data_source(conn: psycopg.Connection, *, csv_path: Path) -> UUID:
    data_source = DataSource(
        domain=_NCSBE_DATA_SOURCE_DOMAIN,
        jurisdiction=_NCSBE_DATA_SOURCE_JURISDICTION,
        name=_NCSBE_DATA_SOURCE_NAME,
        source_url=_NCSBE_CANDIDATE_LISTING_SOURCE_URL,
        source_format="csv",
        update_frequency="weekly",
    )
    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id
    return _lookup_existing_data_source_id(conn)


def _resolve_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_url: str,
    raw_fields: dict[str, str],
    pull_date: datetime,
) -> tuple[UUID, bool]:
    record_hash = compute_record_hash(raw_fields)
    source_record_key = f"{_NCSBE_SOURCE_RECORD_KEY_PREFIX}:{record_hash}"
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=source_url,
        raw_fields=raw_fields,
        pull_date=pull_date,
        record_hash=record_hash,
    )
    inserted_source_record_id = try_insert_source_record(conn, source_record)
    if inserted_source_record_id is not None:
        return inserted_source_record_id, True

    active_source_record = select_active_source_record_by_key(
        conn,
        data_source_id=data_source_id,
        source_record_key=source_record_key,
    )
    if active_source_record is None:
        raise RuntimeError(
            "Expected active source_record after idempotent insert miss for "
            f"key={source_record_key}"
        )
    return active_source_record.id, False


def _office_exists(conn: psycopg.Connection, *, office_level: str, state: str, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM civic.office
        WHERE office_level = %s
          AND COALESCE(state, '') = %s
          AND name = %s
        LIMIT 1
        """,
        (office_level, state, name),
    ).fetchone()
    return row is not None


def _electoral_division_exists(
    conn: psycopg.Connection,
    *,
    division_type: str,
    state: str,
    name: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM civic.electoral_division
        WHERE division_type = %s
          AND COALESCE(state, '') = %s
          AND name = %s
          AND COALESCE(boundary_year, 0) = 0
        LIMIT 1
        """,
        (division_type, state, name),
    ).fetchone()
    return row is not None


def _contest_exists(
    conn: psycopg.Connection,
    *,
    office_id: UUID,
    electoral_division_id: UUID,
    election_date: date,
    election_type: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM civic.contest
        WHERE office_id = %s
          AND electoral_division_id IS NOT DISTINCT FROM %s
          AND election_date IS NOT DISTINCT FROM %s
          AND election_type = %s
        LIMIT 1
        """,
        (office_id, electoral_division_id, election_date, election_type),
    ).fetchone()
    return row is not None


def _candidacy_exists(conn: psycopg.Connection, *, person_id: UUID, contest_id: UUID) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM civic.candidacy
        WHERE person_id = %s
          AND contest_id = %s
        LIMIT 1
        """,
        (person_id, contest_id),
    ).fetchone()
    return row is not None


def _contest_id_for_canonical_key(
    conn: psycopg.Connection,
    *,
    office_id: UUID,
    electoral_division_id: UUID,
    election_date: date,
    election_type: str,
) -> UUID | None:
    row = conn.execute(
        """
        SELECT id
        FROM civic.contest
        WHERE office_id = %s
          AND electoral_division_id = %s
          AND election_date IS NOT DISTINCT FROM %s
          AND election_type = %s
        LIMIT 1
        """,
        (office_id, electoral_division_id, election_date, election_type),
    ).fetchone()
    return None if row is None else row[0]


def _legacy_statewide_state_senate_contest_id(
    conn: psycopg.Connection,
    *,
    contest_name: str,
    office_id: UUID,
    election_date: date,
    election_type: str,
) -> UUID | None:
    row = conn.execute(
        """
        SELECT ct.id
        FROM civic.contest ct
        JOIN civic.electoral_division d ON d.id = ct.electoral_division_id
        WHERE ct.name = %s
          AND ct.office_id = %s
          AND ct.election_date IS NOT DISTINCT FROM %s
          AND ct.election_type = %s
          AND d.division_type = 'statewide'
          AND d.name = 'NC'
          AND d.state = 'NC'
        LIMIT 1
        """,
        (contest_name, office_id, election_date, election_type),
    ).fetchone()
    return None if row is None else row[0]


def _reconcile_state_senate_legacy_scope(
    conn: psycopg.Connection,
    *,
    parsed_row: CandidateListingRow,
    office_id: UUID,
    canonical_division_id: UUID,
    election_type: str,
    source_record_id: UUID,
) -> None:
    if not parsed_row.contest_name.upper().startswith("NC STATE SENATE DISTRICT "):
        return

    legacy_contest_id = _legacy_statewide_state_senate_contest_id(
        conn,
        contest_name=parsed_row.contest_name,
        office_id=office_id,
        election_date=parsed_row.election_date,
        election_type=election_type,
    )
    if legacy_contest_id is None:
        return

    canonical_contest_id = _contest_id_for_canonical_key(
        conn,
        office_id=office_id,
        electoral_division_id=canonical_division_id,
        election_date=parsed_row.election_date,
        election_type=election_type,
    )

    if canonical_contest_id is None:
        conn.execute(
            """
            UPDATE civic.contest
            SET electoral_division_id = %s,
                source_record_id = COALESCE(%s, source_record_id),
                updated_at = NOW()
            WHERE id = %s
            """,
            (canonical_division_id, source_record_id, legacy_contest_id),
        )
        return

    if canonical_contest_id == legacy_contest_id:
        return

    # Merge stale candidacies into the canonical contest before dropping legacy row.
    conn.execute(
        """
        DELETE FROM civic.candidacy legacy
        USING civic.candidacy canonical
        WHERE legacy.contest_id = %s
          AND canonical.contest_id = %s
          AND legacy.person_id = canonical.person_id
        """,
        (legacy_contest_id, canonical_contest_id),
    )
    conn.execute(
        """
        UPDATE civic.candidacy
        SET contest_id = %s,
            source_record_id = COALESCE(%s, source_record_id),
            updated_at = NOW()
        WHERE contest_id = %s
        """,
        (canonical_contest_id, source_record_id, legacy_contest_id),
    )
    conn.execute(
        """
        DELETE FROM civic.contest
        WHERE id = %s
        """,
        (legacy_contest_id,),
    )


def _build_person_stub(raw_fields: dict[str, str], *, candidate_display_name: str) -> Person:
    return Person(
        canonical_name=candidate_display_name,
        first_name=_non_empty_or_none(raw_fields["first_name"].title()),
        middle_name=_non_empty_or_none(raw_fields["middle_name"].title()),
        last_name=_non_empty_or_none(raw_fields["last_name"].title()),
        suffix=_non_empty_or_none(raw_fields["name_suffix_lbl"]),
        identifiers=_STUB_IDENTIFIERS,
    )


def load_candidate_listing(
    conn: psycopg.Connection,
    *,
    csv_path: Path,
    today: date | None = None,
    year_from: int | None = None,
) -> CandidateListingLoadSummary:
    """Load NCSBE candidate-listing rows via canonical civic upsert/provenance owners."""
    parsed = parse_ncsbe_candidate_listing(csv_path)
    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"Candidate listing CSV missing header row: {csv_path}")
        raw_rows = list(reader)

    if len(raw_rows) != len(parsed.rows):
        raise RuntimeError(
            "Candidate listing parser/raw row mismatch: "
            f"parsed_rows={len(parsed.rows)} raw_rows={len(raw_rows)}"
        )

    resolved_today = today or datetime.now().date()
    pull_date = utc_now()
    data_source_id = _ensure_ncsbe_data_source(conn, csv_path=csv_path)

    rows_loaded = 0
    rows_skipped_out_of_window = 0
    offices_upserted = 0
    electoral_divisions_upserted = 0
    contests_upserted = 0
    candidacies_upserted = 0
    source_records_inserted = 0
    source_records_reused = 0

    for parsed_row, source_row in zip(parsed.rows, raw_rows, strict=True):
        if not _in_supported_window(parsed_row.election_date, today=resolved_today, year_from=year_from):
            rows_skipped_out_of_window += 1
            continue

        raw_fields = _normalize_raw_row(source_row, header=parsed.header)
        source_record_id, source_record_inserted = _resolve_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_url=_NCSBE_CANDIDATE_LISTING_SOURCE_URL,
            raw_fields=raw_fields,
            pull_date=pull_date,
        )
        if source_record_inserted:
            source_records_inserted += 1
        else:
            source_records_reused += 1

        office_name = parsed_row.contest_name
        office_level = _office_level_for_contest(parsed_row.contest_name)
        office_exists_before = _office_exists(conn, office_level=office_level, state="NC", name=office_name)
        office_id = upsert_office(
            conn,
            Office(
                name=office_name,
                office_level=office_level,
                state="NC",
                number_of_seats=max(1, parsed_row.vote_for),
                source_record_id=source_record_id,
            ),
        )
        if not office_exists_before:
            offices_upserted += 1

        division_scope = _derive_division_scope(parsed_row)
        division_exists_before = _electoral_division_exists(
            conn,
            division_type=division_scope.division_type,
            state="NC",
            name=division_scope.division_name,
        )
        division_id = upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=division_scope.division_name,
                division_type=division_scope.division_type,
                state="NC",
                district_number=division_scope.district_number,
                source_record_id=source_record_id,
            ),
        )
        if not division_exists_before:
            electoral_divisions_upserted += 1

        election_type = _candidacy_election_type(parsed_row)
        _reconcile_state_senate_legacy_scope(
            conn,
            parsed_row=parsed_row,
            office_id=office_id,
            canonical_division_id=division_id,
            election_type=election_type,
            source_record_id=source_record_id,
        )
        contest_exists_before = _contest_exists(
            conn,
            office_id=office_id,
            electoral_division_id=division_id,
            election_date=parsed_row.election_date,
            election_type=election_type,
        )
        contest_id = upsert_contest(
            conn,
            Contest(
                name=parsed_row.contest_name,
                election_date=parsed_row.election_date,
                election_type=election_type,
                office_id=office_id,
                electoral_division_id=division_id,
                number_of_seats=max(1, parsed_row.vote_for),
                is_partisan=parsed_row.is_partisan,
                source_record_id=source_record_id,
            ),
        )
        if not contest_exists_before:
            contests_upserted += 1

        person_id = resolve_person_by_name_and_zip(
            conn,
            _build_person_stub(raw_fields, candidate_display_name=parsed_row.candidate_display_name),
            None,
        )
        if person_id is None:
            raise RuntimeError("resolve_person_by_name_and_zip returned None for candidate stub row")

        candidacy_exists_before = _candidacy_exists(conn, person_id=person_id, contest_id=contest_id)
        upsert_candidacy(
            conn,
            Candidacy(
                person_id=person_id,
                contest_id=contest_id,
                party=_non_empty_or_none(parsed_row.party_candidate),
                filing_date=_parse_optional_mmddyyyy(raw_fields["candidacy_dt"]),
                status="filed",
                incumbent_challenge=None,
                candidate_number=None,
                name_on_ballot=parsed_row.name_on_ballot,
                is_unexpired_term=_parse_bool(raw_fields["is_unexpired"]),
                raw_fields=raw_fields,
                committee_id=_parse_committee_id(raw_fields),
                source_record_id=source_record_id,
            ),
        )
        if not candidacy_exists_before:
            candidacies_upserted += 1
        rows_loaded += 1

    return CandidateListingLoadSummary(
        rows_read=len(parsed.rows),
        rows_loaded=rows_loaded,
        rows_skipped_out_of_window=rows_skipped_out_of_window,
        offices_upserted=offices_upserted,
        electoral_divisions_upserted=electoral_divisions_upserted,
        contests_upserted=contests_upserted,
        candidacies_upserted=candidacies_upserted,
        source_records_inserted=source_records_inserted,
        source_records_reused=source_records_reused,
    )


def load_candidate_listing_from_source(
    *,
    year_from: int | None = None,
    candidate_listing_path: Path | None = None,
) -> CandidateListingLoadSummary:
    """Load candidate listings from an override path or the canonical NCSBE CSV."""
    connection: psycopg.Connection | None = None
    try:
        connection = get_connection()
        with connection.transaction():
            if candidate_listing_path is not None:
                summary = load_candidate_listing(connection, csv_path=candidate_listing_path, year_from=year_from)
            else:
                with tempfile.TemporaryDirectory(prefix="nc-candidate-listing-") as temp_dir:
                    canonical_csv_path = Path(temp_dir) / "candidate_listing_2026.csv"
                    urlretrieve(_NCSBE_CANDIDATE_LISTING_SOURCE_URL, canonical_csv_path)
                    summary = load_candidate_listing(connection, csv_path=canonical_csv_path, year_from=year_from)
        connection.commit()
        return summary
    finally:
        if connection is not None:
            connection.close()
