"""Indiana scraper extraction helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path

_ORGANIZATION_KEYWORDS = (
    " LLC",
    " LLP",
    " INC",
    " CORP",
    " CORPORATION",
    " COMMITTEE",
    " ASSOCIATION",
    " PARTY",
    " FUND",
    " PAC",
    " BANK",
    " LODGE",
)
_PERSON_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}


class INContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class INExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "committee_type": _load_column_for_semantic_path("contributions", "committee.type"),
        "donor_type": _load_column_for_semantic_path("contributions", "donor.type"),
        "donor_name": _load_column_for_semantic_path("contributions", "donor.name"),
        "occupation": _load_column_for_semantic_path("contributions", "donor.occupation"),
        "street1": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "committee_type": _load_column_for_semantic_path("expenditures", "committee.type"),
        "payee_name": _load_column_for_semantic_path("expenditures", "payee.name"),
        "occupation": _load_column_for_semantic_path("expenditures", "payee.occupation"),
        "expenditure_code": _load_column_for_semantic_path("expenditures", "transaction.code"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


def extract_in_contribution(row: dict[str, str | None]) -> INContributionExtraction:
    fields = _contribution_fields()
    donor_name = row.get(fields["donor_name"])
    donor_type = _normalized_text(row.get(fields["donor_type"]))

    donor_person = None
    donor_org = None
    if _is_individual_contributor(donor_type):
        donor_person = _person_from_name(
            donor_name,
            identifiers={
                "occupation": row.get(fields["occupation"]),
            },
        )
    else:
        donor_org = _organization_from_name(donor_name)

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_in_expenditure(row: dict[str, str | None]) -> INExpenditureExtraction:
    fields = _expenditure_fields()
    payee_name = row.get(fields["payee_name"])
    occupation = row.get(fields["occupation"])
    expenditure_code = row.get(fields["expenditure_code"])

    payee_person = None
    payee_org = None
    if _is_transfer_expenditure(expenditure_code):
        payee_org = _organization_from_name(payee_name)
    elif _occupation_indicates_person(occupation):
        payee_person = _person_from_name(payee_name, identifiers={"occupation": occupation})
    elif _looks_like_organization_name(payee_name):
        payee_org = _organization_from_name(payee_name)
    else:
        payee_person = _person_from_name(payee_name, identifiers={"occupation": occupation})

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def _extract_committee(row: dict[str, str | None], *, fields: dict[str, str]) -> Organization:
    committee_name = _normalized_text(row.get(fields["committee_name"])) or ""
    committee_type = _normalized_text(row.get(fields["committee_type"]))
    return Organization(
        canonical_name=committee_name,
        org_type=committee_type.lower() if committee_type is not None else None,
    )


def _person_from_name(name: str | None, *, identifiers: dict[str, str | None]) -> Person | None:
    normalized_name = _normalized_text(name)
    if normalized_name is None:
        return None

    first_name, last_name, suffix = _split_person_name(normalized_name)
    if first_name is None or last_name is None:
        return None

    normalized_identifiers = {
        key: normalized_value
        for key, value in identifiers.items()
        if (normalized_value := _normalized_text(value)) is not None
    }

    return Person(
        canonical_name=normalized_name,
        first_name=first_name,
        last_name=last_name,
        suffix=suffix,
        identifiers=normalized_identifiers,
    )


def _split_person_name(name: str) -> tuple[str | None, str | None, str | None]:
    if "," in name:
        last_name_part, first_name_part = [part.strip() for part in name.split(",", maxsplit=1)]
        first_tokens = first_name_part.split()
        if not first_tokens:
            return None, None, None
        return first_tokens[0], _normalized_text(last_name_part), None

    parts = name.split()
    if len(parts) < 2:
        return None, None, None

    suffix = None
    if len(parts) > 2 and parts[-1].rstrip(".").upper() in _PERSON_SUFFIXES:
        suffix = parts[-1]
        last_name = parts[-2]
    else:
        last_name = parts[-1]

    first_name = parts[0]
    return _normalized_text(first_name), _normalized_text(last_name), _normalized_text(suffix)


def _organization_from_name(name: str | None) -> Organization | None:
    normalized_name = _normalized_text(name)
    if normalized_name is None:
        return None
    return Organization(canonical_name=normalized_name)


def _extract_address(
    *,
    street1: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
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
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5, zip4 = normalized_zip.split("-", maxsplit=1)
        return _coerce_zip5(_normalized_digits(zip5)), _coerce_zip4(_normalized_digits(zip4))

    digits = _normalized_digits(normalized_zip)
    if digits is None:
        return None, None
    if len(digits) == 9:
        return digits[:5], digits[5:]

    return _coerce_zip5(digits), None


def _coerce_zip5(value: str | None) -> str | None:
    if value is None or len(value) < 5:
        return None
    return value[:5]


def _coerce_zip4(value: str | None) -> str | None:
    if value is None or len(value) < 4:
        return None
    return value[:4]


def _normalize_state_code(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None

    upper_value = normalized_value.upper()
    if len(upper_value) != 2:
        return None
    return upper_value


def _normalized_digits(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None

    digits = "".join(character for character in normalized_value if character.isdigit())
    if not digits:
        return None
    return digits


def _is_individual_contributor(donor_type: str | None) -> bool:
    normalized_type = _normalized_text(donor_type)
    if normalized_type is None:
        return False
    return normalized_type.lower() == "individual"


def _is_transfer_expenditure(expenditure_code: str | None) -> bool:
    normalized_code = _normalized_text(expenditure_code)
    if normalized_code is None:
        return False
    return normalized_code.lower() == "contributions"


def _occupation_indicates_person(occupation: str | None) -> bool:
    normalized_occupation = _normalized_text(occupation)
    if normalized_occupation is None:
        return False
    return normalized_occupation.lower() != "other"


def _looks_like_organization_name(name: str | None) -> bool:
    normalized_name = _normalized_text(name)
    if normalized_name is None:
        return False

    upper_name = f" {normalized_name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True
    if "&" in normalized_name:
        return True
    return "," not in normalized_name and len(normalized_name.split()) == 1


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None

    stripped_value = value.strip()
    return stripped_value or None
