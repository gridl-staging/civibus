from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.IL.scraper import download as il_download
from domains.campaign_finance.jurisdictions.states.IL.scraper.download import (
    _extract_download_link,
    _validate_il_download_link,
    _validate_il_download_page_url,
    download_il_data,
    download_il_data_with_metadata,
    download_il_raw_file,
)

_IL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class _FakeStreamingResponse:
    def __init__(
        self,
        *,
        chunks: list[bytes],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        raise_during_iter: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self._raise_during_iter = raise_during_iter

    def __enter__(self) -> "_FakeStreamingResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "status error",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )

    def iter_bytes(self):  # noqa: ANN201
        for chunk in self._chunks:
            yield chunk
        if self._raise_during_iter is not None:
            raise self._raise_during_iter


class _FakeClient:
    def __init__(self, responses: list[_FakeStreamingResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def stream(self, method: str, url: str, headers: dict[str, str] | None = None):  # noqa: ANN201
        self.calls.append({"method": method, "url": url, "headers": headers})
        return next(self._responses)


def _streaming_response(chunks: list[bytes], *, response_url: str) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    response.url = httpx.URL(response_url)
    response.history = []
    return response


def test_il_config_reports_continuous_update_frequency_for_campaign_finance_sources() -> None:
    config = load_jurisdiction_config(_IL_CONFIG_PATH)

    assert {source.name: source.update_frequency for source in config.data_sources} == {
        "IL SBE Campaign Disclosure — Receipts": "continuous",
        "IL SBE Campaign Disclosure — Expenditures": "continuous",
    }


def test_validate_il_download_page_url_enforces_https_host_and_path() -> None:
    valid_url = "https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx"

    assert _validate_il_download_page_url(valid_url) == valid_url

    with pytest.raises(ValueError, match="must use HTTPS"):
        _validate_il_download_page_url(valid_url.replace("https://", "http://"))

    with pytest.raises(ValueError, match="official Illinois elections host"):
        _validate_il_download_page_url("https://example.com/CampaignDisclosure/DownloadCDDataFiles.aspx")

    with pytest.raises(ValueError, match="bulk-download page path"):
        _validate_il_download_page_url("https://elections.il.gov/CampaignDisclosure/Wrong.aspx")


def test_validate_il_download_link_enforces_new_doc_display_contract() -> None:
    valid_url = "https://elections.il.gov/NewDocDisplay.aspx?abc=123"

    assert _validate_il_download_link(valid_url) == valid_url

    with pytest.raises(ValueError, match="NewDocDisplay.aspx"):
        _validate_il_download_link("https://elections.il.gov/not-download")


def test_extract_download_link_resolves_relative_href() -> None:
    html = '<a id="ContentPlaceHolder1_hypDownloadFile" href="/NewDocDisplay.aspx?abc=123">Download File</a>'

    assert (
        _extract_download_link(
            html,
            page_url="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        )
        == "https://elections.il.gov/NewDocDisplay.aspx?abc=123"
    )


def test_download_il_raw_file_resolves_anchor_and_writes_atomically(tmp_path: Path) -> None:
    with (
        patch("httpx.Client") as mock_client_type,
        patch.object(il_download, "_resolve_download_link") as resolve_download_link,
    ):
        mock_client = mock_client_type.return_value.__enter__.return_value
        stream_response = _streaming_response(
            [b"ID\tCommitteeID\n", b"1\t42\n"],
            response_url="https://elections.il.gov/NewDocDisplay.aspx?abc=123",
        )
        mock_client.stream.return_value.__enter__.return_value = stream_response
        resolve_download_link.return_value = "https://elections.il.gov/NewDocDisplay.aspx?abc=123"

        output_path = download_il_raw_file("Receipts.txt", dest_dir=tmp_path)

    assert output_path == tmp_path / "Receipts.txt"
    assert output_path.read_text(encoding="utf-8") == "ID\tCommitteeID\n1\t42\n"


def test_download_il_data_maps_supported_types() -> None:
    with patch(
        "domains.campaign_finance.jurisdictions.states.IL.scraper.download.download_il_data_with_metadata"
    ) as raw_file_download:
        raw_file_download.return_value = il_download.ILDownloadResult(
            path=Path("/tmp/Receipts.txt"),
            bytes_written=24,
            data_rows_written=None,
            truncated=False,
        )

        output_path = download_il_data("contributions", dest_dir=Path("/tmp"))

    assert output_path == Path("/tmp/Receipts.txt")
    raw_file_download.assert_called_once()


def test_download_il_data_rejects_unsupported_type() -> None:
    with pytest.raises(ValueError, match="Unsupported IL data type"):
        download_il_data("committees", dest_dir=Path("/tmp"))


def test_download_il_raw_file_uses_unbounded_read_timeout_for_large_bulk_streams(tmp_path: Path) -> None:
    with (
        patch("httpx.Client") as mock_client_type,
        patch.object(il_download, "_resolve_download_link") as resolve_download_link,
    ):
        mock_client = mock_client_type.return_value.__enter__.return_value
        stream_response = _streaming_response(
            [b"ID\tCommitteeID\n", b"1\t42\n"],
            response_url="https://elections.il.gov/NewDocDisplay.aspx?abc=123",
        )
        mock_client.stream.return_value.__enter__.return_value = stream_response
        resolve_download_link.return_value = "https://elections.il.gov/NewDocDisplay.aspx?abc=123"

        download_il_raw_file("Receipts.txt", dest_dir=tmp_path)

    _, client_kwargs = mock_client_type.call_args
    timeout = client_kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == il_download.REQUEST_TIMEOUT_SECONDS
    assert timeout.read is None

    with pytest.raises(ValueError, match="official IL raw file name"):
        download_il_raw_file("../Receipts.txt", dest_dir=tmp_path)


def test_download_il_raw_file_retries_insecure_tls_only_with_break_glass(monkeypatch: pytest.MonkeyPatch) -> None:
    call_verify_values: list[bool] = []
    ssl_error = httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=MagicMock())

    def fake_download_once(
        file_name: str,
        *,
        dest_dir: Path,
        page_url: str,
        verify_certificates: bool,
        max_data_rows: int | None = None,
        tail_data_rows: int | None = None,
    ) -> il_download.ILDownloadResult:
        del file_name, dest_dir, page_url, max_data_rows, tail_data_rows
        call_verify_values.append(verify_certificates)
        if verify_certificates:
            raise ssl_error
        return il_download.ILDownloadResult(
            path=Path("/tmp/Receipts.txt"),
            bytes_written=12,
            data_rows_written=None,
            truncated=False,
        )

    monkeypatch.setenv("CIVIBUS_ALLOW_INSECURE_TLS_RETRY", "1")
    monkeypatch.setattr(il_download, "_download_il_raw_file_once", fake_download_once)

    output_path = download_il_raw_file("Receipts.txt", dest_dir=Path("/tmp"), allow_insecure_tls=True)

    assert output_path == Path("/tmp/Receipts.txt")
    assert call_verify_values == [True, False]


def test_download_il_raw_file_with_metadata_retries_incomplete_chunked_read(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0
    remote_protocol_error = httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body (incomplete chunked read)"
    )

    def fake_download_once(
        file_name: str,
        *,
        dest_dir: Path,
        page_url: str,
        verify_certificates: bool,
        max_data_rows: int | None = None,
        tail_data_rows: int | None = None,
    ) -> il_download.ILDownloadResult:
        del file_name, dest_dir, page_url, verify_certificates, max_data_rows, tail_data_rows
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise remote_protocol_error
        return il_download.ILDownloadResult(
            path=Path("/tmp/Receipts.txt"),
            bytes_written=12,
            data_rows_written=None,
            truncated=False,
        )

    monkeypatch.setattr(il_download, "_download_il_raw_file_once", fake_download_once)

    result = il_download.download_il_raw_file_with_metadata("Receipts.txt", dest_dir=Path("/tmp"))

    assert result.path == Path("/tmp/Receipts.txt")
    assert call_count == 2


def test_download_il_data_with_metadata_stops_on_complete_row_boundaries(tmp_path: Path) -> None:
    with (
        patch("httpx.Client") as mock_client_type,
        patch.object(il_download, "_resolve_download_link") as resolve_download_link,
    ):
        mock_client = mock_client_type.return_value.__enter__.return_value
        stream_response = _streaming_response(
            [
                b"ID\tCommitteeID\n1\t42",
                b"\n2\t84\n3\t126",
            ],
            response_url="https://elections.il.gov/NewDocDisplay.aspx?abc=123",
        )
        mock_client.stream.return_value.__enter__.return_value = stream_response
        resolve_download_link.return_value = "https://elections.il.gov/NewDocDisplay.aspx?abc=123"

        result = download_il_data_with_metadata("contributions", dest_dir=tmp_path, max_data_rows=2)

    assert result.path == tmp_path / "Receipts.txt"
    assert result.path.read_text(encoding="utf-8") == "ID\tCommitteeID\n1\t42\n2\t84\n"
    assert result.bytes_written == len("ID\tCommitteeID\n1\t42\n2\t84\n".encode("utf-8"))
    assert result.data_rows_written == 2
    assert result.truncated is True


def test_download_il_data_with_metadata_keeps_trailing_rows_on_complete_boundaries(tmp_path: Path) -> None:
    with (
        patch("httpx.Client") as mock_client_type,
        patch.object(il_download, "_resolve_download_link") as resolve_download_link,
    ):
        mock_client = mock_client_type.return_value.__enter__.return_value
        stream_response = _streaming_response(
            [
                b"ID\tCommitteeID\n1\t42\n2\t84",
                b"\n3\t126\n4\t168",
            ],
            response_url="https://elections.il.gov/NewDocDisplay.aspx?abc=123",
        )
        mock_client.stream.return_value.__enter__.return_value = stream_response
        resolve_download_link.return_value = "https://elections.il.gov/NewDocDisplay.aspx?abc=123"

        result = download_il_data_with_metadata("contributions", dest_dir=tmp_path, tail_data_rows=2)

    assert result.path == tmp_path / "Receipts.txt"
    assert result.path.read_text(encoding="utf-8") == "ID\tCommitteeID\n3\t126\n4\t168"
    assert result.bytes_written == len("ID\tCommitteeID\n3\t126\n4\t168".encode("utf-8"))
    assert result.data_rows_written == 2
    assert result.truncated is True


def test_download_il_data_with_metadata_rejects_conflicting_row_limit_modes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Choose either max_data_rows or tail_data_rows"):
        download_il_data_with_metadata(
            "contributions",
            dest_dir=tmp_path,
            max_data_rows=2,
            tail_data_rows=2,
        )


def test_stream_download_to_path_resumes_after_incomplete_chunked_read(tmp_path: Path) -> None:
    destination_path = tmp_path / "Receipts.txt"
    partial_stream_error = httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body (incomplete chunked read)"
    )
    fake_client = _FakeClient(
        [
            _FakeStreamingResponse(chunks=[b"ID\tCommitteeID\n", b"1\t42\n"], raise_during_iter=partial_stream_error),
            _FakeStreamingResponse(
                chunks=[b"2\t84\n"],
                status_code=206,
                headers={"Content-Range": "bytes 20-25/26"},
            ),
        ]
    )

    result = il_download._stream_download_to_path(
        fake_client,
        "https://elections.il.gov/NewDocDisplay.aspx?abc=123",
        destination_path,
    )

    assert result.path == destination_path
    assert result.bytes_written == len("ID\tCommitteeID\n1\t42\n2\t84\n".encode("utf-8"))
    assert destination_path.read_text(encoding="utf-8") == "ID\tCommitteeID\n1\t42\n2\t84\n"
    assert fake_client.calls[0]["headers"] is None
    assert fake_client.calls[1]["headers"] == {"Range": "bytes=20-"}
