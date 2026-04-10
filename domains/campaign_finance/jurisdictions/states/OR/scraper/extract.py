"""Entity extraction helpers for OR campaign finance rows.

ORESTAR names follow a "LAST FIRST" (space-separated) convention for individuals.
The "Addr Book Type" field distinguishes "Individual" from "Business Entity".
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Organization, Person

from . import _load_column_for_semantic_path


class ORContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization


class ORExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization


@lru_cache(maxsize=1)
def _contribution_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("contributions", "committee.id"),
        "committee_name": _load_column_for_semantic_path("contributions", "committee.name"),
        "name": _load_column_for_semantic_path("contributions", "donor.org_name"),
        "addr_book_type": _load_column_for_semantic_path("contributions", "or.addr_book_type"),
    }


@lru_cache(maxsize=1)
def _expenditure_fields() -> dict[str, str]:
    return {
        "committee_id": _load_column_for_semantic_path("expenditures", "committee.id"),
        "committee_name": _load_column_for_semantic_path("expenditures", "committee.name"),
        "name": _load_column_for_semantic_path("expenditures", "payee.org_name"),
        "addr_book_type": _load_column_for_semantic_path("expenditures", "or.addr_book_type"),
    }


def _normalized_text(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _extract_committee(row: dict[str, str | None], fields: dict[str, str]) -> Organization:
    """Build an Organization for the filing committee."""
    committee_name = _normalized_text(row.get(fields["committee_name"])) or "Unknown OR Committee"
    committee_id = _normalized_text(row.get(fields["committee_id"]))
    identifiers = {"or_filer_id": committee_id} if committee_id is not None else {}

    return Organization(
        canonical_name=committee_name,
        identifiers=identifiers,
    )


def _is_individual(row: dict[str, str | None], fields: dict[str, str]) -> bool:
    """Check if the row represents an individual based on Addr Book Type."""
    addr_book_type = _normalized_text(row.get(fields["addr_book_type"]))
    if addr_book_type is None:
        return False
    return addr_book_type.lower() == "individual"


def _split_or_name(raw_name: str) -> tuple[str, str]:
    """Split an ORESTAR "LAST FIRST" or "LAST FIRST MIDDLE" name.

    OR convention: the FIRST token is the last name, remaining tokens
    are the first name (and optional middle). For simple two-token names
    like "THOMPSON MARIA", returns ("THOMPSON", "MARIA").

    Returns:
        (last_name, first_name) -- first_name may include middle name tokens
    """
    parts = raw_name.strip().split()
    if len(parts) < 2:
        # Single-word name -- treat as last name with empty first
        return (parts[0] if parts else raw_name, "")

    last_name = parts[0]
    first_name = parts[1]
    return last_name, first_name


def _extract_person_or_org(
    row: dict[str, str | None],
    fields: dict[str, str],
) -> tuple[Person | None, Organization | None]:
    """Extract a Person or Organization from a contributor/payee row.

    Uses "Addr Book Type" to classify:
    - "Individual" -> split "LAST FIRST" name into Person
    - "Business Entity" or anything else -> Organization
    """
    name_value = _normalized_text(row.get(fields["name"]))
    if name_value is None:
        return None, None

    if _is_individual(row, fields):
        last_name, first_name = _split_or_name(name_value)
        if first_name:
            canonical = f"{first_name} {last_name}"
        else:
            canonical = last_name

        return (
            Person(
                canonical_name=canonical,
                first_name=first_name or None,
                last_name=last_name,
            ),
            None,
        )

    # Business Entity or unclassified -- treat as Organization
    return None, Organization(canonical_name=name_value)


def extract_or_contribution(row: dict[str, str | None]) -> ORContributionExtraction:
    """Extract entities from an OR contribution row."""
    fields = _contribution_fields()
    donor_person, donor_org = _extract_person_or_org(row, fields)

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": _extract_committee(row, fields),
    }


def extract_or_expenditure(row: dict[str, str | None]) -> ORExpenditureExtraction:
    """Extract entities from an OR expenditure row."""
    fields = _expenditure_fields()
    payee_person, payee_org = _extract_person_or_org(row, fields)

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "committee": _extract_committee(row, fields),
    }
