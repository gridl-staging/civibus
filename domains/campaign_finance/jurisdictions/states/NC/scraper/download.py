
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlencode

import httpx

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError as import_error:
    _sync_playwright = None
    _playwright_import_error: Exception | None = import_error
else:
    _playwright_import_error = None

_PARAMS_PATTERN = re.compile(
    r"""\$\('input\[name="Params"\]'\)\.val\('(\{.+?\})'\)""",
)


class BrowserAutomationRequiredError(Exception):
    """Raised when the NC portal requires browser automation that httpx cannot handle."""


def _require_playwright() -> None:
    if _sync_playwright is not None:
        return
    raise RuntimeError(
        "Playwright is required for NC transaction download. "
        "Install download dependencies with `uv sync --extra download` "
        "and browser binaries with `uv run --extra download playwright install chrome`."
    ) from _playwright_import_error


@dataclass(frozen=True, slots=True)
class TransactionSearchCriteria:

    last_name: str = ""
    first_name: str = ""
    org_name: str = ""
    is_org: bool = False
    trans_type: str = ""
    committee_name: str = ""
    committee_id: str = ""
    date_from: str = ""
    date_to: str = ""
    amount_from: str = ""
    amount_to: str = ""
    county: str = ""
    city: str = ""
    city_letter: str = ""
    use_city: bool = False


def _build_transaction_search_form(
    criteria: TransactionSearchCriteria,
) -> dict[str, str]:
    return {
        "SelectedTransType": criteria.trans_type,
        "LastName": criteria.last_name,
        "FirstName": criteria.first_name,
        "OrgName": criteria.org_name,
        "IsOrg": str(criteria.is_org).lower(),
        "CommText": criteria.committee_name,
        "CommName": "",
        "CommID": criteria.committee_id,
        "DateFrom": criteria.date_from,
        "DateTo": criteria.date_to,
        "AmountFrom": criteria.amount_from,
        "AmountTo": criteria.amount_to,
        "SelectedCounty": criteria.county,
        "SelectedCityLetter": criteria.city_letter,
        "SelectedCity": criteria.city,
        "UseCity": str(criteria.use_city).lower(),
    }


def download_transaction_export(
    criteria: TransactionSearchCriteria,
    dest_path: Path,
) -> None:
    search_form = _build_transaction_search_form(criteria)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        # Step 1: GET search page to establish session
        client.get(_TXN_SEARCH_URL).raise_for_status()

        # Step 2: POST search form to get results page with Params
        results_response = client.post(_TXN_RESULTS_URL, data=search_form)
        results_response.raise_for_status()
        try:
            params_json = _extract_transaction_export_params(results_response.text)
        except ValueError as exc:
            raise BrowserAutomationRequiredError(str(exc)) from exc

        # Step 3: POST Params to export endpoint and stream CSV
        export_response = client.post(_TXN_EXPORT_URL, data={"Params": params_json})
        export_response.raise_for_status()
        _validate_csv_export_response(
            export_response,
            export_label="Transaction export",
            empty_csv_message=(
                "Transaction export returned empty CSV; the server-side query "
                "was not executed — this endpoint requires browser automation "
                "to trigger the Ignite UI grid's AJAX paging before export"
            ),
        )
        _stream_response_to_path(export_response, dest_path)


def _validate_csv_export_response(
    response: httpx.Response,
    *,
    export_label: str,
    empty_csv_message: str,
) -> None:
    if _is_html_response(response):
        raise BrowserAutomationRequiredError(
            f"{export_label} returned HTML instead of CSV; the portal may require browser automation"
        )
    if not _is_csv_response(response):
        content_type = response.headers.get("content-type", "")
        raise BrowserAutomationRequiredError(
            f"{export_label} returned unexpected content type {content_type!r} "
            "instead of CSV; the portal contract may have changed or require "
            "browser automation"
        )
    if _is_empty_csv(response):
        raise BrowserAutomationRequiredError(empty_csv_message)


def _extract_transaction_export_params(results_html: str) -> str:
    match = _PARAMS_PATTERN.search(results_html)
    if match is None:
        raise ValueError(
            "Could not find Params payload in transaction results HTML; the portal may require browser automation"
        )
    return match.group(1)


_NC_PORTAL_BASE = "https://cf.ncsbe.gov"
_TXN_SEARCH_URL = f"{_NC_PORTAL_BASE}/CFTxnLkup/"
_TXN_RESULTS_URL = f"{_NC_PORTAL_BASE}/CFTxnLkup/TxnSearchResults/"
_TXN_EXPORT_URL = f"{_NC_PORTAL_BASE}/CFTxnLkup/ExportResults/"
_COMMITTEE_EXPORT_BASE = f"{_NC_PORTAL_BASE}/CFOrgLkup/ExportSearchResults/"
_REQUEST_TIMEOUT_SECONDS = 60.0


def _stream_response_to_path(response: httpx.Response, destination: Path) -> None:
    _write_part_file(
        destination,
        lambda temp_path: _write_response_stream(response, temp_path),
    )


def _write_part_file(
    destination: Path,
    write_to_part_path: Callable[[Path], None],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    part_path = temp_dir / destination.name
    try:
        write_to_part_path(part_path)
        part_path.replace(destination)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _write_response_stream(response: httpx.Response, destination: Path) -> None:
    with destination.open("wb") as f:
        for chunk in response.iter_bytes():
            if chunk:
                f.write(chunk)


def _build_committee_export_url(org_group_id: str, title: str) -> str:
    normalized_org_group_id = org_group_id.strip()
    if not normalized_org_group_id:
        raise ValueError("org_group_id must not be blank")
    query = urlencode({"OGID": normalized_org_group_id, "Title": title, "Type": "DocGen"})
    return f"{_COMMITTEE_EXPORT_BASE}?{query}"


def _is_html_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return "html" in content_type.lower()


def _is_csv_response(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    normalized_content_type = content_type.lower()
    if "csv" in normalized_content_type or "excel" in normalized_content_type:
        return True
    if normalized_content_type and "octet-stream" not in normalized_content_type:
        return False

    content_disposition = response.headers.get("content-disposition", "")
    return ".csv" in content_disposition.lower()


def _is_empty_csv(response: httpx.Response) -> bool:
    return response.content.strip() == b""


def download_committee_document_export(
    org_group_id: str,
    title: str,
    dest_path: Path,
) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    url = _build_committee_export_url(org_group_id, title)
    with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(url)
        response.raise_for_status()
        _validate_csv_export_response(
            response,
            export_label="Committee export",
            empty_csv_message=(
                "Committee export returned empty CSV; the export URL or required portal state may have changed"
            ),
        )
        _stream_response_to_path(response, dest_path)


# --- Playwright-based transaction export ---

_SEARCH_BUTTON_SELECTOR = "#btnSearch"
_EXPORT_BUTTON_SELECTOR = "#btnExportResults"
_ORG_CHECKBOX_SELECTOR = "#IsOrg"
_CITY_SELECTOR = "#City"
_USE_CITY_SELECTOR = "#UseCity"
_RESULTS_READY_TIMEOUT_MS = 120_000
_DOWNLOAD_EVENT_TIMEOUT_MS = 180_000
_RESULTS_POLL_INTERVAL_MS = 500
_HIDDEN_SEARCH_FIELD_SELECTORS = frozenset({_USE_CITY_SELECTOR, "#CommID"})
_VALID_TRANS_TYPE_VALUES = frozenset({"all", "rec", "exp"})
_DEPENDENT_CITY_SEARCH_FIELD_ATTRS = frozenset({"county", "city_letter", "city"})
_NON_SPECIFIC_COUNTY_VALUE = "0"
_NON_SPECIFIC_CITY_LETTER_VALUES = frozenset({"", "*", "All"})

# Declarative mapping from TransactionSearchCriteria attrs to DOM selectors.
# Uses element IDs (unique on the NC search page, verified live 2026-03-16).
# Action: "fill" for <input>, "select" for <select>.
_NC_SEARCH_FORM_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("trans_type", "#TransType", "select"),
    ("last_name", "#LastName", "fill"),
    ("first_name", "#FirstName", "fill"),
    ("org_name", "#OrgName", "fill"),
    ("committee_name", "#CommText", "fill"),
    ("committee_id", "#CommID", "fill"),
    ("date_from", "#DateFrom", "fill"),
    ("date_to", "#DateTo", "fill"),
    ("amount_from", "#AmountFrom", "fill"),
    ("amount_to", "#AmountTo", "fill"),
    ("county", "#County", "select"),
    ("city_letter", "#CityLetter", "select"),
    ("city", "#City", "select"),
)


def _fill_transaction_search_form_playwright(
    page: object,
    criteria: TransactionSearchCriteria,
) -> None:
    _validate_playwright_search_criteria(criteria)

    _set_hidden_search_field_value(page, _USE_CITY_SELECTOR, "false")
    if criteria.is_org:
        page.check(_ORG_CHECKBOX_SELECTOR)  # type: ignore[union-attr]

    for attr, selector, action in _NC_SEARCH_FORM_FIELDS:
        if attr in _DEPENDENT_CITY_SEARCH_FIELD_ATTRS:
            continue
        value = getattr(criteria, attr)
        if not value:
            continue
        _apply_search_field_value(page, selector, action, value)

    _apply_dependent_city_filters(page, criteria)

    if criteria.use_city:
        _set_hidden_search_field_value(page, _USE_CITY_SELECTOR, "true")


def _apply_search_field_value(
    page: object,
    selector: str,
    action: str,
    value: str,
) -> None:
    if selector in _HIDDEN_SEARCH_FIELD_SELECTORS:
        _set_hidden_search_field_value(page, selector, value)
        return
    if action == "fill":
        page.fill(selector, value)  # type: ignore[union-attr]
        return
    page.select_option(selector, value)  # type: ignore[union-attr]


def _apply_dependent_city_filters(
    page: object,
    criteria: TransactionSearchCriteria,
) -> None:
    county_selector, county_action = _lookup_search_form_field("county")
    city_letter_selector, city_letter_action = _lookup_search_form_field("city_letter")
    city_selector, city_action = _lookup_search_form_field("city")

    if _has_specific_county(criteria):
        _apply_search_field_value(page, county_selector, county_action, criteria.county)
    if _has_specific_city_letter(criteria.city_letter):
        _apply_search_field_value(
            page,
            city_letter_selector,
            city_letter_action,
            criteria.city_letter,
        )
    if criteria.city:
        trigger_selector, trigger_value = _resolve_city_option_trigger(criteria)
        _wait_for_city_option(
            page,
            city_value=criteria.city,
            trigger_selector=trigger_selector,
            trigger_value=trigger_value,
        )
        _apply_search_field_value(page, city_selector, city_action, criteria.city)


def _lookup_search_form_field(criteria_attr: str) -> tuple[str, str]:
    for attr, selector, action in _NC_SEARCH_FORM_FIELDS:
        if attr == criteria_attr:
            return selector, action
    raise ValueError(f"Missing NC search field mapping for {criteria_attr!r}")


def _resolve_city_option_trigger(
    criteria: TransactionSearchCriteria,
) -> tuple[str, str]:
    if _has_specific_city_letter(criteria.city_letter):
        return _lookup_search_form_field("city_letter")[0], criteria.city_letter
    if _has_specific_county(criteria):
        return _lookup_search_form_field("county")[0], criteria.county
    raise ValueError("city requires a specific county or city_letter to populate NC city options")


def _has_specific_county(criteria: TransactionSearchCriteria) -> bool:
    return bool(criteria.county and criteria.county != _NON_SPECIFIC_COUNTY_VALUE)


def _has_specific_city_letter(city_letter: str) -> bool:
    return bool(city_letter and city_letter not in _NON_SPECIFIC_CITY_LETTER_VALUES)


def _validate_playwright_search_criteria(
    criteria: TransactionSearchCriteria,
) -> None:
    if criteria.org_name and not criteria.is_org:
        raise ValueError("org_name requires is_org=True for NC transaction search")
    if criteria.trans_type and criteria.trans_type not in _VALID_TRANS_TYPE_VALUES:
        raise ValueError("trans_type must be one of the NC portal option values: all, rec, exp")
    if criteria.county and not criteria.county.isdigit():
        raise ValueError("county must use the NC portal option value, for example '92' for WAKE")
    if criteria.city_letter and not _is_valid_city_letter_value(criteria.city_letter):
        raise ValueError("city_letter must use the NC portal option value, such as 'C', '*' or 'All'")
    if _has_specific_county(criteria) and _has_specific_city_letter(criteria.city_letter):
        raise ValueError(
            "county cannot be combined with a specific city_letter in NC Playwright "
            "search; the live portal hides CityLetter after county selection"
        )
    if criteria.city and not _has_city_option_trigger(criteria):
        raise ValueError("city requires a specific county or city_letter to populate NC city options")


def _is_valid_city_letter_value(city_letter: str) -> bool:
    return city_letter in {"*", "All"} or (len(city_letter) == 1 and city_letter.isalpha() and city_letter.isupper())


def _has_city_option_trigger(criteria: TransactionSearchCriteria) -> bool:
    return _has_specific_county(criteria) or _has_specific_city_letter(criteria.city_letter)


def _set_hidden_search_field_value(
    page: object,
    selector: str,
    value: str,
) -> None:
    page.evaluate(  # type: ignore[union-attr]
        """([fieldSelector, fieldValue]) => {
            const field = document.querySelector(fieldSelector);
            if (!field) {
                throw new Error(`Missing NC search field ${fieldSelector}`);
            }
            field.value = fieldValue;
        }""",
        [selector, value],
    )


def _wait_for_city_option(
    page: object,
    *,
    city_value: str,
    trigger_selector: str,
    trigger_value: str,
) -> None:
    page.wait_for_function(  # type: ignore[union-attr]
        """([citySelector, cityOptionValue, triggerSelector, expectedTriggerValue]) => {
            const triggerField = document.querySelector(triggerSelector);
            if (!triggerField) {
                return false;
            }
            if (triggerField.value !== expectedTriggerValue) {
                return false;
            }
            const cityField = document.querySelector(citySelector);
            if (!cityField) {
                return false;
            }
            return Array.from(cityField.options).some(
                (option) => option.value === cityOptionValue,
            );
        }""",
        arg=[_CITY_SELECTOR, city_value, trigger_selector, trigger_value],
        timeout=_RESULTS_READY_TIMEOUT_MS,
    )


def _trigger_transaction_export_download(
    page: object,
    dest_path: Path,
) -> None:
    export_button = page.locator(_EXPORT_BUTTON_SELECTOR)  # type: ignore[union-attr]
    export_button.wait_for(state="visible", timeout=_RESULTS_READY_TIMEOUT_MS)
    with page.expect_download(timeout=_DOWNLOAD_EVENT_TIMEOUT_MS) as download_info:  # type: ignore[union-attr]
        export_button.click(no_wait_after=True)
    download = download_info.value
    _write_part_file(dest_path, lambda temp_path: download.save_as(str(temp_path)))


def _classify_results_grid_failure(
    *,
    body_text: str,
    grid_status_codes: tuple[int, ...],
) -> str | None:
    """Summarize known NC results-grid failures while the export button remains hidden."""
    if grid_status_codes:
        latest_status_code = grid_status_codes[-1]
        if latest_status_code >= 500:
            return (
                "NC transaction results grid failed before export: "
                f"GetPagedResults returned {latest_status_code}. "
                "The results page still shows 'Loading Results... error', so the portal "
                "did not produce a downloadable CSV for this browser-session search."
            )

    compact_body = " ".join(body_text.split())
    if "Loading Results... error" in compact_body:
        return (
            "NC transaction results grid failed before export: the results page shows "
            "'Loading Results... error' while the export button remains hidden."
        )
    return None


def _wait_for_results_grid_or_raise(
    page: object,
    *,
    grid_status_codes: list[int],
) -> None:
    """Wait for the NC results grid to become exportable or raise a clearer portal error."""
    export_button = page.locator(_EXPORT_BUTTON_SELECTOR)  # type: ignore[union-attr]
    deadline = time.monotonic() + (_RESULTS_READY_TIMEOUT_MS / 1000)

    while time.monotonic() < deadline:
        if export_button.is_visible():
            return

        body_text = page.text_content("body") or ""  # type: ignore[union-attr]
        failure_message = _classify_results_grid_failure(
            body_text=body_text,
            grid_status_codes=tuple(grid_status_codes),
        )
        if failure_message is not None:
            raise BrowserAutomationRequiredError(failure_message)

        page.wait_for_timeout(_RESULTS_POLL_INTERVAL_MS)  # type: ignore[union-attr]

    export_button.wait_for(state="visible", timeout=1)


def download_transaction_export_playwright(
    criteria: TransactionSearchCriteria,
    dest_path: Path,
) -> None:
    _require_playwright()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with _sync_playwright() as playwright:  # type: ignore[misc]
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            browser_context = browser.new_context(accept_downloads=True)
            try:
                page = browser_context.new_page()
                get_paged_results_status_codes: list[int] = []

                def _capture_results_grid_response(response: object) -> None:
                    response_url = response.url  # type: ignore[attr-defined]
                    if "/CFTxnLkup/GetPagedResults" not in response_url:
                        return
                    get_paged_results_status_codes.append(response.status)  # type: ignore[attr-defined]

                page.on("response", _capture_results_grid_response)  # type: ignore[union-attr]
                page.goto(_TXN_SEARCH_URL, wait_until="domcontentloaded")
                _fill_transaction_search_form_playwright(page, criteria)
                page.locator(_SEARCH_BUTTON_SELECTOR).click()
                page.wait_for_load_state("domcontentloaded", timeout=_RESULTS_READY_TIMEOUT_MS)  # type: ignore[union-attr]
                _wait_for_results_grid_or_raise(page, grid_status_codes=get_paged_results_status_codes)
                _trigger_transaction_export_download(page, dest_path)
            finally:
                browser_context.close()
        finally:
            browser.close()
