from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.CO.scraper import cli
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import LoadResult


class TestCOCLI2026:
    """Lock CO CLI contract for 2026-cycle ingest."""

    def test_parser_accepts_2026_year(self) -> None:
        args = cli._build_argument_parser().parse_args(
            ["--year", "2026", "--data-type", "contributions", "--path", "/tmp/file.csv"]
        )
        assert args.year == 2026

    def test_parser_accepts_2026_expenditures(self) -> None:
        args = cli._build_argument_parser().parse_args(
            ["--year", "2026", "--data-type", "expenditures", "--path", "/tmp/file.csv"]
        )
        assert args.year == 2026
        assert args.data_type == "expenditures"


_SAMPLE_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"
_SAMPLE_EXPENDITURE_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "sample_expenditures.csv"


def test_build_argument_parser_parses_path_input() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--year", "2024", "--data-type", "contributions", "--path", "/tmp/file.csv"]
    )

    assert args.year == 2024
    assert args.data_type == "contributions"
    assert args.path == Path("/tmp/file.csv")
    assert args.download is False
    assert args.allow_insecure_tls is False
    assert args.limit is None


def test_build_argument_parser_parses_limit_and_download_flag() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--year", "2024", "--data-type", "contributions", "--download", "--limit", "100"]
    )

    assert args.download is True
    assert args.allow_insecure_tls is False
    assert args.limit == 100


def test_build_argument_parser_parses_allow_insecure_tls_flag() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--year", "2024", "--data-type", "contributions", "--download", "--allow-insecure-tls"]
    )

    assert args.allow_insecure_tls is True


def test_build_argument_parser_rejects_negative_limit() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--year", "2024", "--data-type", "contributions", "--download", "--limit", "-1"]
        )


def test_build_argument_parser_accepts_expenditures_data_type() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--year", "2024", "--data-type", "expenditures", "--path", "/tmp/file.csv"]
    )

    assert args.data_type == "expenditures"


def test_build_argument_parser_requires_one_input_source() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--year", "2024", "--data-type", "contributions"])


def test_build_argument_parser_rejects_both_input_sources() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--year",
                "2024",
                "--data-type",
                "contributions",
                "--path",
                "/tmp/file.csv",
                "--download",
            ]
        )


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=7,
        skipped=2,
        quarantined=1,
        superseded=1,
        errors=0,
        elapsed_seconds=0.5,
    )


def test_main_loads_provided_path_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_co_contributions_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_co_contributions_with_filings", load_co_contributions_with_filings)

    exit_code = cli.main(
        [
            "--year",
            "2024",
            "--data-type",
            "contributions",
            "--path",
            str(_SAMPLE_FIXTURE_PATH),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    load_co_contributions_with_filings.assert_called_once_with(
        connection,
        _SAMPLE_FIXTURE_PATH,
        limit=None,
    )
    assert "CO contributions load complete" in captured.out
    assert "inserted=7" in captured.out
    assert "skipped=2" in captured.out
    assert "quarantined=1" in captured.out
    assert "superseded=1" in captured.out
    assert "errors=0" in captured.out
    assert captured.err == ""
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once()


def test_main_uses_extracted_csv_path_for_download_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    zip_path = tmp_path / "downloaded.zip"
    extracted_csv_path = tmp_path / "records.csv"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_tracer_file = MagicMock(return_value=zip_path)
    extract_csv_from_zip = MagicMock(return_value=extracted_csv_path)
    load_co_contributions_with_filings = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "download_tracer_file", download_tracer_file)
    monkeypatch.setattr(cli, "extract_csv_from_zip", extract_csv_from_zip)
    monkeypatch.setattr(cli, "load_co_contributions_with_filings", load_co_contributions_with_filings)

    exit_code = cli.main(["--year", "2024", "--data-type", "contributions", "--download"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_tracer_file.assert_called_once()
    called_download_kwargs = download_tracer_file.call_args.kwargs
    assert called_download_kwargs["year"] == 2024
    assert called_download_kwargs["data_type"] == "contributions"
    assert called_download_kwargs["allow_insecure_tls"] is False
    assert isinstance(called_download_kwargs["dest_dir"], Path)

    extract_csv_from_zip.assert_called_once_with(zip_path, dest_dir=called_download_kwargs["dest_dir"])
    load_co_contributions_with_filings.assert_called_once_with(
        connection,
        extracted_csv_path,
        limit=None,
    )
    assert "inserted=7" in captured.out
    assert captured.err == ""
    connection.close.assert_called_once()


def test_main_passes_allow_insecure_tls_to_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    zip_path = tmp_path / "downloaded.zip"
    extracted_csv_path = tmp_path / "records.csv"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_tracer_file = MagicMock(return_value=zip_path)
    monkeypatch.setattr(cli, "download_tracer_file", download_tracer_file)
    monkeypatch.setattr(cli, "extract_csv_from_zip", MagicMock(return_value=extracted_csv_path))
    monkeypatch.setattr(cli, "load_co_contributions_with_filings", MagicMock(return_value=load_result))

    exit_code = cli.main(
        [
            "--year",
            "2024",
            "--data-type",
            "contributions",
            "--download",
            "--allow-insecure-tls",
        ]
    )

    assert exit_code == 0
    assert download_tracer_file.call_args.kwargs["allow_insecure_tls"] is True


def test_main_routes_expenditures_to_expenditure_loader(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    contribution_loader = MagicMock()
    expenditure_loader = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_co_contributions_with_filings", contribution_loader)
    monkeypatch.setattr(cli, "load_co_expenditures_with_filings", expenditure_loader)

    exit_code = cli.main(
        [
            "--year",
            "2024",
            "--data-type",
            "expenditures",
            "--path",
            str(_SAMPLE_EXPENDITURE_FIXTURE_PATH),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    expenditure_loader.assert_called_once_with(
        connection,
        _SAMPLE_EXPENDITURE_FIXTURE_PATH,
        limit=None,
    )
    contribution_loader.assert_not_called()
    assert "CO expenditures load complete" in captured.out
    connection.close.assert_called_once()


def test_main_returns_error_for_download_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)
    monkeypatch.setattr(cli, "download_tracer_file", MagicMock(side_effect=RuntimeError("network down")))

    exit_code = cli.main(["--year", "2024", "--data-type", "contributions", "--download"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "network down" in captured.err
    get_connection.assert_not_called()


def test_main_returns_error_and_closes_connection_for_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_co_contributions_with_filings",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(
        [
            "--year",
            "2024",
            "--data-type",
            "contributions",
            "--path",
            str(_SAMPLE_FIXTURE_PATH),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "load failed" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once()


def test_run_co_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    contribution_loader = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_co_contributions_with_filings", contribution_loader)

    result = cli.run_co_refresh(
        year=2024,
        data_type="contributions",
        path=_SAMPLE_FIXTURE_PATH,
        limit=7,
    )

    assert result == load_result
    contribution_loader.assert_called_once_with(connection, _SAMPLE_FIXTURE_PATH, limit=7)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
