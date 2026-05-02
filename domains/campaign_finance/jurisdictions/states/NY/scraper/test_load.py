"""Tests for NY load module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call
from uuid import uuid4

import psycopg

from domains.campaign_finance.jurisdictions.states.NY.scraper import load
from domains.campaign_finance.jurisdictions.states.NY.scraper.extract import extract_ny_expenditure
from domains.campaign_finance.jurisdictions.states.NY.scraper.load import (
    load_ny_contributions_with_filings,
    load_ny_expenditures_with_filings,
    load_ny_independent_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import parse_independent_expenditures

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_IE_PATH = _FIXTURE_DIR / "sample_ie.csv"
_EXPECTED_DATA_TYPES = {"contributions", "expenditures", "independent_expenditures"}


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    """Public load wrappers should delegate to _load_ny_with_filings."""
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_ny_with_filings", internal)
    conn = MagicMock()

    load_ny_contributions_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, limit=5)
    load_ny_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, limit=6)
    load_ny_independent_expenditures_with_filings(conn, _SAMPLE_IE_PATH, limit=7)

    assert internal.call_count == 3
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"
    assert internal.call_args_list[2].kwargs["data_type"] == "independent_expenditures"


def test_conn_commit_after_ensure_data_source(monkeypatch) -> None:
    """Regression: ensure_ny_data_source leaves conn IN_TRANSACTION.

    _load_ny_with_filings must call conn.commit() after ensure_ny_data_source
    so that _load_ny_rows sees IDLE transaction status and enables periodic
    commits every 1000 rows. Without this, NY's ~3.2M rows accumulate in one
    massive uncommitted transaction.
    """
    monkeypatch.setattr(load, "ensure_ny_data_source", MagicMock(return_value=1))
    monkeypatch.setattr(load, "_load_ny_file", MagicMock(return_value=MagicMock(errors=[])))
    monkeypatch.setattr(load, "_load_ny_relational_transactions", MagicMock(return_value=[]))
    monkeypatch.setattr(load, "validated_limit", MagicMock(return_value=None))

    conn = MagicMock()
    load._load_ny_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    assert call.commit() in conn.method_calls, "conn.commit() was never called — periodic commits will not fire"


def test_dispatch_tables_stay_in_lockstep() -> None:
    """All NY load dispatch tables should stay in lockstep on supported data types."""
    assert set(load._NY_ENTITY_KEYS) == _EXPECTED_DATA_TYPES
    assert set(load._NY_EXTRACT_FN) == _EXPECTED_DATA_TYPES
    assert set(load._NY_PARSER_FN) == _EXPECTED_DATA_TYPES
    assert set(load._NY_COUNTERPARTY_NAME_PATHS) == _EXPECTED_DATA_TYPES
    assert set(load._NY_COUNTERPARTY_EMPLOYER_PATH) == _EXPECTED_DATA_TYPES
    assert set(load._NY_ENTITY_ROLES) == _EXPECTED_DATA_TYPES
    assert set(load._NY_COUNTERPARTY_ROLES) == _EXPECTED_DATA_TYPES


def test_independent_expenditures_reuse_expenditure_dispatch_entries() -> None:
    """IE should reuse expenditure extraction/parsing and role mappings."""
    assert load._NY_EXTRACT_FN["independent_expenditures"] is extract_ny_expenditure
    assert load._NY_PARSER_FN["independent_expenditures"] is parse_independent_expenditures
    assert load._NY_ENTITY_KEYS["independent_expenditures"] == load._NY_ENTITY_KEYS["expenditures"]
    assert (
        load._NY_COUNTERPARTY_NAME_PATHS["independent_expenditures"] == load._NY_COUNTERPARTY_NAME_PATHS["expenditures"]
    )
    assert load._NY_ENTITY_ROLES["independent_expenditures"] == load._NY_ENTITY_ROLES["expenditures"]
    assert load._NY_COUNTERPARTY_ROLES["independent_expenditures"] == load._NY_COUNTERPARTY_ROLES["expenditures"]


def test_upsert_transaction_uses_canonical_ie_transaction_type(monkeypatch) -> None:
    """IE transaction type should use the canonical shared transaction label."""
    row = next(iter(parse_independent_expenditures(_SAMPLE_IE_PATH)))
    captured: dict[str, object] = {}

    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(load, "_resolve_ny_transaction_address_id", MagicMock(return_value=None))

    def capture_upsert_transaction(_conn, transaction) -> None:  # noqa: ANN001
        captured["transaction"] = transaction

    monkeypatch.setattr(load, "upsert_transaction", capture_upsert_transaction)

    load._upsert_ny_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="independent_expenditures",
    )

    transaction = captured["transaction"]
    assert transaction.transaction_type == "Independent Expenditure"
    assert transaction.transaction_type != row["filing_sched_abbrev"]


def test_load_ny_independent_expenditures_is_idempotent_for_fixture_reruns(db_conn: psycopg.Connection) -> None:
    """Rerunning NY IE load should preserve source-record and transaction cardinality."""
    first_result = load_ny_independent_expenditures_with_filings(db_conn, _SAMPLE_IE_PATH)
    second_result = load_ny_independent_expenditures_with_filings(db_conn, _SAMPLE_IE_PATH)

    assert first_result.inserted > 0
    assert second_result.inserted == 0
    assert second_result.skipped > 0

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.jurisdiction = 'state/NY'
              AND ds.name = 'NY BoE Independent Expenditures'
            """,
        )
        source_record_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'NY-%-independent_expenditures'
            """,
        )
        ny_ie_transaction_count = cursor.fetchone()[0]

    assert source_record_count == 2
    assert ny_ie_transaction_count == 2
