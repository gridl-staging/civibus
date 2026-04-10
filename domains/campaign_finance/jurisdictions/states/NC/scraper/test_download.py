from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.NC.scraper import (
    _CONFIG_PATH as _NC_CONFIG_PATH,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    BrowserAutomationRequiredError,
    TransactionSearchCriteria,
    _NC_PORTAL_BASE,
    _TXN_EXPORT_URL,
    _TXN_RESULTS_URL,
    _TXN_SEARCH_URL,
    _build_committee_export_url,
    _build_transaction_search_form,
    _extract_transaction_export_params,
    _is_csv_response,
    _stream_response_to_path,
    download_committee_document_export,
    download_transaction_export,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
TXN_RESULTS_FIXTURE = FIXTURE_DIR / "txn_search_results_sample.html"


class TestExtractTransactionExportParams:
    def test_extracts_params_json_from_results_page(self):
        html = TXN_RESULTS_FIXTURE.read_text()
        params = _extract_transaction_export_params(html)
        parsed = json.loads(params)
        assert parsed["LastName"] == "ADAMS"
        assert parsed["DateFrom"] == "01/01/2026"
        assert parsed["DateTo"] == "03/14/2026"
        assert parsed["Page"] == 0
        assert parsed["Debug"] is False

    def test_raises_value_error_when_params_payload_missing(self):
        html = "<html><body><p>No params here</p></body></html>"
        with pytest.raises(ValueError, match="Params"):
            _extract_transaction_export_params(html)

    def test_raises_value_error_for_empty_html(self):
        with pytest.raises(ValueError, match="Params"):
            _extract_transaction_export_params("")


_EXPECTED_FORM_KEYS = {
    "SelectedTransType",
    "LastName",
    "FirstName",
    "OrgName",
    "IsOrg",
    "CommText",
    "CommName",
    "CommID",
    "DateFrom",
    "DateTo",
    "AmountFrom",
    "AmountTo",
    "SelectedCounty",
    "SelectedCityLetter",
    "SelectedCity",
    "UseCity",
}


class TestBuildTransactionSearchForm:
    def test_emits_exact_portal_form_keys(self):
        form = _build_transaction_search_form(TransactionSearchCriteria(last_name="ADAMS"))
        assert set(form.keys()) == _EXPECTED_FORM_KEYS

    def test_no_duplicate_keys(self):
        form = _build_transaction_search_form(TransactionSearchCriteria(last_name="ADAMS"))
        assert len(form) == len(_EXPECTED_FORM_KEYS)

    def test_booleans_normalized_to_strings(self):
        form = _build_transaction_search_form(TransactionSearchCriteria(last_name="ADAMS", is_org=True))
        assert form["IsOrg"] == "true"

    def test_booleans_default_to_false_string(self):
        form = _build_transaction_search_form(TransactionSearchCriteria(last_name="ADAMS"))
        assert form["IsOrg"] == "false"
        assert form["UseCity"] == "false"

    def test_blank_optionals_are_empty_strings(self):
        form = _build_transaction_search_form(TransactionSearchCriteria(last_name="ADAMS"))
        assert form["SelectedTransType"] == ""
        assert form["AmountFrom"] == ""
        assert form["AmountTo"] == ""
        assert form["SelectedCounty"] == ""

    def test_provided_values_populate_form(self):
        form = _build_transaction_search_form(
            TransactionSearchCriteria(
                last_name="ADAMS",
                date_from="01/01/2026",
                date_to="03/14/2026",
                org_name="SOME ORG",
            )
        )
        assert form["LastName"] == "ADAMS"
        assert form["DateFrom"] == "01/01/2026"
        assert form["DateTo"] == "03/14/2026"
        assert form["OrgName"] == "SOME ORG"


class TestCsvResponseGuards:
    def test_is_csv_response_accepts_content_disposition_filename(self):
        response = MagicMock(spec=httpx.Response)
        response.headers = {"content-disposition": 'attachment; filename="committee_docs.csv"'}
        assert _is_csv_response(response) is True

    def test_is_csv_response_accepts_excel_download_content_type(self):
        response = MagicMock(spec=httpx.Response)
        response.headers = {"content-type": "application/vnd.ms-excel"}
        assert _is_csv_response(response) is True


def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.iter_bytes.return_value = chunks
    response.content = b"".join(chunks)
    response.headers = {"content-type": "text/csv"}
    return response


def _make_failing_streaming_response(chunks: list[bytes], error: Exception) -> MagicMock:
    def iter_bytes():
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.iter_bytes.return_value = iter_bytes()
    response.content = b"".join(chunks)
    response.headers = {"content-type": "text/csv"}
    return response


@contextmanager
def _patched_httpx_client(
    *,
    get_response: MagicMock | None = None,
    post_responses: list[MagicMock] | None = None,
    post_response: MagicMock | None = None,
) -> Iterator[MagicMock]:
    with patch("domains.campaign_finance.jurisdictions.states.NC.scraper.download.httpx.Client") as mock_client_cls:
        client = mock_client_cls.return_value.__enter__.return_value
        if get_response is not None:
            client.get.return_value = get_response
        if post_responses is not None:
            client.post.side_effect = post_responses
        elif post_response is not None:
            client.post.return_value = post_response
        yield client


class TestStreamResponseToPath:
    def test_writes_response_to_destination(self, tmp_path: Path):
        dest = tmp_path / "output.csv"
        response = _make_streaming_response([b"col1,col2\n", b"a,b\n"])
        _stream_response_to_path(response, dest)
        assert dest.read_bytes() == b"col1,col2\na,b\n"

    def test_uses_part_file_during_download(self, tmp_path: Path):
        dest = tmp_path / "output.csv"

        def tracking_iter_bytes():
            yield b"chunk1"
            temp_dirs = list(tmp_path.glob(".output.csv.*"))
            assert len(temp_dirs) == 1, "secure temp directory should exist during streaming"
            assert (temp_dirs[0] / "output.csv").exists(), "temporary output file should exist during streaming"
            assert not dest.exists(), "final file should not exist during streaming"
            yield b"chunk2"

        response = MagicMock(spec=httpx.Response)
        response.iter_bytes.return_value = tracking_iter_bytes()
        response.headers = {"content-type": "text/csv"}

        _stream_response_to_path(response, dest)
        assert dest.exists()
        assert not list(tmp_path.glob(".output.csv.*"))

    def test_removes_part_file_on_failure(self, tmp_path: Path):
        dest = tmp_path / "output.csv"
        error = httpx.ReadError("stream interrupted", request=MagicMock())
        response = _make_failing_streaming_response([b"partial"], error)

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            _stream_response_to_path(response, dest)

        assert not list(tmp_path.glob(".output.csv.*"))
        assert not dest.exists()

    def test_ignores_predictable_legacy_part_symlink(self, tmp_path: Path):
        dest = tmp_path / "output.csv"
        legacy_part_path = tmp_path / "output.csv.part"
        sentinel = tmp_path / "sentinel.txt"
        sentinel.write_text("protected", encoding="utf-8")
        legacy_part_path.symlink_to(sentinel)

        response = _make_streaming_response([b"secure,data\n"])

        _stream_response_to_path(response, dest)

        assert dest.read_bytes() == b"secure,data\n"
        assert sentinel.read_text(encoding="utf-8") == "protected"


_SAMPLE_PARAMS_JSON = (
    '{"ReceiptType":"","ExpenditureType":"","CommitteeType":"",'
    '"PartyType":"","OfficeType":"","CommitteeIDs":null,'
    '"CommitteeName":"","Cities":"","Counties":"","State":"",'
    '"ZipCodes":"","DateFrom":"01/01/2026","DateTo":"03/14/2026",'
    '"OrganizationName":"","FirstName":"","LastName":"ADAMS",'
    '"NameSoundsLike":false,"NameIsOrg":false,"Purpose":"",'
    '"AmountFrom":"","AmountTo":"","JobProfession":"",'
    '"JobProfSoundsLike":false,"Employer":"","EmployerSoundsLike":false,'
    '"PaymentType":"","Page":0,"Debug":false}'
)


def _build_results_html_with_params(params_json: str) -> str:
    return (
        "<html><script>"
        """$('input[name="Params"]').val('"""
        + params_json
        + """');$('input[name="Params"]').closest("form").submit();"""
        "</script></html>"
    )


class TestDownloadTransactionExport:
    def test_performs_three_step_session_flow(self, tmp_path: Path):
        dest = tmp_path / "transactions.csv"
        results_html = _build_results_html_with_params(_SAMPLE_PARAMS_JSON)
        csv_content = b"Name,Amount\nADAMS,100.00\n"

        search_response = MagicMock(spec=httpx.Response)
        search_response.text = results_html
        search_response.raise_for_status = MagicMock()

        export_response = _make_streaming_response([csv_content])
        export_response.raise_for_status = MagicMock()

        with _patched_httpx_client(
            get_response=MagicMock(spec=httpx.Response, raise_for_status=MagicMock()),
            post_responses=[search_response, export_response],
        ) as client:
            criteria = TransactionSearchCriteria(
                last_name="ADAMS",
                date_from="01/01/2026",
                date_to="03/14/2026",
            )
            expected_form = _build_transaction_search_form(criteria)
            download_transaction_export(criteria, dest)

        assert dest.read_bytes() == csv_content

        # Verify the 3-step flow
        client.get.assert_called_once()
        get_url = client.get.call_args[0][0]
        assert "/CFTxnLkup/" in get_url

        assert client.post.call_count == 2
        search_post_url = client.post.call_args_list[0][0][0]
        assert "/CFTxnLkup/TxnSearchResults/" in search_post_url
        assert client.post.call_args_list[0][1]["data"] == expected_form

        export_post_url = client.post.call_args_list[1][0][0]
        assert "/CFTxnLkup/ExportResults/" in export_post_url

        # Verify Params was posted
        export_post_data = client.post.call_args_list[1][1].get("data", {})
        assert "Params" in export_post_data


@pytest.mark.integration
class TestTransactionExportIntegration:
    def test_live_transaction_export_raises_browser_automation_required(self, tmp_path: Path):
        dest = tmp_path / "transinq_results.csv"
        criteria = TransactionSearchCriteria(
            last_name="ADAMS",
            date_from="01/01/2026",
            date_to="03/14/2026",
        )
        try:
            with pytest.raises(BrowserAutomationRequiredError):
                download_transaction_export(criteria, dest)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            pytest.skip(f"NC portal unavailable: {exc}")


class TestBuildCommitteeExportUrl:
    def test_emits_documented_url_contract(self):
        url = _build_committee_export_url("12345", "ADAMS FOR NC HOUSE")
        assert url == (
            "https://cf.ncsbe.gov/CFOrgLkup/ExportSearchResults/?OGID=12345&Title=ADAMS+FOR+NC+HOUSE&Type=DocGen"
        )

    def test_strips_surrounding_whitespace_from_org_group_id(self):
        url = _build_committee_export_url(" 12345 ", "ADAMS FOR NC HOUSE")
        assert "OGID=12345" in url
        assert "OGID=+12345+" not in url

    def test_url_encodes_title_with_special_characters(self):
        url = _build_committee_export_url("99", "NAME (WITH PARENS)")
        assert "Title=NAME+%28WITH+PARENS%29" in url

    def test_rejects_blank_org_group_id(self):
        with pytest.raises(ValueError, match="org_group_id"):
            _build_committee_export_url("", "SOME TITLE")

    def test_rejects_whitespace_only_org_group_id(self):
        with pytest.raises(ValueError, match="org_group_id"):
            _build_committee_export_url("   ", "SOME TITLE")


class TestDownloadCommitteeDocumentExport:
    def test_downloads_csv_using_committee_export_url(self, tmp_path: Path):
        dest = tmp_path / "committee_docs.csv"
        csv_content = b"SBoE ID,Name\nSTA-ABC,Test Committee\n"
        csv_response = _make_streaming_response([csv_content])
        csv_response.raise_for_status = MagicMock()

        with _patched_httpx_client(get_response=csv_response) as client:
            download_committee_document_export("12345", "TEST COMMITTEE", dest)

        assert dest.read_bytes() == csv_content
        client.get.assert_called_once()
        get_url = client.get.call_args[0][0]
        assert "/CFOrgLkup/ExportSearchResults/" in get_url
        assert "OGID=12345" in get_url

    def test_raises_browser_automation_error_for_html_response(self, tmp_path: Path):
        dest = tmp_path / "committee_docs.csv"
        html_response = MagicMock(spec=httpx.Response)
        html_response.headers = {"content-type": "text/html; charset=utf-8"}
        html_response.raise_for_status = MagicMock()
        html_response.iter_bytes.return_value = [b"<html>error</html>"]

        with _patched_httpx_client(get_response=html_response):
            with pytest.raises(BrowserAutomationRequiredError):
                download_committee_document_export("12345", "TEST", dest)

    def test_raises_browser_automation_error_for_non_csv_response(self, tmp_path: Path):
        dest = tmp_path / "committee_docs.csv"
        text_response = MagicMock(spec=httpx.Response)
        text_response.headers = {
            "content-type": "text/plain; charset=utf-8",
            "content-disposition": 'attachment; filename="committee_docs.csv"',
        }
        text_response.content = b"unexpected portal message"
        text_response.raise_for_status = MagicMock()

        with _patched_httpx_client(get_response=text_response):
            with pytest.raises(
                BrowserAutomationRequiredError,
                match="unexpected content type",
            ):
                download_committee_document_export("12345", "TEST", dest)

    def test_raises_browser_automation_error_for_empty_csv_response(self, tmp_path: Path):
        dest = tmp_path / "committee_docs.csv"
        empty_csv_response = MagicMock(spec=httpx.Response)
        empty_csv_response.headers = {"content-type": "text/csv; charset=utf-8"}
        empty_csv_response.content = b"\r\n"
        empty_csv_response.raise_for_status = MagicMock()

        with _patched_httpx_client(get_response=empty_csv_response):
            with pytest.raises(BrowserAutomationRequiredError, match="empty CSV"):
                download_committee_document_export("12345", "TEST", dest)


@pytest.mark.integration
class TestCommitteeExportIntegration:
    def test_live_committee_export_produces_valid_csv(self, tmp_path: Path):
        from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
            COMMITTEE_DOC_COLUMNS,
        )

        dest = tmp_path / "committee_docs.csv"
        try:
            download_committee_document_export(
                org_group_id="27075",
                title="ADAMS FOR NC HOUSE (ADAMS, JAMES CECIL  JR)",
                dest_path=dest,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            pytest.skip(f"NC portal unavailable: {exc}")

        assert dest.exists()
        header_line = dest.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
        actual_columns = tuple(header_line.strip().split(","))
        assert actual_columns == COMMITTEE_DOC_COLUMNS, (
            f"CSV header mismatch — portal contract may have changed: {actual_columns}"
        )


class TestStopConditionGuards:
    def test_transaction_export_raises_when_params_missing(self, tmp_path: Path):
        """When the results page no longer exposes Params, raise BrowserAutomationRequiredError."""
        dest = tmp_path / "transactions.csv"
        no_params_html = "<html><body>No export available</body></html>"

        search_response = MagicMock(spec=httpx.Response)
        search_response.text = no_params_html
        search_response.raise_for_status = MagicMock()

        with _patched_httpx_client(
            get_response=MagicMock(spec=httpx.Response, raise_for_status=MagicMock()),
            post_response=search_response,
        ):
            criteria = TransactionSearchCriteria(last_name="TEST")
            with pytest.raises(BrowserAutomationRequiredError, match="Params"):
                download_transaction_export(criteria, dest)

    def test_transaction_export_raises_when_export_returns_html(self, tmp_path: Path):
        """When the export endpoint returns HTML instead of CSV, raise BrowserAutomationRequiredError."""
        dest = tmp_path / "transactions.csv"
        results_html = _build_results_html_with_params(_SAMPLE_PARAMS_JSON)

        search_response = MagicMock(spec=httpx.Response)
        search_response.text = results_html
        search_response.raise_for_status = MagicMock()

        html_export_response = MagicMock(spec=httpx.Response)
        html_export_response.headers = {"content-type": "text/html; charset=utf-8"}
        html_export_response.raise_for_status = MagicMock()

        with _patched_httpx_client(
            get_response=MagicMock(spec=httpx.Response, raise_for_status=MagicMock()),
            post_responses=[search_response, html_export_response],
        ):
            criteria = TransactionSearchCriteria(last_name="TEST")
            with pytest.raises(BrowserAutomationRequiredError):
                download_transaction_export(criteria, dest)

    def test_transaction_export_raises_when_export_returns_empty_csv(self, tmp_path: Path):
        """When the export returns CSV content-type but empty body (just CRLF),
        raise BrowserAutomationRequiredError — this means the server-side query
        was never triggered by the JavaScript grid."""
        dest = tmp_path / "transactions.csv"
        results_html = _build_results_html_with_params(_SAMPLE_PARAMS_JSON)

        search_response = MagicMock(spec=httpx.Response)
        search_response.text = results_html
        search_response.raise_for_status = MagicMock()

        empty_csv_response = MagicMock(spec=httpx.Response)
        empty_csv_response.headers = {"content-type": "text/csv; charset=utf-8"}
        empty_csv_response.content = b"\r\n"
        empty_csv_response.raise_for_status = MagicMock()

        with _patched_httpx_client(
            get_response=MagicMock(spec=httpx.Response, raise_for_status=MagicMock()),
            post_responses=[search_response, empty_csv_response],
        ):
            criteria = TransactionSearchCriteria(last_name="TEST")
            with pytest.raises(BrowserAutomationRequiredError, match="empty CSV"):
                download_transaction_export(criteria, dest)

    def test_transaction_export_raises_when_export_returns_non_csv_content(self, tmp_path: Path):
        """When the export endpoint returns a non-CSV payload, fail fast."""
        dest = tmp_path / "transactions.csv"
        results_html = _build_results_html_with_params(_SAMPLE_PARAMS_JSON)

        search_response = MagicMock(spec=httpx.Response)
        search_response.text = results_html
        search_response.raise_for_status = MagicMock()

        text_export_response = MagicMock(spec=httpx.Response)
        text_export_response.headers = {
            "content-type": "text/plain; charset=utf-8",
            "content-disposition": 'attachment; filename="transinq_results.csv"',
        }
        text_export_response.content = b"unexpected portal message"
        text_export_response.raise_for_status = MagicMock()

        with _patched_httpx_client(
            get_response=MagicMock(spec=httpx.Response, raise_for_status=MagicMock()),
            post_responses=[search_response, text_export_response],
        ):
            criteria = TransactionSearchCriteria(last_name="TEST")
            with pytest.raises(
                BrowserAutomationRequiredError,
                match="unexpected content type",
            ):
                download_transaction_export(criteria, dest)


# -- 2026-cycle portal-contract lock tests --


class TestNCPortalContract2026:
    """Lock NC portal URLs and config assumptions for 2026 cycle.

    These are regression guards: if the NC SBE portal changes its URL
    structure, these tests catch it before a live scrape attempt fails silently.
    """

    def test_portal_base_url_matches_ncsbe(self) -> None:
        assert _NC_PORTAL_BASE == "https://cf.ncsbe.gov"

    def test_transaction_search_url_under_portal_base(self) -> None:
        assert _TXN_SEARCH_URL.startswith(_NC_PORTAL_BASE)
        assert "CFTxnLkup" in _TXN_SEARCH_URL

    def test_transaction_results_url_under_portal_base(self) -> None:
        assert _TXN_RESULTS_URL.startswith(_NC_PORTAL_BASE)
        assert "TxnSearchResults" in _TXN_RESULTS_URL

    def test_transaction_export_url_under_portal_base(self) -> None:
        assert _TXN_EXPORT_URL.startswith(_NC_PORTAL_BASE)
        assert "ExportResults" in _TXN_EXPORT_URL

    def test_config_verified_for_2026_cycle(self) -> None:
        """All NC data sources must show a 2026-cycle verification date."""
        cycle_cutoff = date(2026, 3, 21)
        config = load_jurisdiction_config(_NC_CONFIG_PATH)
        for source in config.data_sources:
            assert source.last_verified_working is not None, f"{source.name} has no last_verified_working date"
            assert source.last_verified_working >= cycle_cutoff, (
                f"{source.name} last_verified_working={source.last_verified_working} is before {cycle_cutoff}"
            )
