"""Unit tests for the SF CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from domains.campaign_finance.jurisdictions.cities.SF.scraper import cli
from domains.campaign_finance.jurisdictions.states.load_utils import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_TRANSACTIONS_PATH = _FIXTURE_DIR / "sample_transactions.csv"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=5,
        skipped=2,
        quarantined=0,
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


def test_build_argument_parser_parses_download_input() -> None:
    args = cli._build_argument_parser().parse_args(["--download", "--data-type", "transactions", "--limit", "10"])

    assert args.download is True
    assert args.path is None
    assert args.data_type == "transactions"
    assert args.limit == 10


def test_build_argument_parser_rejects_path_and_download_together() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--path", "/tmp/sample.csv", "--download", "--data-type", "transactions"]
        )


def test_main_loads_path_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_sf_transactions_with_filings", load_with_filings)

    exit_code = cli.main(["--path", str(_SAMPLE_TRANSACTIONS_PATH), "--data-type", "transactions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_with_filings.assert_called_once_with(connection, _SAMPLE_TRANSACTIONS_PATH, limit=None)
    assert "SF transactions load complete" in captured.out
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
    downloaded_path = tmp_path / "sf_transactions.csv"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_sf_csv = MagicMock(return_value=downloaded_path)
    monkeypatch.setattr(cli, "download_sf_csv", download_sf_csv)
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_sf_transactions_with_filings", load_with_filings)

    exit_code = cli.main(["--download", "--data-type", "transactions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_sf_csv.assert_called_once_with("transactions", dest_dir=ANY)
    load_with_filings.assert_called_once_with(connection, downloaded_path, limit=None)
    assert "SF transactions load complete" in captured.out
    assert captured.err == ""
    connection.close.assert_called_once_with()


def test_main_dry_run_uses_path_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_connection", MagicMock())
    monkeypatch.setattr(
        cli,
        "parse_transactions",
        MagicMock(return_value=iter([{"a": "1"}, {"a": "2"}, {"a": "3"}])),
    )
    monkeypatch.setattr(cli, "load_sf_transactions_with_filings", MagicMock())

    exit_code = cli.main(["--path", str(_SAMPLE_TRANSACTIONS_PATH), "--data-type", "transactions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    cli.load_sf_transactions_with_filings.assert_not_called()
    assert "SF transactions dry-run: parsed 3 rows" in captured.out


def test_main_returns_error_and_closes_connection_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_sf_transactions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_TRANSACTIONS_PATH), "--data-type", "transactions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "SF ingest failed: load failed" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


def test_run_sf_refresh_executes_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_sf_transactions_with_filings", load_with_filings)

    result = cli.run_sf_refresh(
        data_type="transactions",
        path=_SAMPLE_TRANSACTIONS_PATH,
        limit=6,
    )

    assert result == load_result
    load_with_filings.assert_called_once_with(connection, _SAMPLE_TRANSACTIONS_PATH, limit=6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_sf_refresh_download_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_sf_csv = MagicMock(return_value=Path("/tmp/sf_transactions.csv"))
    monkeypatch.setattr(cli, "download_sf_csv", download_sf_csv)
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_sf_transactions_with_filings", load_with_filings)

    result = cli.run_sf_refresh(data_type="transactions", download=True)

    assert result == load_result
    download_sf_csv.assert_called_once()
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_sf_refresh_rejects_unsupported_data_type(monkeypatch: pytest.MonkeyPatch) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="Unsupported SF data type: receipts"):
        cli.run_sf_refresh(data_type="receipts", path=_SAMPLE_TRANSACTIONS_PATH)

    get_connection.assert_not_called()
