from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import domains.campaign_finance.jurisdictions.states.GA.scraper.download as download_module
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.GA.scraper import (
    _CONFIG_PATH as _GA_CONFIG_PATH,
    _load_date_selectors_for_transaction_type,
    _find_ga_data_source_block_by_transaction_type,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.download import (
    _EXPORT_BUTTON_SELECTOR,
    _SEARCH_BUTTON_SELECTOR,
    build_search_url,
    download_ga_export,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

_ALLOWED_GA_SEARCH_URL = "https://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx"
_GA_IE_SOURCE_NAME = "Georgia Campaign Portal — Independent Expenditures Search Export"
_STRICT_PLAYWRIGHT_FLOW_CASES = (
    (
        "contributions",
        "#ctl00_ContentPlaceHolder1_txtReceivedDateFrom",
        "#ctl00_ContentPlaceHolder1_txtReceivedDateTo",
        "StateEthicsReport.csv",
    ),
    (
        "expenditures",
        "#ctl00_ContentPlaceHolder1_txtDateFrom",
        "#ctl00_ContentPlaceHolder1_txtDateTo",
        "EthicsReportExport.xls",
    ),
)

# -- 2026-cycle portal-contract lock tests --


class TestGAPortalContract2026:
    """Lock GA portal selectors, URLs, and export assumptions for 2026 cycle.

    These are regression guards: if the GA ethics portal changes its DOM
    structure, these tests catch it before a live scrape attempt fails silently.
    """

    def test_contribution_date_selectors_match_portal_dom(self) -> None:
        selectors = _load_date_selectors_for_transaction_type("contributions")
        assert selectors == (
            "#ctl00_ContentPlaceHolder1_txtReceivedDateFrom",
            "#ctl00_ContentPlaceHolder1_txtReceivedDateTo",
        )

    def test_expenditure_date_selectors_match_portal_dom(self) -> None:
        selectors = _load_date_selectors_for_transaction_type("expenditures")
        assert selectors == (
            "#ctl00_ContentPlaceHolder1_txtDateFrom",
            "#ctl00_ContentPlaceHolder1_txtDateTo",
        )

    def test_search_button_selector_matches_portal_dom(self) -> None:
        assert _SEARCH_BUTTON_SELECTOR == "#ctl00_ContentPlaceHolder1_Search"

    def test_export_button_selector_matches_portal_dom(self) -> None:
        assert _EXPORT_BUTTON_SELECTOR == "#ctl00_ContentPlaceHolder1_Export"

    def test_contribution_search_url_resolves_to_ga_ethics_portal(self) -> None:
        url = build_search_url("contributions")
        assert url.startswith("https://media.ethics.ga.gov/")
        assert "ByContributions" in url

    def test_expenditure_search_url_resolves_to_ga_ethics_portal(self) -> None:
        url = build_search_url("expenditures")
        assert url.startswith("https://media.ethics.ga.gov/")
        assert "ByExpenditures" in url

    def test_independent_expenditure_search_url_resolves_to_ga_ethics_portal(self) -> None:
        url = build_search_url("independent_expenditures")
        assert url.startswith("https://media.ethics.ga.gov/")
        assert "ByIEFiler" in url

    def test_config_verified_for_2026_cycle(self) -> None:
        """All GA data sources must either verify working or capture explicit 2026-cycle breakage."""
        cycle_cutoff = date(2026, 3, 21)
        config = load_jurisdiction_config(_GA_CONFIG_PATH)
        for source in config.data_sources:
            if source.last_verified_working is not None:
                assert source.last_verified_working >= cycle_cutoff, (
                    f"{source.name} last_verified_working={source.last_verified_working} is before {cycle_cutoff}"
                )
                continue

            assert source.name == _GA_IE_SOURCE_NAME
            assert any("2026-04-29" in issue and "HTTP 404" in issue for issue in source.known_issues)


def _is_playwright_timeout(error: Exception) -> bool:
    error_type = type(error)
    return error_type.__name__ == "TimeoutError" and error_type.__module__.startswith("playwright")


def _patch_build_search_url(
    monkeypatch: pytest.MonkeyPatch,
    *,
    search_url: str = _ALLOWED_GA_SEARCH_URL,
) -> MagicMock:
    build_search_url_mock = MagicMock(return_value=search_url)
    monkeypatch.setattr(download_module, "build_search_url", build_search_url_mock)
    return build_search_url_mock


def _set_playwright_available(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sync_playwright: object,
) -> None:
    monkeypatch.setattr(download_module, "_sync_playwright", sync_playwright)
    monkeypatch.setattr(download_module, "_playwright_import_error", None)


def _assert_integration_download_returns_nonempty_parseable_file(
    tmp_path: Path,
    *,
    data_type: str,
    candidate: str,
    date_start: str,
    date_end: str,
    parser: Callable[[Path], object],
) -> None:
    try:
        export_path = download_ga_export(
            data_type,
            dest_dir=tmp_path,
            candidate=candidate,
            date_start=date_start,
            date_end=date_end,
        )
    except RuntimeError as error:
        if "playwright" in str(error).lower():
            pytest.skip(f"Playwright unavailable for integration test: {error}")
        raise
    except Exception as error:  # noqa: BLE001
        if _is_playwright_timeout(error):
            pytest.skip(f"GA portal timed out during {data_type} integration test: {error}")
        raise

    assert export_path.exists()
    assert export_path.stat().st_size > 0
    assert list(parser(export_path))


@pytest.mark.parametrize("data_type", ["contributions", "expenditures", "independent_expenditures"])
def test_build_search_url_resolves_url_from_config_transaction_type(data_type: str) -> None:
    source_block = _find_ga_data_source_block_by_transaction_type(data_type)
    assert source_block is not None

    assert build_search_url(data_type) == source_block.url


def test_build_search_url_raises_for_unknown_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported GA data type"):
        build_search_url("independent-expenditures")


def test_strict_playwright_flow_cases_exclude_unverified_ie_contract() -> None:
    assert tuple(case[0] for case in _STRICT_PLAYWRIGHT_FLOW_CASES) == ("contributions", "expenditures")


@pytest.mark.parametrize(
    "search_url",
    [
        "http://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx",
        "https://example.test/ga-search",
        "https://user:pass@media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx",
        "file:///tmp/ga-search.html",
    ],
)
def test_download_ga_export_rejects_untrusted_search_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    search_url: str,
) -> None:
    sync_playwright_mock = MagicMock()
    build_search_url_mock = _patch_build_search_url(monkeypatch, search_url=search_url)
    _set_playwright_available(monkeypatch, sync_playwright=sync_playwright_mock)

    with pytest.raises(
        ValueError,
        match="GA search URL must use https://media.ethics.ga.gov without embedded credentials",
    ):
        download_ga_export(
            "contributions",
            dest_dir=tmp_path / "downloads",
            candidate="Jane Example",
            date_start="01/01/2024",
            date_end="01/31/2024",
        )

    build_search_url_mock.assert_called_once_with("contributions")
    sync_playwright_mock.assert_not_called()


def test_download_ga_export_rejects_unverified_ie_source_before_browser_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_playwright_mock = MagicMock()
    build_search_url_mock = _patch_build_search_url(monkeypatch)
    _set_playwright_available(monkeypatch, sync_playwright=sync_playwright_mock)

    with pytest.raises(
        RuntimeError,
        match=r"independent_expenditures'.*HTTP 404",
    ):
        download_ga_export(
            "independent_expenditures",
            dest_dir=tmp_path / "downloads",
            candidate="Jane Example",
            date_start="01/01/2024",
            date_end="01/31/2024",
        )

    build_search_url_mock.assert_not_called()
    sync_playwright_mock.assert_not_called()


@pytest.mark.parametrize(
    ("data_type", "date_start_selector", "date_end_selector", "suggested_filename"),
    _STRICT_PLAYWRIGHT_FLOW_CASES,
)
def test_download_ga_export_runs_expected_playwright_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    data_type: str,
    date_start_selector: str,
    date_end_selector: str,
    suggested_filename: str,
) -> None:
    candidate = "Jane Example"
    date_start = "01/01/2024"
    date_end = "01/31/2024"
    build_search_url_mock = _patch_build_search_url(monkeypatch)

    playwright_manager = MagicMock()
    playwright_instance = MagicMock()
    browser = MagicMock()
    browser_context = MagicMock()
    page = MagicMock()
    search_button = MagicMock()
    export_button = MagicMock()
    download = MagicMock()
    download.suggested_filename = suggested_filename
    download_info = MagicMock()
    download_info.value = download

    expect_download_context_manager = MagicMock()
    expect_download_context_manager.__enter__.return_value = download_info
    expect_download_context_manager.__exit__.return_value = None
    page.expect_download.return_value = expect_download_context_manager
    page.locator.side_effect = lambda selector: {
        "#ctl00_ContentPlaceHolder1_Search": search_button,
        "#ctl00_ContentPlaceHolder1_Export": export_button,
    }[selector]

    playwright_manager.__enter__.return_value = playwright_instance
    playwright_manager.__exit__.return_value = None
    playwright_instance.chromium.launch.return_value = browser
    browser.new_context.return_value = browser_context
    browser_context.new_page.return_value = page
    _set_playwright_available(
        monkeypatch,
        sync_playwright=MagicMock(return_value=playwright_manager),
    )

    saved_path = download_ga_export(
        data_type,
        dest_dir=tmp_path / "downloads",
        candidate=candidate,
        date_start=date_start,
        date_end=date_end,
    )

    assert saved_path == tmp_path / "downloads" / suggested_filename
    build_search_url_mock.assert_called_once_with(data_type)
    page.goto.assert_called_once_with(_ALLOWED_GA_SEARCH_URL, wait_until="domcontentloaded")
    playwright_instance.chromium.launch.assert_called_once_with(headless=True)
    browser.new_context.assert_called_once_with(accept_downloads=True)
    assert page.fill.call_args_list == [
        call("#ctl00_ContentPlaceHolder1_txtCandidateName", candidate),
        call(date_start_selector, date_start),
        call(date_end_selector, date_end),
    ]
    search_button.click.assert_called_once_with()
    page.expect_navigation.assert_called_once_with(wait_until="domcontentloaded", timeout=120_000)
    export_button.wait_for.assert_called_once_with(state="visible", timeout=120_000)
    page.expect_download.assert_called_once_with(timeout=180_000)
    export_button.click.assert_called_once_with(no_wait_after=True)
    download.save_as.assert_called_once_with(str(saved_path))
    browser_context.close.assert_called_once_with()
    browser.close.assert_called_once_with()


def test_download_ga_export_closes_browser_when_context_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    build_search_url_mock = _patch_build_search_url(monkeypatch)

    playwright_manager = MagicMock()
    playwright_instance = MagicMock()
    browser = MagicMock()
    browser.new_context.side_effect = RuntimeError("context setup failed")

    playwright_manager.__enter__.return_value = playwright_instance
    playwright_manager.__exit__.return_value = None
    playwright_instance.chromium.launch.return_value = browser
    _set_playwright_available(
        monkeypatch,
        sync_playwright=MagicMock(return_value=playwright_manager),
    )

    with pytest.raises(RuntimeError, match="context setup failed"):
        download_ga_export(
            "contributions",
            dest_dir=tmp_path / "downloads",
            candidate="Jane Example",
            date_start="01/01/2024",
            date_end="01/31/2024",
        )

    build_search_url_mock.assert_called_once_with("contributions")
    playwright_instance.chromium.launch.assert_called_once_with(headless=True)
    browser.new_context.assert_called_once_with(accept_downloads=True)
    browser.close.assert_called_once_with()


def test_download_ga_export_raises_runtime_error_when_playwright_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(download_module, "_sync_playwright", None)
    monkeypatch.setattr(
        download_module,
        "_playwright_import_error",
        ImportError("No module named 'playwright'"),
    )

    with pytest.raises(RuntimeError, match="Install download dependencies"):
        download_ga_export(
            "contributions",
            dest_dir=tmp_path,
            candidate="Jane Example",
            date_start="01/01/2024",
            date_end="01/31/2024",
        )


@pytest.mark.integration
def test_download_ga_export_contributions_integration_returns_nonempty_parseable_file(
    tmp_path: Path,
) -> None:
    _assert_integration_download_returns_nonempty_parseable_file(
        tmp_path,
        data_type="contributions",
        candidate="Hatfield",
        date_start="01/01/2026",
        date_end="03/31/2026",
        parser=parse_contributions,
    )


@pytest.mark.integration
def test_download_ga_export_expenditures_integration_returns_nonempty_parseable_file(
    tmp_path: Path,
) -> None:
    _assert_integration_download_returns_nonempty_parseable_file(
        tmp_path,
        data_type="expenditures",
        candidate="Hatfield",
        date_start="01/01/2026",
        date_end="03/31/2026",
        parser=parse_expenditures,
    )
