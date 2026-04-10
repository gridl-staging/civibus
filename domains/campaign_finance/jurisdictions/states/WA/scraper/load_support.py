
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from domains.campaign_finance.ingest.text_utils import normalize_optional_text

_normalize_optional_text = normalize_optional_text


def _required_wa_text(value: str | None, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"WA row is missing {field_name}")
    return normalized_value


def _parse_optional_wa_date(raw_value: str | None) -> date | None:
    normalized_value = _normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    for parser in (
        lambda value: date.fromisoformat(value),
        lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).date(),
    ):
        try:
            return parser(normalized_value)
        except ValueError:
            continue

    for date_format in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"WA row has invalid date: {raw_value!r}")


def _parse_required_wa_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_wa_text(raw_value, field_name)
    try:
        normalized_amount = normalized_value.replace(",", "")
        return Decimal(normalized_amount)
    except InvalidOperation as error:
        raise ValueError(f"WA row has invalid {field_name}: {raw_value!r}") from error


def _normalize_support_oppose(value: str | None) -> str | None:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None

    normalized_upper = normalized_value.upper()
    try:
        return {
            "S": "S",
            "FOR": "S",
            "SUPPORT": "S",
            "O": "O",
            "AGAINST": "O",
            "OPPOSE": "O",
            "OPPOSITION": "O",
        }[normalized_upper]
    except KeyError as error:
        raise ValueError(
            f"Unsupported WA independent expenditure support/oppose value: {normalized_value!r}"
        ) from error
