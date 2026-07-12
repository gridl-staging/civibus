"""
Stub summary for mar26_am_3_new_state_pipeline_builds/civibus_dev/domains/campaign_finance/jurisdictions/states/NJ/scraper/download.py.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 60.0
_ALLOWED_BLOB_HOST_SUFFIXES = (".blob.core.windows.net",)
_ALLOWED_DIRECT_DOWNLOAD_HOSTS = {"www.njelecefilesearch.com"}


def build_nj_download_url(data_type: str) -> str:
    return _load_bulk_download_url_for_data_type(data_type)


def _validate_download_host(url: str) -> str:
    parsed_url = urlparse(url)
    hostname = parsed_url.hostname

    if parsed_url.scheme != "https" or hostname is None:
        raise RuntimeError(f"ELEC API returned unexpected blob URL format: {url!r}")

    if hostname in _ALLOWED_DIRECT_DOWNLOAD_HOSTS:
        return url

    if any(hostname.endswith(host_suffix) for host_suffix in _ALLOWED_BLOB_HOST_SUFFIXES):
        return url

    raise RuntimeError(f"ELEC API returned blob URL on unexpected host: {hostname!r}")


def _request_blob_url(http_client: httpx.Client, api_url: str) -> str:
    """POST to the ELEC API to obtain a temporary Azure Blob Storage URL."""
    response = http_client.post(api_url, json={})
    response.raise_for_status()
    blob_url = response.json()
    if not isinstance(blob_url, str):
        raise RuntimeError(f"ELEC API returned unexpected blob URL format: {blob_url!r}")
    return _validate_download_host(blob_url)


def _stream_download_to_path(http_client: httpx.Client, url: str, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        with http_client.stream("GET", url, follow_redirects=False) as response:
            response.raise_for_status()
            with temporary_download_path.open("wb") as destination_file:
                for chunk in response.iter_bytes():
                    if chunk:
                        destination_file.write(chunk)
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_nj_csv(data_type: str, dest_dir: Path) -> Path:
    """Download NJ contribution CSV via the two-step ELEC API flow."""
    api_url = build_nj_download_url(data_type)
    normalized_data_type = data_type.strip().lower()
    destination_path = dest_dir / f"nj_{normalized_data_type}.csv"

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
        blob_url = _request_blob_url(http_client, api_url)
        _stream_download_to_path(http_client, blob_url, destination_path)

    return destination_path
