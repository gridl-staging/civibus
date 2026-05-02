
from __future__ import annotations

import re
from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path

_ORGANIZATION_KEYWORDS = (
    " LLC",
    " LLP",
    " INC",
    " CORP",
    " COMPANY",
    " COMMITTEE",
    " ASSOCIATION",
    " FUND",
    " BANK",
    " PAC",
    " PARTY",
)


class ALContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class ALExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "name": _load_column_for_semantic_path("contributions", "donor.name"),
        "city_state": _load_column_for_semantic_path("contributions", "donor.address.city_state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "name": _load_column_for_semantic_path("expenditures", "payee.name"),
        "city_state": _load_column_for_semantic_path("expenditures", "payee.address.city_state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


def _normalized_text(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _normalize_state_code(state: str | None) -> str | None:
    text = _normalized_text(state)
    if text is None:
        return None
    upper = text.upper()
    if len(upper) != 2:
        return None
    return upper


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    text = _normalized_text(raw_zip)
    if not text:
        return None, None

    match = re.match(r"^(\d{5})(?:-(\d{4}))?", text)
    if match:
        return match.group(1), match.group(2)

    digits = "".join(c for c in text if c.isdigit())
    if len(digits) >= 5:
        zip5 = digits[:5]
        zip4 = digits[5:9] if len(digits) >= 9 else None
        return zip5, zip4

    return None, None


def _parse_city_state(city_state: str | None) -> tuple[str | None, str | None]:
    """Parse a combined 'CITY, ST' value into (city, state_code)."""
    text = _normalized_text(city_state)
    if text is None:
        return None, None

    if "," in text:
        parts = [p.strip() for p in text.rsplit(",", maxsplit=1)]
        city = _normalized_text(parts[0])
        state = _normalize_state_code(parts[1]) if len(parts) > 1 else None
        return city, state

    return text, None


def _build_address_from_city_state(
    city_state: str | None,
    raw_zip: str | None,
) -> Address | None:
    city, state = _parse_city_state(city_state)
    normalized_zip = _normalized_text(raw_zip)

    if not any((city, state, normalized_zip)):
        return None

    zip5, zip4 = _split_zip(normalized_zip)
    raw_parts = [p for p in (city, state, normalized_zip) if p]
    return Address(
        raw_address=", ".join(raw_parts),
        city=city,
        state=state,
        zip5=zip5,
        zip4=zip4,
    )


def _looks_like_organization_name(name: str) -> bool:
    upper_name = f" {name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True
    if "&" in name:
        return True
    if "," not in name and len(name.split()) == 1:
        return True
    return False


def _extract_committee(row: dict[str, str | None], fields: dict[str, str]) -> Organization:
    committee_name = _normalized_text(row.get(fields["committee_name"])) or "Unknown AL Committee"
    committee_id = _normalized_text(row.get(fields["committee_id"]))
    identifiers = {"al_org_id": committee_id} if committee_id is not None else {}

    return Organization(
        canonical_name=committee_name,
        identifiers=identifiers,
    )


def _extract_person_or_org_from_name(
    name_value: str | None,
) -> tuple[Person | None, Organization | None]:
    """Classify a single name field as person or organization."""
    text = _normalized_text(name_value)
    if text is None:
        return None, None

    if _looks_like_organization_name(text):
        return None, Organization(canonical_name=text)

    # Multi-word names are likely persons; try "FIRST MIDDLE LAST" parsing.
    words = text.split()
    if len(words) >= 2:
        return (
            Person(
                canonical_name=text,
                first_name=words[0],
                last_name=words[-1],
                middle_name=" ".join(words[1:-1]) if len(words) > 2 else None,
            ),
            None,
        )

    return None, Organization(canonical_name=text)


def extract_al_contribution(row: dict[str, str | None]) -> ALContributionExtraction:
    fields = _contribution_fields()
    donor_person, donor_org = _extract_person_or_org_from_name(row.get(fields["name"]))

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address_from_city_state(
            row.get(fields["city_state"]),
            row.get(fields["zip"]),
        ),
    }


def extract_al_expenditure(row: dict[str, str | None]) -> ALExpenditureExtraction:
    fields = _expenditure_fields()
    payee_person, payee_org = _extract_person_or_org_from_name(row.get(fields["name"]))

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address_from_city_state(
            row.get(fields["city_state"]),
            row.get(fields["zip"]),
        ),
    }
