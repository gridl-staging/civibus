"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_02_oh_state_pipeline/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/download.py.
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
import tempfile
from urllib.parse import urljoin, urlparse

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_DOWNLOAD_BYTES = 1_073_741_824

_COMMITTEE_TYPES = {"CAN", "PAC", "PARTY"}
_ALLOWED_DOWNLOAD_SCHEMES = {"https"}
_ALLOWED_DOWNLOAD_HOSTS = {"www6.ohiosos.gov", "www.ohiosos.gov"}
_SUFFIX_BY_DATA_TYPE = {
    "contributions": "CON",
    "expenditures": "EXP",
}


class _ApexTableHrefParser(HTMLParser):
    """Extract anchor href values contained in HTML tables."""

    def __init__(self) -> None:
        super().__init__()
        self._table_depth = 0
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()

        if lowered_tag == "table":
            self._table_depth += 1
            return

        if self._table_depth == 0 or lowered_tag != "a":
            return

        for attr_name, attr_value in attrs:
            if attr_name.lower() == "href" and attr_value:
                self.hrefs.append(attr_value)
                return

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "table" and self._table_depth > 0:
            self._table_depth -= 1


def _normalize_committee_type(committee_type: str) -> str:
    normalized_committee_type = committee_type.strip().upper()
    if normalized_committee_type not in _COMMITTEE_TYPES:
        raise ValueError(f"Unsupported OH committee type: {committee_type}")
    return normalized_committee_type


def _validate_oh_download_url(url: str, *, context: str) -> str:
    parsed_url = urlparse(url)
    normalized_scheme = parsed_url.scheme.lower()
    normalized_host = (parsed_url.hostname or "").lower()

    if normalized_scheme not in _ALLOWED_DOWNLOAD_SCHEMES:
        raise ValueError(f"{context} must use HTTPS: {url}")
    if normalized_host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(f"{context} must stay on an approved Ohio SOS host: {url}")
    return url


def _scrape_apex_file_listing(committee_type: str, *, data_type: str) -> list[str]:
    normalized_committee_type = _normalize_committee_type(committee_type)
    listing_url = _validate_oh_download_url(
        _load_bulk_download_url_for_data_type(data_type).replace("{TYPE}", normalized_committee_type),
        context="OH listing URL",
    )

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
        response = http_client.get(listing_url, follow_redirects=True)
        response.raise_for_status()
        _validate_oh_download_url(str(response.url), context="OH listing URL")

        parser = _ApexTableHrefParser()
        parser.feed(response.text)

    hrefs: list[str] = []
    for href in parser.hrefs:
        resolved_href = urljoin(str(response.url), href)
        if Path(urlparse(resolved_href).path).suffix.lower() != ".csv":
            continue
        hrefs.append(_validate_oh_download_url(resolved_href, context="OH file URL"))

    if not hrefs:
        raise ValueError(
            f"No OH CSV download links found in APEX listing for committee type {normalized_committee_type}"
        )

    return hrefs


def _match_file_url(hrefs: list[str], *, data_type: str, year: int) -> str:
    suffix = _SUFFIX_BY_DATA_TYPE.get(data_type)
    if suffix is None:
        raise ValueError(f"Unsupported OH data type: {data_type}")

    expected_suffix = f"_{suffix}_{year}.CSV"
    matches = [href for href in hrefs if Path(urlparse(href).path).name.upper().endswith(expected_suffix)]

    if len(matches) != 1:
        raise ValueError(f"Expected exactly one OH file URL ending with {expected_suffix!r} but found {len(matches)}")

    return matches[0]


def _stream_download_to_path(url: str, destination_path: Path) -> None:
    validated_url = _validate_oh_download_url(url, context="OH file URL")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
            with http_client.stream("GET", validated_url, follow_redirects=True) as response:
                response.raise_for_status()
                _validate_oh_download_url(str(response.url), context="OH file URL")
                with temporary_download_path.open("wb") as destination_file:
                    downloaded_bytes = 0
                    for chunk in response.iter_bytes():
                        if chunk:
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"OH download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes"
                                )
                            destination_file.write(chunk)
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_oh_csv(data_type: str, committee_type: str, year: int, dest_dir: Path) -> Path:
    hrefs = _scrape_apex_file_listing(committee_type, data_type=data_type)
    file_url = _match_file_url(hrefs, data_type=data_type, year=year)
    destination_path = dest_dir / Path(urlparse(file_url).path).name
    _stream_download_to_path(file_url, destination_path)
    return destination_path
