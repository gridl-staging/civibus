"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/TX/scraper/extract.py.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path


class TXContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class TXExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


class TXLoanExtraction(TypedDict):
    lender_person: Person | None
    lender_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "committee_type": _load_column_for_semantic_path("contributions", "committee.type"),
        "donor_type": _load_column_for_semantic_path("contributions", "donor.type"),
        "donor_org_name": _load_column_for_semantic_path("contributions", "donor.name.organization"),
        "donor_first": _load_column_for_semantic_path("contributions", "donor.name.first"),
        "donor_last": _load_column_for_semantic_path("contributions", "donor.name.last"),
        "donor_suffix": _load_column_for_semantic_path("contributions", "donor.name.suffix"),
        "donor_prefix": _load_column_for_semantic_path("contributions", "donor.name.prefix"),
        "donor_employer": _load_column_for_semantic_path("contributions", "donor.employer"),
        "donor_occupation": _load_column_for_semantic_path("contributions", "donor.occupation"),
        "donor_job_title": _load_column_for_semantic_path("contributions", "donor.job_title"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "committee_type": _load_column_for_semantic_path("expenditures", "committee.type"),
        "payee_type": _load_column_for_semantic_path("expenditures", "payee.type"),
        "payee_org_name": _load_column_for_semantic_path("expenditures", "payee.name.organization"),
        "payee_first": _load_column_for_semantic_path("expenditures", "payee.name.first"),
        "payee_last": _load_column_for_semantic_path("expenditures", "payee.name.last"),
        "payee_suffix": _load_column_for_semantic_path("expenditures", "payee.name.suffix"),
        "payee_prefix": _load_column_for_semantic_path("expenditures", "payee.name.prefix"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "street2": _load_column_for_semantic_path("expenditures", "payee.address.street2"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


@lru_cache(maxsize=1)
def _loan_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("loans", "committee.id"),
        "committee_name": _load_column_for_semantic_path("loans", "committee.name"),
        "committee_type": _load_column_for_semantic_path("loans", "committee.type"),
        "lender_type": _load_column_for_semantic_path("loans", "lender.type"),
        "lender_org_name": _load_column_for_semantic_path("loans", "lender.name.organization"),
        "lender_first": _load_column_for_semantic_path("loans", "lender.name.first"),
        "lender_last": _load_column_for_semantic_path("loans", "lender.name.last"),
        "lender_suffix": _load_column_for_semantic_path("loans", "lender.name.suffix"),
        "lender_prefix": _load_column_for_semantic_path("loans", "lender.name.prefix"),
        "lender_employer": _load_column_for_semantic_path("loans", "lender.employer"),
        "lender_occupation": _load_column_for_semantic_path("loans", "lender.occupation"),
        "lender_job_title": _load_column_for_semantic_path("loans", "lender.job_title"),
        "city": _load_column_for_semantic_path("loans", "lender.address.city"),
        "state": _load_column_for_semantic_path("loans", "lender.address.state"),
        "zip": _load_column_for_semantic_path("loans", "lender.address.zip"),
    }


def extract_tx_contribution(row: dict[str, str | None]) -> TXContributionExtraction:
    fields = _contribution_fields()
    donor_type = _normalized_text(row.get(fields["donor_type"]))

    donor_person = None
    donor_org = None
    if _is_individual_type(donor_type):
        donor_person = _person_from_split_name(
            first_name=row.get(fields["donor_first"]),
            last_name=row.get(fields["donor_last"]),
            suffix=row.get(fields["donor_suffix"]),
            prefix=row.get(fields["donor_prefix"]),
            identifiers={
                "employer": row.get(fields["donor_employer"]),
                "occupation": row.get(fields["donor_occupation"]),
                "job_title": row.get(fields["donor_job_title"]),
            },
        )
    elif _is_entity_type(donor_type):
        donor_org = _organization_from_name(row.get(fields["donor_org_name"]))

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_tx_expenditure(row: dict[str, str | None]) -> TXExpenditureExtraction:
    fields = _expenditure_fields()
    payee_type = _normalized_text(row.get(fields["payee_type"]))

    payee_person = None
    payee_org = None
    if _is_individual_type(payee_type):
        payee_person = _person_from_split_name(
            first_name=row.get(fields["payee_first"]),
            last_name=row.get(fields["payee_last"]),
            suffix=row.get(fields["payee_suffix"]),
            prefix=row.get(fields["payee_prefix"]),
            identifiers={},
        )
    elif _is_entity_type(payee_type):
        payee_org = _organization_from_name(row.get(fields["payee_org_name"]))

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_tx_loan(row: dict[str, str | None]) -> TXLoanExtraction:
    fields = _loan_fields()
    lender_type = _normalized_text(row.get(fields["lender_type"]))

    lender_person = None
    lender_org = None
    if _is_individual_type(lender_type):
        lender_person = _person_from_split_name(
            first_name=row.get(fields["lender_first"]),
            last_name=row.get(fields["lender_last"]),
            suffix=row.get(fields["lender_suffix"]),
            prefix=row.get(fields["lender_prefix"]),
            identifiers={
                "employer": row.get(fields["lender_employer"]),
                "occupation": row.get(fields["lender_occupation"]),
                "job_title": row.get(fields["lender_job_title"]),
            },
        )
    elif _is_entity_type(lender_type):
        lender_org = _organization_from_name(row.get(fields["lender_org_name"]))

    return {
        "lender_person": lender_person,
        "lender_org": lender_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def _extract_committee(row: dict[str, str | None], *, fields: dict[str, str]) -> Organization:
    committee_name = _normalized_text(row.get(fields["committee_name"])) or ""
    committee_type = _normalized_text(row.get(fields["committee_type"]))
    committee_id = _normalized_text(row.get(fields["committee_id"]))

    identifiers = {"tx_committee_id": committee_id} if committee_id is not None else {}
    return Organization(
        canonical_name=committee_name,
        org_type=committee_type.lower() if committee_type is not None else None,
        identifiers=identifiers,
    )


def _person_from_split_name(
    *,
    first_name: str | None,
    last_name: str | None,
    suffix: str | None,
    prefix: str | None,
    identifiers: dict[str, str | None],
) -> Person | None:
    normalized_first = _normalized_text(first_name)
    normalized_last = _normalized_text(last_name)
    if normalized_first is None or normalized_last is None:
        return None

    normalized_suffix = _normalized_text(suffix)
    normalized_prefix = _normalized_text(prefix)
    canonical_name = " ".join(
        part for part in (normalized_prefix, normalized_first, normalized_last, normalized_suffix) if part
    )

    normalized_identifiers = {
        key: normalized_value
        for key, value in identifiers.items()
        if (normalized_value := _normalized_text(value)) is not None
    }

    return Person(
        canonical_name=canonical_name,
        first_name=normalized_first,
        last_name=normalized_last,
        suffix=normalized_suffix,
        identifiers=normalized_identifiers,
    )


def _organization_from_name(name: str | None) -> Organization | None:
    canonical_name = _normalized_text(name)
    if canonical_name is None:
        return None
    return Organization(canonical_name=canonical_name)


def _extract_address(
    *,
    street1: str | None = None,
    street2: str | None = None,
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


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    """Split a raw ZIP string into (zip5, zip4) components.

    Handles formats seen in government data:
      - '77494'       -> ('77494', None)       standard 5-digit
      - '77494-6162'  -> ('77494', '6162')      ZIP+4 with dash
      - '774946162'   -> ('77494', '6162')      ZIP+4 without dash (TX live data)
      - '693' / '966' -> (None, None)           garbage short ZIP, drop silently

    Anything that is not exactly 5 or 9 digits (or a dashed split that yields
    a 5-digit zip5) is treated as malformed and dropped — propagating it as
    `zip5` would fail Address.zip5 Pydantic validation and, on the priority
    refresh runner, spam hundreds of MB of stack traces while still leaving
    the row unloaded. Dropping the bad ZIP keeps the rest of the address
    intact so the row still loads.
    """
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5_raw, zip4_raw = normalized_zip.split("-", maxsplit=1)
        zip5 = _normalized_digits(zip5_raw)
        zip4 = _normalized_digits(zip4_raw)
        # A dashed value with a non-5-digit prefix is malformed; drop it rather
        # than raising downstream.
        if zip5 is None or len(zip5) != 5:
            return None, None
        return zip5, zip4

    digits = _normalized_digits(normalized_zip)
    if digits is None:
        return None, None

    if len(digits) == 5:
        return digits, None
    # 9-digit ZIP+4 without dash: split into 5+4
    if len(digits) == 9:
        return digits[:5], digits[5:]

    # 1-4 or 6-8 digits is garbage; drop rather than raise.
    return None, None


def _normalized_digits(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    digits = "".join(character for character in normalized_value if character.isdigit())
    if not digits:
        return None
    return digits


def _normalize_state_code(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    upper_value = normalized_value.upper()
    if len(upper_value) != 2:
        return None
    return upper_value


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped_value = value.strip()
    return stripped_value or None


def _is_individual_type(person_type_code: str | None) -> bool:
    return (person_type_code or "").upper() == "INDIVIDUAL"


def _is_entity_type(person_type_code: str | None) -> bool:
    return (person_type_code or "").upper() == "ENTITY"
