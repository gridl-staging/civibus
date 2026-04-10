from __future__ import annotations

import psycopg
import pytest

from domains.property.ingest import cli
from domains.property.ingest.durham_source import (
    load_durham_config,
    load_durham_fixture_records,
    normalize_durham_raw_records,
    resolve_bundled_durham_asset_paths,
)
from domains.property.ingest.ingest_test_helpers import fixture_reids, fixture_row_counts
from domains.property.ingest.loader import ensure_durham_data_source, ensure_durham_jurisdiction, load_durham_records

pytestmark = pytest.mark.integration


class _NoCommitNoCloseConnection:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def test_main_with_real_durham_assets_matches_direct_loader_counts(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    config_path, fixture_path = resolve_bundled_durham_asset_paths()
    config = load_durham_config(config_path)
    records = normalize_durham_raw_records(load_durham_fixture_records(fixture_path))
    reids = fixture_reids(records)

    baseline_counts: dict[str, int] = {}

    class _RollbackBaseline(RuntimeError):
        pass

    try:
        with db_conn.transaction():
            data_source_id = ensure_durham_data_source(db_conn, config)
            jurisdiction_id = ensure_durham_jurisdiction(db_conn, config)
            inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)

            assert (inserted, skipped, errors) == (len(records), 0, 0)
            baseline_counts = fixture_row_counts(db_conn, data_source_id, reids)
            raise _RollbackBaseline
    except _RollbackBaseline:
        pass

    monkeypatch.setattr(cli, "get_connection", lambda: _NoCommitNoCloseConnection(db_conn))
    exit_code = cli.main(["--config-path", str(config_path), "--fixture-path", str(fixture_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "loaded=3 skipped=0 errors=0 fetched=3" in captured.out

    data_source_id = ensure_durham_data_source(db_conn, config)
    cli_counts = fixture_row_counts(db_conn, data_source_id, reids)
    assert cli_counts == baseline_counts
