"""Extract Person, Organization, and Address from Durham ArcGIS parcel records."""

from __future__ import annotations

from typing import TypedDict

from core.types.python.extraction import EntityExtraction, coerce_optional_uuid
from core.types.python.models import Address, Organization, Person

from domains.property.normalize.owners import (
    OwnerKind,
    classify_owner,
    normalize_mailing_address,
    normalize_owner_name,
    split_joint_owners,
)


class OwnerExtraction(TypedDict):
    person: Person | None
    organization: Organization | None
    persons: list[Person]
    address: Address | None


def extract_owner(raw_record: dict[str, object]) -> OwnerExtraction:
    """Extract core-model owner objects from a Durham ArcGIS parcel record.

    Returns person/organization/address objects based on the PROPERTY_OWNER
    classification. Joint owners produce multiple entries in the `persons` list.
    """
    raw_owner = str(raw_record.get("PROPERTY_OWNER") or "").strip()
    owner_kind = classify_owner(raw_owner)
    address = _extract_mailing_address(raw_record)

    if owner_kind == OwnerKind.ORGANIZATION:
        organization = Organization(
            canonical_name=normalize_owner_name(raw_owner),
            identifiers={"owner_name_as_filed": raw_owner},
        )
        return OwnerExtraction(
            person=None,
            organization=organization,
            persons=[],
            address=address,
        )

    # Person (possibly joint owners)
    persons = [_person_from_owner_segment(owner_name) for owner_name in split_joint_owners(raw_owner)]

    return OwnerExtraction(
        person=persons[0] if persons else None,
        organization=None,
        persons=persons,
        address=address,
    )


def extract_entities(raw_record: dict[str, object]) -> list[EntityExtraction]:
    """Contract-compatible extractor for domain plugin consumers.

    Returns EntityExtraction payloads for each entity found in the record.
    REID/PIN are parcel identifiers and flow through source_record_id provenance,
    not through EntityExtraction.identifiers.
    """
    owner_result = extract_owner(raw_record)
    source_record_id = coerce_optional_uuid(raw_record.get("source_record_id"))
    address_text = owner_result["address"].raw_address if owner_result["address"] else None

    entities: list[EntityExtraction] = []

    if owner_result["organization"] is not None:
        org = owner_result["organization"]
        entities.append(
            EntityExtraction(
                entity_type="organization",
                name=org.canonical_name,
                address=address_text,
                identifiers=org.identifiers,
                source_record_id=source_record_id,
            )
        )

    for person in owner_result["persons"]:
        entities.append(
            EntityExtraction(
                entity_type="person",
                name=person.canonical_name,
                address=address_text,
                identifiers=person.identifiers,
                source_record_id=source_record_id,
            )
        )

    return entities


def _extract_mailing_address(raw_record: dict[str, object]) -> Address | None:
    """Build a core Address from Durham OWNER_MAIL_* fields."""
    normalized = normalize_mailing_address(
        mail_1=_str_or_none(raw_record.get("OWNER_MAIL_1")),
        mail_2=_str_or_none(raw_record.get("OWNER_MAIL_2")),
        mail_3=_str_or_none(raw_record.get("OWNER_MAIL_3")),
        city=_str_or_none(raw_record.get("OWNER_MAIL_CITY")),
        state=_str_or_none(raw_record.get("OWNER_MAIL_STATE")),
        zip_code=_str_or_none(raw_record.get("OWNER_MAIL_ZIP")),
    )
    if normalized is None:
        return None

    return Address(
        raw_address=normalized["raw_address"],
        city=normalized["city"],
        state=normalized["state"],
        zip5=normalized["zip5"],
    )


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _person_from_owner_segment(owner_name_as_filed: str) -> Person:
    return Person(
        canonical_name=normalize_owner_name(owner_name_as_filed),
        identifiers={"owner_name_as_filed": owner_name_as_filed.strip()},
    )
