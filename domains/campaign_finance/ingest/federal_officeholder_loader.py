
from __future__ import annotations

import logging
from datetime import date
from uuid import UUID
from xml.etree import ElementTree

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
from domains.civics.types.models import ElectoralDivision, Officeholding

LOGGER = logging.getLogger(__name__)

# Deterministic seed UUIDs from domains/civics/schema/tables.sql
_OFFICE_US_HOUSE = UUID("00000000-0000-4000-8000-000000000101")
_OFFICE_US_SENATE = UUID("00000000-0000-4000-8000-000000000102")
_DIVISION_US_STATEWIDE = UUID("00000000-0000-4000-8000-000000000501")
_DIVISION_US_CONGRESSIONAL_DISTRICTS = UUID("00000000-0000-4000-8000-000000000504")

_VACANT_NAMES = frozenset({"VACANT", "VACANCY", ""})


def _text(node: ElementTree.Element, tag: str) -> str:
    value = node.findtext(tag)
    return "" if value is None else value.strip()


def _normalize_display_name(
    *,
    first_name: str,
    last_name: str,
    fallback_member_name: str,
) -> str:
    def _humanize(token: str) -> str:
        return token.title() if token.isupper() else token

    if first_name and last_name:
        return f"{_humanize(first_name)} {_humanize(last_name)}"
    if fallback_member_name:
        if "," in fallback_member_name:
            last_part, first_part = [part.strip() for part in fallback_member_name.split(",", 1)]
            if first_part and last_part:
                return f"{_humanize(first_part)} {_humanize(last_part)}"
        return fallback_member_name
    return " ".join(_humanize(part) for part in (first_name, last_name) if part).strip()


def _normalize_senate_class(raw_value: str) -> str:
    normalized = raw_value.strip().upper()
    if normalized in {"1", "2", "3"}:
        return normalized
    if normalized in {"CLASS I", "CLASS II", "CLASS III"}:
        return {"CLASS I": "1", "CLASS II": "2", "CLASS III": "3"}[normalized]
    return raw_value.strip()


def normalize_house_xml_rows(xml_text: str) -> list[dict[str, str | None]]:
    """Parse House Clerk XML into normalized row dictionaries.

    The return contract intentionally matches load_federal_house_officeholders() field keys
    so civics roster parsing can reuse this owner without implementing duplicate XML parsing.
    """
    root = ElementTree.fromstring(xml_text)
    rows: list[dict[str, str | None]] = []
    member_nodes = root.findall("./member")
    if not member_nodes:
        # House Clerk now wraps current members under a <members> node.
        member_nodes = root.findall("./members/member")
    for node in member_nodes:
        member_info = node.find("member-info")
        if member_info is None:
            first_name = _text(node, "first_name")
            last_name = _text(node, "last_name")
            fallback_member_name = _text(node, "member_name")
            state = _text(node, "state")
            district = _text(node, "district")
            party = _text(node, "party")
            phone = _text(node, "phone")
            office_building = _text(node, "office_building")
            office_room = _text(node, "office_room")
            office_zip = _text(node, "office_zip")
            elected_date = _text(node, "elected_date")
            sworn_date = _text(node, "sworn_date")
            bioguide_id = _text(node, "bioguide_id")
        else:
            first_name = _text(member_info, "firstname")
            last_name = _text(member_info, "lastname")
            fallback_member_name = _text(member_info, "namelist")
            state_node = member_info.find("state")
            state = ""
            if state_node is not None:
                state = (state_node.get("postal-code") or "").strip()
            if state == "":
                state = _text(member_info, "state")
            district = _text(member_info, "district")
            if district == "" or district.lower() == "at large":
                state_district = _text(node, "statedistrict")
                if len(state_district) >= 4:
                    district = state_district[2:]
            party = _text(member_info, "party")
            phone = _text(member_info, "phone")
            office_building = _text(member_info, "office-building")
            office_room = _text(member_info, "office-room")
            office_zip = _text(member_info, "office-zip")
            elected_node = member_info.find("elected-date")
            sworn_node = member_info.find("sworn-date")
            elected_date = (
                (elected_node.get("date") or "").strip()
                if elected_node is not None
                else _text(member_info, "elected-date")
            )
            sworn_date = (
                (sworn_node.get("date") or "").strip()
                if sworn_node is not None
                else _text(member_info, "sworn-date")
            )
            bioguide_id = _text(member_info, "bioguideID")

        member_name = _normalize_display_name(
            first_name=first_name,
            last_name=last_name,
            fallback_member_name=fallback_member_name,
        )
        rows.append(
            {
                "bioguide_id": bioguide_id,
                "member_name": member_name,
                "first_name": first_name,
                "last_name": last_name,
                "state": state,
                "district": district,
                "party": party,
                "phone": phone,
                "office_building": office_building,
                "office_room": office_room,
                "office_zip": office_zip,
                "elected_date": elected_date,
                "sworn_date": sworn_date,
            }
        )
    return rows


def normalize_senate_xml_rows(xml_text: str) -> list[dict[str, str | None]]:
    """Parse Senate contact XML into normalized row dictionaries."""
    root = ElementTree.fromstring(xml_text)
    rows: list[dict[str, str | None]] = []
    for node in root.findall("./member"):
        first_name = _text(node, "first_name")
        last_name = _text(node, "last_name")
        member_full = _normalize_display_name(
            first_name=first_name,
            last_name=last_name,
            fallback_member_name=_text(node, "member_full"),
        )
        rows.append(
            {
                "bioguide_id": _text(node, "bioguide_id"),
                "member_full": member_full,
                "first_name": first_name,
                "last_name": last_name,
                "state": _text(node, "state"),
                "party": _text(node, "party"),
                "class": _normalize_senate_class(_text(node, "class")),
                "phone": _text(node, "phone"),
                "email": _text(node, "email"),
                "website": _text(node, "website"),
                "address": _text(node, "address"),
                "appointed": _text(node, "appointed"),
            }
        )
    return rows


def _is_vacant(row: dict[str, str | None]) -> bool:
    """Check if a row represents a vacant seat."""
    name = (row.get("member_name") or row.get("member_full") or "").strip().upper()
    bioguide = (row.get("bioguide_id") or "").strip()
    return name in _VACANT_NAMES or not bioguide


def is_federal_officeholder_vacant(row: dict[str, str | None]) -> bool:
    """Public vacancy helper shared across federal owner consumers."""
    return _is_vacant(row)


def _house_term_window(sworn_date_str: str | None) -> ValidDateRange:
    """Compute House term [sworn_date, sworn_date + 2 years) aligned to Jan 3."""
    if not sworn_date_str:
        return ValidDateRange()
    try:
        sworn = date.fromisoformat(sworn_date_str)
    except ValueError:
        return ValidDateRange()
    # House terms end Jan 3 of the next odd year after swearing in
    end_year = sworn.year + 2 if sworn.year % 2 == 1 else sworn.year + 1
    return ValidDateRange(start_date=sworn, end_date=date(end_year, 1, 3))


def _resolve_house_division(
    conn: psycopg.Connection,
    state: str | None,
    district: str | None,
) -> UUID | None:
    if not state or not district:
        return None
    district_padded = district.zfill(2)
    state_lower = state.lower()
    name = f"{state_lower}_cd_{district_padded}"
    return upsert_electoral_division(
        conn,
        ElectoralDivision(
            name=name,
            division_type="congressional_district",
            state=state.upper(),
            district_number=district_padded,
            parent_id=_DIVISION_US_CONGRESSIONAL_DISTRICTS,
        ),
    )


def _resolve_senate_division(
    conn: psycopg.Connection,
    state: str | None,
) -> UUID | None:
    if not state:
        return None
    state_lower = state.lower()
    return upsert_electoral_division(
        conn,
        ElectoralDivision(
            name=state_lower,
            division_type="statewide",
            state=state.upper(),
            parent_id=_DIVISION_US_STATEWIDE,
        ),
    )


# ---------------------------------------------------------------------------
# House loader
# ---------------------------------------------------------------------------


def load_federal_house_officeholders(
    conn: psycopg.Connection,
    rows: list[dict[str, str | None]],
    *,
    data_source_id: UUID,
) -> LoadResult:
    result = LoadResult()

    for raw_row in rows:

        def _process_row() -> None:
            if _is_vacant(raw_row):
                # Retire any active officeholding for this seat before skipping
                state = (raw_row.get("state") or "").strip()
                district = (raw_row.get("district") or "").strip()
                if state and district:
                    division_id = _resolve_house_division(conn, state, district)
                    retire_officeholdings_for_vacancy(conn, _OFFICE_US_HOUSE, division_id)
                return

            bioguide_id = (raw_row.get("bioguide_id") or "").strip()
            first_name = (raw_row.get("first_name") or "").strip()
            last_name = (raw_row.get("last_name") or "").strip()
            state = (raw_row.get("state") or "").strip()
            district = (raw_row.get("district") or "").strip()
            phone = (raw_row.get("phone") or "").strip()
            sworn_date = (raw_row.get("sworn_date") or "").strip()

            source_record_id = insert_officeholder_source_record(
                conn,
                data_source_id=data_source_id,
                source_record_key=f"house:{bioguide_id}",
                raw_row=raw_row,
            )
            person_id = resolve_or_create_person_by_identifier(
                conn,
                identifier_key="bioguide_id",
                identifier_value=bioguide_id,
                first_name=first_name,
                last_name=last_name,
                source_record_id=source_record_id,
            )
            division_id = _resolve_house_division(conn, state, district)
            term = _house_term_window(sworn_date)
            upsert_officeholding(
                conn,
                Officeholding(
                    person_id=person_id,
                    office_id=_OFFICE_US_HOUSE,
                    electoral_division_id=division_id,
                    holder_status="elected",
                    valid_period=term,
                    date_precision="day" if term.start_date else "year",
                    source_record_id=source_record_id,
                ),
            )
            upsert_owned_contact_point(
                conn,
                cp_type="phone",
                value_raw=phone,
                owner_type="office",
                owner_id=_OFFICE_US_HOUSE,
                source_record_id=source_record_id,
            )

        if not run_officeholder_row(
            conn,
            logger=LOGGER,
            failure_message="Error ingesting House member row: %s",
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


# ---------------------------------------------------------------------------
# Senate loader
# ---------------------------------------------------------------------------


def load_federal_senate_officeholders(
    conn: psycopg.Connection,
    rows: list[dict[str, str | None]],
    *,
    data_source_id: UUID,
) -> LoadResult:
    result = LoadResult()

    for raw_row in rows:

        def _process_row() -> None:
            if _is_vacant(raw_row):
                state = (raw_row.get("state") or "").strip()
                senate_class = (raw_row.get("class") or "").strip()
                if state:
                    division_id = _resolve_senate_division(conn, state)
                    if senate_class:
                        retire_officeholdings_for_vacancy(
                            conn,
                            _OFFICE_US_SENATE,
                            division_id,
                            vacancy_source_filters={"class": senate_class},
                        )
                    else:
                        LOGGER.warning(
                            "Skipping Senate vacancy retirement for %s because class is missing",
                            state,
                        )
                return

            bioguide_id = (raw_row.get("bioguide_id") or "").strip()
            first_name = (raw_row.get("first_name") or "").strip()
            last_name = (raw_row.get("last_name") or "").strip()
            state = (raw_row.get("state") or "").strip()
            phone = (raw_row.get("phone") or "").strip()
            email = (raw_row.get("email") or "").strip()
            is_appointed = (raw_row.get("appointed") or "").strip().lower() == "true"

            source_record_id = insert_officeholder_source_record(
                conn,
                data_source_id=data_source_id,
                source_record_key=f"senate:{bioguide_id}",
                raw_row=raw_row,
            )
            person_id = resolve_or_create_person_by_identifier(
                conn,
                identifier_key="bioguide_id",
                identifier_value=bioguide_id,
                first_name=first_name,
                last_name=last_name,
                source_record_id=source_record_id,
            )
            division_id = _resolve_senate_division(conn, state)
            holder_status = "appointed" if is_appointed else "elected"
            oh_id = upsert_officeholding(
                conn,
                Officeholding(
                    person_id=person_id,
                    office_id=_OFFICE_US_SENATE,
                    electoral_division_id=division_id,
                    holder_status=holder_status,
                    valid_period=ValidDateRange(),
                    date_precision="year",
                    source_record_id=source_record_id,
                ),
            )
            upsert_owned_contact_point(
                conn,
                cp_type="phone",
                value_raw=phone,
                owner_type="office",
                owner_id=_OFFICE_US_SENATE,
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
            failure_message="Error ingesting Senate member row: %s",
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
