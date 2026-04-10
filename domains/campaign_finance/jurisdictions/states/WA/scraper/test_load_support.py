from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from domains.campaign_finance.jurisdictions.states.WA.scraper import load_support


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("2025-04-15", date(2025, 4, 15)),
        ("2025-04-15T00:00:00.000", date(2025, 4, 15)),
        ("04/15/2025", date(2025, 4, 15)),
    ],
)
def test_parse_optional_wa_date_accepts_supported_formats(raw_value: str, expected: date) -> None:
    assert load_support._parse_optional_wa_date(raw_value) == expected


def test_parse_optional_wa_date_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="WA row has invalid date"):
        load_support._parse_optional_wa_date("not-a-date")


def test_parse_required_wa_amount_accepts_commas() -> None:
    assert load_support._parse_required_wa_amount("1,234.50", "Amount") == Decimal("1234.50")


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [("For", "S"), ("Against", "O"), ("support", "S"), ("opposition", "O"), ("neutral", None), (None, None)],
)
def test_normalize_support_oppose_maps_wa_values(raw_value: str | None, expected: str | None) -> None:
    if raw_value == "neutral":
        with pytest.raises(ValueError, match="Unsupported WA independent expenditure support/oppose value"):
            load_support._normalize_support_oppose(raw_value)
        return
    assert load_support._normalize_support_oppose(raw_value) == expected
