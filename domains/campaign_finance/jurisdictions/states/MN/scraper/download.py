"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/MN/scraper/download.py.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 30.0


def build_mn_download_url(data_type: str) -> str:
    return _load_bulk_download_url_for_data_type(data_type)


def _stream_download_to_path(url: str, destination_path: Path) -> None:
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
            with http_client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()
                with temporary_download_path.open("wb") as destination_file:
                    for chunk in response.iter_bytes():
                        if chunk:
                            destination_file.write(chunk)
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_mn_csv(data_type: str, dest_dir: Path) -> Path:
    download_url = build_mn_download_url(data_type)
    normalized_data_type = data_type.strip().lower()
    destination_path = dest_dir / f"mn_{normalized_data_type}.csv"

    _stream_download_to_path(download_url, destination_path)
    return destination_path
