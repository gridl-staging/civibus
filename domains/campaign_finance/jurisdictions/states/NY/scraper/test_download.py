"""Tests for NY SODA API download module."""

from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.NY.scraper.download import (
    SODA_PAGE_SIZE,
    YEAR_FILTER_THRESHOLD,
    build_ny_download_url,
)


class TestNYDownloadURLContract:
    """Lock the SODA dataset IDs and query structure."""

    def test_contributions_url_uses_known_dataset_id(self) -> None:
        url = build_ny_download_url("contributions")
        # Dataset 4j2b-6a2j is the contributions filtered view.
        assert "4j2b-6a2j" in url

    def test_expenditures_url_uses_known_dataset_id(self) -> None:
        url = build_ny_download_url("expenditures")
        # Dataset ajsb-8pni is the expenditures filtered view.
        assert "ajsb-8pni" in url

    def test_url_includes_date_filter(self) -> None:
        url = build_ny_download_url("contributions")
        assert "sched_date" in url
        assert YEAR_FILTER_THRESHOLD in url

    def test_url_includes_pagination(self) -> None:
        url = build_ny_download_url("contributions", offset=50000)
        assert "$offset=50000" in url
        assert f"$limit={SODA_PAGE_SIZE}" in url

    def test_url_includes_ordering(self) -> None:
        url = build_ny_download_url("contributions")
        assert "$order=trans_number" in url

    def test_custom_limit_overrides_page_size(self) -> None:
        url = build_ny_download_url("contributions", limit=100)
        assert "$limit=100" in url

    def test_soda_page_size_is_50000(self) -> None:
        # SODA max per request is 50K — this is a contract lock.
        assert SODA_PAGE_SIZE == 50_000

    def test_year_filter_threshold_is_2022(self) -> None:
        # 5-year window for 2026 election coverage.
        assert "2022" in YEAR_FILTER_THRESHOLD
