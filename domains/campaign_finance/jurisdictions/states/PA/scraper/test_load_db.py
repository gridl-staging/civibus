from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.PA.scraper import load as pa_load_module
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    bulk_fixture_row_counts,
    cleanup_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper import pa_load_test_support as pa_support
from domains.campaign_finance.jurisdictions.states.PA.scraper.load import load_pa_contributions_with_filings


# --- DB-backed partial-commit durability ---------------------------------------
#
# These tests prove the committing PA loader contracts against a real database.
# The synthetic fixture pair and leak-proof cleanup are owned by pa_load_test_support,
# so all committing specimens share one source of truth for fixture identity and
# cleanup scoping.


def test_load_pa_with_filings_commits_own_work_visible_from_second_connection(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    fixture = pa_support.write_pa_fixture_pair(tmp_path)
    # db_conn yields with BEGIN already executed; the loader must observe IDLE to
    # own its commits, otherwise nothing commits and the test proves nothing.
    db_conn.rollback()
    cleanup_bulk_fixture(fixture)

    try:
        result = load_pa_contributions_with_filings(db_conn, fixture.detail_path, year=pa_support.PA_FIXTURE_YEAR)

        assert result.inserted == 1
        assert result.errors == 0
        assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        # Visibility from an independent connection proves the loader committed its
        # own work rather than leaving it in the caller's transaction.
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == 1
        assert transaction_count == 1
    finally:
        cleanup_bulk_fixture(fixture)


def test_cleanup_bulk_fixture_removes_the_entity_rows_a_pa_load_created(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    # Leak guard: the committing tests create core.person / core.organization /
    # core.address / cf.committee rows as well as the provenance links, and the
    # links are what cleanup used to be scoped to. Counts are taken by fixture
    # identity rather than by provenance link, because a link-scoped count reads
    # zero after cleanup no matter how many entity rows were left behind.
    fixture = pa_support.write_pa_fixture_pair(tmp_path)
    db_conn.rollback()
    cleanup_bulk_fixture(fixture)

    try:
        counts_before = pa_support.fixture_entity_row_counts(fixture)

        load_pa_contributions_with_filings(db_conn, fixture.detail_path, year=pa_support.PA_FIXTURE_YEAR)

        # Non-vacuity: the load must actually have created entity rows to clean up.
        assert pa_support.fixture_entity_row_counts(fixture) != counts_before

        cleanup_bulk_fixture(fixture)
        assert pa_support.fixture_entity_row_counts(fixture) == counts_before
    finally:
        cleanup_bulk_fixture(fixture)


def test_load_pa_with_filings_reload_is_idempotent_with_no_double_count(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    fixture = pa_support.write_pa_fixture_pair(tmp_path)
    db_conn.rollback()
    cleanup_bulk_fixture(fixture)

    try:
        first = load_pa_contributions_with_filings(db_conn, fixture.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert first.inserted == 1
        counts_before = bulk_fixture_row_counts(fixture)

        reload_conn = get_connection()
        try:
            reload_conn.rollback()
            second = load_pa_contributions_with_filings(
                reload_conn, fixture.detail_path, year=pa_support.PA_FIXTURE_YEAR
            )
        finally:
            reload_conn.close()

        assert second.inserted == 0
        assert second.skipped == 1
        assert second.errors == 0

        counts_after = bulk_fixture_row_counts(fixture)
        assert counts_after == counts_before
    finally:
        cleanup_bulk_fixture(fixture)


def test_load_pa_with_filings_phase1_records_survive_phase2_failure(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = pa_support.write_pa_fixture_pair(tmp_path)
    db_conn.rollback()
    cleanup_bulk_fixture(fixture)

    monkeypatch.setattr(
        pa_load_module,
        "_load_pa_relational_transactions",
        MagicMock(side_effect=RuntimeError("phase 2 boom")),
    )

    try:
        with pytest.raises(RuntimeError, match="phase 2 boom"):
            pa_load_module._load_pa_with_filings(
                db_conn, fixture.detail_path, data_type="contributions", year=pa_support.PA_FIXTURE_YEAR
            )

        # Phase-1 raw records were committed before the phase-2 failure and remain
        # visible from an independent connection.
        source_record_count, _transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == 1
    finally:
        cleanup_bulk_fixture(fixture)
