"""Cross-pipeline IE smoke test.

Loads independent expenditure data from eight sources (FEC Schedule E,
CA, MN, WA, KY, NE, CO, WI) into a single DB and verifies that all produce correct rows
in cf.transaction with transaction_type='Independent Expenditure' and valid
support_oppose values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source
from domains.campaign_finance.ingest.schedule_e_loader import load_schedule_e
from domains.campaign_finance.jurisdictions.states.CA.scraper.load import (
    load_ca_member_directory_with_filings,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import (
    load_co_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.KY.scraper.load import (
    load_ky_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.MN.scraper.load import (
    load_mn_independent_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NE.scraper.load import (
    load_ne_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.load import (
    load_ny_independent_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper.load import (
    load_wa_independent_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.WI.scraper.load import (
    load_wi_transactions_with_filings,
)
from test_support.schedule_e import extract_schedule_e_committees, seed_schedule_e_committee

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FEC_SCHEDULE_E_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "bulk" / "schedule_e_sample.csv"


def _state_fixture(state: str, filename: str) -> Path:
    """Path to a state pipeline's test fixture CSV."""
    return (
        _REPO_ROOT
        / "domains"
        / "campaign_finance"
        / "jurisdictions"
        / "states"
        / state
        / "scraper"
        / "test_fixtures"
        / filename
    )


# Each entry: (loader_fn, fixture_path, label, filing_prefix, extra_kwargs)
_STATE_IE_SOURCES: list[tuple[Callable[..., Any], Path, str, str, dict[str, Any]]] = [
    (
        load_ca_member_directory_with_filings,
        _state_fixture("CA", "sample_archive"),
        "CA expenditures",
        "CA-",
        {},
    ),
    (
        load_mn_independent_expenditures_with_filings,
        _state_fixture("MN", "sample_independent_expenditures.csv"),
        "MN IE",
        "MN-",
        {},
    ),
    (
        load_wa_independent_expenditures_with_filings,
        _state_fixture("WA", "sample_independent_expenditures.csv"),
        "WA IE",
        "WA-",
        {},
    ),
    (
        load_ky_expenditures_with_filings,
        _state_fixture("KY", "sample_expenditures.csv"),
        "KY expenditures",
        "KY::",
        {"year_from": 2022},
    ),
    (
        load_ne_expenditures_with_filings,
        _state_fixture("NE", "sample_expenditures.csv"),
        "NE expenditures",
        "NE-",
        {"year": 2026, "year_from": 2022},
    ),
    (
        load_ny_independent_expenditures_with_filings,
        _state_fixture("NY", "sample_ie.csv"),
        "NY IE",
        "NY-",
        {},
    ),
    (
        load_co_expenditures_with_filings,
        _state_fixture("CO", "sample_expenditures.csv"),
        "CO expenditures",
        "CO-",
        {},
    ),
    (
        load_wi_transactions_with_filings,
        _state_fixture("WI", "sample_transactions.csv"),
        "WI transactions",
        "WI-",
        {},
    ),
]

# All state filing prefixes — used to identify FEC rows by exclusion
_STATE_PREFIXES = tuple(prefix for _, _, _, prefix, _ in _STATE_IE_SOURCES)


def _processed_rows(result: Any) -> int:
    """Rows touched by a loader, including idempotent skips on reruns."""
    return int(getattr(result, "inserted", 0)) + int(getattr(result, "skipped", 0))


def test_all_ie_sources_produce_transaction_rows(db_conn: psycopg.Connection) -> None:
    """All IE pipelines land rows in cf.transaction with correct types."""

    # --- FEC Schedule E (cycle 2024, first 5 rows) ---
    fec_ds_id = ensure_fec_bulk_data_source(db_conn)
    for committee_fec_id, committee_name in extract_schedule_e_committees(_FEC_SCHEDULE_E_FIXTURE, limit=5):
        seed_schedule_e_committee(db_conn, committee_fec_id, committee_name)
    fec_result = load_schedule_e(db_conn, _FEC_SCHEDULE_E_FIXTURE, cycle=2024, data_source_id=fec_ds_id, limit=5)
    assert _processed_rows(fec_result) > 0, "FEC Schedule E should process at least one row"

    # --- Load all state IE sources ---
    state_results: dict[str, Any] = {}
    for loader, fixture, label, _prefix, kwargs in _STATE_IE_SOURCES:
        result = loader(db_conn, fixture, **kwargs)
        assert _processed_rows(result) > 0, f"{label} should process at least one row"
        state_results[label] = result

    # --- Cross-source query: all IE transactions ---
    with db_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT t.transaction_type,
                   t.support_oppose,
                   f.filing_fec_id
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE t.transaction_type = 'Independent Expenditure'
            ORDER BY f.filing_fec_id
            """,
        )
        ie_rows = cur.fetchall()

    # Must have rows from all sources.
    filing_ids = {row["filing_fec_id"] for row in ie_rows}

    has_fec = any(not fid.startswith(_STATE_PREFIXES) for fid in filing_ids)
    assert has_fec, f"Expected FEC Schedule E rows in cf.transaction, got filing_ids: {filing_ids}"

    for _, _, label, prefix, _ in _STATE_IE_SOURCES:
        assert any(fid.startswith(prefix) for fid in filing_ids), (
            f"Expected {label} rows in cf.transaction, got filing_ids: {filing_ids}"
        )

    # All IE transactions must have valid support_oppose
    support_oppose_values = {row["support_oppose"] for row in ie_rows}
    assert support_oppose_values <= {"S", "O", None}, f"Unexpected support_oppose values: {support_oppose_values}"
    assert "S" in support_oppose_values, "Expected at least one 'S' (support) IE transaction"
    assert "O" in support_oppose_values, "Expected at least one 'O' (oppose) IE transaction"

    # NE must contribute both S and O values
    ne_ie_rows = [row for row in ie_rows if row["filing_fec_id"].startswith("NE-")]
    ne_so_values = {row["support_oppose"] for row in ne_ie_rows}
    assert "S" in ne_so_values, f"Expected NE IE rows with support_oppose='S', got: {ne_so_values}"
    assert "O" in ne_so_values, f"Expected NE IE rows with support_oppose='O', got: {ne_so_values}"

    # Verify total IE row count covers all sources.
    # Expected fixture minimums: FEC=5, CA=1, MN=1, WA=1, KY=1, NE=2, NY=2, CO=1, WI=1.
    # Use fixed minima so the smoke test is rerunnable when upserts return inserted=0.
    expected_min_ie_rows = 15
    assert len(ie_rows) >= expected_min_ie_rows
