"""Unit tests for campaign-finance freshness probes."""

from __future__ import annotations

from datetime import date
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    @patch("domains.campaign_finance.quality.freshness._probe_nj_contributions", return_value=_fake_check("pass"))
    @patch("domains.campaign_finance.quality.freshness._probe_mn_contributions", return_value=_fake_check("warn"))
    @patch("domains.campaign_finance.quality.freshness._probe_in_contributions", return_value=_fake_check("fail"))
    @patch("domains.campaign_finance.quality.freshness._probe_il_contributions", return_value=_fake_check("pass"))
    def test_dispatches_in_mn_nj_probes(
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


def test_probe_in_uses_download_and_configured_date_column(tmp_path: Path) -> None:
    current_year = date.today().year
    parsed_rows = [
        {"ContributionDate": "2026-03-25 14:01:00"},
        {"ContributionDate": "2026-03-10 10:00:00"},
    ]

    def _write_download_to(destination_dir: Path) -> Path:
        download_path = destination_dir / "in_contributions.csv.zip"
        download_path.write_bytes(b"zip-placeholder")
        return download_path

    with (
        patch(
            "domains.campaign_finance.quality.freshness.download_in_data",
            side_effect=lambda **kwargs: _write_download_to(kwargs["dest_dir"]),
        ) as mock_download,
        patch(
            "domains.campaign_finance.quality.freshness.parse_in_contributions",
            return_value=iter(parsed_rows),
        ),
        patch(
            "domains.campaign_finance.quality.freshness.in_column_for_semantic_path",
            return_value="ContributionDate",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.in_data_source_for_data_type",
            return_value=MagicMock(url="https://example.com/in/source"),
        ),
        patch(
            "domains.campaign_finance.quality.freshness.in_bulk_download_url_for_data_type",
            return_value="https://example.com/in/contributions/{YEAR}.zip",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.parse_in_date",
            side_effect=[date(2026, 3, 25), date(2026, 3, 10)],
        ),
        patch(
            "domains.campaign_finance.quality.freshness._build_freshness_check_result",
            return_value=_fake_check("pass"),
        ) as mock_build_check,
    ):
        result = _probe_in_contributions()

    assert result.status == "pass"
    mock_download.assert_called_once()
    assert mock_download.call_args.kwargs["data_type"] == "contributions"
    mock_build_check.assert_called_once()
    observed_payload = mock_build_check.call_args.args[0]
    assert observed_payload.jurisdiction == "state/IN"
    assert observed_payload.date_column == "ContributionDate"
    assert observed_payload.source_url == "https://example.com/in/source"
    assert observed_payload.artifact_url == f"https://example.com/in/contributions/{current_year}.zip"
    assert observed_payload.parsed_row_count == 2
    assert observed_payload.max_transaction_date == date(2026, 3, 25)

    escaped_path = tmp_path / "escaped.csv"
    with (
        patch(
            "domains.campaign_finance.quality.freshness.download_in_data",
            return_value=escaped_path,
        ),
        patch(
            "domains.campaign_finance.quality.freshness.in_column_for_semantic_path",
            return_value="ContributionDate",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.in_data_source_for_data_type",
            return_value=MagicMock(url="https://example.com/in/source"),
        ),
        patch(
            "domains.campaign_finance.quality.freshness.in_bulk_download_url_for_data_type",
            return_value="https://example.com/in/contributions/{YEAR}.zip",
        ),
    ):
        with pytest.raises(ValueError, match="escaped the temporary directory"):
            _probe_in_contributions()


def test_probe_il_uses_download_and_configured_date_column(tmp_path: Path) -> None:
    parsed_rows = [
        {"RcvDate": "2026-03-29 15:10:00"},
        {"RcvDate": "2026-03-27 10:13:00"},
    ]

    def _write_download_to(destination_dir: Path) -> Path:
        download_path = destination_dir / "Receipts.txt"
        download_path.write_text("placeholder", encoding="utf-8")
        return download_path

    with (
        patch(
            "domains.campaign_finance.quality.freshness.download_il_data",
            side_effect=lambda data_type, *, dest_dir, tail_data_rows: _write_download_to(dest_dir),
        ) as mock_download,
        patch(
            "domains.campaign_finance.quality.freshness.parse_il_contributions",
            return_value=iter(parsed_rows),
        ),
        patch(
            "domains.campaign_finance.quality.freshness.il_column_for_semantic_path",
            return_value="RcvDate",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.il_data_source_url_for_data_type",
            return_value="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.il_bulk_download_url_for_data_type",
            return_value="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.parse_il_date",
            side_effect=[date(2026, 3, 29), date(2026, 3, 27)],
        ),
        patch(
            "domains.campaign_finance.quality.freshness._build_freshness_check_result",
            return_value=_fake_check("pass"),
        ) as mock_build_check,
    ):
        result = _probe_il_contributions()

    assert result.status == "pass"
    mock_download.assert_called_once_with(
        "contributions",
        dest_dir=mock_download.call_args.kwargs["dest_dir"],
        tail_data_rows=_IL_FRESHNESS_TAIL_ROWS,
    )
    mock_build_check.assert_called_once()
    observed_payload = mock_build_check.call_args.args[0]
    assert observed_payload.jurisdiction == "state/IL"
    assert observed_payload.date_column == "RcvDate"
    assert observed_payload.source_url == "https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx"
    assert observed_payload.artifact_url == "https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx"
    assert observed_payload.parsed_row_count == 2
    assert observed_payload.max_transaction_date == date(2026, 3, 29)

    escaped_path = tmp_path / "escaped.txt"
    with (
        patch(
            "domains.campaign_finance.quality.freshness.download_il_data",
            return_value=escaped_path,
        ),
        patch(
            "domains.campaign_finance.quality.freshness.il_column_for_semantic_path",
            return_value="RcvDate",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.il_data_source_url_for_data_type",
            return_value="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        ),
        patch(
            "domains.campaign_finance.quality.freshness.il_bulk_download_url_for_data_type",
            return_value="https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx",
        ),
    ):
        with pytest.raises(ValueError, match="escaped the temporary directory"):
            _probe_il_contributions()


@patch("domains.campaign_finance.quality.freshness._probe_contributions", return_value=_fake_check("pass"))
def test_state_probes_share_common_probe_flow(mock_probe_contributions: MagicMock) -> None:
    _probe_il_contributions()
    _probe_in_contributions()
    _probe_mn_contributions()
    _probe_nj_contributions()

    assert mock_probe_contributions.call_count == 4
    jurisdictions = [call.args[0].jurisdiction for call in mock_probe_contributions.call_args_list]
    assert jurisdictions == ["state/IL", "state/IN", "state/MN", "state/NJ"]
