from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import (
    CONTRIBUTION_COLUMNS,
    _find_ga_data_source_block_by_transaction_type,
    _load_date_selectors_for_transaction_type,
)

_SEARCH_BUTTON_SELECTOR = "#ctl00_ContentPlaceHolder1_Search"
_EXPORT_BUTTON_SELECTOR = "#ctl00_ContentPlaceHolder1_Export"
_CANDIDATE_SELECTOR = "#ctl00_ContentPlaceHolder1_txtCandidateName"
_PAGE_GOTO_TIMEOUT_MS = 15_000
_RESULTS_READY_TIMEOUT_MS = 30_000
_DOWNLOAD_EVENT_TIMEOUT_MS = 35_000
_CONTRIBUTION_RESULTS_PATH = "Campaign_ByContributionsearchresults.aspx"
_CONTRIBUTION_RESULTS_GRID_SELECTOR = "#ctl00_ContentPlaceHolder1_dgContSummary"
_CONTRIBUTION_GRID_DATA_CELL_COUNT = 7
_CONTRIBUTION_EXPORT_FILENAME = "StateEthicsReport.csv"
_CONTENT_DISPOSITION_FILENAME_PATTERN = re.compile(r'filename="?([^";]+)"?', re.IGNORECASE)
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


def _is_contribution_results_page(page: object) -> bool:
    return _CONTRIBUTION_RESULTS_PATH in str(page.url)


def _collect_form_data(page: object) -> dict[str, str]:
    return page.evaluate(
        """
        () => {
            const form = document.querySelector("form");
            const formData = {};
            for (const element of form.elements) {
                if (
                    !element.name
                    || element.disabled
                    || ["button", "image", "reset", "submit"].includes(element.type)
                ) {
                    continue;
                }
                if ((element.type === "checkbox" || element.type === "radio") && !element.checked) {
                    continue;
                }
                formData[element.name] = element.value;
            }
            return formData;
        }
        """
    )


def _filename_from_content_disposition(content_disposition: str | None, fallback: str) -> str:
    if content_disposition is None:
        return fallback
    filename_match = _CONTENT_DISPOSITION_FILENAME_PATTERN.search(content_disposition)
    if filename_match is None:
        return fallback
    return Path(filename_match.group(1)).name


def _save_contribution_export_response(page: object, export_button: object, dest_dir: Path) -> Path:
    # The search form may redirect. Revalidate immediately before forwarding
    # hidden WebForms state so a cross-origin result page cannot receive it.
    response_url = _validate_search_url(str(page.url))
    export_button_name = export_button.get_attribute("name")
    if not export_button_name:
        raise RuntimeError("GA contribution export button is missing a form field name")

    form_data = _collect_form_data(page)
    form_data[f"{export_button_name}.x"] = "1"
    form_data[f"{export_button_name}.y"] = "1"
    try:
        response = page.context.request.post(
            response_url,
            form=form_data,
            timeout=_DOWNLOAD_EVENT_TIMEOUT_MS,
            max_redirects=0,
        )
    except Exception:
        return _save_contribution_result_grid(page, dest_dir)

    if not 200 <= response.status < 300:
        raise RuntimeError(f"GA contribution export POST failed with HTTP {response.status}")
    filename = _filename_from_content_disposition(
        response.headers.get("content-disposition"),
        _CONTRIBUTION_EXPORT_FILENAME,
    )
    response_body = response.body()
    if not response_body:
        raise RuntimeError("GA contribution export POST returned an empty response body")
    destination_path = dest_dir / filename
    destination_path.write_bytes(response_body)
    return destination_path


def _save_contribution_result_grid(page: object, dest_dir: Path) -> Path:
    grid_rows = page.evaluate(
        f"""
        () => Array.from(document.querySelectorAll("{_CONTRIBUTION_RESULTS_GRID_SELECTOR} tr"))
            .map((row) => Array.from(row.cells).map((cell) => cell.innerText))
        """
    )
    if _contribution_grid_has_pagination_controls(grid_rows):
        raise RuntimeError(
            "GA contribution paginated result grid cannot be safely exported from the visible page fallback"
        )

    csv_rows = [
        _contribution_grid_row_to_csv_row(row)
        for row in grid_rows[1:]
        if len(row) == _CONTRIBUTION_GRID_DATA_CELL_COUNT
    ]
    if not csv_rows:
        raise RuntimeError("GA contribution result grid did not contain exportable rows")

    destination_path = dest_dir / _CONTRIBUTION_EXPORT_FILENAME
    with destination_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(CONTRIBUTION_COLUMNS)
        writer.writerows(csv_rows)
    return destination_path


def _contribution_grid_has_pagination_controls(grid_rows: list[list[str]]) -> bool:
    return any(_is_contribution_grid_pager_row(row) for row in grid_rows[1:])


def _is_contribution_grid_pager_row(row: list[str]) -> bool:
    if len(row) == _CONTRIBUTION_GRID_DATA_CELL_COUNT:
        return False
    pager_tokens = [token for cell in row for token in re.split(r"\s+", cell.strip()) if token]
    return any(token == "..." or (token.isdigit() and int(token) > 1) for token in pager_tokens)


def _contribution_grid_row_to_csv_row(row: list[str]) -> list[str]:
    filer_id, committee_name, candidate_name = _split_lines(row[0], min_count=3)[:3]
    contributor_lines = _split_lines(row[1], min_count=3)
    pac_affiliation, occupation, employer = _split_lines(row[2], min_count=3)[:3]
    transaction_date, transaction_type, election, election_year = _split_lines(row[3], min_count=4)[:4]
    candidate_first, candidate_middle, candidate_last, candidate_suffix = _split_candidate_name(candidate_name)
    city, state, zip_code = _split_city_state_zip(contributor_lines[2])
    values = {
        "FilerID": filer_id,
        "Type": transaction_type,
        "LastName": contributor_lines[0],
        "FirstName": "",
        "Address": contributor_lines[1],
        "City": city,
        "State": state,
        "Zip": zip_code,
        "PAC": pac_affiliation,
        "Occupation": occupation,
        "Employer": employer,
        "Date": f"{transaction_date} 12:00:00 AM",
        "Election": election,
        "Election_Year": election_year,
        "Cash_Amount": _grid_amount_to_export_amount(row[4]),
        "In_Kind_Amount": _grid_amount_to_export_amount(row[5]),
        "In_Kind_Description": row[6].strip(),
        "Candidate_FirstName": candidate_first,
        "Candidate_MiddleName": candidate_middle,
        "Candidate_LastName": candidate_last,
        "Candidate_Suffix": candidate_suffix,
        "Committee_Name": committee_name,
    }
    return [values[column] for column in CONTRIBUTION_COLUMNS]


def _split_lines(value: str, *, min_count: int) -> list[str]:
    lines = [line.strip() for line in value.splitlines()]
    while len(lines) < min_count:
        lines.append("")
    return lines


def _split_candidate_name(candidate_name: str) -> tuple[str, str, str, str]:
    parts = candidate_name.split()
    suffix = ""
    if len(parts) >= 3 and parts[-1].rstrip(".").lower() in {"jr", "sr", "ii", "iii", "iv"}:
        suffix = parts.pop()
    if len(parts) <= 1:
        return candidate_name, "", "", suffix
    return parts[0], " ".join(parts[1:-1]), parts[-1], suffix


def _split_city_state_zip(value: str) -> tuple[str, str, str]:
    city, _, state_zip = value.partition(",")
    state_zip_parts = state_zip.strip().split()
    if not state_zip_parts:
        return city.strip(), "", ""
    return city.strip(), " ".join(state_zip_parts[:-1]), state_zip_parts[-1]


def _grid_amount_to_export_amount(value: str) -> str:
    normalized = value.strip().replace("$", "").replace(",", "")
    if not normalized:
        return ""
    return f"{float(normalized):.4f}"


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
    if _is_contribution_results_page(page):
        return _save_contribution_export_response(page, export_button, dest_dir)
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
                page.goto(search_url, wait_until="domcontentloaded", timeout=_PAGE_GOTO_TIMEOUT_MS)
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
