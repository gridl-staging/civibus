
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from . import _find_ga_data_source_block_by_transaction_type, _load_date_selectors_for_transaction_type

_SEARCH_BUTTON_SELECTOR = "#ctl00_ContentPlaceHolder1_Search"
_EXPORT_BUTTON_SELECTOR = "#ctl00_ContentPlaceHolder1_Export"
_CANDIDATE_SELECTOR = "#ctl00_ContentPlaceHolder1_txtCandidateName"
_RESULTS_READY_TIMEOUT_MS = 120_000
_DOWNLOAD_EVENT_TIMEOUT_MS = 180_000
_ALLOWED_SEARCH_URL_SCHEME = "https"
_ALLOWED_SEARCH_URL_HOSTS = frozenset({"media.ethics.ga.gov"})

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError as import_error:
    _sync_playwright = None
    _playwright_import_error: Exception | None = import_error
else:
    _playwright_import_error = None


def _normalize_data_type(data_type: str) -> str:
    return data_type.strip().lower()


def _require_playwright() -> None:
    if _sync_playwright is not None:
        return
    raise RuntimeError(
        "Playwright is required for GA portal download. "
        "Install download dependencies with `uv sync --extra download` "
        "and browser binaries with `uv run --extra download playwright install chromium`."
    ) from _playwright_import_error


def build_search_url(data_type: str) -> str:
    normalized_data_type = _normalize_data_type(data_type)
    source_block = _find_ga_data_source_block_by_transaction_type(normalized_data_type)
    if source_block is None:
        raise ValueError(f"Unsupported GA data type: {data_type}")
    return source_block.url


def _validate_search_url(search_url: str) -> str:
    parsed_url = urlsplit(search_url)
    if (
        parsed_url.scheme != _ALLOWED_SEARCH_URL_SCHEME
        or parsed_url.hostname not in _ALLOWED_SEARCH_URL_HOSTS
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError("GA search URL must use https://media.ethics.ga.gov without embedded credentials")
    return search_url


def _fill_search_form(
    page: object,
    date_selectors: tuple[str, str],
    candidate: str,
    date_start: str,
    date_end: str,
) -> None:
    date_start_selector, date_end_selector = date_selectors
    page.fill(_CANDIDATE_SELECTOR, candidate)
    page.fill(date_start_selector, date_start)
    page.fill(date_end_selector, date_end)


def _trigger_export_download(page: object, dest_dir: Path) -> Path:
    export_button = page.locator(_EXPORT_BUTTON_SELECTOR)
    try:
        export_button.wait_for(state="visible", timeout=_RESULTS_READY_TIMEOUT_MS)
    except Exception:
        # Save a debug screenshot when the export button doesn't appear.
        # This helps diagnose whether the search returned no results,
        # the portal changed its layout, or the postback failed.
        debug_path = dest_dir / "ga_export_timeout_debug.png"
        try:
            page.screenshot(path=str(debug_path))
        except Exception:
            pass
        raise
    with page.expect_download(timeout=_DOWNLOAD_EVENT_TIMEOUT_MS) as download_info:
        export_button.click(no_wait_after=True)

    download = download_info.value
    destination_path = dest_dir / Path(download.suggested_filename).name
    download.save_as(str(destination_path))
    return destination_path


def download_ga_export(
    data_type: str,
    *,
    dest_dir: Path,
    candidate: str,
    date_start: str,
    date_end: str,
) -> Path:
    _require_playwright()

    normalized_data_type = _normalize_data_type(data_type)
    source_block = _find_ga_data_source_block_by_transaction_type(normalized_data_type)
    if source_block is None:
        raise ValueError(f"Unsupported GA data type: {data_type}")
    if source_block.last_verified_working is None:
        source_issue_summary = (
            source_block.known_issues[0] if source_block.known_issues else "missing last_verified_working"
        )
        raise RuntimeError(
            "GA data type "
            f"{normalized_data_type!r} is configured but not currently verified for live export: {source_issue_summary}"
        )
    date_selectors = _load_date_selectors_for_transaction_type(normalized_data_type)

    search_url = _validate_search_url(build_search_url(normalized_data_type))
    dest_dir.mkdir(parents=True, exist_ok=True)

    with _sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            browser_context = browser.new_context(accept_downloads=True)
            try:
                page = browser_context.new_page()
                # ASP.NET WebForms pages can keep background network activity
                # alive via ViewState updates and polling, so DOM parsing is
                # the stable readiness signal for this page.
                page.goto(search_url, wait_until="domcontentloaded")
                _fill_search_form(page, date_selectors, candidate, date_start, date_end)
                # ASP.NET WebForms uses __doPostBack for the search button.
                # Clicking triggers a full page reload via form POST. We must
                # wait for navigation to complete before looking for the
                # Export button on the result page. Use domcontentloaded
                # because networkidle can hang on WebForms postback traffic.
                with page.expect_navigation(wait_until="domcontentloaded", timeout=_RESULTS_READY_TIMEOUT_MS):
                    page.locator(_SEARCH_BUTTON_SELECTOR).click()
                return _trigger_export_download(page, dest_dir)
            finally:
                browser_context.close()
        finally:
            browser.close()
