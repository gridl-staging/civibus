from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from unittest.mock import ANY

from domains.campaign_finance.jurisdictions.states.CA.scraper import cli
from domains.campaign_finance.jurisdictions.states.CA.scraper.load import LoadResult

_SAMPLE_FIXTURE_PATH = Path(__file__).parent / "test_fixtures" / "sample_archive"


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.25,
    )


def test_build_argument_parser_parses_path_input() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/sample_archive"])

    assert args.path == Path("/tmp/sample_archive")
    assert args.download is False
    assert args.limit is None
    assert args.dry_run is False


def test_build_argument_parser_parses_download_and_limit() -> None:
    args = cli._build_argument_parser().parse_args(["--download", "--limit", "10"])

    assert args.download is True
    assert args.limit == 10


def test_build_argument_parser_rejects_negative_limit() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--path", "/tmp/sample_archive", "--limit", "-1"])


def test_main_loads_provided_path_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_ca_member_directory_with_filings",
        MagicMock(return_value=load_result),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_FIXTURE_PATH)])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.load_ca_member_directory_with_filings.assert_called_once_with(
        connection,
        _SAMPLE_FIXTURE_PATH,
        limit=None,
        year_from=None,
    )
    assert "CA load complete" in captured.out
    assert "inserted=3" in captured.out
    assert "skipped=1" in captured.out
    assert "quarantined=0" in captured.out
    assert "superseded=0" in captured.out
    assert "errors=0" in captured.out
    assert "elapsed_seconds=0.25" in captured.out
    assert captured.err == ""
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_downloads_and_extracts_before_loading(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    archive_path = tmp_path / "dbwebexport.zip"
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    extracted_member = extracted_dir / "RCPT_CD.TSV"
    extracted_member.write_text("header\n", encoding="utf-8")

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "download_ca_archive", MagicMock(return_value=archive_path))
    monkeypatch.setattr(
        cli,
        "extract_ingestion_members",
        MagicMock(return_value={extracted_member.name: extracted_member}),
    )
    monkeypatch.setattr(
        cli,
        "load_ca_member_directory_with_filings",
        MagicMock(return_value=load_result),
    )

    exit_code = cli.main(["--download"])
    captured = capsys.readouterr()

    assert exit_code == 0
    cli.download_ca_archive.assert_called_once()
    cli.extract_ingestion_members.assert_called_once_with(archive_path, dest_dir=ANY)
    cli.load_ca_member_directory_with_filings.assert_called_once_with(
        connection,
        extracted_dir,
        limit=None,
        year_from=None,
    )
    assert "CA load complete" in captured.out
    assert "inserted=3" in captured.out
    assert "quarantined=0" in captured.out
    assert "superseded=0" in captured.out
    assert "errors=0" in captured.out
    assert "elapsed_seconds=0.25" in captured.out
    connection.close.assert_called_once_with()


def test_main_returns_error_for_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "load_ca_member_directory_with_filings",
        MagicMock(side_effect=RuntimeError("broken archive")),
    )

    exit_code = cli.main(["--path", str(_SAMPLE_FIXTURE_PATH)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "broken archive" in captured.err
    connection.close.assert_called_once_with()


def test_run_ca_refresh_executes_typed_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_ca_member_directory_with_filings", load_with_filings)

    result = cli.run_ca_refresh(path=_SAMPLE_FIXTURE_PATH, limit=5)

    assert result == load_result
    load_with_filings.assert_called_once_with(connection, _SAMPLE_FIXTURE_PATH, limit=5, year_from=None)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_ca_refresh_retries_db_connection_on_host_default_port_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    get_connection_mock = MagicMock(
        side_effect=[
            RuntimeError("Unable to connect to PostgreSQL at localhost:5433/civibus"),
            connection,
        ]
    )

    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.setattr(cli, "get_connection", get_connection_mock)
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_ca_member_directory_with_filings", load_with_filings)

    result = cli.run_ca_refresh(path=_SAMPLE_FIXTURE_PATH, limit=5)

    assert result == load_result
    assert get_connection_mock.call_args_list == [
        call(),
        call(host="127.0.0.1", port=5432),
    ]
    load_with_filings.assert_called_once_with(connection, _SAMPLE_FIXTURE_PATH, limit=5, year_from=None)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_ca_refresh_retries_db_connection_when_default_host_mode_is_explicitly_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for configured_host in ("localhost", "db"):
        connection = MagicMock()
        load_result = _build_load_result()
        get_connection_mock = MagicMock(
            side_effect=[
                RuntimeError("Unable to connect to PostgreSQL at 127.0.0.1:5433/civibus"),
                connection,
            ]
        )

        monkeypatch.setenv("POSTGRES_HOST", configured_host)
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setattr(cli, "get_connection", get_connection_mock)
        load_with_filings = MagicMock(return_value=load_result)
        monkeypatch.setattr(cli, "load_ca_member_directory_with_filings", load_with_filings)

        result = cli.run_ca_refresh(path=_SAMPLE_FIXTURE_PATH, limit=5)

        assert result == load_result
        assert get_connection_mock.call_args_list == [
            call(),
            call(host="127.0.0.1", port=5432),
        ]
        load_with_filings.assert_called_once_with(connection, _SAMPLE_FIXTURE_PATH, limit=5, year_from=None)
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()


def test_run_ca_refresh_retries_db_connection_on_loopback_default_port_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    get_connection_mock = MagicMock(
        side_effect=[
            RuntimeError("Unable to connect to PostgreSQL at 127.0.0.1:5433/civibus"),
            connection,
        ]
    )

    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.setattr(cli, "get_connection", get_connection_mock)
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_ca_member_directory_with_filings", load_with_filings)

    result = cli.run_ca_refresh(path=_SAMPLE_FIXTURE_PATH, limit=5)

    assert result == load_result
    assert get_connection_mock.call_args_list == [
        call(),
        call(host="127.0.0.1", port=5432),
    ]
    load_with_filings.assert_called_once_with(connection, _SAMPLE_FIXTURE_PATH, limit=5, year_from=None)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_ca_refresh_retries_db_connection_on_explicit_localhost_5432_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    get_connection_mock = MagicMock(
        side_effect=[
            RuntimeError("Unable to connect to PostgreSQL at localhost:5432/civibus"),
            connection,
        ]
    )

    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setattr(cli, "get_connection", get_connection_mock)
    load_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_ca_member_directory_with_filings", load_with_filings)

    result = cli.run_ca_refresh(path=_SAMPLE_FIXTURE_PATH, limit=5)

    assert result == load_result
    assert get_connection_mock.call_args_list == [
        call(),
        call(host="127.0.0.1", port=5432),
    ]
    load_with_filings.assert_called_once_with(connection, _SAMPLE_FIXTURE_PATH, limit=5, year_from=None)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_ca_refresh_rejects_missing_mode() -> None:
    with pytest.raises(ValueError, match="requires either path or download mode"):
        cli.run_ca_refresh()


def test_run_ca_refresh_rejects_mixed_mode() -> None:
    with pytest.raises(ValueError, match="path or download mode, not both"):
        cli.run_ca_refresh(path=_SAMPLE_FIXTURE_PATH, download=True)


def test_main_dry_run_cleans_temp_dir_on_count_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    temp_dir = MagicMock()
    monkeypatch.setattr(cli, "_resolve_input_directory", MagicMock(return_value=(_SAMPLE_FIXTURE_PATH, temp_dir)))
    monkeypatch.setattr(cli, "_count_transaction_rows", MagicMock(side_effect=RuntimeError("broken row")))

    exit_code = cli.main(["--path", str(_SAMPLE_FIXTURE_PATH), "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "broken row" in captured.err
    temp_dir.cleanup.assert_called_once_with()
