
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile

import httpx

LOGGER = logging.getLogger(__name__)

IRS_527_FULL_DATA_URL = "https://forms.irs.gov/app/pod/dataDownload/fullData"
IRS_527_TXT_MEMBER_PATH = "var/IRS/data/scripts/pofd/download/FullDataFile.txt"

REQUEST_TIMEOUT_SECONDS = 120.0
MAX_DOWNLOAD_BYTES = 2_147_483_648  # 2 GiB — full archive is ~321 MB

_ALLOWED_IRS_SCHEMES = frozenset({"https"})
_ALLOWED_IRS_HOSTS = frozenset({"forms.irs.gov", "apps.irs.gov"})


def _validate_irs_download_url(url: str, *, context: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()

    if scheme not in _ALLOWED_IRS_SCHEMES:
        raise ValueError(f"{context} must use HTTPS: {url}")
    if host not in _ALLOWED_IRS_HOSTS:
        raise ValueError(f"{context} must stay on an approved IRS host: {url}")

    return url


def _stream_download_to_path(url: str, destination: Path) -> None:
    _validate_irs_download_url(url, context="IRS download URL")
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=destination.parent,
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            with client.stream("GET", url, follow_redirects=True) as response:
                response.raise_for_status()

                redirect_history = tuple(getattr(response, "history", ()))
                for hop in (*redirect_history, response):
                    _validate_irs_download_url(str(hop.url), context="IRS download URL")

                with tmp_path.open("wb") as f:
                    downloaded_bytes = 0
                    for chunk in response.iter_bytes():
                        if chunk:
                            downloaded_bytes += len(chunk)
                            if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                                raise ValueError(
                                    f"IRS download exceeds the allowed size limit of {MAX_DOWNLOAD_BYTES} bytes"
                                )
                            f.write(chunk)

        tmp_path.replace(destination)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def download_irs_527_full_data(dest_dir: Path) -> Path:
    destination = dest_dir / "PolOrgsFullData.zip"
    _stream_download_to_path(IRS_527_FULL_DATA_URL, destination)
    return destination


def _find_irs_527_txt_member(archive_path: Path) -> str:
    with ZipFile(archive_path) as zf:
        if IRS_527_TXT_MEMBER_PATH in zf.namelist():
            return IRS_527_TXT_MEMBER_PATH

        txt_members = [n for n in zf.namelist() if n.lower().endswith("fulldatafile.txt")]
        if txt_members:
            return txt_members[0]

    raise ValueError(
        f"No FullDataFile.txt member found in {archive_path}. Expected member path: {IRS_527_TXT_MEMBER_PATH}"
    )


def extract_irs_527_txt(archive_path: Path, dest_dir: Path) -> Path:
    member = _find_irs_527_txt_member(archive_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "FullDataFile.txt"

    with ZipFile(archive_path) as zf:
        with zf.open(member) as src:
            with dest_file.open("wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)

    LOGGER.info("Extracted %s -> %s", member, dest_file)
    return dest_file
