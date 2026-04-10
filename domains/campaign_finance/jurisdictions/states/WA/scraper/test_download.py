from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.WA.scraper.download import (
    build_wa_download_url,
    download_wa_csv,
)

_WA_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class TestWADirectDownloadContract2026:
    """Lock WA PDC Socrata dataset IDs and config verification for 2026 cycle."""

    def test_contributions_url_uses_known_dataset_id(self) -> None:
        url = build_wa_download_url("contributions")
        assert "kv7h-kjye" in url

    def test_expenditures_url_uses_known_dataset_id(self) -> None:
        url = build_wa_download_url("expenditures")
        assert "tijg-9zyp" in url

    def test_independent_expenditures_url_uses_known_dataset_id(self) -> None:
        url = build_wa_download_url("independent_expenditures")
        assert "67cp-h962" in url

    def test_loans_url_uses_known_dataset_id(self) -> None:
        url = build_wa_download_url("loans")
        assert "d2ig-r3q4" in url

    def test_config_verified_for_2026_cycle(self) -> None:
        """All WA data sources must show a 2026-cycle verification date."""
        cycle_cutoff = date(2026, 3, 21)
        config = load_jurisdiction_config(_WA_CONFIG_PATH)
        for source in config.data_sources:
            assert source.last_verified_working is not None, f"{source.name} has no last_verified_working date"
            assert source.last_verified_working >= cycle_cutoff, (
                f"{source.name} last_verified_working={source.last_verified_working} is before {cycle_cutoff}"
            )


@pytest.mark.parametrize(
    ("data_type", "expected_url"),
    [
        ("contributions", "https://data.wa.gov/resource/kv7h-kjye.csv"),
        ("expenditures", "https://data.wa.gov/resource/tijg-9zyp.csv"),
        ("independent_expenditures", "https://data.wa.gov/resource/67cp-h962.csv"),
        ("loans", "https://data.wa.gov/resource/d2ig-r3q4.csv"),
    ],
)
def test_build_wa_download_url_uses_configured_bulk_urls(data_type: str, expected_url: str) -> None:
    assert build_wa_download_url(data_type) == expected_url


def test_build_wa_download_url_adds_limit_query() -> None:
    assert build_wa_download_url("contributions", limit=50) == "https://data.wa.gov/resource/kv7h-kjye.csv?$limit=50"


def test_build_wa_download_url_raises_for_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported WA data type"):
        build_wa_download_url("pledges")


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


def test_download_wa_csv_streams_to_dest_dir_and_returns_path(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"id,amount\n", b"1,100.00\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        saved_path = download_wa_csv(data_type="contributions", dest_dir=destination_dir)

    assert saved_path == destination_dir / "wa_contributions.csv"
    assert saved_path.read_text(encoding="utf-8") == "id,amount\n1,100.00\n"


def test_download_wa_csv_removes_partial_file_when_stream_fails(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())
    mock_response = _make_failing_streaming_response([b"id,amount\n"], error=read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_wa_csv(data_type="contributions", dest_dir=destination_dir)

    assert list(destination_dir.iterdir()) == []
