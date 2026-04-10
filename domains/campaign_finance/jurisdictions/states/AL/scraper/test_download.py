"""Tests for AL download module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.AL.scraper.download import (
    build_al_search_url,
    download_al_json,
)


def _mock_api_response(data: list[dict], total_records: int | None = None) -> MagicMock:
    """Build a mock httpx.Response that returns FCPA-shaped JSON."""
    payload = {
        "success": True,
        "totalRecords": total_records if total_records is not None else len(data),
        "data": data,
    }
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


def test_build_al_search_url_contributions() -> None:
    url = build_al_search_url("contributions", page_number=1, page_size=100)
    assert "contributionsearchresults" in url
    assert "pageNumber=1" in url
    assert "pageSize=100" in url
    assert "sortBy=receivedDate" in url


def test_build_al_search_url_expenditures() -> None:
    url = build_al_search_url("expenditures", page_number=2, page_size=500)
    assert "expendituresearchresults" in url
    assert "pageNumber=2" in url
    assert "pageSize=500" in url
    assert "sortBy=expendedDate" in url


def test_build_al_search_url_rejects_unsupported_type() -> None:
    with pytest.raises(ValueError, match="Unsupported AL data type"):
        build_al_search_url("loans")


def test_download_al_json_single_page(tmp_path: Path) -> None:
    """Single-page download: all rows fit in one API response."""
    rows = [{"orgId": "CC1", "amount": "100.00"}]
    mock_response = _mock_api_response(rows, total_records=1)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = mock_response

        result_path = download_al_json("contributions", tmp_path, page_size=100)

    assert result_path == tmp_path / "AL_contributions.json"
    assert result_path.exists()
    saved = json.loads(result_path.read_text())
    assert saved["totalRecords"] == 1
    assert len(saved["data"]) == 1
    assert saved["data"][0]["orgId"] == "CC1"


def test_download_al_json_paginated(tmp_path: Path) -> None:
    """Multi-page download: rows span two API pages."""
    page1_rows = [{"orgId": f"CC{i}"} for i in range(3)]
    page2_rows = [{"orgId": "CC3"}]  # fewer than page_size => last page

    call_count = 0

    def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_api_response(page1_rows, total_records=4)
        return _mock_api_response(page2_rows, total_records=4)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.side_effect = _side_effect

        result_path = download_al_json("expenditures", tmp_path, page_size=3)

    saved = json.loads(result_path.read_text())
    assert saved["totalRecords"] == 4
    assert len(saved["data"]) == 4


def test_download_al_json_max_pages_limits_pagination(tmp_path: Path) -> None:
    """max_pages parameter stops pagination early."""
    rows = [{"orgId": f"CC{i}"} for i in range(50)]
    mock_response = _mock_api_response(rows, total_records=200)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = mock_response

        result_path = download_al_json("contributions", tmp_path, page_size=50, max_pages=1)

    saved = json.loads(result_path.read_text())
    # Only 1 page fetched, so 50 rows even though totalRecords is 200.
    assert len(saved["data"]) == 50


def test_download_al_json_cleans_partial_on_failure(tmp_path: Path) -> None:
    """Partial files are cleaned up on network failure."""
    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.side_effect = httpx.ReadError("connection reset", request=MagicMock())

        with pytest.raises(httpx.ReadError, match="connection reset"):
            download_al_json("contributions", tmp_path)

    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("AL_contributions.json")) == []


def test_download_al_json_rejects_unsuccessful_response(tmp_path: Path) -> None:
    """API responses without success=True raise ValueError."""
    bad_response = MagicMock(spec=httpx.Response)
    bad_response.raise_for_status = MagicMock()
    bad_response.json.return_value = {"success": False, "error": "bad request"}

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = bad_response

        with pytest.raises(ValueError, match="unexpected response"):
            download_al_json("contributions", tmp_path)
