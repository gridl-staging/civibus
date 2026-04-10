from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.TX.scraper import cli
from domains.campaign_finance.jurisdictions.states.TX.scraper.load import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=1,
        errors=0,
        elapsed_seconds=0.25,
    )


def test_build_argument_parser_requires_data_type_choice() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", "loans"])

    assert args.path == Path("/tmp/sample.csv")
    assert args.data_type == "loans"


def test_build_argument_parser_rejects_invalid_data_type_choice() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", "independent"])


def test_build_argument_parser_rejects_path_and_download_together() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--path", "/tmp/sample.csv", "--download", "--data-type", "contributions"]
        )


def test_build_argument_parser_parses_limit_and_dry_run() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/sample.csv", "--data-type", "contributions", "--limit", "5", "--dry-run"]
    )

    assert args.limit == 5
    assert args.dry_run is True


def test_main_download_mode_uses_downloaded_archive_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    downloaded_archive = tmp_path / "TEC_CF_CSV.zip"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_tx_archive = MagicMock(return_value=downloaded_archive)
    monkeypatch.setattr(cli, "download_tx_archive", download_tx_archive)
    load_contributions = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_tx_contributions_with_filings", load_contributions)

    exit_code = cli.main(["--download", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_tx_archive.assert_called_once_with("contributions", ANY)
    load_contributions.assert_called_once_with(connection, downloaded_archive, limit=None, year_from=None)
    assert "TX contributions load complete" in captured.out


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
    assert "TX contributions dry-run: parsed 3 rows" in captured.out


def test_main_returns_non_zero_for_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_tx_contributions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "TX ingest failed: load failed" in captured.err


def test_run_tx_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(return_value=(_SAMPLE_CONTRIBUTIONS_PATH, None))
    load_path = MagicMock(return_value=load_result)
    main = MagicMock()

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "main", main)

    result = cli.run_tx_refresh(
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
    assert resolved_args.limit == 6
    load_path.assert_called_once_with(
        connection, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", limit=6, year_from=None
    )
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
    main.assert_not_called()


def test_run_tx_refresh_rejects_unknown_data_type(monkeypatch: pytest.MonkeyPatch) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="Unsupported TX data type: filings"):
        cli.run_tx_refresh(data_type="filings", path=_SAMPLE_CONTRIBUTIONS_PATH)

    get_connection.assert_not_called()
