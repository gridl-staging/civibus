from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.WI.scraper import cli
from domains.campaign_finance.jurisdictions.states.WI.scraper.load import LoadResult

_FIXTURE_PATH = Path("/tmp/wi-transactions.csv")


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
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", "transactions"])

    assert args.path == Path("/tmp/sample.csv")
    assert args.download is False
    assert args.data_type == "transactions"
    assert args.limit is None
    assert args.dry_run is False


def test_build_argument_parser_accepts_reports_and_committees() -> None:
    for data_type in ("reports", "committees"):
        args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", data_type])
        assert args.data_type == data_type


def test_main_download_dry_run_for_reports_uses_parser_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "download_wi_csv", MagicMock(return_value=_FIXTURE_PATH))
    monkeypatch.setattr(cli, "parse_reports", MagicMock(return_value=iter([{}, {}])))
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(["--download", "--data-type", "reports", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.download_wi_csv.assert_called_once_with("reports", dest_dir=ANY)
    cli.get_connection.assert_not_called()
    assert "WI reports dry-run: parsed 2 rows" in captured.out


def test_main_transactions_path_loads_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_wi_transactions_with_filings", load_with_filings)

    exit_code = cli.main(["--path", str(_FIXTURE_PATH), "--data-type", "transactions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_with_filings.assert_called_once_with(connection, _FIXTURE_PATH, limit=None)
    assert "WI transactions load complete" in captured.out
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_non_transaction_load_mode_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(["--path", str(_FIXTURE_PATH), "--data-type", "reports"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "WI reports data type is supported for parse/dry-run only" in captured.err


def test_run_wi_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(return_value=(_FIXTURE_PATH, None))
    load_path = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_wi_refresh(data_type="transactions", path=_FIXTURE_PATH, limit=6)

    assert result == load_result
    resolve_input_path.assert_called_once()
    resolved_args = resolve_input_path.call_args.args[0]
    assert resolved_args.path == _FIXTURE_PATH
    assert resolved_args.download is False
    assert resolved_args.data_type == "transactions"
    assert resolved_args.limit == 6
    load_path.assert_called_once_with(connection, _FIXTURE_PATH, data_type="transactions", limit=6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_wi_refresh_rejects_non_transaction_data_type(monkeypatch: pytest.MonkeyPatch) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="WI reports data type is supported for parse/dry-run only"):
        cli.run_wi_refresh(data_type="reports", path=_FIXTURE_PATH)

    get_connection.assert_not_called()
