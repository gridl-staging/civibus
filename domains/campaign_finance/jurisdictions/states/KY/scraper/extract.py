
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


class KYContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class KYExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _load_optional_column_for_semantic_path(data_type: str, semantic_path: str) -> str | None:
    try:
        return _load_column_for_semantic_path(data_type, semantic_path)
    except RuntimeError:
        return None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str | None]:
    """Map semantic keys to actual CSV column names for contribution rows."""
    return {
        "committee_org_name": _load_optional_column_for_semantic_path("contributions", "ky.to_organization"),
        "committee_first_name": _load_optional_column_for_semantic_path(
            "contributions", "ky.committee_candidate_first_name"
        ),
        "committee_last_name": _load_optional_column_for_semantic_path(
            "contributions", "ky.committee_candidate_last_name"
        ),
        "name": _load_column_for_semantic_path("contributions", "donor.org_name"),
        "first_name": _load_column_for_semantic_path("contributions", "donor.first_name"),
        "last_name": _load_column_for_semantic_path("contributions", "donor.last_name"),
        "street1": _load_optional_column_for_semantic_path("contributions", "donor.address.street1"),
        "city": _load_optional_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_optional_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_optional_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str | None]:
    """Map semantic keys to actual CSV column names for expenditure rows."""
    return {
        "committee_org_name": _load_optional_column_for_semantic_path("expenditures", "ky.from_organization_name"),
        "committee_first_name": _load_optional_column_for_semantic_path(
            "expenditures", "ky.committee_candidate_first_name"
        ),
        "committee_last_name": _load_optional_column_for_semantic_path(
            "expenditures", "ky.committee_candidate_last_name"
        ),
        "name": _load_column_for_semantic_path("expenditures", "payee.org_name"),
        "first_name": _load_column_for_semantic_path("expenditures", "payee.first_name"),
        "last_name": _load_column_for_semantic_path("expenditures", "payee.last_name"),
        "street1": _load_optional_column_for_semantic_path("expenditures", "payee.address.street1"),
        "city": _load_optional_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_optional_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_optional_column_for_semantic_path("expenditures", "payee.address.zip"),
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
    # Must be exactly 2 uppercase letters (not FIPS numeric codes like "17")
    if len(upper) != 2 or not upper.isalpha():
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

    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 5:
        zip5 = digits[:5]
        zip4 = digits[5:9] if len(digits) >= 9 else None
        return zip5, zip4

    return None, None


def _build_address(
    street1: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    """Build an Address entity from KY CSV address fields.

    KY only has a single Address column (no street2), so we skip street2.
    """
    normalized_street1 = _normalized_text(street1)
    normalized_city = _normalized_text(city)
    normalized_state = _normalize_state_code(state)
    normalized_zip = _normalized_text(raw_zip)

    if not any((normalized_street1, normalized_city, normalized_state, normalized_zip)):
        return None

    zip5, zip4 = _split_zip(normalized_zip)
    raw_address = ", ".join(
        part for part in (normalized_street1, normalized_city, normalized_state, normalized_zip) if part
    )
    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=zip5,
        zip4=zip4,
    )


def _looks_like_organization_name(name: str) -> bool:
    """Heuristic: does this name look like an organization rather than a person?"""
    upper_name = f" {name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True
    if "&" in name:
        return True
    # Single-word names without commas are ambiguous; treat as org
    if "," not in name and len(name.split()) == 1:
        return True
    return False


def _committee_name_from_fields(row: dict[str, str | None], fields: dict[str, str | None]) -> str:
    organization_name = (
        _normalized_text(row.get(fields["committee_org_name"])) if fields["committee_org_name"] is not None else None
    )
    if organization_name is not None:
        return organization_name

    first_name = (
        _normalized_text(row.get(fields["committee_first_name"]))
        if fields["committee_first_name"] is not None
        else None
    )
    last_name = (
        _normalized_text(row.get(fields["committee_last_name"])) if fields["committee_last_name"] is not None else None
    )
    if first_name is not None and last_name is not None:
        return f"{first_name} {last_name}"
    if last_name is not None:
        return last_name
    if first_name is not None:
        return first_name
    return "Unknown KY Committee"


def _extract_committee(row: dict[str, str | None], fields: dict[str, str | None]) -> Organization:
    """Extract the receiving or paying committee as an Organization entity."""

    return Organization(
        canonical_name=_committee_name_from_fields(row, fields),
        identifiers={},
    )


def _extract_person_or_org(
    row: dict[str, str | None],
    *,
    name_column: str | None,
    first_name_column: str | None,
    last_name_column: str | None,
) -> tuple[Person | None, Organization | None]:
    """Determine if a row's counterparty is a Person or Organization.

    KY uses FirstName/LastName columns separately from the org-name column
    (ContributorName or VendorName). When FirstName and LastName are present,
    it's a person. When only the org-name column is present (and FirstName is
    empty), it's likely an organization.
    """
    name_value = _normalized_text(row.get(name_column)) if name_column is not None else None
    first_name = _normalized_text(row.get(first_name_column)) if first_name_column is not None else None
    last_name = _normalized_text(row.get(last_name_column)) if last_name_column is not None else None

    # If we have explicit first/last name fields, it's a person
    if first_name is not None and last_name is not None:
        canonical_name = f"{first_name} {last_name}"
        return (
            Person(
                canonical_name=canonical_name,
                first_name=first_name,
                last_name=last_name,
            ),
            None,
        )

    # Only first_name without last_name (rare edge case)
    if first_name is not None:
        return (
            Person(
                canonical_name=first_name,
                first_name=first_name,
                last_name=None,
            ),
            None,
        )

    # Fall back to the org-name column
    if name_value is None:
        return None, None

    if _looks_like_organization_name(name_value):
        return None, Organization(canonical_name=name_value)

    # Name with comma likely "Last, First" format
    if "," in name_value:
        last_part, first_part = [part.strip() for part in name_value.split(",", maxsplit=1)]
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

    # Ambiguous: default to org
    return None, Organization(canonical_name=name_value)


def extract_ky_contribution(row: dict[str, str | None]) -> KYContributionExtraction:
    """Extract entities from a KY contribution row."""
    fields = _contribution_fields()
    donor_person, donor_org = _extract_person_or_org(
        row,
        name_column=fields["name"],
        first_name_column=fields["first_name"],
        last_name_column=fields["last_name"],
    )

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address(
            row.get(fields["street1"]) if fields["street1"] is not None else None,
            row.get(fields["city"]) if fields["city"] is not None else None,
            row.get(fields["state"]) if fields["state"] is not None else None,
            row.get(fields["zip"]) if fields["zip"] is not None else None,
        ),
    }


def extract_ky_expenditure(row: dict[str, str | None]) -> KYExpenditureExtraction:
    """Extract entities from a KY expenditure row."""
    fields = _expenditure_fields()
    payee_person, payee_org = _extract_person_or_org(
        row,
        name_column=fields["name"],
        first_name_column=fields["first_name"],
        last_name_column=fields["last_name"],
    )

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address(
            row.get(fields["street1"]) if fields["street1"] is not None else None,
            row.get(fields["city"]) if fields["city"] is not None else None,
            row.get(fields["state"]) if fields["state"] is not None else None,
            row.get(fields["zip"]) if fields["zip"] is not None else None,
        ),
    }
