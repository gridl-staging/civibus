"""Unit tests for the quality check CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.cli import (
    _discover_and_run,
    _validate_cli_arguments,
    build_argument_parser,
    main,
)
from domains.campaign_finance.quality.models import (
    CheckResult,
    JurisdictionSummary,
    QualityReport,
)


@pytest.fixture(autouse=True)
def _mock_freshness_checks() -> None:
    with patch("domains.campaign_finance.quality.cli.run_freshness_checks", return_value=[]):
        yield


class TestArgumentParser:
    def test_no_args_accepted(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args([])
        assert args.jurisdiction is None
        assert args.check is None

    def test_jurisdiction_filter(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args(["--jurisdiction", "state/CO"])
        assert args.jurisdiction == "state/CO"

    def test_check_filter(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args(["--check", "record_count"])
        assert args.check == "record_count"

    def test_graph_edges_check_filter(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args(["--check", "graph_edges"])
        assert args.check == "graph_edges"
        _validate_cli_arguments(args)

    def test_both_filters(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args(["--jurisdiction", "federal/fec", "--check", "null_rate"])
        assert args.jurisdiction == "federal/fec"
        assert args.check == "null_rate"

    def test_artifact_path_argument(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args(["--artifact-path", "tmp/report.json"])
        assert args.artifact_path == "tmp/report.json"


class TestMainExitCodes:
    def _make_report(self, status: str) -> QualityReport:
        """Build a report with the given effective status."""
        if status == "pass":
            checks = [CheckResult(name="test", status="pass")]
        elif status == "fail":
            checks = [CheckResult(name="test", status="fail")]
        elif status == "error":
            checks = [CheckResult(name="test", status="error")]
        else:
            checks = [CheckResult(name="test", status="warn")]

        return QualityReport(
            summaries=[
                JurisdictionSummary(jurisdiction="test", check_results=checks),
            ],
        )

    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_0_on_pass(self, mock_get_conn: MagicMock, mock_run: MagicMock, capsys) -> None:
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_run.return_value = self._make_report("pass")

        exit_code = main([])
        assert exit_code == 0
        mock_conn.close.assert_called_once()

        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "pass"

    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_1_on_fail(self, mock_get_conn: MagicMock, mock_run: MagicMock) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_run.return_value = self._make_report("fail")

        exit_code = main([])
        assert exit_code == 1

    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_1_on_error(self, mock_get_conn: MagicMock, mock_run: MagicMock) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_run.return_value = self._make_report("error")

        exit_code = main([])
        assert exit_code == 1

    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_0_on_warn(self, mock_get_conn: MagicMock, mock_run: MagicMock) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_run.return_value = self._make_report("warn")

        exit_code = main([])
        assert exit_code == 0

    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_1_on_connection_error(self, mock_get_conn: MagicMock, capsys) -> None:
        mock_get_conn.side_effect = RuntimeError("Cannot connect")

        exit_code = main([])
        assert exit_code == 1
        assert "Cannot connect" in capsys.readouterr().err

    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_connection_closed_on_error(self, mock_get_conn: MagicMock, mock_run: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_run.side_effect = RuntimeError("check error")

        exit_code = main([])
        assert exit_code == 1
        mock_conn.close.assert_called_once()

    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_2_on_invalid_check_filter(self, mock_get_conn: MagicMock, capsys) -> None:
        exit_code = main(["--check", "not-a-real-check"])
        assert exit_code == 2
        mock_get_conn.assert_not_called()
        assert "Unsupported --check value" in capsys.readouterr().err

    @patch("domains.campaign_finance.quality.cli.get_connection")
    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    def test_unknown_jurisdiction_filter_is_not_rejected(
        self,
        mock_run: MagicMock,
        mock_get_conn: MagicMock,
        capsys,
    ) -> None:
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_run.return_value = QualityReport(jurisdiction_filter="state/ZZ")

        exit_code = main(["--jurisdiction", "state/ZZ"])

        assert exit_code == 0
        mock_run.assert_called_once()
        assert mock_run.call_args.args[1] == "state/ZZ"
        assert json.loads(capsys.readouterr().out)["jurisdiction_filter"] == "state/ZZ"

    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_exit_2_on_unknown_flag(self, mock_get_conn: MagicMock, capsys) -> None:
        exit_code = main(["--unknown-flag"])
        assert exit_code == 2
        mock_get_conn.assert_not_called()
        assert "unrecognized arguments" in capsys.readouterr().err


class TestEmptyReport:
    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_empty_report_exits_0(self, mock_get_conn: MagicMock, mock_run: MagicMock, capsys) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_run.return_value = QualityReport()

        exit_code = main([])
        assert exit_code == 0

        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "pass"
        assert output["total_checks"] == 0


class TestFreshnessCliRouting:
    def test_validate_cli_accepts_freshness_check(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args(["--check", "freshness"])
        _validate_cli_arguments(args)

    def test_check_freshness_skips_database_path(self, capsys) -> None:
        freshness_summary = JurisdictionSummary(
            jurisdiction="state/MN",
            baseline_urls=["https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/"],
            check_results=[CheckResult(name="freshness", status="pass", message="ok")],
        )
        with (
            patch(
                "domains.campaign_finance.quality.cli.run_freshness_checks", return_value=[freshness_summary]
            ) as mock_run_freshness,
            patch("domains.campaign_finance.quality.cli.get_connection") as mock_get_connection,
            patch("domains.campaign_finance.quality.cli._discover_and_run") as mock_discover,
        ):
            exit_code = main(["--check", "freshness"])

        assert exit_code == 0
        mock_get_connection.assert_not_called()
        mock_discover.assert_not_called()
        mock_run_freshness.assert_called_once_with(None)
        payload = json.loads(capsys.readouterr().out)
        assert payload["check_filter"] == "freshness"
        assert payload["summaries"][0]["check_results"][0]["name"] == "freshness"

    def test_unfiltered_main_merges_db_and_freshness_by_jurisdiction(self, capsys) -> None:
        db_report = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="state/MN",
                    data_source_ids=["db-source-mn"],
                    baseline_urls=["https://db.example/mn"],
                    record_count=5,
                    check_results=[CheckResult(name="record_count_reconciliation", status="pass", message="ok")],
                ),
                JurisdictionSummary(
                    jurisdiction="state/IN",
                    data_source_ids=["db-source-in"],
                    baseline_urls=["https://db.example/in"],
                    record_count=7,
                    check_results=[CheckResult(name="record_count_reconciliation", status="warn", message="warn")],
                ),
            ],
        )
        freshness_summaries = [
            JurisdictionSummary(
                jurisdiction="state/MN",
                data_source_ids=["freshness-source-mn"],
                baseline_urls=["https://db.example/mn", "https://freshness.example/mn"],
                check_results=[CheckResult(name="freshness", status="warn", message="stale")],
            ),
            JurisdictionSummary(
                jurisdiction="state/NJ",
                baseline_urls=["https://freshness.example/nj"],
                check_results=[CheckResult(name="freshness", status="pass", message="ok")],
            ),
        ]

        with (
            patch(
                "domains.campaign_finance.quality.cli.get_connection", return_value=MagicMock()
            ) as mock_get_connection,
            patch("domains.campaign_finance.quality.cli._discover_and_run", return_value=db_report) as mock_discover,
            patch(
                "domains.campaign_finance.quality.cli.run_freshness_checks",
                return_value=freshness_summaries,
            ) as mock_run_freshness,
        ):
            exit_code = main([])

        assert exit_code == 0
        mock_get_connection.assert_called_once()
        mock_discover.assert_called_once()
        mock_run_freshness.assert_called_once_with(None)
        payload = json.loads(capsys.readouterr().out)
        assert [summary["jurisdiction"] for summary in payload["summaries"]] == ["state/MN", "state/IN", "state/NJ"]

        merged_mn = payload["summaries"][0]
        assert merged_mn["data_source_ids"] == ["db-source-mn", "freshness-source-mn"]
        assert merged_mn["baseline_urls"] == ["https://db.example/mn", "https://freshness.example/mn"]
        assert [check["name"] for check in merged_mn["check_results"]] == [
            "record_count_reconciliation",
            "freshness",
        ]
        assert merged_mn["record_count"] == 5

    @pytest.mark.parametrize(
        ("freshness_jurisdiction", "expected_jurisdictions"),
        [
            ("state/MN", ["state/MN"]),
            ("state/NJ", ["state/MN", "state/NJ"]),
        ],
    )
    def test_unfiltered_main_any_freshness_fail_forces_report_fail(
        self,
        freshness_jurisdiction: str,
        expected_jurisdictions: list[str],
        capsys,
    ) -> None:
        db_report = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="state/MN",
                    data_source_ids=["db-source-mn"],
                    baseline_urls=["https://db.example/mn"],
                    record_count=10,
                    check_results=[CheckResult(name="record_count_reconciliation", status="pass", message="ok")],
                )
            ]
        )
        freshness_summaries = [
            JurisdictionSummary(
                jurisdiction=freshness_jurisdiction,
                baseline_urls=[f"https://freshness.example/{freshness_jurisdiction.lower()}"],
                check_results=[CheckResult(name="freshness", status="fail", message="stale")],
            )
        ]

        with (
            patch("domains.campaign_finance.quality.cli.get_connection", return_value=MagicMock()),
            patch("domains.campaign_finance.quality.cli._discover_and_run", return_value=db_report),
            patch("domains.campaign_finance.quality.cli.run_freshness_checks", return_value=freshness_summaries),
        ):
            exit_code = main([])

        assert exit_code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "fail"
        assert any(summary["status"] == "fail" for summary in payload["summaries"])
        assert [summary["jurisdiction"] for summary in payload["summaries"]] == expected_jurisdictions

    @pytest.mark.parametrize("check_name", ["record_count", "graph_edges"])
    def test_db_only_check_does_not_invoke_freshness(self, check_name: str) -> None:
        with (
            patch("domains.campaign_finance.quality.cli.get_connection", return_value=MagicMock()),
            patch("domains.campaign_finance.quality.cli._discover_and_run", return_value=QualityReport()),
            patch("domains.campaign_finance.quality.cli.run_freshness_checks") as mock_run_freshness,
        ):
            exit_code = main(["--check", check_name])

        assert exit_code == 0
        mock_run_freshness.assert_not_called()

    def test_json_output_includes_freshness_result_structure(self, capsys) -> None:
        with (
            patch("domains.campaign_finance.quality.cli.get_connection") as mock_get_connection,
            patch(
                "domains.campaign_finance.quality.cli.run_freshness_checks",
                return_value=[
                    JurisdictionSummary(
                        jurisdiction="state/IN",
                        baseline_urls=["https://campaignfinance.in.gov/public"],
                        check_results=[
                            CheckResult(
                                name="freshness",
                                status="fail",
                                metric_name="max_transaction_age_days",
                                metric_value=48.0,
                                details={"max_transaction_date": "2026-02-12"},
                            )
                        ],
                    )
                ],
            ),
        ):
            exit_code = main(["--check", "freshness"])

        assert exit_code == 1
        mock_get_connection.assert_not_called()
        payload = json.loads(capsys.readouterr().out)
        freshness_result = payload["summaries"][0]["check_results"][0]
        assert freshness_result["name"] == "freshness"
        assert freshness_result["metric_name"] == "max_transaction_age_days"
        assert freshness_result["details"]["max_transaction_date"] == "2026-02-12"


class TestJsonOutput:
    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_stdout_is_valid_json(self, mock_get_conn: MagicMock, mock_run: MagicMock, capsys) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_run.return_value = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="federal/fec",
                    check_results=[
                        CheckResult(name="record_count", status="pass", metric_value=100.0),
                    ],
                ),
            ],
        )

        main([])
        output = json.loads(capsys.readouterr().out)
        assert "summaries" in output
        assert output["summaries"][0]["jurisdiction"] == "federal/fec"

    @patch("domains.campaign_finance.quality.cli._discover_and_run")
    @patch("domains.campaign_finance.quality.cli.get_connection")
    def test_filters_passed_through(self, mock_get_conn: MagicMock, mock_run: MagicMock, capsys) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_run.return_value = QualityReport(
            jurisdiction_filter="state/CO",
            check_filter="null_rate",
        )

        main(["--jurisdiction", "state/CO", "--check", "null_rate"])
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][1] == "state/CO"  # jurisdiction_filter
        assert call_args[0][2] == "null_rate"  # check_filter


class TestArtifactWriting:
    def test_main_writes_report_artifact_when_requested(self, tmp_path: Path, capsys) -> None:
        artifact_path = tmp_path / "quality-report.json"
        report = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="state/IL",
                    check_results=[CheckResult(name="freshness", status="pass", message="ok")],
                )
            ]
        )

        with (
            patch("domains.campaign_finance.quality.cli.run_freshness_checks", return_value=report.summaries),
            patch("domains.campaign_finance.quality.cli.get_connection") as mock_get_connection,
        ):
            exit_code = main(["--check", "freshness", "--artifact-path", str(artifact_path)])

        assert exit_code == 0
        mock_get_connection.assert_not_called()
        assert json.loads(capsys.readouterr().out)["status"] == "pass"
        assert json.loads(artifact_path.read_text(encoding="utf-8"))["status"] == "pass"

    def test_main_returns_1_when_artifact_write_fails(self, tmp_path: Path, capsys) -> None:
        artifact_path = tmp_path / "quality-report.json"
        freshness_summaries = [
            JurisdictionSummary(
                jurisdiction="state/IL",
                check_results=[CheckResult(name="freshness", status="pass", message="ok")],
            )
        ]

        with (
            patch(
                "domains.campaign_finance.quality.cli.run_freshness_checks",
                return_value=freshness_summaries,
            ),
            patch(
                "domains.campaign_finance.quality.cli._write_report_artifact",
                side_effect=OSError("disk full"),
            ),
            patch("domains.campaign_finance.quality.cli.get_connection") as mock_get_connection,
        ):
            exit_code = main(["--check", "freshness", "--artifact-path", str(artifact_path)])

        assert exit_code == 1
        mock_get_connection.assert_not_called()
        captured = capsys.readouterr()
        assert json.loads(captured.out)["status"] == "pass"
        assert "failed to write report artifact" in captured.err.lower()


class TestRunChecksForDataSource:
    """Verify that _run_checks_for_data_source dispatches to the correct checks."""

    def _run_with_filter(self, check_filter: str | None) -> list[str]:
        from domains.campaign_finance.quality.cli import _run_checks_for_data_source

        ds_id = uuid4()
        with (
            patch(
                "domains.campaign_finance.quality.cli.check_record_count_reconciliation",
                return_value=CheckResult(name="record_count_reconciliation", status="pass"),
            ),
            patch(
                "domains.campaign_finance.quality.cli.check_key_field_completeness",
                return_value=[CheckResult(name="completeness_source_record_key", status="pass")],
            ),
            patch(
                "domains.campaign_finance.quality.cli.check_null_rate",
                side_effect=[
                    CheckResult(name="null_rate_source_record_key", status="pass"),
                    CheckResult(name="null_rate_source_url", status="pass"),
                ],
            ),
            patch(
                "domains.campaign_finance.quality.cli.check_duplicate_records",
                return_value=CheckResult(name="duplicate_records", status="pass"),
            ),
            patch(
                "domains.campaign_finance.quality.cli.check_amount_sanity",
                return_value=CheckResult(name="amount_sanity", status="pass"),
            ),
            patch(
                "domains.campaign_finance.quality.cli.check_date_range",
                return_value=CheckResult(name="date_range", status="pass"),
            ),
            patch(
                "domains.campaign_finance.quality.cli.check_graph_edge_presence",
                return_value=CheckResult(name="graph_edge_presence", status="pass"),
            ),
        ):
            results = _run_checks_for_data_source(MagicMock(), str(ds_id), "Test", check_filter)
        return [r.name for r in results]

    def test_no_filter_runs_all_checks(self) -> None:
        names = self._run_with_filter(None)
        assert names == [
            "record_count_reconciliation",
            "completeness_source_record_key",
            "null_rate_source_record_key",
            "null_rate_source_url",
            "duplicate_records",
            "amount_sanity",
            "date_range",
            "graph_edge_presence",
        ]

    def test_record_count_filter(self) -> None:
        names = self._run_with_filter("record_count")
        assert names == ["record_count_reconciliation"]

    def test_duplicates_filter(self) -> None:
        names = self._run_with_filter("duplicates")
        assert names == ["duplicate_records"]

    def test_amount_filter(self) -> None:
        names = self._run_with_filter("amount")
        assert names == ["amount_sanity"]

    def test_date_range_filter(self) -> None:
        names = self._run_with_filter("date_range")
        assert names == ["date_range"]

    def test_graph_edges_filter(self) -> None:
        names = self._run_with_filter("graph_edges")
        assert names == ["graph_edge_presence"]

    def test_completeness_filter(self) -> None:
        names = self._run_with_filter("completeness")
        assert names == ["completeness_source_record_key"]

    def test_null_rate_filter(self) -> None:
        names = self._run_with_filter("null_rate")
        # null_rate runs for source_record_key and source_url
        assert len(names) == 2
        assert all("null_rate" in n for n in names)

    def test_null_rate_filter_checks_source_record_key_and_source_url(self) -> None:
        from domains.campaign_finance.quality.cli import _run_checks_for_data_source

        ds_id = uuid4()
        with (
            patch("domains.campaign_finance.quality.cli.check_record_count_reconciliation"),
            patch("domains.campaign_finance.quality.cli.check_key_field_completeness"),
            patch(
                "domains.campaign_finance.quality.cli.check_null_rate",
                side_effect=[
                    CheckResult(name="null_rate_source_record_key", status="pass"),
                    CheckResult(name="null_rate_source_url", status="pass"),
                ],
            ) as mock_null_rate,
            patch("domains.campaign_finance.quality.cli.check_duplicate_records"),
            patch("domains.campaign_finance.quality.cli.check_amount_sanity"),
            patch("domains.campaign_finance.quality.cli.check_date_range"),
        ):
            results = _run_checks_for_data_source(MagicMock(), str(ds_id), "Test", "null_rate")

        assert [result.name for result in results] == [
            "null_rate_source_record_key",
            "null_rate_source_url",
        ]
        assert [call.args[3] for call in mock_null_rate.call_args_list] == [
            "source_record_key",
            "source_url",
        ]


class TestDiscoverAndRun:
    @patch("domains.campaign_finance.quality.cli._run_checks_for_data_source", return_value=[])
    @patch("domains.campaign_finance.quality.cli.count_source_records", side_effect=[3, 2])
    @patch(
        "domains.campaign_finance.quality.cli.fetch_data_source_metadata",
        side_effect=[
            ("TRACER Bulk Download — Contributions", "https://www.coloradosos.gov/tracer"),
            ("TRACER Bulk Download — Expenditures", "https://www.coloradosos.gov/tracer"),
        ],
    )
    @patch(
        "domains.campaign_finance.quality.cli.list_data_source_jurisdictions",
        return_value=["state/CO"],
    )
    @patch("domains.campaign_finance.quality.cli.resolve_data_source_ids")
    def test_populates_deduplicated_baseline_urls(
        self,
        mock_resolve: MagicMock,
        _mock_list_jurisdictions: MagicMock,
        _mock_fetch_metadata: MagicMock,
        _mock_count_records: MagicMock,
        _mock_run_checks: MagicMock,
    ) -> None:
        ds_ids = [uuid4(), uuid4()]
        mock_resolve.return_value = ds_ids

        report = _discover_and_run(MagicMock(), "state/CO", None)

        assert len(report.summaries) == 1
        summary = report.summaries[0]
        assert summary.jurisdiction == "state/CO"
        assert summary.data_source_ids == [str(ds_id) for ds_id in ds_ids]
        assert summary.baseline_urls == ["https://www.coloradosos.gov/tracer"]
        assert summary.record_count == 5

    @patch(
        "domains.campaign_finance.quality.cli.list_data_source_jurisdictions",
        return_value=["state/TX"],
    )
    @patch("domains.campaign_finance.quality.cli.resolve_data_source_ids")
    def test_discovers_jurisdictions_from_data_source_scope(
        self,
        mock_resolve: MagicMock,
        _mock_list_jurisdictions: MagicMock,
    ) -> None:
        ds_id = uuid4()
        mock_resolve.return_value = [ds_id]
        with (
            patch(
                "domains.campaign_finance.quality.cli.fetch_data_source_metadata",
                return_value=("Texas Source", "https://example.com/tx"),
            ),
            patch("domains.campaign_finance.quality.cli.count_source_records", return_value=7),
            patch("domains.campaign_finance.quality.cli._run_checks_for_data_source", return_value=[]),
        ):
            report = _discover_and_run(MagicMock(), "state/TX", None)

        assert [summary.jurisdiction for summary in report.summaries] == ["state/TX"]
        assert mock_resolve.call_args.kwargs["domain"] == "campaign_finance"

    @patch(
        "domains.campaign_finance.quality.cli.list_data_source_jurisdictions",
        return_value=["state/TX"],
    )
    @patch("domains.campaign_finance.quality.cli.resolve_data_source_ids")
    def test_unknown_jurisdiction_filter_returns_empty_report(
        self,
        mock_resolve: MagicMock,
        _mock_list_jurisdictions: MagicMock,
    ) -> None:
        report = _discover_and_run(MagicMock(), "state/ZZ", None)

        assert report.summaries == []
        mock_resolve.assert_not_called()

    @patch("domains.campaign_finance.quality.cli._run_checks_for_data_source", return_value=[])
    @patch("domains.campaign_finance.quality.cli.count_source_records", return_value=1)
    @patch(
        "domains.campaign_finance.quality.cli.fetch_data_source_metadata",
        return_value=("State Source", "https://example.com/source"),
    )
    @patch(
        "domains.campaign_finance.quality.cli.list_data_source_jurisdictions",
        return_value=["state/CA", "state/MN", "state/WA"],
    )
    @patch("domains.campaign_finance.quality.cli.resolve_data_source_ids")
    def test_discovers_all_states_from_data_source_jurisdictions(
        self,
        mock_resolve: MagicMock,
        _mock_list_jurisdictions: MagicMock,
        _mock_fetch_metadata: MagicMock,
        _mock_count_records: MagicMock,
        _mock_run_checks: MagicMock,
    ) -> None:
        mock_resolve.side_effect = [[uuid4()], [uuid4()], [uuid4()]]

        report = _discover_and_run(MagicMock(), None, "record_count")

        assert [summary.jurisdiction for summary in report.summaries] == [
            "state/CA",
            "state/MN",
            "state/WA",
        ]
        assert [call.kwargs["jurisdiction"] for call in mock_resolve.call_args_list] == [
            "state/CA",
            "state/MN",
            "state/WA",
        ]
