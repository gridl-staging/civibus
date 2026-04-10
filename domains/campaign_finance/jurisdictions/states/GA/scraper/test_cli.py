from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.GA.scraper import cli
from domains.campaign_finance.jurisdictions.states.GA.scraper.cli import _DataTypeConfig
from domains.campaign_finance.jurisdictions.states.GA.scraper.load import LoadResult


# ---------------------------------------------------------------------------
# Argument parser tests
# ---------------------------------------------------------------------------


def test_build_argument_parser_parses_required_args() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/file.xls", "--data-type", "contributions"])

    assert args.path == Path("/tmp/file.xls")
    assert args.data_type == "contributions"
    assert args.limit is None
    assert args.dry_run is False


def test_build_argument_parser_accepts_expenditures() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/file.xls", "--data-type", "expenditures"])

    assert args.data_type == "expenditures"


def test_build_argument_parser_rejects_invalid_data_type() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--path", "/tmp/file.xls", "--data-type", "loans"])


def test_build_argument_parser_accepts_limit() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/file.xls", "--data-type", "contributions", "--limit", "50"]
    )

    assert args.limit == 50


def test_build_argument_parser_accepts_zero_limit() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/file.xls", "--data-type", "contributions", "--limit", "0"]
    )

    assert args.limit == 0


def test_build_argument_parser_rejects_negative_limit() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--path", "/tmp/file.xls", "--data-type", "contributions", "--limit", "-1"]
        )


def test_build_argument_parser_accepts_dry_run() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/file.xls", "--data-type", "contributions", "--dry-run"]
    )

    assert args.dry_run is True


def test_build_argument_parser_accepts_download_with_required_filters() -> None:
    args = cli._build_argument_parser().parse_args(
        [
            "--download",
            "--data-type",
            "contributions",
            "--candidate",
            "Jane Example",
            "--date-start",
            "01/01/2024",
            "--date-end",
            "01/31/2024",
        ]
    )

    assert args.download is True
    assert args.path is None
    assert args.candidate == "Jane Example"
    assert args.date_start == "01/01/2024"
    assert args.date_end == "01/31/2024"


def test_build_argument_parser_rejects_download_with_path() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--path",
                "/tmp/file.xls",
                "--download",
                "--data-type",
                "contributions",
                "--candidate",
                "Jane Example",
                "--date-start",
                "01/01/2024",
                "--date-end",
                "01/31/2024",
            ]
        )


def test_build_argument_parser_allows_download_without_candidate() -> None:
    """Candidate is optional — empty string means 'all candidates' on the portal."""
    args = cli._build_argument_parser().parse_args(
        [
            "--download",
            "--data-type",
            "contributions",
            "--date-start",
            "01/01/2024",
            "--date-end",
            "01/31/2024",
        ]
    )
    assert args.candidate is None
    assert args.download is True


def test_build_argument_parser_requires_date_start_when_download_enabled() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "contributions",
                "--candidate",
                "Jane Example",
                "--date-end",
                "01/31/2024",
            ]
        )


def test_build_argument_parser_requires_date_end_when_download_enabled() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "contributions",
                "--candidate",
                "Jane Example",
                "--date-start",
                "01/01/2024",
            ]
        )


def test_build_argument_parser_requires_path() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--data-type", "contributions"])


def test_build_argument_parser_requires_data_type() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--path", "/tmp/file.xls"])


def test_non_negative_int_accepts_positive() -> None:
    assert cli._non_negative_int("42") == 42


def test_non_negative_int_accepts_zero() -> None:
    assert cli._non_negative_int("0") == 0


def test_non_negative_int_rejects_negative() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="greater than or equal to 0"):
        cli._non_negative_int("-1")


# ---------------------------------------------------------------------------
# Summary helper tests
# ---------------------------------------------------------------------------


def _build_ga_load_result() -> LoadResult:
    return LoadResult(inserted=5, skipped=2, errors=1, elapsed_seconds=1.23)


def test_print_load_summary_includes_all_fields(
    capsys: pytest.CaptureFixture,
) -> None:
    result = _build_ga_load_result()
    cli._print_load_summary(result, "contributions")
    captured = capsys.readouterr()

    assert "GA" in captured.out
    assert "contributions" in captured.out
    assert "inserted=5" in captured.out
    assert "skipped=2" in captured.out
    assert "errors=1" in captured.out
    assert "elapsed_seconds=1.23" in captured.out


def test_print_load_summary_expenditures(
    capsys: pytest.CaptureFixture,
) -> None:
    result = _build_ga_load_result()
    cli._print_load_summary(result, "expenditures")
    captured = capsys.readouterr()

    assert "GA expenditures" in captured.out


def test_print_dry_run_summary(
    capsys: pytest.CaptureFixture,
) -> None:
    cli._print_dry_run_summary("contributions", 42)
    captured = capsys.readouterr()

    assert "contributions" in captured.out
    assert "42" in captured.out


# ---------------------------------------------------------------------------
# main() happy path tests
# ---------------------------------------------------------------------------


def _patch_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    data_type: str,
    parser: MagicMock,
    loader: MagicMock,
) -> None:
    monkeypatch.setitem(
        cli._DATA_TYPE_DISPATCH,
        data_type,
        _DataTypeConfig(parser=parser, loader=loader, label=data_type),
    )


def _build_contribution_download_args(
    *extra_args: str,
    candidate: str = "Jane Example",
    date_start: str = "01/01/2024",
    date_end: str = "01/31/2024",
) -> list[str]:
    return [
        "--download",
        "--data-type",
        "contributions",
        "--candidate",
        candidate,
        "--date-start",
        date_start,
        "--date-end",
        date_end,
        *extra_args,
    ]


def _patch_download_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[MagicMock, MagicMock, Path]:
    temp_dir = MagicMock()
    temp_dir.name = str(tmp_path / "ga-download")
    monkeypatch.setattr(cli.tempfile, "TemporaryDirectory", MagicMock(return_value=temp_dir))

    downloaded_path = Path(temp_dir.name) / "StateEthicsReport.csv"
    download_mock = MagicMock(return_value=downloaded_path)
    monkeypatch.setattr(cli, "download_ga_export", download_mock)
    return temp_dir, download_mock, downloaded_path


def _assert_contribution_download_requested(
    download_mock: MagicMock,
    temp_dir: MagicMock,
    *,
    candidate: str = "Jane Example",
    date_start: str = "01/01/2024",
    date_end: str = "01/31/2024",
) -> None:
    download_mock.assert_called_once_with(
        "contributions",
        dest_dir=Path(temp_dir.name),
        candidate=candidate,
        date_start=date_start,
        date_end=date_end,
    )


def test_main_download_mode_preserves_2026_cycle_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    load_result = _build_ga_load_result()
    connection = MagicMock()

    parser_mock = MagicMock()
    loader_mock = MagicMock(return_value=load_result)
    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)

    temp_dir, download_mock, downloaded_path = _patch_download_resolution(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    exit_code = cli.main(
        _build_contribution_download_args(
            candidate="Brian Kemp",
            date_start="01/01/2026",
            date_end="03/31/2026",
        )
    )

    assert exit_code == 0
    _assert_contribution_download_requested(
        download_mock,
        temp_dir,
        candidate="Brian Kemp",
        date_start="01/01/2026",
        date_end="03/31/2026",
    )
    loader_mock.assert_called_once_with(connection, downloaded_path, limit=None)


def test_main_routes_contributions_through_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    load_result = _build_ga_load_result()
    connection = MagicMock()

    parser_mock = MagicMock()
    loader_mock = MagicMock(return_value=load_result)

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    exit_code = cli.main(["--path", "/tmp/c.xls", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 0
    parser_mock.assert_not_called()
    loader_mock.assert_called_once_with(connection, Path("/tmp/c.xls"), limit=None)
    assert "GA contributions load complete" in captured.out
    assert "inserted=5" in captured.out
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once()


def test_main_routes_expenditures_through_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    load_result = _build_ga_load_result()
    connection = MagicMock()

    parser_mock = MagicMock()
    loader_mock = MagicMock(return_value=load_result)

    _patch_dispatch(monkeypatch, "expenditures", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    exit_code = cli.main(["--path", "/tmp/exp.xls", "--data-type", "expenditures"])
    captured = capsys.readouterr()

    assert exit_code == 0
    parser_mock.assert_not_called()
    loader_mock.assert_called_once_with(connection, Path("/tmp/exp.xls"), limit=None)
    assert "GA expenditures" in captured.out
    connection.close.assert_called_once()


def test_main_download_mode_resolves_temp_path_and_loads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    load_result = _build_ga_load_result()
    connection = MagicMock()

    parser_mock = MagicMock()
    loader_mock = MagicMock(return_value=load_result)
    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)

    temp_dir, download_mock, downloaded_path = _patch_download_resolution(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    exit_code = cli.main(_build_contribution_download_args())

    assert exit_code == 0
    _assert_contribution_download_requested(download_mock, temp_dir)
    parser_mock.assert_not_called()
    loader_mock.assert_called_once_with(connection, downloaded_path, limit=None)
    connection.close.assert_called_once()
    temp_dir.cleanup.assert_called_once_with()


def test_main_forwards_limit_to_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_result = _build_ga_load_result()
    connection = MagicMock()

    parser_mock = MagicMock()
    loader_mock = MagicMock(return_value=load_result)

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    exit_code = cli.main(["--path", "/tmp/c.xls", "--data-type", "contributions", "--limit", "10"])

    assert exit_code == 0
    parser_mock.assert_not_called()
    loader_mock.assert_called_once_with(connection, Path("/tmp/c.xls"), limit=10)
    connection.close.assert_called_once_with()


def test_main_uses_single_dispatch_not_duplicate_switches() -> None:
    """Verify that cli.py uses a single DATA_TYPE_DISPATCH mapping."""
    assert hasattr(cli, "_DATA_TYPE_DISPATCH"), "cli.py must define _DATA_TYPE_DISPATCH as the single source of truth"
    dispatch = cli._DATA_TYPE_DISPATCH
    assert "contributions" in dispatch
    assert "expenditures" in dispatch


# ---------------------------------------------------------------------------
# main() dry-run and parse failure tests
# ---------------------------------------------------------------------------


def test_main_dry_run_reports_row_count_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    rows = [{"col": "v1"}, {"col": "v2"}, {"col": "v3"}]
    parser_mock = MagicMock(return_value=iter(rows))
    loader_mock = MagicMock()
    get_connection = MagicMock()

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(["--path", "/tmp/c.xls", "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    parser_mock.assert_called_once_with(Path("/tmp/c.xls"))
    get_connection.assert_not_called()
    loader_mock.assert_not_called()
    assert "3" in captured.out
    assert "contributions" in captured.out


def test_main_download_dry_run_reports_row_count_and_cleans_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    rows = [{"col": "v1"}, {"col": "v2"}, {"col": "v3"}]
    parser_mock = MagicMock(return_value=iter(rows))
    loader_mock = MagicMock()
    get_connection = MagicMock()

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    temp_dir, download_mock, downloaded_path = _patch_download_resolution(monkeypatch, tmp_path)

    exit_code = cli.main(_build_contribution_download_args("--dry-run"))
    captured = capsys.readouterr()

    assert exit_code == 0
    _assert_contribution_download_requested(download_mock, temp_dir)
    parser_mock.assert_called_once_with(downloaded_path)
    get_connection.assert_not_called()
    loader_mock.assert_not_called()
    temp_dir.cleanup.assert_called_once_with()
    assert "3" in captured.out
    assert "contributions" in captured.out


def test_main_loader_parse_failure_returns_1_after_connection_setup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    parser_mock = MagicMock()
    connection = MagicMock()
    loader_mock = MagicMock(side_effect=ValueError("bad header"))
    get_connection = MagicMock(return_value=connection)

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(["--path", "/tmp/c.xls", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "bad header" in captured.err
    parser_mock.assert_not_called()
    get_connection.assert_called_once_with()
    loader_mock.assert_called_once_with(connection, Path("/tmp/c.xls"), limit=None)
    connection.close.assert_called_once_with()


def test_main_download_parse_failure_returns_1_and_cleans_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    parser_mock = MagicMock()
    connection = MagicMock()
    loader_mock = MagicMock(side_effect=ValueError("bad header"))
    get_connection = MagicMock(return_value=connection)

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    temp_dir, _, downloaded_path = _patch_download_resolution(monkeypatch, tmp_path)

    exit_code = cli.main(_build_contribution_download_args())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "bad header" in captured.err
    parser_mock.assert_not_called()
    get_connection.assert_called_once_with()
    loader_mock.assert_called_once_with(connection, downloaded_path, limit=None)
    connection.close.assert_called_once_with()
    temp_dir.cleanup.assert_called_once_with()


# ---------------------------------------------------------------------------
# main() load failure tests
# ---------------------------------------------------------------------------


def test_main_load_failure_returns_1_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()

    parser_mock = MagicMock()
    loader_mock = MagicMock(side_effect=RuntimeError("db exploded"))

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    exit_code = cli.main(["--path", "/tmp/c.xls", "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "db exploded" in captured.err
    parser_mock.assert_not_called()
    loader_mock.assert_called_once_with(connection, Path("/tmp/c.xls"), limit=None)
    connection.commit.assert_not_called()
    connection.close.assert_called_once()


def test_run_ga_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    load_result = _build_ga_load_result()
    connection = MagicMock()
    parser_mock = MagicMock()
    loader_mock = MagicMock(return_value=load_result)

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_ga_refresh(
        data_type="contributions",
        path=Path("/tmp/c.xls"),
        limit=11,
    )

    assert result == load_result
    parser_mock.assert_not_called()
    loader_mock.assert_called_once_with(connection, Path("/tmp/c.xls"), limit=11)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_ga_refresh_download_accepts_empty_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty candidate triggers A-Z alphabetic iteration (26 letters)."""
    load_result = _build_ga_load_result()
    connection = MagicMock()
    loader_mock = MagicMock(return_value=load_result)
    download_mock = MagicMock(return_value=Path("/tmp/fake.csv"))
    parser_mock = MagicMock()

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "download_ga_export", download_mock)

    result = cli.run_ga_refresh(
        data_type="contributions",
        download=True,
        candidate="",
        date_start="01/01/2026",
        date_end="12/31/2026",
    )

    # Empty candidate iterates A-Z: 26 letters × 5 inserted each = 130 total
    assert result.inserted == load_result.inserted * 26
    assert result.skipped == load_result.skipped * 26
    assert result.errors == load_result.errors * 26
    assert download_mock.call_count == 26
    # First call should be letter "A"
    first_call = download_mock.call_args_list[0]
    assert first_call[0][0] == "contributions"
    assert first_call[1]["candidate"] == "A"
    # Last call should be letter "Z"
    last_call = download_mock.call_args_list[-1]
    assert last_call[1]["candidate"] == "Z"


def test_run_ga_refresh_download_specific_candidate_skips_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A specific candidate name downloads once, no A-Z iteration."""
    load_result = _build_ga_load_result()
    connection = MagicMock()
    loader_mock = MagicMock(return_value=load_result)
    download_mock = MagicMock(return_value=Path("/tmp/fake.csv"))
    parser_mock = MagicMock()

    _patch_dispatch(monkeypatch, "contributions", parser_mock, loader_mock)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "download_ga_export", download_mock)

    result = cli.run_ga_refresh(
        data_type="contributions",
        download=True,
        candidate="Hatfield",
        date_start="01/01/2026",
        date_end="12/31/2026",
    )

    assert result == load_result
    download_mock.assert_called_once_with(
        "contributions",
        dest_dir=ANY,
        candidate="Hatfield",
        date_start="01/01/2026",
        date_end="12/31/2026",
    )


def test_run_ga_refresh_download_requires_dates() -> None:
    """date_start and date_end are still required for download mode."""
    with pytest.raises(ValueError, match="requires date_start and date_end"):
        cli.run_ga_refresh(
            data_type="contributions",
            download=True,
            candidate="",
            date_start=None,
            date_end="12/31/2026",
        )
