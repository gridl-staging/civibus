"""Unit tests for campaign-finance freshness probes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.quality.freshness import (
    _IL_FRESHNESS_TAIL_ROWS,
    _FreshnessObservation,
    _build_freshness_check_result,
    _freshness_status_for_age_days,
    _max_transaction_date_from_rows,
    _probe_il_contributions,
    _probe_in_contributions,
    _probe_mn_contributions,
    _probe_nj_contributions,
    run_freshness_checks,
)
from domains.campaign_finance.quality.models import CheckResult


def _fake_check(status: str) -> CheckResult:
    return CheckResult(name="freshness", status=status, message="ok")


@dataclass(frozen=True)
class _ProbeWiringCase:
    case_id: str
    probe_func: Callable[[], CheckResult]
    download_attr: str
    parse_attr: str
    column_attr: str
    source_attr: str
    artifact_attr: str
    date_attr: str
    download_call_style: str
    download_filename: str
    download_is_binary: bool
    parsed_rows: tuple[dict[str, str], ...]
    parsed_dates: tuple[date, ...]
    date_column: str
    source_url: str
    patched_artifact_url: str
    jurisdiction: str
    escaped_filename: str


_FRESHNESS_MODULE = "domains.campaign_finance.quality.freshness"


def _write_download_file(destination_dir: Path, filename: str, *, binary: bool = False) -> Path:
    download_path = destination_dir / filename
    if binary:
        download_path.write_bytes(b"zip-placeholder")
    else:
        download_path.write_text("placeholder", encoding="utf-8")
    return download_path


def _source_return_value(case: _ProbeWiringCase) -> object:
    if case.download_call_style == "in":
        return MagicMock(url=case.source_url)
    return case.source_url


def _download_side_effect(case: _ProbeWiringCase) -> Callable[..., Path]:
    if case.download_call_style == "in":
        return lambda **kwargs: _write_download_file(
            kwargs["dest_dir"],
            case.download_filename,
            binary=case.download_is_binary,
        )
    if case.download_call_style == "il":
        return lambda data_type, *, dest_dir, tail_data_rows: _write_download_file(
            dest_dir,
            case.download_filename,
            binary=case.download_is_binary,
        )
    return lambda data_type, dest_dir: _write_download_file(
        dest_dir,
        case.download_filename,
        binary=case.download_is_binary,
    )


def _assert_download_called(case: _ProbeWiringCase, mock_download: MagicMock) -> None:
    if case.download_call_style == "in":
        mock_download.assert_called_once()
        assert mock_download.call_args.kwargs["data_type"] == "contributions"
        return

    if case.download_call_style == "il":
        mock_download.assert_called_once_with(
            "contributions",
            dest_dir=mock_download.call_args.kwargs["dest_dir"],
            tail_data_rows=_IL_FRESHNESS_TAIL_ROWS,
        )
        return

    mock_download.assert_called_once_with(
        data_type="contributions",
        dest_dir=mock_download.call_args.kwargs["dest_dir"],
    )


def _expected_artifact_url(case: _ProbeWiringCase) -> str:
    if case.download_call_style == "in":
        return case.patched_artifact_url.replace("{YEAR}", str(date.today().year))
    return case.patched_artifact_url


_PROBE_WIRING_CASES = (
    _ProbeWiringCase(
        case_id="in",
        probe_func=_probe_in_contributions,
        download_attr="download_in_data",
        parse_attr="parse_in_contributions",
        column_attr="in_column_for_semantic_path",
        source_attr="in_data_source_for_data_type",
        artifact_attr="in_bulk_download_url_for_data_type",
        date_attr="parse_in_date",
        download_call_style="in",
        download_filename="in_contributions.csv.zip",
        download_is_binary=True,
        parsed_rows=(
            {"ContributionDate": "2026-03-25 14:01:00"},
            {"ContributionDate": "2026-03-10 10:00:00"},
        ),
        parsed_dates=(date(2026, 3, 25), date(2026, 3, 10)),
        date_column="ContributionDate",
        source_url="https://example.com/in/source",
        patched_artifact_url="https://example.com/in/contributions/{YEAR}.zip",
        jurisdiction="state/IN",
        escaped_filename="escaped.csv",
    ),
    _ProbeWiringCase(
        case_id="il",
        probe_func=_probe_il_contributions,
        download_attr="download_il_data",
        parse_attr="parse_il_contributions",
        column_attr="il_column_for_semantic_path",
        source_attr="il_data_source_url_for_data_type",
        artifact_attr="il_bulk_download_url_for_data_type",
        date_attr="parse_il_date",
        download_call_style="il",
        download_filename="Receipts.txt",
        download_is_binary=False,
        parsed_rows=(
            {"RcvDate": "2026-03-29 15:10:00"},
            {"RcvDate": "2026-03-27 10:13:00"},
        ),
        parsed_dates=(date(2026, 3, 29), date(2026, 3, 27)),
        date_column="RcvDate",
        source_url="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        patched_artifact_url="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        jurisdiction="state/IL",
        escaped_filename="escaped.txt",
    ),
    _ProbeWiringCase(
        case_id="mn",
        probe_func=_probe_mn_contributions,
        download_attr="download_mn_csv",
        parse_attr="parse_mn_contributions",
        column_attr="mn_column_for_semantic_path",
        source_attr="mn_source_url_for_data_type",
        artifact_attr="build_mn_download_url",
        date_attr="parse_mn_date",
        download_call_style="keyword",
        download_filename="mn_contributions.csv",
        download_is_binary=False,
        parsed_rows=(
            {"transaction_date": "2026-03-18"},
            {"transaction_date": "2026-03-01"},
        ),
        parsed_dates=(date(2026, 3, 18), date(2026, 3, 1)),
        date_column="transaction_date",
        source_url="https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/",
        patched_artifact_url="https://register.cfb.mn.gov/downloads/contributions.csv",
        jurisdiction="state/MN",
        escaped_filename="escaped.csv",
    ),
    _ProbeWiringCase(
        case_id="nj",
        probe_func=_probe_nj_contributions,
        download_attr="download_nj_csv",
        parse_attr="parse_nj_contributions",
        column_attr="nj_column_for_semantic_path",
        source_attr="nj_source_url_for_data_type",
        artifact_attr="build_nj_download_url",
        date_attr="parse_nj_date",
        download_call_style="keyword",
        download_filename="nj_contributions.csv",
        download_is_binary=False,
        parsed_rows=(
            {"ContributionDate": "2026-03-21"},
            {"ContributionDate": "2026-03-03"},
        ),
        parsed_dates=(date(2026, 3, 21), date(2026, 3, 3)),
        date_column="ContributionDate",
        source_url="https://www.njelecefilesearch.com/",
        patched_artifact_url="https://www.njelecefilesearch.com/download/contributions.csv",
        jurisdiction="state/NJ",
        escaped_filename="escaped.csv",
    ),
)


class TestFreshnessClassification:
    def _observation(
        self,
        *,
        max_transaction_date: date | None,
        parsed_row_count: int = 100,
    ) -> _FreshnessObservation:
        return _FreshnessObservation(
            jurisdiction="state/IN",
            source_url="https://example.com/in",
            artifact_url="https://example.com/in.csv",
            date_column="ContributionDate",
            max_transaction_date=max_transaction_date,
            parsed_row_count=parsed_row_count,
        )

    def test_result_builder_signature_within_hard_parameter_limit(self) -> None:
        assert len(inspect.signature(_build_freshness_check_result).parameters) <= 6

    @pytest.mark.parametrize(
        ("age_days", "expected_status"),
        [
            (-1, "warn"),
            (0, "pass"),
            (7, "pass"),
            (8, "warn"),
            (30, "warn"),
            (31, "fail"),
        ],
    )
    def test_status_helper_honors_threshold_boundaries(
        self,
        age_days: int,
        expected_status: str,
    ) -> None:
        assert _freshness_status_for_age_days(age_days) == expected_status

    def test_none_max_date_returns_fail_with_no_metric(self) -> None:
        result = _build_freshness_check_result(self._observation(max_transaction_date=None, parsed_row_count=50))
        assert result.status == "fail"
        assert result.metric_value is None
        assert "no parseable transaction dates" in result.message
        assert result.details["parsed_row_count"] == 50
        assert result.details["max_transaction_date"] is None

    @pytest.mark.parametrize(
        ("max_transaction_date", "expected_status"),
        [
            (date(2026, 3, 31), "pass"),
            (date(2026, 3, 15), "warn"),
            (date(2026, 2, 1), "fail"),
        ],
    )
    def test_classifies_max_date_recency(
        self,
        max_transaction_date: date,
        expected_status: str,
    ) -> None:
        result = _build_freshness_check_result(
            self._observation(max_transaction_date=max_transaction_date),
            as_of_date=date(2026, 3, 31),
        )
        assert result.status == expected_status
        assert result.name == "freshness"

    def test_result_builder_surfaces_future_dated_anomalies_without_changing_status(self) -> None:
        observation = _FreshnessObservation(
            jurisdiction="state/NJ",
            source_url="https://example.com/nj",
            artifact_url="https://example.com/nj.csv",
            date_column="ContributionDate",
            parsed_row_count=100,
            max_transaction_date=date(2026, 4, 7),
            future_dated_row_count=1,
            max_future_transaction_date=date(2033, 12, 31),
        )

        result = _build_freshness_check_result(observation, as_of_date=date(2026, 4, 9))

        assert result.status == "pass"
        assert result.details["future_dated_row_count"] == 1
        assert result.details["max_future_transaction_date"] == "2033-12-31"
        assert "ignored 1 future-dated rows" in result.message


def test_max_transaction_date_ignores_future_dated_outliers() -> None:
    max_transaction_date, parsed_row_count, future_dated_row_count, max_future_transaction_date = (
        _max_transaction_date_from_rows(
            [
                {"ContributionDate": "2026-04-08"},
                {"ContributionDate": "2033-12-31"},
                {"ContributionDate": "2026-03-01"},
            ],
            date_column="ContributionDate",
            parse_date=lambda value: date.fromisoformat(value) if value is not None else None,
            as_of_date=date(2026, 4, 9),
        )
    )

    assert max_transaction_date == date(2026, 4, 8)
    assert parsed_row_count == 3
    assert future_dated_row_count == 1
    assert max_future_transaction_date == date(2033, 12, 31)


class TestFreshnessProbeDispatch:
    @patch("domains.campaign_finance.quality.freshness._probe_nj_contributions", return_value=_fake_check("pass"))
    @patch("domains.campaign_finance.quality.freshness._probe_mn_contributions", return_value=_fake_check("warn"))
    @patch("domains.campaign_finance.quality.freshness._probe_in_contributions", return_value=_fake_check("fail"))
    @patch("domains.campaign_finance.quality.freshness._probe_il_contributions", return_value=_fake_check("pass"))
    def test_dispatches_il_in_mn_nj_probes(
        self,
        mock_il_probe: MagicMock,
        mock_in_probe: MagicMock,
        mock_mn_probe: MagicMock,
        mock_nj_probe: MagicMock,
    ) -> None:
        summaries = run_freshness_checks(None)

        assert [summary.jurisdiction for summary in summaries] == ["state/IL", "state/IN", "state/MN", "state/NJ"]
        assert [summary.check_results[0].status for summary in summaries] == ["pass", "fail", "warn", "pass"]
        mock_il_probe.assert_called_once()
        mock_in_probe.assert_called_once()
        mock_mn_probe.assert_called_once()
        mock_nj_probe.assert_called_once()

    @patch(
        "domains.campaign_finance.quality.freshness._probe_in_contributions", side_effect=RuntimeError("network error")
    )
    def test_probe_failure_returns_error_check_result(
        self,
        _mock_in_probe: MagicMock,
    ) -> None:
        summaries = run_freshness_checks("state/IN")

        assert len(summaries) == 1
        result = summaries[0].check_results[0]
        assert summaries[0].jurisdiction == "state/IN"
        assert result.status == "error"
        assert "network error" in result.message

    @patch("domains.campaign_finance.quality.freshness._probe_nj_contributions", side_effect=RuntimeError("timeout"))
    @patch("domains.campaign_finance.quality.freshness._probe_mn_contributions", return_value=_fake_check("warn"))
    @patch("domains.campaign_finance.quality.freshness._probe_in_contributions", return_value=_fake_check("pass"))
    @patch("domains.campaign_finance.quality.freshness._probe_il_contributions", return_value=_fake_check("pass"))
    def test_probe_failure_isolated_per_state(
        self,
        _mock_il_probe: MagicMock,
        _mock_in_probe: MagicMock,
        _mock_mn_probe: MagicMock,
        _mock_nj_probe: MagicMock,
    ) -> None:
        summaries = run_freshness_checks(None)
        by_jurisdiction = {summary.jurisdiction: summary for summary in summaries}

        assert by_jurisdiction["state/IL"].check_results[0].status == "pass"
        assert by_jurisdiction["state/IN"].check_results[0].status == "pass"
        assert by_jurisdiction["state/MN"].check_results[0].status == "warn"
        assert by_jurisdiction["state/NJ"].check_results[0].status == "error"
        assert "timeout" in by_jurisdiction["state/NJ"].check_results[0].message


@pytest.mark.parametrize("case", _PROBE_WIRING_CASES, ids=[case.case_id for case in _PROBE_WIRING_CASES])
def test_probe_uses_download_and_configured_date_column(case: _ProbeWiringCase) -> None:
    with (
        patch(
            f"{_FRESHNESS_MODULE}.{case.download_attr}",
            side_effect=_download_side_effect(case),
        ) as mock_download,
        patch(
            f"{_FRESHNESS_MODULE}.{case.parse_attr}",
            return_value=iter(case.parsed_rows),
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.column_attr}",
            return_value=case.date_column,
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.source_attr}",
            return_value=_source_return_value(case),
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.artifact_attr}",
            return_value=case.patched_artifact_url,
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.date_attr}",
            side_effect=case.parsed_dates,
        ),
        patch(
            f"{_FRESHNESS_MODULE}._build_freshness_check_result",
            return_value=_fake_check("pass"),
        ) as mock_build_check,
    ):
        result = case.probe_func()

    assert result.status == "pass"
    _assert_download_called(case, mock_download)
    mock_build_check.assert_called_once()
    observed_payload = mock_build_check.call_args.args[0]
    assert observed_payload.jurisdiction == case.jurisdiction
    assert observed_payload.date_column == case.date_column
    assert observed_payload.source_url == case.source_url
    assert observed_payload.artifact_url == _expected_artifact_url(case)
    assert observed_payload.parsed_row_count == 2
    assert observed_payload.max_transaction_date == case.parsed_dates[0]


@pytest.mark.parametrize("case", _PROBE_WIRING_CASES, ids=[case.case_id for case in _PROBE_WIRING_CASES])
def test_probe_rejects_download_paths_outside_temp_directory(case: _ProbeWiringCase, tmp_path: Path) -> None:
    escaped_path = tmp_path / case.escaped_filename
    with (
        patch(
            f"{_FRESHNESS_MODULE}.{case.download_attr}",
            return_value=escaped_path,
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.column_attr}",
            return_value=case.date_column,
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.source_attr}",
            return_value=_source_return_value(case),
        ),
        patch(
            f"{_FRESHNESS_MODULE}.{case.artifact_attr}",
            return_value=case.patched_artifact_url,
        ),
    ):
        with pytest.raises(ValueError, match="escaped the temporary directory"):
            case.probe_func()


@pytest.mark.parametrize(
    ("probe_func", "download_attr", "column_attr", "source_attr", "artifact_attr", "date_column"),
    [
        (
            _probe_il_contributions,
            "download_il_data",
            "il_column_for_semantic_path",
            "il_data_source_url_for_data_type",
            "il_bulk_download_url_for_data_type",
            "RcvDate",
        ),
        (
            _probe_mn_contributions,
            "download_mn_csv",
            "mn_column_for_semantic_path",
            "mn_source_url_for_data_type",
            "build_mn_download_url",
            "transaction_date",
        ),
        (
            _probe_nj_contributions,
            "download_nj_csv",
            "nj_column_for_semantic_path",
            "nj_source_url_for_data_type",
            "build_nj_download_url",
            "ContributionDate",
        ),
    ],
)
def test_direct_probe_connection_errors_propagate(
    probe_func,
    download_attr: str,
    column_attr: str,
    source_attr: str,
    artifact_attr: str,
    date_column: str,
) -> None:
    with (
        patch(
            f"domains.campaign_finance.quality.freshness.{column_attr}",
            return_value=date_column,
        ),
        patch(
            f"domains.campaign_finance.quality.freshness.{source_attr}",
            return_value="https://example.com/source",
        ),
        patch(
            f"domains.campaign_finance.quality.freshness.{artifact_attr}",
            return_value="https://example.com/artifact",
        ),
        patch(
            f"domains.campaign_finance.quality.freshness.{download_attr}",
            side_effect=RuntimeError("connection refused"),
        ),
    ):
        with pytest.raises(RuntimeError, match="connection refused"):
            probe_func()


def test_probe_mn_timeout_propagates_and_dispatcher_returns_error() -> None:
    with (
        patch(
            "domains.campaign_finance.quality.freshness.mn_column_for_semantic_path",
            return_value="transaction_date",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.mn_source_url_for_data_type",
            return_value="https://example.com/mn/source",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.build_mn_download_url",
            return_value="https://example.com/mn/contributions.csv",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.download_mn_csv",
            side_effect=httpx.ReadTimeout("read timed out"),
        ),
    ):
        with pytest.raises(httpx.ReadTimeout, match="read timed out"):
            _probe_mn_contributions()
        summaries = run_freshness_checks("state/MN")

    assert len(summaries) == 1
    assert summaries[0].jurisdiction == "state/MN"
    result = summaries[0].check_results[0]
    assert result.status == "error"
    assert "read timed out" in result.message


@patch("domains.campaign_finance.quality.freshness._probe_contributions", return_value=_fake_check("pass"))
def test_state_probes_share_common_probe_flow(mock_probe_contributions: MagicMock) -> None:
    _probe_il_contributions()
    _probe_in_contributions()
    _probe_mn_contributions()
    _probe_nj_contributions()

    assert mock_probe_contributions.call_count == 4
    jurisdictions = [call.args[0].jurisdiction for call in mock_probe_contributions.call_args_list]
    assert jurisdictions == ["state/IL", "state/IN", "state/MN", "state/NJ"]
