"""Tests for generic campaign-finance name normalization."""

from domains.campaign_finance.normalize.names import ParsedName, parse_name


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
