"""Tests for generic campaign-finance name normalization."""

import pytest

from domains.campaign_finance.normalize.names import ParsedName, parse_name


@pytest.mark.parametrize(
    ("raw_name", "expected", "expected_canonical"),
    [
        ("SMITH", ParsedName(last="SMITH"), "SMITH"),
        ("SMITH, JOHN", ParsedName(first="JOHN", last="SMITH"), "JOHN SMITH"),
        (
            "SMITH, JOHN JR",
            ParsedName(first="JOHN", last="SMITH", suffix="JR"),
            "JOHN SMITH JR",
        ),
        ("O'BRIEN, MARY", ParsedName(first="MARY", last="O'BRIEN"), "MARY O'BRIEN"),
        (
            "DE LA CRUZ, MARIA",
            ParsedName(first="MARIA", last="DE LA CRUZ"),
            "MARIA DE LA CRUZ",
        ),
    ],
)
def test_parse_name_owns_transaction_splitter_defect_specimens(
    raw_name: str,
    expected: ParsedName,
    expected_canonical: str,
) -> None:
    parsed_name = parse_name(raw_name)

    assert parsed_name == expected
    assert parsed_name.canonical == expected_canonical


@pytest.mark.parametrize(
    ("raw_name", "expected", "expected_canonical"),
    [
        ("John Smith", ParsedName(first="JOHN", last="SMITH"), "JOHN SMITH"),
        ("John Quincy Smith", ParsedName(first="JOHN", last="SMITH"), "JOHN SMITH"),
    ],
)
def test_parse_name_first_last_only_preserves_nc_transaction_projection(
    raw_name: str,
    expected: ParsedName,
    expected_canonical: str,
) -> None:
    # The NC transaction row has no middle-name field, so its compatibility
    # projection intentionally discards middle tokens instead of silently
    # changing the resolver's two-field matching input.
    parsed_name = parse_name(raw_name, first_last_only=True)

    assert parsed_name == expected
    assert parsed_name.canonical == expected_canonical


def test_parse_name_rejects_conflicting_first_last_only_and_surname_first_modes() -> None:
    with pytest.raises(ValueError, match="first_last_only cannot be combined with surname_first"):
        parse_name("SMITH JOHN", first_last_only=True, surname_first=True)


@pytest.mark.parametrize(
    ("raw_name", "expected", "expected_canonical"),
    [
        ("John Smith", ParsedName(first="JOHN", last="SMITH"), "JOHN SMITH"),
        (
            "John Quincy Smith",
            ParsedName(first="JOHN", middle="QUINCY", last="SMITH"),
            "JOHN Q SMITH",
        ),
        (
            "John Smith Jr.",
            ParsedName(first="JOHN", last="SMITH", suffix="JR"),
            "JOHN SMITH JR",
        ),
    ],
)
def test_parse_name_defaults_remain_natural_order_for_ssot_specimens(
    raw_name: str,
    expected: ParsedName,
    expected_canonical: str,
) -> None:
    parsed_name = parse_name(raw_name)

    assert parsed_name == expected
    assert parsed_name.canonical == expected_canonical


def test_fec_basic() -> None:
    assert parse_name("SMITH, JOHN") == ParsedName(first="JOHN", last="SMITH")


def test_fec_with_middle() -> None:
    assert parse_name("SMITH, JOHN MICHAEL") == ParsedName(first="JOHN", middle="MICHAEL", last="SMITH")


def test_fec_with_suffix() -> None:
    assert parse_name("SMITH, JOHN JR") == ParsedName(first="JOHN", last="SMITH", suffix="JR")


def test_fec_with_suffix_period() -> None:
    assert parse_name("SMITH, JOHN JR.") == ParsedName(first="JOHN", last="SMITH", suffix="JR")


def test_fec_with_middle_and_suffix() -> None:
    assert parse_name("SMITH, JOHN M JR") == ParsedName(first="JOHN", middle="M", last="SMITH", suffix="JR")


def test_natural_order() -> None:
    assert parse_name("John Smith") == ParsedName(first="JOHN", last="SMITH")


def test_natural_with_prefix_and_single_token() -> None:
    assert parse_name("MR. JOHN") == ParsedName(prefix="MR", first="JOHN")


def test_natural_with_suffix_and_single_token() -> None:
    assert parse_name("JOHN JR.") == ParsedName(first="JOHN", suffix="JR")


def test_last_name_only() -> None:
    assert parse_name("SMITH") == ParsedName(last="SMITH")


def test_empty_string() -> None:
    assert parse_name("") == ParsedName()


def test_none_input() -> None:
    assert parse_name(None) == ParsedName()


def test_prefix_and_suffix() -> None:
    assert parse_name("MR. JOHN SMITH III") == ParsedName(prefix="MR", first="JOHN", last="SMITH", suffix="III")


def test_apostrophe() -> None:
    assert parse_name("O'BRIEN, MARY") == ParsedName(first="MARY", last="O'BRIEN")


def test_multi_word_fec_last_name() -> None:
    assert parse_name("DE LA CRUZ, MARIA") == ParsedName(first="MARIA", last="DE LA CRUZ")


def test_fec_multi_comma_name_does_not_retain_comma_artifact_on_given_name() -> None:
    # A second comma (organizational suffix or stray delimiter) must not leave a
    # trailing comma stuck to the given-name token.
    assert parse_name("SMITH, JOHN, JR") == ParsedName(first="JOHN", last="SMITH", suffix="JR")


def test_fec_multi_comma_first_last_only_projection_has_clean_tokens() -> None:
    parsed_name = parse_name("PATRICIA C. FLEMING, CPA, PLLC", first_last_only=True)
    assert parsed_name.first == "CPA"
    assert parsed_name.last == "PATRICIA C. FLEMING"


def test_canonical_property() -> None:
    assert ParsedName(first="JOHN", last="SMITH").canonical == "JOHN SMITH"


def test_canonical_with_middle() -> None:
    parsed_name = ParsedName(first="JOHN", middle="MICHAEL", last="SMITH")
    assert parsed_name.canonical == "JOHN M SMITH"


def test_canonical_with_suffix() -> None:
    assert ParsedName(first="JOHN", last="SMITH", suffix="JR").canonical == "JOHN SMITH JR"


def test_canonical_omits_prefix() -> None:
    assert ParsedName(prefix="DR", first="JOHN", last="SMITH").canonical == "JOHN SMITH"


def test_surname_first_comma_less_two_token_donor_order() -> None:
    assert parse_name("ROBINSON STEPHANIE", surname_first=True) == ParsedName(
        first="STEPHANIE",
        last="ROBINSON",
    )
    assert parse_name("GARCIA RYAN", surname_first=True) == ParsedName(
        first="RYAN",
        last="GARCIA",
    )


def test_surname_first_comma_less_multi_token_donor_order_after_affix_stripping() -> None:
    # In this delimiter-free FEC mode, every core token before the given name belongs to the surname.
    assert parse_name("DR. VAN DYKE AMY JR.", surname_first=True) == ParsedName(
        prefix="DR",
        first="AMY",
        middle=None,
        last="VAN DYKE",
        suffix="JR",
    )


def test_surname_first_keeps_default_natural_order_unchanged() -> None:
    assert parse_name("Stephanie Robinson") == ParsedName(
        first="STEPHANIE",
        last="ROBINSON",
    )


def test_surname_first_does_not_double_invert_comma_bearing_name() -> None:
    expected = ParsedName(first="STEPHANIE", last="ROBINSON")

    assert parse_name("ROBINSON, STEPHANIE") == expected
    assert parse_name("ROBINSON, STEPHANIE", surname_first=True) == expected


def test_surname_first_retains_empty_and_single_token_outcomes() -> None:
    assert parse_name("", surname_first=True) == ParsedName()
    assert parse_name("SMITH", surname_first=True) == ParsedName(last="SMITH")
    assert parse_name("JOHN JR.", surname_first=True) == ParsedName(first="JOHN", suffix="JR")
