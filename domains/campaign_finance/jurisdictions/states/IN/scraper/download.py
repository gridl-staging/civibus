
from __future__ import annotations

import os
from pathlib import Path
from posixpath import normpath
import tempfile
from urllib.parse import unquote, urlparse

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_DOWNLOAD_BYTES = 1_073_741_824
_ALLOWED_DOWNLOAD_SCHEMES = {"https"}
_ALLOWED_DOWNLOAD_HOSTS = {"campaignfinance.in.gov"}
_ALLOWED_DOWNLOAD_PATH_PREFIX = "/PublicSite/Docs/BulkDataDownloads/"
_BROWSER_LIKE_HEADERS = {
    # Indiana's bulk-download endpoint currently serves the ZIP to curl and browser
    # traffic but can return a Cloudflare interstitial to bare httpx defaults.
    # Keeping these defaults here makes the downloader behavior explicit and testable.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _validate_in_download_url(url: str, *, context: str) -> str:
    parsed_url = urlparse(url)
    normalized_scheme = parsed_url.scheme.lower()
    normalized_host = (parsed_url.hostname or "").lower()
    normalized_path = "/" + normpath(unquote(parsed_url.path or "/")).lstrip("/")

    if normalized_scheme not in _ALLOWED_DOWNLOAD_SCHEMES:
        raise ValueError(f"{context} must use HTTPS: {url}")
    if normalized_host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(f"{context} must stay on an approved Indiana campaign-finance host: {url}")
    if not normalized_path.startswith(_ALLOWED_DOWNLOAD_PATH_PREFIX):
        raise ValueError(f"{context} must stay within the Indiana bulk-download path: {url}")
    if not normalized_path.lower().endswith(".csv.zip"):
        raise ValueError(f"{context} must point to an Indiana yearly .csv.zip file: {url}")

    return url


def _stream_download_to_path(url: str, destination_path: Path) -> None:
    validated_url = _validate_in_download_url(url, context="IN file URL")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, headers=_BROWSER_LIKE_HEADERS) as http_client:
            with http_client.stream("GET", validated_url, follow_redirects=True) as response:
                response.raise_for_status()
                redirect_history = tuple(getattr(response, "history", ()))
                for redirect_response in (*redirect_history, response):
                    _validate_in_download_url(str(redirect_response.url), context="IN file URL")
                with temporary_download_path.open("wb") as destination_file:
                    downloaded_bytes = 0
                    for chunk in response.iter_bytes():
                        if chunk:
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"IN download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes"
                                )
                            destination_file.write(chunk)

        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_in_data(year: int, data_type: str, dest_dir: Path) -> Path:
    download_url_template = _load_bulk_download_url_for_data_type(data_type)
    download_url = _validate_in_download_url(download_url_template.replace("{YEAR}", str(year)), context="IN file URL")
    destination_path = dest_dir / Path(urlparse(download_url).path).name
    _stream_download_to_path(download_url, destination_path)
    return destination_path
