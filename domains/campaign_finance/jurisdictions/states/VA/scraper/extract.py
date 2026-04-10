"""Virginia campaign finance entity extraction.

Extracts Person, Organization, and Address entities from parsed VA CSV rows.
Uses the VA-specific IsIndividual field (string 'True'/'False') to decide
whether a row represents an individual or organization donor/payee.

Contribution rows (ScheduleA) produce donor entities.
Expenditure rows (ScheduleD) produce payee entities.
"""

from __future__ import annotations

from typing import TypedDict

from core.types.python.models import Address, Organization, Person


class VAContributionExtraction(TypedDict):
    """Typed dict for entities extracted from a VA ScheduleA (contribution) row."""

    donor_person: Person | None
    donor_org: Organization | None
    address: Address | None
    report_id: str | None


class VAExpenditureExtraction(TypedDict):
    """Typed dict for entities extracted from a VA ScheduleD (expenditure) row."""

    payee_person: Person | None
    payee_org: Organization | None
    address: Address | None
    report_id: str | None
    item_or_service: str | None


def extract_va_contribution(row: dict[str, str | None]) -> VAContributionExtraction:
    """Extract donor entities from a parsed VA ScheduleA row.

    Uses IsIndividual to determine person vs. org. For individuals,
    builds a Person from FirstName/MiddleName/LastOrCompanyName.
    For organizations, builds an Organization from LastOrCompanyName.
    """
    is_individual = _parse_is_individual(row.get("IsIndividual"))

    donor_person: Person | None = None
    donor_org: Organization | None = None

    if is_individual:
        donor_person = _build_person(
            first_name=row.get("FirstName"),
            middle_name=row.get("MiddleName"),
            last_name=row.get("LastOrCompanyName"),
            suffix=row.get("Suffix"),
            occupation=row.get("OccupationOrTypeOfBusiness"),
            employer=row.get("NameOfEmployer"),
        )
    else:
        # For non-individuals, LastOrCompanyName is the org name
        org_name = _normalized_text(row.get("LastOrCompanyName"))
        if org_name is not None:
            donor_org = Organization(canonical_name=org_name)

    return {
        "donor_person": donor_person,
        "donor_org": donor_org,
        "address": _extract_address(
            street1=row.get("AddressLine1"),
            street2=row.get("AddressLine2"),
            city=row.get("City"),
            state=row.get("StateCode"),
            raw_zip=row.get("ZipCode"),
        ),
        "report_id": _normalized_text(row.get("ReportId")),
    }


def extract_va_expenditure(row: dict[str, str | None]) -> VAExpenditureExtraction:
    """Extract payee entities from a parsed VA ScheduleD row.

    Same IsIndividual logic as contributions, but keys are payee_person/payee_org.
    Also captures ItemOrService for transaction description.
    """
    is_individual = _parse_is_individual(row.get("IsIndividual"))

    payee_person: Person | None = None
    payee_org: Organization | None = None

    if is_individual:
        payee_person = _build_person(
            first_name=row.get("FirstName"),
            middle_name=row.get("MiddleName"),
            last_name=row.get("LastOrCompanyName"),
            suffix=row.get("Suffix"),
            # Expenditure rows don't have occupation/employer columns
            occupation=None,
            employer=None,
        )
    else:
        org_name = _normalized_text(row.get("LastOrCompanyName"))
        if org_name is not None:
            payee_org = Organization(canonical_name=org_name)

    return {
        "payee_person": payee_person,
        "payee_org": payee_org,
        "address": _extract_address(
            street1=row.get("AddressLine1"),
            street2=row.get("AddressLine2"),
            city=row.get("City"),
            state=row.get("StateCode"),
            raw_zip=row.get("ZipCode"),
        ),
        "report_id": _normalized_text(row.get("ReportId")),
        "item_or_service": _normalized_text(row.get("ItemOrService")),
    }


def _parse_is_individual(value: str | None) -> bool:
    """Parse the VA IsIndividual field.

    VA uses string 'True'/'False' rather than a native boolean.
    Defaults to False (organization) when the field is missing or empty.
    """
    normalized = _normalized_text(value)
    if normalized is None:
        return False
    return normalized.lower() == "true"


def _build_person(
    *,
    first_name: str | None,
    middle_name: str | None,
    last_name: str | None,
    suffix: str | None,
    occupation: str | None,
    employer: str | None,
) -> Person | None:
    """Build a Person from VA name parts.

    VA splits names into FirstName, MiddleName, LastOrCompanyName, Suffix.
    Returns None if we can't construct a meaningful canonical name.
    """
    normalized_first = _normalized_text(first_name)
    normalized_middle = _normalized_text(middle_name)
    normalized_last = _normalized_text(last_name)
    normalized_suffix = _normalized_text(suffix)
    normalized_occupation = _normalized_text(occupation)
    normalized_employer = _normalized_text(employer)

    # Need at least a last name to build a meaningful person
    if normalized_last is None:
        return None

    # Build canonical name from available parts
    name_parts = []
    if normalized_first:
        name_parts.append(normalized_first)
    if normalized_middle:
        name_parts.append(normalized_middle)
    name_parts.append(normalized_last)
    if normalized_suffix:
        name_parts.append(normalized_suffix)

    canonical_name = " ".join(name_parts)

    identifiers: dict[str, str] = {}
    if normalized_occupation:
        identifiers["occupation"] = normalized_occupation
    if normalized_employer:
        identifiers["employer"] = normalized_employer

    return Person(
        canonical_name=canonical_name,
        first_name=normalized_first,
        middle_name=normalized_middle,
        last_name=normalized_last,
        suffix=normalized_suffix,
        identifiers=identifiers,
    )


def _extract_address(
    *,
    street1: str | None,
    street2: str | None,
    city: str | None,
    state: str | None,
    raw_zip: str | None,
) -> Address | None:
    """Build an Address from VA address fields.

    Returns None if all fields are empty/missing.
    State codes are already two-letter in VA data (StateCode field).
    """
    normalized_street1 = _normalized_text(street1)
    normalized_street2 = _normalized_text(street2)
    normalized_city = _normalized_text(city)
    normalized_state = _normalize_state_code(state)
    normalized_zip = _normalize_zip5(raw_zip)

    # If everything is empty, don't create an address
    if not any((normalized_street1, normalized_city, normalized_state, normalized_zip)):
        return None

    # Build raw address string from available parts
    raw_parts = [
        part
        for part in (normalized_street1, normalized_street2, normalized_city, normalized_state, normalized_zip)
        if part
    ]
    raw_address = ", ".join(raw_parts)

    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=normalized_zip,
    )


def _normalize_state_code(value: str | None) -> str | None:
    """Normalize a state value to a two-letter uppercase code.

    VA data typically already uses two-letter codes in the StateCode field,
    but we handle edge cases just in case.
    """
    normalized = _normalized_text(value)
    if normalized is None:
        return None

    upper_value = normalized.upper()
    # VA data uses two-letter codes directly
    if len(upper_value) == 2:
        return upper_value

    return None


def _normalize_zip5(value: str | None) -> str | None:
    """Extract the first 5 digits from a zip code value.

    Handles ZIP+4 formats like '23666-1234' and plain '23666'.
    Returns None if fewer than 5 digits are present.
    """
    normalized = _normalized_text(value)
    if normalized is None:
        return None

    digits = "".join(character for character in normalized if character.isdigit())
    if len(digits) < 5:
        return None
    return digits[:5]


def _normalized_text(value: str | None) -> str | None:
    """Strip whitespace and convert empty strings to None."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return normalized
