
from __future__ import annotations

from functools import lru_cache
import re
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
)


class MNContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class MNExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "committee_type": _load_column_for_semantic_path("contributions", "committee.type"),
        "committee_sub_type": _load_column_for_semantic_path("contributions", "committee.sub_type"),
        "donor_name": _load_column_for_semantic_path("contributions", "donor.name"),
        "donor_type": _load_column_for_semantic_path("contributions", "donor.type"),
        "donor_employer": _load_column_for_semantic_path("contributions", "donor.employer"),
        "donor_zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "committee_type": _load_column_for_semantic_path("expenditures", "committee.type"),
        "committee_sub_type": _load_column_for_semantic_path("expenditures", "committee.sub_type"),
        "payee_name": _load_column_for_semantic_path("expenditures", "payee.name"),
        "address1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "address2": _load_column_for_semantic_path("expenditures", "payee.address.street2"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


@lru_cache(maxsize=1)
def _independent_expenditure_fields() -> dict[str, str]:
    data_type = "independent_expenditures"
    return {
        field_name: _load_column_for_semantic_path(data_type, semantic_path)
        for field_name, semantic_path in {
            "committee_id": "committee.id",
            "committee_name": "committee.name",
            "committee_type": "committee.type",
            "committee_sub_type": "committee.sub_type",
            "payee_name": "payee.name",
            "address1": "payee.address.street1",
            "address2": "payee.address.street2",
            "city": "payee.address.city",
            "state": "payee.address.state",
            "zip": "payee.address.zip",
        }.items()
    }


def extract_mn_contribution(row: dict[str, str | None]) -> MNContributionExtraction:
    fields = _contribution_fields()
    donor_name = _normalized_text(row.get(fields["donor_name"]))
    donor_type = _normalized_text(row.get(fields["donor_type"]))

    donor_person = None
    if _is_individual_contributor(donor_type):
        donor_person = _person_from_full_name(
            donor_name,
            identifiers={"employer": _normalized_text(row.get(fields["donor_employer"]))},
        )
    donor_org = None if donor_person is not None or donor_name is None else Organization(canonical_name=donor_name)

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_zip_only_address(row.get(fields["donor_zip"])),
    }


def extract_mn_expenditure(row: dict[str, str | None]) -> MNExpenditureExtraction:
    return _extract_mn_payee_transaction(row, fields=_expenditure_fields())


def extract_mn_independent_expenditure(row: dict[str, str | None]) -> MNExpenditureExtraction:
    return _extract_mn_payee_transaction(row, fields=_independent_expenditure_fields())


def _extract_mn_payee_transaction(
    row: dict[str, str | None],
    *,
    fields: dict[str, str],
) -> MNExpenditureExtraction:
    payee_name = _normalized_text(row.get(fields["payee_name"]))

    payee_person = None
    if payee_name is not None and _looks_like_organization_name(payee_name):
        payee_org = Organization(canonical_name=payee_name)
    else:
        payee_org = None
        payee_person = _person_from_full_name(payee_name, identifiers={})

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_street_address(
            address1=row.get(fields["address1"]),
            address2=row.get(fields["address2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def _extract_committee(row: dict[str, str | None], *, fields: dict[str, str]) -> Organization:
    committee_name = _normalized_text(row.get(fields["committee_name"])) or ""
    committee_type = _normalized_text(row.get(fields["committee_type"]))
    committee_sub_type = _normalized_text(row.get(fields["committee_sub_type"]))
    normalized_committee_id = _normalized_text(row.get(fields["committee_id"]))

    organization_type = " ".join(part for part in (committee_type, committee_sub_type) if part).strip().lower() or None
    identifiers = {"mn_committee_reg_num": normalized_committee_id} if normalized_committee_id is not None else {}

    return Organization(
        canonical_name=committee_name,
        org_type=organization_type,
        identifiers=identifiers,
    )


def _extract_zip_only_address(raw_zip: str | None) -> Address | None:
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None

    zip5, zip4 = _split_zip(normalized_zip)
    return Address(
        raw_address=normalized_zip,
        zip5=zip5,
        zip4=zip4,
    )


def _extract_street_address(
    *,
    address1: str | None,
    address2: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    normalized_address1 = _normalized_text(address1)
    normalized_address2 = _normalized_text(address2)
    normalized_city = _normalized_text(city)
    normalized_state = _normalize_state_code(state)
    normalized_zip = _normalized_text(raw_zip)

    if not any((normalized_address1, normalized_address2, normalized_city, normalized_state, normalized_zip)):
        return None

    zip5, zip4 = _split_zip(normalized_zip)
    raw_address = ", ".join(
        part
        for part in (normalized_address1, normalized_address2, normalized_city, normalized_state, normalized_zip)
        if part
    )
    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=zip5,
        zip4=zip4,
    )


def _person_from_full_name(full_name: str | None, identifiers: dict[str, str | None]) -> Person | None:
    normalized_name = _normalized_text(full_name)
    if normalized_name is None:
        return None

    first_name, last_name = _split_person_name(normalized_name)
    if first_name is None or last_name is None:
        return None

    normalized_identifiers = {
        key: normalized_value
        for key, value in identifiers.items()
        if (normalized_value := _normalized_text(value)) is not None
    }

    canonical_name = f"{first_name} {last_name}".strip()
    return Person(
        canonical_name=canonical_name,
        first_name=first_name,
        last_name=last_name,
        identifiers=normalized_identifiers,
    )


def _split_person_name(full_name: str) -> tuple[str | None, str | None]:
    if "," in full_name:
        last_name_part, first_name_part = [part.strip() for part in full_name.split(",", maxsplit=1)]
        first_name = _title_case_name(first_name_part)
        last_name = _title_case_name(last_name_part)
        return first_name, last_name

    normalized_whitespace_name = re.sub(r"\s+", " ", full_name).strip()
    parts = normalized_whitespace_name.split(" ")
    if len(parts) < 2:
        return None, None

    first_name = _title_case_name(parts[0])
    last_name = _title_case_name(parts[-1])
    return first_name, last_name


def _looks_like_organization_name(name: str | None) -> bool:
    normalized_name = _normalized_text(name)
    if normalized_name is None:
        return False

    upper_name = f" {normalized_name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True

    # Names with commas in this dataset are commonly "Last, First" person format.
    return "," not in normalized_name and len(normalized_name.split()) == 1


def _is_individual_contributor(contributor_type: str | None) -> bool:
    normalized_type = _normalized_text(contributor_type)
    return normalized_type is not None and normalized_type.lower().startswith("individual")


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5_raw, zip4_raw = normalized_zip.split("-", maxsplit=1)
        return _pad_zip5(_normalized_digits(zip5_raw)), _normalized_digits(zip4_raw)

    return _pad_zip5(_normalized_digits(normalized_zip)), None


def _pad_zip5(digits: str | None) -> str | None:
    """Zero-pad a zip5 string to 5 digits (east-coast US zips lose leading zeros)."""
    if digits is None:
        return None
    if len(digits) > 5 or len(digits) < 3:
        return None
    return digits.zfill(5)


def _normalized_digits(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None

    digits_only = "".join(char for char in normalized_value if char.isdigit())
    return digits_only or None


def _normalize_state_code(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None

    uppercase_state = normalized_value.upper()
    if len(uppercase_state) != 2:
        return None

    return uppercase_state


def _title_case_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None

    stripped_value = value.strip()
    return stripped_value or None
