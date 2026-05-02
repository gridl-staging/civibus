from __future__ import annotations
import csv
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions._test_helpers import clear_state_loader_records
from domains.campaign_finance.jurisdictions.states.TX.scraper import load as tx_load_module
from domains.campaign_finance.jurisdictions.states.TX.scraper.load import (
    LoadResult,
    _parse_tx_date,
    _tx_amendment_indicator,
    _tx_filing_fec_id,
    _tx_source_record_key,
    _tx_transaction_identifier,
    ensure_tx_data_source,
    load_tx_contribution,
    load_tx_contributions_with_filings,
    load_tx_expenditures_with_filings,
    load_tx_loans_with_filings,
)
from domains.campaign_finance.jurisdictions.states.TX.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_loans,
)

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"
_TX_JURISDICTION = "state/TX"
_TX_STATE_CODE = "TX"


def _parsed_contributions() -> list[dict[str, str | None]]:
    return list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))


def _parsed_expenditures() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))


def _write_csv_rows(
    csv_path: Path,
    *,
    fieldnames: list[str],
    rows: list[dict[str, str | None]],
) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) or "" for column in fieldnames})


def _reader_connection_or_skip(db_conn: psycopg.Connection) -> psycopg.Connection:
    try:
        return psycopg.connect(db_conn.info.dsn)
    except (RuntimeError, psycopg.Error) as error:
        message = str(error)
        if message.startswith("Unable to connect to PostgreSQL at ") or "connection" in message.lower():
            pytest.skip(message)
        raise


def _sample_load_result() -> LoadResult:
    return LoadResult(
        inserted=2,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )


def _stub_load_tx_with_filings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ensure_data_source: object,
    relational_side_effect: Exception | None = None,
) -> None:
    monkeypatch.setattr(tx_load_module, "ensure_tx_data_source", ensure_data_source)
    monkeypatch.setattr(tx_load_module, "_load_tx_file", lambda *_args, **_kwargs: _sample_load_result())
    monkeypatch.setitem(tx_load_module._TX_PARSER_FN, "contributions", lambda _path, **_kw: iter(()))

    relational_loader = MagicMock()
    if relational_side_effect is not None:
        relational_loader.side_effect = relational_side_effect
    monkeypatch.setattr(tx_load_module, "_load_tx_relational_transactions", relational_loader)


@pytest.fixture(autouse=True)
def _isolate_tx_loader_state(
    request: pytest.FixtureRequest,
) -> None:
    # Keep pure helper tests runnable without forcing the integration DB fixture.
    if "db_conn" not in request.fixturenames:
        return
    db_conn = request.getfixturevalue("db_conn")
    clear_state_loader_records(db_conn, jurisdiction=_TX_JURISDICTION, state_code=_TX_STATE_CODE)


def test_source_record_key_and_transaction_identifier_follow_stage1_rules() -> None:
    row = _parsed_contributions()[0]

    assert _tx_source_record_key(row, data_type="contributions") == row["contributionInfoId"]
    assert _tx_transaction_identifier(row, data_type="contributions") == row["contributionInfoId"]


def test_filing_fec_id_and_date_parsing_follow_stage1_rules() -> None:
    row = _parsed_contributions()[0]

    assert _tx_filing_fec_id(row, data_type="contributions") == "TX-00057770-2008-contributions"
    assert _parse_tx_date("20080410") == date(2008, 4, 10)


def test_amendment_indicator_uses_info_only_flag_and_form_type_code() -> None:
    contribution_row = _parsed_contributions()[0]
    expenditure_row = _parsed_expenditures()[0]

    assert _tx_amendment_indicator(contribution_row, data_type="contributions") == "T"
    assert _tx_amendment_indicator(expenditure_row, data_type="expenditures") == "A"


def test_tx_is_independent_expenditure_true_for_dce_form_type() -> None:
    row = {"formTypeCd": "DCE", "schedFormTypeCd": "F1"}
    assert tx_load_module._tx_is_independent_expenditure(row, data_type="expenditures") is True


def test_tx_is_independent_expenditure_false_for_non_ie_code() -> None:
    row = {"formTypeCd": "CORCOH", "schedFormTypeCd": "F1"}
    assert tx_load_module._tx_is_independent_expenditure(row, data_type="expenditures") is False


@pytest.mark.parametrize("raw_value", ["", None])
def test_tx_is_independent_expenditure_false_for_blank_or_null(raw_value: str | None) -> None:
    row = {"formTypeCd": raw_value, "schedFormTypeCd": "F1"}
    assert tx_load_module._tx_is_independent_expenditure(row, data_type="expenditures") is False


def test_tx_is_independent_expenditure_false_for_non_expenditure_data_type() -> None:
    row = {"formTypeCd": "DCE", "schedFormTypeCd": "F1"}
    assert tx_load_module._tx_is_independent_expenditure(row, data_type="contributions") is False


def test_upsert_tx_transaction_overrides_type_for_independent_expenditure(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(tx_load_module, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(tx_load_module, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(tx_load_module, "_resolve_tx_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(tx_load_module, "_select_tx_transaction_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(
        tx_load_module,
        "_tx_extract_row",
        lambda _row, _data_type: {"payee_person": None, "payee_org": None, "address": None},
    )

    row = dict(_parsed_expenditures()[0])
    row["schedFormTypeCd"] = "F1"
    row["formTypeCd"] = "DCE"
    row["expendDt"] = "20260115"
    row["expendAmount"] = "100.00"
    row["expendInfoId"] = "TX-IE-SYNTH-1"

    tx_load_module._upsert_tx_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "Independent Expenditure"


def test_load_tx_contribution_deduplicates_source_record_by_stage1_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_contributions()[0]
    data_source_id = ensure_tx_data_source(db_conn, data_type="contributions")

    first_insert = load_tx_contribution(db_conn, row, data_source_id)
    second_insert = load_tx_contribution(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, row["contributionInfoId"]),
        )
        result = cursor.fetchone()

    assert result is not None
    assert result["count"] == 1


def test_load_tx_contributions_with_filings_is_idempotent_and_sets_keys(db_conn: psycopg.Connection) -> None:
    first_result = load_tx_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    assert isinstance(first_result, LoadResult)
    assert first_result.inserted == 10
    assert first_result.errors == 0

    expected_source_record_keys = sorted(
        _tx_source_record_key(row, data_type="contributions")
        for row in _parsed_contributions()
    )
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   f.receipt_date,
                   t.transaction_identifier,
                   t.amendment_indicator,
                   t.source_record_id
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id = %s
              AND t.transaction_identifier = %s
            LIMIT 1
            """,
            ("TX-00057770-2008-contributions", "110000001"),
        )
        row = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE filing_fec_id LIKE 'TX-%-contributions'
            """,
        )
        first_filing_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'TX-%-contributions'
            """,
        )
        first_transaction_count = cursor.fetchone()["count"]

    contribution_data_source_id = ensure_tx_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, expected_source_record_keys),
        )
        source_record_snapshot = cursor.fetchall()

    assert row is not None
    assert row["filing_fec_id"] == "TX-00057770-2008-contributions"
    assert row["receipt_date"] == date(2008, 4, 10)
    assert row["transaction_identifier"] == "110000001"
    assert row["amendment_indicator"] == "T"
    assert [record["source_record_key"] for record in source_record_snapshot] == expected_source_record_keys

    second_result = load_tx_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    assert isinstance(second_result, LoadResult)
    assert second_result.inserted == 0
    assert second_result.skipped == 10

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id,
                   f.receipt_date,
                   t.transaction_identifier,
                   t.amendment_indicator,
                   t.source_record_id
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id = %s
              AND t.transaction_identifier = %s
            LIMIT 1
            """,
            ("TX-00057770-2008-contributions", "110000001"),
        )
        rerun_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE filing_fec_id LIKE 'TX-%-contributions'
            """,
        )
        second_filing_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'TX-%-contributions'
            """,
        )
        second_transaction_count = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, expected_source_record_keys),
        )
        rerun_source_record_snapshot = cursor.fetchall()

    assert rerun_row == row
    assert second_filing_count == first_filing_count
    assert second_transaction_count == first_transaction_count
    assert rerun_source_record_snapshot == source_record_snapshot


def test_load_tx_expenditures_with_filings_maps_cor_form_type_to_amendment_a(db_conn: psycopg.Connection) -> None:
    result = load_tx_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)

    assert result.inserted == 10
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT t.amendment_indicator
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE %s
            """,
            ("TX-%-expenditures",),
        )
        amendments = {row["amendment_indicator"] for row in cursor.fetchall()}

    assert amendments == {"A"}


def test_load_tx_loans_with_filings_skips_missing_loan_amount_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    rows = list(parse_loans(_SAMPLE_LOANS_PATH))
    assert len(rows) >= 2

    test_rows = [dict(rows[0]), dict(rows[1])]
    test_rows[0]["loanAmount"] = None
    test_csv_path = tmp_path / "sample_loans_missing_amount.csv"
    _write_csv_rows(test_csv_path, fieldnames=list(test_rows[0].keys()), rows=test_rows)

    load_result = load_tx_loans_with_filings(db_conn, test_csv_path)

    assert isinstance(load_result, LoadResult)
    assert load_result.inserted == 1
    assert load_result.skipped == 0
    assert load_result.errors == 1

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN core.source_record sr ON sr.id = t.source_record_id
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.name = %s
            """,
            ("TEC Campaign Finance — Loans",),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["count"] == 1


def test_load_tx_loans_with_filings_clears_stale_filing_lookup_after_rollback(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    rows = list(parse_loans(_SAMPLE_LOANS_PATH))
    assert rows

    base_row = dict(rows[0])
    bad_row = dict(base_row)
    bad_row["loanAmount"] = None
    bad_row["loanInfoId"] = "BAD-LOOKUP-TEST-1"

    good_row = dict(base_row)
    good_row["loanAmount"] = "1234.56"
    good_row["loanInfoId"] = "GOOD-LOOKUP-TEST-2"

    test_csv_path = tmp_path / "sample_loans_stale_lookup.csv"
    _write_csv_rows(test_csv_path, fieldnames=list(base_row.keys()), rows=[bad_row, good_row])

    load_result = load_tx_loans_with_filings(db_conn, test_csv_path)

    assert isinstance(load_result, LoadResult)
    assert load_result.inserted == 1
    assert load_result.skipped == 0
    assert load_result.errors == 1

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN core.source_record sr ON sr.id = t.source_record_id
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.name = %s
              AND t.transaction_identifier = %s
            """,
            ("TEC Campaign Finance — Loans", "GOOD-LOOKUP-TEST-2"),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["count"] == 1


def test_load_tx_loans_with_filings_preserves_existing_filing_provenance_after_row_rollback(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    rows = list(parse_loans(_SAMPLE_LOANS_PATH))
    assert rows

    first_good_row = dict(rows[0])
    first_good_row["loanAmount"] = "100.00"
    first_good_row["loanInfoId"] = "GOOD-FIRST-LOOKUP-1"

    bad_row = dict(rows[0])
    bad_row["loanAmount"] = None
    bad_row["loanInfoId"] = "BAD-MIDDLE-LOOKUP-2"

    later_good_row = dict(rows[0])
    later_good_row["loanAmount"] = "200.00"
    later_good_row["loanInfoId"] = "GOOD-LATER-LOOKUP-3"

    test_csv_path = tmp_path / "sample_loans_preserve_filing_source_record.csv"
    _write_csv_rows(
        test_csv_path,
        fieldnames=list(first_good_row.keys()),
        rows=[first_good_row, bad_row, later_good_row],
    )

    load_result = load_tx_loans_with_filings(db_conn, test_csv_path)

    assert isinstance(load_result, LoadResult)
    assert load_result.inserted == 2
    assert load_result.skipped == 0
    assert load_result.errors == 1

    filing_fec_id = _tx_filing_fec_id(first_good_row, data_type="loans")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT sr.source_record_key
            FROM cf.filing f
            JOIN core.source_record sr ON sr.id = f.source_record_id
            WHERE f.filing_fec_id = %s
            LIMIT 1
            """,
            (filing_fec_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["source_record_key"] == "GOOD-FIRST-LOOKUP-1"


def test_load_tx_contributions_with_filings_keeps_caller_transaction_uncommitted(
    db_conn: psycopg.Connection,
) -> None:
    load_tx_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    with _reader_connection_or_skip(db_conn) as reader_conn, reader_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record sr
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.jurisdiction = %s
            """,
            (_TX_JURISDICTION,),
        )
        result = cursor.fetchone()

    assert result is not None
    assert result["count"] == 0


def test_load_tx_with_filings_delegates_batch_commits_to_inner_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_load_tx_with_filings must not wrap everything in a single outer transaction.

    Bug: tx-loader-no-batch-commit — wrapping all rows in one transaction disables
    the inner batch-commit logic, exhausting PostgreSQL max_locks_per_transaction
    for large datasets (500K+ rows). Inner functions now use try_row_without_savepoint
    instead of per-row conn.transaction() savepoints.
    """
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    # ensure_tx_data_source runs a query, which puts psycopg3 connection into
    # INTRANS state (implicit transaction).  Simulate this so the commit path
    # is exercised.
    def _fake_ensure_tx_data_source(*_args, **_kwargs):
        conn.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
        return "tx-source-id"

    _stub_load_tx_with_filings(monkeypatch, ensure_data_source=_fake_ensure_tx_data_source)

    tx_load_module._load_tx_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    # It must commit after ensure_tx_data_source to return connection to IDLE state
    # so inner functions detect manages_outer_transaction=True
    conn.commit.assert_called()


def test_load_tx_with_filings_preserves_caller_owned_outer_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS

    _stub_load_tx_with_filings(monkeypatch, ensure_data_source=lambda *_args, **_kwargs: "tx-source-id")

    tx_load_module._load_tx_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    conn.commit.assert_not_called()


def test_load_tx_with_filings_reports_end_to_end_elapsed_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    _stub_load_tx_with_filings(monkeypatch, ensure_data_source=lambda *_args, **_kwargs: "tx-source-id")
    monotonic = MagicMock(side_effect=[100.0, 104.25])
    monkeypatch.setattr(tx_load_module.time, "monotonic", monotonic)

    result = tx_load_module._load_tx_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    assert result.elapsed_seconds == 4.25


def test_load_tx_with_filings_propagates_relational_phase_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the relational phase fails, the error propagates but raw ingest data
    is already committed via batch commits (not rolled back in a single transaction).

    This is correct for large datasets where batch commits prevent
    max_locks_per_transaction exhaustion. The loader is idempotent, so
    re-running after a partial failure fills in the gaps.
    """
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    _stub_load_tx_with_filings(
        monkeypatch,
        ensure_data_source=lambda *_args, **_kwargs: "tx-source-id",
        relational_side_effect=RuntimeError("relational failed"),
    )

    with pytest.raises(RuntimeError, match="relational failed"):
        tx_load_module._load_tx_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    # No single-transaction rollback — raw ingest was already committed via batch commits
    conn.rollback.assert_not_called()
