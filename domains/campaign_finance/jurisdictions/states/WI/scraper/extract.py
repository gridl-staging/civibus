"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_pm_1_prod_data_deploy_and_runner_cleanup/civibus_dev/domains/campaign_finance/jurisdictions/states/WI/scraper/extract.py.
"""

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
    " COMMITTEE",
    " ASSOCIATION",
    " FUND",
    " PARTY",
    " PAC",
)

_STATE_NAME_TO_CODE = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
}


class WITransactionExtraction(TypedDict):
    contributor_person: Person | None
    contributor_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _transaction_fields() -> dict[str, str]:
    return {
        "contributor_name": _load_column_for_semantic_path("transactions", "donor.name"),
        "contributor_type": _load_column_for_semantic_path("transactions", "donor.type"),
        "contributor_occupation": _load_column_for_semantic_path("transactions", "donor.occupation"),
        "contributor_address1": _load_column_for_semantic_path("transactions", "donor.address.street1"),
        "contributor_city": _load_column_for_semantic_path("transactions", "donor.address.city"),
        "contributor_state": _load_column_for_semantic_path("transactions", "donor.address.state"),
        "contributor_zip": _load_column_for_semantic_path("transactions", "donor.address.zip"),
        "committee_id": _load_column_for_semantic_path("transactions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("transactions", "committee.name"),
        "committee_type": _load_column_for_semantic_path("transactions", "committee.type"),
    }


def extract_wi_transaction(row: dict[str, str | None]) -> WITransactionExtraction:
    fields = _transaction_fields()

    contributor_name = _normalized_text(row.get(fields["contributor_name"]))
    contributor_type = _normalized_text(row.get(fields["contributor_type"]))

    contributor_person: Person | None = None
    contributor_org: Organization | None = None
    if _is_individual_contributor(contributor_type):
        contributor_person = _person_from_name(
            contributor_name,
            occupation=_normalized_text(row.get(fields["contributor_occupation"])),
        )
    elif contributor_name is not None:
        contributor_org = Organization(canonical_name=contributor_name)

    return {
        "contributor_person": contributor_person,
        "contributor_org": contributor_org,
        "committee": _extract_committee(row, fields=fields),
        "address": _extract_address(
            street1=row.get(fields["contributor_address1"]),
            city=row.get(fields["contributor_city"]),
            state=row.get(fields["contributor_state"]),
            raw_zip=row.get(fields["contributor_zip"]),
        ),
    }


def _extract_committee(row: dict[str, str | None], *, fields: dict[str, str]) -> Organization:
    committee_name = _normalized_text(row.get(fields["committee_name"])) or ""
    committee_type = _normalized_text(row.get(fields["committee_type"]))
    committee_id = _normalized_text(row.get(fields["committee_id"]))

    identifiers: dict[str, str] = {}
    if committee_id is not None:
        identifiers["wi_registrant_id"] = committee_id

    return Organization(
        canonical_name=committee_name,
        org_type=committee_type.lower() if committee_type is not None else None,
        identifiers=identifiers,
    )


def _person_from_name(name: str | None, *, occupation: str | None) -> Person | None:
    normalized_name = _normalized_text(name)
    if normalized_name is None:
        return None

    parts = normalized_name.split()
    if len(parts) < 2:
        return None

    first_name = parts[0]
    last_name = parts[-1]

    identifiers: dict[str, str] = {}
    if occupation:
        identifiers["occupation"] = occupation

    return Person(
        canonical_name=normalized_name,
        first_name=first_name,
        last_name=last_name,
        identifiers=identifiers,
    )


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
    normalized_zip = _normalize_zip5(raw_zip)

    if not any((normalized_street1, normalized_city, normalized_state, normalized_zip)):
        return None

    raw_address = ", ".join(
        part for part in (normalized_street1, normalized_city, normalized_state, normalized_zip) if part
    )

    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=normalized_zip,
    )


def _normalize_state_code(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None

    upper_value = normalized.upper()
    if len(upper_value) == 2:
        return upper_value
    return _STATE_NAME_TO_CODE.get(upper_value)


def _normalize_zip5(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None

    digits = "".join(character for character in normalized if character.isdigit())
    if len(digits) < 5:
        return None
    return digits[:5]


def _is_individual_contributor(contributor_type: str | None) -> bool:
    normalized_type = _normalized_text(contributor_type)
    if normalized_type is None:
        return False

    lowered_type = normalized_type.lower()
    if lowered_type in {"individual", "person"}:
        return True

    normalized_upper = f" {normalized_type.upper()} "
    if any(keyword in normalized_upper for keyword in _ORGANIZATION_KEYWORDS):
        return False

    return False


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized
