"""Download helpers for AL campaign finance data from the FCPA JSON API.

The FCPA portal at fcpa.alabamavotes.gov provides a paginated JSON search API.
Contributions use the contributionsearchresults page; expenditures use
expendituresearchresults. The live API returns nested JSON:
``{"success": true, "data": {"totalRecords": N, "list": [...]}}``.
This module normalizes the response to ``{"totalRecords": N, "data": [...]}``
for downstream parse compatibility.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import httpx

from . import _load_api_base_url_for_data_type

LOGGER = logging.getLogger(__name__)

# FCPA API supports large page sizes — use 50K to minimize round-trips.
DEFAULT_PAGE_SIZE = 50_000

REQUEST_TIMEOUT_SECONDS = 120.0

# Max total response bytes per download to guard against runaway responses.
MAX_DOWNLOAD_BYTES = 2_147_483_648  # 2 GB

# FCPA search API page names by data type.
_API_PAGE_NAMES: dict[str, str] = {
    "contributions": "com.acf.common.page.contributionsearchresults",
    "expenditures": "com.acf.common.page.expendituresearchresults",
}

# FCPA sort fields by data type.
_SORT_FIELDS: dict[str, str] = {
    "contributions": "receivedDate",
    "expenditures": "expendedDate",
}


def build_al_search_url(
    data_type: str,
    *,
    page_number: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort_direction: str = "DESC",
) -> str:
    """Build an FCPA search API URL for the given data type and pagination params.

    The criteria parameter is an empty JSON array (no server-side filtering)
    because we apply year filtering on the client side during parse.
    """
    normalized = data_type.strip().lower()
    page_name = _API_PAGE_NAMES.get(normalized)
    if page_name is None:
        raise ValueError(f"Unsupported AL data type for download: {data_type}")

    sort_field = _SORT_FIELDS[normalized]
    base_url = _load_api_base_url_for_data_type(normalized)

    return (
        f"{base_url}/page.request.do"
        f"?page={page_name}"
        f"&pageNumber={page_number}"
        f"&pageSize={page_size}"
        f"&sortDirection={sort_direction}"
        f"&sortBy={sort_field}"
        f"&criteria=%5B%5D"
    )


def _fetch_al_page(url: str) -> dict:
    """Fetch a single FCPA API page and return normalized dict.

    The live FCPA API returns ``{"success": true, "data": {"totalRecords": N, "list": [...]}}``.
    This function normalizes to ``{"totalRecords": N, "data": [...]}``.
    """
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict) or not payload.get("success"):
        raise ValueError(f"FCPA API returned unexpected response: {json.dumps(payload)[:200]}")

    raw_data = payload.get("data")
    if isinstance(raw_data, dict):
        return {
            "totalRecords": raw_data.get("totalRecords", 0),
            "data": raw_data.get("list", []),
        }
    if isinstance(raw_data, list):
        return {
            "totalRecords": payload.get("totalRecords", 0),
            "data": raw_data,
        }
    raise ValueError(f"FCPA API 'data' field has unexpected type: {type(raw_data)}")


def download_al_json(
    data_type: str,
    dest_dir: Path,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
) -> Path:
    """Download all pages of AL FCPA search results and save as a single JSON file.

    Paginates through the API, collecting all rows into a single combined
    JSON file with {"totalRecords": N, "data": [...]}.

    Args:
        data_type: "contributions" or "expenditures"
        dest_dir: Directory to write the output JSON
        page_size: Number of rows per API request
        max_pages: Optional limit on number of pages to fetch (for testing)

    Returns:
        Path to the downloaded JSON file.
    """
    normalized = data_type.strip().lower()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"AL_{normalized}.json"

    # Write to a temp file, then atomic-rename on success.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".AL_{normalized}.",
        suffix=".part",
        dir=dest_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        all_rows: list[dict] = []
        page_number = 1
        total_records = None

        while True:
            if max_pages is not None and page_number > max_pages:
                break

            url = build_al_search_url(normalized, page_number=page_number, page_size=page_size)
            LOGGER.info("Downloading AL %s page %d (pageSize=%d)", normalized, page_number, page_size)

            payload = _fetch_al_page(url)
            page_data = payload.get("data", [])

            if total_records is None:
                total_records = payload.get("totalRecords", 0)
                LOGGER.info("AL %s: totalRecords=%d", normalized, total_records)

            all_rows.extend(page_data)
            LOGGER.info("AL %s: fetched %d rows so far", normalized, len(all_rows))

            # If this page returned fewer rows than requested, we've reached the end.
            if len(page_data) < page_size:
                break

            page_number += 1

        # Write combined output as single JSON file.
        combined = {
            "totalRecords": total_records or len(all_rows),
            "data": all_rows,
        }
        tmp_path.write_text(json.dumps(combined), encoding="utf-8")

        # Guard against unexpectedly large files.
        if tmp_path.stat().st_size > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"AL download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes")

        tmp_path.replace(dest_path)
        LOGGER.info("AL %s download complete: %d total rows -> %s", normalized, len(all_rows), dest_path)
        return dest_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
