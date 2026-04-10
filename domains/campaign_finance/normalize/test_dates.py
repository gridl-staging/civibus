"""Tests for campaign-finance date normalization."""

from domains.campaign_finance.normalize.dates import DateResult, parse_date


def test_fec_date() -> None:
    assert parse_date("12252024") == DateResult(value="2024-12-25", is_reliable=True)


def test_iso_passthrough() -> None:
    assert parse_date("2024-12-25") == DateResult(value="2024-12-25", is_reliable=True)


def test_us_slash_format() -> None:
    assert parse_date("12/25/2024") == DateResult(value="2024-12-25", is_reliable=True)


def test_us_short_year_2000s() -> None:
    assert parse_date("12/25/24") == DateResult(value="2024-12-25", is_reliable=True)


def test_us_short_year_1900s() -> None:
    assert parse_date("06/15/99") == DateResult(value="1999-06-15", is_reliable=True)


def test_empty_string() -> None:
    assert parse_date("") == DateResult(value=None, is_reliable=False)


def test_none_input() -> None:
    assert parse_date(None) == DateResult(value=None, is_reliable=False)


def test_all_zeros_invalid() -> None:
    assert parse_date("00000000") == DateResult(value=None, is_reliable=False)


def test_invalid_month_day_range() -> None:
    assert parse_date("99991231") == DateResult(value=None, is_reliable=False)


def test_invalid_calendar_combination() -> None:
    assert parse_date("2023-02-29") == DateResult(value=None, is_reliable=False)


def test_reliable_lower_boundary() -> None:
    assert parse_date("01011970") == DateResult(value="1970-01-01", is_reliable=True)


def test_reliable_upper_boundary() -> None:
    assert parse_date("12312050") == DateResult(value="2050-12-31", is_reliable=True)


def test_unreliable_old_date() -> None:
    assert parse_date("01011900") == DateResult(value="1900-01-01", is_reliable=False)


def test_unreliable_future_date() -> None:
    assert parse_date("01012051") == DateResult(value="2051-01-01", is_reliable=False)


def test_whitespace_only_input() -> None:
    assert parse_date("  ") == DateResult(value=None, is_reliable=False)


def test_junk_input() -> None:
    assert parse_date("not-a-date") == DateResult(value=None, is_reliable=False)
