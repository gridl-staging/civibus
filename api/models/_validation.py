from __future__ import annotations

from datetime import date
from decimal import Decimal


def validate_inclusive_bounds(
    min_value: date | Decimal | float | None,
    max_value: date | Decimal | float | None,
    *,
    min_name: str,
    max_name: str,
) -> None:
    if min_value is None or max_value is None:
        return
    if min_value > max_value:
        raise ValueError(f"{min_name} must be less than or equal to {max_name}")
