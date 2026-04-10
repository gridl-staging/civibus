
from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path

_ORGANIZATION_KEYWORDS = (
    " ASSN",
    " ASSOCIATION",
    " CLUB",
    " CO",
    " COMMITTEE",
    " CORP",
    " FUND",
    " INC",
    " LLC",
    " LP",
    " PAC",
    " PARTY",
    " UNION",
)


class ILContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class ILExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "last_or_business": _load_column_for_semantic_path("contributions", "donor.name.last_or_business"),
        "first_name": _load_column_for_semantic_path("contributions", "donor.name.first"),
        "occupation": _load_column_for_semantic_path("contributions", "donor.occupation"),
        "employer": _load_column_for_semantic_path("contributions", "donor.employer"),
        "street1": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "street2": _load_column_for_semantic_path("contributions", "donor.address.street2"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "last_or_business": _load_column_for_semantic_path("expenditures", "payee.name.last_or_business"),
        "first_name": _load_column_for_semantic_path("expenditures", "payee.name.first"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "street2": _load_column_for_semantic_path("expenditures", "payee.address.street2"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


def extract_il_contribution(row: dict[str, str | None]) -> ILContributionExtraction:
    fields = _contribution_fields()
    last_or_business = _normalized_text(row.get(fields["last_or_business"]))
    first_name = _normalized_text(row.get(fields["first_name"]))

    donor_person: Person | None = None
    donor_org: Organization | None = None
    if _is_person_name(last_or_business, first_name):
        donor_person = _person_from_split_name(
            first_name=first_name,
            last_name=last_or_business,
            identifiers={
                "occupation": row.get(fields["occupation"]),
                "employer": row.get(fields["employer"]),
            },
        )
    elif last_or_business is not None:
        donor_org = Organization(canonical_name=last_or_business)

    committee_id = _normalized_text(row.get(fields["committee_id"])) or ""
    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": Organization(
            canonical_name=f"IL Committee {committee_id}" if committee_id else "IL Committee",
            identifiers={"il_committee_id": committee_id} if committee_id else {},
        ),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_il_expenditure(row: dict[str, str | None]) -> ILExpenditureExtraction:
    fields = _expenditure_fields()
    last_or_business = _normalized_text(row.get(fields["last_or_business"]))
    first_name = _normalized_text(row.get(fields["first_name"]))

    payee_person: Person | None = None
    payee_org: Organization | None = None
    if _is_person_name(last_or_business, first_name):
        payee_person = _person_from_split_name(first_name=first_name, last_name=last_or_business, identifiers={})
    elif last_or_business is not None:
        payee_org = Organization(canonical_name=last_or_business)

    committee_id = _normalized_text(row.get(fields["committee_id"])) or ""
    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": Organization(
            canonical_name=f"IL Committee {committee_id}" if committee_id else "IL Committee",
            identifiers={"il_committee_id": committee_id} if committee_id else {},
        ),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def _is_person_name(last_or_business: str | None, first_name: str | None) -> bool:
    if last_or_business is None:
        return False
    if first_name is None:
        return False
    return not _looks_like_organization(last_or_business)


def _looks_like_organization(last_or_business: str) -> bool:
    normalized_name = last_or_business.upper()
    return any(keyword in normalized_name for keyword in _ORGANIZATION_KEYWORDS)


def _person_from_split_name(
    *,
    first_name: str | None,
    last_name: str | None,
    identifiers: dict[str, str | None],
) -> Person | None:
    normalized_first = _normalized_text(first_name)
    normalized_last = _normalized_text(last_name)
    if normalized_first is None or normalized_last is None:
        return None

    normalized_identifiers = {
        key: normalized_value
        for key, value in identifiers.items()
        if (normalized_value := _normalized_text(value)) is not None
    }
    return Person(
        canonical_name=f"{normalized_first} {normalized_last}",
        first_name=normalized_first,
        last_name=normalized_last,
        identifiers=normalized_identifiers,
    )


def _extract_address(
    *,
    street1: str | None,
    street2: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    normalized_parts = [
        _normalized_text(street1),
        _normalized_text(street2),
        _normalized_text(city),
        _normalized_text(state),
        _normalized_zip5(raw_zip),
    ]
    raw_address = ", ".join(part for part in normalized_parts if part)
    if not raw_address:
        return None

    return Address(
        raw_address=raw_address,
        city=_normalized_text(city),
        state=_normalized_state(state),
        zip5=_normalized_zip5(raw_zip),
    )


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _normalized_state(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    return normalized_value.upper()


def _normalized_zip5(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None

    digits_only = "".join(character for character in normalized_value if character.isdigit())
    if len(digits_only) < 5:
        return None
    return digits_only[:5]
