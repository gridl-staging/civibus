
from __future__ import annotations

import re
from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path

_PERSON_TYPE_CODES = frozenset({"IND", "CAN"})
_ORGANIZATION_TYPE_CODES = frozenset({"BUS", "COM", "PAC", "PTY", "ORG", "ANO"})
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


class LAContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class LALoanExtraction(TypedDict):
    lender_person: Person | None
    lender_org: Organization | None
    committee: Organization
    address: Address | None


class LAExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "committee_first_name": _load_column_for_semantic_path("contributions", "la.filer_first_name"),
        "contributor_type": _load_column_for_semantic_path("contributions", "donor.type"),
        "name": _load_column_for_semantic_path("contributions", "donor.org_name"),
        "street1": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "street2": _load_column_for_semantic_path("contributions", "donor.address.street2"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _loan_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("loans", "committee.id"),
        "committee_name": _load_column_for_semantic_path("loans", "committee.name"),
        "committee_first_name": _load_column_for_semantic_path("loans", "la.filer_first_name"),
        "name": _load_column_for_semantic_path("loans", "donor.org_name"),
        "street1": _load_column_for_semantic_path("loans", "donor.address.street1"),
        "street2": _load_column_for_semantic_path("loans", "donor.address.street2"),
        "city": _load_column_for_semantic_path("loans", "donor.address.city"),
        "state": _load_column_for_semantic_path("loans", "donor.address.state"),
        "zip": _load_column_for_semantic_path("loans", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "committee_first_name": _load_column_for_semantic_path("expenditures", "la.filer_first_name"),
        "name": _load_column_for_semantic_path("expenditures", "payee.org_name"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "street2": _load_column_for_semantic_path("expenditures", "payee.address.street2"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
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

    digits = "".join(character for character in text if character.isdigit())
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
    upper_name = f" {name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True
    if "&" in name:
        return True
    if "/" in name:
        return True
    return False


def _build_committee_name(last_name: str | None, first_name: str | None) -> str:
    committee_last = _normalized_text(last_name)
    committee_first = _normalized_text(first_name)
    if committee_last:
        return committee_last
    if committee_first:
        return committee_first
    return "Unknown LA Committee"


def _extract_committee(row: dict[str, str | None], fields: dict[str, str]) -> Organization:
    committee_name = _build_committee_name(row.get(fields["committee_name"]), row.get(fields["committee_first_name"]))
    committee_id = _normalized_text(row.get(fields["committee_id"]))
    identifiers = {"la_filer_number": committee_id} if committee_id is not None else {}

    return Organization(
        canonical_name=committee_name,
        identifiers=identifiers,
    )


def _person_from_name(name_value: str) -> Person | None:
    normalized = _normalized_text(name_value)
    if normalized is None:
        return None

    if "," in normalized:
        last_name, first_name_segment = [part.strip() for part in normalized.split(",", maxsplit=1)]
        first_name = _normalized_text(first_name_segment.split(" ")[0] if first_name_segment else None)
        if first_name and last_name:
            return Person(canonical_name=normalized, first_name=first_name, last_name=last_name)
        return None

    tokens = [token for token in normalized.split() if token]
    if len(tokens) < 2:
        return None

    first_name = tokens[0]
    last_name = tokens[-1]
    middle_name = " ".join(tokens[1:-1]) or None
    return Person(
        canonical_name=normalized,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
    )


def _extract_contributor(
    name_value: str | None, contributor_type: str | None
) -> tuple[Person | None, Organization | None]:
    normalized_name = _normalized_text(name_value)
    normalized_type = (_normalized_text(contributor_type) or "").upper()
    if normalized_name is None:
        return None, None

    if normalized_type in _ORGANIZATION_TYPE_CODES:
        return None, Organization(canonical_name=normalized_name)

    if normalized_type in _PERSON_TYPE_CODES:
        person = _person_from_name(normalized_name)
        if person is not None:
            return person, None

    if _looks_like_organization_name(normalized_name):
        return None, Organization(canonical_name=normalized_name)

    person = _person_from_name(normalized_name)
    if person is not None:
        return person, None
    return None, Organization(canonical_name=normalized_name)


def _extract_loan_holder(name_value: str | None) -> tuple[Person | None, Organization | None]:
    normalized_name = _normalized_text(name_value)
    if normalized_name is None:
        return None, None

    if _looks_like_organization_name(normalized_name):
        return None, Organization(canonical_name=normalized_name)

    person = _person_from_name(normalized_name)
    if person is not None:
        return person, None
    return None, Organization(canonical_name=normalized_name)


def _extract_expenditure_payee(name_value: str | None) -> tuple[Person | None, Organization | None]:
    normalized_name = _normalized_text(name_value)
    if normalized_name is None:
        return None, None
    return None, Organization(canonical_name=normalized_name)


def extract_la_contribution(row: dict[str, str | None]) -> LAContributionExtraction:
    fields = _contribution_fields()
    donor_person, donor_org = _extract_contributor(row.get(fields["name"]), row.get(fields["contributor_type"]))

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


def extract_la_loan(row: dict[str, str | None]) -> LALoanExtraction:
    fields = _loan_fields()
    lender_person, lender_org = _extract_loan_holder(row.get(fields["name"]))

    return {
        "lender_person": lender_person,
        "lender_org": lender_org,
        "committee": _extract_committee(row, fields),
        "address": _build_address(
            row.get(fields["street1"]),
            row.get(fields["street2"]),
            row.get(fields["city"]),
            row.get(fields["state"]),
            row.get(fields["zip"]),
        ),
    }


def extract_la_expenditure(row: dict[str, str | None]) -> LAExpenditureExtraction:
    fields = _expenditure_fields()
    payee_person, payee_org = _extract_expenditure_payee(row.get(fields["name"]))

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
