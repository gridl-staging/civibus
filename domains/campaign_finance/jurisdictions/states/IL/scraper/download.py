
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import os
import re
import tempfile
import warnings
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from . import _load_bulk_download_url_for_data_type

REQUEST_TIMEOUT_SECONDS = 120.0
_DOWNLOAD_TIMEOUT = httpx.Timeout(
    connect=REQUEST_TIMEOUT_SECONDS,
    # Illinois serves the bulk export over a long-lived chunked stream. We keep
    # connection setup bounded, but remove the per-read timeout so the transfer
    # can continue while the server trickles out the remaining file.
    read=None,
    write=REQUEST_TIMEOUT_SECONDS,
    pool=REQUEST_TIMEOUT_SECONDS,
)
_ALLOWED_DOWNLOAD_PAGE_HOSTS = frozenset({"elections.il.gov", "www.elections.il.gov"})
_ALLOWED_DOWNLOAD_LINK_PATH = "/NewDocDisplay.aspx"
SUPPORTED_SSL_ERROR_HINTS = ("certificate", "ssl", "tls", "cert verify failed")
INSECURE_TLS_RETRY_ENV_VAR = "CIVIBUS_ALLOW_INSECURE_TLS_RETRY"
REMOTE_PROTOCOL_RETRY_ATTEMPTS = 3
STREAM_RESUME_ATTEMPTS = 12
INCOMPLETE_CHUNKED_READ_HINT = "incomplete chunked read"
_CONTENT_RANGE_PATTERN = re.compile(r"^bytes (?P<start>\d+)-(?P<end>\d+)/(?:\d+|\*)$")
_DATA_FILE_BY_DATA_TYPE = {
    "contributions": "Receipts.txt",
    "expenditures": "Expenditures.txt",
}


@dataclass(frozen=True, slots=True)
class ILDownloadResult:
    path: Path
    bytes_written: int
    data_rows_written: int | None
    truncated: bool


def _normalize_data_type(data_type: str) -> str:
    return data_type.strip().lower()


def _validate_il_download_page_url(download_page_url: str, *, context: str = "IL download page URL") -> str:
    parsed_url = urlsplit(download_page_url)
    if parsed_url.scheme != "https":
        raise ValueError(f"{context} must use HTTPS")
    if parsed_url.hostname not in _ALLOWED_DOWNLOAD_PAGE_HOSTS:
        raise ValueError(f"{context} must use the official Illinois elections host")
    if parsed_url.path != "/CampaignDisclosure/DownloadCDDataFiles.aspx":
        raise ValueError(f"{context} must use the Illinois bulk-download page path")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ValueError(f"{context} must not embed credentials")
    return download_page_url


def _validate_il_download_link(download_url: str) -> str:
    parsed_url = urlsplit(download_url)
    if parsed_url.scheme != "https":
        raise ValueError("IL file URL must use HTTPS")
    if parsed_url.hostname not in _ALLOWED_DOWNLOAD_PAGE_HOSTS:
        raise ValueError("IL file URL must use the official Illinois elections host")
    if parsed_url.path != _ALLOWED_DOWNLOAD_LINK_PATH:
        raise ValueError("IL file URL must use the NewDocDisplay.aspx path")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ValueError("IL file URL must not embed credentials")
    return download_url


def _extract_hidden_value(page_html: str, field_name: str) -> str:
    match = re.search(rf'name="{re.escape(field_name)}"[^>]*value="([^"]*)"', page_html)
    return unescape(match.group(1)) if match else ""


def _build_postback_payload(page_html: str, *, file_name: str) -> dict[str, str]:
    return {
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$ddlDataFiles",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": _extract_hidden_value(page_html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _extract_hidden_value(page_html, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": _extract_hidden_value(page_html, "__EVENTVALIDATION"),
        "MenuTabContainer_ClientState": _extract_hidden_value(page_html, "MenuTabContainer_ClientState"),
        "ctl00$ContentPlaceHolder1$ddlDataFiles": file_name,
    }


def _extract_download_link(postback_html: str, *, page_url: str) -> str:
    match = re.search(r'id="ContentPlaceHolder1_hypDownloadFile"[^>]*href="([^"]+)"', postback_html)
    if match is None:
        raise RuntimeError("IL postback response did not include the download hyperlink")
    return _validate_il_download_link(urljoin(page_url, unescape(match.group(1))))


def _resolve_download_link(client: httpx.Client, *, file_name: str, page_url: str) -> str:
    download_page_url = _validate_il_download_page_url(page_url)
    initial_response = client.get(download_page_url)
    initial_response.raise_for_status()
    payload = _build_postback_payload(initial_response.text, file_name=file_name)
    postback_response = client.post(download_page_url, data=payload)
    postback_response.raise_for_status()
    return _extract_download_link(postback_response.text, page_url=str(postback_response.url))


def _split_complete_lines(buffer: bytes) -> tuple[list[bytes], bytes]:
    lines = buffer.splitlines(keepends=True)
    if lines and not lines[-1].endswith((b"\n", b"\r")):
        return lines[:-1], lines[-1]
    return lines, b""


def _validate_resume_response(response: httpx.Response, *, expected_start: int) -> bool:
    """Return whether to continue appending to the existing partial file."""
    if response.status_code == 206:
        content_range = response.headers.get("Content-Range", "").strip()
        content_range_match = _CONTENT_RANGE_PATTERN.match(content_range)
        if content_range_match is None:
            raise RuntimeError("IL resume response did not include a valid Content-Range header")
        if int(content_range_match.group("start")) != expected_start:
            raise RuntimeError("IL resume response returned an unexpected Content-Range start offset")
        return True
    if response.status_code == 200:
        return False
    raise RuntimeError(
        "IL resume request returned unexpected HTTP status; expected 206 Partial Content or 200 OK fallback"
    )


def _stream_download_to_path(
    client: httpx.Client,
    download_url: str,
    destination_path: Path,
    *,
    max_data_rows: int | None = None,
    tail_data_rows: int | None = None,
) -> ILDownloadResult:
    if max_data_rows is not None and tail_data_rows is not None:
        raise ValueError("Choose either max_data_rows or tail_data_rows, not both")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)
    bytes_written = 0
    data_rows_written = 0 if (max_data_rows is not None or tail_data_rows is not None) else None
    truncated = False

    try:
        validated_download_url = _validate_il_download_link(download_url)
        with temporary_download_path.open("wb") as destination_file:
            if max_data_rows is None and tail_data_rows is None:
                incomplete_chunk_retry_count = 0
                while True:
                    request_headers: dict[str, str] | None = None
                    expected_resume_start = bytes_written
                    if expected_resume_start > 0:
                        request_headers = {"Range": f"bytes={expected_resume_start}-"}

                    try:
                        with client.stream("GET", validated_download_url, headers=request_headers) as response:
                            response.raise_for_status()

                            if request_headers is not None:
                                should_append = _validate_resume_response(
                                    response,
                                    expected_start=expected_resume_start,
                                )
                                if not should_append:
                                    # Some upstreams ignore Range and restart at byte 0.
                                    destination_file.seek(0)
                                    destination_file.truncate(0)
                                    bytes_written = 0
                                    warnings.warn(
                                        "IL resume request returned 200 OK; restarting stream from byte 0.",
                                        UserWarning,
                                        stacklevel=2,
                                    )

                            for chunk in response.iter_bytes():
                                if chunk:
                                    destination_file.write(chunk)
                                    bytes_written += len(chunk)
                        break
                    except httpx.RemoteProtocolError as error:
                        if not _is_incomplete_chunked_read_error(error):
                            raise
                        incomplete_chunk_retry_count += 1
                        if incomplete_chunk_retry_count >= STREAM_RESUME_ATTEMPTS:
                            raise
                        warnings.warn(
                            "IL bulk stream closed early with incomplete chunked read; "
                            f"retrying stream with resume offset {bytes_written}.",
                            UserWarning,
                            stacklevel=2,
                        )
            elif max_data_rows is not None:
                with client.stream("GET", validated_download_url) as response:
                    response.raise_for_status()
                    pending_bytes = b""
                    saw_header = False

                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        pending_bytes += chunk
                        complete_lines, pending_bytes = _split_complete_lines(pending_bytes)

                        for line in complete_lines:
                            if not saw_header:
                                destination_file.write(line)
                                bytes_written += len(line)
                                saw_header = True
                                continue
                            if data_rows_written >= max_data_rows:
                                truncated = True
                                break
                            destination_file.write(line)
                            bytes_written += len(line)
                            data_rows_written += 1

                        if truncated:
                            break

                    if not truncated and pending_bytes:
                        if not saw_header:
                            destination_file.write(pending_bytes)
                            bytes_written += len(pending_bytes)
                        elif data_rows_written < max_data_rows:
                            destination_file.write(pending_bytes)
                            bytes_written += len(pending_bytes)
                            data_rows_written += 1
                        else:
                            truncated = True
            else:
                with client.stream("GET", validated_download_url) as response:
                    response.raise_for_status()
                    pending_bytes = b""
                    header_line: bytes | None = None
                    trailing_data_lines: deque[bytes] = deque(maxlen=tail_data_rows)
                    total_data_rows_seen = 0

                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        pending_bytes += chunk
                        complete_lines, pending_bytes = _split_complete_lines(pending_bytes)

                        for line in complete_lines:
                            if header_line is None:
                                header_line = line
                                continue
                            total_data_rows_seen += 1
                            trailing_data_lines.append(line)

                    if pending_bytes:
                        if header_line is None:
                            header_line = pending_bytes
                        else:
                            total_data_rows_seen += 1
                            trailing_data_lines.append(pending_bytes)

                    if header_line is not None:
                        destination_file.write(header_line)
                        bytes_written += len(header_line)

                    for line in trailing_data_lines:
                        destination_file.write(line)
                        bytes_written += len(line)

                    data_rows_written = len(trailing_data_lines)
                    truncated = total_data_rows_seen > tail_data_rows

        temporary_download_path.replace(destination_path)
        return ILDownloadResult(
            path=destination_path,
            bytes_written=bytes_written,
            data_rows_written=data_rows_written,
            truncated=truncated,
        )
    except Exception:
        temporary_download_path.unlink(missing_ok=True)
        raise


def _is_ssl_or_certificate_error(error: httpx.HTTPError) -> bool:
    if not isinstance(error, httpx.ConnectError):
        return False

    chained_error_messages = [
        str(error).lower(),
        str(error.__cause__).lower() if error.__cause__ else "",
        str(error.__context__).lower() if error.__context__ else "",
    ]
    combined_error_message = " ".join(chained_error_messages)

    return any(hint in combined_error_message for hint in SUPPORTED_SSL_ERROR_HINTS)


def _is_incomplete_chunked_read_error(error: httpx.HTTPError) -> bool:
    if not isinstance(error, httpx.RemoteProtocolError):
        return False

    chained_error_messages = [
        str(error).lower(),
        str(error.__cause__).lower() if error.__cause__ else "",
        str(error.__context__).lower() if error.__context__ else "",
    ]
    combined_error_message = " ".join(chained_error_messages)
    return INCOMPLETE_CHUNKED_READ_HINT in combined_error_message


def _break_glass_insecure_tls_retry_enabled() -> bool:
    return os.getenv(INSECURE_TLS_RETRY_ENV_VAR, "").strip() == "1"


def _download_il_raw_file_once(
    file_name: str,
    *,
    dest_dir: Path,
    page_url: str,
    verify_certificates: bool,
    max_data_rows: int | None = None,
    tail_data_rows: int | None = None,
) -> ILDownloadResult:
    download_page_url = page_url or _load_bulk_download_url_for_data_type("contributions")
    if file_name not in _DATA_FILE_BY_DATA_TYPE.values():
        raise ValueError("IL raw downloads must use an official IL raw file name")
    destination_path = dest_dir / file_name

    with httpx.Client(
        headers={"user-agent": "Mozilla/5.0"},
        follow_redirects=True,
        timeout=_DOWNLOAD_TIMEOUT,
        verify=verify_certificates,
    ) as http_client:
        download_url = _resolve_download_link(http_client, file_name=file_name, page_url=download_page_url)
        return _stream_download_to_path(
            http_client,
            download_url,
            destination_path,
            max_data_rows=max_data_rows,
            tail_data_rows=tail_data_rows,
        )


def download_il_raw_file_with_metadata(
    file_name: str,
    *,
    dest_dir: Path,
    page_url: str | None = None,
    allow_insecure_tls: bool = False,
    max_data_rows: int | None = None,
    tail_data_rows: int | None = None,
) -> ILDownloadResult:
    download_page_url = page_url or _load_bulk_download_url_for_data_type("contributions")
    for attempt_number in range(1, REMOTE_PROTOCOL_RETRY_ATTEMPTS + 1):
        try:
            return _download_il_raw_file_once(
                file_name,
                dest_dir=dest_dir,
                page_url=download_page_url,
                verify_certificates=True,
                max_data_rows=max_data_rows,
                tail_data_rows=tail_data_rows,
            )
        except httpx.HTTPError as error:
            if _is_incomplete_chunked_read_error(error) and attempt_number < REMOTE_PROTOCOL_RETRY_ATTEMPTS:
                warnings.warn(
                    "IL bulk stream closed early with incomplete chunked read; retrying download from scratch.",
                    UserWarning,
                    stacklevel=2,
                )
                continue
            if not _is_ssl_or_certificate_error(error):
                raise
            if not allow_insecure_tls:
                raise
            if not _break_glass_insecure_tls_retry_enabled():
                raise RuntimeError(
                    "Insecure TLS retry requested, but break-glass override is disabled. "
                    f"Set {INSECURE_TLS_RETRY_ENV_VAR}=1 to allow a one-off insecure retry."
                ) from error

            warnings.warn(
                "SSL certificate validation failed; retrying with certificate verification disabled "
                f"because {INSECURE_TLS_RETRY_ENV_VAR}=1 was provided.",
                UserWarning,
                stacklevel=2,
            )
            return _download_il_raw_file_once(
                file_name,
                dest_dir=dest_dir,
                page_url=download_page_url,
                verify_certificates=False,
                max_data_rows=max_data_rows,
                tail_data_rows=tail_data_rows,
            )


def download_il_raw_file(
    file_name: str,
    *,
    dest_dir: Path,
    page_url: str | None = None,
    allow_insecure_tls: bool = False,
    max_data_rows: int | None = None,
    tail_data_rows: int | None = None,
) -> Path:
    return download_il_raw_file_with_metadata(
        file_name,
        dest_dir=dest_dir,
        page_url=page_url,
        allow_insecure_tls=allow_insecure_tls,
        max_data_rows=max_data_rows,
        tail_data_rows=tail_data_rows,
    ).path


def download_il_data_with_metadata(
    data_type: str,
    *,
    dest_dir: Path,
    allow_insecure_tls: bool = False,
    max_data_rows: int | None = None,
    tail_data_rows: int | None = None,
) -> ILDownloadResult:
    normalized_data_type = _normalize_data_type(data_type)
    try:
        file_name = _DATA_FILE_BY_DATA_TYPE[normalized_data_type]
    except KeyError as error:
        raise ValueError(f"Unsupported IL data type: {data_type}") from error
    return download_il_raw_file_with_metadata(
        file_name,
        dest_dir=dest_dir,
        page_url=_load_bulk_download_url_for_data_type(data_type),
        allow_insecure_tls=allow_insecure_tls,
        max_data_rows=max_data_rows,
        tail_data_rows=tail_data_rows,
    )


def download_il_data(
    data_type: str,
    *,
    dest_dir: Path,
    allow_insecure_tls: bool = False,
    tail_data_rows: int | None = None,
) -> Path:
    return download_il_data_with_metadata(
        data_type,
        dest_dir=dest_dir,
        allow_insecure_tls=allow_insecure_tls,
        tail_data_rows=tail_data_rows,
    ).path
