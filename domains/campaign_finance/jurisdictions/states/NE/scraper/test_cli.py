from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.NE.scraper import cli
from domains.campaign_finance.jurisdictions.states.load_utils import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTION_LOAN_PATH = _FIXTURE_DIR / "sample_contribution_loan.csv"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.25,
    )


def test_build_argument_parser_accepts_all_ne_data_types() -> None:
    parser = cli._build_argument_parser()
    for data_type in ("contributions", "expenditures", "loans"):
        args = parser.parse_args(["--year", "2026", "--path", "/tmp/sample.csv", "--data-type", data_type])
        assert args.data_type == data_type


def test_build_argument_parser_rejects_path_and_download_together() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--year", "2026", "--path", "/tmp/sample.csv", "--download", "--data-type", "contributions"]
        )


def test_run_ne_refresh_executes_path_mode(monkeypatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    load_path = MagicMock(return_value=load_result)
    resolve_input_path = MagicMock(return_value=(_SAMPLE_CONTRIBUTION_LOAN_PATH, None))

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)

    result = cli.run_ne_refresh(
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTION_LOAN_PATH,
        year=2026,
        year_from=2022,
        limit=4,
    )

    assert result == load_result
    load_path.assert_called_once_with(
        connection,
        _SAMPLE_CONTRIBUTION_LOAN_PATH,
        data_type="contributions",
        year=2026,
        year_from=2022,
        limit=4,
    )
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_ne_refresh_requires_path_or_download() -> None:
    with pytest.raises(ValueError, match="requires either path or download mode"):
        cli.run_ne_refresh(data_type="loans")


def test_main_dry_run_reports_row_count_without_db(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "_resolve_input_path", MagicMock(return_value=(_SAMPLE_CONTRIBUTION_LOAN_PATH, None)))
    monkeypatch.setattr(cli, "_count_rows", MagicMock(return_value=2))
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(
        ["--year", "2026", "--path", str(_SAMPLE_CONTRIBUTION_LOAN_PATH), "--data-type", "contributions", "--dry-run"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    assert "NE contributions dry-run: parsed 2 rows" in captured.out
