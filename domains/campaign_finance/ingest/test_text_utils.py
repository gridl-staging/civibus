from __future__ import annotations

import pytest

from domains.campaign_finance.ingest.text_utils import normalize_optional_text

pytestmark = pytest.mark.unit


def test_normalize_optional_text_returns_none_for_none() -> None:
    assert normalize_optional_text(None) is None


def test_normalize_optional_text_returns_none_for_blank_text() -> None:
    assert normalize_optional_text("   ") is None


def test_normalize_optional_text_strips_and_returns_text() -> None:
    assert normalize_optional_text("  C00100001  ") == "C00100001"
