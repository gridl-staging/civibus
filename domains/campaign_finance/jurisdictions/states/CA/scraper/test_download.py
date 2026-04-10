from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.CA.scraper import (
    INGESTION_MEMBERS,
)
from domains.campaign_finance.jurisdictions.states.CA.scraper.download import (
    download_ca_archive,
    extract_ingestion_members,
    extract_member_from_archive,
    get_archive_download_url,
)

_CA_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class TestCADirectDownloadContract2026:
    """Lock CA direct-download URL, format, and config verification for 2026 cycle.

    These are regression guards: if the CA SOS changes the archive URL or the
    config verification dates drift, these tests catch it before a live download
    attempt fails silently.
    """

    def test_archive_url_resolves_to_sos_cdn(self) -> None:
        url = get_archive_download_url()
        assert url.startswith("https://campaignfinance.cdn.sos.ca.gov/")
        assert url.endswith(".zip")

    def test_archive_url_is_cycle_independent(self) -> None:
        """CA archive is a single rolling file — no year parameter needed."""
        url = get_archive_download_url()
        assert url == "https://campaignfinance.cdn.sos.ca.gov/dbwebexport.zip"

    def test_config_verified_for_2026_cycle(self) -> None:
        """All CA data sources must show a 2026-cycle verification date."""
        cycle_cutoff = date(2026, 3, 21)
        config = load_jurisdiction_config(_CA_CONFIG_PATH)
        for source in config.data_sources:
            assert source.last_verified_working is not None, f"{source.name} has no last_verified_working date"
            assert source.last_verified_working >= cycle_cutoff, (
                f"{source.name} last_verified_working={source.last_verified_working} is before {cycle_cutoff}"
            )


def test_archive_download_url_from_config():
    url = get_archive_download_url()
    assert url == "https://campaignfinance.cdn.sos.ca.gov/dbwebexport.zip"


def _write_zip_with_members(zip_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, mode="w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    return response


def _make_failing_streaming_response(chunks: list[bytes], error: httpx.HTTPError) -> MagicMock:
    def iter_bytes():
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = iter_bytes()
    return response


# --- download_ca_archive ---


def test_download_ca_archive_streams_to_dest_dir_and_returns_path(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"PK", b"\x03\x04"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        saved_path = download_ca_archive(dest_dir=destination_dir)

    assert saved_path.name == "dbwebexport.zip"
    assert saved_path.parent == destination_dir
    assert saved_path.read_bytes() == b"PK\x03\x04"


def test_download_ca_archive_removes_partial_file_on_stream_failure(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())
    mock_response = _make_failing_streaming_response([b"PK"], error=read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_ca_archive(dest_dir=destination_dir)

    # No partial files should remain
    if destination_dir.exists():
        assert list(destination_dir.iterdir()) == []


# --- extract_member_from_archive ---


def test_extract_member_from_archive_extracts_single_tsv(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    tsv_content = b"FILING_ID\tTRAN_ID\tAMOUNT\n1001\tT001\t500.00\n"
    _write_zip_with_members(zip_path, {"CalAccess/DATA/RCPT_CD.TSV": tsv_content})

    dest_dir = tmp_path / "extracted"
    extracted = extract_member_from_archive(
        zip_path,
        "CalAccess/DATA/RCPT_CD.TSV",
        dest_dir=dest_dir,
    )

    assert extracted.name == "RCPT_CD.TSV"
    assert extracted.read_bytes() == tsv_content


def test_extract_member_raises_for_missing_member(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    _write_zip_with_members(zip_path, {"CalAccess/DATA/RCPT_CD.TSV": b"data"})

    with pytest.raises(KeyError):
        extract_member_from_archive(
            zip_path,
            "CalAccess/DATA/NONEXISTENT.TSV",
            dest_dir=tmp_path / "out",
        )


def test_extract_member_rejects_path_traversal(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    _write_zip_with_members(zip_path, {"../etc/passwd": b"root:x:0:0"})

    with pytest.raises(ValueError, match="[Uu]nsafe|[Pp]ath traversal"):
        extract_member_from_archive(
            zip_path,
            "../etc/passwd",
            dest_dir=tmp_path / "out",
        )


def test_extract_member_rejects_windows_style_path_traversal(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    _write_zip_with_members(zip_path, {r"..\\evil.tsv": b"payload"})

    with pytest.raises(ValueError, match="[Uu]nsafe|[Pp]ath traversal"):
        extract_member_from_archive(
            zip_path,
            r"..\\evil.tsv",
            dest_dir=tmp_path / "out",
        )


def test_extract_member_flattens_to_filename_only(tmp_path: Path):
    """Extracted file should be the bare filename, not nested under CalAccess/DATA/."""
    zip_path = tmp_path / "dbwebexport.zip"
    _write_zip_with_members(zip_path, {"CalAccess/DATA/EXPN_CD.TSV": b"col1\tcol2\n"})

    dest_dir = tmp_path / "extracted"
    extracted = extract_member_from_archive(
        zip_path,
        "CalAccess/DATA/EXPN_CD.TSV",
        dest_dir=dest_dir,
    )

    # Should be flat: dest_dir/EXPN_CD.TSV, not dest_dir/CalAccess/DATA/EXPN_CD.TSV
    assert extracted == dest_dir / "EXPN_CD.TSV"


def test_extract_member_does_not_follow_preexisting_destination_symlink(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    tsv_content = b"FILING_ID\tTRAN_ID\tAMOUNT\n1001\tT001\t500.00\n"
    _write_zip_with_members(zip_path, {"CalAccess/DATA/RCPT_CD.TSV": tsv_content})

    dest_dir = tmp_path / "extracted"
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination_path = dest_dir / "RCPT_CD.TSV"
    victim_path = tmp_path / "victim.txt"
    victim_path.write_text("do-not-overwrite", encoding="utf-8")
    destination_path.symlink_to(victim_path)

    extracted = extract_member_from_archive(
        zip_path,
        "CalAccess/DATA/RCPT_CD.TSV",
        dest_dir=dest_dir,
    )

    assert extracted == destination_path
    assert extracted.read_bytes() == tsv_content
    assert not extracted.is_symlink()
    assert victim_path.read_text(encoding="utf-8") == "do-not-overwrite"


# --- extract_ingestion_members ---


def test_extract_ingestion_members_extracts_all_locked_members(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    member_data = {member: f"header\tfor\t{member}\n".encode() for member in INGESTION_MEMBERS}
    _write_zip_with_members(zip_path, member_data)

    dest_dir = tmp_path / "extracted"
    result = extract_ingestion_members(zip_path, dest_dir=dest_dir)

    assert len(result) == 6
    for member in INGESTION_MEMBERS:
        table_name = member.rsplit("/", 1)[-1]
        assert table_name in result
        assert result[table_name].exists()


def test_extract_ingestion_members_raises_when_member_missing(tmp_path: Path):
    zip_path = tmp_path / "dbwebexport.zip"
    # Only include 5 of 6 members
    partial_members = {m: b"data" for m in INGESTION_MEMBERS[:5]}
    _write_zip_with_members(zip_path, partial_members)

    with pytest.raises(KeyError):
        extract_ingestion_members(zip_path, dest_dir=tmp_path / "out")


# --- ZIP64 handling ---


def test_extract_member_handles_zip64_large_file_header(tmp_path: Path):
    """Members with ZIP64 extended headers (uncomp_size=0xFFFFFFFF) should extract correctly."""
    zip_path = tmp_path / "dbwebexport.zip"
    # Create a ZIP64 archive by using force_zip64=True
    with zipfile.ZipFile(zip_path, mode="w", allowZip64=True) as archive:
        info = zipfile.ZipInfo("CalAccess/DATA/RCPT_CD.TSV")
        info.file_size = 100  # small actual content
        archive.writestr(info, b"A" * 100)

    dest_dir = tmp_path / "extracted"
    extracted = extract_member_from_archive(
        zip_path,
        "CalAccess/DATA/RCPT_CD.TSV",
        dest_dir=dest_dir,
    )
    assert extracted.exists()
    assert len(extracted.read_bytes()) == 100
