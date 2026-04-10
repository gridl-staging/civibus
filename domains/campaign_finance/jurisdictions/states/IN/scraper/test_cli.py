from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.IN.scraper import cli
from domains.campaign_finance.jurisdictions.states.IN.scraper.load import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=1,
        errors=0,
        elapsed_seconds=0.25,
    )


def test_build_argument_parser_accepts_in_data_types() -> None:
    for data_type in ("contributions", "expenditures"):
        args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", data_type])
        assert args.data_type == data_type


def test_build_argument_parser_rejects_path_and_download_together() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--path", "/tmp/sample.csv", "--download", "--data-type", "contributions"]
        )


def test_build_argument_parser_parses_limit_dry_run_and_year() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/sample.csv", "--data-type", "contributions", "--limit", "5", "--dry-run", "--year", "2025"]
    )

    assert args.limit == 5
    assert args.dry_run is True
    assert args.year == 2025


def test_count_rows_uses_parser_for_data_type() -> None:
    parsed_contribution_rows = cli._count_rows(_SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", limit=None)
    parsed_expenditure_rows = cli._count_rows(_SAMPLE_EXPENDITURES_PATH, data_type="expenditures", limit=3)

    assert parsed_contribution_rows == 8
    assert parsed_expenditure_rows == 3


def test_main_download_mode_requires_year(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["--download", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "--download requires --year" in captured.err


def test_main_download_mode_uses_downloaded_archive_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    downloaded_archive = tmp_path / "2025_ContributionData.csv.zip"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_in_data = MagicMock(return_value=downloaded_archive)
    monkeypatch.setattr(cli, "download_in_data", download_in_data)
    load_contributions = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_in_contributions_with_filings", load_contributions)

    exit_code = cli.main(["--download", "--year", "2025", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_in_data.assert_called_once()
    load_contributions.assert_called_once_with(connection, downloaded_archive, limit=None)
    assert "IN contributions load complete" in captured.out


def test_main_path_contributions_loads_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_contributions = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_in_contributions_with_filings", load_contributions)

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_contributions.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, limit=None)
    assert "IN contributions load complete" in captured.out
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_dry_run_reports_row_count_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "parse_contributions", MagicMock(return_value=iter([{}, {}, {}])))
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    assert "IN contributions dry-run: parsed 3 rows" in captured.out


def test_main_returns_non_zero_for_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_in_contributions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "IN ingest failed: load failed" in captured.err


def test_run_in_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(return_value=(_SAMPLE_CONTRIBUTIONS_PATH, None))
    load_path = MagicMock(return_value=load_result)
    main = MagicMock()

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "main", main)

    result = cli.run_in_refresh(
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS_PATH,
        limit=6,
    )

    assert result == load_result
    resolve_input_path.assert_called_once()
    resolved_args = resolve_input_path.call_args.args[0]
    assert resolved_args.path == _SAMPLE_CONTRIBUTIONS_PATH
    assert resolved_args.download is False
    assert resolved_args.data_type == "contributions"
    assert resolved_args.year is None
    assert resolved_args.limit == 6
    load_path.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", limit=6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
    main.assert_not_called()


def test_run_in_refresh_executes_download_mode_with_year(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(return_value=(_SAMPLE_EXPENDITURES_PATH, None))
    load_path = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_in_refresh(
        data_type="expenditures",
        download=True,
        year=2026,
        limit=2,
    )

    assert result == load_result
    resolve_input_path.assert_called_once()
    resolved_args = resolve_input_path.call_args.args[0]
    assert resolved_args.path is None
    assert resolved_args.download is True
    assert resolved_args.data_type == "expenditures"
    assert resolved_args.year == 2026
    assert resolved_args.limit == 2
    load_path.assert_called_once_with(connection, _SAMPLE_EXPENDITURES_PATH, data_type="expenditures", limit=2)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_in_refresh_requires_year_in_download_mode() -> None:
    with pytest.raises(ValueError, match="--download requires --year"):
        cli.run_in_refresh(data_type="contributions", download=True)
