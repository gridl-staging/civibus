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
    resolve_people_by_name_and_zip,
    try_insert_data_source,
)
from core.db_ingest import EntitySourceLink, insert_entity_sources_bulk, try_insert_source_records_bulk
from core.types.python.models import DataSource, Person, SourceRecord, compute_record_hash, utc_now
from domains.civics.ingest import (
    candidacy_natural_key,
    contest_natural_key,
    electoral_division_natural_key,
    office_natural_key,
    office_preexistence_key,
    select_candidacy_ids_by_natural_key,
    select_contest_ids_by_natural_key,
    select_electoral_division_ids_by_natural_key,
    select_office_ids_and_preexistence,
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


@dataclass(frozen=True)
class _PreparedCandidateListingRow:
    parsed: CandidateListingRow
    raw_fields: dict[str, str]
    source_record: SourceRecord


@dataclass(frozen=True)
class _CandidateListingPreparation:
    header: list[str]
    today: date
    year_from: int | None
    data_source_id: UUID
    pull_date: datetime


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
    if "COURT" in uppercase_name or "JUDGE" in uppercase_name or "DISTRICT ATTORNEY" in uppercase_name:
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

    if uppercase_name.startswith("NC SENATE DISTRICT ") or uppercase_name.startswith("NC STATE SENATE DISTRICT "):
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

    if "CITY OF " in uppercase_name or "TOWN OF " in uppercase_name or "VILLAGE OF " in uppercase_name:
        return _DivisionScope(division_name=f"NC {parsed_row.county_name}", division_type="municipal")

    if county_name in uppercase_name or f"{county_name}-" in uppercase_name or " COUNTY " in uppercase_name:
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
    canonical_contest_id: UUID | None,
) -> UUID | None:
    if not parsed_row.contest_name.upper().startswith("NC STATE SENATE DISTRICT "):
        return canonical_contest_id

    legacy_contest_id = _legacy_statewide_state_senate_contest_id(
        conn,
        contest_name=parsed_row.contest_name,
        office_id=office_id,
        election_date=parsed_row.election_date,
        election_type=election_type,
    )
    if legacy_contest_id is None:
        return canonical_contest_id

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
        return legacy_contest_id

    if canonical_contest_id == legacy_contest_id:
        return canonical_contest_id

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
    return canonical_contest_id


def _build_person_stub(raw_fields: dict[str, str], *, candidate_display_name: str) -> Person:
    return Person(
        canonical_name=candidate_display_name,
        first_name=_non_empty_or_none(raw_fields["first_name"].title()),
        middle_name=_non_empty_or_none(raw_fields["middle_name"].title()),
        last_name=_non_empty_or_none(raw_fields["last_name"].title()),
        suffix=_non_empty_or_none(raw_fields["name_suffix_lbl"]),
        identifiers=_STUB_IDENTIFIERS,
    )


def _prepare_supported_rows(
    parsed_rows: list[CandidateListingRow],
    raw_rows: list[dict[str, str]],
    preparation: _CandidateListingPreparation,
) -> tuple[list[_PreparedCandidateListingRow], int]:
    prepared_rows: list[_PreparedCandidateListingRow] = []
    skipped = 0
    for parsed_row, source_row in zip(parsed_rows, raw_rows, strict=True):
        if not _in_supported_window(
            parsed_row.election_date,
            today=preparation.today,
            year_from=preparation.year_from,
        ):
            skipped += 1
            continue
        raw_fields = _normalize_raw_row(source_row, header=preparation.header)
        record_hash = compute_record_hash(raw_fields)
        prepared_rows.append(
            _PreparedCandidateListingRow(
                parsed=parsed_row,
                raw_fields=raw_fields,
                source_record=SourceRecord(
                    data_source_id=preparation.data_source_id,
                    source_record_key=f"{_NCSBE_SOURCE_RECORD_KEY_PREFIX}:{record_hash}",
                    source_url=_NCSBE_CANDIDATE_LISTING_SOURCE_URL,
                    raw_fields=raw_fields,
                    pull_date=preparation.pull_date,
                    record_hash=record_hash,
                ),
            )
        )
    return prepared_rows, skipped


def _upsert_prepared_offices(
    conn: psycopg.Connection,
    prepared_rows: list[_PreparedCandidateListingRow],
    source_record_ids: list[UUID],
) -> tuple[list[UUID], int]:
    offices = [
        Office(
            name=row.parsed.contest_name,
            office_level=_office_level_for_contest(row.parsed.contest_name),
            state="NC",
            number_of_seats=max(1, row.parsed.vote_for),
            source_record_id=source_record_id,
        )
        for row, source_record_id in zip(prepared_rows, source_record_ids, strict=True)
    ]
    existing_ids, preexisting_keys = select_office_ids_and_preexistence(conn, offices)
    last_office_by_key = {office_natural_key(office): office for office in offices}
    created = 0
    for key, office in last_office_by_key.items():
        created += office_preexistence_key(office) not in preexisting_keys
        existing_ids[key] = upsert_office(conn, office, link_source=False)
    return [existing_ids[office_natural_key(office)] for office in offices], created


def _upsert_prepared_divisions(
    conn: psycopg.Connection,
    prepared_rows: list[_PreparedCandidateListingRow],
    source_record_ids: list[UUID],
) -> tuple[list[UUID], int]:
    divisions = []
    for row, source_record_id in zip(prepared_rows, source_record_ids, strict=True):
        scope = _derive_division_scope(row.parsed)
        divisions.append(
            ElectoralDivision(
                name=scope.division_name,
                division_type=scope.division_type,
                state="NC",
                district_number=scope.district_number,
                source_record_id=source_record_id,
            )
        )
    existing_ids = select_electoral_division_ids_by_natural_key(conn, divisions)
    last_division_by_key = {electoral_division_natural_key(division): division for division in divisions}
    created = 0
    for key, division in last_division_by_key.items():
        created += key not in existing_ids
        existing_ids[key] = upsert_electoral_division(conn, division, link_source=False)
    return [existing_ids[electoral_division_natural_key(division)] for division in divisions], created


def _build_prepared_contests(
    prepared_rows: list[_PreparedCandidateListingRow],
    source_record_ids: list[UUID],
    office_ids: list[UUID],
    division_ids: list[UUID],
) -> list[Contest]:
    return [
        Contest(
            name=row.parsed.contest_name,
            election_date=row.parsed.election_date,
            election_type=_candidacy_election_type(row.parsed),
            office_id=office_id,
            electoral_division_id=division_id,
            number_of_seats=max(1, row.parsed.vote_for),
            is_partisan=row.parsed.is_partisan,
            source_record_id=source_record_id,
        )
        for row, source_record_id, office_id, division_id in zip(
            prepared_rows,
            source_record_ids,
            office_ids,
            division_ids,
            strict=True,
        )
    ]


def _upsert_prepared_contests(
    conn: psycopg.Connection,
    prepared_rows: list[_PreparedCandidateListingRow],
    contests: list[Contest],
) -> tuple[list[UUID], int]:
    existing_ids = select_contest_ids_by_natural_key(conn, contests)
    last_contest_by_key = {
        contest_natural_key(contest): (row, contest) for row, contest in zip(prepared_rows, contests, strict=True)
    }
    created = 0
    for key, (row, contest) in last_contest_by_key.items():
        reconciled_id = _reconcile_state_senate_legacy_scope(
            conn,
            parsed_row=row.parsed,
            office_id=contest.office_id,
            canonical_division_id=contest.electoral_division_id,
            election_type=contest.election_type,
            source_record_id=contest.source_record_id,
            canonical_contest_id=existing_ids.get(key),
        )
        if reconciled_id is not None:
            existing_ids[key] = reconciled_id
        created += key not in existing_ids
        existing_ids[key] = upsert_contest(conn, contest, link_source=False)
    return [existing_ids[contest_natural_key(contest)] for contest in contests], created


def _build_prepared_candidacies(
    prepared_rows: list[_PreparedCandidateListingRow],
    source_record_ids: list[UUID],
    person_ids: list[UUID],
    contest_ids: list[UUID],
) -> list[Candidacy]:
    return [
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            party=_non_empty_or_none(row.parsed.party_candidate),
            filing_date=_parse_optional_mmddyyyy(row.raw_fields["candidacy_dt"]),
            status="filed",
            incumbent_challenge=None,
            candidate_number=None,
            name_on_ballot=row.parsed.name_on_ballot,
            is_unexpired_term=_parse_bool(row.raw_fields["is_unexpired"]),
            raw_fields=row.raw_fields,
            committee_id=_parse_committee_id(row.raw_fields),
            source_record_id=source_record_id,
        )
        for row, source_record_id, person_id, contest_id in zip(
            prepared_rows,
            source_record_ids,
            person_ids,
            contest_ids,
            strict=True,
        )
    ]


def _upsert_prepared_candidacies(
    conn: psycopg.Connection,
    candidacies: list[Candidacy],
) -> tuple[list[UUID], int]:
    existing_ids = select_candidacy_ids_by_natural_key(conn, candidacies)
    candidacies_by_key: dict[tuple[UUID, UUID], list[Candidacy]] = {}
    for candidacy in candidacies:
        candidacies_by_key.setdefault(candidacy_natural_key(candidacy), []).append(candidacy)

    created = 0
    for key, grouped_candidacies in candidacies_by_key.items():
        created += key not in existing_ids
        for candidacy in grouped_candidacies:
            existing_ids[key] = upsert_candidacy(conn, candidacy, link_source=False)
    return [existing_ids[candidacy_natural_key(candidacy)] for candidacy in candidacies], created


def _insert_prepared_provenance(
    conn: psycopg.Connection,
    source_record_ids: list[UUID],
    office_ids: list[UUID],
    division_ids: list[UUID],
    contest_ids: list[UUID],
    candidacy_ids: list[UUID],
) -> None:
    links: list[EntitySourceLink] = []
    for source_id, office_id, division_id, contest_id, candidacy_id in zip(
        source_record_ids,
        office_ids,
        division_ids,
        contest_ids,
        candidacy_ids,
        strict=True,
    ):
        links.extend(
            EntitySourceLink(
                entity_type=entity_type,
                entity_id=entity_id,
                source_record_id=source_id,
                extraction_role=entity_type,
            )
            for entity_type, entity_id in (
                ("office", office_id),
                ("electoral_division", division_id),
                ("contest", contest_id),
                ("candidacy", candidacy_id),
            )
        )
    insert_entity_sources_bulk(conn, links)


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
            f"Candidate listing parser/raw row mismatch: parsed_rows={len(parsed.rows)} raw_rows={len(raw_rows)}"
        )

    data_source_id = _ensure_ncsbe_data_source(conn, csv_path=csv_path)
    prepared_rows, rows_skipped_out_of_window = _prepare_supported_rows(
        parsed.rows,
        raw_rows,
        _CandidateListingPreparation(
            header=parsed.header,
            today=today or datetime.now().date(),
            year_from=year_from,
            data_source_id=data_source_id,
            pull_date=utc_now(),
        ),
    )
    source_results = try_insert_source_records_bulk(
        conn,
        [row.source_record for row in prepared_rows],
    )
    if any(result.source_record_id is None for result in source_results):
        raise RuntimeError("Bulk source-record resolution did not return every active identity")
    source_record_ids = [result.source_record_id for result in source_results if result.source_record_id is not None]

    office_ids, offices_upserted = _upsert_prepared_offices(conn, prepared_rows, source_record_ids)
    division_ids, electoral_divisions_upserted = _upsert_prepared_divisions(
        conn,
        prepared_rows,
        source_record_ids,
    )
    contests = _build_prepared_contests(prepared_rows, source_record_ids, office_ids, division_ids)
    contest_ids, contests_upserted = _upsert_prepared_contests(conn, prepared_rows, contests)
    people = [
        _build_person_stub(row.raw_fields, candidate_display_name=row.parsed.candidate_display_name)
        for row in prepared_rows
    ]
    person_ids = resolve_people_by_name_and_zip(conn, people, [None] * len(people))
    candidacies = _build_prepared_candidacies(
        prepared_rows,
        source_record_ids,
        person_ids,
        contest_ids,
    )
    candidacy_ids, candidacies_upserted = _upsert_prepared_candidacies(conn, candidacies)
    _insert_prepared_provenance(
        conn,
        source_record_ids,
        office_ids,
        division_ids,
        contest_ids,
        candidacy_ids,
    )

    return CandidateListingLoadSummary(
        rows_read=len(parsed.rows),
        rows_loaded=len(prepared_rows),
        rows_skipped_out_of_window=rows_skipped_out_of_window,
        offices_upserted=offices_upserted,
        electoral_divisions_upserted=electoral_divisions_upserted,
        contests_upserted=contests_upserted,
        candidacies_upserted=candidacies_upserted,
        source_records_inserted=sum(result.inserted for result in source_results),
        source_records_reused=sum(not result.inserted for result in source_results),
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
