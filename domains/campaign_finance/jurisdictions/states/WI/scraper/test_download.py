from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.WI.scraper.download import (
    build_wi_download_url,
    download_wi_csv,
)


@pytest.mark.parametrize(
    ("data_type", "expected_url"),
    [
        ("transactions", "https://campaignfinance.wi.gov/api/data-download/transactions"),
        ("reports", "https://campaignfinance.wi.gov/api/data-download/reports"),
        ("committees", "https://campaignfinance.wi.gov/api/data-download/committees"),
    ],
)
def test_build_wi_download_url_uses_verified_sunshine_endpoints(data_type: str, expected_url: str) -> None:
    assert build_wi_download_url(data_type) == expected_url


def test_build_wi_download_url_raises_for_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported WI data type"):
        build_wi_download_url("loans")


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


def test_download_wi_csv_streams_to_dest_dir_and_returns_path(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"id,amount\\n", b"1,100.00\\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        saved_path = download_wi_csv(data_type="transactions", dest_dir=destination_dir)

    assert saved_path == destination_dir / "wi_transactions.csv"
    assert saved_path.read_text(encoding="utf-8") == "id,amount\\n1,100.00\\n"


def test_download_wi_csv_removes_partial_file_when_stream_fails(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())
    mock_response = _make_failing_streaming_response([b"id,amount\\n"], error=read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_wi_csv(data_type="transactions", dest_dir=destination_dir)

    assert list(destination_dir.iterdir()) == []
