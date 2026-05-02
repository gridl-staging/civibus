"""Tests for NC orchestrator progress table schema and repository."""

from __future__ import annotations

from datetime import date, datetime

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions.states.NC.scraper.cli_test_support import (
    create_minimal_registry as _create_minimal_registry,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrator_progress import (
    _build_allowlist_scope,
    claim_next_committee,
    mark_completed,
    mark_failed,
    mark_retryable_failure,
    reclaim_stale_in_progress,
    seed_progress_from_registry,
)

pytestmark = pytest.mark.integration

_WINDOW_START = date(2025, 1, 1)
_WINDOW_END = date(2025, 6, 30)


class TestBuildAllowlistScope:
    def test_build_allowlist_scope_returns_fragment_and_params(self) -> None:
        where_allowlist, params = _build_allowlist_scope(["STA-C0002", "STA-C0001"])

        assert where_allowlist == " AND sboe_id = ANY(%(allowlist_sboe_ids)s::text[])"
        assert params == {"allowlist_sboe_ids": ["STA-C0002", "STA-C0001"]}

    def test_build_allowlist_scope_without_allowlist_is_noop(self) -> None:
        where_allowlist, params = _build_allowlist_scope(None)

        assert where_allowlist == ""
        assert params == {}


# ---------------------------------------------------------------------------
# Schema existence tests
# ---------------------------------------------------------------------------


class TestProgressTableSchema:
    def test_progress_table_exists(self, db_conn: psycopg.Connection) -> None:
        row = db_conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'cf' AND table_name = 'nc_orchestrator_progress'
            ) AS table_exists
            """
        ).fetchone()
        assert row is not None
        assert row[0] is True

    def test_progress_table_has_required_columns(self, db_conn: psycopg.Connection) -> None:
        rows = db_conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'cf' AND table_name = 'nc_orchestrator_progress'
            ORDER BY ordinal_position
            """
        ).fetchall()
        column_names = {r[0] for r in rows}
        required = {
            "sboe_id",
            "window_start",
            "window_end",
            "status",
            "claimed_at",
            "updated_at",
            "attempt_count",
            "last_error",
        }
        missing = required - column_names
        assert not missing, f"Missing columns: {missing}"

    def test_progress_table_status_constraint(self, db_conn: psycopg.Connection) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            db_conn.execute(
                """
                INSERT INTO cf.nc_orchestrator_progress
                    (sboe_id, window_start, window_end, status)
                VALUES ('TEST001', '2025-01-01', '2025-06-30', 'invalid_status')
                """
            )

    def test_progress_table_primary_key(self, db_conn: psycopg.Connection) -> None:
        db_conn.execute(
            """
            INSERT INTO cf.nc_orchestrator_progress
                (sboe_id, window_start, window_end, status)
            VALUES ('TEST001', '2025-01-01', '2025-06-30', 'pending')
            """
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            db_conn.execute(
                """
                INSERT INTO cf.nc_orchestrator_progress
                    (sboe_id, window_start, window_end, status)
                VALUES ('TEST001', '2025-01-01', '2025-06-30', 'pending')
                """
            )


# ---------------------------------------------------------------------------
# Repository: seed_progress_from_registry
# ---------------------------------------------------------------------------


class TestSeedProgressFromRegistry:
    def test_seed_with_allowlist_only_inserts_allowlisted_sboe_ids(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0003",
                    "committee_name": "Gamma PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 4, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Beta PAC",
                    "last_filing_date": date(2025, 5, 1),
                    "is_active": True,
                },
            ],
        )

        seeded = seed_progress_from_registry(
            db_conn,
            _WINDOW_START,
            _WINDOW_END,
            allowlist_sboe_ids=["STA-C0003", "STA-C0001"],
        )
        assert seeded == 2

        seeded_ids = db_conn.execute(
            "SELECT sboe_id FROM cf.nc_orchestrator_progress ORDER BY sboe_id ASC",
        ).fetchall()
        assert [row[0] for row in seeded_ids] == ["STA-C0001", "STA-C0003"]

    def test_seed_with_allowlist_remains_idempotent(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Beta PAC",
                    "last_filing_date": date(2025, 4, 1),
                    "is_active": True,
                },
            ],
        )

        first = seed_progress_from_registry(
            db_conn,
            _WINDOW_START,
            _WINDOW_END,
            allowlist_sboe_ids=["STA-C0001"],
        )
        second = seed_progress_from_registry(
            db_conn,
            _WINDOW_START,
            _WINDOW_END,
            allowlist_sboe_ids=["STA-C0001"],
        )
        assert first == 1
        assert second == 0

    def test_seed_creates_pending_rows(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Beta PAC",
                    "last_filing_date": date(2025, 4, 1),
                    "is_active": True,
                },
            ],
        )
        count = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        assert count == 2

        rows = db_conn.execute(
            "SELECT sboe_id, status FROM cf.nc_orchestrator_progress ORDER BY sboe_id",
            binary=False,
        ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [
            ("STA-C0001", "pending"),
            ("STA-C0002", "pending"),
        ]

    def test_seed_is_idempotent(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        first = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        second = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        assert first == 1
        assert second == 0

    def test_seed_different_windows_are_independent(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        alt_start = date(2025, 7, 1)
        alt_end = date(2025, 12, 31)
        count = seed_progress_from_registry(db_conn, alt_start, alt_end)
        assert count == 1

        total = db_conn.execute("SELECT count(*) FROM cf.nc_orchestrator_progress").fetchone()
        assert total is not None
        assert total[0] == 2

    def test_seed_fails_when_registry_missing(self, db_conn: psycopg.Connection) -> None:
        # Simulate the missing-registry condition by renaming the table inside the
        # test transaction. The db_conn fixture rolls back at exit, restoring the
        # canonical name. Previously this test relied on a divergent test schema
        # that did not auto-create the registry; it now exercises the same
        # defensive check against the real prod schema layout.
        db_conn.execute("ALTER TABLE cf.nc_committee_registry RENAME TO nc_committee_registry_renamed_for_test")
        try:
            with pytest.raises(RuntimeError, match="nc_committee_registry"):
                seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        finally:
            # Rollback in db_conn fixture handles cleanup, but be explicit so a
            # bare pytest.raises miss does not leave the test transaction stuck
            # with the renamed table.
            db_conn.execute(
                "ALTER TABLE IF EXISTS cf.nc_committee_registry_renamed_for_test RENAME TO nc_committee_registry"
            )

    def test_seed_filters_to_active_or_recent_committees(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Inactive Stale",
                    "last_filing_date": date(2024, 12, 31),
                    "is_active": False,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Inactive Recent",
                    "last_filing_date": date(2025, 1, 1),
                    "is_active": False,
                },
                {
                    "sboe_id": "STA-C0003",
                    "committee_name": "Active Missing Date",
                    "last_filing_date": None,
                    "is_active": True,
                },
            ],
        )

        seeded = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        assert seeded == 2

        seeded_ids = db_conn.execute(
            "SELECT sboe_id FROM cf.nc_orchestrator_progress ORDER BY sboe_id",
        ).fetchall()
        assert [row[0] for row in seeded_ids] == ["STA-C0002", "STA-C0003"]

    def test_seed_excludes_inactive_rows_with_null_filing_date(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Active Null",
                    "last_filing_date": None,
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Inactive Null",
                    "last_filing_date": None,
                    "is_active": False,
                },
            ],
        )

        seeded = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        assert seeded == 1

        seeded_ids = db_conn.execute(
            "SELECT sboe_id FROM cf.nc_orchestrator_progress ORDER BY sboe_id",
        ).fetchall()
        assert [row[0] for row in seeded_ids] == ["STA-C0001"]

    def test_seed_skips_empty_sboe_id_rows(self, db_conn: psycopg.Connection) -> None:
        """Multiple registry rows with empty sboe_id must not break the orchestrator.

        Why: live NC discovery (2026-04-25 production) found 232 active committees
        whose CFOrgLkup row carries no SBoE ID (sboe_id=''). Without this filter,
        seed_progress_from_registry violates nc_orchestrator_progress_pkey on the
        first duplicate, blocking the entire orchestrator run. Empty-sboe_id rows
        cannot be downloaded anyway (the portal needs a real ID), so dropping them
        costs no real coverage and prevents the PK collision.
        """
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "",
                    "committee_name": "Active No ID 1",
                    "last_filing_date": None,
                    "is_active": True,
                },
                {
                    "sboe_id": "",
                    "committee_name": "Active No ID 2",
                    "last_filing_date": None,
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Active With ID",
                    "last_filing_date": None,
                    "is_active": True,
                },
            ],
        )

        seeded = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        assert seeded == 1

        seeded_ids = db_conn.execute(
            "SELECT sboe_id FROM cf.nc_orchestrator_progress ORDER BY sboe_id",
        ).fetchall()
        assert [row[0] for row in seeded_ids] == ["STA-C0001"]

    def test_seed_skips_whitespace_only_sboe_id_rows(self, db_conn: psycopg.Connection) -> None:
        """Whitespace-only SBoE IDs must be treated as blank, not queued as work.

        The selector already trims blank-equivalent IDs before allowlisting. The
        progress seed path must apply the same blank semantics or a registry row
        with ``sboe_id='   '`` can still enter the queue in non-selector mode.
        """
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "   ",
                    "committee_name": "Active Whitespace ID",
                    "last_filing_date": None,
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Active With ID",
                    "last_filing_date": None,
                    "is_active": True,
                },
            ],
        )

        seeded = seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        assert seeded == 1

        seeded_ids = db_conn.execute(
            "SELECT sboe_id FROM cf.nc_orchestrator_progress ORDER BY sboe_id",
        ).fetchall()
        assert [row[0] for row in seeded_ids] == ["STA-C0001"]


# ---------------------------------------------------------------------------
# Repository: claim_next_committee
# ---------------------------------------------------------------------------


class TestClaimNextCommittee:
    def _seed_committees(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0003",
                    "committee_name": "Gamma PAC",
                    "last_filing_date": date(2025, 2, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Beta PAC",
                    "last_filing_date": date(2025, 4, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)

    def test_claim_returns_lowest_sboe_id(self, db_conn: psycopg.Connection) -> None:
        self._seed_committees(db_conn)
        claimed = claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        assert claimed is not None
        assert claimed["sboe_id"] == "STA-C0001"
        assert claimed["status"] == "in_progress"

    def test_claim_skips_already_claimed(self, db_conn: psycopg.Connection) -> None:
        self._seed_committees(db_conn)
        first = claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        second = claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        assert first is not None
        assert second is not None
        assert first["sboe_id"] == "STA-C0001"
        assert second["sboe_id"] == "STA-C0002"

    def test_claim_returns_none_when_exhausted(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        exhausted = claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        assert exhausted is None

    def test_claim_sets_claimed_at(self, db_conn: psycopg.Connection) -> None:
        self._seed_committees(db_conn)
        claimed = claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        assert claimed is not None
        assert isinstance(claimed["claimed_at"], datetime)

    def test_claim_with_allowlist_only_claims_allowlisted_rows(self, db_conn: psycopg.Connection) -> None:
        self._seed_committees(db_conn)
        claimed = claim_next_committee(
            db_conn,
            _WINDOW_START,
            _WINDOW_END,
            allowlist_sboe_ids=["STA-C0002"],
        )
        assert claimed is not None
        assert claimed["sboe_id"] == "STA-C0002"


# ---------------------------------------------------------------------------
# Repository: mark_completed / mark_failed
# ---------------------------------------------------------------------------


class TestMarkCompleted:
    def test_mark_completed_transitions_status(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        mark_completed(db_conn, "STA-C0001", _WINDOW_START, _WINDOW_END)

        row = db_conn.execute(
            "SELECT status FROM cf.nc_orchestrator_progress WHERE sboe_id = 'STA-C0001'",
        ).fetchone()
        assert row is not None
        assert row[0] == "completed"


class TestMarkFailed:
    def test_mark_failed_transitions_status_with_error(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        mark_failed(db_conn, "STA-C0001", _WINDOW_START, _WINDOW_END, error="Download timeout")

        with db_conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                """
                SELECT status, last_error, attempt_count
                FROM cf.nc_orchestrator_progress
                WHERE sboe_id = 'STA-C0001'
                    AND window_start = %s AND window_end = %s
                """,
                (_WINDOW_START, _WINDOW_END),
            ).fetchone()
        assert row is not None
        assert row["status"] == "failed"
        assert row["last_error"] == "Download timeout"
        assert row["attempt_count"] == 1

    def test_mark_failed_increments_attempt_count(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        mark_failed(db_conn, "STA-C0001", _WINDOW_START, _WINDOW_END, error="err1")
        # Re-claim (simulating reclaim) and fail again
        db_conn.execute(
            """
            UPDATE cf.nc_orchestrator_progress
            SET status = 'in_progress', claimed_at = now()
            WHERE sboe_id = 'STA-C0001'
                AND window_start = %s AND window_end = %s
            """,
            (_WINDOW_START, _WINDOW_END),
        )
        mark_failed(db_conn, "STA-C0001", _WINDOW_START, _WINDOW_END, error="err2")

        with db_conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                """
                SELECT attempt_count, last_error
                FROM cf.nc_orchestrator_progress
                WHERE sboe_id = 'STA-C0001'
                    AND window_start = %s AND window_end = %s
                """,
                (_WINDOW_START, _WINDOW_END),
            ).fetchone()
        assert row is not None
        assert row["attempt_count"] == 2
        assert row["last_error"] == "err2"


class TestMarkRetryableFailure:
    def test_mark_retryable_failure_returns_row_to_pending(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        mark_retryable_failure(db_conn, "STA-C0001", _WINDOW_START, _WINDOW_END, error="temporary timeout")

        with db_conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                """
                SELECT status, claimed_at, attempt_count, last_error
                FROM cf.nc_orchestrator_progress
                WHERE sboe_id = 'STA-C0001'
                    AND window_start = %s AND window_end = %s
                """,
                (_WINDOW_START, _WINDOW_END),
            ).fetchone()
        assert row is not None
        assert row["status"] == "pending"
        assert row["claimed_at"] is None
        assert row["attempt_count"] == 1
        assert row["last_error"] == "temporary timeout"


# ---------------------------------------------------------------------------
# Repository: reclaim_stale_in_progress
# ---------------------------------------------------------------------------


class TestReclaimStaleInProgress:
    def test_reclaim_resets_stale_rows_to_pending(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        # Backdate claimed_at to simulate staleness
        db_conn.execute(
            """
            UPDATE cf.nc_orchestrator_progress
            SET claimed_at = now() - interval '120 minutes'
            WHERE sboe_id = 'STA-C0001'
                AND window_start = %s AND window_end = %s
            """,
            (_WINDOW_START, _WINDOW_END),
        )
        reclaimed = reclaim_stale_in_progress(db_conn, _WINDOW_START, _WINDOW_END, stale_after_minutes=60)
        assert reclaimed == 1

        row = db_conn.execute(
            """
            SELECT status, claimed_at
            FROM cf.nc_orchestrator_progress
            WHERE sboe_id = 'STA-C0001'
                AND window_start = %s AND window_end = %s
            """,
            (_WINDOW_START, _WINDOW_END),
        ).fetchone()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] is None

    def test_reclaim_ignores_recent_in_progress(self, db_conn: psycopg.Connection) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        reclaimed = reclaim_stale_in_progress(db_conn, _WINDOW_START, _WINDOW_END, stale_after_minutes=60)
        assert reclaimed == 0

    def test_reclaim_with_allowlist_ignores_non_allowlisted_stale_rows(
        self,
        db_conn: psycopg.Connection,
    ) -> None:
        _create_minimal_registry(
            db_conn,
            [
                {
                    "sboe_id": "STA-C0001",
                    "committee_name": "Alpha PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
                {
                    "sboe_id": "STA-C0002",
                    "committee_name": "Beta PAC",
                    "last_filing_date": date(2025, 3, 1),
                    "is_active": True,
                },
            ],
        )
        seed_progress_from_registry(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        claim_next_committee(db_conn, _WINDOW_START, _WINDOW_END)
        db_conn.execute(
            """
            UPDATE cf.nc_orchestrator_progress
            SET claimed_at = now() - interval '120 minutes'
            WHERE window_start = %s AND window_end = %s
            """,
            (_WINDOW_START, _WINDOW_END),
        )
        reclaimed = reclaim_stale_in_progress(
            db_conn,
            _WINDOW_START,
            _WINDOW_END,
            stale_after_minutes=60,
            allowlist_sboe_ids=["STA-C0001"],
        )
        assert reclaimed == 1

        statuses = db_conn.execute(
            """
            SELECT sboe_id, status
            FROM cf.nc_orchestrator_progress
            WHERE window_start = %s AND window_end = %s
            ORDER BY sboe_id ASC
            """,
            (_WINDOW_START, _WINDOW_END),
        ).fetchall()
        assert statuses == [("STA-C0001", "pending"), ("STA-C0002", "in_progress")]
