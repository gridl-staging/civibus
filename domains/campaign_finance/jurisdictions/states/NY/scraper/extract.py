"""Extract Person, Organization, and Address entities from NY SODA rows.

NY contribution rows have donor entity fields (flng_ent_*) and committee
fields (cand_comm_name, filer_id). Expenditure rows reuse the same field
names but the flng_ent_* fields represent the payee/vendor.

The cntrbr_type_desc field distinguishes individuals from organizations
on contributions. For expenditures, we heuristically classify based on
whether flng_ent_last_name is populated.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path

# NY contributor types that indicate an individual (not an organization).
_INDIVIDUAL_CONTRIBUTOR_TYPES = frozenset(
    {
        "Individual",
        "Candidate",
        "Family Member",
        "Candidate/Spouse",
        "Partner",
    }
)

# Organization keywords for heuristic fallback classification.
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
    " UNION",
    " TRUST",
)


class NYContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class NYExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    """Map semantic roles to CSV column names for contribution rows."""
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "donor_type": _load_column_for_semantic_path("contributions", "donor.type"),
        "donor_org_name": _load_column_for_semantic_path("contributions", "donor.org_name"),
        "donor_first": _load_column_for_semantic_path("contributions", "donor.first_name"),
        "donor_middle": _load_column_for_semantic_path("contributions", "donor.middle_name"),
        "donor_last": _load_column_for_semantic_path("contributions", "donor.last_name"),
        "donor_street": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "donor_city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "donor_state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "donor_zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    """Map semantic roles to CSV column names for expenditure rows."""
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "payee_org_name": _load_column_for_semantic_path("expenditures", "payee.org_name"),
        "payee_first": _load_column_for_semantic_path("expenditures", "payee.first_name"),
        "payee_middle": _load_column_for_semantic_path("expenditures", "payee.middle_name"),
        "payee_last": _load_column_for_semantic_path("expenditures", "payee.last_name"),
        "payee_street": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "payee_city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "payee_state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "payee_zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


def _normalized_text(value: str | None) -> str | None:
    """Strip whitespace and return None for empty strings."""
    if not value:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _normalize_state_code(state: str | None) -> str | None:
    """Uppercase two-letter state codes, return None for empty."""
    text = _normalized_text(state)
    if text is None:
        return None
    return text.upper()[:2]


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    """Split a raw ZIP into (zip5, zip4) components."""
    text = _normalized_text(raw_zip)
    if not text:
        return None, None
    # Handle "12345-6789" format.
    match = re.match(r"^(\d{5})(?:-(\d{4}))?", text)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _build_address(
    street: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    """Build an Address model from component fields.

    Address requires raw_address (a concatenation of all parts).
    Returns None if all fields are empty.
    """
    norm_street = _normalized_text(street)
    norm_city = _normalized_text(city)
    norm_state = _normalize_state_code(state)
    norm_zip = _normalized_text(raw_zip)

    if not any((norm_street, norm_city, norm_state, norm_zip)):
        return None

    zip5, zip4 = _split_zip(raw_zip)
    # Construct a raw_address string from available parts.
    raw_address = ", ".join(part for part in (norm_street, norm_city, norm_state, norm_zip) if part)

    return Address(
        raw_address=raw_address,
        city=norm_city,
        state=norm_state,
        zip5=zip5,
        zip4=zip4,
    )


def _build_committee(committee_name: str | None, committee_id: str | None) -> Organization:
    """Build an Organization for the filing committee."""
    canonical = _normalized_text(committee_name) or "Unknown Committee"
    identifiers: dict[str, str] = {}
    if committee_id:
        identifiers["ny_filer_id"] = committee_id.strip()
    return Organization(
        canonical_name=canonical,
        identifiers=identifiers,
    )


def _is_individual_by_contributor_type(contributor_type: str | None) -> bool | None:
    """Determine if the contributor is an individual based on cntrbr_type_desc.

    Returns True for individuals, False for known orgs, None if unknown/empty.
    """
    if not contributor_type:
        return None
    if contributor_type in _INDIVIDUAL_CONTRIBUTOR_TYPES:
        return True
    return False


def _is_org_name_heuristic(name: str | None) -> bool:
    """Heuristic: does the name look like an organization?"""
    if not name:
        return False
    upper = name.upper()
    return any(kw in upper for kw in _ORGANIZATION_KEYWORDS)


def _build_person(
    first_name: str | None,
    middle_name: str | None,
    last_name: str | None,
) -> Person | None:
    """Build a Person from name components. Returns None if no name available."""
    first = _normalized_text(first_name)
    last = _normalized_text(last_name)
    if not last:
        return None
    canonical = f"{first} {last}".strip() if first else last
    return Person(
        canonical_name=canonical,
        first_name=first,
        middle_name=_normalized_text(middle_name),
        last_name=last,
    )


def extract_ny_contribution(row: dict[str, str | None]) -> NYContributionExtraction:
    """Extract donor person/org, committee, and address from a contribution row."""
    fields = _contribution_fields()

    committee = _build_committee(row.get(fields["committee_name"]), row.get(fields["committee_id"]))

    # Donor classification: use cntrbr_type_desc first, then heuristic.
    contributor_type = row.get(fields["donor_type"])
    is_individual = _is_individual_by_contributor_type(contributor_type)

    first_name = row.get(fields["donor_first"])
    last_name = row.get(fields["donor_last"])
    org_name = row.get(fields["donor_org_name"])

    # If contributor type is ambiguous, fall back to field presence:
    # individuals have last_name populated; orgs use flng_ent_name.
    if is_individual is None:
        if last_name:
            is_individual = not _is_org_name_heuristic(last_name)
        elif org_name:
            is_individual = False

    donor_person: Person | None = None
    donor_org: Organization | None = None

    if is_individual:
        donor_person = _build_person(first_name, row.get(fields["donor_middle"]), last_name)
    else:
        name = _normalized_text(org_name) or _normalized_text(last_name)
        if name:
            donor_org = Organization(canonical_name=name)

    address = _build_address(
        row.get(fields["donor_street"]),
        row.get(fields["donor_city"]),
        row.get(fields["donor_state"]),
        row.get(fields["donor_zip"]),
    )

    return NYContributionExtraction(
        donor_person=donor_person,
        donor_org=donor_org,
        committee=committee,
        address=address,
    )


def extract_ny_expenditure(row: dict[str, str | None]) -> NYExpenditureExtraction:
    """Extract payee person/org, committee, and address from an expenditure row."""
    fields = _expenditure_fields()

    committee = _build_committee(row.get(fields["committee_name"]), row.get(fields["committee_id"]))

    first_name = row.get(fields["payee_first"])
    last_name = row.get(fields["payee_last"])
    org_name = row.get(fields["payee_org_name"])

    # Expenditures don't have cntrbr_type_desc — classify by field presence.
    payee_person: Person | None = None
    payee_org: Organization | None = None

    if last_name and not _is_org_name_heuristic(last_name):
        payee_person = _build_person(first_name, row.get(fields["payee_middle"]), last_name)
    else:
        name = _normalized_text(org_name) or _normalized_text(last_name)
        if name:
            payee_org = Organization(canonical_name=name)

    address = _build_address(
        row.get(fields["payee_street"]),
        row.get(fields["payee_city"]),
        row.get(fields["payee_state"]),
        row.get(fields["payee_zip"]),
    )

    return NYExpenditureExtraction(
        payee_person=payee_person,
        payee_org=payee_org,
        committee=committee,
        address=address,
    )
