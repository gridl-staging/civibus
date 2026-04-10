"""Unit tests for _strip_null_bytes in db_ingest.

Validates that Unicode null bytes (\x00) are stripped from strings in
raw_fields dicts before PostgreSQL insertion. This is critical because
government source data (e.g., CA CTRIB_EMP) occasionally contains
embedded null bytes that PostgreSQL rejects.
"""

from __future__ import annotations

from core.db_ingest import _strip_null_bytes


def test_strip_null_bytes_from_string() -> None:
    assert _strip_null_bytes("hello\x00world") == "helloworld"


def test_strip_null_bytes_preserves_clean_string() -> None:
    assert _strip_null_bytes("clean string") == "clean string"


def test_strip_null_bytes_from_dict_values() -> None:
    raw = {"name": "Michael\x00", "city": "Los Angeles"}
    result = _strip_null_bytes(raw)
    assert result == {"name": "Michael", "city": "Los Angeles"}


def test_strip_null_bytes_from_nested_dict() -> None:
    raw = {"outer": {"inner": "has\x00null"}}
    result = _strip_null_bytes(raw)
    assert result == {"outer": {"inner": "hasnull"}}


def test_strip_null_bytes_from_list_in_dict() -> None:
    raw = {"tags": ["ok", "bad\x00data", "fine"]}
    result = _strip_null_bytes(raw)
    assert result == {"tags": ["ok", "baddata", "fine"]}


def test_strip_null_bytes_passes_through_non_string_types() -> None:
    assert _strip_null_bytes(42) == 42
    assert _strip_null_bytes(None) is None
    assert _strip_null_bytes(3.14) == 3.14
    assert _strip_null_bytes(True) is True


def test_strip_null_bytes_empty_dict() -> None:
    assert _strip_null_bytes({}) == {}


def test_strip_null_bytes_multiple_null_bytes_in_one_string() -> None:
    """CA data has been seen with multiple \x00 in a single field."""
    assert _strip_null_bytes("a\x00b\x00c") == "abc"


def test_strip_null_bytes_realistic_ca_data() -> None:
    """Reproduces the exact error from production CA load logs."""
    raw = {
        "__table_name": "RCPT_CD",
        "CTRIB_ZIP4": "91006",
        "CTRIB_EMP": "Michaelb\x00aker Industries",
        "CTRIB_CITY": "Arcadia",
    }
    result = _strip_null_bytes(raw)
    assert result["CTRIB_EMP"] == "Michaelbaker Industries"
    # Other fields should be unchanged
    assert result["CTRIB_ZIP4"] == "91006"
    assert result["__table_name"] == "RCPT_CD"
