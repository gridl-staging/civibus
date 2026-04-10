
from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

import psycopg

from core.types.python.models import ValidDateRange
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.officeholder_contact import (
    insert_officeholder_source_record,
    resolve_or_create_person_by_identifier,
    run_officeholder_row,
    upsert_owned_contact_point,
)
from domains.civics.ingest import retire_officeholdings_for_vacancy, upsert_electoral_division, upsert_officeholding
from domains.civics.types.models import DivisionTypeLiteral, ElectoralDivision, Officeholding

LOGGER = logging.getLogger(__name__)

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
_OFFICE_WA_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000213")
_OFFICE_WA_STATE_HOUSE = UUID("00000000-0000-4000-8000-000000000212")
_DIVISION_WA_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000505")
_DIVISION_WA_HOUSE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000506")

_VACANT_NAMES = frozenset({"VACANT", "VACANCY", ""})


def _is_vacant(row: dict[str, str | None]) -> bool:
    """Check if a row represents a vacant seat."""
    name = (row.get("Name") or "").strip().upper()
    sponsor_id = (row.get("Id") or "").strip()
    return name in _VACANT_NAMES or not sponsor_id


def _current_biennium() -> ValidDateRange:
    """WA legislative terms follow the biennium (odd year to odd year).

    Returns the current biennium as a half-open date range.
    """
    year = date.today().year
    # Biennium starts in odd years
    start_year = year if year % 2 == 1 else year - 1
    # WA legislature convenes second Monday in January
    # Approximate: Jan 13 start, next biennium starts ~Jan 11 two years later
    return ValidDateRange(
        start_date=date(start_year, 1, 13),
        end_date=date(start_year + 2, 1, 11),
    )


def _resolve_agency(agency: str) -> tuple[UUID, DivisionTypeLiteral, UUID] | None:
    """Map agency string to (office_id, division_type, division_parent_id)."""
    agency_upper = agency.strip().upper()
    if agency_upper == "HOUSE":
        return (_OFFICE_WA_STATE_HOUSE, "state_legislative_lower", _DIVISION_WA_HOUSE_DISTRICTS)
    if agency_upper == "SENATE":
        return (_OFFICE_WA_STATE_SENATE, "state_legislative_upper", _DIVISION_WA_SENATE_DISTRICTS)
    return None


def _resolve_wa_division(
    conn: psycopg.Connection,
    division_type: DivisionTypeLiteral,
    division_parent_id: UUID,
    district: str,
) -> UUID | None:
    """Resolve a WA district string + agency info to an electoral division UUID."""
    if not district:
        return None
    district_padded = district.zfill(2)
    prefix = "hd" if division_type == "state_legislative_lower" else "sd"
    div_name = f"wa_{prefix}_{district_padded}"
    return upsert_electoral_division(
        conn,
        ElectoralDivision(
            name=div_name,
            division_type=division_type,
            state="WA",
            district_number=district_padded,
            parent_id=division_parent_id,
        ),
    )


def load_wa_officeholders(
    conn: psycopg.Connection,
    rows: list[dict[str, str | None]],
    *,
    data_source_id: UUID,
) -> LoadResult:
    result = LoadResult()
    biennium = _current_biennium()

    for raw_row in rows:
        skip_unknown_agency = False

        def _process_row() -> None:
            nonlocal skip_unknown_agency
            if _is_vacant(raw_row):
                agency = (raw_row.get("Agency") or "").strip()
                district = (raw_row.get("District") or "").strip()
                agency_info = _resolve_agency(agency)
                if agency_info is not None:
                    office_id, division_type, division_parent_id = agency_info
                    division_id = _resolve_wa_division(conn, division_type, division_parent_id, district)
                    if division_id is not None:
                        retire_officeholdings_for_vacancy(conn, office_id, division_id)
                return

            sponsor_id = (raw_row.get("Id") or "").strip()
            first_name = (raw_row.get("FirstName") or "").strip()
            last_name = (raw_row.get("LastName") or "").strip()
            agency = (raw_row.get("Agency") or "").strip()
            district = (raw_row.get("District") or "").strip()
            phone = (raw_row.get("Phone") or "").strip()
            email = (raw_row.get("Email") or "").strip()

            agency_info = _resolve_agency(agency)
            if agency_info is None:
                LOGGER.warning("Unknown Agency %r for sponsor %s", agency, sponsor_id)
                skip_unknown_agency = True
                return

            office_id, division_type, division_parent_id = agency_info
            source_record_id = insert_officeholder_source_record(
                conn,
                data_source_id=data_source_id,
                source_record_key=f"wa_sponsor:{sponsor_id}",
                raw_row=raw_row,
            )
            person_id = resolve_or_create_person_by_identifier(
                conn,
                identifier_key="wa_sponsor_id",
                identifier_value=sponsor_id,
                first_name=first_name,
                last_name=last_name,
                source_record_id=source_record_id,
            )
            division_id = _resolve_wa_division(conn, division_type, division_parent_id, district)
            oh_id = upsert_officeholding(
                conn,
                Officeholding(
                    person_id=person_id,
                    office_id=office_id,
                    electoral_division_id=division_id,
                    holder_status="elected",
                    valid_period=biennium,
                    date_precision="day",
                    source_record_id=source_record_id,
                ),
            )
            upsert_owned_contact_point(
                conn,
                cp_type="phone",
                value_raw=phone,
                owner_type="office",
                owner_id=office_id,
                source_record_id=source_record_id,
            )
            upsert_owned_contact_point(
                conn,
                cp_type="email",
                value_raw=email,
                owner_type="officeholding",
                owner_id=oh_id,
                source_record_id=source_record_id,
            )

        if not run_officeholder_row(
            conn,
            logger=LOGGER,
            failure_message="Error ingesting WA sponsor row: %s",
            raw_row=raw_row,
            operation=_process_row,
        ):
            result.errors += 1
            continue

        if _is_vacant(raw_row):
            result.skipped += 1
            continue

        if skip_unknown_agency:
            result.skipped += 1
            continue

        result.inserted += 1

    return result
