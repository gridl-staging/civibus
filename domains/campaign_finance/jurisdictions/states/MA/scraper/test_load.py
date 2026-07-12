"""Tests for MA load module — IE classification and production loading."""

from __future__ import annotations

import os
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call
from uuid import uuid4

import psycopg
import pytest

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.MA.scraper import load
from domains.campaign_finance.jurisdictions.states.MA.scraper.load import (
    load_ma_contributions_with_filings,
    load_ma_expenditures_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_REPORT_ITEMS_PATH = _FIXTURE_DIR / "sample_report_items.txt"
_PROTECTED_DATABASE_NAMES = frozenset({"civibus", "civibus_prod", "civibus_staging"})
_DEADLOCK_STATEMENT_TIMEOUT = "2s"


def _required_dedicated_database_name() -> str:
    database_name = os.getenv("CF_SCHEMA_TEST_DATABASE", "").strip()
    if not database_name:
        pytest.skip(
            "Skipping MA deadlock integration tests: CF_SCHEMA_TEST_DATABASE is not set. "
            "Run against a dedicated non-production database."
        )
    if database_name in _PROTECTED_DATABASE_NAMES:
        pytest.skip(
            f"Skipping MA deadlock integration tests: refusing to run against protected database {database_name!r}."
        )
    postgres_database_name = os.getenv("POSTGRES_DB", "").strip()
    if postgres_database_name and postgres_database_name != database_name:
        pytest.skip(
            "Skipping MA deadlock integration tests: POSTGRES_DB and "
            "CF_SCHEMA_TEST_DATABASE must point at the same dedicated database."
        )
    return database_name


def _open_connection_or_skip() -> psycopg.Connection:
    try:
        return get_connection()
    except RuntimeError as exc:
        pytest.skip(f"Skipping MA deadlock integration tests: cannot connect to dedicated DB ({exc})")


@pytest.fixture(autouse=True)
def _isolate_ma_deadlock_rows_via_short_timeout_probe(request: pytest.FixtureRequest) -> None:
    if "deadlock" not in request.node.name.lower():
        return

    database_name = _required_dedicated_database_name()
    probe_conn = _open_connection_or_skip()
    try:
        probe_conn.execute("BEGIN")
        probe_conn.execute(f"SET LOCAL statement_timeout = '{_DEADLOCK_STATEMENT_TIMEOUT}'")
        try:
            has_schema = probe_conn.execute(
                """
                SELECT to_regclass('core.source_record') IS NOT NULL
                   AND to_regclass('cf.filing') IS NOT NULL
                """
            ).fetchone()
            if not has_schema or not has_schema[0]:
                pytest.skip(
                    f"Skipping MA deadlock integration tests: required schemas/tables are "
                    f"missing from dedicated DB {database_name!r}."
                )
            existing_ma_row = probe_conn.execute(
                "SELECT 1 FROM cf.filing WHERE filing_fec_id LIKE 'MA-%' LIMIT 1"
            ).fetchone()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                "Skipping MA deadlock integration tests: unable to verify safe isolation with "
                f"short timeout probe ({exc!r})."
            )
        finally:
            probe_conn.execute("SET LOCAL statement_timeout = 0")
            probe_conn.rollback()
        if existing_ma_row is not None:
            pytest.skip(
                "Skipping MA deadlock integration tests: dedicated DB already contains MA filings; "
                "this regression requires an isolated database with no pre-existing MA rows."
            )
    finally:
        probe_conn.close()


def _build_deadlock_row(
    *,
    item_id: str,
    report_id: str,
    record_type_id: str,
    related_cpf_id: str,
    name: str,
    first_name: str = "",
    amount: str = "250.00",
    is_supported: str = "",
) -> dict[str, str]:
    return {
        "Item_ID": item_id,
        "Report_ID": report_id,
        "Record_Type_ID": record_type_id,
        "Date": "04/29/2026",
        "Amount": amount,
        "Name": name,
        "First_Name": first_name,
        "Street_Address": "10 Test Way",
        "City": "Boston",
        "State": "MA",
        "Zip": "02108",
        "Description": "MA deadlock regression row",
        "Related_CPF_ID": related_cpf_id,
        "Occupation": "Engineer",
        "Employer": "Civibus",
        "Principal_Officer": "",
        "Tender_Type_ID": "1",
        "Clarified_Name": "",
        "Clarified_Purpose": "",
        "Is_Supported": is_supported,
        "Is_Previous_Year_Receipt": "0",
    }


def _seed_ma_relational_prerequisites(
    setup_conn: psycopg.Connection,
    *,
    rows_by_type: dict[str, list[dict[str, str]]],
) -> Any:
    data_source_id = load.ensure_ma_data_source(setup_conn)
    seeded_any = False
    for data_type, rows in rows_by_type.items():
        for row in rows:
            inserted = load._extract_and_load_ma_row(setup_conn, row, data_source_id, data_type=data_type)
            assert inserted, (
                "Expected pass-1 source-record/entity seeding to insert each synthetic MA row; "
                f"duplicate source_record for data_type={data_type!r}, item={row.get('Item_ID')!r}, "
                f"report={row.get('Report_ID')!r}."
            )
            source_record_id = load._select_ma_source_record_id(
                setup_conn,
                data_source_id=data_source_id,
                source_record_key=load._ma_source_record_key(row),
            )
            assert source_record_id is not None, "Seeded MA row is missing its source_record for relational pass"
            seeded_any = True
    assert seeded_any, "Deadlock regression requires at least one seeded MA row"
    setup_conn.commit()
    return data_source_id


def _run_ma_relational_pass_with_short_timeout(
    worker_conn: psycopg.Connection,
    *,
    rows: list[dict[str, str]],
    data_source_id: Any,
    data_type: str,
) -> int:
    worker_conn.execute(f"SET statement_timeout = '{_DEADLOCK_STATEMENT_TIMEOUT}'")
    try:
        return load._load_ma_relational_transactions(
            worker_conn,
            rows,
            data_source_id=data_source_id,
            data_type=data_type,
            limit=None,
        )
    finally:
        worker_conn.execute("SET statement_timeout = 0")


@pytest.mark.integration
def test_ma_relational_committee_upsert_concurrency_regression_deadlock(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Red regression: concurrent MA relational passes deadlock in committee upsert path."""
    _required_dedicated_database_name()
    caplog.set_level("ERROR", logger=load.LOGGER.name)

    # Two lanes share one Related_CPF_ID committee id so both workers contend in ensure_state_committee().
    run_suffix = uuid4().hex[:12]
    shared_related_cpf_id = f"MA-DEADLOCK-CPF-{run_suffix}"
    contribution_rows = [
        _build_deadlock_row(
            item_id=f"MA-DEADLOCK-C-{run_suffix}",
            report_id=f"MA-DEADLOCK-RC-{run_suffix}",
            record_type_id="201",
            related_cpf_id=shared_related_cpf_id,
            name="Synthetic Contributor",
            first_name="Casey",
            amount="125.00",
        )
    ]
    expenditure_rows = [
        _build_deadlock_row(
            item_id=f"MA-DEADLOCK-E-{run_suffix}",
            report_id=f"MA-DEADLOCK-RE-{run_suffix}",
            record_type_id="301",
            related_cpf_id=shared_related_cpf_id,
            name="Synthetic Vendor LLC",
            amount="175.00",
            is_supported="1",
        )
    ]

    setup_conn = _open_connection_or_skip()
    contribution_worker_conn = _open_connection_or_skip()
    expenditure_worker_conn = _open_connection_or_skip()

    try:
        data_source_id = _seed_ma_relational_prerequisites(
            setup_conn,
            rows_by_type={
                "contributions": contribution_rows,
                "expenditures": expenditure_rows,
            },
        )

        start_barrier = threading.Barrier(2)
        committee_barrier = threading.Barrier(2)
        first_ensure_threads: set[int] = set()
        ensure_state_committee_calls: list[tuple[int, str, str]] = []
        ensure_thread_lock = threading.Lock()
        original_ensure_state_committee = load.ensure_state_committee

        def _synchronized_ensure_state_committee(
            conn: psycopg.Connection,
            *,
            state: str,
            native_committee_id: str,
            organization_id: Any,
        ) -> Any:
            # Force both lanes to enter their first committee upsert together.
            current_thread_id = threading.get_ident()
            should_wait = False
            with ensure_thread_lock:
                ensure_state_committee_calls.append((current_thread_id, state, native_committee_id))
                if current_thread_id not in first_ensure_threads:
                    first_ensure_threads.add(current_thread_id)
                    should_wait = True
            if should_wait:
                committee_barrier.wait(timeout=2)
            return original_ensure_state_committee(
                conn,
                state=state,
                native_committee_id=native_committee_id,
                organization_id=organization_id,
            )

        results: dict[str, int] = {}
        errors: list[BaseException] = []

        def _worker(
            lane: str,
            worker_conn: psycopg.Connection,
            rows: list[dict[str, str]],
            data_type: str,
        ) -> None:
            try:
                start_barrier.wait(timeout=2)
                results[lane] = _run_ma_relational_pass_with_short_timeout(
                    worker_conn,
                    rows=rows,
                    data_source_id=data_source_id,
                    data_type=data_type,
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        try:
            load.ensure_state_committee = _synchronized_ensure_state_committee
            contribution_thread = threading.Thread(
                target=_worker,
                kwargs={
                    "lane": "contributions",
                    "worker_conn": contribution_worker_conn,
                    "rows": contribution_rows,
                    "data_type": "contributions",
                },
                daemon=True,
            )
            expenditure_thread = threading.Thread(
                target=_worker,
                kwargs={
                    "lane": "expenditures",
                    "worker_conn": expenditure_worker_conn,
                    "rows": expenditure_rows,
                    "data_type": "expenditures",
                },
                daemon=True,
            )
            contribution_thread.start()
            expenditure_thread.start()
            contribution_thread.join(timeout=30)
            expenditure_thread.join(timeout=30)
        finally:
            load.ensure_state_committee = original_ensure_state_committee

        assert not contribution_thread.is_alive(), "Contribution worker timed out during MA deadlock regression"
        assert not expenditure_thread.is_alive(), "Expenditure worker timed out during MA deadlock regression"
        assert not errors, f"Worker thread crashed before deadlock assertion: {errors!r}"
        assert set(results) == {"contributions", "expenditures"}, "Both MA relational worker results are required"
        matching_committee_threads = {
            thread_id
            for thread_id, committee_state, native_committee_id in ensure_state_committee_calls
            if committee_state == "MA" and native_committee_id == shared_related_cpf_id
        }
        assert len(matching_committee_threads) == 2, (
            "Deadlock regression precondition failed: both workers must enter ensure_state_committee() "
            "with the shared MA Related_CPF_ID before asserting lock contention."
        )

        contribution_errors = results["contributions"]
        expenditure_errors = results["expenditures"]
        if contribution_errors + expenditure_errors > 0:
            assert 'relation "committee"' in caplog.text, (
                "Deadlock regression failed without committee-lock evidence in logs; "
                "expected contention to surface via cf.committee index-tuple timeout."
            )
        assert contribution_errors == 0, (
            "Red regression: MA contributions relational pass hit committee-upsert locking under concurrency; "
            "expected zero relational errors after fix."
        )
        assert expenditure_errors == 0, (
            "Red regression: MA expenditures relational pass hit committee-upsert locking under concurrency; "
            "expected zero relational errors after fix."
        )
    finally:
        for conn in (contribution_worker_conn, expenditure_worker_conn, setup_conn):
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            conn.close()


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    """Both public load functions should delegate to _load_ma_with_filings."""
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_ma_with_filings", internal)
    conn = MagicMock()

    load_ma_contributions_with_filings(conn, _SAMPLE_REPORT_ITEMS_PATH, limit=5)
    load_ma_expenditures_with_filings(conn, _SAMPLE_REPORT_ITEMS_PATH, limit=6)

    assert internal.call_count == 2
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"


def test_conn_commit_after_ensure_data_source(monkeypatch) -> None:
    """Regression: ensure_ma_data_source leaves conn IN_TRANSACTION.

    _load_ma_with_filings must call conn.commit() after ensure_ma_data_source
    so that _load_ma_rows sees IDLE transaction status and enables periodic
    commits every 1000 rows.
    """
    monkeypatch.setattr(load, "ensure_ma_data_source", MagicMock(return_value=1))
    monkeypatch.setattr(load, "_load_ma_file", MagicMock(return_value=MagicMock(errors=[])))
    monkeypatch.setattr(load, "_load_ma_relational_transactions", MagicMock(return_value=[]))
    monkeypatch.setattr(load, "validated_limit", MagicMock(return_value=None))

    conn = MagicMock()
    load._load_ma_with_filings(conn, _SAMPLE_REPORT_ITEMS_PATH, data_type="contributions")

    assert call.commit() in conn.method_calls, "conn.commit() was never called — periodic commits will not fire"


# --- Amount parsing tests ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100.00", Decimal("100.00")),
        ("$1,234.56", Decimal("1234.56")),
        ("20.0020", Decimal("20.00")),
        ("175.0080", Decimal("175.01")),
        ("36.4450", Decimal("36.44")),
        ("200.0044", Decimal("200.00")),
        ("0.005", Decimal("0.00")),
        ("50", Decimal("50.00")),
    ],
)
def test_parse_required_ma_amount_quantizes_to_two_places(raw: str, expected: Decimal) -> None:
    result = load._parse_required_ma_amount(raw, "Amount")
    assert result == expected, f"_parse_required_ma_amount({raw!r}) = {result}, expected {expected}"


def test_parse_required_ma_amount_raises_for_missing() -> None:
    with pytest.raises(ValueError, match="missing"):
        load._parse_required_ma_amount(None, "Amount")


def test_parse_required_ma_amount_raises_for_invalid() -> None:
    with pytest.raises(ValueError, match="invalid"):
        load._parse_required_ma_amount("not-a-number", "Amount")


# --- IE classification tests ---


def test_ma_support_oppose_returns_s_for_truthy_values() -> None:
    for value in ("1", "True", "TRUE", "Yes", "Y"):
        row = {"Is_Supported": value}
        assert load._ma_support_oppose(row) == "S", f"Expected 'S' for {value!r}"


def test_ma_support_oppose_returns_o_for_falsy_values() -> None:
    for value in ("0", "False", "FALSE", "No", "N"):
        row = {"Is_Supported": value}
        assert load._ma_support_oppose(row) == "O", f"Expected 'O' for {value!r}"


@pytest.mark.parametrize("raw_value", ["", None])
def test_ma_support_oppose_returns_none_for_blank_or_null(raw_value: str | None) -> None:
    row = {"Is_Supported": raw_value}
    assert load._ma_support_oppose(row) is None


def test_ma_support_oppose_raises_for_unexpected_token() -> None:
    row = {"Is_Supported": "MAYBE"}
    with pytest.raises(ValueError, match="Unsupported MA Is_Supported value"):
        load._ma_support_oppose(row)


def test_upsert_ma_transaction_overrides_type_for_independent_expenditure(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_ma_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row: "SYNTHETIC PAYEE")
    monkeypatch.setitem(load._MA_EXTRACT_FN, "expenditures", lambda _row: {"address": None})

    row = {
        "Item_ID": "99999",
        "Report_ID": "88888",
        "Record_Type_ID": "301",
        "Date": "03/29/2026",
        "Amount": "500.00",
        "Name": "SYNTHETIC PAYEE",
        "First_Name": "",
        "Street_Address": "",
        "City": "",
        "State": "",
        "Zip": "",
        "Description": "Synthetic IE test row",
        "Related_CPF_ID": "77777",
        "Occupation": "",
        "Employer": "",
        "Is_Supported": "1",
    }
    load._upsert_ma_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "Independent Expenditure"
    assert captured[0].support_oppose == "S"


def test_upsert_ma_transaction_does_not_override_for_contributions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_ma_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row: "SYNTHETIC DONOR")
    monkeypatch.setitem(load._MA_EXTRACT_FN, "contributions", lambda _row: {"address": None})

    row = {
        "Item_ID": "99998",
        "Report_ID": "88888",
        "Record_Type_ID": "201",
        "Date": "03/29/2026",
        "Amount": "300.00",
        "Name": "SYNTHETIC DONOR",
        "First_Name": "",
        "Street_Address": "",
        "City": "",
        "State": "",
        "Zip": "",
        "Description": "Synthetic contribution row",
        "Related_CPF_ID": "77777",
        "Occupation": "",
        "Employer": "",
        "Is_Supported": "1",
    }
    load._upsert_ma_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="contributions",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "201"
    assert captured[0].support_oppose is None


def test_upsert_ma_transaction_no_ie_when_is_supported_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_ma_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row: "SYNTHETIC PAYEE")
    monkeypatch.setitem(load._MA_EXTRACT_FN, "expenditures", lambda _row: {"address": None})

    row = {
        "Item_ID": "99997",
        "Report_ID": "88888",
        "Record_Type_ID": "301",
        "Date": "03/29/2026",
        "Amount": "200.00",
        "Name": "SYNTHETIC PAYEE",
        "First_Name": "",
        "Street_Address": "",
        "City": "",
        "State": "",
        "Zip": "",
        "Description": "Regular expenditure",
        "Related_CPF_ID": "77777",
        "Occupation": "",
        "Employer": "",
        "Is_Supported": "",
    }
    load._upsert_ma_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "301"
    assert captured[0].support_oppose is None
