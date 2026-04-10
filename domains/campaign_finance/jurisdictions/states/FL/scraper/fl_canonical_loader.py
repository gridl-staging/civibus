
from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from itertools import islice
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import insert_person
from core.db_ingest import (
    find_person_by_identifier,
    insert_entity_source,
    try_insert_source_record,
    upsert_contact_point,
)
from core.types.python.models import ContactPoint, Person, SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.normalize.dates import parse_date
from domains.civics.ingest import (
    derive_incumbent_challenge,
    upsert_candidacy,
    upsert_contest,
    upsert_electoral_division,
)
from domains.civics.types.models import Candidacy, Contest, ElectoralDivision

LOGGER = logging.getLogger(__name__)

_FL_CANDIDATE_LIST_SOURCE_URL = "https://dos.elections.myflorida.com/candidates/downloadcanlist.asp"

# Deterministic office seeds from domains/civics/schema/tables.sql
_OFFICE_FL_ATTORNEY_GENERAL = UUID("00000000-0000-4000-8000-000000000301")
_OFFICE_FL_CHIEF_FINANCIAL_OFFICER = UUID("00000000-0000-4000-8000-000000000302")
_OFFICE_FL_COMMISSIONER_OF_AGRICULTURE = UUID("00000000-0000-4000-8000-000000000303")
_OFFICE_FL_COUNTY = UUID("00000000-0000-4000-8000-000000000304")
_OFFICE_FL_GOVERNOR = UUID("00000000-0000-4000-8000-000000000305")
_OFFICE_FL_LIEUTENANT_GOVERNOR = UUID("00000000-0000-4000-8000-000000000306")
_OFFICE_FL_MUNICIPAL = UUID("00000000-0000-4000-8000-000000000307")
_OFFICE_FL_SCHOOL_DISTRICT = UUID("00000000-0000-4000-8000-000000000308")
_OFFICE_FL_SPECIAL_DISTRICT = UUID("00000000-0000-4000-8000-000000000309")
_OFFICE_FL_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000310")
_OFFICE_FL_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000311")

# Electoral division parent seeds from domains/civics/schema/tables.sql
_DIVISION_FL = UUID("00000000-0000-4000-8000-000000000503")
_DIVISION_FL_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000511")
_DIVISION_FL_HOUSE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000512")
_DIVISION_FL_COUNTIES = UUID("00000000-0000-4000-8000-000000000513")
_DIVISION_FL_MUNICIPALITIES = UUID("00000000-0000-4000-8000-000000000514")
_DIVISION_FL_SCHOOL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000515")
_DIVISION_FL_SPECIAL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000516")

_FL_OFFICE_CODE_MAP: dict[str, UUID] = {
    "AG": _OFFICE_FL_ATTORNEY_GENERAL,
    "CFO": _OFFICE_FL_CHIEF_FINANCIAL_OFFICER,
    "COMA": _OFFICE_FL_COMMISSIONER_OF_AGRICULTURE,
    "CA": _OFFICE_FL_COUNTY,
    "GOV": _OFFICE_FL_GOVERNOR,
    "LTG": _OFFICE_FL_LIEUTENANT_GOVERNOR,
    "MUN": _OFFICE_FL_MUNICIPAL,
    "SB": _OFFICE_FL_SCHOOL_DISTRICT,
    "SP": _OFFICE_FL_SPECIAL_DISTRICT,
    "SH": _OFFICE_FL_STATE_HOUSE,
    "SS": _OFFICE_FL_STATE_SENATE,
}

_FL_STATEWIDE_OFFICES = {
    _OFFICE_FL_GOVERNOR,
    _OFFICE_FL_LIEUTENANT_GOVERNOR,
    _OFFICE_FL_ATTORNEY_GENERAL,
    _OFFICE_FL_CHIEF_FINANCIAL_OFFICER,
    _OFFICE_FL_COMMISSIONER_OF_AGRICULTURE,
}


def _resolve_office_from_desc(office_desc: str) -> UUID | None:
    desc = office_desc.strip().lower()
    if "lieutenant" in desc and "governor" in desc:
        return _OFFICE_FL_LIEUTENANT_GOVERNOR
    if "governor" in desc:
        return _OFFICE_FL_GOVERNOR
    if "attorney" in desc and "general" in desc:
        return _OFFICE_FL_ATTORNEY_GENERAL
    if "chief financial" in desc:
        return _OFFICE_FL_CHIEF_FINANCIAL_OFFICER
    if "commissioner" in desc and "agriculture" in desc:
        return _OFFICE_FL_COMMISSIONER_OF_AGRICULTURE
    if "state senator" in desc or "state senate" in desc:
        return _OFFICE_FL_STATE_SENATE
    if "state representative" in desc or "state house" in desc:
        return _OFFICE_FL_STATE_HOUSE
    if "school" in desc:
        return _OFFICE_FL_SCHOOL_DISTRICT
    if "special district" in desc:
        return _OFFICE_FL_SPECIAL_DISTRICT
    if "municipal" in desc or "city" in desc:
        return _OFFICE_FL_MUNICIPAL
    if "county" in desc:
        return _OFFICE_FL_COUNTY
    return None


def _resolve_office_id(office_code: str | None, office_desc: str | None) -> UUID | None:
    if office_code is not None:
        mapped = _FL_OFFICE_CODE_MAP.get(office_code.upper())
        if mapped is not None:
            return mapped
    if office_desc is None:
        return None
    return _resolve_office_from_desc(office_desc)


def _resolve_electoral_division(
    conn: psycopg.Connection,
    office_id: UUID,
    juris1num: str | None,
    juris2num: str | None,
) -> UUID | None:
    if office_id in _FL_STATEWIDE_OFFICES:
        return _DIVISION_FL

    if office_id == _OFFICE_FL_STATE_SENATE:
        if juris1num is None:
            return None
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"fl_sd_{juris1num}",
                division_type="state_legislative_upper",
                state="FL",
                district_number=juris1num,
                parent_id=_DIVISION_FL_SENATE_DISTRICTS,
            ),
        )

    if office_id == _OFFICE_FL_STATE_HOUSE:
        if juris1num is None:
            return None
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"fl_hd_{juris1num}",
                division_type="state_legislative_lower",
                state="FL",
                district_number=juris1num,
                parent_id=_DIVISION_FL_HOUSE_DISTRICTS,
            ),
        )

    if office_id == _OFFICE_FL_COUNTY:
        if juris1num is None:
            return None
        district_suffix = f"_{juris2num}" if juris2num else ""
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"fl_county_{juris1num}{district_suffix}",
                division_type="county",
                state="FL",
                district_number=juris1num,
                parent_id=_DIVISION_FL_COUNTIES,
            ),
        )

    if office_id == _OFFICE_FL_MUNICIPAL:
        locality = juris2num or juris1num
        if locality is None:
            return None
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"fl_muni_{locality}",
                division_type="municipal",
                state="FL",
                district_number=locality,
                parent_id=_DIVISION_FL_MUNICIPALITIES,
            ),
        )

    if office_id == _OFFICE_FL_SCHOOL_DISTRICT:
        district = juris2num or juris1num
        if district is None:
            return None
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"fl_school_{district}",
                division_type="school_district",
                state="FL",
                district_number=district,
                parent_id=_DIVISION_FL_SCHOOL_DISTRICTS,
            ),
        )

    if office_id == _OFFICE_FL_SPECIAL_DISTRICT:
        district = juris2num or juris1num
        if district is None:
            return None
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"fl_special_{district}",
                division_type="special_district",
                state="FL",
                district_number=district,
                parent_id=_DIVISION_FL_SPECIAL_DISTRICTS,
            ),
        )

    return None


def _try_insert_candidate_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    raw_fields: dict[str, object],
) -> UUID | None:
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=_FL_CANDIDATE_LIST_SOURCE_URL,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    return try_insert_source_record(conn, source_record)


def _resolve_or_create_person(
    conn: psycopg.Connection,
    *,
    canonical_name: str,
    first_name: str | None,
    last_name: str | None,
    candidate_id: str | None,
    source_record_id: UUID,
) -> UUID:
    if candidate_id is not None:
        person_id = find_person_by_identifier(conn, "fl_candidate_id", candidate_id)
        if person_id is not None:
            insert_entity_source(conn, "person", person_id, source_record_id, "candidate")
            return person_id

    person_id = insert_person(
        conn,
        Person(
            canonical_name=canonical_name,
            first_name=first_name,
            last_name=last_name,
            identifiers={"fl_candidate_id": candidate_id} if candidate_id is not None else {},
        ),
    )
    insert_entity_source(conn, "person", person_id, source_record_id, "candidate")
    return person_id


def _parse_required_election_date(raw_value: str | None) -> date:
    normalized_date = normalize_optional_text(raw_value)
    if normalized_date is None:
        raise ValueError("Missing ElectionDate field")

    parsed = parse_date(normalized_date)
    if parsed.value is None:
        raise ValueError(f"Invalid ElectionDate value: {normalized_date!r}")
    return date.fromisoformat(parsed.value)


def _build_contest_name(office_desc: str | None, office_code: str | None, election_date: date) -> str:
    office_label = office_desc or office_code or "Office"
    return f"FL {office_label} General {election_date.year}"


def _ingest_candidate_row(conn: psycopg.Connection, raw_row: dict[str, str | None], source_record_id: UUID) -> None:
    office_code = normalize_optional_text(raw_row.get("OfficeCode"))
    office_desc = normalize_optional_text(raw_row.get("OfficeDesc"))
    office_id = _resolve_office_id(office_code, office_desc)
    if office_id is None:
        raise ValueError(f"Unknown office mapping for OfficeCode={office_code!r}, OfficeDesc={office_desc!r}")

    candidate_name = normalize_optional_text(raw_row.get("CandName"))
    first_name = normalize_optional_text(raw_row.get("CandFirstName"))
    last_name = normalize_optional_text(raw_row.get("CandLastName"))
    if candidate_name is None and (first_name is None or last_name is None):
        raise ValueError("Missing candidate name fields")

    candidate_id = normalize_optional_text(raw_row.get("CandidateId"))
    party = normalize_optional_text(raw_row.get("Party"))
    status = normalize_optional_text(raw_row.get("Status"))
    juris1num = normalize_optional_text(raw_row.get("Juris1num"))
    juris2num = normalize_optional_text(raw_row.get("Juris2num"))

    election_date = _parse_required_election_date(raw_row.get("ElectionDate"))
    division_id = _resolve_electoral_division(conn, office_id, juris1num, juris2num)
    person_id = _resolve_or_create_person(
        conn,
        canonical_name=candidate_name or f"{last_name}, {first_name}",
        first_name=first_name,
        last_name=last_name,
        candidate_id=candidate_id,
        source_record_id=source_record_id,
    )
    incumbent_challenge = derive_incumbent_challenge(
        conn,
        person_id,
        office_id,
        division_id,
        as_of=election_date,
    )
    contest_id = upsert_contest(
        conn,
        Contest(
            name=_build_contest_name(office_desc, office_code, election_date),
            election_date=election_date,
            election_type="general",
            office_id=office_id,
            electoral_division_id=division_id,
            source_record_id=source_record_id,
        ),
    )

    candidacy_id = upsert_candidacy(
        conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            party=party,
            status=status,
            incumbent_challenge=incumbent_challenge,
            candidate_number=candidate_id,
            source_record_id=source_record_id,
        ),
    )

    email = normalize_optional_text(raw_row.get("Email"))
    if email is not None:
        upsert_contact_point(
            conn,
            ContactPoint(
                type="email",
                value_raw=email,
                owner_type="candidacy",
                owner_id=candidacy_id,
                role="campaign",
                source_record_id=source_record_id,
            ),
        )

    phone = normalize_optional_text(raw_row.get("Phone"))
    if phone is not None:
        upsert_contact_point(
            conn,
            ContactPoint(
                type="phone",
                value_raw=phone,
                owner_type="candidacy",
                owner_id=candidacy_id,
                role="campaign",
                source_record_id=source_record_id,
            ),
        )


def _source_record_key(raw_row: Mapping[str, str | None]) -> str:
    candidate_id = normalize_optional_text(raw_row.get("CandidateId")) or "candidate"
    office_code = normalize_optional_text(raw_row.get("OfficeCode"))
    office_desc = normalize_optional_text(raw_row.get("OfficeDesc"))
    office_fragment = office_code or office_desc or "office"
    election_date = normalize_optional_text(raw_row.get("ElectionDate")) or "election"
    return f"fl_canonical:{candidate_id}:{office_fragment}:{election_date}"


def load_fl_candidates_canonical(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    batch_size: int = 1000,
) -> LoadResult:
    """Load FL candidate-download rows into canonical civic.* and contact_point tables."""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    result = LoadResult()
    processed_since_commit = 0

    for raw_row in rows:
        row = dict(raw_row)
        source_record_id = _try_insert_candidate_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=_source_record_key(row),
            raw_fields=row,
        )
        if source_record_id is None:
            result.skipped += 1
            continue

        try:
            _ingest_candidate_row(conn, row, source_record_id)
        except (ValueError, KeyError) as exc:
            LOGGER.warning("Skipping FL candidate row %s: %s", row.get("CandidateId") or "unknown", exc)
            result.errors += 1
            continue

        result.inserted += 1
        processed_since_commit += 1
        if processed_since_commit >= batch_size:
            conn.commit()
            processed_since_commit = 0

    if processed_since_commit > 0:
        conn.commit()

    return result


def iter_fl_candidate_rows(path: str | Path) -> Iterator[dict[str, str | None]]:
    """Yield row dicts from the FL candidate TSV export."""
    candidate_path = Path(path)
    with candidate_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter="\t")
        for row in reader:
            yield {key: normalize_optional_text(value) for key, value in row.items() if key is not None}


def load_fl_candidates_canonical_from_tsv(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    """Parse FL candidate TSV and load rows into canonical entities."""
    rows: Iterable[dict[str, str | None]] = iter_fl_candidate_rows(path)
    if limit is not None:
        rows = islice(rows, limit)
    return load_fl_candidates_canonical(conn, rows, data_source_id=data_source_id, batch_size=batch_size)
