from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.NE.scraper import download as ne_download
from domains.campaign_finance.jurisdictions.states.NE.scraper.download import download_ne_archive


def _streaming_response(chunks: list[bytes]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    return response


def _failing_response(chunks: list[bytes], error: httpx.HTTPError) -> MagicMock:
    def _iter_bytes() -> object:
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = _iter_bytes()
    return response


def test_download_ne_archive_uses_data_type_and_year_url_resolution(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    expected_url = "https://example.test/ne-2026.zip"
    mock_response = _streaming_response([b"zip-bytes"])

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.NE.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = expected_url
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        archive_path = download_ne_archive("contributions", 2026, destination_dir)

    assert archive_path == destination_dir / "NE_contributions_2026.zip"
    load_url.assert_called_once_with("contributions", 2026)
    mock_client.stream.assert_called_once_with("GET", expected_url, follow_redirects=True)


def test_download_ne_archive_streams_to_disk_and_returns_stable_path(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    mock_response = _streaming_response([b"PK", b"\x03\x04zipcontent"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        archive_path = download_ne_archive("expenditures", 2026, destination_dir)

    assert archive_path == destination_dir / "NE_expenditures_2026.zip"
    assert archive_path.read_bytes() == b"PK\x03\x04zipcontent"


def test_download_ne_archive_cleans_partial_files_on_failure(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("connection reset", request=MagicMock())
    mock_response = _failing_response([b"partial"], read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="connection reset"):
            download_ne_archive("loans", 2026, destination_dir)

    assert list(destination_dir.glob("*.part")) == []
    assert list(destination_dir.glob("NE_loans_2026.zip")) == []


def test_download_ne_archive_rejects_oversized_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination_dir = tmp_path / "downloads"
    monkeypatch.setattr(ne_download, "MAX_DOWNLOAD_BYTES", 4)
    mock_response = _streaming_response([b"1234", b"5"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(ValueError, match="exceeds the allowed size limit"):
            download_ne_archive("contributions", 2026, destination_dir)

    assert list(destination_dir.glob("*.part")) == []
