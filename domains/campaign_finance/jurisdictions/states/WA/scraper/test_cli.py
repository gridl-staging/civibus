from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call

import pytest

from domains.campaign_finance.jurisdictions.states.WA.scraper import cli
from domains.campaign_finance.jurisdictions.states.WA.scraper.download import WASourceSnapshot
from domains.campaign_finance.jurisdictions.states.WA.scraper.load import (
    LoadResult,
    WAContributionPageChanges,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_independent_expenditures.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=5,
        skipped=2,
        quarantined=1,
        superseded=0,
        errors=0,
        elapsed_seconds=0.75,
    )


def test_build_argument_parser_parses_path_input() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", "contributions"])

    assert args.path == Path("/tmp/sample.csv")
    assert args.download is False
    assert args.data_type == "contributions"
    assert args.limit is None
    assert args.dry_run is False


def test_build_argument_parser_parses_download_input() -> None:
    args = cli._build_argument_parser().parse_args(["--download", "--data-type", "loans", "--limit", "10"])

    assert args.download is True
    assert args.path is None
    assert args.data_type == "loans"
    assert args.limit == 10


def test_build_argument_parser_accepts_independent_expenditures_data_type() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", str(_SAMPLE_INDEPENDENT_EXPENDITURES_PATH), "--data-type", "independent_expenditures"]
    )

    assert args.data_type == "independent_expenditures"


def test_build_argument_parser_rejects_path_and_download_together() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--path",
                "/tmp/sample.csv",
                "--download",
                "--data-type",
                "contributions",
            ]
        )


def test_main_loads_path_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", load_with_filings)

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_with_filings.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, limit=None)
    assert "WA contributions load complete" in captured.out
    assert "inserted=5" in captured.out
    assert captured.err == ""
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_download_mode_resolves_path_and_loads(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    complete_refresh = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "_run_complete_contributions_refresh", complete_refresh)

    exit_code = cli.main(["--download", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    complete_refresh.assert_called_once()
    assert complete_refresh.call_args.args[0] is connection
    assert complete_refresh.call_args.args[1].name.startswith("wa-contributions-")
    assert "WA contributions load complete" in captured.out
    assert captured.err == ""
    connection.close.assert_called_once_with()


def test_main_download_mode_passes_limit_to_download(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    downloaded_path = tmp_path / "wa_loans.csv"

    download_wa_csv = MagicMock(return_value=downloaded_path)
    monkeypatch.setattr(cli, "download_wa_csv", download_wa_csv)
    monkeypatch.setattr(
        cli,
        "parse_loans",
        MagicMock(return_value=iter([{"a": "1"}, {"a": "2"}])),
    )

    exit_code = cli.main(["--download", "--data-type", "loans", "--limit", "2", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_wa_csv.assert_called_once_with("loans", dest_dir=ANY, limit=2)
    assert "WA loans dry-run: parsed 2 rows" in captured.out


def test_main_dry_run_uses_path_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_connection", MagicMock())
    monkeypatch.setattr(
        cli,
        "parse_contributions",
        MagicMock(return_value=iter([{"a": "1"}, {"a": "2"}, {"a": "3"}])),
    )
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", MagicMock())

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    cli.load_wa_contributions_with_filings.assert_not_called()
    assert "WA contributions dry-run: parsed 3 rows" in captured.out


def test_main_routes_expenditures_to_expenditure_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", MagicMock())
    load_expenditures = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_wa_expenditures_with_filings", load_expenditures)

    exit_code = cli.main(["--path", str(_SAMPLE_EXPENDITURES_PATH), "--data-type", "expenditures"])

    assert exit_code == 0
    load_expenditures.assert_called_once_with(connection, _SAMPLE_EXPENDITURES_PATH, limit=None)
    cli.load_wa_contributions_with_filings.assert_not_called()


def test_main_routes_loans_to_loan_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", MagicMock())
    monkeypatch.setattr(cli, "load_wa_expenditures_with_filings", MagicMock())
    load_loans = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_wa_loans_with_filings", load_loans)

    exit_code = cli.main(["--path", str(_SAMPLE_LOANS_PATH), "--data-type", "loans"])

    assert exit_code == 0
    load_loans.assert_called_once_with(connection, _SAMPLE_LOANS_PATH, limit=None)


def test_main_routes_independent_expenditures_to_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", MagicMock())
    monkeypatch.setattr(cli, "load_wa_expenditures_with_filings", MagicMock())
    monkeypatch.setattr(cli, "load_wa_loans_with_filings", MagicMock())
    load_independent_expenditures = MagicMock(return_value=load_result)
    monkeypatch.setattr(
        cli,
        "load_wa_independent_expenditures_with_filings",
        load_independent_expenditures,
    )

    exit_code = cli.main(
        ["--path", str(_SAMPLE_INDEPENDENT_EXPENDITURES_PATH), "--data-type", "independent_expenditures"]
    )

    assert exit_code == 0
    load_independent_expenditures.assert_called_once_with(
        connection,
        _SAMPLE_INDEPENDENT_EXPENDITURES_PATH,
        limit=None,
    )


def test_main_returns_error_and_closes_connection_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_wa_contributions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "WA ingest failed: load failed" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


def test_run_wa_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", load_with_filings)

    result = cli.run_wa_refresh(
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS_PATH,
        limit=6,
    )

    assert result == load_result
    load_with_filings.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, limit=6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_wa_refresh_executes_independent_expenditure_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_independent_expenditures = MagicMock(return_value=load_result)
    monkeypatch.setattr(
        cli,
        "load_wa_independent_expenditures_with_filings",
        load_independent_expenditures,
    )

    result = cli.run_wa_refresh(
        data_type="independent_expenditures",
        path=_SAMPLE_INDEPENDENT_EXPENDITURES_PATH,
        limit=4,
    )

    assert result == load_result
    load_independent_expenditures.assert_called_once_with(connection, _SAMPLE_INDEPENDENT_EXPENDITURES_PATH, limit=4)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_wa_refresh_rejects_unsupported_data_type(monkeypatch: pytest.MonkeyPatch) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="Unsupported WA data type: receipts"):
        cli.run_wa_refresh(data_type="receipts", path=_SAMPLE_CONTRIBUTIONS_PATH)

    get_connection.assert_not_called()


def test_complete_contributions_refresh_proves_6358218_unchanged_rows_without_full_reload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    last_pull_at = datetime(2026, 8, 26, 4, 41, 59, tzinfo=timezone.utc)
    snapshot = WASourceSnapshot(
        row_count=6_358_218,
        max_updated_at=datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc),
        version_sum=8_100_000,
    )
    monkeypatch.setattr(
        cli,
        "select_wa_contributions_refresh_baseline",
        MagicMock(return_value=SimpleNamespace(active_source_records=6_358_218, last_pull_at=last_pull_at)),
    )
    fetch_snapshot = MagicMock(side_effect=[snapshot, snapshot])
    monkeypatch.setattr(cli, "fetch_wa_source_snapshot", fetch_snapshot)
    monkeypatch.setattr(cli, "fetch_wa_source_change_count", MagicMock(return_value=0))
    download_page = MagicMock(side_effect=AssertionError("an unchanged complete source must not be fully reloaded"))
    monkeypatch.setattr(cli, "download_wa_csv_page", download_page)
    monkeypatch.setattr(cli, "count_active_wa_source_records", MagicMock(return_value=6_358_218))

    result = cli._run_complete_contributions_refresh(
        connection,
        tmp_path,
        monotonic=lambda: 10.0,
        budget_seconds=25 * 60,
    )

    assert result.source_complete is True
    assert result.source_row_count == 6_358_218
    assert (result.inserted, result.skipped, result.quarantined, result.superseded, result.errors) == (0, 0, 0, 0, 0)
    assert fetch_snapshot.call_count == 2
    cli.fetch_wa_source_change_count.assert_called_once_with(
        "contributions",
        updated_after=datetime(2026, 8, 25, 4, 41, 59, tzinfo=timezone.utc),
        updated_through=snapshot.max_updated_at,
    )
    download_page.assert_not_called()


def test_contributions_refresh_timeout_keeps_committed_progress_resumable_but_refuses_freshness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    snapshot = WASourceSnapshot(
        row_count=6_358_218,
        max_updated_at=datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc),
        version_sum=8_100_000,
    )
    monkeypatch.setattr(
        cli,
        "select_wa_contributions_refresh_baseline",
        MagicMock(return_value=SimpleNamespace(active_source_records=6_300_000, last_pull_at=None)),
    )
    monkeypatch.setattr(cli, "fetch_wa_source_snapshot", MagicMock(return_value=snapshot))
    monkeypatch.setattr(cli, "fetch_wa_source_change_count", MagicMock(return_value=58_218))
    page_path = tmp_path / "page.csv"
    page_path.write_text("id\n1\n", encoding="utf-8")
    monkeypatch.setattr(cli, "download_wa_csv_page", MagicMock(return_value=page_path))
    monkeypatch.setattr(
        cli,
        "filter_wa_contribution_page_changes",
        MagicMock(
            return_value=WAContributionPageChanges(
                source_rows=50_000,
                changed_rows=50_000,
                path=page_path,
            )
        ),
    )
    load_page = MagicMock(
        return_value=LoadResult(
            inserted=50_000,
            skipped=0,
            quarantined=0,
            superseded=0,
            errors=0,
            elapsed_seconds=1.0,
        )
    )
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", load_page)
    ticks = iter([0.0, 0.0, 1_501.0])

    with pytest.raises(cli.WAContributionsIncompleteError, match="resume"):
        cli._run_complete_contributions_refresh(
            connection,
            tmp_path,
            monotonic=lambda: next(ticks),
            budget_seconds=1_500,
        )

    load_page.assert_called_once_with(connection, page_path, limit=None)
    connection.rollback.assert_not_called()


def test_contributions_refresh_resumes_from_persisted_page_hashes_without_reloading_committed_page(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    snapshot = WASourceSnapshot(
        row_count=100_000,
        max_updated_at=datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc),
        version_sum=130_000,
    )
    monkeypatch.setattr(
        cli,
        "select_wa_contributions_refresh_baseline",
        MagicMock(return_value=SimpleNamespace(active_source_records=0, last_pull_at=None)),
    )
    monkeypatch.setattr(cli, "fetch_wa_source_snapshot", MagicMock(side_effect=[snapshot, snapshot, snapshot]))
    monkeypatch.setattr(cli, "fetch_wa_source_change_count", MagicMock(return_value=100_000))
    downloaded_paths = {offset: tmp_path / f"page_{offset}.csv" for offset in (0, 50_000)}
    monkeypatch.setattr(
        cli,
        "download_wa_csv_page",
        MagicMock(side_effect=lambda _kind, _dir, *, offset, **_kwargs: downloaded_paths[offset]),
    )
    first_changed = tmp_path / "changed_first.csv"
    second_changed = tmp_path / "changed_second.csv"
    filter_page = MagicMock(
        side_effect=[
            WAContributionPageChanges(source_rows=50_000, changed_rows=50_000, path=first_changed),
            WAContributionPageChanges(source_rows=50_000, changed_rows=0, path=None),
            WAContributionPageChanges(source_rows=50_000, changed_rows=50_000, path=second_changed),
        ]
    )
    monkeypatch.setattr(cli, "filter_wa_contribution_page_changes", filter_page)
    load_page = MagicMock(
        return_value=LoadResult(
            inserted=50_000,
            skipped=0,
            quarantined=0,
            superseded=0,
            errors=0,
            elapsed_seconds=1.0,
        )
    )
    monkeypatch.setattr(cli, "load_wa_contributions_with_filings", load_page)

    first_ticks = iter([0.0, 0.0, 1_501.0])
    with pytest.raises(cli.WAContributionsIncompleteError, match="resume"):
        cli._run_complete_contributions_refresh(
            connection,
            tmp_path,
            monotonic=lambda: next(first_ticks),
            budget_seconds=1_500,
        )

    monkeypatch.setattr(cli, "count_active_wa_source_records", MagicMock(return_value=100_000))
    second_ticks = iter([0.0, 0.0, 1.0, 2.0, 3.0])
    result = cli._run_complete_contributions_refresh(
        connection,
        tmp_path,
        monotonic=lambda: next(second_ticks),
        budget_seconds=1_500,
    )

    assert result.source_complete is True
    assert result.source_row_count == 100_000
    assert load_page.call_args_list == [
        call(connection, first_changed, limit=None),
        call(connection, second_changed, limit=None),
    ]


def test_contributions_refresh_refuses_short_page_even_when_database_count_matches_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    snapshot = WASourceSnapshot(
        row_count=50_000,
        max_updated_at=datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc),
        version_sum=65_000,
    )
    monkeypatch.setattr(
        cli,
        "select_wa_contributions_refresh_baseline",
        MagicMock(return_value=SimpleNamespace(active_source_records=50_000, last_pull_at=None)),
    )
    monkeypatch.setattr(cli, "fetch_wa_source_snapshot", MagicMock(return_value=snapshot))
    monkeypatch.setattr(cli, "fetch_wa_source_change_count", MagicMock(return_value=50_000))
    page_path = tmp_path / "short.csv"
    monkeypatch.setattr(cli, "download_wa_csv_page", MagicMock(return_value=page_path))
    monkeypatch.setattr(
        cli,
        "filter_wa_contribution_page_changes",
        MagicMock(return_value=WAContributionPageChanges(source_rows=49_999, changed_rows=0, path=None)),
    )

    with pytest.raises(cli.WAContributionsIncompleteError, match="returned 49999 of 50000"):
        cli._run_complete_contributions_refresh(connection, tmp_path, monotonic=lambda: 0.0)


def test_contributions_refresh_refuses_same_count_and_timestamp_when_source_row_version_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    initial = WASourceSnapshot(
        row_count=6_358_218,
        max_updated_at=datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc),
        version_sum=8_100_000,
    )
    changed = WASourceSnapshot(
        row_count=initial.row_count,
        max_updated_at=initial.max_updated_at,
        version_sum=initial.version_sum + 1,
    )
    monkeypatch.setattr(
        cli,
        "select_wa_contributions_refresh_baseline",
        MagicMock(
            return_value=SimpleNamespace(
                active_source_records=initial.row_count,
                last_pull_at=datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc),
            )
        ),
    )
    monkeypatch.setattr(cli, "fetch_wa_source_snapshot", MagicMock(side_effect=[initial, changed]))
    monkeypatch.setattr(cli, "fetch_wa_source_change_count", MagicMock(return_value=0))
    monkeypatch.setattr(cli, "count_active_wa_source_records", MagicMock(return_value=initial.row_count))

    with pytest.raises(cli.WAContributionsIncompleteError, match="source changed"):
        cli._run_complete_contributions_refresh(connection, tmp_path, monotonic=lambda: 0.0)


def test_runner_accepts_zero_delta_only_with_complete_source_proof_and_promotes_freshness_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.refresh import runner

    connection = MagicMock()
    result = cli.WACompleteContributionsResult(
        inserted=0,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.2,
        source_complete=True,
        source_row_count=6_358_218,
    )
    job = runner.RefreshJob(
        key="state-wa-contributions",
        domain="campaign_finance",
        jurisdiction="state/WA",
        cadence="daily",
        data_source_names=("WA PDC Contributions",),
        run_callable=MagicMock(return_value=result),
    )
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=object()))
    sync = MagicMock(return_value=6_358_218)
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync)
    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "update_refresh_run", MagicMock())

    outcome = runner.run_job(connection, job, execution_origin="operator_attended")

    assert outcome.status == "success"
    assert outcome.metadata_updates == 1
    assert "complete source rows=6358218" in outcome.message
    sync.assert_called_once()
