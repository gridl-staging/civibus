"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/entity_extractors/extract.py.
"""

from core.types.python.extraction import EntityExtraction, coerce_optional_uuid
from core.types.python.models import Address, Organization, Person

from .name_parser import parse_fec_name


def extract_contribution(contribution: dict) -> dict:
    """Extract entities from a single FEC contribution dict.

    Returns {"person": Person | None, "organization": Organization, "address": Address | None}.
    Person is None when entity_type != "IND".
    Address is None when contributor_state is missing.
    """
    return {
        "person": _extract_person(contribution),
        "organization": _extract_organization(contribution),
        "address": _extract_address(contribution),
    }


def extract_entities(raw_record: dict) -> list[EntityExtraction]:
    """Contract-compatible extractor for domain plugin consumers."""
    extracted = extract_contribution(raw_record)
    address = extracted["address"]
    address_text = address.raw_address if address is not None else None
    source_record_id = coerce_optional_uuid(raw_record.get("source_record_id"))

    organization = extracted["organization"]
    entities: list[EntityExtraction] = [
        {
            "entity_type": "organization",
            "name": organization.canonical_name,
            "address": address_text,
            "identifiers": organization.identifiers,
            "source_record_id": source_record_id,
        }
    ]

    person = extracted["person"]
    if person is not None:
        entities.append(
            {
                "entity_type": "person",
                "name": person.canonical_name,
                "address": address_text,
                "identifiers": person.identifiers,
                "source_record_id": source_record_id,
            }
        )

    return entities


def _extract_person(c: dict) -> Person | None:
    if c.get("entity_type") != "IND":
        return None

    first, middle, last, suffix = _resolve_person_name_parts(c)
    if not first and not last:
        return None

    # Build canonical_name: title-cased, first-last order
    parts = [p for p in [first, middle, last] if p]
    canonical_name = " ".join(p.title() for p in parts)

    # Identifiers: employer + occupation when present
    identifiers: dict[str, str] = {}
    employer = c.get("contributor_employer")
    occupation = c.get("contributor_occupation")
    if employer:
        identifiers["employer"] = employer
    if occupation:
        identifiers["occupation"] = occupation

    return Person(
        canonical_name=canonical_name,
        first_name=first,
        last_name=last,
        middle_name=middle,
        suffix=suffix,
        identifiers=identifiers,
    )


def _resolve_person_name_parts(c: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve person name fields, filling missing pre-parsed parts from contributor_name."""
    first = c.get("contributor_first_name")
    last = c.get("contributor_last_name")
    middle = c.get("contributor_middle_name")
    suffix = c.get("contributor_suffix")

    # Prefer pre-parsed values when present, but recover missing fields from the raw combined name.
    if any(part in (None, "") for part in (first, middle, last, suffix)):
        parsed = parse_fec_name(c.get("contributor_name"))
        if parsed is not None:
            first = first or parsed["first_name"]
            middle = middle or parsed["middle_name"]
            last = last or parsed["last_name"]
            suffix = suffix or parsed["suffix"]

    return first, middle, last, suffix


def _extract_organization(c: dict) -> Organization:
    committee_id = c.get("committee_id")
    # committee_name flat field is often None in live data; fall back to nested committee.name
    committee_name = c.get("committee_name")
    committee_obj = c.get("committee") or {}
    if not committee_name:
        committee_name = committee_obj.get("name", "")

    # Derive org_type from nested committee_type_full
    org_type = None
    committee_type_full = committee_obj.get("committee_type_full")
    if committee_type_full:
        org_type = committee_type_full.lower()

    identifiers: dict[str, str] = {}
    if committee_id:
        identifiers["fec_committee_id"] = committee_id

    return Organization(
        canonical_name=committee_name,
        org_type=org_type,
        identifiers=identifiers,
    )


def _normalize_zip_parts(value: object) -> tuple[str | None, str | None, str | None]:
    normalized_zip = str(value).strip() if value is not None else ""
    if not normalized_zip:
        return None, None, None

    if any(character.isalpha() for character in normalized_zip):
        return None, None, normalized_zip

    digits_only = "".join(character for character in normalized_zip if character.isdigit())
    zip5 = digits_only[:5] if len(digits_only) >= 5 else None
    zip4 = digits_only[5:9] if len(digits_only) >= 9 else None
    return zip5, zip4, normalized_zip


def _extract_address(c: dict) -> Address | None:
    state = c.get("contributor_state")
    if not state:
        return None

    city = c.get("contributor_city")
    zip5, zip4, raw_zip = _normalize_zip_parts(c.get("contributor_zip"))

    # Assemble raw_address from non-empty parts
    street1 = c.get("contributor_street_1") or ""
    street2 = c.get("contributor_street_2") or ""

    parts: list[str] = []
    if street1.strip():
        parts.append(street1.strip())
    if street2.strip():
        parts.append(street2.strip())
    if city:
        parts.append(city)

    # State + zip5 go together
    state_zip = state
    if zip5:
        state_zip = f"{state} {zip5}"
    elif raw_zip:
        state_zip = f"{state} {raw_zip}"
    parts.append(state_zip)

    raw_address = ", ".join(parts)

    return Address(
        raw_address=raw_address,
        city=city,
        state=state,
        zip5=zip5,
        zip4=zip4,
    )
