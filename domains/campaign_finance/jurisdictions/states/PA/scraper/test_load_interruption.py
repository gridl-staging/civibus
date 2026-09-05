from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import psycopg
import pytest

from core.db import get_connection
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    bulk_fixture_row_counts,
    cleanup_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper import load as pa_load_module
from domains.campaign_finance.jurisdictions.states.PA.scraper import pa_load_test_support as pa_support
from domains.campaign_finance.jurisdictions.states.PA.scraper.load import load_pa_contributions_with_filings

_BULK_ROW_COUNT = pa_load_module._COMMIT_BATCH_ROWS + 1


class _Stage3Interruption(BaseException):
    # _try_load_pa_row swallows Exception, while a process-style interrupt must escape.
    pass


def _stage3_interrupting_row_loader(raise_at_invocation: int):
    real_load_pa_row = pa_load_module._load_pa_row
    invocations = 0

    def _interrupting_load_pa_row(conn, row, data_source_id, *, data_type):
        nonlocal invocations
        invocations += 1
        if invocations == raise_at_invocation:
            raise _Stage3Interruption("stage3 interruption")
        return real_load_pa_row(conn, row, data_source_id, data_type=data_type)

    return _interrupting_load_pa_row


def test_load_pa_with_filings_rerun_after_interruption_preserves_committed_batch(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with ExitStack() as resources:
        fixture = pa_support.write_pa_fixture_pair(tmp_path, row_count=_BULK_ROW_COUNT)
        resources.callback(cleanup_bulk_fixture, fixture)
        db_conn.rollback()
        cleanup_bulk_fixture(fixture)
        assert bulk_fixture_row_counts(fixture) == (0, 0)

        monkeypatch.setattr(
            pa_load_module,
            "_load_pa_row",
            _stage3_interrupting_row_loader(_BULK_ROW_COUNT),
        )
        with pytest.raises(_Stage3Interruption, match="stage3 interruption"):
            load_pa_contributions_with_filings(
                db_conn,
                fixture.detail_path,
                year=pa_support.PA_FIXTURE_YEAR,
            )
        db_conn.rollback()

        # Phase 2 never ran, so the committed source-record batch has zero transactions.
        assert bulk_fixture_row_counts(fixture) == (_BULK_ROW_COUNT - 1, 0)

        monkeypatch.undo()
        rerun_conn = get_connection()
        resources.callback(rerun_conn.close)
        rerun_conn.rollback()
        second = load_pa_contributions_with_filings(
            rerun_conn,
            fixture.detail_path,
            year=pa_support.PA_FIXTURE_YEAR,
        )

        assert second.inserted == 1
        assert second.skipped == _BULK_ROW_COUNT - 1
        assert second.errors == 0
        assert bulk_fixture_row_counts(fixture) == (_BULK_ROW_COUNT, _BULK_ROW_COUNT)
