from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions._test_helpers import (
    _source_record_count,
    clear_state_loader_records,
)
from domains.campaign_finance.jurisdictions.states.FL.scraper import load as fl_load_module
from domains.campaign_finance.jurisdictions.states.FL.scraper.load import (
    LoadResult,
    ensure_fl_data_source,
    load_fl_contribution,
    load_fl_contributions_with_filings,
    load_fl_expenditures_with_filings,
    load_fl_other_with_filings,
    load_fl_transfers_with_filings,
)
from domains.campaign_finance.jurisdictions.states.FL.scraper.parse import parse_contributions

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.txt"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.txt"
_SAMPLE_TRANSFERS_PATH = _FIXTURE_DIR / "sample_transfers.txt"
_SAMPLE_OTHER_PATH = _FIXTURE_DIR / "sample_other.txt"
_FL_JURISDICTION = "state/FL"
_FL_STATE_CODE = "FL"


def _parsed_contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))


@pytest.fixture(autouse=True)
def _isolate_fl_loader_state(request: pytest.FixtureRequest) -> None:
    if "db_conn" not in request.fixturenames:
        return
    db_conn = request.getfixturevalue("db_conn")
    clear_state_loader_records(db_conn, jurisdiction=_FL_JURISDICTION, state_code=_FL_STATE_CODE)


def test_ensure_fl_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_fl_data_source(db_conn, data_type="contributions")
    second_id = ensure_fl_data_source(db_conn, data_type="contributions")

    assert first_id == second_id


def test_ensure_fl_data_source_uses_distinct_names_per_data_type(db_conn: psycopg.Connection) -> None:
    contribution_id = ensure_fl_data_source(db_conn, data_type="contributions")
    expenditure_id = ensure_fl_data_source(db_conn, data_type="expenditures")
    transfer_id = ensure_fl_data_source(db_conn, data_type="transfers")
    other_id = ensure_fl_data_source(db_conn, data_type="other")

    ids = {contribution_id, expenditure_id, transfer_id, other_id}
    assert len(ids) == 4


def test_load_fl_contribution_deduplicates_by_source_record_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_contribution_rows()[0]
    data_source_id = ensure_fl_data_source(db_conn, data_type="contributions")

    first_insert = load_fl_contribution(db_conn, row, data_source_id)
    second_insert = load_fl_contribution(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False
    assert _source_record_count(db_conn, data_source_id) == 1


def test_load_fl_contributions_with_filings_is_idempotent(db_conn: psycopg.Connection) -> None:
    result = load_fl_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    assert isinstance(result, LoadResult)
    assert result.inserted == 2
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   t.transaction_identifier,
                   t.amount::text AS amount,
                   t.source_record_id,
                   sr.record_hash,
                   sr.raw_fields
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            JOIN core.source_record sr
              ON sr.id = t.source_record_id
            WHERE f.filing_fec_id LIKE 'FL-%-contributions'
            ORDER BY f.filing_fec_id, t.transaction_identifier
            """,
        )
        first_transaction_snapshot = cursor.fetchall()

    rerun = load_fl_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)
    assert rerun.inserted == 0
    assert rerun.skipped == 2
    assert rerun.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   t.transaction_identifier,
                   t.amount::text AS amount,
                   t.source_record_id,
                   sr.record_hash,
                   sr.raw_fields
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            JOIN core.source_record sr
              ON sr.id = t.source_record_id
            WHERE f.filing_fec_id LIKE 'FL-%-contributions'
            ORDER BY f.filing_fec_id, t.transaction_identifier
            """,
        )
        second_transaction_snapshot = cursor.fetchall()

    assert second_transaction_snapshot == first_transaction_snapshot


def test_load_fl_expenditures_with_filings_maps_amount_and_type(db_conn: psycopg.Connection) -> None:
    result = load_fl_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)

    assert result.inserted + result.skipped == 2
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_type, t.amount
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'FL-%-expenditures'
            ORDER BY t.amount DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["transaction_type"] == "MON"
    assert row["amount"] == Decimal("3978.00")

    rerun = load_fl_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)
    assert rerun.inserted == 0
    assert rerun.skipped == 2
    assert rerun.errors == 0


def test_fl_is_independent_expenditure_true_for_assumed_ind_token() -> None:
    row = {"Type": "IND"}
    assert fl_load_module._fl_is_independent_expenditure(row, data_type="expenditures") is True


def test_fl_is_independent_expenditure_false_for_non_ie_token() -> None:
    row = {"Type": "MON"}
    assert fl_load_module._fl_is_independent_expenditure(row, data_type="expenditures") is False


@pytest.mark.parametrize("raw_value", ["", None])
def test_fl_is_independent_expenditure_false_for_blank_or_null(raw_value: str | None) -> None:
    row = {"Type": raw_value}
    assert fl_load_module._fl_is_independent_expenditure(row, data_type="expenditures") is False


def test_fl_is_independent_expenditure_false_for_non_expenditure_data_type() -> None:
    row = {"Type": "IND", "Typ": "IND"}
    assert fl_load_module._fl_is_independent_expenditure(row, data_type="contributions") is False


def test_upsert_fl_transaction_overrides_type_for_independent_expenditure(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(fl_load_module, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(fl_load_module, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(fl_load_module, "_resolve_fl_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(fl_load_module, "_counterparty_address", lambda _row, _data_type: None)
    monkeypatch.setattr(fl_load_module, "_counterparty_name_raw", lambda _row, _data_type: "SYNTHETIC PAYEE")

    row = {
        "Date": "03/25/2026",
        "Amount": "500.00",
        "Type": "IND",
    }
    fl_load_module._upsert_fl_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "Independent Expenditure"


def test_load_fl_transfers_with_filings_ingests_fixture(db_conn: psycopg.Connection) -> None:
    result = load_fl_transfers_with_filings(db_conn, _SAMPLE_TRANSFERS_PATH)

    assert result.inserted == 1
    assert result.errors == 0


def test_load_fl_other_with_filings_ingests_fixture(db_conn: psycopg.Connection) -> None:
    result = load_fl_other_with_filings(db_conn, _SAMPLE_OTHER_PATH)

    assert result.inserted == 2
    assert result.errors == 0
