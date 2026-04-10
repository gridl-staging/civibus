"""New Jersey campaign finance contribution extraction."""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path


class NJContributionExtraction(TypedDict):
    contributor_person: Person | None
    contributor_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    """Resolve NJ contribution CSV column names from config semantic paths."""
    return {
        "is_individual": _load_column_for_semantic_path("contributions", "donor.is_individual"),
        "first_name": _load_column_for_semantic_path("contributions", "donor.first_name"),
        "middle_initial": _load_column_for_semantic_path("contributions", "donor.middle_initial"),
        "last_name": _load_column_for_semantic_path("contributions", "donor.last_name"),
        "suffix": _load_column_for_semantic_path("contributions", "donor.suffix"),
        "org_name": _load_column_for_semantic_path("contributions", "donor.organization_name"),
        "street": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
        "employer": _load_column_for_semantic_path("contributions", "donor.employer"),
        "occupation": _load_column_for_semantic_path("contributions", "donor.occupation"),
        "contributor_type": _load_column_for_semantic_path("contributions", "donor.type"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
    }


def extract_nj_contribution(row: dict[str, str | None]) -> NJContributionExtraction:
    """Extract structured entities from one NJ contribution CSV row."""
    fields = _contribution_fields()

    is_individual = _normalized_text(row.get(fields["is_individual"]))
    individual = is_individual is not None and is_individual.lower() == "true"

    contributor_person: Person | None = None
    contributor_org: Organization | None = None

    if individual:
        contributor_person = _build_person(row, fields=fields)
    else:
        org_name = _normalized_text(row.get(fields["org_name"]))
        if org_name is not None:
            contributor_org = Organization(canonical_name=org_name)

    committee_name = _normalized_text(row.get(fields["committee_name"])) or ""
    committee = Organization(canonical_name=committee_name)

    address = _extract_address(
        street1=row.get(fields["street"]),
        city=row.get(fields["city"]),
        state=row.get(fields["state"]),
        raw_zip=row.get(fields["zip"]),
    )

    return {
        "contributor_person": contributor_person,
        "contributor_org": contributor_org,
        "committee": committee,
        "address": address,
    }


def _build_person(row: dict[str, str | None], *, fields: dict[str, str]) -> Person | None:
    """Build a Person from NJ structured name fields (FirstName/MI/LastName/Suffix)."""
    first_name = _normalized_text(row.get(fields["first_name"]))
    last_name = _normalized_text(row.get(fields["last_name"]))

    if first_name is None or last_name is None:
        return None

    middle_initial = _normalized_text(row.get(fields["middle_initial"]))
    suffix = _normalized_text(row.get(fields["suffix"]))

    name_parts = [first_name]
    if middle_initial:
        name_parts.append(middle_initial)
    name_parts.append(last_name)
    if suffix:
        name_parts.append(suffix)
    canonical_name = " ".join(name_parts)

    occupation = _normalized_text(row.get(fields["occupation"]))
    employer = _normalized_text(row.get(fields["employer"]))
    identifiers: dict[str, str] = {}
    if occupation:
        identifiers["occupation"] = occupation
    if employer:
        identifiers["employer"] = employer

    return Person(
        canonical_name=canonical_name,
        first_name=first_name,
        last_name=last_name,
        identifiers=identifiers,
    )


def _extract_address(
    *,
    street1: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    """Build an Address if any address component is present; return None otherwise."""
    normalized_street1 = _normalized_text(street1)
    normalized_city = _normalized_text(city)
    normalized_state = _normalize_state_code(state)
    normalized_zip = _normalize_zip5(raw_zip)

    if not any((normalized_street1, normalized_city, normalized_state, normalized_zip)):
        return None

    raw_address = ", ".join(
        part for part in (normalized_street1, normalized_city, normalized_state, normalized_zip) if part
    )

    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=normalized_zip,
    )


def _normalize_state_code(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    upper_value = normalized.upper()
    if len(upper_value) != 2:
        return None
    return upper_value


def _normalize_zip5(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    digits = "".join(c for c in normalized if c.isdigit())
    if len(digits) < 5:
        return None
    return digits[:5]


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized
