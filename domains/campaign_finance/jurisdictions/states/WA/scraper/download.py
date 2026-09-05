"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/jurisdictions/states/WA/scraper/download.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 30.0
WA_PAGE_ROWS = 50_000


@dataclass(frozen=True, slots=True)
class WASourceSnapshot:
    """The aggregate facts that bound one immutable Socrata read window."""

    row_count: int
    max_updated_at: datetime
    version_sum: int

    @classmethod
    def from_payload(cls, payload: object) -> WASourceSnapshot:
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ValueError("WA source snapshot must contain exactly one aggregate row")
        row = payload[0]
        if isinstance(row.get("row_count"), bool):
            raise ValueError("WA source snapshot row_count is missing or invalid")
        try:
            row_count = int(row["row_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("WA source snapshot row_count is missing or invalid") from error
        if row_count < 0:
            raise ValueError("WA source snapshot row_count must be non-negative")
        try:
            max_updated_at = datetime.fromtimestamp(float(row["max_updated_at"]), tz=timezone.utc)
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise ValueError("WA source snapshot max_updated_at is missing or invalid") from error
        if isinstance(row.get("version_sum"), bool):
            raise ValueError("WA source snapshot version_sum is missing or invalid")
        try:
            version_sum = int(row["version_sum"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("WA source snapshot version_sum is missing or invalid") from error
        if version_sum < 0:
            raise ValueError("WA source snapshot version_sum must be non-negative")
        return cls(row_count=row_count, max_updated_at=max_updated_at, version_sum=version_sum)


def _json_resource_url(data_type: str) -> str:
    csv_url = _load_bulk_download_url_for_data_type(data_type)
    if not csv_url.endswith(".csv"):
        raise ValueError("WA Socrata resource URL must end in .csv")
    return f"{csv_url[:-4]}.json"


def _socrata_timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _updated_window(updated_after: datetime | None, updated_through: datetime) -> str:
    predicates = [f":updated_at <= '{_socrata_timestamp(updated_through)}'"]
    if updated_after is not None:
        predicates.insert(0, f":updated_at >= '{_socrata_timestamp(updated_after)}'")
    return " AND ".join(predicates)


def build_wa_snapshot_url(data_type: str) -> str:
    return (
        f"{_json_resource_url(data_type)}?"
        "$select=count(*) as row_count,max(:updated_at) as max_updated_at,sum(:version) as version_sum"
    )


def build_wa_change_count_url(
    data_type: str,
    *,
    updated_after: datetime | None,
    updated_through: datetime,
) -> str:
    return (
        f"{_json_resource_url(data_type)}?$select=count(*) as row_count"
        f"&$where={_updated_window(updated_after, updated_through)}"
    )


def build_wa_download_url(
    data_type: str,
    *,
    limit: int | None = None,
    offset: int = 0,
    updated_after: datetime | None = None,
    updated_through: datetime | None = None,
) -> str:
    url = _load_bulk_download_url_for_data_type(data_type)
    if limit is None:
        if offset or updated_after is not None or updated_through is not None:
            raise ValueError("bounded WA download options require an explicit limit")
        return url
    if limit <= 0 or limit > WA_PAGE_ROWS:
        raise ValueError(f"WA Socrata page limit must be between 1 and {WA_PAGE_ROWS}")
    if offset < 0:
        raise ValueError("WA Socrata page offset must be non-negative")
    query = [f"$limit={limit}"]
    if offset:
        query.append(f"$offset={offset}")
    if updated_through is not None:
        query.extend(("$order=:updated_at,:id", f"$where={_updated_window(updated_after, updated_through)}"))
    elif updated_after is not None:
        raise ValueError("updated_after requires updated_through")
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{'&'.join(query)}"


def _get_json(url: str) -> Any:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
        response = http_client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.json()


def fetch_wa_source_snapshot(data_type: str) -> WASourceSnapshot:
    return WASourceSnapshot.from_payload(_get_json(build_wa_snapshot_url(data_type)))


def fetch_wa_source_change_count(
    data_type: str,
    *,
    updated_after: datetime | None,
    updated_through: datetime,
) -> int:
    payload = _get_json(
        build_wa_change_count_url(
            data_type,
            updated_after=updated_after,
            updated_through=updated_through,
        )
    )
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError("WA source change count must contain exactly one aggregate row")
    if isinstance(payload[0].get("row_count"), bool):
        raise ValueError("WA source change row_count is missing or invalid")
    try:
        row_count = int(payload[0]["row_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("WA source change row_count is missing or invalid") from error
    if row_count < 0:
        raise ValueError("WA source change row_count must be non-negative")
    return row_count


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


def download_wa_csv(data_type: str, dest_dir: Path, *, limit: int | None = None) -> Path:
    download_url = build_wa_download_url(data_type, limit=limit)
    normalized_data_type = data_type.strip().lower()
    destination_path = dest_dir / f"wa_{normalized_data_type}.csv"

    _stream_download_to_path(download_url, destination_path)
    return destination_path


def download_wa_csv_page(
    data_type: str,
    dest_dir: Path,
    *,
    offset: int,
    limit: int,
    updated_after: datetime | None,
    updated_through: datetime,
) -> Path:
    destination_path = dest_dir / f"wa_{data_type}_offset_{offset}.csv"
    _stream_download_to_path(
        build_wa_download_url(
            data_type,
            limit=limit,
            offset=offset,
            updated_after=updated_after,
            updated_through=updated_through,
        ),
        destination_path,
    )
    return destination_path
