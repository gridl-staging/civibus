from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from conftest import _skip_or_fail_for_postgres_unavailable
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.dark_money import cli

_POSTGRES_UNAVAILABLE_PREFIX = "Unable to connect to PostgreSQL at "


def _skip_if_optional_postgres_unavailable(error: RuntimeError) -> None:
    if str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
        _skip_or_fail_for_postgres_unavailable(str(error))
    raise error


@pytest.mark.unit
def test_cli_parser_ingest_accepts_path_batch_size_and_limit(tmp_path: Path) -> None:
    input_path = tmp_path / "irs_527_sample.zip"
    input_path.write_text("stub", encoding="utf-8")

    parser = cli.build_argument_parser()
    args = parser.parse_args(["ingest", "--path", str(input_path), "--batch-size", "250", "--limit", "12"])

    assert args.mode == "ingest"
    assert args.path == input_path
    assert args.batch_size == 250
    assert args.limit == 12


@pytest.mark.unit
def test_cli_parser_ingest_uses_default_batch_size_and_optional_limit(tmp_path: Path) -> None:
    input_path = tmp_path / "irs_527_sample.txt"
    input_path.write_text("stub", encoding="utf-8")

    parser = cli.build_argument_parser()
    args = parser.parse_args(["ingest", "--path", str(input_path)])

    assert args.mode == "ingest"
    assert args.path == input_path
    assert args.batch_size == 1000
    assert args.limit is None


@pytest.mark.unit
def test_cli_parser_download_requires_no_extra_args() -> None:
    parser = cli.build_argument_parser()
    args = parser.parse_args(["download"])

    assert args.mode == "download"


@pytest.mark.unit
def test_main_download_mode_calls_download_and_extract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    downloaded_zip = Path("/tmp/PolOrgsFullData.zip")
    extracted_txt = Path("/tmp/FullDataFile.txt")

    download_mock = MagicMock(return_value=downloaded_zip)
    extract_mock = MagicMock(return_value=extracted_txt)

    monkeypatch.setattr(cli, "download_irs_527_full_data", download_mock)
    monkeypatch.setattr(cli, "extract_irs_527_txt", extract_mock)

    exit_code = cli.main(["download"])
    captured = capsys.readouterr()

    assert exit_code == 0
    download_mock.assert_called_once()
    extract_mock.assert_called_once_with(downloaded_zip, downloaded_zip.parent)
    assert "IRS 527 download complete" in captured.out


@pytest.mark.unit
def test_main_ingest_mode_extracts_zip_then_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    zip_path = tmp_path / "irs_527_sample.zip"
    zip_path.write_text("zip", encoding="utf-8")
    extracted_txt_path = tmp_path / "FullDataFile.txt"

    mock_connection = MagicMock()
    mock_load_result = LoadResult(inserted=3, skipped=1, errors=0)

    monkeypatch.setattr(cli, "extract_irs_527_txt", MagicMock(return_value=extracted_txt_path))
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=mock_connection))
    monkeypatch.setattr(cli, "ensure_irs_527_data_source", MagicMock(return_value=uuid4()))
    load_mock = MagicMock(return_value=mock_load_result)
    monkeypatch.setattr(cli, "load_irs_527_records", load_mock)

    exit_code = cli.main(["ingest", "--path", str(zip_path), "--batch-size", "500", "--limit", "9"])

    assert exit_code == 0
    load_mock.assert_called_once()
    assert load_mock.call_args.kwargs["batch_size"] == 500
    assert load_mock.call_args.kwargs["limit"] == 9
    assert load_mock.call_args.args[1] == extracted_txt_path
    mock_connection.close.assert_called_once()


@pytest.mark.unit
def test_main_ingest_mode_returns_exit_1_on_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "irs_527_sample.zip"
    input_path.write_text("zip", encoding="utf-8")

    def _raise_runtime_error(**_: object) -> LoadResult:
        raise RuntimeError("ingest exploded")

    monkeypatch.setattr(cli, "run_ingest", _raise_runtime_error)

    exit_code = cli.main(["ingest", "--path", str(input_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "IRS 527 pipeline failed: ingest exploded" in captured.err


@pytest.mark.unit
def test_skip_if_optional_postgres_unavailable_skips_without_required_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVIBUS_REQUIRE_DB", raising=False)

    with pytest.raises(pytest.skip.Exception, match="Unable to connect to PostgreSQL"):
        _skip_if_optional_postgres_unavailable(RuntimeError("Unable to connect to PostgreSQL at localhost:1/civibus"))


@pytest.mark.unit
def test_skip_if_optional_postgres_unavailable_fails_with_required_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVIBUS_REQUIRE_DB", "1")

    try:
        _skip_if_optional_postgres_unavailable(RuntimeError("Unable to connect to PostgreSQL at localhost:1/civibus"))
    except pytest.skip.Exception as exc:
        pytest.fail(f"expected required database failure, got skip: {exc}")
    except pytest.fail.Exception as exc:
        assert "Unable to connect to PostgreSQL" in str(exc)
    else:
        pytest.fail("expected required database failure")


@pytest.mark.integration
def test_run_ingest_fixture_zip_returns_inserted_rows() -> None:
    fixture_path = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "bulk" / "irs_527_sample.zip"

    # First run: load all fixture rows — may insert or skip depending on prior DB state.
    try:
        first_result = cli.run_ingest(path=fixture_path, batch_size=1000, limit=1000)
    except RuntimeError as error:
        _skip_if_optional_postgres_unavailable(error)

    assert isinstance(first_result, LoadResult)
    total_processed = first_result.inserted + first_result.skipped
    assert total_processed > 0

    # Second run: all rows should be skipped (idempotency check).
    second_result = cli.run_ingest(path=fixture_path, batch_size=1000, limit=1000)
    assert second_result.skipped == total_processed
    assert second_result.inserted == 0
