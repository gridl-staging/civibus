"""Virginia campaign finance CSV downloader.

Downloads monthly CSV files from the VA SBE bulk export portal at
https://apps.elections.virginia.gov/SBE_CSV/CF/{year_month}/

The portal is organized by YYYY_MM directories containing:
  - ScheduleA.csv (contributions)
  - ScheduleD.csv (expenditures)
  - Report.csv (filing metadata)

No bot protection -- just needs a User-Agent header. Daily updates.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx

from . import _load_bulk_download_url_for_data_type

# VA files can be large (multi-year months), so allow generous timeout
REQUEST_TIMEOUT_SECONDS = 60.0

# Polite user-agent identifying our scraper
_USER_AGENT = "Mozilla/5.0 (compatible; Civibus/1.0)"

# Map data type names to the CSV filename used in the VA portal
_DATA_TYPE_TO_FILENAME = {
    "contributions": "ScheduleA",
    "expenditures": "ScheduleD",
    "reports": "Report",
}


def build_va_download_url(data_type: str, year_month: str) -> str:
    """Construct the full download URL for a VA CSV by data type and month.

    The URL template comes from config.yaml and contains a {year_month}
    placeholder that gets filled in here.

    Args:
        data_type: One of 'contributions', 'expenditures', 'reports'
        year_month: Month identifier like '2026_03'

    Returns:
        Full download URL like
        'https://apps.elections.virginia.gov/SBE_CSV/CF/2026_03/ScheduleA.csv'
    """
    url_template = _load_bulk_download_url_for_data_type(data_type)
    return url_template.replace("{year_month}", year_month)


def _stream_download_to_path(url: str, destination_path: Path) -> None:
    """Stream-download a URL to a file with atomic write.

    Uses a temporary .part file in the same directory, then atomically
    renames on success. Cleans up the temp file on failure.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory so rename is atomic (same filesystem)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
        ) as http_client:
            with http_client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary_download_path.open("wb") as destination_file:
                    for chunk in response.iter_bytes():
                        if chunk:
                            destination_file.write(chunk)
        # Atomic rename: only visible after full download succeeds
        temporary_download_path.replace(destination_path)
    except Exception:
        # Clean up partial file on any failure
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_va_csv(data_type: str, dest_dir: Path, year_month: str) -> Path:
    """Download a VA CSV file for the given data type and month.

    Args:
        data_type: One of 'contributions', 'expenditures', 'reports'
        dest_dir: Directory to save the downloaded file
        year_month: Month identifier like '2026_03'

    Returns:
        Path to the downloaded CSV file
    """
    download_url = build_va_download_url(data_type, year_month)
    normalized_data_type = data_type.strip().lower()
    # Include year_month in filename to support multi-month downloads
    destination_path = dest_dir / f"va_{normalized_data_type}_{year_month}.csv"

    _stream_download_to_path(download_url, destination_path)
    return destination_path
