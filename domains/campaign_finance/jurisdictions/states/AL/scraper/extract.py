"""Entity extraction helpers for AL rows.

Extracts Person, Organization, and Address entities from normalized
AL FCPA JSON rows, following the same patterns as NE extract.py.
"""

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
    """Map semantic roles to config-driven JSON field names for contributions."""
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "name": _load_column_for_semantic_path("contributions", "donor.org_name"),
        "first_name": _load_column_for_semantic_path("contributions", "donor.first_name"),
        "middle_name": _load_column_for_semantic_path("contributions", "donor.middle_name"),
        "last_name": _load_column_for_semantic_path("contributions", "donor.last_name"),
        "street1": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "street2": _load_column_for_semantic_path("contributions", "donor.address.street2"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    """Map semantic roles to config-driven JSON field names for expenditures."""
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "name": _load_column_for_semantic_path("expenditures", "payee.org_name"),
        "first_name": _load_column_for_semantic_path("expenditures", "payee.first_name"),
        "middle_name": _load_column_for_semantic_path("expenditures", "payee.middle_name"),
        "last_name": _load_column_for_semantic_path("expenditures", "payee.last_name"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "street2": _load_column_for_semantic_path("expenditures", "payee.address.street2"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


def _normalized_text(value: str | None) -> str | None:
    """Strip and return None for empty strings."""
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
    """Split a ZIP code into zip5 and optional zip4 components."""
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


def _build_address(
    street1: str | None,
    street2: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    """Build an Address entity from raw fields, returning None if all are empty."""
    normalized_street1 = _normalized_text(street1)
    normalized_street2 = _normalized_text(street2)
    normalized_city = _normalized_text(city)
    normalized_state = _normalize_state_code(state)
    normalized_zip = _normalized_text(raw_zip)

    if not any((normalized_street1, normalized_street2, normalized_city, normalized_state, normalized_zip)):
        return None

    zip5, zip4 = _split_zip(normalized_zip)
    raw_address = ", ".join(
        part
        for part in (normalized_street1, normalized_street2, normalized_city, normalized_state, normalized_zip)
        if part
    )
    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=zip5,
        zip4=zip4,
    )


def _looks_like_organization_name(name: str) -> bool:
    """Heuristic: detect organization-style names."""
    upper_name = f" {name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True
    if "&" in name:
        return True
    # Single-word names without comma are likely organizations.
    if "," not in name and len(name.split()) == 1:
        return True
    return False


def _extract_committee(row: dict[str, str | None], fields: dict[str, str]) -> Organization:
    """Extract the recipient committee as an Organization entity."""
    committee_name = _normalized_text(row.get(fields["committee_name"])) or "Unknown AL Committee"
    committee_id = _normalized_text(row.get(fields["committee_id"]))
    identifiers = {"al_org_id": committee_id} if committee_id is not None else {}

    return Organization(
        canonical_name=committee_name,
        identifiers=identifiers,
    )


def _extract_person_or_org(
    row: dict[str, str | None],
    *,
    name_column: str,
    first_name_column: str,
    middle_name_column: str,
    last_name_column: str,
) -> tuple[Person | None, Organization | None]:
    """Determine if a row's counterparty is a Person or Organization.

    AL data has separate firstName/lastName fields, so if firstName is
    present we treat it as a person. Otherwise we fall back to the
    sourceName/payeeName field and apply organization heuristics.
    """
    name_value = _normalized_text(row.get(name_column))
    first_name = _normalized_text(row.get(first_name_column))
    last_name = _normalized_text(row.get(last_name_column))
    middle_name = _normalized_text(row.get(middle_name_column))

    # If first_name is present, treat as person.
    if first_name is not None:
        canonical_parts = [part for part in (first_name, middle_name, last_name) if part]
        return (
            Person(
                canonical_name=" ".join(canonical_parts),
                first_name=first_name,
                middle_name=middle_name,
                last_name=last_name,
            ),
            None,
        )

    # No first name — check if the name field indicates a person or org.
    if name_value is None:
        return None, None

    if _looks_like_organization_name(name_value):
        return None, Organization(canonical_name=name_value)

    # Name with comma might be "Last, First" format.
    if "," in name_value:
        parts = [part.strip() for part in name_value.split(",", maxsplit=1)]
        last_part, first_part = parts[0], parts[1] if len(parts) > 1 else ""
        first_token = _normalized_text(first_part.split(" ")[0] if first_part else None)
        if first_token and last_part:
            return (
                Person(
                    canonical_name=name_value,
                    first_name=first_token,
                    last_name=last_part,
                ),
                None,
            )

    # Default: treat as organization.
    return None, Organization(canonical_name=name_value)


def extract_al_contribution(row: dict[str, str | None]) -> ALContributionExtraction:
    """Extract entities from an AL contribution row."""
    fields = _contribution_fields()
    donor_person, donor_org = _extract_person_or_org(
        row,
        name_column=fields["name"],
        first_name_column=fields["first_name"],
        middle_name_column=fields["middle_name"],
        last_name_column=fields["last_name"],
    )

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address(
            row.get(fields["street1"]),
            row.get(fields["street2"]),
            row.get(fields["city"]),
            row.get(fields["state"]),
            row.get(fields["zip"]),
        ),
    }


def extract_al_expenditure(row: dict[str, str | None]) -> ALExpenditureExtraction:
    """Extract entities from an AL expenditure row."""
    fields = _expenditure_fields()
    payee_person, payee_org = _extract_person_or_org(
        row,
        name_column=fields["name"],
        first_name_column=fields["first_name"],
        middle_name_column=fields["middle_name"],
        last_name_column=fields["last_name"],
    )

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address(
            row.get(fields["street1"]),
            row.get(fields["street2"]),
            row.get(fields["city"]),
            row.get(fields["state"]),
            row.get(fields["zip"]),
        ),
    }
