"""Tests for OR two-step session-based download."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.OR.scraper import download as or_download
from domains.campaign_finance.jurisdictions.states.OR.scraper.download import download_or_transactions


def _mock_session_response() -> MagicMock:
    """Mock response for the session-seeding cneSearch.do GET."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.raise_for_status = MagicMock()
    return response


def _mock_xls_response(chunks: list[bytes]) -> MagicMock:
    """Mock streaming response for XcelCNESearch export."""
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    return response


def _failing_xls_response(chunks: list[bytes], error: httpx.HTTPError) -> MagicMock:
    """Mock streaming response that fails partway through."""

    def _iter_bytes():
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = _iter_bytes()
    return response


def test_download_performs_two_step_session_acquisition(tmp_path: Path) -> None:
    """Verify: step 1 seeds session via cneSearch.do, step 2 downloads XcelCNESearch."""
    dest_dir = tmp_path / "downloads"
    session_resp = _mock_session_response()
    xls_resp = _mock_xls_response([b"Tran Id\tAmount\n", b"5001\t500.00\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        # First call = session seed, second call = stream
        mock_client.get.return_value = session_resp
        mock_client.stream.return_value.__enter__.return_value = xls_resp

        result_path = download_or_transactions("contributions", dest_dir)

    assert result_path.exists()
    assert result_path.suffix == ".xls"
    assert result_path.name.startswith("OR_contributions_")
    # Session seed should have been called
    mock_client.get.assert_called_once()
    # XLS stream should have been called
    mock_client.stream.assert_called_once()


def test_download_writes_xls_content_to_disk(tmp_path: Path) -> None:
    dest_dir = tmp_path / "downloads"
    content = b"Tran Id\tFiler\tAmount\n5001\tTest Committee\t500.00\n"
    xls_resp = _mock_xls_response([content])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = _mock_session_response()
        mock_client.stream.return_value.__enter__.return_value = xls_resp

        result_path = download_or_transactions("expenditures", dest_dir)

    assert result_path.read_bytes() == content


def test_download_cleans_partial_files_on_failure(tmp_path: Path) -> None:
    dest_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("connection reset", request=MagicMock())
    xls_resp = _failing_xls_response([b"partial"], read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = _mock_session_response()
        mock_client.stream.return_value.__enter__.return_value = xls_resp

        with pytest.raises(httpx.ReadError, match="connection reset"):
            download_or_transactions("contributions", dest_dir)

    assert list(dest_dir.glob("*.part")) == []
    assert list(dest_dir.glob("*.xls")) == []


def test_download_rejects_oversized_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest_dir = tmp_path / "downloads"
    monkeypatch.setattr(or_download, "MAX_DOWNLOAD_BYTES", 4)
    xls_resp = _mock_xls_response([b"1234", b"5"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = _mock_session_response()
        mock_client.stream.return_value.__enter__.return_value = xls_resp

        with pytest.raises(ValueError, match="exceeds the allowed size limit"):
            download_or_transactions("contributions", dest_dir)

    assert list(dest_dir.glob("*.part")) == []


def test_download_session_seed_failure_raises(tmp_path: Path) -> None:
    """If the session seed GET fails, the download should propagate the error."""
    dest_dir = tmp_path / "downloads"

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.side_effect = httpx.ConnectError("refused", request=MagicMock())

        with pytest.raises(httpx.ConnectError, match="refused"):
            download_or_transactions("contributions", dest_dir)
