"""Tests for IRS 527 bulk downloader and ZIP extraction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.ingest.dark_money import download as irs_download
from domains.campaign_finance.ingest.dark_money.download import (
    IRS_527_FULL_DATA_URL,
    IRS_527_TXT_MEMBER_PATH,
    _find_irs_527_txt_member,
    _validate_irs_download_url,
    download_irs_527_full_data,
    extract_irs_527_txt,
)

FIXTURE_ZIP = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "bulk" / "irs_527_sample.zip"


# --- helpers ---


def _streaming_response(chunks: list[bytes], *, response_url: str) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    response.url = httpx.URL(response_url)
    response.history = []
    return response


def _failing_response(chunks: list[bytes], error: Exception, *, response_url: str) -> MagicMock:
    def _iter_bytes() -> object:
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = _iter_bytes()
    response.url = httpx.URL(response_url)
    response.history = []
    return response


def _redirect_response(response_url: str) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.url = httpx.URL(response_url)
    response.history = []
    return response


# --- URL constant ---


class TestIRS527FullDataURL:
    def test_url_points_to_irs_forms_full_data(self):
        assert IRS_527_FULL_DATA_URL == "https://forms.irs.gov/app/pod/dataDownload/fullData"


# --- URL validation ---


class TestValidateIrsDownloadUrl:
    def test_accepts_valid_irs_url(self):
        url = "https://forms.irs.gov/app/pod/dataDownload/fullData"
        assert _validate_irs_download_url(url, context="test") == url

    def test_rejects_http(self):
        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_irs_download_url("http://forms.irs.gov/app/pod/dataDownload/fullData", context="test")

    def test_rejects_non_irs_host(self):
        with pytest.raises(ValueError, match="approved IRS"):
            _validate_irs_download_url("https://evil.example/app/pod/dataDownload/fullData", context="test")

    def test_accepts_apps_irs_gov(self):
        url = "https://apps.irs.gov/pub/epostcard/990/xml/2026/index_2026.csv"
        assert _validate_irs_download_url(url, context="test") == url


# --- download_irs_527_full_data ---


class TestDownloadIrs527FullData:
    def test_uses_correct_url_and_destination(self, tmp_path: Path):
        dest_dir = tmp_path / "downloads"
        with patch("domains.campaign_finance.ingest.dark_money.download._stream_download_to_path") as stream:
            result = download_irs_527_full_data(dest_dir)

        expected_path = dest_dir / "PolOrgsFullData.zip"
        assert result == expected_path
        stream.assert_called_once_with(IRS_527_FULL_DATA_URL, expected_path)


# --- _stream_download_to_path atomic behavior ---


class TestStreamDownloadToPath:
    def test_uses_ipv4_only_transport_for_irs_downloads(self, tmp_path: Path):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        response = _streaming_response(
            [b"PK", b"\x03\x04zipcontent"],
            response_url=IRS_527_FULL_DATA_URL,
        )

        ipv4_client_cm = MagicMock()
        ipv4_client = ipv4_client_cm.__enter__.return_value
        ipv4_client.stream.return_value.__enter__.return_value = response

        transport = MagicMock()

        with patch("httpx.Client", return_value=ipv4_client_cm) as mock_client_type:
            with patch("httpx.HTTPTransport", return_value=transport) as mock_transport_type:
                irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert dest.exists()
        assert dest.read_bytes() == b"PK\x03\x04zipcontent"
        assert mock_client_type.call_count == 1
        assert mock_client_type.call_args_list[0].kwargs == {
            "timeout": irs_download.REQUEST_TIMEOUT_SECONDS,
            "transport": transport,
        }
        mock_transport_type.assert_called_once_with(local_address="0.0.0.0")

    def test_writes_atomically_without_temp_residue(self, tmp_path: Path):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        response = _streaming_response(
            [b"PK", b"\x03\x04zipcontent"],
            response_url=IRS_527_FULL_DATA_URL,
        )

        with patch("httpx.Client") as mock_client_type:
            client = mock_client_type.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response
            irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert dest.exists()
        assert dest.read_bytes() == b"PK\x03\x04zipcontent"
        assert list(dest.parent.glob("*.part")) == []

    def test_cleans_partial_on_stream_failure(self, tmp_path: Path):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        error = httpx.ReadError("connection reset", request=MagicMock())
        response = _failing_response([b"partial"], error, response_url=IRS_527_FULL_DATA_URL)

        with patch("httpx.Client") as mock_client_type:
            client = mock_client_type.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response

            with pytest.raises(httpx.ReadError, match="connection reset"):
                irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert list(dest.parent.glob("*.part")) == []
        assert list(dest.parent.glob("*.zip")) == []

    def test_cleans_partial_on_http_status_error(self, tmp_path: Path):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        request = httpx.Request("GET", IRS_527_FULL_DATA_URL)
        response = _streaming_response([b"payload"], response_url=IRS_527_FULL_DATA_URL)
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=request,
            response=httpx.Response(500, request=request),
        )

        with patch("httpx.Client") as mock_client_type:
            client = mock_client_type.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response

            with pytest.raises(httpx.HTTPStatusError, match="server error"):
                irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert list(dest.parent.glob("*.part")) == []

    def test_rejects_oversized_stream(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        monkeypatch.setattr(irs_download, "MAX_DOWNLOAD_BYTES", 4)
        response = _streaming_response([b"1234", b"5"], response_url=IRS_527_FULL_DATA_URL)

        with patch("httpx.Client") as mock_client_type:
            client = mock_client_type.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response

            with pytest.raises(ValueError, match="exceeds.*size limit"):
                irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert list(dest.parent.glob("*.part")) == []

    def test_rejects_redirect_to_external_host(self, tmp_path: Path):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        response = _streaming_response(
            [b"payload"],
            response_url="https://evil.example/PolOrgsFullData.zip",
        )

        with patch("httpx.Client") as mock_client_type:
            client = mock_client_type.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response

            with pytest.raises(ValueError, match="approved IRS"):
                irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert list(dest.parent.glob("*.part")) == []

    def test_rejects_redirect_hop_to_external_host(self, tmp_path: Path):
        dest = tmp_path / "downloads" / "PolOrgsFullData.zip"
        response = _streaming_response([b"payload"], response_url=IRS_527_FULL_DATA_URL)
        response.history = [_redirect_response("https://evil.example/redirect")]

        with patch("httpx.Client") as mock_client_type:
            client = mock_client_type.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response

            with pytest.raises(ValueError, match="approved IRS"):
                irs_download._stream_download_to_path(IRS_527_FULL_DATA_URL, dest)

        assert list(dest.parent.glob("*.part")) == []


# --- archive member discovery and extraction ---


class TestFindIrs527TxtMember:
    def test_finds_fulldatafile_txt_in_real_fixture(self):
        member = _find_irs_527_txt_member(FIXTURE_ZIP)
        assert member == IRS_527_TXT_MEMBER_PATH

    def test_raises_on_missing_member(self, tmp_path: Path):
        bad_zip = tmp_path / "empty.zip"
        import zipfile

        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("not_the_right_file.csv", "data")

        with pytest.raises(ValueError, match="FullDataFile.txt"):
            _find_irs_527_txt_member(bad_zip)


class TestExtractIrs527Txt:
    def test_extracts_txt_to_destination(self, tmp_path: Path):
        dest_dir = tmp_path / "extracted"
        result = extract_irs_527_txt(FIXTURE_ZIP, dest_dir)

        assert result == dest_dir / "FullDataFile.txt"
        assert result.exists()

        # Verify content has expected record types
        content = result.read_text(encoding="latin-1")
        record_types = {line.split("|")[0] for line in content.strip().split("\n")}
        assert {"H", "1", "2", "A", "B", "D", "R", "F"} == record_types

    def test_extracts_pipe_terminated_rows(self, tmp_path: Path):
        dest_dir = tmp_path / "extracted"
        result = extract_irs_527_txt(FIXTURE_ZIP, dest_dir)

        for line in result.read_text(encoding="latin-1").strip().split("\n"):
            assert line.endswith("|"), f"Row not pipe-terminated: {line[:40]}..."
