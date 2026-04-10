"""Download NY campaign finance data from the data.ny.gov SODA API.

Uses paginated CSV downloads with $limit/$offset. The SODA API returns
up to 50,000 rows per request. Date filtering uses sched_date >= threshold
to limit to the 5-year window (2022+).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import httpx

from . import _load_bulk_download_url_for_data_type

LOGGER = logging.getLogger(__name__)

# SODA API max rows per request — tested and confirmed working at 50K.
SODA_PAGE_SIZE = 50_000

# Date threshold for 5-year window: only pull 2022-01-01 and later.
YEAR_FILTER_THRESHOLD = "2022-01-01T00:00:00"

REQUEST_TIMEOUT_SECONDS = 120.0

# NY SODA datasets: contributions (4j2b-6a2j), expenditures (ajsb-8pni).
# Both use sched_date as the primary transaction date field.
_DATE_FIELD = "sched_date"


def build_ny_download_url(
    data_type: str,
    *,
    limit: int = SODA_PAGE_SIZE,
    offset: int = 0,
    year_from: str = YEAR_FILTER_THRESHOLD,
) -> str:
    """Build a SODA API URL with pagination and date filtering.

    Uses trans_number ordering for deterministic pagination. The $where
    clause filters to sched_date >= year_from to stay within the 5-year
    window.
    """
    base_url = _load_bulk_download_url_for_data_type(data_type)
    # SoQL query: filter by date, order by trans_number for stable pagination.
    where_clause = f"{_DATE_FIELD} >= '{year_from}'"
    return f"{base_url}?$where={where_clause}&$order=trans_number&$limit={limit}&$offset={offset}"


def download_ny_csv(
    data_type: str,
    dest_dir: Path,
    *,
    limit: int | None = None,
    year_from: str = YEAR_FILTER_THRESHOLD,
) -> Path:
    """Download all pages of NY SODA data into a single CSV file.

    Paginates through the API, appending rows to one output file.
    The header row is written once from the first page; subsequent pages
    skip their header line.

    Args:
        data_type: "contributions" or "expenditures"
        dest_dir: Directory to write the output CSV
        limit: Max total rows to download (None = all available)
        year_from: ISO date threshold for sched_date filter

    Returns:
        Path to the downloaded CSV file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    normalized = data_type.strip().lower()
    dest_path = dest_dir / f"ny_{normalized}.csv"

    # Write to a temp file, then atomic-rename on success.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".ny_{normalized}.",
        suffix=".part",
        dir=dest_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        total_rows = 0
        offset = 0
        is_first_page = True

        with tmp_path.open("wb") as out_file:
            while True:
                # Calculate page size — respect overall limit if set.
                page_size = SODA_PAGE_SIZE
                if limit is not None:
                    remaining = limit - total_rows
                    if remaining <= 0:
                        break
                    page_size = min(page_size, remaining)

                url = build_ny_download_url(
                    data_type,
                    limit=page_size,
                    offset=offset,
                    year_from=year_from,
                )
                LOGGER.info("Downloading NY %s page offset=%d limit=%d", normalized, offset, page_size)

                with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                    response = client.get(url, follow_redirects=True)
                    response.raise_for_status()

                content = response.content
                if not content.strip():
                    # Empty response = no more data.
                    break

                lines = content.split(b"\n")
                # Remove trailing empty line if present.
                if lines and not lines[-1].strip():
                    lines = lines[:-1]

                if is_first_page:
                    # Write header + all data lines from first page.
                    for line in lines:
                        out_file.write(line + b"\n")
                    # First line is header, rest are data.
                    page_row_count = len(lines) - 1
                    is_first_page = False
                else:
                    # Skip header line on subsequent pages.
                    for line in lines[1:]:
                        out_file.write(line + b"\n")
                    page_row_count = len(lines) - 1

                total_rows += page_row_count
                offset += page_row_count
                LOGGER.info("NY %s: downloaded %d rows so far", normalized, total_rows)

                # If we got fewer rows than requested, we've reached the end.
                if page_row_count < page_size:
                    break

        tmp_path.replace(dest_path)
        LOGGER.info("NY %s download complete: %d total rows -> %s", normalized, total_rows, dest_path)
        return dest_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
