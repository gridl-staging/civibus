from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock

import httpx
import pytest

from domains.campaign_finance.jurisdictions.states.OH.scraper import cli
from domains.campaign_finance.jurisdictions.states.OH.scraper.load import LoadResult

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES = _FIXTURE_DIR / "sample_expenditures.csv"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=1,
        errors=0,
        elapsed_seconds=0.25,
    )


def _stage1_upstream_blocker_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:0::NO:RP:P73_TYPE:CAN:")
    response = httpx.Response(status_code=403, request=request, text="Maintenance")
    return httpx.HTTPStatusError(
        "Client error '403 Forbidden' for url 'https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:0::NO:RP:P73_TYPE:CAN:'",
        request=request,
        response=response,
    )


def _assert_cli_failure_with_envelope(
    capsys: pytest.CaptureFixture[str], *, argv: list[str], expected_message_fragment: str
) -> None:
    exit_code = cli.main(argv)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("OH ingest failed: ")
    assert expected_message_fragment in captured.err


# --- argument parser tests ---


def test_build_argument_parser_accepts_oh_data_types() -> None:
    for data_type in ("contributions", "expenditures"):
        args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample.csv", "--data-type", data_type])
        assert args.data_type == data_type


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


def test_build_argument_parser_rejects_negative_limit() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--path", "/tmp/sample.csv", "--data-type", "contributions", "--limit", "-1"]
        )


def test_download_mode_requires_committee_type_and_year(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--download without --committee-type and --year should fail."""
    _assert_cli_failure_with_envelope(
        capsys,
        argv=["--download", "--data-type", "contributions"],
        expected_message_fragment="--download requires --committee-type and --year",
    )
    _assert_cli_failure_with_envelope(
        capsys,
        argv=["--download", "--data-type", "contributions", "--committee-type", "CAN"],
        expected_message_fragment="--download requires --year",
    )
    _assert_cli_failure_with_envelope(
        capsys,
        argv=["--download", "--data-type", "contributions", "--year", "2022"],
        expected_message_fragment="--download requires --committee-type",
    )


# --- main() wiring tests ---


def test_main_dry_run_reports_row_count_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "parse_contributions", MagicMock(return_value=iter([{}, {}, {}])))
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS), "--data-type", "contributions", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.get_connection.assert_not_called()
    assert "OH contributions dry-run: parsed 3 rows" in captured.out


def test_main_download_mode_passes_committee_type_and_year(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    downloaded_csv = tmp_path / "oh_contributions.csv"

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    download_mock = MagicMock(return_value=downloaded_csv)
    monkeypatch.setattr(cli, "download_oh_csv", download_mock)
    load_mock = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_oh_contributions", load_mock)

    exit_code = cli.main(
        [
            "--download",
            "--data-type",
            "contributions",
            "--committee-type",
            "CAN",
            "--year",
            "2022",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    download_mock.assert_called_once_with("contributions", "CAN", 2022, ANY)
    load_mock.assert_called_once_with(connection, downloaded_csv, limit=None)
    assert "OH contributions load complete" in captured.out


def test_main_download_mode_reports_stage1_upstream_blocker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocker = _stage1_upstream_blocker_error()
    download_mock = MagicMock(side_effect=blocker)
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "download_oh_csv", download_mock)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    _assert_cli_failure_with_envelope(
        capsys,
        argv=["--download", "--data-type", "contributions", "--committee-type", "CAN", "--year", "2022"],
        expected_message_fragment="403 Forbidden",
    )

    download_mock.assert_called_once_with("contributions", "CAN", 2022, ANY)
    get_connection.assert_not_called()


def test_main_returns_non_zero_on_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_oh_contributions",
        MagicMock(side_effect=RuntimeError("load failed")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_CONTRIBUTIONS), "--data-type", "contributions"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "OH ingest failed: load failed" in captured.err


def test_resolve_input_path_cleans_temp_dir_on_download_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = _stage1_upstream_blocker_error()
    temp_dir = MagicMock()
    temp_dir.name = "/tmp/oh-contributions-2022-xyz"
    temp_dir_factory = MagicMock(return_value=temp_dir)
    download_mock = MagicMock(side_effect=blocker)
    monkeypatch.setattr(cli.tempfile, "TemporaryDirectory", temp_dir_factory)
    monkeypatch.setattr(cli, "download_oh_csv", download_mock)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        cli._resolve_input_path(
            cli._build_args(
                year=2022,
                data_type="contributions",
                path=None,
                download=True,
                limit=None,
                committee_type="CAN",
            )
        )

    assert exc_info.value is blocker
    temp_dir_factory.assert_called_once_with(prefix="oh-contributions-2022-")
    download_mock.assert_called_once_with("contributions", "CAN", 2022, Path(temp_dir.name))
    temp_dir.cleanup.assert_called_once_with()


def test_count_limited_rows_stops_at_limit() -> None:
    assert cli._count_limited_rows(iter([1, 2, 3, 4]), limit=2) == 2


def test_cleanup_temp_dir_calls_cleanup() -> None:
    temp_dir = MagicMock()
    cli._cleanup_temp_dir(temp_dir)
    temp_dir.cleanup.assert_called_once_with()


@pytest.mark.parametrize(
    ("kwargs", "error_message"),
    [
        (
            {"year": 2022, "data_type": "receipts", "path": _SAMPLE_CONTRIBUTIONS},
            "Unsupported OH data type: receipts",
        ),
        (
            {"year": 2022, "data_type": "contributions", "path": None, "download": False},
            "OH refresh requires either path or download mode",
        ),
        (
            {"year": 2022, "data_type": "contributions", "path": _SAMPLE_CONTRIBUTIONS, "download": True},
            "OH refresh accepts path or download mode, not both",
        ),
        (
            {
                "year": 2022,
                "data_type": "contributions",
                "path": _SAMPLE_CONTRIBUTIONS,
                "download": False,
                "committee_types": ("CAN",),
            },
            "OH committee_types is only supported in download mode",
        ),
    ],
)
def test_run_oh_refresh_rejects_invalid_mode_combinations(
    kwargs: dict[str, object],
    error_message: str,
) -> None:
    with pytest.raises(ValueError, match=error_message):
        cli.run_oh_refresh(**kwargs)


def test_run_oh_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    resolve_input_path = MagicMock(return_value=(_SAMPLE_CONTRIBUTIONS, None))
    load_path = MagicMock(return_value=load_result)
    main = MagicMock()

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "main", main)

    result = cli.run_oh_refresh(
        year=2022,
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS,
        limit=4,
    )

    assert result == load_result
    resolve_input_path.assert_called_once()
    resolved_args = resolve_input_path.call_args.args[0]
    assert resolved_args.year == 2022
    assert resolved_args.path == _SAMPLE_CONTRIBUTIONS
    assert resolved_args.download is False
    assert resolved_args.data_type == "contributions"
    assert resolved_args.limit == 4
    load_path.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS, data_type="contributions", limit=4)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
    main.assert_not_called()


def test_run_oh_refresh_path_mode_cleans_temp_dir_if_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    temp_dir = MagicMock()
    resolve_input_path = MagicMock(return_value=(_SAMPLE_CONTRIBUTIONS, temp_dir))
    load_path = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_oh_refresh(
        year=2022,
        data_type="contributions",
        path=_SAMPLE_CONTRIBUTIONS,
        limit=4,
    )

    assert result == load_result
    load_path.assert_called_once_with(connection, _SAMPLE_CONTRIBUTIONS, data_type="contributions", limit=4)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
    temp_dir.cleanup.assert_called_once_with()


def test_run_oh_refresh_download_mode_propagates_stage1_upstream_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = _stage1_upstream_blocker_error()
    download_mock = MagicMock(side_effect=blocker)
    load_resolved_paths = MagicMock()
    monkeypatch.setattr(cli, "download_oh_csv", download_mock)
    monkeypatch.setattr(cli, "_load_resolved_paths", load_resolved_paths)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        cli.run_oh_refresh(
            year=2022,
            data_type="contributions",
            download=True,
            committee_types=("CAN",),
        )

    assert exc_info.value is blocker
    download_mock.assert_called_once_with("contributions", "CAN", 2022, ANY)
    load_resolved_paths.assert_not_called()


def test_run_oh_refresh_download_mode_fans_out_committee_types(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    resolve_temp_dirs = [MagicMock(), MagicMock(), MagicMock()]
    resolve_input_path = MagicMock(
        side_effect=[
            (Path("/tmp/can.csv"), resolve_temp_dirs[0]),
            (Path("/tmp/pac.csv"), resolve_temp_dirs[1]),
            (Path("/tmp/party.csv"), resolve_temp_dirs[2]),
        ]
    )
    load_results = [
        LoadResult(inserted=1, skipped=2, quarantined=3, superseded=4, errors=5, elapsed_seconds=0.1),
        LoadResult(inserted=10, skipped=20, quarantined=30, superseded=40, errors=50, elapsed_seconds=0.2),
        LoadResult(inserted=100, skipped=200, quarantined=300, superseded=400, errors=500, elapsed_seconds=0.3),
    ]
    load_path = MagicMock(side_effect=load_results)

    monkeypatch.setattr(cli, "_resolve_input_path", resolve_input_path)
    monkeypatch.setattr(cli, "_load_path", load_path)
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))

    result = cli.run_oh_refresh(
        year=2022,
        data_type="contributions",
        download=True,
    )

    assert result == LoadResult(
        inserted=111,
        skipped=222,
        quarantined=333,
        superseded=444,
        errors=555,
        elapsed_seconds=0.6,
    )
    assert [call.args[1] for call in load_path.call_args_list] == [
        Path("/tmp/can.csv"),
        Path("/tmp/pac.csv"),
        Path("/tmp/party.csv"),
    ]
    assert [call.kwargs["data_type"] for call in load_path.call_args_list] == [
        "contributions",
        "contributions",
        "contributions",
    ]
    assert [call.kwargs["limit"] for call in load_path.call_args_list] == [None, None, None]
    assert [call.args[0].committee_type for call in resolve_input_path.call_args_list] == ["CAN", "PAC", "PARTY"]
    assert [call.args[0].year for call in resolve_input_path.call_args_list] == [2022, 2022, 2022]
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
    for temp_dir in resolve_temp_dirs:
        temp_dir.cleanup.assert_called_once_with()
