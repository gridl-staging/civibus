"""Tests for Virginia CSV downloader.

Tests URL construction for the VA monthly-directory CSV pattern
and verifies streaming download behavior with mocked HTTP.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.VA.scraper.download import (
    build_va_download_url,
    download_va_csv,
)


# --- URL construction tests ---


@pytest.mark.parametrize(
    ("data_type", "year_month", "expected_url"),
    [
        (
            "contributions",
            "2026_03",
            "https://apps.elections.virginia.gov/SBE_CSV/CF/2026_03/ScheduleA.csv",
        ),
        (
            "expenditures",
            "2025_11",
            "https://apps.elections.virginia.gov/SBE_CSV/CF/2025_11/ScheduleD.csv",
        ),
        (
            "reports",
            "2024_06",
            "https://apps.elections.virginia.gov/SBE_CSV/CF/2024_06/Report.csv",
        ),
    ],
)
def test_build_va_download_url_constructs_monthly_urls(data_type: str, year_month: str, expected_url: str) -> None:
    """URL builder should interpolate year_month into the config template."""
    assert build_va_download_url(data_type, year_month) == expected_url


def test_build_va_download_url_raises_for_unsupported_data_type() -> None:
    """Should raise ValueError for an unknown data type."""
    with pytest.raises(ValueError, match="Unsupported VA data type"):
        build_va_download_url("loans", "2026_03")


# --- Streaming download tests ---


def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    """Build a mock httpx streaming response that yields the given chunks."""
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    return response


def _make_failing_streaming_response(chunks: list[bytes], error: httpx.HTTPError) -> MagicMock:
    """Build a mock streaming response that raises an error partway through."""

    def iter_bytes():
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = iter_bytes()
    return response


def test_download_va_csv_streams_to_dest_dir_and_returns_path(tmp_path: Path) -> None:
    """Download should stream CSV content to the destination directory."""
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"ReportId,Amount\n", b"123,100.00\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        saved_path = download_va_csv(
            data_type="contributions",
            dest_dir=destination_dir,
            year_month="2026_03",
        )

    assert saved_path == destination_dir / "va_contributions_2026_03.csv"
    assert saved_path.read_text(encoding="utf-8") == "ReportId,Amount\n123,100.00\n"


def test_download_va_csv_removes_partial_file_when_stream_fails(tmp_path: Path) -> None:
    """If the stream fails mid-download, partial files should be cleaned up."""
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())
    mock_response = _make_failing_streaming_response([b"ReportId,Amount\n"], error=read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_va_csv(
                data_type="contributions",
                dest_dir=destination_dir,
                year_month="2026_03",
            )

    # No partial files should remain
    assert list(destination_dir.iterdir()) == []


def test_download_va_csv_sends_user_agent_header(tmp_path: Path) -> None:
    """Download should include a browser-like User-Agent header."""
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"data\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        download_va_csv(
            data_type="contributions",
            dest_dir=destination_dir,
            year_month="2026_03",
        )

        # Verify User-Agent was passed in headers to the Client constructor
        call_kwargs = mock_client_type.call_args
        assert "headers" in call_kwargs.kwargs
        headers = call_kwargs.kwargs["headers"]
        assert "User-Agent" in headers
