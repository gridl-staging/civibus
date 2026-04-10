"""Shared plugin contract types for domain entity extractors."""

from __future__ import annotations

from typing import Literal, TypedDict
from uuid import UUID


class EntityExtraction(TypedDict):
    entity_type: Literal["person", "organization"]
    name: str
    address: str | None
    identifiers: dict[str, str]
    source_record_id: UUID | None


def coerce_optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
