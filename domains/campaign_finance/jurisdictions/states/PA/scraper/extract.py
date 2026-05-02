"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/extract.py.
"""

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
    " CORPORATION",
    " COMPANY",
    " COMMITTEE",
    " ASSOCIATION",
    " ASSOCIATES",
    " FOUNDATION",
    " FUND",
    " BANK",
    " PAC",
    " PARTY",
)

_PERSON_PREFIXES = {"MR", "MRS", "MS", "DR", "PROF", "REV"}


class PAContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class PAExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


class PADebtExtraction(TypedDict):
    lender_person: Person | None
    lender_org: Organization | None
    committee: Organization
    address: Address | None


class PAReceiptExtraction(TypedDict):
    source_person: Person | None
    source_org: Organization | None
    committee: Organization
    address: Address | None


class PAFilerExtraction(TypedDict):
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "donor_name": _load_column_for_semantic_path("contributions", "donor.name"),
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
        "payee_name": _load_column_for_semantic_path("expenditures", "payee.name"),
        "street1": _load_column_for_semantic_path("expenditures", "payee.address.street1"),
        "street2": _load_column_for_semantic_path("expenditures", "payee.address.street2"),
        "city": _load_column_for_semantic_path("expenditures", "payee.address.city"),
        "state": _load_column_for_semantic_path("expenditures", "payee.address.state"),
        "zip": _load_column_for_semantic_path("expenditures", "payee.address.zip"),
    }


@lru_cache(maxsize=1)
def _debt_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("debts", "committee.id"),
        "lender_name": _load_column_for_semantic_path("debts", "lender.name"),
        "street1": _load_column_for_semantic_path("debts", "lender.address.street1"),
        "street2": _load_column_for_semantic_path("debts", "lender.address.street2"),
        "city": _load_column_for_semantic_path("debts", "lender.address.city"),
        "state": _load_column_for_semantic_path("debts", "lender.address.state"),
        "zip": _load_column_for_semantic_path("debts", "lender.address.zip"),
    }


@lru_cache(maxsize=1)
def _receipt_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("receipts", "committee.id"),
        "source_name": _load_column_for_semantic_path("receipts", "pa.receipt_source_name"),
        "street1": _load_column_for_semantic_path("receipts", "pa.receipt_source_address.street1"),
        "street2": _load_column_for_semantic_path("receipts", "pa.receipt_source_address.street2"),
        "city": _load_column_for_semantic_path("receipts", "pa.receipt_source_address.city"),
        "state": _load_column_for_semantic_path("receipts", "pa.receipt_source_address.state"),
        "zip": _load_column_for_semantic_path("receipts", "pa.receipt_source_address.zip"),
    }


@lru_cache(maxsize=1)
def _filer_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("filings", "committee.id"),
        "committee_name": _load_column_for_semantic_path("filings", "committee.name"),
        "street1": _load_column_for_semantic_path("filings", "committee.address.street1"),
        "street2": _load_column_for_semantic_path("filings", "committee.address.street2"),
        "city": _load_column_for_semantic_path("filings", "committee.address.city"),
        "state": _load_column_for_semantic_path("filings", "committee.address.state"),
        "zip": _load_column_for_semantic_path("filings", "committee.address.zip"),
    }


def extract_pa_contribution(row: dict[str, str | None]) -> PAContributionExtraction:
    fields = _contribution_fields()
    donor_person, donor_org = _person_or_org_from_single_name(row.get(fields["donor_name"]))

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_pa_expenditure(row: dict[str, str | None]) -> PAExpenditureExtraction:
    fields = _expenditure_fields()
    payee_person, payee_org = _person_or_org_from_single_name(row.get(fields["payee_name"]))

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


def extract_pa_debt(row: dict[str, str | None]) -> PADebtExtraction:
    fields = _debt_fields()
    lender_person, lender_org = _person_or_org_from_single_name(row.get(fields["lender_name"]))

    return {
        "lender_person": lender_person,
        "lender_org": lender_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_pa_receipt(row: dict[str, str | None]) -> PAReceiptExtraction:
    fields = _receipt_fields()
    source_person, source_org = _person_or_org_from_single_name(row.get(fields["source_name"]))

    return {
        "source_person": source_person,
        "source_org": source_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def extract_pa_filing(row: dict[str, str | None]) -> PAFilerExtraction:
    fields = _filer_fields()
    return {
        "committee": _extract_committee(row, fields=fields, committee_name_column="committee_name"),
        "address": _extract_address(
            street1=row.get(fields["street1"]),
            street2=row.get(fields["street2"]),
            city=row.get(fields["city"]),
            state=row.get(fields["state"]),
            raw_zip=row.get(fields["zip"]),
        ),
    }


def _extract_committee(
    row: dict[str, str | None],
    *,
    fields: dict[str, str],
    committee_name_column: str | None = None,
) -> Organization:
    name_column = committee_name_column or "committee_name"
    if name_column in fields:
        committee_name = _normalized_text(row.get(fields[name_column])) or ""
    else:
        committee_name = ""

    committee_id = _normalized_text(row.get(fields["committee_id"]))
    identifiers = {"pa_filer_id": committee_id} if committee_id is not None else {}
    return Organization(canonical_name=committee_name, identifiers=identifiers)


def _person_or_org_from_single_name(name: str | None) -> tuple[Person | None, Organization | None]:
    normalized_name = _normalized_text(name)
    if normalized_name is None:
        return None, None

    if _looks_like_organization_name(normalized_name):
        return None, Organization(canonical_name=normalized_name)

    person = _person_from_full_name(normalized_name)
    if person is None:
        return None, Organization(canonical_name=normalized_name)

    return person, None


def _looks_like_organization_name(name: str) -> bool:
    upper_name = f" {name.upper()} "
    if any(keyword in upper_name for keyword in _ORGANIZATION_KEYWORDS):
        return True
    if "&" in name:
        return True
    if "," not in name and len(name.split()) == 1:
        return True
    return False


def _person_from_full_name(full_name: str) -> Person | None:
    if "," in full_name:
        last_name_part, first_name_part = [part.strip() for part in full_name.split(",", maxsplit=1)]
        first_name = _first_name_token(first_name_part)
        last_name = _normalized_text(last_name_part)
    else:
        normalized_whitespace = re.sub(r"\s+", " ", full_name).strip()
        parts = normalized_whitespace.split(" ")
        while parts and parts[0].rstrip(".").upper() in _PERSON_PREFIXES:
            parts = parts[1:]
        if len(parts) < 2:
            return None
        first_name = _normalized_text(parts[0])
        last_name = _normalized_text(parts[-1])

    if first_name is None or last_name is None:
        return None

    return Person(
        canonical_name=full_name,
        first_name=first_name,
        last_name=last_name,
    )


def _first_name_token(name_part: str) -> str | None:
    first_token = name_part.split(" ")[0] if name_part else ""
    return _normalized_text(first_token)


def _extract_address(
    *,
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


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None

    if "-" in normalized_zip:
        zip5, zip4 = normalized_zip.split("-", maxsplit=1)
        return _coerce_zip5(_normalized_digits(zip5)), _coerce_zip4(_normalized_digits(zip4))

    normalized_digits = _normalized_digits(normalized_zip)
    if normalized_digits is None:
        return None, None
    if len(normalized_digits) == 9:
        return normalized_digits[:5], normalized_digits[5:]

    return _coerce_zip5(normalized_digits), None


def _normalized_digits(value: str | None) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    digits = "".join(character for character in normalized_value if character.isdigit())
    if not digits:
        return None
    return digits


def _coerce_zip5(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 5:
        return value[:5]
    return None


def _coerce_zip4(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 4:
        return value[:4]
    return None


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
