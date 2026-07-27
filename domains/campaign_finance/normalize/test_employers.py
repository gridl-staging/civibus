"""Tests for FEC employer normalization and industry mapping."""

import pytest

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
