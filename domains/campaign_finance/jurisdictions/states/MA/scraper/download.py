"""Download MA campaign finance data from OCPF Azure Blob Storage.

Downloads per-year ZIP files, extracts report-items.txt (tab-delimited
transaction data). Each ZIP contains reports.txt, report-items.txt, and
readme.txt. We only need report-items.txt for the pipeline.

The 5-year window (2022-2026) means downloading 5 ZIP files. Each is
under 25MB compressed.
"""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from pathlib import Path

import httpx

from . import _load_bulk_download_url_template

LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120.0

# 5-year window: 2022 through current year.
_DEFAULT_YEAR_START = 2022
_DEFAULT_YEAR_END = 2026

# The file inside each ZIP that contains all transaction line items.
_REPORT_ITEMS_FILENAME = "report-items.txt"


def build_ma_download_url(year: int) -> str:
    """Build the download URL for a specific year's ZIP file."""
    template = _load_bulk_download_url_template()
    return template.replace("{year}", str(year))


def _download_zip(url: str, dest_path: Path) -> None:
    """Download a single ZIP file to dest_path with atomic rename."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{dest_path.name}.",
        suffix=".part",
        dir=dest_path.parent,
    )
    os.close(fd)
    tmp_path = Path(tmp_str)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            with client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()
                with tmp_path.open("wb") as f:
                    for chunk in response.iter_bytes():
                        if chunk:
                            f.write(chunk)
        tmp_path.replace(dest_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _extract_report_items(zip_path: Path, dest_dir: Path, year: int) -> Path:
    """Extract report-items.txt from a ZIP and rename to ma_{year}_report_items.txt."""
    output_path = dest_dir / f"ma_{year}_report_items.txt"
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find report-items.txt (case-insensitive search).
        report_items_name = None
        for name in zf.namelist():
            if name.lower() == _REPORT_ITEMS_FILENAME:
                report_items_name = name
                break
        if report_items_name is None:
            raise FileNotFoundError(f"No {_REPORT_ITEMS_FILENAME} found in {zip_path}")

        with zf.open(report_items_name) as src, output_path.open("wb") as dst:
            dst.write(src.read())

    return output_path


def download_ma_report_items(
    dest_dir: Path,
    *,
    year_start: int = _DEFAULT_YEAR_START,
    year_end: int = _DEFAULT_YEAR_END,
) -> list[Path]:
    """Download and extract report-items.txt for each year in the range.

    Returns list of extracted file paths, one per year.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted_paths: list[Path] = []

    for year in range(year_start, year_end + 1):
        url = build_ma_download_url(year)
        zip_path = dest_dir / f"ma_{year}_reports.zip"

        LOGGER.info("Downloading MA OCPF %d from %s", year, url)
        _download_zip(url, zip_path)

        LOGGER.info("Extracting report-items.txt from %s", zip_path.name)
        items_path = _extract_report_items(zip_path, dest_dir, year)
        extracted_paths.append(items_path)

        # Remove the ZIP after extraction to save disk space.
        zip_path.unlink(missing_ok=True)

    LOGGER.info("MA OCPF download complete: %d year files", len(extracted_paths))
    return extracted_paths
