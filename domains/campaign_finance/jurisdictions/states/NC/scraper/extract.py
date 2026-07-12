"""
Stub summary for MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/extract.py.
"""

from __future__ import annotations

import re
from typing import TypedDict

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.normalize.names import parse_name

from .parse import classify_transction_type

_LEADING_STREET_NUMBER_PATTERN = re.compile(r"^\s*(\d+)")
_normalized_text = normalize_optional_text


class NCTransactionExtraction(TypedDict):
    person: Person | None
    committee: Organization
    contributor_org: Organization | None
    address: Address | None


def extract_person(row: dict[str, str | None]) -> Person | None:
    if classify_transction_type(row.get("Transction Type")) != "person":
        return None

    parsed_name = parse_name(_normalized_text(row.get("Name")))
    if parsed_name.first is None and parsed_name.last is None:
        return None

    return Person(
        canonical_name=_build_title_cased_name(
            parsed_name.first,
            parsed_name.middle,
            parsed_name.last,
            parsed_name.suffix,
        ),
        first_name=parsed_name.first,
        middle_name=parsed_name.middle,
        last_name=parsed_name.last,
        suffix=parsed_name.suffix,
        identifiers=_build_person_identifiers(row),
    )


def extract_committee(row: dict[str, str | None]) -> Organization:
    committee_id = _normalized_text(row.get("Committee SBoE ID"))

    return Organization(
        canonical_name=_normalized_text(row.get("Committee Name")) or "",
        identifiers={"nc_sboe_id": committee_id} if committee_id is not None else {},
    )


def extract_contributor_org(row: dict[str, str | None]) -> Organization | None:
    if classify_transction_type(row.get("Transction Type")) != "organization":
        return None

    contributor_name = _normalized_text(row.get("Name"))
    if contributor_name is None:
        return None

    return Organization(canonical_name=contributor_name)


def extract_address(row: dict[str, str | None]) -> Address | None:
    city = _normalized_text(row.get("City"))
    state = _normalize_state_code(row.get("State"))
    if city is None and state is None:
        return None

    street_line_1 = _normalized_text(row.get("Street Line 1"))
    street_line_2 = _normalized_text(row.get("Street Line 2"))
    raw_zip = _normalized_text(row.get("Zip Code"))
    zip5, zip4 = _split_zip(raw_zip)

    raw_address = ", ".join(part for part in (street_line_1, street_line_2, city, state, raw_zip) if part is not None)

    return Address(
        raw_address=raw_address,
        city=city,
        state=state,
        zip5=zip5,
        zip4=zip4,
        street_number=_extract_street_number(street_line_1),
    )


def extract_nc_transaction(row: dict[str, str | None]) -> NCTransactionExtraction:
    return {
        "person": extract_person(row),
        "committee": extract_committee(row),
        "contributor_org": extract_contributor_org(row),
        "address": extract_address(row),
    }


def _build_title_cased_name(*name_parts: str | None) -> str:
    return " ".join(part for part in name_parts if part is not None).title()


def _build_person_identifiers(row: dict[str, str | None]) -> dict[str, str]:
    identifier_fields = {
        "occupation": row.get("Profession/Job Title"),
        "employer": row.get("Employer's Name/Specific Field"),
    }

    return {
        key: normalized_value
        for key, value in identifier_fields.items()
        if (normalized_value := _normalized_text(value)) is not None
    }


def _normalize_state_code(raw: str | None) -> str | None:
    normalized = _normalized_text(raw)
    if normalized is None:
        return None

    return normalized.upper()


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5, zip4 = normalized_zip.split("-", maxsplit=1)
        normalized_zip5 = _normalized_text(zip5)
        if normalized_zip5 is None:
            return None, None
        normalized_zip4 = _normalized_text(zip4)
        if normalized_zip4 == "9999":
            normalized_zip4 = None
        return normalized_zip5, normalized_zip4

    return normalized_zip, None


def _extract_street_number(street_line_1: str | None) -> str | None:
    if street_line_1 is None:
        return None

    match = _LEADING_STREET_NUMBER_PATTERN.match(street_line_1)
    if match is None:
        return None

    return match.group(1)
