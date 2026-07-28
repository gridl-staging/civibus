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


@pytest.mark.parametrize("status_value", ["HOMEMAKER", "ENTREPRENEUR"])
def test_random_sample_status_values_are_junk(status_value: str) -> None:
    assert is_junk_employer(status_value) is True
    assert canonicalize_employer(status_value) is None
    assert employer_junk_weight(status_value) == JUNK_EMPLOYER_WEIGHT
    assert industry_for_employer(status_value) == UNKNOWN_INDUSTRY


@pytest.mark.parametrize("ambiguous_employer", ["CHARTER", "HONEYWELL INTERNATIONAL", "WILLIAMS WPC-I, LLC."])
def test_random_sample_ambiguous_employers_remain_unmapped(ambiguous_employer: str) -> None:
    assert is_junk_employer(ambiguous_employer) is False
    assert canonicalize_employer(ambiguous_employer) is not None
    assert industry_for_employer(ambiguous_employer) == UNKNOWN_INDUSTRY


def test_random_sample_industry_coverage_meets_module_contract() -> None:
    sample_size = 14_324
    baseline_known_count = 19
    newly_mapped_sample_counts = {
        "NORTHROP GRUMMAN CORPORATION": 28,
        "BOEING": 24,
        "USPS": 21,
        "UNITED PARCEL SERVICE": 16,
        "COMCAST (CC) OF WILLOW GROVE": 13,
        "FEDERAL AVIATION ADMINISTRATION": 13,
        "HOME DEPOT U.S.A., INC.": 11,
        "GENERAL MOTORS COMPANY": 10,
        "ABBOTT": 9,
        "AMERICAN AIRLINES": 9,
        "THE ELEVANCE HEALTH COMPANIES, INC.": 9,
        "UNITED AIRLINES": 9,
        "AMAZON": 8,
        "ELECTRICIANS LOCAL 98": 8,
        "FRIAS TRANSPORTATION": 8,
        "GLAXOSMITHKLINE": 11,
    }

    newly_mapped_count = sum(newly_mapped_sample_counts.values())
    achieved_known_count = baseline_known_count + newly_mapped_count
    achieved_share = achieved_known_count / sample_size

    assert newly_mapped_count == 207
    assert achieved_known_count == 226
    assert achieved_share == 226 / 14_324
    assert hasattr(employers, "INDUSTRY_BY_EMPLOYER_MIN_COVERAGE")
    minimum_coverage = getattr(employers, "INDUSTRY_BY_EMPLOYER_MIN_COVERAGE", float("inf"))
    assert achieved_share >= minimum_coverage
