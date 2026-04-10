"""Download helpers for KY campaign finance data.

Kentucky exposes separate public CSV export endpoints for transaction search
results:

- contributions: ``/ExportContributors``
- expenditures: ``/Export``

Both export contracts are direct GET requests and do not require a browser
session once the correct query-string parameters are supplied.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx

from . import _load_api_base_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 60.0
MAX_DOWNLOAD_BYTES = 1_073_741_824  # 1 GB safety cap

_EXPORT_ROUTE_BY_DATA_TYPE = {
    "contributions": "ExportContributors",
    "expenditures": "Export",
}

_LAST_NAME_PARAM_BY_DATA_TYPE = {
    "contributions": "CandidateLastName",
    "expenditures": "FromCandidateLastName",
}


def _normalize_election_date_param(raw_value: str) -> str:
    """Normalize KREF election dates to the live export-link shape."""
    stripped = raw_value.strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(stripped, fmt)
            return parsed.strftime("%m/%d/%Y %H:%M:%S")
        except ValueError:
            continue
    return stripped


def _build_export_url(
    data_type: str,
    *,
    election_date: str | None = None,
    election_type: str | None = None,
    last_name: str | None = None,
) -> str:
    """Build the KREF export URL for the requested transaction search surface."""
    base_url = _load_api_base_url_for_data_type(data_type)
    route = _EXPORT_ROUTE_BY_DATA_TYPE.get(data_type)
    if route is None:
        raise ValueError(f"Unsupported KY data type for download: {data_type}")

    params: dict[str, str] = {}

    if election_date is not None:
        params["ElectionDate"] = _normalize_election_date_param(election_date)
    if election_type is not None:
        params["ElectionType"] = election_type
    if last_name is not None:
        params[_LAST_NAME_PARAM_BY_DATA_TYPE[data_type]] = last_name

    if data_type == "contributions":
        # Live contribution export links always carry this discriminator.
        params["ContributionSearchType"] = "All"

    return f"{base_url}/{route}?{urlencode(params)}"


def _stream_download_to_path(url: str, destination_path: Path) -> None:
    """Stream an HTTP response to disk using atomic temp-file rename."""
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
                                    f"KY download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes"
                                )
                            destination_file.write(chunk)
        # Atomic rename on success
        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_ky_csv(
    data_type: str,
    *,
    dest_dir: Path,
    election_date: str | None = None,
    election_type: str | None = None,
    last_name: str | None = None,
) -> Path:
    """Download a KY campaign finance CSV from the KREF export endpoint.

    Args:
        data_type: "contributions" or "expenditures"
        dest_dir: Directory to save the downloaded CSV
        election_date: Optional election date filter (e.g. "5/19/2026")
        election_type: Optional election type filter (e.g. "Primary")
        last_name: Optional last name filter

    Returns:
        Path to the downloaded CSV file.
    """
    normalized_data_type = data_type.strip().lower()
    download_url = _build_export_url(
        normalized_data_type,
        election_date=election_date,
        election_type=election_type,
        last_name=last_name,
    )
    destination_path = dest_dir / f"KY_{normalized_data_type}.csv"
    _stream_download_to_path(download_url, destination_path)
    return destination_path
