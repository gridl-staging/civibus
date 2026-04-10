from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.IN.scraper import download as in_download
from domains.campaign_finance.jurisdictions.states.IN.scraper.download import (
    _validate_in_download_url,
    download_in_data,
)


def _streaming_response(chunks: list[bytes], *, response_url: str) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    response.url = httpx.URL(response_url)
    response.history = []
    return response


def _failing_response(chunks: list[bytes], error: httpx.HTTPError, *, response_url: str) -> MagicMock:
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


def test_validate_in_download_url_enforces_https_and_indiana_host() -> None:
    valid_url = "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip"

    assert _validate_in_download_url(valid_url, context="IN file URL") == valid_url

    with pytest.raises(ValueError, match="must use HTTPS"):
        _validate_in_download_url(valid_url.replace("https://", "http://"), context="IN file URL")

    with pytest.raises(ValueError, match="approved Indiana campaign-finance host"):
        _validate_in_download_url(
            "https://evil.example/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
            context="IN file URL",
        )


def test_validate_in_download_url_rejects_same_host_non_bulk_paths() -> None:
    with pytest.raises(ValueError, match="Indiana bulk-download path"):
        _validate_in_download_url(
            "https://campaignfinance.in.gov/not-the-bulk-area/2025_ContributionData.csv.zip",
            context="IN file URL",
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/../secret.csv.zip",
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/%2e%2e/secret.csv.zip",
    ],
)
def test_validate_in_download_url_rejects_bulk_path_traversal(url: str) -> None:
    with pytest.raises(ValueError, match="Indiana bulk-download path"):
        _validate_in_download_url(url, context="IN file URL")


def test_download_in_data_uses_data_type_url_resolution_and_year_substitution(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    template_url = "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/{YEAR}_ContributionData.csv.zip"

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.IN.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("domains.campaign_finance.jurisdictions.states.IN.scraper.download._stream_download_to_path") as stream,
    ):
        load_url.return_value = template_url
        archive_path = download_in_data(year=2025, data_type="contributions", dest_dir=destination_dir)

    expected_path = destination_dir / "2025_ContributionData.csv.zip"
    assert archive_path == expected_path
    load_url.assert_called_once_with("contributions")
    stream.assert_called_once_with(
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
        expected_path,
    )


def test_download_in_data_uses_default_direct_get_bulk_url_shape(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"

    with patch("domains.campaign_finance.jurisdictions.states.IN.scraper.download._stream_download_to_path") as stream:
        archive_path = download_in_data(year=2026, data_type="expenditures", dest_dir=destination_dir)

    expected_path = destination_dir / "2026_ExpenditureData.csv.zip"
    assert archive_path == expected_path
    stream.assert_called_once_with(
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2026_ExpenditureData.csv.zip",
        expected_path,
    )


def test_stream_download_to_path_writes_atomically_without_temp_file_residue(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    response = _streaming_response(
        [b"PK", b"\x03\x04zipcontent"],
        response_url="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        in_download._stream_download_to_path(
            "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
            destination_path,
        )

    assert destination_path.exists()
    assert destination_path.read_bytes() == b"PK\x03\x04zipcontent"
    assert list(destination_path.parent.glob("*.part")) == []


def test_stream_download_to_path_uses_browser_like_default_headers(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    response = _streaming_response(
        [b"payload"],
        response_url="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        in_download._stream_download_to_path(
            "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
            destination_path,
        )

    _, client_kwargs = mock_client_type.call_args
    assert client_kwargs["timeout"] == in_download.REQUEST_TIMEOUT_SECONDS
    assert client_kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")


def test_stream_download_to_path_cleans_partial_files_on_failure(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    read_error = httpx.ReadError("connection reset", request=MagicMock())
    response = _failing_response(
        [b"partial"],
        read_error,
        response_url="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(httpx.ReadError, match="connection reset"):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []


def test_stream_download_to_path_rejects_oversized_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    monkeypatch.setattr(in_download, "MAX_DOWNLOAD_BYTES", 4)
    response = _streaming_response(
        [b"1234", b"5"],
        response_url="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(ValueError, match="exceeds the allowed size limit"):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []


def test_stream_download_to_path_rejects_redirect_to_external_host(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    response = _streaming_response(
        [b"payload"],
        response_url="https://evil.example/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(ValueError, match="approved Indiana campaign-finance host"):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []


@pytest.mark.parametrize(
    "redirect_history_url, error_pattern",
    [
        (
            "https://evil.example/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
            "approved Indiana campaign-finance host",
        ),
        (
            "https://campaignfinance.in.gov/not-the-bulk-area/2025_ContributionData.csv.zip",
            "Indiana bulk-download path",
        ),
    ],
)
def test_stream_download_to_path_rejects_invalid_redirect_hops(
    tmp_path: Path, redirect_history_url: str, error_pattern: str
) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    response = _streaming_response(
        [b"payload"],
        response_url="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )
    response.history = [_redirect_response(redirect_history_url)]

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(ValueError, match=error_pattern):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []


def test_stream_download_to_path_rejects_redirect_to_same_host_non_bulk_path(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    response = _streaming_response(
        [b"payload"],
        response_url="https://campaignfinance.in.gov/not-the-bulk-area/2025_ContributionData.csv.zip",
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(ValueError, match="Indiana bulk-download path"):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []


@pytest.mark.parametrize(
    "response_url",
    [
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/../secret.csv.zip",
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/%2e%2e/secret.csv.zip",
    ],
)
def test_stream_download_to_path_rejects_redirect_with_bulk_path_traversal(tmp_path: Path, response_url: str) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    response = _streaming_response([b"payload"], response_url=response_url)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(ValueError, match="Indiana bulk-download path"):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []


def test_stream_download_to_path_propagates_http_status_errors(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "2025_ContributionData.csv.zip"
    request = httpx.Request(
        "GET", "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip"
    )
    response = _streaming_response(
        [b"payload"],
        response_url="https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
    )
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error",
        request=request,
        response=httpx.Response(500, request=request),
    )

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = response

        with pytest.raises(httpx.HTTPStatusError, match="server error"):
            in_download._stream_download_to_path(
                "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/2025_ContributionData.csv.zip",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("*.zip")) == []
