from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.NJ.scraper import cli
from domains.campaign_finance.jurisdictions.states.NJ.scraper.load import LoadResult

_FIXTURE_PATH = Path("/tmp/nj-contributions.csv")


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


def test_main_download_dry_run_uses_parser_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "download_nj_csv", MagicMock(return_value=_FIXTURE_PATH))
    monkeypatch.setattr(cli, "parse_contributions", MagicMock(return_value=iter([{}, {}, {}])))
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(["--download", "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.download_nj_csv.assert_called_once_with("contributions", dest_dir=ANY)
    cli.get_connection.assert_not_called()
    assert "NJ contributions dry-run: parsed 3 rows" in captured.out


def test_main_contributions_path_loads_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nj_contributions_with_filings", load_with_filings)

    exit_code = cli.main(["--path", str(_FIXTURE_PATH), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_with_filings.assert_called_once_with(connection, _FIXTURE_PATH, limit=None)
    assert "NJ contributions load complete" in captured.out
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_unsupported_data_type_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(["--path", str(_FIXTURE_PATH), "--data-type", "pay_to_play"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Unsupported NJ data type" in captured.err


def test_run_nj_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(return_value=(_FIXTURE_PATH, None))
    load_path = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_nj_refresh(data_type="contributions", path=_FIXTURE_PATH, limit=6)

    assert result == load_result
    resolve_input_path.assert_called_once()


def test_run_nj_refresh_rejects_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported NJ data type"):
        cli.run_nj_refresh(data_type="pay_to_play", path=_FIXTURE_PATH)
