"""Tests for NY SODA API download module."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.NY.scraper.download import (
    REQUEST_TIMEOUT_SECONDS,
    SODA_PAGE_SIZE,
    YEAR_FILTER_THRESHOLD,
    build_ny_download_url,
    download_ny_csv,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import (
    IE_COLUMNS,
    parse_independent_expenditures,
)


def _build_csv_page(row_count: int) -> bytes:
    lines = ["col_a,col_b"]
    for index in range(row_count):
        lines.append(f"value_{index},value_{index}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _read_query_param(url: str, key: str) -> str:
    values = parse_qs(urlsplit(url).query).get(key)
    assert values is not None
    assert len(values) == 1
    return values[0]


class _MockResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return


class _MockClient:
    def __init__(self, actions: list[_MockResponse | Exception], seen_urls: list[str]) -> None:
        self._actions = actions
        self._seen_urls = seen_urls

    def __enter__(self) -> _MockClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, *, follow_redirects: bool) -> _MockResponse:
        assert follow_redirects is True
        self._seen_urls.append(url)
        if not self._actions:
            raise AssertionError("No remaining mock actions for httpx.Client.get")
        action = self._actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _install_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    actions: Sequence[_MockResponse | Exception],
) -> list[str]:
    seen_urls: list[str] = []
    mutable_actions = list(actions)

    def _client_factory(*, timeout: float) -> _MockClient:
        assert timeout == REQUEST_TIMEOUT_SECONDS
        return _MockClient(mutable_actions, seen_urls)

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.NY.scraper.download.httpx.Client",
        _client_factory,
    )
    return seen_urls


def _assert_lane_offset_progress_observability(
    caplog: pytest.LogCaptureFixture,
    *,
    lane: str,
    offset: int,
) -> None:
    lane_lower = lane.lower()
    assert any(
        lane_lower in record.message.lower()
        and f"offset={offset}" in record.message
        and any(token in record.message.lower() for token in ("page", "downloaded", "rows so far"))
        for record in caplog.records
    )


def _assert_terminal_lane_offset_failure_observability(
    caplog: pytest.LogCaptureFixture,
    *,
    lane: str,
    offset: int,
) -> None:
    lane_lower = lane.lower()
    _assert_lane_offset_progress_observability(caplog, lane=lane, offset=offset)
    assert any(
        lane_lower in record.message.lower()
        and f"offset={offset}" in record.message
        and any(token in record.message.lower() for token in ("fail", "error", "timeout", "terminal", "exception"))
        for record in caplog.records
    )
    assert any(
        lane_lower in record.message.lower()
        and f"offset={offset}" in record.message
        and "page" in record.message.lower()
        and any(token in record.message.lower() for token in ("fail", "error", "timeout", "terminal", "exception"))
        for record in caplog.records
    )


def _assert_record_page_context(
    record: logging.LogRecord,
    *,
    lane: str,
    offset: int,
    limit: int,
    page: int,
    progress_outcome: str,
) -> None:
    assert getattr(record, "lane", None) == lane
    assert getattr(record, "offset", None) == offset
    assert getattr(record, "limit", None) == limit
    assert getattr(record, "page", None) == page
    assert getattr(record, "progress_outcome", None) == progress_outcome


class TestNYDownloadURLContract:
    """Lock the SODA dataset IDs and query structure."""

    def test_contributions_url_uses_known_dataset_id(self) -> None:
        url = build_ny_download_url("contributions")
        assert "4j2b-6a2j" in url

    def test_expenditures_url_uses_known_dataset_id(self) -> None:
        url = build_ny_download_url("expenditures")
        assert "ajsb-8pni" in url

    def test_ie_url_uses_parent_dataset(self) -> None:
        url = build_ny_download_url("independent_expenditures")
        assert "e9ss-239a" in url

    def test_ie_url_includes_filing_cat_desc_filter(self) -> None:
        url = build_ny_download_url("independent_expenditures")
        where_clause = _read_query_param(url, "$where")
        assert "filing_cat_desc" in where_clause
        assert "IE 24 Hour/Weekly Notices" in where_clause

    def test_ie_url_includes_date_and_pagination(self) -> None:
        url = build_ny_download_url("independent_expenditures", offset=50000)
        where_clause = _read_query_param(url, "$where")
        assert "sched_date" in where_clause
        assert YEAR_FILTER_THRESHOLD in where_clause
        assert "$offset=50000" in url
        assert "$order=trans_number" in url

    def test_url_includes_date_filter(self) -> None:
        url = build_ny_download_url("contributions")
        where_clause = _read_query_param(url, "$where")
        assert "sched_date" in where_clause
        assert YEAR_FILTER_THRESHOLD in where_clause

    def test_url_includes_pagination(self) -> None:
        url = build_ny_download_url("contributions", offset=50000)
        assert "$offset=50000" in url
        assert f"$limit={SODA_PAGE_SIZE}" in url

    def test_url_includes_ordering(self) -> None:
        url = build_ny_download_url("contributions")
        assert "$order=trans_number" in url

    def test_custom_limit_overrides_page_size(self) -> None:
        url = build_ny_download_url("contributions", limit=100)
        assert "$limit=100" in url

    def test_soda_page_size_is_50000(self) -> None:
        assert SODA_PAGE_SIZE == 50_000

    def test_year_filter_threshold_is_2022(self) -> None:
        assert "2022" in YEAR_FILTER_THRESHOLD

    def test_url_rejects_non_iso_year_from(self) -> None:
        with pytest.raises(ValueError, match="year_from must be an ISO-8601"):
            build_ny_download_url("contributions", year_from="2022-01-01' OR trans_number > 0 --")


def test_stage1_regression_contributions_page1_read_timeout_requires_terminal_lane_offset_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Apr 28 evidence: contributions page-1 read timeout should be diagnosable."""

    seen_urls = _install_mock_client(
        monkeypatch,
        actions=[httpx.ReadTimeout("The read operation timed out")],
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(httpx.ReadTimeout, match="read operation timed out"):
        download_ny_csv("contributions", tmp_path)

    assert seen_urls and "$offset=0" in seen_urls[0]
    assert not (tmp_path / "ny_contributions.csv").exists()
    assert not list(tmp_path.glob("*.part"))
    assert not any("download complete" in record.message for record in caplog.records)
    _assert_terminal_lane_offset_failure_observability(
        caplog,
        lane="contributions",
        offset=0,
    )


def test_stage1_regression_expenditures_hang_class_requires_terminal_progress_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Apr 28 evidence: expenditures hang/0-byte class needs bounded per-page observability."""

    first_page = _MockResponse(_build_csv_page(SODA_PAGE_SIZE))
    seen_urls = _install_mock_client(
        monkeypatch,
        actions=[first_page, httpx.ReadTimeout("The read operation timed out")],
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(httpx.ReadTimeout, match="read operation timed out"):
        download_ny_csv("expenditures", tmp_path)

    assert len(seen_urls) == 2
    assert "$offset=0" in seen_urls[0]
    assert f"$offset={SODA_PAGE_SIZE}" in seen_urls[1]
    assert not (tmp_path / "ny_expenditures.csv").exists()
    assert not list(tmp_path.glob("*.part"))
    _assert_lane_offset_progress_observability(
        caplog,
        lane="expenditures",
        offset=0,
    )
    assert not any("download complete" in record.message for record in caplog.records)
    _assert_terminal_lane_offset_failure_observability(
        caplog,
        lane="expenditures",
        offset=SODA_PAGE_SIZE,
    )


def test_stage1_regression_ie_header_only_is_truthful_zero_row_terminal_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Apr 29 corroboration: IE can truthfully terminate with header-only source response."""

    ie_header_only = (",".join(IE_COLUMNS) + "\n").encode("utf-8")
    seen_urls = _install_mock_client(monkeypatch, actions=[_MockResponse(ie_header_only)])

    csv_path = download_ny_csv("independent_expenditures", tmp_path)

    assert len(seen_urls) == 1
    assert "$offset=0" in seen_urls[0]
    assert csv_path.exists()
    assert csv_path.read_text(encoding="utf-8").strip() == ",".join(IE_COLUMNS)
    assert list(parse_independent_expenditures(csv_path)) == []


def test_download_rejects_unsupported_data_type_before_writing_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Unsupported NY data type"):
        download_ny_csv("../escape", tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_stage3_regression_emits_structured_page_context_for_attempt_complete_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first_page = _MockResponse(_build_csv_page(SODA_PAGE_SIZE))
    _install_mock_client(
        monkeypatch,
        actions=[first_page, httpx.ReadTimeout("The read operation timed out")],
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(httpx.ReadTimeout, match="read operation timed out"):
        download_ny_csv("expenditures", tmp_path)

    attempt_records = [record for record in caplog.records if "NY page request attempt" in record.message]
    complete_records = [record for record in caplog.records if "NY page complete" in record.message]
    failure_records = [record for record in caplog.records if "NY terminal failure" in record.message]

    assert len(attempt_records) == 2
    _assert_record_page_context(
        attempt_records[0],
        lane="expenditures",
        offset=0,
        limit=SODA_PAGE_SIZE,
        page=1,
        progress_outcome="request_attempt",
    )
    _assert_record_page_context(
        attempt_records[1],
        lane="expenditures",
        offset=SODA_PAGE_SIZE,
        limit=SODA_PAGE_SIZE,
        page=2,
        progress_outcome="request_attempt",
    )

    assert len(complete_records) == 1
    _assert_record_page_context(
        complete_records[0],
        lane="expenditures",
        offset=0,
        limit=SODA_PAGE_SIZE,
        page=1,
        progress_outcome="page_complete",
    )
    assert getattr(complete_records[0], "page_rows", None) == SODA_PAGE_SIZE
    assert getattr(complete_records[0], "total_rows", None) == SODA_PAGE_SIZE

    assert len(failure_records) == 1
    _assert_record_page_context(
        failure_records[0],
        lane="expenditures",
        offset=SODA_PAGE_SIZE,
        limit=SODA_PAGE_SIZE,
        page=2,
        progress_outcome="terminal_failure",
    )
    assert getattr(failure_records[0], "total_rows", None) == SODA_PAGE_SIZE
