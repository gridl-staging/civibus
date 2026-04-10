"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar25_pm_2_easy_jurisdiction_expansion/civibus_dev/domains/campaign_finance/jurisdictions/states/FL/scraper/extract.py.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, Organization, Person

from . import _load_column_for_semantic_path

# Keywords that indicate an organization rather than a person
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
    " PC ",
    " GROUP",
    " TRUST",
    " FOUNDATION",
    " COUNCIL",
    " SERVICES",
    " PARTNERS",
    " HOLDINGS",
)

# Pattern: `"LAST, SUFFIX" FIRST` — quotes are literal data in FL exports
_FL_QUOTED_NAME_PATTERN = re.compile(r'^"([^"]+)"\s+(.+)$')


class FLContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    committee: Organization
    address: Address | None


class FLExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


class FLTransferExtraction(TypedDict):
    target_person: Person | None
    target_org: Organization | None
    committee: Organization
    address: Address | None


class FLOtherExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    committee: Organization
    address: Address | None


# --- Cached field lookups ---

# Semantic paths per data type: each maps a uniform key to the config semantic path.
# Contributions use "donor.*"; all others use "payee.*".
_FL_COUNTERPARTY_SEMANTICS: dict[str, dict[str, str]] = {
    "contributions": {
        "name": "donor.name",
        "address": "donor.address.street1",
        "city_state_zip": "donor.address.city_state_zip",
        "occupation": "donor.occupation",
    },
    "expenditures": {
        "name": "payee.name",
        "address": "payee.address.street1",
        "city_state_zip": "payee.address.city_state_zip",
    },
    "transfers": {
        "name": "payee.name",
        "address": "payee.address.street1",
        "city_state_zip": "payee.address.city_state_zip",
    },
    "other": {
        "name": "payee.name",
        "address": "payee.address.street1",
        "city_state_zip": "payee.address.city_state_zip",
    },
}


@lru_cache(maxsize=None)
def _fields_for_data_type(data_type: str) -> dict[str, str]:
    """Resolve CSV column names for a data type's semantic paths."""
    paths = _FL_COUNTERPARTY_SEMANTICS[data_type]
    result = {"committee_name": _load_column_for_semantic_path(data_type, "committee.name")}
    for key, semantic_path in paths.items():
        result[key] = _load_column_for_semantic_path(data_type, semantic_path)
    return result


# --- Shared parsing helpers ---


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _title_case_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


def _parse_city_state_zip(composite: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse FL composite 'City, State Zip' field into (city, state, zip5).

    Examples:
        'ATLANTIC BEACH, FL 32233' -> ('ATLANTIC BEACH', 'FL', '32233')
        'SAINT-LAURENT, XC 00000' -> ('SAINT-LAURENT', 'XC', '00000')
        'MIAMI, FL 33143' -> ('MIAMI', 'FL', '33143')
    """
    normalized = _normalized_text(composite)
    if normalized is None:
        return None, None, None

    # Expected format: "CITY, ST ZIP" or "CITY, ST ZIP-ZIP4"
    comma_index = normalized.rfind(",")
    if comma_index < 0:
        return normalized, None, None

    city = normalized[:comma_index].strip() or None
    remainder = normalized[comma_index + 1 :].strip()

    parts = remainder.split()
    if len(parts) >= 2:
        state = parts[0].upper()
        raw_zip = parts[1]
        # Extract zip5 from potential zip5-zip4
        zip5 = raw_zip.split("-")[0] if raw_zip else None
        return city, state, zip5
    if len(parts) == 1:
        return city, parts[0].upper(), None

    return city, None, None


def _build_address(
    *,
    street1: str | None,
    city_state_zip: str | None,
) -> Address | None:
    """Build an Address from FL row fields."""
    normalized_street = _normalized_text(street1)
    city, state, zip5 = _parse_city_state_zip(city_state_zip)

    if not any((normalized_street, city, state, zip5)):
        return None

    raw_parts = [p for p in (normalized_street, city, state, zip5) if p]
    return Address(
        raw_address=", ".join(raw_parts),
        city=city,
        state=state,
        zip5=zip5,
    )


def _looks_like_organization_name(name: str | None) -> bool:
    """Heuristic: does the name look like an organization rather than a person?"""
    normalized = _normalized_text(name)
    if normalized is None:
        return False

    upper = f" {normalized.upper()} "
    if any(keyword in upper for keyword in _ORGANIZATION_KEYWORDS):
        return True

    # Names starting with a digit are likely orgs (e.g., "1 SOUTH DADE")
    if normalized[0].isdigit():
        return True

    # No comma means no "Last, First" pattern — treat as org if single token
    if "," not in normalized and '"' not in normalized and len(normalized.split()) == 1:
        return True

    return False


def _classify_name_as_person_or_org(
    name_raw: str | None,
) -> tuple[Person | None, Organization | None]:
    """Classify a normalized name as either a Person or Organization.

    Used by expenditure, transfer, and other extractors which share the same
    person/org classification logic (contributions have extra occupation handling).
    """
    if _looks_like_organization_name(name_raw):
        if name_raw is not None:
            return None, Organization(canonical_name=name_raw)
        return None, None

    person = _parse_fl_contributor_name(name_raw)
    if person is None and name_raw is not None:
        # Fallback: treat as org if name parsing didn't produce a person
        return None, Organization(canonical_name=name_raw)
    return person, None


def _parse_fl_contributor_name(raw: str | None) -> Person | None:
    """Parse FL-specific name formats into a Person.

    FL uses `"LAST, SUFFIX" FIRST` where quotes are literal data.
    Also handles plain `LAST, FIRST` and skips org-like names.
    """
    normalized = _normalized_text(raw)
    if normalized is None:
        return None

    if _looks_like_organization_name(normalized):
        return None

    # Try FL quoted pattern: `"LAST, SUFFIX" FIRST`
    match = _FL_QUOTED_NAME_PATTERN.match(normalized)
    if match:
        inside_quotes = match.group(1).strip()
        first_part = match.group(2).strip()

        # Inside quotes: "LAST, SUFFIX" or just "LAST"
        if "," in inside_quotes:
            last_name_raw, suffix_raw = inside_quotes.split(",", maxsplit=1)
            last_name = _title_case_name(last_name_raw.strip())
            suffix = suffix_raw.strip() or None
        else:
            last_name = _title_case_name(inside_quotes)
            suffix = None

        first_name = _title_case_name(first_part.split()[0])
        canonical = f"{first_name} {last_name}".strip()
        return Person(
            canonical_name=canonical,
            first_name=first_name,
            last_name=last_name,
            suffix=suffix,
        )

    # Plain comma-separated: "LAST, FIRST ..."
    if "," in normalized:
        last_part, first_part = normalized.split(",", maxsplit=1)
        last_name = _title_case_name(last_part.strip())
        first_name = _title_case_name(first_part.strip().split()[0])
        canonical = f"{first_name} {last_name}".strip()
        return Person(
            canonical_name=canonical,
            first_name=first_name,
            last_name=last_name,
        )

    return None


# --- Per-type extractors ---


def extract_fl_contribution(row: dict[str, str | None]) -> FLContributionExtraction:
    fields = _fields_for_data_type("contributions")
    donor_name_raw = row.get(fields["name"])
    occupation = _normalized_text(row.get(fields["occupation"]))

    donor_person = _parse_fl_contributor_name(donor_name_raw)
    donor_org: Organization | None = None

    if donor_person is not None:
        # Attach occupation as an identifier
        identifiers: dict[str, str] = {}
        if occupation is not None:
            identifiers["occupation"] = occupation
        donor_person = Person(
            canonical_name=donor_person.canonical_name,
            first_name=donor_person.first_name,
            last_name=donor_person.last_name,
            suffix=donor_person.suffix,
            identifiers=identifiers,
        )
    elif _normalized_text(donor_name_raw) is not None:
        donor_org = Organization(canonical_name=_normalized_text(donor_name_raw))  # type: ignore[arg-type]

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "committee": Organization(canonical_name=_normalized_text(row.get(fields["committee_name"])) or ""),
        "address": _build_address(
            street1=row.get(fields["address"]),
            city_state_zip=row.get(fields["city_state_zip"]),
        ),
    }


# Mapping from data type to the dict keys used in its TypedDict return type.
_FL_COUNTERPARTY_KEYS: dict[str, tuple[str, str]] = {
    "expenditures": ("payee_person", "payee_org"),
    "transfers": ("target_person", "target_org"),
    "other": ("payee_person", "payee_org"),
}


def _extract_fl_counterparty(
    row: dict[str, str | None],
    data_type: str,
) -> dict[str, Person | Organization | Address | None]:
    """Shared extractor for expenditure, transfer, and other rows.

    These three types share identical logic: classify the counterparty name
    as person or org, then build committee + address.
    """
    fields = _fields_for_data_type(data_type)
    person_key, org_key = _FL_COUNTERPARTY_KEYS[data_type]

    name_raw = _normalized_text(row.get(fields["name"]))
    person, org = _classify_name_as_person_or_org(name_raw)

    return {
        person_key: person,
        org_key: org,
        "committee": Organization(canonical_name=_normalized_text(row.get(fields["committee_name"])) or ""),
        "address": _build_address(
            street1=row.get(fields["address"]),
            city_state_zip=row.get(fields["city_state_zip"]),
        ),
    }


def extract_fl_expenditure(row: dict[str, str | None]) -> FLExpenditureExtraction:
    """Extract entities from an FL expenditure row."""
    return _extract_fl_counterparty(row, "expenditures")  # type: ignore[return-value]


def extract_fl_transfer(row: dict[str, str | None]) -> FLTransferExtraction:
    """Extract entities from an FL transfer row."""
    return _extract_fl_counterparty(row, "transfers")  # type: ignore[return-value]


def extract_fl_other(row: dict[str, str | None]) -> FLOtherExtraction:
    """Extract entities from an FL other disbursement row."""
    return _extract_fl_counterparty(row, "other")  # type: ignore[return-value]
