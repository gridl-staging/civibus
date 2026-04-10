"""State sample-ingest e2e smoke test.

Automates the database-reset and sample-ingest portion of the Stage 6 closeout
contract: run the CO/GA/NC CLI entry points with the same fixture arguments as
the Makefile targets, then prove the CO relational chain
``cf.transaction -> cf.filing -> cf.committee -> core.organization``.

Manual Stage 6 closeout still owns the `make db-up`, `make test`, and
testing-log/package-chat evidence requirements. This module does NOT duplicate
field-level transformation or idempotency assertions already owned by each
state's ``test_load.py``.
"""

from __future__ import annotations

import os
import subprocess

import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.CO.scraper.cli import (
    main as co_main,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.cli import (
    main as ga_main,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.cli import (
    main as nc_main,
)

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Fixture paths — mirror what Makefile sample targets pass
# ---------------------------------------------------------------------------

_CO_SAMPLE_ARGS = [
    "--path",
    "domains/campaign_finance/jurisdictions/states/CO/scraper/test_fixtures/sample_contributions.csv",
    "--year",
    "2024",
    "--data-type",
    "contributions",
]

_GA_SAMPLE_ARGS = [
    "--path",
    "domains/campaign_finance/jurisdictions/states/GA/tests/fixtures/contribution_export_sample.xls",
    "--data-type",
    "contributions",
]

_NC_SAMPLE_ARGS = [
    "--path",
    "domains/campaign_finance/jurisdictions/states/NC/tests/fixtures/transaction_export_sample.csv",
    "--data-type",
    "transactions",
]

_STATE_SAMPLE_INGESTS = (
    ("CO", co_main, _CO_SAMPLE_ARGS),
    ("GA", ga_main, _GA_SAMPLE_ARGS),
    ("NC", nc_main, _NC_SAMPLE_ARGS),
)
_STAGE5_PRESEED_INGEST_TARGETS = (
    "ingest-ca-sample",
    "ingest-mn-sample",
    "ingest-wa-sample",
)

_COUNT_BY_STATE_SQL = {
    "filing": """
        SELECT COUNT(*) AS n
        FROM cf.filing f
        JOIN cf.committee c ON c.id = f.committee_id
        WHERE c.state = %s
        """,
    "transaction": """
        SELECT COUNT(*) AS n
        FROM cf.transaction t
        JOIN cf.committee c ON c.id = t.committee_id
        WHERE c.state = %s
        """,
}


def _run_state_sample_ingests() -> None:
    for state, cli_main, args in _STATE_SAMPLE_INGESTS:
        assert cli_main(args) == 0, f"{state} sample ingest failed"


def _ensure_test_postgres_password() -> None:
    os.environ.setdefault("POSTGRES_PASSWORD", "civibus_dev")


def _run_make_target(target: str) -> None:
    subprocess.run(["make", target], check=True, capture_output=True, env=os.environ.copy())


def _run_stage5_preseed_ingests() -> None:
    for target in _STAGE5_PRESEED_INGEST_TARGETS:
        _run_make_target(target)


def _count_rows_for_state(conn, *, row_type: str, state: str) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_COUNT_BY_STATE_SQL[row_type], (state,))
        return cur.fetchone()["n"]


# ---------------------------------------------------------------------------
# Module-scoped fixture: reset DB then run all three sample ingests once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def state_ingest_db():
    """Reset database, pre-seed CA/MN/WA, then run CO/GA/NC sample ingests."""
    _ensure_test_postgres_password()
    _run_make_target("db-reset")
    _run_stage5_preseed_ingests()
    _run_state_sample_ingests()

    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CO: filing-aware path — filing and transaction rows must exist
# ---------------------------------------------------------------------------


class TestCORelationalChain:
    def test_co_filing_count_nonzero(self, state_ingest_db):
        assert _count_rows_for_state(state_ingest_db, row_type="filing", state="CO") > 0

    def test_co_transaction_count_nonzero(self, state_ingest_db):
        assert _count_rows_for_state(state_ingest_db, row_type="transaction", state="CO") > 0

    def test_co_full_relational_chain_join(self, state_ingest_db):
        """Prove cf.transaction -> cf.filing -> cf.committee -> core.organization."""
        with state_ingest_db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT t.transaction_identifier,
                       f.filing_fec_id,
                       o.identifiers ->> 'co_committee_id' AS committee_identifier,
                       o.canonical_name
                FROM cf.transaction t
                JOIN cf.filing f ON f.id = t.filing_id
                JOIN cf.committee c ON c.id = t.committee_id
                JOIN core.organization o ON o.id = c.organization_id
                WHERE c.state = 'CO'
                  AND f.filing_fec_id IS NOT NULL
                  AND o.identifiers ? 'co_committee_id'
                  AND o.canonical_name IS NOT NULL
                LIMIT 10
                """
            )
            rows = cur.fetchall()

        assert len(rows) > 0, "No CO rows with full relational chain"
        for row in rows:
            assert row["transaction_identifier"] is not None
            assert row["filing_fec_id"] is not None
            assert row["committee_identifier"] is not None
            assert row["canonical_name"] is not None


class TestStage5PreseedStateSources:
    def test_preseed_state_data_sources_exist(self, state_ingest_db):
        with state_ingest_db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT jurisdiction, COUNT(*) AS n
                FROM core.data_source
                WHERE domain = 'campaign_finance'
                  AND jurisdiction IN ('state/CA', 'state/MN', 'state/WA')
                GROUP BY jurisdiction
                """
            )
            rows = cur.fetchall()

        counts = {row["jurisdiction"]: row["n"] for row in rows}
        assert counts.get("state/CA", 0) > 0
        assert counts.get("state/MN", 0) > 0
        assert counts.get("state/WA", 0) > 0


# ---------------------------------------------------------------------------
# GA: filing-aware path — filing and transaction rows must exist
# ---------------------------------------------------------------------------


class TestGARelationalChain:
    def test_ga_filing_count_nonzero(self, state_ingest_db):
        assert _count_rows_for_state(state_ingest_db, row_type="filing", state="GA") > 0

    def test_ga_transaction_count_nonzero(self, state_ingest_db):
        assert _count_rows_for_state(state_ingest_db, row_type="transaction", state="GA") > 0


# ---------------------------------------------------------------------------
# NC: provenance-only path — no cf.transaction rows expected without
# --committee-docs-path, but the CLI must exit successfully
# ---------------------------------------------------------------------------


class TestNCProvenanceOnly:
    def test_nc_no_transaction_rows_from_provenance_path(self, state_ingest_db):
        """NC sample ingest without --committee-docs-path must NOT create cf.transaction rows."""
        count = _count_rows_for_state(
            state_ingest_db,
            row_type="transaction",
            state="NC",
        )
        assert count == 0, f"Expected 0 NC transaction rows on provenance-only path, got {count}"
