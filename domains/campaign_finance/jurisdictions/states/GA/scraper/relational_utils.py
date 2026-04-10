from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Mapping

from core.types.python.models import compute_record_hash
from domains.campaign_finance.ingest.text_utils import normalize_optional_text

from .parse import parse_ga_date

_normalize_optional_text = normalize_optional_text


def require_ga_text(value: object, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"GA row is missing {field_name}")
    return normalized_value


def ga_source_record_key(row: Mapping[str, object]) -> str:
    return compute_record_hash(json_compatible_raw_fields(row))


def parse_ga_row_date(raw_value: object) -> date | None:
    normalized_value = _normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    try:
        parsed_value = parse_ga_date(normalized_value)
        if parsed_value is None:
            return None
        return date.fromisoformat(parsed_value)
    except ValueError:
        return date.fromisoformat(normalized_value)


def ga_contributor_name(row: Mapping[str, object]) -> str | None:
    first_name = _normalize_optional_text(row.get("FirstName"))
    last_name = _normalize_optional_text(row.get("LastName"))
    joined_name = " ".join(name for name in (first_name, last_name) if name is not None)
    return _normalize_optional_text(joined_name) or last_name


def json_compatible_raw_fields(row: Mapping[str, object]) -> dict[str, object]:
    raw_fields: dict[str, object] = {}
    for key, value in row.items():
        raw_fields[key] = str(value) if isinstance(value, Decimal) else value
    return raw_fields
