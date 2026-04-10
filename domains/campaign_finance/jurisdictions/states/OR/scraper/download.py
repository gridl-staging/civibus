"""Download helpers for OR campaign finance data.

ORESTAR uses a two-step session-based acquisition:
  Step 1: GET cneSearch.do with search params to seed the server-side session
  Step 2: GET XcelCNESearch with the session cookie to export XLS (tab-separated text)
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from . import _load_api_base_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 60.0
MAX_DOWNLOAD_BYTES = 1_073_741_824

# ORESTAR cneSearch.do parameter mapping for transaction type filtering.
# "C" = contributions, "E" = expenditures per ORESTAR v4.4.1.
_TRANSACTION_TYPE_PARAM: dict[str, str] = {
    "contributions": "C",
    "expenditures": "E",
}

# ORESTAR uses "Original" as the default transaction status for non-amended filings
_DEFAULT_TRAN_STATUS = "Original"


def _build_session_seed_url(api_base_url: str, *, data_type: str) -> str:
    """Build the cneSearch.do URL that seeds the server-side session.

    This GET request must happen BEFORE the XcelCNESearch export will work.
    The server responds with an HTML search results page and sets a JSESSIONID
    cookie that the subsequent export request must carry.
    """
    tran_type_code = _TRANSACTION_TYPE_PARAM.get(data_type)
    if tran_type_code is None:
        raise ValueError(f"Unsupported OR data type for download: {data_type}")

    # Minimal search params that produce a valid session. We search broadly
    # (no filer ID filter) so the export covers all filers.
    params = {
        "cneSearchButtonName": "search",
        "cneSearchTranType": tran_type_code,
        "cneSearchTranStatus": _DEFAULT_TRAN_STATUS,
    }
    return f"{api_base_url}/cneSearch.do?{urlencode(params)}"


def _build_export_url(api_base_url: str) -> str:
    """Build the XcelCNESearch URL that streams the XLS export."""
    return f"{api_base_url}/XcelCNESearch"


def _stream_download_to_path(
    http_client: httpx.Client,
    url: str,
    destination_path: Path,
) -> None:
    """Stream an HTTP GET response to a file path with atomic rename."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        with http_client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with temporary_download_path.open("wb") as dest_file:
                downloaded_bytes = 0
                for chunk in response.iter_bytes():
                    if chunk:
                        downloaded_bytes += len(chunk)
                        if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                            raise ValueError(
                                f"OR download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes"
                            )
                        dest_file.write(chunk)
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_or_transactions(data_type: str, dest_dir: Path) -> Path:
    """Download OR campaign finance transactions via two-step ORESTAR session.

    Args:
        data_type: "contributions" or "expenditures"
        dest_dir: Directory to save the downloaded XLS file

    Returns:
        Path to the downloaded XLS file
    """
    normalized = data_type.strip().lower()
    api_base_url = _load_api_base_url_for_data_type(normalized)

    # Timestamp for unique filenames across runs
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    destination_path = dest_dir / f"OR_{normalized}_{timestamp}.xls"

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
        # Step 1: Seed the server-side session via cneSearch.do GET.
        # The JSESSIONID cookie is automatically captured by the httpx client.
        session_seed_url = _build_session_seed_url(api_base_url, data_type=normalized)
        session_response = http_client.get(session_seed_url, follow_redirects=True)
        session_response.raise_for_status()

        # Step 2: Stream the XLS export using the seeded session cookie.
        export_url = _build_export_url(api_base_url)
        _stream_download_to_path(http_client, export_url, destination_path)

    return destination_path
