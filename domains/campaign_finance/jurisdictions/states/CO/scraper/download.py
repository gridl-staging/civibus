"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/CO/scraper/download.py.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import warnings
import zipfile

import httpx

from . import _load_co_data_source_blocks

REQUEST_TIMEOUT_SECONDS = 30.0
SUPPORTED_SSL_ERROR_HINTS = ("certificate", "ssl", "tls", "cert verify failed")
INSECURE_TLS_RETRY_ENV_VAR = "CIVIBUS_ALLOW_INSECURE_TLS_RETRY"


@lru_cache(maxsize=1)
def _load_data_source_templates() -> dict[str, str]:
    template_by_data_type: dict[str, str] = {}
    for data_source_block in _load_co_data_source_blocks():
        bulk_download_url = _extract_bulk_download_url(data_source_block.lines)
        if bulk_download_url is None:
            continue
        _register_data_source_template(
            template_by_data_type=template_by_data_type,
            source_name=data_source_block.name,
            bulk_download_url=bulk_download_url,
        )

    return template_by_data_type


def _extract_bulk_download_url(lines: tuple[str, ...]) -> str | None:
    for line in lines:
        if not line.startswith("    bulk_download_url:"):
            continue

        bulk_download_url = line.strip().removeprefix("bulk_download_url:").strip()
        if bulk_download_url.lower() == "null":
            return None
        return bulk_download_url.strip('"')

    return None


def _register_data_source_template(
    template_by_data_type: dict[str, str],
    source_name: str,
    bulk_download_url: str,
) -> None:
    for supported_data_type in _extract_supported_data_types(source_name, bulk_download_url):
        template_by_data_type[supported_data_type] = bulk_download_url


def _extract_supported_data_types(source_name: str, bulk_download_url: str) -> tuple[str, ...]:
    supported_data_types: list[str] = []

    source_label = source_name.rpartition("—")[2].strip().lower()
    if source_label:
        supported_data_types.append(source_label)

    filename = bulk_download_url.rsplit("/", maxsplit=1)[-1]
    prefix = "{YEAR}_"
    suffix = "Data.csv.zip"
    if filename.startswith(prefix) and filename.endswith(suffix):
        filename_label = filename[len(prefix) : -len(suffix)].strip().lower()
        if filename_label:
            supported_data_types.append(filename_label)

    return tuple(dict.fromkeys(supported_data_types))


def _find_bulk_download_template(data_type: str) -> str:
    normalized_data_type = data_type.strip().lower()
    bulk_download_url = _load_data_source_templates().get(normalized_data_type)
    if bulk_download_url is not None:
        return bulk_download_url

    raise ValueError(f"Unsupported TRACER data type: {data_type}")


def build_tracer_url(year: int, data_type: str) -> str:
    template = _find_bulk_download_template(data_type=data_type)
    return template.replace("{YEAR}", str(year))


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


def _stream_download_to_path(url: str, destination_path: Path, verify_certificates: bool) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_download_path_text = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".part",
        dir=destination_path.parent,
    )
    os.close(file_descriptor)
    temporary_download_path = Path(temporary_download_path_text)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, verify=verify_certificates) as http_client:
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


def _break_glass_insecure_tls_retry_enabled() -> bool:
    return os.getenv(INSECURE_TLS_RETRY_ENV_VAR, "").strip() == "1"


def download_tracer_file(
    year: int,
    data_type: str,
    dest_dir: Path,
    *,
    allow_insecure_tls: bool = False,
) -> Path:
    tracer_url = build_tracer_url(year=year, data_type=data_type)
    dest_dir.mkdir(parents=True, exist_ok=True)

    zip_filename = f"{year}_{data_type}Data.csv.zip"
    destination_path = dest_dir / zip_filename

    try:
        _stream_download_to_path(
            url=tracer_url,
            destination_path=destination_path,
            verify_certificates=True,
        )
    except httpx.HTTPError as error:
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
        _stream_download_to_path(
            url=tracer_url,
            destination_path=destination_path,
            verify_certificates=False,
        )

    return destination_path


def _build_safe_extraction_path(target_directory: Path, member_filename: str) -> Path:
    member_path = PurePosixPath(member_filename)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"ZIP file contains unsafe CSV path: {member_filename}")

    return target_directory.joinpath(*member_path.parts)


def extract_csv_from_zip(zip_path: Path, dest_dir: Path | None = None) -> Path:
    target_directory = dest_dir if dest_dir is not None else zip_path.parent
    target_directory.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        csv_members = [
            member for member in archive.infolist() if not member.is_dir() and member.filename.lower().endswith(".csv")
        ]
        if len(csv_members) != 1:
            raise ValueError("ZIP file must contain exactly one CSV member")

        csv_member = csv_members[0]
        extracted_path = _build_safe_extraction_path(target_directory, csv_member.filename)
        extracted_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(csv_member) as source_file, extracted_path.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)

    return extracted_path
