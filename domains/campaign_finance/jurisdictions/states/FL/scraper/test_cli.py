from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.FL.scraper import load_supported_data_types
from domains.campaign_finance.jurisdictions.states.FL.scraper import cli
from domains.campaign_finance.jurisdictions.states.FL.scraper.load import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.txt"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.txt"
_SAMPLE_TRANSFERS_PATH = _FIXTURE_DIR / "sample_transfers.txt"
_SAMPLE_OTHER_PATH = _FIXTURE_DIR / "sample_other.txt"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=5,
        skipped=2,
        quarantined=1,
        superseded=0,
        errors=0,
        elapsed_seconds=0.75,
    )


# --- Argument parser tests ---


def test_build_argument_parser_accepts_config_derived_data_types() -> None:
    for data_type in load_supported_data_types():
        args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.txt", "--data-type", data_type])
        assert args.data_type == data_type


def test_build_argument_parser_choices_match_config_supported_types() -> None:
    parser = cli._build_argument_parser()
    data_type_action = next(action for action in parser._actions if action.dest == "data_type")

    assert tuple(data_type_action.choices) == load_supported_data_types()


def test_build_argument_parser_rejects_invalid_data_type() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--path", "/tmp/sample.txt", "--data-type", "loans"])


def test_build_argument_parser_parses_path_input() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.txt", "--data-type", "contributions"])

    assert args.path == Path("/tmp/sample.txt")
    assert args.download is False
    assert args.data_type == "contributions"
    assert args.limit is None
    assert args.dry_run is False


def test_build_argument_parser_parses_download_input() -> None:
    args = cli._build_argument_parser().parse_args(
        [
            "--download",
            "--data-type",
            "expenditures",
            "--limit",
            "10",
            "--election",
            "All",
            "--rowlimit",
            "50000",
            "--date-from",
            "2024-01-01",
            "--date-to",
            "2024-12-31",
        ]
    )

    assert args.download is True
    assert args.path is None
    assert args.data_type == "expenditures"
    assert args.limit == 10
    assert args.election == "All"
    assert args.rowlimit == 50000
    assert args.date_from == "2024-01-01"
    assert args.date_to == "2024-12-31"


def test_build_argument_parser_rejects_negative_rowlimit() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "contributions",
                "--rowlimit",
                "-1",
            ]
        )


def test_build_argument_parser_rejects_path_and_download_together() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--path",
                "/tmp/sample.txt",
                "--download",
                "--data-type",
                "contributions",
            ]
        )


# --- Dry-run tests ---


def test_main_dry_run_parses_rows_without_db_connection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_connection", MagicMock())
    monkeypatch.setattr(
        cli,
        "parse_contributions",
        MagicMock(return_value=iter([{"a": "1"}, {"a": "2"}, {"a": "3"}])),
    )
    monkeypatch.setattr(cli, "load_fl_contributions_with_filings", MagicMock())

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    cli.load_fl_contributions_with_filings.assert_not_called()
    assert "FL contributions dry-run: parsed 3 rows" in captured.out


# --- Load failure tests ---


def test_main_returns_error_and_closes_connection_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_fl_contributions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FL ingest failed: load failed" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


# --- run_fl_refresh routing tests ---


def test_run_fl_refresh_routes_contributions(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_fl_contributions_with_filings", load_with_filings)

    result = cli.run_fl_refresh(
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS_PATH,
        limit=6,
    )

    assert result == load_result
    load_with_filings.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, limit=6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_fl_refresh_routes_expenditures(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_expenditures = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_fl_expenditures_with_filings", load_expenditures)

    result = cli.run_fl_refresh(data_type="expenditures", path=_SAMPLE_EXPENDITURES_PATH)

    assert result == load_result
    load_expenditures.assert_called_once_with(connection, _SAMPLE_EXPENDITURES_PATH, limit=None)


def test_run_fl_refresh_rejects_unsupported_data_type(monkeypatch: pytest.MonkeyPatch) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="Unsupported FL data type: receipts"):
        cli.run_fl_refresh(data_type="receipts", path=_SAMPLE_CONTRIBUTIONS_PATH)

    get_connection.assert_not_called()
