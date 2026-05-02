
from __future__ import annotations

from datetime import datetime
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from . import _load_bulk_download_url_for_data_type, _normalize_data_type

LOGGER = logging.getLogger(__name__)

SODA_PAGE_SIZE = 50_000

YEAR_FILTER_THRESHOLD = "2022-01-01T00:00:00"

REQUEST_TIMEOUT_SECONDS = 120.0

_DATE_FIELD = "sched_date"

_IE_FILING_CAT_DESC = "IE 24 Hour/Weekly Notices"


def _validate_supported_data_type(data_type: str) -> str:
    normalized = _normalize_data_type(data_type)
    _load_bulk_download_url_for_data_type(normalized)
    return normalized


def _validate_year_from(year_from: str) -> str:
    try:
        return datetime.fromisoformat(year_from).isoformat()
    except ValueError as error:
        raise ValueError("year_from must be an ISO-8601 date or datetime") from error


def _build_page_context(
    *,
    lane: str,
    offset: int,
    limit: int,
) -> dict[str, int | str]:
    page_number = (offset // SODA_PAGE_SIZE) + 1
    return {
        "lane": lane,
        "offset": offset,
        "limit": limit,
        "page": page_number,
    }


def _log_ny_page_info(
    message: str,
    *,
    page_context: dict[str, int | str],
    progress_outcome: str,
    **context: int | str,
) -> None:
    structured_context = page_context | {"progress_outcome": progress_outcome} | context
    LOGGER.info(message, structured_context, extra=structured_context)


def _log_ny_page_exception(
    message: str,
    *,
    page_context: dict[str, int | str],
    progress_outcome: str,
    **context: int | str,
) -> None:
    structured_context = page_context | {"progress_outcome": progress_outcome} | context
    LOGGER.exception(message, structured_context, extra=structured_context)


def build_ny_download_url(
    data_type: str,
    *,
    limit: int = SODA_PAGE_SIZE,
    offset: int = 0,
    year_from: str = YEAR_FILTER_THRESHOLD,
) -> str:
    normalized = _validate_supported_data_type(data_type)
    validated_year_from = _validate_year_from(year_from)
    base_url = _load_bulk_download_url_for_data_type(normalized)
    where_clause = f"{_DATE_FIELD} >= '{validated_year_from}'"
    if normalized == "independent_expenditures":
        where_clause += f" AND filing_cat_desc='{_IE_FILING_CAT_DESC}'"
    query_string = "&".join(
        (
            f"$where={quote_plus(where_clause)}",
            f"$order={quote_plus('trans_number')}",
            f"$limit={limit}",
            f"$offset={offset}",
        )
    )
    return f"{base_url}?{query_string}"


def download_ny_csv(
    data_type: str,
    dest_dir: Path,
    *,
    limit: int | None = None,
    year_from: str = YEAR_FILTER_THRESHOLD,
) -> Path:
    """Download all pages of NY SODA data into a single CSV file.

    Paginates through the API, appending rows to one output file.
    The header row is written once from the first page; subsequent pages
    skip their header line.

    Args:
        data_type: "contributions" or "expenditures"
        dest_dir: Directory to write the output CSV
        limit: Max total rows to download (None = all available)
        year_from: ISO date threshold for sched_date filter

    Returns:
        Path to the downloaded CSV file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    normalized = _validate_supported_data_type(data_type)
    validated_year_from = _validate_year_from(year_from)
    dest_path = dest_dir / f"ny_{normalized}.csv"

    # Write to a temp file, then atomic-rename on success.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".ny_{normalized}.",
        suffix=".part",
        dir=dest_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    page_context: dict[str, int | str] = _build_page_context(
        lane=normalized,
        offset=0,
        limit=SODA_PAGE_SIZE,
    )
    total_rows = 0

    try:
        offset = 0
        is_first_page = True

        with tmp_path.open("wb") as out_file:
            while True:
                # Calculate page size — respect overall limit if set.
                page_size = SODA_PAGE_SIZE
                if limit is not None:
                    remaining = limit - total_rows
                    if remaining <= 0:
                        break
                    page_size = min(page_size, remaining)

                url = build_ny_download_url(
                    normalized,
                    limit=page_size,
                    offset=offset,
                    year_from=validated_year_from,
                )
                page_context = _build_page_context(
                    lane=normalized,
                    offset=offset,
                    limit=page_size,
                )
                _log_ny_page_info(
                    "NY page request attempt lane=%(lane)s page=%(page)d offset=%(offset)d limit=%(limit)d",
                    page_context=page_context,
                    progress_outcome="request_attempt",
                )

                with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                    response = client.get(url, follow_redirects=True)
                    response.raise_for_status()

                content = response.content
                if not content.strip():
                    # Empty response = no more data.
                    _log_ny_page_info(
                        "NY page terminal empty lane=%(lane)s page=%(page)d offset=%(offset)d limit=%(limit)d total_rows=%(total_rows)d",
                        page_context=page_context,
                        progress_outcome="terminal_empty",
                        total_rows=total_rows,
                    )
                    break

                lines = content.split(b"\n")
                # Remove trailing empty line if present.
                if lines and not lines[-1].strip():
                    lines = lines[:-1]

                if is_first_page:
                    # Write header + all data lines from first page.
                    for line in lines:
                        out_file.write(line + b"\n")
                    # First line is header, rest are data.
                    page_row_count = len(lines) - 1
                    is_first_page = False
                else:
                    # Skip header line on subsequent pages.
                    for line in lines[1:]:
                        out_file.write(line + b"\n")
                    page_row_count = len(lines) - 1

                total_rows += page_row_count
                _log_ny_page_info(
                    "NY page complete lane=%(lane)s page=%(page)d offset=%(offset)d limit=%(limit)d page_rows=%(page_rows)d total_rows=%(total_rows)d",
                    page_context=page_context,
                    progress_outcome="page_complete",
                    page_rows=page_row_count,
                    total_rows=total_rows,
                )
                offset += page_row_count

                # If we got fewer rows than requested, we've reached the end.
                if page_row_count < page_size:
                    break

        tmp_path.replace(dest_path)
        LOGGER.info(
            "NY download complete lane=%(lane)s total_rows=%(total_rows)d destination=%(destination)s",
            {
                "lane": normalized,
                "total_rows": total_rows,
                "destination": str(dest_path),
            },
            extra={
                "lane": normalized,
                "total_rows": total_rows,
                "destination": str(dest_path),
                "progress_outcome": "download_complete",
            },
        )
        return dest_path

    except Exception:
        _log_ny_page_exception(
            "NY terminal failure lane=%(lane)s page=%(page)d offset=%(offset)d limit=%(limit)d total_rows=%(total_rows)d",
            page_context=page_context,
            progress_outcome="terminal_failure",
            total_rows=total_rows,
        )
        tmp_path.unlink(missing_ok=True)
        raise
