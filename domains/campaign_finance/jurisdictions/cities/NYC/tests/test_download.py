"""Unit tests for the NYC bulk CSV downloader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import httpx
import pytest

from domains.campaign_finance.jurisdictions.cities.NYC.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_nyc_config,
)
from domains.campaign_finance.jurisdictions.cities.NYC.scraper.download import (
    build_nyc_download_url,
    download_nyc_csv,
)


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


def test_load_nyc_config_and_contributions_source_from_yaml() -> None:
    config = _load_nyc_config()
    data_source = _load_data_source_for_data_type("  TRANSACTIONS  ")

    assert config.jurisdiction.code == "NYC"
    assert data_source.name == "NYC CFB Campaign Contributions"


def test_load_columns_for_transactions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("transactions")

    assert len(columns) == 52
    assert columns[0] == "ELECTION"
    assert columns[-1] == "INT_C_CODE"


def test_load_bulk_download_url_for_transactions_uses_config() -> None:
    url = _load_bulk_download_url_for_data_type("transactions")
    assert "nyccfb.info" in url
    assert "Contributions" in url


def test_build_nyc_download_url_returns_direct_url() -> None:
    url = build_nyc_download_url("transactions")

    assert "nyccfb.info" in url
    assert "Contributions" in url


def test_build_nyc_download_url_rejects_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported NYC data type"):
        build_nyc_download_url("pledges")


def test_download_nyc_csv_writes_plain_csv_and_names_destination(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    csv_bytes = b"ELECTION,OFFICECD,RECIPID\n2025,1,1682\n"
    response = _make_streaming_response([csv_bytes])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value = MagicMock(
            __enter__=MagicMock(return_value=response),
            __exit__=MagicMock(return_value=False),
        )

        output_path = download_nyc_csv("transactions", destination_dir)

    assert output_path == destination_dir / "nyc_transactions.csv"
    assert output_path.read_bytes() == csv_bytes


def test_download_nyc_csv_extracts_csv_from_zip(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    csv_content = b"ELECTION,OFFICECD,RECIPID\n2025,1,1682\n"

    # Build a real ZIP in memory
    zip_path = tmp_path / "source.zip"
    with ZipFile(zip_path, "w") as zf:
        zf.writestr("2025_Contributions.csv", csv_content)
    zip_bytes = zip_path.read_bytes()

    response = _make_streaming_response([zip_bytes])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value = MagicMock(
            __enter__=MagicMock(return_value=response),
            __exit__=MagicMock(return_value=False),
        )

        output_path = download_nyc_csv("transactions", destination_dir)

    assert output_path.name == "2025_Contributions.csv"
    assert output_path.read_bytes() == csv_content


def test_download_nyc_csv_removes_partial_file_when_stream_raises(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    interrupted = httpx.ReadError("stream interrupted", request=MagicMock())
    failing_response = _make_failing_streaming_response([b"ELECTION,OFFICECD\n"], interrupted)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = failing_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_nyc_csv("transactions", destination_dir)

    # Only the destination dir should exist, no leftover files
    assert list(destination_dir.iterdir()) == []


def test_download_nyc_csv_no_soda_pagination() -> None:
    """NYC uses direct HTTP GET — no $offset/$limit parameters in URL."""
    url = build_nyc_download_url("transactions")

    assert "$offset" not in url
    assert "$limit" not in url
    assert "$order" not in url
