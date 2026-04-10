
from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import tempfile
from typing import Callable

import httpx

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError as import_error:
    _sync_playwright = None
    _playwright_import_error: Exception | None = import_error
else:
    _playwright_import_error = None

from . import (
    _load_bulk_download_url_for_data_type,
    _load_data_source_url_for_data_type,
    _normalize_data_type,
)

REQUEST_TIMEOUT_SECONDS = 30.0
_FL_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_REQUIRES_SINGLE_DAY_RANGE = {"expenditures", "transfers"}
_EXPECTED_CONTENT_TYPE_PREFIX = "text/tab-separated-values"
_FL_CANDIDATE_LIST_URL = "https://dos.elections.myflorida.com/candidates/downloadcanlist.asp"
_CANDIDATE_LIST_ALLOWED_CONTENT_TYPES = {
    "text/tab-separated-values",
    "text/plain",
    "application/octet-stream",
}
_DIAGNOSTIC_HEADER_NAMES = ("server", "content-type", "content-length", "cf-ray")
_MAX_DIAGNOSTIC_BODY_CHARS = 400
_DOWNLOAD_EVENT_TIMEOUT_MS = 180_000
_FL_QUERY_PAGE_FORM_SELECTORS = {
    "election": 'select[name="election"]',
    "search_on_date_range": 'input[name="search_on"][value="4"]',
    "queryformat_tab": 'input[name="queryformat"][value="2"]',
    "date_from": 'input[name="cdatefrom"]',
    "date_to": 'input[name="cdateto"]',
    "rowlimit": 'input[name="rowlimit"]',
    "submit": 'input[name="Submit"]',
}


def _require_playwright() -> None:
    if _sync_playwright is not None:
        return
    raise RuntimeError(
        "Playwright is required for FL browser-session download fallback. "
        "Install download dependencies with `uv sync --extra download` "
        "and browser binaries with `uv run --extra download playwright install chrome`."
    ) from _playwright_import_error


def _validate_date_window(data_type: str, date_from: date, date_to: date) -> None:
    if data_type in _REQUIRES_SINGLE_DAY_RANGE and date_from != date_to:
        raise ValueError(f"FL {data_type} export requires single-day date windows")


def _format_fl_date(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def _validate_rowlimit(rowlimit: int) -> None:
    if rowlimit < 0:
        raise ValueError("FL rowlimit must be >= 0")


def _build_form_data(*, election: str, date_from: date, date_to: date, rowlimit: int) -> dict[str, str]:
    return {
        "election": election,
        "search_on": "4",
        "queryformat": "2",
        "cdatefrom": _format_fl_date(date_from),
        "cdateto": _format_fl_date(date_to),
        "rowlimit": str(rowlimit),
    }


def _extract_response_body_snippet(response: httpx.Response) -> str:
    try:
        body_bytes = response.read()
    except Exception:
        return "<unavailable>"

    if isinstance(body_bytes, (bytes, bytearray)):
        body_text = body_bytes.decode("utf-8", errors="replace")
    else:
        body_text = str(body_bytes)
    compact_body = " ".join(body_text.split())
    return compact_body[:_MAX_DIAGNOSTIC_BODY_CHARS]


def _format_response_diagnostics(response: httpx.Response) -> str:
    header_parts = []
    for header_name in _DIAGNOSTIC_HEADER_NAMES:
        header_value = response.headers.get(header_name)
        if header_value is not None:
            header_parts.append(f"{header_name}={header_value!r}")

    return (
        f"status={response.status_code} "
        f"content_type={response.headers.get('content-type', '')!r} "
        f"headers={', '.join(header_parts) if header_parts else 'none'} "
        f"body_snippet={_extract_response_body_snippet(response)!r}"
    )


def _validate_response_content_type(response: httpx.Response) -> None:
    content_type = response.headers.get("content-type", "")
    normalized_content_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized_content_type != _EXPECTED_CONTENT_TYPE_PREFIX:
        raise ValueError(
            "Unexpected FL export Content-Type: "
            f"expected {_EXPECTED_CONTENT_TYPE_PREFIX!r} but received {content_type!r}; "
            f"{_format_response_diagnostics(response)}"
        )


def _validate_candidate_list_content_type(response: httpx.Response) -> None:
    content_type = response.headers.get("content-type", "")
    normalized_content_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized_content_type not in _CANDIDATE_LIST_ALLOWED_CONTENT_TYPES:
        raise ValueError(
            "Unexpected FL candidate-list Content-Type: "
            f"expected one of {sorted(_CANDIDATE_LIST_ALLOWED_CONTENT_TYPES)!r} but received {content_type!r}; "
            f"{_format_response_diagnostics(response)}"
        )


def _stream_export_to_path(
    *,
    url: str,
    destination_path: Path,
    headers: dict[str, str],
    form_data: dict[str, str],
) -> None:
    _write_part_file(
        destination_path,
        lambda temporary_download_path: _stream_http_export_to_path(
            url=url,
            destination_path=temporary_download_path,
            headers=headers,
            form_data=form_data,
        ),
    )


def _write_part_file(destination_path: Path, write_download: Callable[[Path], None]) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        write_download(temporary_download_path)
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def _stream_http_export_to_path(
    *,
    url: str,
    destination_path: Path,
    headers: dict[str, str],
    form_data: dict[str, str],
) -> None:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
        with http_client.stream(
            "POST",
            url,
            headers=headers,
            data=form_data,
            follow_redirects=True,
        ) as response:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                request_url = str(error.request.url) if error.request is not None else url
                if error.response is None:
                    raise ValueError(f"FL export request failed: url={request_url!r}; error={error}") from error
                raise ValueError(
                    f"FL export request failed: url={request_url!r}; {_format_response_diagnostics(error.response)}"
                ) from error
            _validate_response_content_type(response)
            with destination_path.open("wb") as destination_file:
                for chunk in response.iter_bytes():
                    if chunk:
                        destination_file.write(chunk)


def _build_destination_path(data_type: str, date_from: date, date_to: date, dest_dir: Path) -> Path:
    filename = f"fl_{data_type}_{date_from.isoformat()}_{date_to.isoformat()}.txt"
    return dest_dir / filename


def _is_browser_fallback_candidate(error: ValueError) -> bool:
    message = str(error).lower()
    return "status=502" in message and "cloudflare" in message


def _download_fl_export_playwright(
    *,
    data_type: str,
    destination_path: Path,
    form_data: dict[str, str],
) -> None:
    _require_playwright()
    query_page_url = _load_data_source_url_for_data_type(data_type)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    with _sync_playwright() as playwright:  # type: ignore[misc]
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            browser_context = browser.new_context(
                accept_downloads=True,
                user_agent=_FL_USER_AGENT,
            )
            try:
                page = browser_context.new_page()
                page.goto(query_page_url, wait_until="domcontentloaded", timeout=_DOWNLOAD_EVENT_TIMEOUT_MS)
                page.select_option(_FL_QUERY_PAGE_FORM_SELECTORS["election"], form_data["election"])
                page.check(_FL_QUERY_PAGE_FORM_SELECTORS["search_on_date_range"])
                page.fill(_FL_QUERY_PAGE_FORM_SELECTORS["date_from"], form_data["cdatefrom"])
                page.fill(_FL_QUERY_PAGE_FORM_SELECTORS["date_to"], form_data["cdateto"])
                page.fill(_FL_QUERY_PAGE_FORM_SELECTORS["rowlimit"], form_data["rowlimit"])
                page.check(_FL_QUERY_PAGE_FORM_SELECTORS["queryformat_tab"])
                with page.expect_download(timeout=_DOWNLOAD_EVENT_TIMEOUT_MS) as download_info:
                    page.locator(_FL_QUERY_PAGE_FORM_SELECTORS["submit"]).click()
                download = download_info.value
                _write_part_file(destination_path, lambda temp_path: download.save_as(str(temp_path)))
            finally:
                browser_context.close()
        finally:
            browser.close()


def download_fl_export(
    data_type: str,
    date_from: date,
    date_to: date,
    dest_dir: Path,
    *,
    election: str,
    rowlimit: int,
) -> Path:
    normalized_data_type = _normalize_data_type(data_type)
    _validate_date_window(normalized_data_type, date_from, date_to)
    _validate_rowlimit(rowlimit)

    download_url = _load_bulk_download_url_for_data_type(normalized_data_type)
    destination_path = _build_destination_path(normalized_data_type, date_from, date_to, dest_dir)
    form_data = _build_form_data(election=election, date_from=date_from, date_to=date_to, rowlimit=rowlimit)
    headers = {"User-Agent": _FL_USER_AGENT}

    try:
        _stream_export_to_path(
            url=download_url,
            destination_path=destination_path,
            headers=headers,
            form_data=form_data,
        )
    except ValueError as error:
        if not _is_browser_fallback_candidate(error):
            raise
        try:
            _download_fl_export_playwright(
                data_type=normalized_data_type,
                destination_path=destination_path,
                form_data=form_data,
            )
        except RuntimeError as playwright_error:
            raise ValueError(f"{error}; browser-session fallback unavailable: {playwright_error}") from playwright_error
    return destination_path


def download_fl_candidate_list(dest_dir: Path) -> Path:
    """Download FL candidate list TSV from the state candidate endpoint."""
    destination_path = dest_dir / "fl_candidates_current.txt"
    headers = {"User-Agent": _FL_USER_AGENT}

    def _download_to_path(temporary_download_path: Path) -> None:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
            with http_client.stream(
                "GET",
                _FL_CANDIDATE_LIST_URL,
                headers=headers,
                follow_redirects=True,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    request_url = str(error.request.url) if error.request is not None else _FL_CANDIDATE_LIST_URL
                    if error.response is None:
                        raise ValueError(
                            f"FL candidate-list request failed: url={request_url!r}; error={error}"
                        ) from error
                    raise ValueError(
                        "FL candidate-list request failed: "
                        f"url={request_url!r}; {_format_response_diagnostics(error.response)}"
                    ) from error

                _validate_candidate_list_content_type(response)
                with temporary_download_path.open("wb") as destination_file:
                    for chunk in response.iter_bytes():
                        if chunk:
                            destination_file.write(chunk)

    _write_part_file(destination_path, _download_to_path)
    return destination_path
