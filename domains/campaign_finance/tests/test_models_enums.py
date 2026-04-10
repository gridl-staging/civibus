"""Unit tests for campaign-finance enum types."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
import pytest

from domains.campaign_finance.types import CommitteeType, OfficeType


def test_committee_type_contains_all_stage1_codes():
    expected_codes = {
        "C",
        "D",
        "E",
        "H",
        "I",
        "N",
        "O",
        "P",
        "Q",
        "S",
        "U",
        "V",
        "W",
        "X",
        "Y",
        "Z",
    }
    assert {member.value for member in CommitteeType} == expected_codes


def test_committee_type_json_and_string_serialization():
    adapter = TypeAdapter(CommitteeType)
    assert adapter.dump_json(CommitteeType.HOUSE_CAMPAIGN).decode("utf-8") == '"H"'
    assert adapter.validate_python("H") is CommitteeType.HOUSE_CAMPAIGN


def test_committee_type_rejects_unknown_code():
    adapter = TypeAdapter(CommitteeType)
    with pytest.raises(ValidationError):
        adapter.validate_python("K")


def test_office_type_allows_house_senate_and_president():
    adapter = TypeAdapter(OfficeType)
    assert adapter.validate_python("H") is OfficeType.HOUSE
    assert adapter.validate_python("S") is OfficeType.SENATE
    assert adapter.validate_python("P") is OfficeType.PRESIDENT


def test_office_type_rejects_invalid_code():
    adapter = TypeAdapter(OfficeType)
    with pytest.raises(ValidationError):
        adapter.validate_python("G")
