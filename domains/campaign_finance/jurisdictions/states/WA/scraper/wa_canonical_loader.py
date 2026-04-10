
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from uuid import UUID

import psycopg

from core.db import insert_organization, insert_person
from core.db_ingest import (
    find_organization_by_canonical_name,
    find_person_by_identifier,
    insert_entity_source,
    try_insert_source_record,
    upsert_contact_point,
)
from core.types.python.models import (
    ContactPoint,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.civics.ingest import (
    derive_incumbent_challenge,
    upsert_candidacy,
    upsert_contest,
    upsert_electoral_division,
)
from domains.civics.types.models import Candidacy, Contest, ElectoralDivision

LOGGER = logging.getLogger(__name__)

# Deterministic seed UUIDs from domains/civics/schema/tables.sql — WA offices
_OFFICE_WA_ATTORNEY_GENERAL = UUID("00000000-0000-4000-8000-000000000201")
_OFFICE_WA_COMMISSIONER_PUBLIC_LANDS = UUID("00000000-0000-4000-8000-000000000202")
_OFFICE_WA_COUNTY = UUID("00000000-0000-4000-8000-000000000203")
_OFFICE_WA_GOVERNOR = UUID("00000000-0000-4000-8000-000000000204")
_OFFICE_WA_INSURANCE_COMMISSIONER = UUID("00000000-0000-4000-8000-000000000205")
_OFFICE_WA_LIEUTENANT_GOVERNOR = UUID("00000000-0000-4000-8000-000000000206")
_OFFICE_WA_MUNICIPAL = UUID("00000000-0000-4000-8000-000000000207")
_OFFICE_WA_SCHOOL_DISTRICT = UUID("00000000-0000-4000-8000-000000000208")
_OFFICE_WA_SECRETARY_OF_STATE = UUID("00000000-0000-4000-8000-000000000209")
_OFFICE_WA_SPECIAL_DISTRICT = UUID("00000000-0000-4000-8000-000000000210")
_OFFICE_WA_STATE_AUDITOR = UUID("00000000-0000-4000-8000-000000000211")
_OFFICE_WA_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000212")
_OFFICE_WA_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000213")
_OFFICE_WA_STATE_TREASURER = UUID("00000000-0000-4000-8000-000000000214")
_OFFICE_WA_SUPERINTENDENT = UUID("00000000-0000-4000-8000-000000000215")

# Electoral division parent seeds
_DIVISION_WA = UUID("00000000-0000-4000-8000-000000000502")
_DIVISION_WA_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000505")
_DIVISION_WA_HOUSE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000506")
_DIVISION_WA_COUNTIES = UUID("00000000-0000-4000-8000-000000000507")
_DIVISION_WA_MUNICIPALITIES = UUID("00000000-0000-4000-8000-000000000508")
_DIVISION_WA_SCHOOL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000509")
_DIVISION_WA_SPECIAL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000510")

# Map WA office names (as they appear in PDC data) to seed office UUIDs.
# Keys are lowercased for case-insensitive matching.
_WA_OFFICE_MAP: dict[str, UUID] = {
    "governor": _OFFICE_WA_GOVERNOR,
    "lieutenant governor": _OFFICE_WA_LIEUTENANT_GOVERNOR,
    "secretary of state": _OFFICE_WA_SECRETARY_OF_STATE,
    "attorney general": _OFFICE_WA_ATTORNEY_GENERAL,
    "state treasurer": _OFFICE_WA_STATE_TREASURER,
    "state auditor": _OFFICE_WA_STATE_AUDITOR,
    "superintendent of public instruction": _OFFICE_WA_SUPERINTENDENT,
    "commissioner of public lands": _OFFICE_WA_COMMISSIONER_PUBLIC_LANDS,
    "insurance commissioner": _OFFICE_WA_INSURANCE_COMMISSIONER,
    "state senator": _OFFICE_WA_STATE_SENATE,
    "state senate": _OFFICE_WA_STATE_SENATE,
    "state representative": _OFFICE_WA_STATE_HOUSE,
    "state house": _OFFICE_WA_STATE_HOUSE,
    "county council": _OFFICE_WA_COUNTY,
    "county commissioner": _OFFICE_WA_COUNTY,
    "county executive": _OFFICE_WA_COUNTY,
    "county assessor": _OFFICE_WA_COUNTY,
    "county auditor": _OFFICE_WA_COUNTY,
    "county clerk": _OFFICE_WA_COUNTY,
    "county coroner": _OFFICE_WA_COUNTY,
    "county prosecutor": _OFFICE_WA_COUNTY,
    "county sheriff": _OFFICE_WA_COUNTY,
    "county treasurer": _OFFICE_WA_COUNTY,
    "school board": _OFFICE_WA_SCHOOL_DISTRICT,
    "school director": _OFFICE_WA_SCHOOL_DISTRICT,
}

# Offices that require a legislative_district for division resolution
_LEGISLATIVE_OFFICES = {_OFFICE_WA_STATE_SENATE, _OFFICE_WA_STATE_HOUSE}

# Statewide offices — division is the state itself
_STATEWIDE_OFFICES = {
    _OFFICE_WA_GOVERNOR,
    _OFFICE_WA_LIEUTENANT_GOVERNOR,
    _OFFICE_WA_SECRETARY_OF_STATE,
    _OFFICE_WA_ATTORNEY_GENERAL,
    _OFFICE_WA_STATE_TREASURER,
    _OFFICE_WA_STATE_AUDITOR,
    _OFFICE_WA_SUPERINTENDENT,
    _OFFICE_WA_COMMISSIONER_PUBLIC_LANDS,
    _OFFICE_WA_INSURANCE_COMMISSIONER,
}


def _fallback_office_id_for_type(office_type: str | None) -> UUID | None:
    """Map WA jurisdiction/candidate office types to the generic local office seeds."""
    normalized_office_type = normalize_optional_text(office_type)
    if normalized_office_type is None:
        return None

    office_type_lower = normalized_office_type.lower()
    if "county" in office_type_lower:
        return _OFFICE_WA_COUNTY
    if "municip" in office_type_lower or "city" in office_type_lower or "town" in office_type_lower:
        return _OFFICE_WA_MUNICIPAL
    if "school" in office_type_lower:
        return _OFFICE_WA_SCHOOL_DISTRICT
    if "special" in office_type_lower:
        return _OFFICE_WA_SPECIAL_DISTRICT
    return None


def _resolve_office_id(office_raw: str, *, office_type: str | None = None) -> UUID | None:
    """Map a WA office name to its seed UUID, falling back to the office-type bucket for local races."""
    mapped_office_id = _WA_OFFICE_MAP.get(office_raw.strip().lower())
    if mapped_office_id is not None:
        return mapped_office_id
    return _fallback_office_id_for_type(office_type)


def _resolve_electoral_division(
    conn: psycopg.Connection,
    office_id: UUID,
    legislative_district: str | None,
    jurisdiction_county: str | None,
    jurisdiction: str | None,
) -> UUID | None:
    """Resolve or create the electoral division for a WA candidate row."""
    if office_id in _STATEWIDE_OFFICES:
        return _DIVISION_WA

    if office_id in _LEGISLATIVE_OFFICES and legislative_district:
        district_padded = legislative_district.strip().zfill(2)
        if office_id == _OFFICE_WA_STATE_SENATE:
            name = f"wa_sd_{district_padded}"
            return upsert_electoral_division(
                conn,
                ElectoralDivision(
                    name=name,
                    division_type="state_legislative_upper",
                    state="WA",
                    district_number=district_padded,
                    parent_id=_DIVISION_WA_SENATE_DISTRICTS,
                ),
            )
        else:
            name = f"wa_hd_{district_padded}"
            return upsert_electoral_division(
                conn,
                ElectoralDivision(
                    name=name,
                    division_type="state_legislative_lower",
                    state="WA",
                    district_number=district_padded,
                    parent_id=_DIVISION_WA_HOUSE_DISTRICTS,
                ),
            )

    if office_id == _OFFICE_WA_COUNTY and jurisdiction_county:
        county_lower = jurisdiction_county.strip().lower()
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"wa_{county_lower}_county",
                division_type="county",
                state="WA",
                parent_id=_DIVISION_WA_COUNTIES,
            ),
        )

    if office_id == _OFFICE_WA_MUNICIPAL and jurisdiction:
        muni_lower = jurisdiction.strip().lower().replace(" ", "_")
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"wa_{muni_lower}",
                division_type="municipal",
                state="WA",
                parent_id=_DIVISION_WA_MUNICIPALITIES,
            ),
        )

    if office_id == _OFFICE_WA_SCHOOL_DISTRICT and jurisdiction:
        sd_lower = jurisdiction.strip().lower().replace(" ", "_")
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"wa_{sd_lower}_sd",
                division_type="school_district",
                state="WA",
                parent_id=_DIVISION_WA_SCHOOL_DISTRICTS,
            ),
        )

    if office_id == _OFFICE_WA_SPECIAL_DISTRICT and jurisdiction:
        sp_lower = jurisdiction.strip().lower().replace(" ", "_")
        return upsert_electoral_division(
            conn,
            ElectoralDivision(
                name=f"wa_{sp_lower}_special",
                division_type="special_district",
                state="WA",
                parent_id=_DIVISION_WA_SPECIAL_DISTRICTS,
            ),
        )

    return None


def wa_general_election_date(year: int) -> date:
    """WA general election: first Tuesday after the first Monday in November."""
    nov1 = date(year, 11, 1)
    dow = nov1.weekday()
    first_monday = 1 + (7 - dow) % 7
    return date(year, 11, first_monday + 1)


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


def _resolve_or_create_person(
    conn: psycopg.Connection,
    canonical_name: str,
    filer_id: str | None,
    source_record_id: UUID,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
) -> UUID:
    """Find existing person by wa_filer_id identifier, or create a new one."""
    if filer_id:
        person_id = find_person_by_identifier(conn, "wa_filer_id", filer_id)
        if person_id is not None:
            insert_entity_source(conn, "person", person_id, source_record_id, "candidate")
            return person_id

    person_id = insert_person(
        conn,
        Person(
            canonical_name=canonical_name,
            first_name=first_name,
            last_name=last_name,
            identifiers={"wa_filer_id": filer_id} if filer_id else {},
        ),
    )
    insert_entity_source(conn, "person", person_id, source_record_id, "candidate")
    return person_id


def _ingest_contribution_row(
    conn: psycopg.Connection,
    raw_row: dict[str, str | None],
    source_record_id: UUID,
) -> None:
    office_raw = normalize_optional_text(raw_row.get("office"))
    if office_raw is None:
        raise ValueError("Missing office field")

    election_year_raw = normalize_optional_text(raw_row.get("election_year"))
    if election_year_raw is None:
        raise ValueError("Missing election_year field")
    election_year = int(election_year_raw)

    filer_name = normalize_optional_text(raw_row.get("filer_name"))
    if filer_name is None:
        raise ValueError("Missing filer_name field")

    filer_id = normalize_optional_text(raw_row.get("filer_id"))
    legislative_district = normalize_optional_text(raw_row.get("legislative_district"))
    jurisdiction_county = normalize_optional_text(raw_row.get("jurisdiction_county"))
    jurisdiction = normalize_optional_text(raw_row.get("jurisdiction"))
    jurisdiction_type = normalize_optional_text(raw_row.get("jurisdiction_type"))
    party = normalize_optional_text(raw_row.get("party"))

    office_id = _resolve_office_id(office_raw, office_type=jurisdiction_type)
    if office_id is None:
        raise ValueError(f"Unknown office: {office_raw!r}")

    # Resolve electoral division
    division_id = _resolve_electoral_division(
        conn,
        office_id,
        legislative_district,
        jurisdiction_county,
        jurisdiction,
    )

    election_date = wa_general_election_date(election_year)

    # Resolve person
    person_id = _resolve_or_create_person(
        conn,
        filer_name,
        filer_id,
        source_record_id,
    )
    incumbent_challenge = derive_incumbent_challenge(
        conn,
        person_id,
        office_id,
        division_id,
        as_of=election_date,
    )

    # Create contest
    contest_name = f"WA {office_raw} General {election_year}"
    contest_id = upsert_contest(
        conn,
        Contest(
            name=contest_name,
            election_date=election_date,
            election_type="general",
            office_id=office_id,
            electoral_division_id=division_id,
            source_record_id=source_record_id,
        ),
    )

    # Create candidacy
    upsert_candidacy(
        conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            party=party,
            incumbent_challenge=incumbent_challenge,
            source_record_id=source_record_id,
        ),
    )


def load_wa_candidates_canonical(
    conn: psycopg.Connection,
    rows: Iterable[dict[str, str | None]],
    *,
    data_source_id: UUID,
    batch_size: int = 1000,
) -> LoadResult:
    """Load WA contribution/expenditure/loan rows into canonical civic.* tables.

    Only processes rows with type='Candidate'. Political Committee rows are skipped.
    """
    result = LoadResult()
    processed_since_commit = 0

    for raw_row in rows:
        row_type = normalize_optional_text(raw_row.get("type"))
        if row_type != "Candidate":
            result.skipped += 1
            continue

        row_id = normalize_optional_text(raw_row.get("id")) or "unknown"
        source_record_key = f"wa_canonical:{row_id}"
        source_record_id = _try_insert_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_fields=dict(raw_row),
        )
        if source_record_id is None:
            result.skipped += 1
            continue

        try:
            _ingest_contribution_row(conn, raw_row, source_record_id)
        except (ValueError, KeyError) as exc:
            LOGGER.warning("Skipping WA row %s: %s", row_id, exc)
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


def _upsert_ie_sponsor_contacts(
    conn: psycopg.Connection,
    raw_row: dict[str, str | None],
    source_record_id: UUID,
) -> None:
    """Find/create the IE sponsor org and upsert its email/phone contact points."""
    sponsor_name = normalize_optional_text(raw_row.get("sponsor_name"))
    if sponsor_name is None:
        return

    org_id = find_organization_by_canonical_name(conn, sponsor_name)
    if org_id is None:
        org_id = insert_organization(
            conn,
            Organization(canonical_name=sponsor_name),
        )
    insert_entity_source(conn, "organization", org_id, source_record_id, "ie_sponsor")

    sponsor_email = normalize_optional_text(raw_row.get("sponsor_email"))
    sponsor_phone = normalize_optional_text(raw_row.get("sponsor_phone"))

    if sponsor_email:
        upsert_contact_point(
            conn,
            ContactPoint(
                type="email",
                value_raw=sponsor_email,
                owner_type="organization",
                owner_id=org_id,
                role="ie_sponsor",
                source_record_id=source_record_id,
            ),
        )

    if sponsor_phone:
        upsert_contact_point(
            conn,
            ContactPoint(
                type="phone",
                value_raw=sponsor_phone,
                owner_type="organization",
                owner_id=org_id,
                role="ie_sponsor",
                source_record_id=source_record_id,
            ),
        )


def _ingest_ie_row(
    conn: psycopg.Connection,
    raw_row: dict[str, str | None],
    source_record_id: UUID,
) -> None:
    candidate_office_raw = normalize_optional_text(raw_row.get("candidate_office"))
    if candidate_office_raw is None:
        raise ValueError("Missing candidate_office field")

    candidate_office_type = normalize_optional_text(raw_row.get("candidate_office_type"))
    office_id = _resolve_office_id(candidate_office_raw, office_type=candidate_office_type)
    if office_id is None:
        raise ValueError(f"Unknown candidate_office: {candidate_office_raw!r}")

    election_year_raw = normalize_optional_text(raw_row.get("election_year"))
    if election_year_raw is None:
        raise ValueError("Missing election_year field")
    election_year = int(election_year_raw)

    candidate_name = normalize_optional_text(raw_row.get("candidate_name"))
    candidate_first = normalize_optional_text(raw_row.get("candidate_first_name"))
    candidate_last = normalize_optional_text(raw_row.get("candidate_last_name"))
    candidate_filer_id = normalize_optional_text(raw_row.get("candidate_filer_id"))
    if candidate_name is None and (candidate_first is None or candidate_last is None):
        raise ValueError("Missing candidate name fields")

    display_name = candidate_name or f"{candidate_last}, {candidate_first}"
    candidate_party = normalize_optional_text(raw_row.get("candidate_party"))
    candidate_jurisdiction = normalize_optional_text(raw_row.get("candidate_jurisdiction"))

    # Resolve electoral division
    division_id = _resolve_electoral_division(
        conn,
        office_id,
        None,
        None,
        candidate_jurisdiction,
    )

    election_date = wa_general_election_date(election_year)

    # Resolve candidate person
    person_id = _resolve_or_create_person(
        conn,
        display_name,
        filer_id=candidate_filer_id,
        source_record_id=source_record_id,
        first_name=candidate_first,
        last_name=candidate_last,
    )
    incumbent_challenge = derive_incumbent_challenge(
        conn,
        person_id,
        office_id,
        division_id,
        as_of=election_date,
    )

    # Create contest
    contest_name = f"WA {candidate_office_raw} General {election_year}"
    contest_id = upsert_contest(
        conn,
        Contest(
            name=contest_name,
            election_date=election_date,
            election_type="general",
            office_id=office_id,
            electoral_division_id=division_id,
            source_record_id=source_record_id,
        ),
    )

    # Create candidacy
    upsert_candidacy(
        conn,
        Candidacy(
            person_id=person_id,
            contest_id=contest_id,
            party=candidate_party,
            incumbent_challenge=incumbent_challenge,
            source_record_id=source_record_id,
        ),
    )

    # Extract sponsor contact points
    _upsert_ie_sponsor_contacts(conn, raw_row, source_record_id)


def load_wa_ie_canonical(
    conn: psycopg.Connection,
    rows: Iterable[dict[str, str | None]],
    *,
    data_source_id: UUID,
    batch_size: int = 1000,
) -> LoadResult:
    """Load WA independent-expenditure rows into canonical civic.* + contact_point tables."""
    result = LoadResult()
    processed_since_commit = 0

    for raw_row in rows:
        row_id = normalize_optional_text(raw_row.get("id")) or "unknown"
        source_record_key = f"wa_ie_canonical:{row_id}"
        source_record_id = _try_insert_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_fields=dict(raw_row),
        )
        if source_record_id is None:
            result.skipped += 1
            continue

        try:
            _ingest_ie_row(conn, raw_row, source_record_id)
        except (ValueError, KeyError) as exc:
            LOGGER.warning("Skipping WA IE row %s: %s", row_id, exc)
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
