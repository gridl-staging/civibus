"""RED tests for FEC donor name parsing."""

# This import will fail until GREEN implementation exists.
from domains.campaign_finance.entity_extractors.name_parser import parse_fec_name


class TestParseFecName:
    def test_simple_last_first(self):
        result = parse_fec_name("DOE, JOHN")
        assert result == {"first_name": "JOHN", "middle_name": None, "last_name": "DOE", "suffix": None}

    def test_last_first_middle(self):
        result = parse_fec_name("DOE, JOHN A")
        assert result == {"first_name": "JOHN", "middle_name": "A", "last_name": "DOE", "suffix": None}

    def test_last_first_middle_suffix(self):
        result = parse_fec_name("DOE, JOHN A JR")
        assert result == {"first_name": "JOHN", "middle_name": "A", "last_name": "DOE", "suffix": "JR"}

    def test_last_first_suffix_no_middle(self):
        """JR is a known suffix, not a middle name."""
        result = parse_fec_name("DOE, JOHN JR")
        assert result == {"first_name": "JOHN", "middle_name": None, "last_name": "DOE", "suffix": "JR"}

    def test_apostrophe_last_name(self):
        result = parse_fec_name("O'BRIEN, MARY KATE")
        assert result == {"first_name": "MARY", "middle_name": "KATE", "last_name": "O'BRIEN", "suffix": None}

    def test_no_comma_returns_none(self):
        """No comma indicates an organizational contributor, not a person."""
        assert parse_fec_name("DOE") is None

    def test_empty_string_returns_none(self):
        assert parse_fec_name("") is None

    def test_none_returns_none(self):
        assert parse_fec_name(None) is None

    def test_known_suffixes(self):
        """All known suffixes should be detected."""
        for suffix in ["SR", "II", "III", "IV", "V", "MD", "PHD", "ESQ", "DDS", "DVM", "RN", "CPA"]:
            result = parse_fec_name(f"DOE, JOHN {suffix}")
            assert result["suffix"] == suffix, f"Failed to detect suffix {suffix}"
            assert result["middle_name"] is None
