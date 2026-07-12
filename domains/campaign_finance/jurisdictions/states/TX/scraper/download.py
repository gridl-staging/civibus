"""
Stub summary for mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/TX/scraper/download.py.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_DOWNLOAD_BYTES = 1_073_741_824
_TX_ARCHIVE_FILENAME = "TEC_CF_CSV.zip"


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
                    downloaded_bytes = 0
                    for chunk in response.iter_bytes():
                        if chunk:
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"TX download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes"
                                )
                            destination_file.write(chunk)
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_tx_archive(data_type: str, dest_dir: Path) -> Path:
    download_url = _load_bulk_download_url_for_data_type(data_type)
    destination_path = dest_dir / _TX_ARCHIVE_FILENAME
    _stream_download_to_path(download_url, destination_path)
    return destination_path
