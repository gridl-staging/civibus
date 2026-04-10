from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.FL.scraper import download as fl_download
from domains.campaign_finance.jurisdictions.states.FL.scraper.download import (
    download_fl_candidate_list,
    download_fl_export,
)


def _streaming_response(chunks: list[bytes], *, content_type: str = "text/tab-separated-values") -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": content_type}
    response.iter_bytes.return_value = chunks
    response.read.return_value = b"".join(chunks)
    return response


def _failing_response(chunks: list[bytes], error: httpx.HTTPError) -> MagicMock:
    def _iter_bytes() -> object:
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.headers = {"content-type": "text/tab-separated-values"}
    response.iter_bytes.return_value = _iter_bytes()
    return response


def test_download_fl_export_posts_expected_form_parameters_for_contributions(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    expected_url = "https://example.test/cgi-bin/contrib.exe"
    mock_response = _streaming_response([b"header\tvalue\r\n", b"a\tb\r\n"])

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.FL.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = expected_url
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        export_path = download_fl_export(
            data_type="contributions",
            date_from=date(2024, 7, 10),
            date_to=date(2024, 7, 15),
            dest_dir=destination_dir,
            election="20241105-GEN",
            rowlimit=500,
        )

    assert export_path == destination_dir / "fl_contributions_2024-07-10_2024-07-15.txt"
    assert export_path.read_bytes() == b"header\tvalue\r\na\tb\r\n"
    load_url.assert_called_once_with("contributions")

    stream_call = mock_client.stream.call_args
    assert stream_call.args == ("POST", expected_url)
    assert stream_call.kwargs["follow_redirects"] is True
    assert stream_call.kwargs["data"] == {
        "election": "20241105-GEN",
        "search_on": "4",
        "queryformat": "2",
        "cdatefrom": "07/10/2024",
        "cdateto": "07/15/2024",
        "rowlimit": "500",
    }


def test_download_fl_export_sets_browser_like_user_agent_header(tmp_path: Path) -> None:
    mock_response = _streaming_response([b"header\tvalue\r\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        download_fl_export(
            data_type="other",
            date_from=date(2024, 7, 10),
            date_to=date(2024, 7, 10),
            dest_dir=tmp_path,
            election="20241105-GEN",
            rowlimit=1000,
        )

    stream_call = mock_client.stream.call_args
    assert stream_call.kwargs["headers"]["User-Agent"] == fl_download._FL_USER_AGENT


def test_download_fl_export_rejects_html_error_response_with_http_200(tmp_path: Path) -> None:
    mock_response = _streaming_response([b"<html>Invalid Date Range Entered</html>"], content_type="text/html")

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(ValueError, match="Unexpected FL export Content-Type") as error_info:
            download_fl_export(
                data_type="expenditures",
                date_from=date(2024, 7, 10),
                date_to=date(2024, 7, 10),
                dest_dir=tmp_path,
                election="20241105-GEN",
                rowlimit=1000,
            )
    error_message = str(error_info.value)
    assert "status=200" in error_message
    assert "content_type='text/html'" in error_message
    assert "Invalid Date Range Entered" in error_message


def test_download_fl_export_http_status_error_includes_response_diagnostics(tmp_path: Path) -> None:
    expected_url = "https://example.test/cgi-bin/contrib.exe"
    request = httpx.Request("POST", expected_url)
    status_response = httpx.Response(
        502,
        request=request,
        headers={
            "content-type": "text/html; charset=UTF-8",
            "server": "example-upstream",
            "cf-ray": "abc123",
        },
        content=b"<html><title>Bad gateway</title></html>",
    )

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.FL.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
    ):
        load_url.return_value = expected_url
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = status_response

        with pytest.raises(ValueError, match="FL export request failed") as error_info:
            download_fl_export(
                data_type="contributions",
                date_from=date(2024, 7, 10),
                date_to=date(2024, 7, 10),
                dest_dir=tmp_path,
                election="All",
                rowlimit=1000,
            )

    error_message = str(error_info.value)
    assert expected_url in error_message
    assert "status=502" in error_message
    assert "server='example-upstream'" in error_message
    assert "cf-ray='abc123'" in error_message
    assert "Bad gateway" in error_message


def test_download_fl_export_falls_back_to_browser_session_on_cloudflare_502(tmp_path: Path) -> None:
    expected_url = "https://example.test/cgi-bin/contrib.exe"
    request = httpx.Request("POST", expected_url)
    status_response = httpx.Response(
        502,
        request=request,
        headers={
            "content-type": "text/html; charset=UTF-8",
            "server": "cloudflare",
            "cf-ray": "abc123",
        },
        content=b"<html><title>Bad gateway</title></html>",
    )

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.FL.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
        patch(
            "domains.campaign_finance.jurisdictions.states.FL.scraper.download._download_fl_export_playwright"
        ) as download_playwright,
    ):
        load_url.return_value = expected_url
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = status_response
        download_playwright.side_effect = lambda **kwargs: kwargs["destination_path"].write_bytes(
            b"header\tvalue\r\nbrowser\tfallback\r\n"
        )

        export_path = download_fl_export(
            data_type="contributions",
            date_from=date(2024, 7, 10),
            date_to=date(2024, 7, 10),
            dest_dir=tmp_path,
            election="All",
            rowlimit=1000,
        )

    assert export_path.read_bytes() == b"header\tvalue\r\nbrowser\tfallback\r\n"
    download_playwright.assert_called_once()
    assert download_playwright.call_args.kwargs["data_type"] == "contributions"
    assert download_playwright.call_args.kwargs["form_data"]["cdatefrom"] == "07/10/2024"


def test_download_fl_export_surfaces_when_browser_fallback_is_unavailable(tmp_path: Path) -> None:
    expected_url = "https://example.test/cgi-bin/contrib.exe"
    request = httpx.Request("POST", expected_url)
    status_response = httpx.Response(
        502,
        request=request,
        headers={
            "content-type": "text/html; charset=UTF-8",
            "server": "cloudflare",
            "cf-ray": "abc123",
        },
        content=b"<html><title>Bad gateway</title></html>",
    )

    with (
        patch(
            "domains.campaign_finance.jurisdictions.states.FL.scraper.download._load_bulk_download_url_for_data_type"
        ) as load_url,
        patch("httpx.Client") as mock_client_type,
        patch(
            "domains.campaign_finance.jurisdictions.states.FL.scraper.download._download_fl_export_playwright"
        ) as download_playwright,
    ):
        load_url.return_value = expected_url
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = status_response
        download_playwright.side_effect = RuntimeError("Playwright unavailable")

        with pytest.raises(ValueError, match="browser-session fallback unavailable") as error_info:
            download_fl_export(
                data_type="contributions",
                date_from=date(2024, 7, 10),
                date_to=date(2024, 7, 10),
                dest_dir=tmp_path,
                election="All",
                rowlimit=1000,
            )

    assert "status=502" in str(error_info.value)


def test_download_fl_export_writes_atomically_without_temp_file_residue(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    mock_response = _streaming_response([b"header\tvalue\r\n", b"x\ty\r\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        export_path = download_fl_export(
            data_type="transfers",
            date_from=date(2024, 7, 10),
            date_to=date(2024, 7, 10),
            dest_dir=destination_dir,
            election="20241105-GEN",
            rowlimit=1000,
        )

    assert export_path.exists()
    assert export_path.read_bytes() == b"header\tvalue\r\nx\ty\r\n"
    assert list(destination_dir.glob("*.part")) == []


def test_download_fl_export_cleans_partial_files_on_stream_failure(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("connection reset", request=MagicMock())
    mock_response = _failing_response([b"partial"], read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="connection reset"):
            download_fl_export(
                data_type="contributions",
                date_from=date(2024, 7, 10),
                date_to=date(2024, 7, 10),
                dest_dir=destination_dir,
                election="20241105-GEN",
                rowlimit=1000,
            )

    assert list(destination_dir.glob("*.part")) == []
    assert list(destination_dir.glob("*.txt")) == []


@pytest.mark.parametrize("data_type", ["expenditures", "transfers"])
def test_download_fl_export_rejects_multi_day_windows_for_restricted_data_types(data_type: str, tmp_path: Path) -> None:
    with patch("httpx.Client") as mock_client_type:
        with pytest.raises(ValueError, match="requires single-day date windows"):
            download_fl_export(
                data_type=data_type,
                date_from=date(2024, 7, 10),
                date_to=date(2024, 7, 11),
                dest_dir=tmp_path,
                election="20241105-GEN",
                rowlimit=1000,
            )

    mock_client_type.assert_not_called()


def test_download_fl_export_rejects_negative_rowlimit(tmp_path: Path) -> None:
    with patch("httpx.Client") as mock_client_type:
        with pytest.raises(ValueError, match="rowlimit must be >= 0"):
            download_fl_export(
                data_type="contributions",
                date_from=date(2024, 7, 10),
                date_to=date(2024, 7, 10),
                dest_dir=tmp_path,
                election="20241105-GEN",
                rowlimit=-1,
            )

    mock_client_type.assert_not_called()


def test_download_fl_candidate_list_streams_get_response_to_disk(tmp_path: Path) -> None:
    mock_response = _streaming_response([b"CandidateId\tCandName\r\n", b"1\tDOE, JANE\r\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        output_path = download_fl_candidate_list(dest_dir=tmp_path)

    assert output_path == tmp_path / "fl_candidates_current.txt"
    assert output_path.read_bytes() == b"CandidateId\tCandName\r\n1\tDOE, JANE\r\n"
    stream_call = mock_client.stream.call_args
    assert stream_call.args == ("GET", "https://dos.elections.myflorida.com/candidates/downloadcanlist.asp")
    assert stream_call.kwargs["follow_redirects"] is True
    assert stream_call.kwargs["headers"]["User-Agent"] == fl_download._FL_USER_AGENT


def test_download_fl_candidate_list_rejects_html_content(tmp_path: Path) -> None:
    mock_response = _streaming_response([b"<html>blocked</html>"], content_type="text/html")

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(ValueError, match="Unexpected FL candidate-list Content-Type"):
            download_fl_candidate_list(dest_dir=tmp_path)
