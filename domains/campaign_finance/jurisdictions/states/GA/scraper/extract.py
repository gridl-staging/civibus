"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/GA/scraper/extract.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from core.types.python.models import Address, DataSource, Organization, Person
from domains.campaign_finance.normalize.addresses import normalize_address

from . import _find_ga_data_source_block_by_transaction_type
from .parse import infer_entity_type


class GAContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    candidate: Person | None
    address: Address | None


class GAExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    candidate: Person | None
    address: Address | None


def extract_donor_person(row: Mapping[str, object]) -> Person | None:
    return _extract_person_from_names(
        row,
        identifiers=_build_identifiers(
            {
                "occupation": row.get("Occupation"),
                "employer": row.get("Employer"),
            }
        ),
    )


def extract_donor_org(row: Mapping[str, object]) -> Organization | None:
    return _extract_org_from_last_name(row)


def extract_payee_person(row: Mapping[str, object]) -> Person | None:
    return _extract_person_from_names(row, identifiers={})


def extract_payee_org(row: Mapping[str, object]) -> Organization | None:
    return _extract_org_from_last_name(row)


def extract_committee(row: Mapping[str, object]) -> Organization:
    committee_name = _title_cased_text(row.get("Committee_Name")) or ""
    return Organization(
        canonical_name=committee_name,
        org_type=None,
        identifiers=_build_identifiers({"ga_filer_id": row.get("FilerID")}),
    )


def extract_candidate(row: Mapping[str, object]) -> Person | None:
    first_name = _title_cased_text(row.get("Candidate_FirstName"))
    middle_name = _title_cased_text(row.get("Candidate_MiddleName"))
    last_name = _title_cased_text(row.get("Candidate_LastName"))
    suffix = _title_cased_text(row.get("Candidate_Suffix"))

    if all(part is None for part in (first_name, middle_name, last_name, suffix)):
        return None

    return Person(
        canonical_name=_build_title_cased_name(first_name, middle_name, last_name, suffix),
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        suffix=suffix,
        identifiers={},
    )


def extract_address(row: Mapping[str, object]) -> Address | None:
    street = _normalized_text(row.get("Address"))
    city = _normalized_text(row.get("City"))
    state = _normalized_text(row.get("State"))
    raw_zip = _normalized_text(row.get("Zip"))

    if city is None and state is None:
        return None

    normalized_address = normalize_address(street=street, city=city, state=state, zip=raw_zip)
    raw_address = ", ".join(part for part in (street, city, state, raw_zip) if part is not None)

    return Address(
        raw_address=raw_address,
        street_number=normalized_address.street_number,
        street_name=normalized_address.street_name,
        unit=normalized_address.unit,
        city=normalized_address.city,
        state=normalized_address.state,
        zip5=normalized_address.zip5,
        zip4=normalized_address.zip4,
    )


def build_ga_data_source(transaction_type: str) -> DataSource:
    data_source_block = _find_ga_data_source_block_by_transaction_type(transaction_type)
    if data_source_block is None:
        raise ValueError(f"Unsupported GA transaction type: {transaction_type!r}")

    return DataSource(
        domain="campaign_finance",
        jurisdiction="state/GA",
        name=data_source_block.name,
        source_url=data_source_block.url,
    )


def extract_ga_contribution(row: Mapping[str, object]) -> GAContributionExtraction:
    return {
        "donor_person": extract_donor_person(row),
        "donor_org": extract_donor_org(row),
        "committee": extract_committee(row),
        "candidate": extract_candidate(row),
        "address": extract_address(row),
    }


def extract_ga_expenditure(row: Mapping[str, object]) -> GAExpenditureExtraction:
    return {
        "payee_person": extract_payee_person(row),
        "payee_org": extract_payee_org(row),
        "committee": extract_committee(row),
        "candidate": extract_candidate(row),
        "address": extract_address(row),
    }


def _extract_person_from_names(row: Mapping[str, object], identifiers: dict[str, str]) -> Person | None:
    entity_type = infer_entity_type(
        _normalized_text(row.get("LastName")),
        _normalized_text(row.get("FirstName")),
    )
    if entity_type != "person":
        return None

    first_name = _title_cased_text(row.get("FirstName"))
    last_name = _title_cased_text(row.get("LastName"))
    if first_name is None or last_name is None:
        return None

    return Person(
        canonical_name=_build_title_cased_name(first_name, last_name),
        first_name=first_name,
        last_name=last_name,
        identifiers=identifiers,
    )


def _extract_org_from_last_name(row: Mapping[str, object]) -> Organization | None:
    entity_type = infer_entity_type(
        _normalized_text(row.get("LastName")),
        _normalized_text(row.get("FirstName")),
    )
    if entity_type != "organization":
        return None

    canonical_name = _title_cased_text(row.get("LastName"))
    if canonical_name is None:
        return None

    return Organization(canonical_name=canonical_name)


def _build_title_cased_name(*parts: object) -> str:
    normalized_parts = [normalized for part in parts if (normalized := _normalized_text(part)) is not None]
    return " ".join(normalized_parts).title()


def _build_identifiers(fields: Mapping[str, object]) -> dict[str, str]:
    return {
        key: normalized_value
        for key, raw_value in fields.items()
        if (normalized_value := _normalized_text(raw_value)) is not None
    }


def _title_cased_text(value: object) -> str | None:
    normalized_value = _normalized_text(value)
    if normalized_value is None:
        return None
    return normalized_value.title()


def _normalized_text(value: object) -> str | None:
    if value is None or not isinstance(value, str):
        return None

    stripped_value = value.strip()
    return stripped_value or None


__all__ = [
    "GAContributionExtraction",
    "GAExpenditureExtraction",
    "build_ga_data_source",
    "extract_address",
    "extract_candidate",
    "extract_committee",
    "extract_donor_org",
    "extract_donor_person",
    "extract_ga_contribution",
    "extract_ga_expenditure",
    "extract_payee_org",
    "extract_payee_person",
]
