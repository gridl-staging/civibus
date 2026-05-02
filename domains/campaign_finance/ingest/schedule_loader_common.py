
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from domains.campaign_finance.ingest.text_utils import normalize_optional_text

_normalize_optional_text = normalize_optional_text


def validate_batch_size(batch_size: int) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")


def json_compatible_raw_fields(row: Mapping[str, object]) -> dict[str, object]:
    raw_fields: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            raw_fields[key] = str(value)
        elif isinstance(value, date):
            raw_fields[key] = value.isoformat()
        else:
            raw_fields[key] = value
    return raw_fields


@dataclass(frozen=True, slots=True)
class ScheduleLoaderFieldParsers:

    loader_label: str

    def require_text(self, row: Mapping[str, object], field_name: str) -> str:
        value = _normalize_optional_text(row.get(field_name))
        if value is None:
            raise ValueError(f"{field_name} is required for {self.loader_label} ingest")
        return value

    def require_decimal(self, row: Mapping[str, object], field_name: str) -> Decimal:
        value = row.get(field_name)
        if not isinstance(value, Decimal):
            raise ValueError(f"{field_name} must be a Decimal for {self.loader_label} ingest")
        return value

    def optional_date(self, row: Mapping[str, object], field_name: str) -> date | None:
        value = row.get(field_name)
        if value is None:
            return None
        if not isinstance(value, date):
            raise ValueError(f"{field_name} must be a date for {self.loader_label} ingest")
        return value

    def normalize_amendment_indicator(self, value: object) -> str:
        normalized_value = _normalize_optional_text(value)
        if normalized_value is None:
            return "N"
        if normalized_value in {"N", "T"}:
            return normalized_value
        if normalized_value in {"A", "A1", "A2", "A3", "A4"}:
            return "A"
        raise ValueError(f"Unsupported {self.loader_label} amendment indicator: {normalized_value!r}")


def create_schedule_loader_field_parsers(loader_label: str) -> ScheduleLoaderFieldParsers:
    return ScheduleLoaderFieldParsers(loader_label=loader_label)


__all__ = [
    "ScheduleLoaderFieldParsers",
    "create_schedule_loader_field_parsers",
    "json_compatible_raw_fields",
    "validate_batch_size",
]
