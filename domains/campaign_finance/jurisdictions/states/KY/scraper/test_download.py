from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.KY.scraper import download as ky_download
from domains.campaign_finance.jurisdictions.states.KY.scraper.download import download_ky_csv


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


def test_download_ky_csv_builds_correct_export_url(tmp_path: Path) -> None:
    """Contributions must use the transaction export endpoint, not ExportSearch."""
    destination_dir = tmp_path / "downloads"
    mock_response = _streaming_response([b"csv-bytes"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        csv_path = download_ky_csv(
            "contributions",
            dest_dir=destination_dir,
            election_date="5/19/2026",
        )

    assert csv_path == destination_dir / "KY_contributions.csv"
    call_args = mock_client.stream.call_args
    assert call_args[0][0] == "GET"
    called_url = call_args[0][1]
    assert "ExportContributors" in called_url
    assert "ContributionSearchType=All" in called_url
    assert "ElectionDate=05%2F19%2F2026+00%3A00%3A00" in called_url


def test_download_ky_csv_streams_to_disk(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    mock_response = _streaming_response([b"header,row\n", b"data,values\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        csv_path = download_ky_csv(
            "expenditures",
            dest_dir=destination_dir,
            election_date="5/19/2026",
        )

    assert csv_path == destination_dir / "KY_expenditures.csv"
    assert csv_path.read_bytes() == b"header,row\ndata,values\n"
    called_url = mock_client.stream.call_args[0][1]
    assert "Export?" in called_url
    assert "ExportSearch" not in called_url


def test_download_ky_csv_cleans_partial_files_on_failure(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("connection reset", request=MagicMock())
    mock_response = _failing_response([b"partial"], read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="connection reset"):
            download_ky_csv(
                "contributions",
                dest_dir=destination_dir,
                election_date="5/19/2026",
            )

    assert list(destination_dir.glob("*.part")) == []
    assert list(destination_dir.glob("KY_contributions.csv")) == []


def test_download_ky_csv_rejects_oversized_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination_dir = tmp_path / "downloads"
    monkeypatch.setattr(ky_download, "MAX_DOWNLOAD_BYTES", 4)
    mock_response = _streaming_response([b"1234", b"5"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(ValueError, match="exceeds the allowed size limit"):
            download_ky_csv(
                "contributions",
                dest_dir=destination_dir,
                election_date="5/19/2026",
            )

    assert list(destination_dir.glob("*.part")) == []


def test_download_ky_csv_defaults_election_date_to_none_for_all_results(tmp_path: Path) -> None:
    """When no election_date is passed, the export URL should omit ElectionDate param."""
    destination_dir = tmp_path / "downloads"
    mock_response = _streaming_response([b"csv-data"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        download_ky_csv("contributions", dest_dir=destination_dir)

    call_args = mock_client.stream.call_args
    called_url = call_args[0][1]
    assert "ExportContributors" in called_url
    assert "ElectionDate" not in called_url
