from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.MN.scraper import cli
from domains.campaign_finance.jurisdictions.states.MN.scraper.load import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_INDEPENDENT_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_independent_expenditures.csv"


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
    args = cli._build_argument_parser().parse_args(["--download", "--data-type", "expenditures", "--limit", "10"])

    assert args.download is True
    assert args.path is None
    assert args.data_type == "expenditures"
    assert args.limit == 10


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
    monkeypatch.setattr(cli, "load_mn_contributions_with_filings", load_with_filings)

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_with_filings.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, limit=None)
    assert "MN contributions load complete" in captured.out
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
    downloaded_path = tmp_path / "mn_contributions.csv"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_mn_csv = MagicMock(return_value=downloaded_path)
    monkeypatch.setattr(cli, "download_mn_csv", download_mn_csv)
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_mn_contributions_with_filings", load_with_filings)

    exit_code = cli.main(["--download", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_mn_csv.assert_called_once_with("contributions", dest_dir=ANY)
    load_with_filings.assert_called_once_with(connection, downloaded_path, limit=None)
    assert "MN contributions load complete" in captured.out
    assert captured.err == ""
    connection.close.assert_called_once_with()


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
    monkeypatch.setattr(cli, "load_mn_contributions_with_filings", MagicMock())

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    cli.load_mn_contributions_with_filings.assert_not_called()
    assert "MN contributions dry-run: parsed 3 rows" in captured.out


def test_main_routes_expenditures_to_expenditure_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "load_mn_contributions_with_filings", MagicMock())
    load_expenditures = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_mn_expenditures_with_filings", load_expenditures)

    exit_code = cli.main(["--path", str(_SAMPLE_EXPENDITURES_PATH), "--data-type", "expenditures"])

    assert exit_code == 0
    load_expenditures.assert_called_once_with(connection, _SAMPLE_EXPENDITURES_PATH, limit=None)
    cli.load_mn_contributions_with_filings.assert_not_called()


def test_main_dry_run_counts_independent_expenditures_fixture(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(
        [
            "--path",
            str(_SAMPLE_INDEPENDENT_EXPENDITURES_PATH),
            "--data-type",
            "independent_expenditures",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    assert "MN independent_expenditures dry-run: parsed 2 rows" in captured.out


def test_main_returns_error_and_closes_connection_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_mn_contributions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "MN ingest failed: load failed" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


def test_run_mn_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_mn_contributions_with_filings", load_with_filings)

    result = cli.run_mn_refresh(
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS_PATH,
        limit=9,
    )

    assert result == load_result
    load_with_filings.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, limit=9)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_mn_refresh_rejects_unsupported_data_type(monkeypatch: pytest.MonkeyPatch) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="Unsupported MN data type: loans"):
        cli.run_mn_refresh(data_type="loans", path=_SAMPLE_CONTRIBUTIONS_PATH)

    get_connection.assert_not_called()
