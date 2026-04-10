from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.IL.scraper import cli
from domains.campaign_finance.jurisdictions.states.IL.scraper.download import ILDownloadResult
from domains.campaign_finance.jurisdictions.states.IL.scraper.load import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "Receipts_sample.txt"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "Expenditures_sample.txt"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=1,
        errors=0,
        elapsed_seconds=0.25,
    )


def test_build_argument_parser_accepts_il_data_types() -> None:
    for data_type in ("contributions", "expenditures"):
        args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.txt", "--data-type", data_type])
        assert args.data_type == data_type


def test_count_rows_uses_parser_for_data_type() -> None:
    assert cli._count_rows(_SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", limit=None) == 7
    assert cli._count_rows(_SAMPLE_EXPENDITURES_PATH, data_type="expenditures", limit=3) == 3


def test_main_download_mode_uses_downloaded_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    downloaded_path = tmp_path / "Receipts.txt"
    download_result = ILDownloadResult(
        path=downloaded_path,
        bytes_written=42,
        data_rows_written=2,
        truncated=True,
    )

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "download_il_data_with_metadata", MagicMock(return_value=download_result))
    load_contributions = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_il_contributions_with_filings", load_contributions)

    exit_code = cli.main(["--download", "--data-type", "contributions", "--download-row-limit", "2"])
    captured = capsys.readouterr()

    assert exit_code == 0
    load_contributions.assert_called_once_with(connection, downloaded_path, limit=None)
    assert "IL contributions load complete" in captured.out
    assert "downloaded_bytes=42" in captured.out
    assert "downloaded_rows=2" in captured.out
    assert "download_truncated=yes" in captured.out


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
    assert "IL contributions dry-run: parsed=3 rows" in captured.out


def test_run_il_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(
        return_value=cli._ResolvedInput(path=_SAMPLE_CONTRIBUTIONS_PATH, temp_dir=None, download_result=None)
    )
    load_path = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_il_refresh(
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS_PATH,
        limit=6,
    )

    assert result == load_result
    load_path.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", limit=6)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_il_refresh_rejects_invalid_source_mode() -> None:
    with pytest.raises(ValueError, match="requires either path or download mode"):
        cli.run_il_refresh(data_type="contributions")


def test_main_dry_run_wraps_invalid_header_with_clear_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "parse_contributions", MagicMock(side_effect=ValueError("Unexpected contribution header")))

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS_PATH), "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "did not match the expected tab-delimited header" in captured.err
