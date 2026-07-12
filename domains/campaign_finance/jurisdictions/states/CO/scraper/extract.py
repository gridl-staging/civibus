"""
Stub summary for MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/CO/scraper/extract.py.
"""

from __future__ import annotations

import re
from typing import TypedDict

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.normalize.addresses import is_valid_zip5

from .parse import parse_contributor_type


_LEADING_STREET_NUMBER_PATTERN = re.compile(r"^\s*(\d+)")


class COContributionExtraction(TypedDict):
    person: Person | None
    committee: Organization
    contributor_org: Organization | None
    address: Address | None


class COExpenditureExtraction(TypedDict):
    payee_person: Person | None
    committee: Organization
    payee_org: Organization | None
    address: Address | None


def extract_person(row: dict[str, str | None]) -> Person | None:
    contributor_type, llc_name = parse_contributor_type(_normalized_text(row.get("ContributorType")))
    name_parts = _normalized_person_name_parts(row)
    last_name = name_parts[2]

    if contributor_type != "Individual" or last_name is None:
        return None

    return _person_from_name_parts(name_parts, _build_person_identifiers(row, llc_name))


def extract_committee(row: dict[str, str | None]) -> Organization:
    committee_name = _normalized_text(row.get("CommitteeName")) or ""
    committee_type = _normalized_text(row.get("CommitteeType"))

    return Organization(
        canonical_name=committee_name,
        org_type=committee_type.lower() if committee_type is not None else None,
        identifiers=_build_committee_identifiers(row.get("CO_ID")),
    )


def extract_contributor_org(row: dict[str, str | None]) -> Organization | None:
    contributor_type, _ = parse_contributor_type(_normalized_text(row.get("ContributorType")))
    if contributor_type == "Individual":
        return None

    return _organization_from_canonical_name(_normalized_text(row.get("LastName")))


def extract_address(row: dict[str, str | None]) -> Address | None:
    city = _normalized_text(row.get("City"))
    state = _normalize_state_code(row.get("State"))
    if not _has_text(city) and not _has_text(state):
        return None

    address1 = _normalized_text(row.get("Address1"))
    address2 = _normalized_text(row.get("Address2"))
    raw_zip = _normalized_text(row.get("Zip"))
    zip5, zip4 = _split_zip(raw_zip)

    raw_address = ", ".join(part for part in (address1, address2, city, state, raw_zip) if _has_text(part))

    return Address(
        raw_address=raw_address,
        city=city,
        state=state,
        zip5=zip5,
        zip4=zip4,
        street_number=_extract_street_number(address1),
    )


def extract_co_contribution(row: dict[str, str | None]) -> COContributionExtraction:
    return {
        "person": extract_person(row),
        "committee": extract_committee(row),
        "contributor_org": extract_contributor_org(row),
        "address": extract_address(row),
    }


def extract_expenditure_payee_person(row: dict[str, str | None]) -> Person | None:
    name_parts = _normalized_person_name_parts(row)
    if name_parts[0] is None:
        return None

    return _person_from_name_parts(name_parts, {})


def extract_expenditure_payee_org(row: dict[str, str | None]) -> Organization | None:
    if _has_text(row.get("FirstName")):
        return None

    return _organization_from_canonical_name(_normalized_text(row.get("LastName")))


def extract_co_expenditure(row: dict[str, str | None]) -> COExpenditureExtraction:
    return {
        "payee_person": extract_expenditure_payee_person(row),
        "committee": extract_committee(row),
        "payee_org": extract_expenditure_payee_org(row),
        "address": extract_address(row),
    }


def _build_title_cased_name(*parts: str | None) -> str:
    return " ".join(_normalized_text(part) for part in parts if _has_text(part)).title()


def _person_from_name_parts(
    name_parts: tuple[str | None, str | None, str | None, str | None],
    identifiers: dict[str, str],
) -> Person:
    first_name, middle_name, last_name, suffix = name_parts
    return Person(
        canonical_name=_build_title_cased_name(first_name, middle_name, last_name, suffix),
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        suffix=suffix,
        identifiers=identifiers,
    )


def _normalized_person_name_parts(
    row: dict[str, str | None],
) -> tuple[str | None, str | None, str | None, str | None]:
    return (
        _normalized_text(row.get("FirstName")),
        _normalized_text(row.get("MI")),
        _normalized_text(row.get("LastName")),
        _normalized_text(row.get("Suffix")),
    )


def _build_person_identifiers(row: dict[str, str | None], llc_name: str | None) -> dict[str, str]:
    identifier_fields = {
        "employer": row.get("Employer"),
        "occupation": row.get("Occupation"),
        "occupation_comments": row.get("OccupationComments"),
        "llc_name": llc_name,
    }

    return {
        key: normalized_value
        for key, value in identifier_fields.items()
        if (normalized_value := _normalized_text(value)) is not None
    }


def _organization_from_canonical_name(canonical_name: str | None) -> Organization | None:
    if canonical_name is None:
        return None

    return Organization(canonical_name=canonical_name)


def _has_text(value: str | None) -> bool:
    return _normalized_text(value) is not None


def _build_committee_identifiers(committee_id: str | None) -> dict[str, str]:
    normalized_committee_id = _normalized_text(committee_id)
    if normalized_committee_id is None:
        return {}

    return {"co_committee_id": normalized_committee_id}


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None

    stripped_value = value.strip()
    return stripped_value or None


def _normalize_state_code(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None

    return normalized_value.upper()


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5, zip4 = normalized_zip.split("-", maxsplit=1)
        zip5 = _normalized_text(zip5)
        return zip5 if is_valid_zip5(zip5) else None, _normalized_text(zip4)

    return normalized_zip if is_valid_zip5(normalized_zip) else None, None


def _extract_street_number(address1: str | None) -> str | None:
    if not _has_text(address1):
        return None

    match = _LEADING_STREET_NUMBER_PATTERN.match(address1)
    if match is None:
        return None

    return match.group(1)
