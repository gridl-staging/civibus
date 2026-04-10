"""Tests for campaign-finance address normalization."""

import pytest

from domains.campaign_finance.normalize.addresses import (
    NormalizedAddress,
    is_valid_zip5,
    normalize_address,
    normalize_state,
)


def test_zip5_only() -> None:
    normalized = normalize_address(zip="27406")
    assert normalized.zip5 == "27406"
    assert normalized.zip4 is None


def test_zip9_packed_fec() -> None:
    normalized = normalize_address(zip="274069005")
    assert normalized.zip5 == "27406"
    assert normalized.zip4 == "9005"


def test_zip9_hyphenated() -> None:
    normalized = normalize_address(zip="27406-9005")
    assert normalized.zip5 == "27406"
    assert normalized.zip4 == "9005"


def test_malformed_short_zip() -> None:
    normalized = normalize_address(zip="123")
    assert normalized.zip5 is None
    assert normalized.zip4 is None


def test_none_zip() -> None:
    normalized = normalize_address(zip=None)
    assert normalized.zip5 is None
    assert normalized.zip4 is None


def test_state_abbreviation_passthrough() -> None:
    assert normalize_state("NC") == "NC"


def test_state_full_name() -> None:
    assert normalize_state("North Carolina") == "NC"


def test_state_case_insensitive() -> None:
    assert normalize_state("north carolina") == "NC"


def test_state_dc_and_territory() -> None:
    assert normalize_state("District of Columbia") == "DC"
    assert normalize_state("Puerto Rico") == "PR"


def test_state_unrecognized() -> None:
    assert normalize_state("Freedonia") is None


def test_apt_style_unit() -> None:
    normalized = normalize_address(street="123 MAIN ST APT 4B")
    assert normalized.street_number == "123"
    assert normalized.street_name == "MAIN ST"
    assert normalized.unit == "APT 4B"


def test_ste_style_unit() -> None:
    normalized = normalize_address(street="500 OAK AVE STE 100")
    assert normalized.street_number == "500"
    assert normalized.street_name == "OAK AVE"
    assert normalized.unit == "STE 100"


def test_hash_style_unit() -> None:
    normalized = normalize_address(street="410 MARKET ST #12")
    assert normalized.street_number == "410"
    assert normalized.street_name == "MARKET ST"
    assert normalized.unit == "# 12"


def test_no_unit_present() -> None:
    normalized = normalize_address(street="5075 MILLPOINT RD")
    assert normalized.unit is None


def test_standard_street_with_number() -> None:
    normalized = normalize_address(street="5075 MILLPOINT RD")
    assert normalized.street_number == "5075"
    assert normalized.street_name == "MILLPOINT RD"


def test_street_number_with_alpha_suffix_preserved() -> None:
    normalized = normalize_address(street="123a main st")
    assert normalized.street_number == "123A"
    assert normalized.street_name == "MAIN ST"


def test_street_without_number() -> None:
    normalized = normalize_address(street="PALLADIAN CORPORATE CENTER")
    assert normalized.street_number is None
    assert normalized.street_name == "PALLADIAN CORPORATE CENTER"


def test_junk_street_values() -> None:
    information_requested = normalize_address(street="INFORMATION REQUESTED")
    assert information_requested.street_number is None
    assert information_requested.street_name is None
    assert information_requested.unit is None

    not_available = normalize_address(street="n/a")
    assert not_available.street_number is None
    assert not_available.street_name is None
    assert not_available.unit is None


def test_none_input_returns_all_none() -> None:
    assert normalize_address(street=None, city=None, state=None, zip=None) == NormalizedAddress()


def test_city_lowercase_input_is_uppercased() -> None:
    normalized = normalize_address(city=" oak   ridge ")
    assert normalized.city == "OAK RIDGE"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("80521", True),
        ("00501", True),
        ("6371", False),  # 4-digit international postal code
        ("180202", False),  # 6-digit postal code
        ("921024548", False),  # 9-digit concatenated zip+4
        ("", False),
        (None, False),
        ("ABCDE", False),  # alphabetic 5-char string
        ("8052", False),  # 4 digits
    ],
)
def test_is_valid_zip5(value: str | None, expected: bool) -> None:
    assert is_valid_zip5(value) is expected


def test_full_realistic_fec_record() -> None:
    normalized = normalize_address(
        street="8409 CREEKS EDGE CT",
        city="OAK RIDGE",
        state="NC",
        zip="274069005",
    )
    assert normalized == NormalizedAddress(
        street_number="8409",
        street_name="CREEKS EDGE CT",
        unit=None,
        city="OAK RIDGE",
        state="NC",
        zip5="27406",
        zip4="9005",
    )
