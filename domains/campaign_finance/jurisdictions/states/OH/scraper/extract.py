"""Ohio campaign finance entity extraction.

Extracts Person, Organization, and Address entities from parsed OH CSV rows.
All column names are derived from config.yaml via _load_column_for_semantic_path()
— no hardcoded OH column names in this module.

OH-specific differences from TX:
- Entity/individual routing is implicit via NON_INDIVIDUAL field presence
  (no explicit type flag column like TX's contributorPersentTypeCd).
- OH has MIDDLE_NAME field — included in Person.middle_name and canonical_name.
- EMP_OCCUPATION (employer/occupation) is handled in load.py, not here
  (matching TX pattern where _counterparty_employer reads from the row directly).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path


class OHContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class OHExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    """Map logical field names to actual CSV column names for contributions."""
    return {
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "donor_first": _load_column_for_semantic_path("contributions", "donor.name.first"),
        "donor_middle": _load_column_for_semantic_path("contributions", "donor.name.middle"),
        "donor_last": _load_column_for_semantic_path("contributions", "donor.name.last"),
        "donor_suffix": _load_column_for_semantic_path("contributions", "donor.name.suffix"),
        "donor_org_name": _load_column_for_semantic_path("contributions", "donor.name.organization"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
        "street1": _load_column_for_semantic_path("contributions", "donor.address.street1"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    """Map logical field names to actual CSV column names for expenditures."""
    return {
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "payee_first": _load_column_for_semantic_path("expenditures", "payee.name.first"),
        "payee_middle": _load_column_for_semantic_path("expenditures", "payee.name.middle"),
        "payee_last": _load_column_for_semantic_path("expenditures", "payee.name.last"),
        "payee_suffix": _load_column_for_semantic_path("expenditures", "payee.name.suffix"),
        "payee_org_name": _load_column_for_semantic_path("expenditures", "payee.name.organization"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
    }


def extract_oh_contribution(row: dict[str, str | None]) -> OHContributionExtraction:
    """Extract entities from an OH contribution row."""
    fields = _contribution_fields()

    # OH entity routing: if NON_INDIVIDUAL is populated, treat as organization;
    # otherwise build person from split name fields (no explicit type flag column).
    org_name = _normalized_text(row.get(fields["donor_org_name"]))

    donor_person = None
    donor_org = None
    if org_name is not None:
        donor_org = _organization_from_name(org_name)
    else:
        donor_person = _person_from_split_name(
            first_name=row.get(fields["donor_first"]),
            middle_name=row.get(fields["donor_middle"]),
            last_name=row.get(fields["donor_last"]),
            suffix=row.get(fields["donor_suffix"]),
        )

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_oh_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_oh_expenditure(row: dict[str, str | None]) -> OHExpenditureExtraction:
    """Extract entities from an OH expenditure row."""
    fields = _expenditure_fields()

    org_name = _normalized_text(row.get(fields["payee_org_name"]))

    payee_person = None
    payee_org = None
    if org_name is not None:
        payee_org = _organization_from_name(org_name)
    else:
        payee_person = _person_from_split_name(
            first_name=row.get(fields["payee_first"]),
            middle_name=row.get(fields["payee_middle"]),
            last_name=row.get(fields["payee_last"]),
            suffix=row.get(fields["payee_suffix"]),
        )

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_oh_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def _extract_oh_committee(row: dict[str, str | None], *, fields: dict[str, str]) -> Organization:
    """Build committee Organization with oh_committee_id from MASTER_KEY."""
    committee_name = _normalized_text(row.get(fields["committee_name"])) or ""
    committee_id = _normalized_text(row.get(fields["committee_id"]))

    identifiers = {"oh_committee_id": committee_id} if committee_id is not None else {}
    return Organization(canonical_name=committee_name, identifiers=identifiers)


def _person_from_split_name(
    *,
    first_name: str | None,
    middle_name: str | None,
    last_name: str | None,
    suffix: str | None,
) -> Person | None:
    """Build Person from split OH name fields, including middle_name.

    OH-specific extension of the TX pattern: accepts middle_name parameter
    and includes it in both Person.middle_name and canonical_name construction.
    """
    normalized_first = _normalized_text(first_name)
    normalized_last = _normalized_text(last_name)
    if normalized_first is None or normalized_last is None:
        return None

    normalized_middle = _normalized_text(middle_name)
    normalized_suffix = _normalized_text(suffix)
    canonical_name = " ".join(
        part for part in (normalized_first, normalized_middle, normalized_last, normalized_suffix) if part
    )

    return Person(
        canonical_name=canonical_name,
        first_name=normalized_first,
        middle_name=normalized_middle,
        last_name=normalized_last,
        suffix=normalized_suffix,
    )


def _organization_from_name(name: str | None) -> Organization | None:
    """Build Organization from a single name string."""
    canonical_name = _normalized_text(name)
    if canonical_name is None:
        return None
    return Organization(canonical_name=canonical_name)


def _extract_address(
    *,
    street1: str | None = None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    """Build Address from OH address fields."""
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


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    """Split zip code into zip5 and optional zip4 components."""
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5, zip4 = normalized_zip.split("-", maxsplit=1)
        return _normalized_digits(zip5), _normalized_digits(zip4)

    return _normalized_digits(normalized_zip), None


def _normalized_digits(value: str | None) -> str | None:
    """Extract only digit characters from a string."""
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    digits = "".join(character for character in normalized_value if character.isdigit())
    if not digits:
        return None
    return digits


def _normalize_state_code(value: str | None) -> str | None:
    """Normalize a 2-letter state code to uppercase."""
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    upper_value = normalized_value.upper()
    if len(upper_value) != 2:
        return None
    return upper_value


def _normalized_text(value: str | None) -> str | None:
    """Strip whitespace and return None for empty strings."""
    if value is None:
        return None
    stripped_value = value.strip()
    return stripped_value or None
