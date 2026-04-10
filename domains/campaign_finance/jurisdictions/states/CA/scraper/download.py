from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from . import INGESTION_MEMBERS, _get_raw_data_source

REQUEST_TIMEOUT_SECONDS = 60.0


def get_archive_download_url() -> str:
    """Return the bulk download URL for the CA archive from config."""
    raw_source = _get_raw_data_source()
    if raw_source.bulk_download_url is None:
        raise RuntimeError("CA config missing bulk_download_url for raw data source")
    return raw_source.bulk_download_url


def _stream_download_to_path(url: str, destination_path: Path) -> None:
    """Stream-download a URL to a local path with atomic rename and cleanup on failure."""
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


def download_ca_archive(dest_dir: Path) -> Path:
    """Download the CAL-ACCESS dbwebexport.zip archive to dest_dir."""
    url = get_archive_download_url()
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination_path = dest_dir / "dbwebexport.zip"
    _stream_download_to_path(url=url, destination_path=destination_path)
    return destination_path


def _validate_member_path(member_path: str) -> None:
    """Reject ZIP member paths that attempt path traversal."""
    # ZIP member names should use forward slashes only; rejecting backslashes closes
    # the Windows-style `..\foo` traversal form before we flatten to a local filename.
    if "\\" in member_path:
        raise ValueError(f"Unsafe Windows-style path separator in ZIP member: {member_path}")
    posix_path = PurePosixPath(member_path)
    if posix_path.is_absolute() or ".." in posix_path.parts:
        raise ValueError(f"Unsafe path traversal in ZIP member: {member_path}")


def _write_archive_member_to_destination(source_file: object, destination_path: Path) -> None:
    """Write extracted bytes to destination via a private temp dir to avoid symlink clobber."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(tempfile.mkdtemp(prefix=f".{destination_path.name}.", dir=destination_path.parent))
    temporary_destination = temporary_directory / destination_path.name
    try:
        with temporary_destination.open("wb") as destination_file:
            shutil.copyfileobj(source_file, destination_file)
        temporary_destination.replace(destination_path)
    except Exception:
        temporary_destination.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporary_directory, ignore_errors=True)


def extract_member_from_archive(
    zip_path: Path,
    member_path: str,
    *,
    dest_dir: Path,
) -> Path:
    """Extract a single member from the CA ZIP archive, flattening to filename only."""
    _validate_member_path(member_path)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Flatten: CalAccess/DATA/RCPT_CD.TSV -> RCPT_CD.TSV
    filename = PurePosixPath(member_path).name

    with zipfile.ZipFile(zip_path, mode="r") as archive:
        with archive.open(member_path) as source_file:
            destination_path = dest_dir / filename
            _write_archive_member_to_destination(source_file, destination_path)

    return destination_path


def extract_ingestion_members(
    zip_path: Path,
    *,
    dest_dir: Path,
) -> dict[str, Path]:
    """Extract all locked Stage 2 ingestion members from the archive.

    Returns a dict mapping filename (e.g. "RCPT_CD.TSV") to the extracted path.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}

    for member in INGESTION_MEMBERS:
        extracted_path = extract_member_from_archive(zip_path, member, dest_dir=dest_dir)
        result[extracted_path.name] = extracted_path

    return result
