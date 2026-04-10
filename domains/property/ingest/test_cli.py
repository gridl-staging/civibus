from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.property.ingest import cli, loader as property_loader


def _build_connection() -> MagicMock:
    connection = MagicMock()
    connection.transaction.side_effect = lambda: nullcontext()
    return connection


def test_main_reports_loaded_skipped_error_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    connection = _build_connection()
    bundled_config_path = Path("/tmp/durham/config.yaml")
    bundled_fixture_path = Path("/tmp/durham/sample_query_response.json")
    normalized_records = [{"reid": "1"}, {"reid": "2"}]

    monkeypatch.setattr(
        cli,
        "resolve_bundled_durham_asset_paths",
        MagicMock(return_value=(bundled_config_path, bundled_fixture_path)),
    )
    monkeypatch.setattr(
        cli, "load_durham_config", MagicMock(return_value={"jurisdiction": {"slug": "states/nc/counties/durham"}})
    )
    monkeypatch.setattr(cli, "load_durham_fixture_records", MagicMock(return_value=[{"REID": "1"}, {"REID": "2"}]))
    monkeypatch.setattr(cli, "normalize_durham_raw_records", MagicMock(return_value=normalized_records))
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_durham_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(cli, "ensure_durham_jurisdiction", MagicMock(return_value=uuid4()))
    load_durham_records = MagicMock(return_value=(1, 1, 0))
    monkeypatch.setattr(cli, "load_durham_records", load_durham_records)

    exit_code = cli.main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "loaded=1 skipped=1 errors=0 fetched=2" in captured.out
    assert captured.err == ""
    load_durham_records.assert_called_once()
    assert load_durham_records.call_args.kwargs["per_record_savepoints"] is True
    connection.close.assert_called_once()


def test_main_isolates_record_failures_with_savepoints(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = _build_connection()
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "resolve_bundled_durham_asset_paths", MagicMock(return_value=(Path("c"), Path("f"))))
    monkeypatch.setattr(
        cli, "load_durham_config", MagicMock(return_value={"jurisdiction": {"slug": "states/nc/counties/durham"}})
    )
    monkeypatch.setattr(
        cli,
        "load_durham_fixture_records",
        MagicMock(return_value=[{"REID": "1"}, {"REID": "2"}, {"REID": "3"}]),
    )
    monkeypatch.setattr(
        cli,
        "normalize_durham_raw_records",
        MagicMock(return_value=[{"reid": "1"}, {"reid": "2"}, {"reid": "3"}]),
    )
    monkeypatch.setattr(cli, "ensure_durham_data_source", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(cli, "ensure_durham_jurisdiction", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(
        property_loader,
        "load_durham_record",
        MagicMock(side_effect=[True, RuntimeError("boom"), False]),
    )

    exit_code = cli.main([])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "Durham ingest completed with record errors: loaded=1 skipped=1 errors=1 fetched=3" in captured.err
    # one outer transaction + three per-record savepoints
    assert connection.transaction.call_count == 4


def test_main_returns_nonzero_on_setup_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(
        cli,
        "resolve_bundled_durham_asset_paths",
        MagicMock(return_value=(Path("/tmp/c.yaml"), Path("/tmp/f.json"))),
    )
    monkeypatch.setattr(cli, "load_durham_config", MagicMock(side_effect=RuntimeError("bad config")))
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main([])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Durham ingest failed: bad config" in captured.err
    get_connection.assert_not_called()


def test_default_durham_ingest_paths_delegate_to_source_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = (Path("/tmp/config.yaml"), Path("/tmp/sample_query_response.json"))
    monkeypatch.setattr(cli, "resolve_bundled_durham_asset_paths", MagicMock(return_value=expected))

    config_path, fixture_path = cli.default_durham_ingest_paths()

    assert config_path == expected[0]
    assert fixture_path == expected[1]
