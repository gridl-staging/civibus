
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
from domains.civics.types.models import ElectoralDivision, Officeholding, OfficeholdingStatusLiteral

LOGGER = logging.getLogger(__name__)

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
_OFFICE_FL_STATE_SENATE = UUID("00000000-0000-4000-8000-000000000311")
_DIVISION_FL_SENATE_DISTRICTS = UUID("00000000-0000-4000-8000-000000000511")

_VACANT_NAMES = frozenset({"VACANT", "VACANCY", ""})

# FL Senate status → holder_status mapping
_STATUS_MAP: dict[str, OfficeholdingStatusLiteral] = {
    "active": "elected",
    "acting": "acting",
    "appointed": "appointed",
    "resigned": "former",
    "died": "former",
    "removed": "former",
    "expired": "former",
}


def _is_vacant(row: dict[str, str | None]) -> bool:
    """Check if a row represents a vacant seat."""
    name = (row.get("name") or "").strip().upper()
    status = (row.get("status") or "").strip().lower()
    senator_id = (row.get("senator_id") or "").strip()
    return name in _VACANT_NAMES or status == "vacant" or not senator_id


def _resolve_holder_status(status: str) -> OfficeholdingStatusLiteral:
    """Map FL Senate roster status to officeholding holder_status."""
    return _STATUS_MAP.get(status.strip().lower(), "elected")


def _resolve_term_window(term_start: str | None, term_end: str | None) -> ValidDateRange:
    """Compute FL Senate term window from year strings.

    FL Senate terms typically run from November of the start year to
    November of the end year.
    """
    if not term_start or not term_end:
        return ValidDateRange()
    try:
        start_year = int(term_start)
        end_year = int(term_end)
    except ValueError:
        return ValidDateRange()
    # FL senators take office after the November general election
    return ValidDateRange(
        start_date=date(start_year, 11, 1),
        end_date=date(end_year, 11, 1),
    )


def _resolve_fl_senate_division(
    conn: psycopg.Connection,
    district: str,
) -> UUID | None:
    """Resolve a FL Senate district string to an electoral division UUID."""
    if not district:
        return None
    district_padded = district.zfill(2)
    div_name = f"fl_sd_{district_padded}"
    return upsert_electoral_division(
        conn,
        ElectoralDivision(
            name=div_name,
            division_type="state_legislative_upper",
            state="FL",
            district_number=district_padded,
            parent_id=_DIVISION_FL_SENATE_DISTRICTS,
        ),
    )


def load_fl_senate_officeholders(
    conn: psycopg.Connection,
    rows: list[dict[str, str | None]],
    *,
    data_source_id: UUID,
) -> LoadResult:
    result = LoadResult()

    for raw_row in rows:

        def _process_row() -> None:
            if _is_vacant(raw_row):
                district = (raw_row.get("district") or "").strip()
                division_id = _resolve_fl_senate_division(conn, district)
                if division_id is not None:
                    retire_officeholdings_for_vacancy(conn, _OFFICE_FL_STATE_SENATE, division_id)
                return

            senator_id = (raw_row.get("senator_id") or "").strip()
            first_name = (raw_row.get("first_name") or "").strip()
            last_name = (raw_row.get("last_name") or "").strip()
            district = (raw_row.get("district") or "").strip()
            status = (raw_row.get("status") or "active").strip()
            term_start = (raw_row.get("term_start") or "").strip()
            term_end = (raw_row.get("term_end") or "").strip()
            district_phone = (raw_row.get("district_phone") or "").strip()
            tallahassee_phone = (raw_row.get("tallahassee_phone") or "").strip()

            source_record_id = insert_officeholder_source_record(
                conn,
                data_source_id=data_source_id,
                source_record_key=f"fl_senator:{senator_id}",
                raw_row=raw_row,
            )
            person_id = resolve_or_create_person_by_identifier(
                conn,
                identifier_key="fl_senator_id",
                identifier_value=senator_id,
                first_name=first_name,
                last_name=last_name,
                source_record_id=source_record_id,
            )
            division_id = _resolve_fl_senate_division(conn, district)
            term = _resolve_term_window(term_start, term_end)
            holder_status = _resolve_holder_status(status)
            upsert_officeholding(
                conn,
                Officeholding(
                    person_id=person_id,
                    office_id=_OFFICE_FL_STATE_SENATE,
                    electoral_division_id=division_id,
                    holder_status=holder_status,
                    valid_period=term,
                    date_precision="year" if term.start_date else "year",
                    source_record_id=source_record_id,
                ),
            )
            upsert_owned_contact_point(
                conn,
                cp_type="phone",
                value_raw=district_phone,
                owner_type="office",
                owner_id=_OFFICE_FL_STATE_SENATE,
                role="district",
                source_record_id=source_record_id,
            )
            upsert_owned_contact_point(
                conn,
                cp_type="phone",
                value_raw=tallahassee_phone,
                owner_type="office",
                owner_id=_OFFICE_FL_STATE_SENATE,
                role="capitol",
                source_record_id=source_record_id,
            )

        if not run_officeholder_row(
            conn,
            logger=LOGGER,
            failure_message="Error ingesting FL senator row: %s",
            raw_row=raw_row,
            operation=_process_row,
        ):
            result.errors += 1
            continue

        if _is_vacant(raw_row):
            result.skipped += 1
            continue

        result.inserted += 1

    return result
