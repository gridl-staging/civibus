
from __future__ import annotations

import re
from functools import lru_cache
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
    " BANK",
    " PAC",
    " PARTY",
    " UNION",
    " TRUST",
)


class MAContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class MAExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


@lru_cache(maxsize=1)
def _item_fields() -> dict[str, str]:
    """Map semantic roles to column names. Both contributions and expenditures
    use the same field_mappings since they come from the same report-items.txt.
    """
    return {
        "name": _load_column_for_semantic_path("contributions", "donor.org_name"),
        "first_name": _load_column_for_semantic_path("contributions", "donor.first_name"),
        "street": _load_column_for_semantic_path("contributions", "donor.address.street1"),
        "city": _load_column_for_semantic_path("contributions", "donor.address.city"),
        "state": _load_column_for_semantic_path("contributions", "donor.address.state"),
        "zip": _load_column_for_semantic_path("contributions", "donor.address.zip"),
        "occupation": _load_column_for_semantic_path("contributions", "donor.occupation"),
        "employer": _load_column_for_semantic_path("contributions", "donor.employer"),
        "report_id": _load_column_for_semantic_path("contributions", "ma.report_id"),
        "related_cpf_id": _load_column_for_semantic_path("contributions", "ma.related_cpf_id"),
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
    # OCPF data has FIPS numeric codes (e.g. '25') and truncated single-char
    # values (e.g. 'M') — skip anything that isn't a valid two-letter code.
    if not text.isalpha() or len(text) < 2:
        return None
    return text.upper()[:2]


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    text = _normalized_text(raw_zip)
    if not text:
        return None, None
    match = re.match(r"^(\d{5})(?:-(\d{4}))?", text)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _is_org_name_heuristic(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(kw in upper for kw in _ORGANIZATION_KEYWORDS)


def _build_address(
    street: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    norm_street = _normalized_text(street)
    norm_city = _normalized_text(city)
    norm_state = _normalize_state_code(state)
    norm_zip = _normalized_text(raw_zip)

    if not any((norm_street, norm_city, norm_state, norm_zip)):
        return None

    zip5, zip4 = _split_zip(raw_zip)
    raw_address = ", ".join(part for part in (norm_street, norm_city, norm_state, norm_zip) if part)

    return Address(
        raw_address=raw_address,
        city=norm_city,
        state=norm_state,
        zip5=zip5,
        zip4=zip4,
    )


def _build_committee_from_report(row: dict[str, str | None]) -> Organization:
    """Build a committee Organization from the report context.

    Uses Related_CPF_ID as the native identifier when available.
    Falls back to a synthetic ID from Report_ID.
    """
    fields = _item_fields()
    cpf_id = _normalized_text(row.get(fields["related_cpf_id"]))
    report_id = _normalized_text(row.get(fields["report_id"]))

    # We don't have the committee name in report-items.txt — only the CPF_ID.
    # Use a placeholder that can be enriched later from the filers file.
    if cpf_id:
        canonical = f"MA CPF {cpf_id}"
        identifiers = {"ma_cpf_id": cpf_id}
    elif report_id:
        canonical = f"MA Report {report_id}"
        identifiers = {"ma_report_id": report_id}
    else:
        canonical = "Unknown MA Committee"
        identifiers = {}

    return Organization(canonical_name=canonical, identifiers=identifiers)


def _extract_entity(row: dict[str, str | None]) -> tuple[Person | None, Organization | None]:
    """Extract a person or organization from the entity fields.

    If First_Name is present, treat as a person. Otherwise, use Name as org.
    """
    fields = _item_fields()
    first_name = _normalized_text(row.get(fields["first_name"]))
    full_name = _normalized_text(row.get(fields["name"]))

    if first_name:
        # Person: First_Name is populated, Name holds the last name.
        last_name = full_name
        canonical = f"{first_name} {last_name}".strip() if last_name else first_name
        person = Person(
            canonical_name=canonical,
            first_name=first_name,
            last_name=last_name,
        )
        return person, None

    if full_name:
        # Organization or individual with no first name split.
        if _is_org_name_heuristic(full_name):
            return None, Organization(canonical_name=full_name)
        # Could be a person with name in "LAST, FIRST" format.
        if "," in full_name:
            parts = [p.strip() for p in full_name.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                person = Person(
                    canonical_name=f"{parts[1]} {parts[0]}",
                    first_name=parts[1],
                    last_name=parts[0],
                )
                return person, None
        # Default to organization if can't determine.
        return None, Organization(canonical_name=full_name)

    return None, None


def extract_ma_contribution(row: dict[str, str | None]) -> MAContributionExtraction:
    """Extract donor person/org, committee, and address from a contribution row."""
    fields = _item_fields()
    committee = _build_committee_from_report(row)
    donor_person, donor_org = _extract_entity(row)

    address = _build_address(
        row.get(fields["street"]),
        row.get(fields["city"]),
        row.get(fields["state"]),
        row.get(fields["zip"]),
    )

    return MAContributionExtraction(
        donor_person=donor_person,
        donor_org=donor_org,
        committee=committee,
        address=address,
    )


def extract_ma_expenditure(row: dict[str, str | None]) -> MAExpenditureExtraction:
    """Extract payee person/org, committee, and address from an expenditure row."""
    fields = _item_fields()
    committee = _build_committee_from_report(row)
    payee_person, payee_org = _extract_entity(row)

    address = _build_address(
        row.get(fields["street"]),
        row.get(fields["city"]),
        row.get(fields["state"]),
        row.get(fields["zip"]),
    )

    return MAExpenditureExtraction(
        payee_person=payee_person,
        payee_org=payee_org,
        committee=committee,
        address=address,
    )
