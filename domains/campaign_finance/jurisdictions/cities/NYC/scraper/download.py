"""NYC CFB bulk CSV downloader — direct HTTP GET (no SODA pagination)."""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 120.0


def build_nyc_download_url(data_type: str) -> str:
    """Return the direct download URL for the given NYC data type."""
    return _load_bulk_download_url_for_data_type(data_type)


def _extract_csv_from_zip(zip_path: Path, dest_dir: Path, data_type: str) -> Path:
    """Extract the first matching CSV from a ZIP archive."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("NYC ZIP archive contains no CSV files")
        # Prefer a file matching the data type keyword
        target = next(
            (n for n in csv_names if data_type.lower() in n.lower()),
            csv_names[0],
        )
        zf.extract(target, dest_dir)
        return dest_dir / target


def download_nyc_csv(
    data_type: str,
    dest_dir: Path,
    *,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> Path:
    """Download a NYC CFB CSV file via direct HTTP GET with atomic temp-file write."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    download_url = build_nyc_download_url(data_type)

    file_descriptor, temp_path_str = tempfile.mkstemp(
        prefix=".nyc_download_",
        suffix=".part",
        dir=dest_dir,
    )
    os.close(file_descriptor)
    temp_path = Path(temp_path_str)

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("GET", download_url, follow_redirects=True) as response:
                response.raise_for_status()
                with temp_path.open("wb") as f:
                    for chunk in response.iter_bytes():
                        if chunk:
                            f.write(chunk)

        # Check if response is a ZIP file
        if zipfile.is_zipfile(temp_path):
            csv_path = _extract_csv_from_zip(temp_path, dest_dir, data_type)
            temp_path.unlink(missing_ok=True)
            return csv_path

        # Plain CSV — rename to final destination
        destination = dest_dir / f"nyc_{data_type.strip().lower()}.csv"
        temp_path.replace(destination)
        return destination

    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
