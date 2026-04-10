
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import tempfile

import httpx

from . import _load_bulk_download_url_for_data_type

SODA_PAGE_SIZE = 50_000
REQUEST_TIMEOUT_SECONDS = 120.0
SODA_ORDER_BY = "filing_id_number,transaction_id"


def build_sf_download_url(data_type: str, *, limit: int = SODA_PAGE_SIZE, offset: int = 0) -> str:
    base_url = _load_bulk_download_url_for_data_type(data_type)
    return f"{base_url}?$order={SODA_ORDER_BY}&$limit={limit}&$offset={offset}"


def _stream_response_content(response: httpx.Response) -> bytes:
    return b"".join(chunk for chunk in response.iter_bytes() if chunk)


def _load_csv_rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8"))))


def _stream_sf_pages_to_path(data_type: str, destination_path: Path, *, limit: int | None = None) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        total_rows = 0
        offset = 0
        expected_header: list[str] | None = None

        with temporary_download_path.open("w", encoding="utf-8", newline="") as destination_file:
            csv_writer = csv.writer(destination_file, lineterminator="\n")
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http_client:
                while True:
                    if limit is None:
                        page_size = SODA_PAGE_SIZE
                    else:
                        remaining = limit - total_rows
                        if remaining <= 0:
                            break
                        page_size = min(SODA_PAGE_SIZE, remaining)

                    download_url = build_sf_download_url(data_type, limit=page_size, offset=offset)
                    with http_client.stream("GET", download_url, follow_redirects=True) as response:
                        response.raise_for_status()
                        content = _stream_response_content(response)

                    if not content.strip():
                        break

                    csv_rows = _load_csv_rows(content)
                    if not csv_rows:
                        break

                    page_header = csv_rows[0]
                    page_data_rows = csv_rows[1:]

                    if expected_header is None:
                        expected_header = page_header
                        csv_writer.writerow(page_header)
                    elif page_header != expected_header:
                        raise ValueError("SF download page header changed across paginated response")

                    csv_writer.writerows(page_data_rows)
                    page_row_count = len(page_data_rows)

                    total_rows += page_row_count
                    offset += page_row_count

                    if page_row_count < page_size:
                        break

        temporary_download_path.replace(destination_path)
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def download_sf_csv(data_type: str, dest_dir: Path, *, limit: int | None = None) -> Path:
    destination_path = dest_dir / f"sf_{data_type.strip().lower()}.csv"
    _stream_sf_pages_to_path(data_type, destination_path, limit=limit)
    return destination_path
