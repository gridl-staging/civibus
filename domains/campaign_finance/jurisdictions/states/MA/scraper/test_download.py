"""Tests for MA OCPF download module."""

from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.MA.scraper.download import build_ma_download_url


class TestMADownloadURLContract:
    """Lock the Azure Blob Storage URL pattern."""

    def test_url_uses_azure_blob_storage(self) -> None:
        url = build_ma_download_url(2026)
        assert "ocpf2.blob.core.windows.net" in url

    def test_url_includes_year(self) -> None:
        url = build_ma_download_url(2024)
        assert "2024" in url
        assert "reports.zip" in url

    def test_url_pattern_is_deterministic(self) -> None:
        url_2025 = build_ma_download_url(2025)
        url_2026 = build_ma_download_url(2026)
        # Only the year should differ.
        assert url_2025.replace("2025", "YEAR") == url_2026.replace("2026", "YEAR")
