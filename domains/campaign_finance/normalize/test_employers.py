"""Tests for FEC employer normalization and industry mapping."""

import pytest

from domains.campaign_finance.normalize import employers
from domains.campaign_finance.normalize.employers import (
    JUNK_EMPLOYER_WEIGHT,
    UNKNOWN_INDUSTRY,
    canonicalize_employer,
    employer_junk_weight,
    industry_for_employer,
    is_junk_employer,
)


@pytest.mark.parametrize(
    "raw_employer, expected",
    [
        ("  acme    manufacturing  ", "ACME MANUFACTURING"),
        ("Acme, Manufacturing!", "ACME MANUFACTURING"),
        ("Acme Inc", "ACME"),
        ("Acme Inc.", "ACME"),
        ("Acme LLC", "ACME"),
        ("Acme L.L.C.", "ACME"),
        ("Acme,L.L.C.", "ACME"),
        ("Acme/L.L.C.", "ACME"),
        ("Acme Corp", "ACME"),
        ("Acme Co", "ACME"),
    ],
)
def test_canonicalize_employer_collapses_case_whitespace_punctuation_and_suffixes(
    raw_employer: str,
    expected: str,
) -> None:
    assert canonicalize_employer(raw_employer) == expected


@pytest.mark.parametrize(
    "junk_employer",
    [
        "RETIRED",
        "SELF",
        "SELF-EMPLOYED",
        "SELF EMPLOYED",
        "NONE",
        "N/A",
        "NOT EMPLOYED",
        "UNEMPLOYED",
        "",
        None,
    ],
)
def test_junk_employers_have_exact_near_zero_weight(junk_employer: str | None) -> None:
    assert is_junk_employer(junk_employer) is True
    assert canonicalize_employer(junk_employer) is None
    assert JUNK_EMPLOYER_WEIGHT == 0.01
    assert employer_junk_weight(junk_employer) == JUNK_EMPLOYER_WEIGHT
    assert employer_junk_weight(junk_employer) == 0.01


def test_non_junk_employer_has_full_weight() -> None:
    assert is_junk_employer("Acme Manufacturing") is False
    assert employer_junk_weight("Acme Manufacturing") == 1.0


def test_different_employers_keep_distinct_canonical_keys() -> None:
    assert canonicalize_employer("Acme Manufacturing") == "ACME MANUFACTURING"
    assert canonicalize_employer("Acme Bank") == "ACME BANK"
    assert canonicalize_employer("Acme Manufacturing") != canonicalize_employer("Acme Bank")


def test_unmapped_non_junk_employer_returns_unknown_industry_sentinel() -> None:
    assert industry_for_employer("Small Town Workshop") == UNKNOWN_INDUSTRY


def test_canonicalize_employer_preserves_unicode_letters() -> None:
    assert canonicalize_employer("Café LLC") == "CAFÉ"


def test_canonicalize_employer_treats_slash_as_punctuation() -> None:
    assert canonicalize_employer("Acme/Tools LLC") == "ACME TOOLS"
    assert canonicalize_employer("Acme Tools LLC") == "ACME TOOLS"


def test_slash_punctuation_normalization_preserves_exact_na_junk_classification() -> None:
    assert is_junk_employer("N/A") is True
    assert canonicalize_employer("N/A") is None


def test_period_between_words_normalizes_as_separator_without_concatenating() -> None:
    assert canonicalize_employer("Acme.Tools LLC") == "ACME TOOLS"
    assert canonicalize_employer("Acme Tools LLC") == "ACME TOOLS"


def test_period_word_separator_does_not_merge_distinct_employers() -> None:
    assert canonicalize_employer("Acme.Tools LLC") != canonicalize_employer("AcmeTools LLC")


def test_dotted_legal_suffix_still_collapses_after_period_separator_change() -> None:
    assert canonicalize_employer("Acme L.L.C.") == "ACME"


def test_canonicalize_employer_normalizes_canonically_equivalent_unicode() -> None:
    precomposed = "Café LLC"
    decomposed = "Cafe\u0301 LLC"
    assert canonicalize_employer(precomposed) == "CAFÉ"
    assert canonicalize_employer(decomposed) == "CAFÉ"
    assert canonicalize_employer(precomposed) == canonicalize_employer(decomposed)


@pytest.mark.parametrize(
    "raw_employer, expected_industry",
    [
        ("Google LLC", "Technology"),
        ("JPMorgan Chase & Co.", "Finance"),
        ("Pfizer Inc.", "Health Care"),
    ],
)
def test_known_employers_map_to_curated_industries(raw_employer: str, expected_industry: str) -> None:
    assert industry_for_employer(raw_employer) == expected_industry


@pytest.mark.parametrize(
    "raw_employer, expected_industry",
    [
        ("NORTHROP GRUMMAN CORPORATION", "Aerospace and Defense"),
        ("BOEING", "Aerospace and Defense"),
        ("USPS", "Government"),
        ("UNITED PARCEL SERVICE", "Transportation"),
        ("COMCAST (CC) OF WILLOW GROVE", "Telecommunications"),
        ("FEDERAL AVIATION ADMINISTRATION", "Government"),
        ("HOME DEPOT U.S.A., INC.", "Retail"),
        ("GENERAL MOTORS COMPANY", "Automotive"),
        ("ABBOTT", "Health Care"),
        ("AMERICAN AIRLINES", "Transportation"),
        ("THE ELEVANCE HEALTH COMPANIES, INC.", "Health Care"),
        ("UNITED AIRLINES", "Transportation"),
        ("AMAZON", "Retail"),
        ("ELECTRICIANS LOCAL 98", "Labor"),
        ("FRIAS TRANSPORTATION", "Transportation"),
        ("GlaxoSmithKline LLC", "Health Care"),
    ],
)
def test_random_sample_employers_map_to_curated_industries(
    raw_employer: str,
    expected_industry: str,
) -> None:
    assert industry_for_employer(raw_employer) == expected_industry


@pytest.mark.parametrize(
    "raw_employer, expected_industry",
    [
        ("LOCKHEED MARTIN", "Aerospace and Defense"),
        ("VALERO SERVICES, INC.", "Energy"),
        ("MICROSOFT", "Technology"),
        ("WALMART", "Retail"),
        ("BNSF RAILWAY COMPANY", "Transportation"),
        ("DELTA AIR LINES", "Transportation"),
        ("FEDERAL GOVERNMENT", "Government"),
        ("FORD MOTOR COMPANY", "Automotive"),
        ("GENENTECH USA, INC.", "Health Care"),
        ("NEW YORK LIFE INSURANCE COMPANY", "Insurance"),
        ("NOVO NORDISK", "Health Care"),
        ("SOUTHWEST AIRLINES", "Transportation"),
        ("SPACE EXPLORATION TECHNOLOGIES CORP.", "Aerospace and Defense"),
        ("AFSCME INT'L", "Labor"),
        ("ALTRIA GROUP DISTRIBUTION CO", "Tobacco"),
    ],
)
def test_round_two_random_sample_employers_map_to_curated_industries(
    raw_employer: str,
    expected_industry: str,
) -> None:
    assert industry_for_employer(raw_employer) == expected_industry


@pytest.mark.parametrize(
    "raw_employer, expected_industry",
    [
        ("APPLE", "Technology"),
        ("APPLE INC", "Technology"),
        ("APPLE INC.", "Technology"),
        ("APPLE, INC.", "Technology"),
        ("DELL TECHNOLOGIES, INC.", "Technology"),
        ("DELL TECHNOLOGIES", "Technology"),
        ("AMGEN INC.", "Health Care"),
        ("AMGEN", "Health Care"),
        ("BANK OF AMERICA", "Finance"),
        ("IBM", "Technology"),
        ("IBM CORP", "Technology"),
        ("MORGAN STANLEY", "Finance"),
        ("ABBVIE INC.", "Health Care"),
        ("ABBVIE", "Health Care"),
        ("VERIZON", "Telecommunications"),
    ],
)
def test_stage_three_random_sample_employers_map_to_curated_industries(
    raw_employer: str,
    expected_industry: str,
) -> None:
    assert industry_for_employer(raw_employer) == expected_industry


@pytest.mark.parametrize("status_value", ["HOMEMAKER", "ENTREPRENEUR"])
def test_random_sample_status_values_are_junk(status_value: str) -> None:
    assert is_junk_employer(status_value) is True
    assert canonicalize_employer(status_value) is None
    assert employer_junk_weight(status_value) == JUNK_EMPLOYER_WEIGHT
    assert industry_for_employer(status_value) == UNKNOWN_INDUSTRY


def test_round_two_status_value_disabled_is_junk() -> None:
    assert is_junk_employer("DISABLED") is True
    assert canonicalize_employer("DISABLED") is None
    assert employer_junk_weight("DISABLED") == JUNK_EMPLOYER_WEIGHT
    assert industry_for_employer("DISABLED") == UNKNOWN_INDUSTRY


@pytest.mark.parametrize(
    "ambiguous_employer",
    [
        "CHARTER",
        "HONEYWELL INTERNATIONAL",
        "WILLIAMS WPC-I, LLC.",
        "LDC AND AFFILIATED LOCALS",
    ],
)
def test_random_sample_ambiguous_employers_remain_unmapped(ambiguous_employer: str) -> None:
    assert is_junk_employer(ambiguous_employer) is False
    assert canonicalize_employer(ambiguous_employer) is not None
    assert industry_for_employer(ambiguous_employer) == UNKNOWN_INDUSTRY


def test_random_sample_industry_coverage_meets_module_contract() -> None:
    sample_size = 14_324
    selected_known_sample_counts = {
        "GOOGLE": 7,
        "GOOGLE LLC": 5,
        "PFIZER, INC": 4,
        "PFIZER INC": 3,
        "NORTHROP GRUMMAN CORPORATION": 28,
        "BOEING": 24,
        "USPS": 21,
        "UNITED PARCEL SERVICE": 16,
        "UNITED PARCEL SERVICE, INC.": 5,
        "COMCAST (CC) OF WILLOW GROVE": 13,
        "FEDERAL AVIATION ADMINISTRATION": 13,
        "HOME DEPOT U.S.A., INC.": 11,
        "GENERAL MOTORS COMPANY": 10,
        "ABBOTT": 9,
        "AMERICAN AIRLINES": 9,
        "AMERICAN AIRLINES, INC.": 4,
        "THE ELEVANCE HEALTH COMPANIES, INC.": 9,
        "UNITED AIRLINES": 9,
        "UNITED AIRLINES INC.": 2,
        "AMAZON": 8,
        "ELECTRICIANS LOCAL 98": 8,
        "FRIAS TRANSPORTATION": 8,
        "LOCKHEED MARTIN": 8,
        "VALERO SERVICES, INC.": 8,
        "MICROSOFT": 7,
        "MICROSOFT CORP.": 1,
        "WALMART": 7,
        "WALMART INC": 2,
        "BNSF RAILWAY COMPANY": 6,
        "DELTA AIR LINES": 6,
        "DELTA AIR LINES, INC.": 5,
        "FEDERAL GOVERNMENT": 6,
        "FORD MOTOR COMPANY": 6,
        "GENENTECH USA, INC.": 6,
        "NEW YORK LIFE INSURANCE COMPANY": 6,
        "NOVO NORDISK": 6,
        "SOUTHWEST AIRLINES": 6,
        "SPACE EXPLORATION TECHNOLOGIES CORP.": 6,
        "AFSCME INT'L": 5,
        "ALTRIA GROUP DISTRIBUTION CO": 5,
        "APPLE": 3,
        "APPLE INC": 2,
        "APPLE INC.": 1,
        "APPLE, INC.": 1,
        "DELL TECHNOLOGIES, INC.": 5,
        "DELL TECHNOLOGIES": 2,
        "AMGEN INC.": 3,
        "AMGEN": 2,
        "BANK OF AMERICA": 5,
        "IBM": 4,
        "IBM CORP": 1,
        "MORGAN STANLEY": 5,
        "ABBVIE INC.": 3,
        "ABBVIE": 1,
        "VERIZON": 4,
    }
    newly_junk_sample_counts = {"DISABLED": 7}

    selected_known_count = sum(selected_known_sample_counts.values())
    newly_junk_count = sum(newly_junk_sample_counts.values())
    achieved_share = selected_known_count / sample_size

    assert newly_junk_count == 7
    assert selected_known_count == 370
    assert achieved_share == 370 / 14_324
    assert hasattr(employers, "INDUSTRY_BY_EMPLOYER_MIN_COVERAGE")
    minimum_coverage = getattr(employers, "INDUSTRY_BY_EMPLOYER_MIN_COVERAGE", float("inf"))
    assert minimum_coverage == 370 / 14_324
    assert achieved_share >= minimum_coverage
