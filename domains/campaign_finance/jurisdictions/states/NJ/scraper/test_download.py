from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.NJ.scraper.download import (
    build_nj_download_url,
    download_nj_csv,
)


def test_build_nj_download_url_returns_elec_api_endpoint() -> None:
    url = build_nj_download_url("contributions")
    assert url == "https://www.njelecefilesearch.com/api/VWContributionDetail/DownlodDataCSV"


def test_build_nj_download_url_raises_for_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported NJ data type"):
        build_nj_download_url("loans")


def _make_post_response(blob_url: str) -> MagicMock:
    """Simulate the ELEC API POST response that returns a JSON string with a blob URL."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = blob_url
    return response


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


def test_download_nj_csv_posts_then_streams_blob_to_dest(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    blob_url = "https://elecdownloads.blob.core.windows.net/exports/nj-contributions.csv?sv=2021-08-06&sig=abc"
    csv_content = b"IsIndividual,FirstName,MI\nTrue,Jane,A\n"

    post_response = _make_post_response(blob_url)
    stream_response = _make_streaming_response([csv_content])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.post.return_value = post_response
        mock_client.stream.return_value.__enter__.return_value = stream_response

        saved_path = download_nj_csv(data_type="contributions", dest_dir=destination_dir)

    assert saved_path == destination_dir / "nj_contributions.csv"
    assert saved_path.read_text(encoding="utf-8") == csv_content.decode()
    mock_client.post.assert_called_once()
    mock_client.stream.assert_called_once_with("GET", blob_url, follow_redirects=False)


def test_download_nj_csv_removes_partial_file_on_stream_failure(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    blob_url = "https://elecdownloads.blob.core.windows.net/exports/nj-contributions.csv?sig=abc"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())

    post_response = _make_post_response(blob_url)
    stream_response = _make_failing_streaming_response([b"partial"], error=read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.post.return_value = post_response
        mock_client.stream.return_value.__enter__.return_value = stream_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_nj_csv(data_type="contributions", dest_dir=destination_dir)

    assert list(destination_dir.iterdir()) == []


@pytest.mark.parametrize(
    "blob_url",
    [
        "http://elecdownloads.blob.core.windows.net/exports/nj-contributions.csv?sig=abc",
        "https://169.254.169.254/latest/meta-data",
        "https://attacker.example.com/nj-contributions.csv",
    ],
)
def test_download_nj_csv_rejects_untrusted_blob_urls(blob_url: str, tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    post_response = _make_post_response(blob_url)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.post.return_value = post_response

        with pytest.raises(RuntimeError, match="unexpected"):
            download_nj_csv(data_type="contributions", dest_dir=destination_dir)

    mock_client.stream.assert_not_called()
