"""Shared payload builders for property model tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4


def _payload_with_overrides(defaults: dict[str, object], overrides: dict[str, object]) -> dict[str, object]:
    payload = defaults.copy()
    payload.update(overrides)
    return payload


def build_uuid_string() -> str:
    return str(uuid4())


def build_parcel_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "reid": "123456789",
            "pin": "0821-01-20-1234",
            "site_address": "123 Main St, Durham, NC 27701",
        },
        overrides,
    )


def build_assessment_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "parcel_id": build_uuid_string(),
            "tax_year": 2024,
            "land_assessed_value": Decimal("125000.00"),
            "improvement_assessed_value": Decimal("205000.00"),
            "total_assessed_value": Decimal("330000.00"),
            "assessed_at": date(2024, 1, 1),
        },
        overrides,
    )


def build_ownership_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "parcel_id": build_uuid_string(),
            "owner_name": "Jordan Fields",
            "owner_mail_line1": "PO Box 1001",
            "owner_mail_city": "Durham",
            "owner_mail_state": "NC",
            "owner_mail_zip5": "27701",
            "ownership_recorded_at": date(2024, 1, 15),
        },
        overrides,
    )
