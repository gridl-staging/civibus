"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/normalize/dates.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


_EARLIEST_RELIABLE_DATE = date(1970, 1, 1)
_LATEST_RELIABLE_DATE = date(2050, 12, 31)


@dataclass(frozen=True)
class DateResult:
    value: str | None
    is_reliable: bool


def parse_date(raw: str | None) -> DateResult:
    cleaned = _clean_input(raw)
    if cleaned is None:
        return DateResult(value=None, is_reliable=False)

    for parser in (_parse_fec_date, _parse_iso_date, _parse_us_date):
        parsed_date = parser(cleaned)
        if parsed_date is None:
            continue
        return DateResult(
            value=parsed_date.isoformat(),
            is_reliable=_is_reliable(parsed_date),
        )

    return DateResult(value=None, is_reliable=False)


def _clean_input(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _parse_fec_date(value: str) -> date | None:
    if len(value) != 8 or not value.isdigit():
        return None

    month = int(value[:2])
    day = int(value[2:4])
    year = int(value[4:])
    return _build_date(month=month, day=day, year=year)


def _parse_iso_date(value: str) -> date | None:
    parts = _split_date_parts(value, "-")
    if parts is None:
        return None
    year_text, month_text, day_text = parts

    if not (
        len(year_text) == 4
        and len(month_text) == 2
        and len(day_text) == 2
        and year_text.isdigit()
        and month_text.isdigit()
        and day_text.isdigit()
    ):
        return None

    return _build_date(
        month=int(month_text),
        day=int(day_text),
        year=int(year_text),
    )


def _parse_us_date(value: str) -> date | None:
    parts = _split_date_parts(value, "/")
    if parts is None:
        return None
    month_text, day_text, year_text = parts
    if not (month_text.isdigit() and day_text.isdigit() and year_text.isdigit()):
        return None

    year = int(year_text)
    if len(year_text) == 2:
        year = _expand_short_year(year)
    elif len(year_text) != 4:
        return None

    if not (1 <= len(month_text) <= 2 and 1 <= len(day_text) <= 2):
        return None

    return _build_date(month=int(month_text), day=int(day_text), year=year)


def _split_date_parts(value: str, separator: str) -> tuple[str, str, str] | None:
    parts = value.split(separator)
    if len(parts) != 3:
        return None
    first_part, second_part, third_part = parts
    return first_part, second_part, third_part


def _expand_short_year(short_year: int) -> int:
    if short_year < 50:
        return 2000 + short_year
    return 1900 + short_year


def _build_date(*, month: int, day: int, year: int) -> date | None:
    try:
        return date(year=year, month=month, day=day)
    except ValueError:
        return None


def _is_reliable(parsed_date: date) -> bool:
    return _EARLIEST_RELIABLE_DATE <= parsed_date <= _LATEST_RELIABLE_DATE
