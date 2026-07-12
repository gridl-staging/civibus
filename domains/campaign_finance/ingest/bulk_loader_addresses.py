from __future__ import annotations


import logging
from uuid import UUID

import psycopg

from core.db import insert_entity_address, insert_entity_source, upsert_address
from core.types.python.models import Address, validate_optional_state_code
from domains.campaign_finance.ingest.text_utils import normalize_optional_text

LOGGER = logging.getLogger(__name__)


def _normalize_zip_parts(zip_code: str | None) -> tuple[str | None, str | None]:
    normalized_zip = normalize_optional_text(zip_code)
    if normalized_zip is None:
        return None, None

    digits_only = "".join(character for character in normalized_zip if character.isdigit())
    if len(digits_only) >= 9:
        return digits_only[:5], digits_only[5:9]
    if len(digits_only) >= 5:
        return digits_only[:5], None
    return None, None


def _normalize_optional_state_code(value: object) -> str | None:
    normalized_state = normalize_optional_text(value)
    if normalized_state is None:
        return None
    try:
        return validate_optional_state_code(normalized_state, field_name="state")
    except ValueError:
        LOGGER.warning("Dropping invalid FEC state code %r", normalized_state)
        return None


def _build_fec_mailing_address(
    street_line_1: object,
    street_line_2: object,
    city: object,
    state: object,
    zip_code: object,
) -> Address | None:
    normalized_street_line_1 = normalize_optional_text(street_line_1)
    normalized_street_line_2 = normalize_optional_text(street_line_2)
    normalized_city = normalize_optional_text(city)
    normalized_state = _normalize_optional_state_code(state)
    normalized_zip = normalize_optional_text(zip_code)

    if (
        normalized_street_line_1 is None
        and normalized_street_line_2 is None
        and normalized_city is None
        and normalized_state is None
        and normalized_zip is None
    ):
        return None

    zip5, zip4 = _normalize_zip_parts(normalized_zip)

    address_parts = [part for part in (normalized_street_line_1, normalized_street_line_2) if part is not None]
    locality_parts = [part for part in (normalized_city, normalized_state) if part is not None]
    if zip5 is not None:
        formatted_zip = f"{zip5}-{zip4}" if zip4 is not None else zip5
        locality_parts.append(formatted_zip)

    if locality_parts:
        address_parts.append(" ".join(locality_parts))

    raw_address = ", ".join(address_parts)
    if not raw_address:
        return None

    return Address(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=zip5,
        zip4=zip4,
    )


def _link_row_mailing_address(
    conn: psycopg.Connection,
    *,
    raw_row: dict[str, object],
    field_prefix: str,
    entity_type: str,
    entity_id: UUID,
    source_record_id: UUID,
    extraction_role: str,
) -> None:
    mailing_address = _build_fec_mailing_address(
        raw_row.get(f"{field_prefix}_ST1"),
        raw_row.get(f"{field_prefix}_ST2"),
        raw_row.get(f"{field_prefix}_CITY"),
        raw_row.get(f"{field_prefix}_ST"),
        raw_row.get(f"{field_prefix}_ZIP"),
    )
    if mailing_address is None:
        return

    address_id = upsert_address(conn, mailing_address)
    insert_entity_source(conn, "address", address_id, source_record_id, extraction_role)
    insert_entity_address(conn, entity_type, entity_id, address_id, source_record_id, "mailing")


__all__ = [
    "_build_fec_mailing_address",
    "_link_row_mailing_address",
    "_normalize_optional_state_code",
    "_normalize_zip_parts",
]
