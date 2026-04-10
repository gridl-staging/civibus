from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.OH.scraper import download as oh_download
from domains.campaign_finance.jurisdictions.states.OH.scraper.download import download_oh_csv

_LISTING_TEMPLATE = "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:0::NO:RP:P73_TYPE:{TYPE}:"
_LISTING_URL_CAN = "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:0::NO:RP:P73_TYPE:CAN:"


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


def _listing_response(*, status_code: int = 200, text: str = "", url: str = _LISTING_URL_CAN) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status_code=status_code, request=request, text=text)


def _upstream_blocker_error(*, status_code: int = 403, text: str = "Maintenance response") -> httpx.HTTPStatusError:
    response = _listing_response(status_code=status_code, text=text)
    return httpx.HTTPStatusError(
        f"Client error '{status_code} Forbidden' for url '{response.request.url}'",
        request=response.request,
        response=response,
    )


def test_scrape_apex_listing_resolves_config_url_and_extracts_csv_hrefs() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr><td><a href="r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV">CON</a></td></tr>
          <tr><td><a href="/ords/r/cfdisclosure/files/static/v5/CAC_EXP_2022.CSV">EXP</a></td></tr>
          <tr><td><a href="/ords/r/cfdisclosure/files/static/v5/readme.txt">TXT</a></td></tr>
        </table>
      </body>
    </html>
    """
    response = _listing_response(text=html)

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = _LISTING_TEMPLATE
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = response

        hrefs = oh_download._scrape_apex_file_listing("CAN", data_type="contributions")

    assert hrefs == [
        "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV",
        "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_EXP_2022.CSV",
    ]
    load_url.assert_called_once_with("contributions")
    mock_client.get.assert_called_once_with(_LISTING_URL_CAN, follow_redirects=True)


def test_scrape_apex_listing_rejects_external_csv_hosts() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr><td><a href="https://evil.example/CAC_CON_2022.CSV">CON</a></td></tr>
        </table>
      </body>
    </html>
    """
    response = _listing_response(text=html)

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = _LISTING_TEMPLATE
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = response

        with pytest.raises(ValueError, match="approved Ohio SOS host"):
            oh_download._scrape_apex_file_listing("CAN", data_type="contributions")


def test_scrape_apex_listing_classifies_403_as_upstream_http_failure() -> None:
    response = _listing_response(status_code=403, text="<html><body>Maintenance</body></html>")

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = _LISTING_TEMPLATE
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = response

        with pytest.raises(httpx.HTTPStatusError, match="403") as exc_info:
            oh_download._scrape_apex_file_listing("CAN", data_type="contributions")

    assert "No OH CSV download links found" not in str(exc_info.value)
    load_url.assert_called_once_with("contributions")
    mock_client.get.assert_called_once_with(_LISTING_URL_CAN, follow_redirects=True)


def test_scrape_apex_listing_errors_when_no_csv_links_present() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr><td><a href="/ords/r/cfdisclosure/files/static/v5/readme.txt">TXT</a></td></tr>
        </table>
      </body>
    </html>
    """
    response = _listing_response(text=html)

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = _LISTING_TEMPLATE
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.get.return_value = response

        with pytest.raises(ValueError, match="No OH CSV download links found"):
            oh_download._scrape_apex_file_listing("CAN", data_type="contributions")


def test_normalize_committee_type_rejects_unsupported_values() -> None:
    with pytest.raises(ValueError, match="Unsupported OH committee type: lobby"):
        oh_download._normalize_committee_type("lobby")


def test_validate_oh_download_url_requires_https_scheme() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        oh_download._validate_oh_download_url(
            "http://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV",
            context="OH file URL",
        )


def test_match_file_url_selects_expected_data_type_and_year() -> None:
    hrefs = [
        "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/ALL_CAN_CON_2009.CSV",
        "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV",
        "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_EXP_2022.CSV",
    ]

    assert oh_download._match_file_url(hrefs, data_type="contributions", year=2022).endswith("CAC_CON_2022.CSV")
    assert oh_download._match_file_url(hrefs, data_type="expenditures", year=2022).endswith("CAC_EXP_2022.CSV")
    assert oh_download._match_file_url(hrefs, data_type="contributions", year=2009).endswith("ALL_CAN_CON_2009.CSV")


def test_match_file_url_reports_expected_suffix_and_count_for_mismatch() -> None:
    with pytest.raises(ValueError, match="'_CON_2024.CSV' but found 0"):
        oh_download._match_file_url(
            ["https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV"],
            data_type="contributions",
            year=2024,
        )

    with pytest.raises(ValueError, match="'_CON_2022.CSV' but found 2"):
        oh_download._match_file_url(
            [
                "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV",
                "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/PAC_CON_2022.CSV",
            ],
            data_type="contributions",
            year=2022,
        )


def test_match_file_url_rejects_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported OH data type: receipts"):
        oh_download._match_file_url(
            ["https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV"],
            data_type="receipts",
            year=2022,
        )


def test_download_oh_csv_streams_selected_file_and_returns_path(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    selected_url = "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV"

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._scrape_apex_file_listing"
        ) as scrape_listing,
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._stream_download_to_path"
        ) as stream_download,
    ):
        scrape_listing.return_value = [selected_url]

        path = download_oh_csv("contributions", "CAN", 2022, destination_dir)

    assert path == destination_dir / "CAC_CON_2022.CSV"
    scrape_listing.assert_called_once_with("CAN", data_type="contributions")
    stream_download.assert_called_once_with(selected_url, path)


def test_download_oh_csv_propagates_listing_upstream_http_failure(tmp_path: Path) -> None:
    blocker = _upstream_blocker_error()
    destination_dir = tmp_path / "downloads"

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.OH.scraper.download._scrape_apex_file_listing",
            side_effect=blocker,
        ) as scrape_listing,
        patch("domains.campaign_finance.jurisdictions.states.OH.scraper.download._match_file_url") as match_file_url,
        patch("domains.campaign_finance.jurisdictions.states.OH.scraper.download._stream_download_to_path") as stream,
    ):
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            download_oh_csv("contributions", "CAN", 2022, destination_dir)

    assert exc_info.value is blocker
    scrape_listing.assert_called_once_with("CAN", data_type="contributions")
    match_file_url.assert_not_called()
    stream.assert_not_called()


def test_stream_download_writes_atomically_without_temp_file_residue(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "CAC_CON_2022.CSV"
    mock_response = _streaming_response([b"part1", b"part2"])
    mock_response.url = httpx.URL("https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV")

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        oh_download._stream_download_to_path(
            "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV",
            destination_path,
        )

    assert destination_path.exists()
    assert destination_path.read_bytes() == b"part1part2"
    assert list(destination_path.parent.glob("*.part")) == []


def test_stream_download_cleans_partial_files_on_http_failure(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "PAC_EXP_2022.CSV"
    read_error = httpx.ReadError("connection reset", request=MagicMock())
    mock_response = _failing_response([b"partial"], read_error)
    mock_response.url = httpx.URL("https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/PAC_EXP_2022.CSV")

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="connection reset"):
            oh_download._stream_download_to_path(
                "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/PAC_EXP_2022.CSV",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("PAC_EXP_2022.CSV")) == []


def test_stream_download_rejects_oversized_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination_path = tmp_path / "downloads" / "PPC_CON_2022.CSV"
    monkeypatch.setattr(oh_download, "MAX_DOWNLOAD_BYTES", 4)
    mock_response = _streaming_response([b"1234", b"5"])
    mock_response.url = httpx.URL("https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/PPC_CON_2022.CSV")

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(ValueError, match="exceeds the allowed size limit"):
            oh_download._stream_download_to_path(
                "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/PPC_CON_2022.CSV",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("PPC_CON_2022.CSV")) == []


def test_stream_download_rejects_redirect_to_external_host(tmp_path: Path) -> None:
    destination_path = tmp_path / "downloads" / "CAC_CON_2022.CSV"
    mock_response = _streaming_response([b"part1"])
    mock_response.url = httpx.URL("https://evil.example/CAC_CON_2022.CSV")

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(ValueError, match="approved Ohio SOS host"):
            oh_download._stream_download_to_path(
                "https://www6.ohiosos.gov/ords/r/cfdisclosure/files/static/v5/CAC_CON_2022.CSV",
                destination_path,
            )

    assert list(destination_path.parent.glob("*.part")) == []
    assert list(destination_path.parent.glob("CAC_CON_2022.CSV")) == []
