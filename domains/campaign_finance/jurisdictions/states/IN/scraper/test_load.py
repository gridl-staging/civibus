from __future__ import annotations

import csv
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    assert_loader_arm_is_caller_owned,
    bulk_fixture_row_counts,
    install_write_interrupt,
    seed_written_bulk_fixture,
)
from domains.campaign_finance.jurisdictions._test_helpers import clear_state_loader_records
from domains.campaign_finance.jurisdictions.states.IN.scraper import (
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper import load as in_load_module
from domains.campaign_finance.jurisdictions.states.IN.scraper import load_helpers as in_load_helpers
from domains.campaign_finance.jurisdictions.states.IN.scraper import relational_load as in_relational_load_module
from domains.campaign_finance.jurisdictions.states.IN.scraper.load import (
    LoadResult,
    ensure_in_data_source,
    load_in_contribution,
    load_in_contributions_with_filings,
    load_in_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper.load_helpers import (
    _in_amendment_indicator,
    _in_filing_fec_id,
    _in_native_committee_id,
    _in_source_record_key,
    _parse_in_date,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper.load_test_support import (
    write_in_contribution_fixture,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper.parse import parse_contributions, parse_expenditures

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
_IN_JURISDICTION = "state/IN"
_IN_STATE_CODE = "IN"


# --- helper fixtures and field accessors ---


def _column(data_type: str, semantic_path: str) -> str:
    return _load_column_for_semantic_path(data_type, semantic_path)


def _parsed_contributions() -> list[dict[str, str | None]]:
    return list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))


def _parsed_expenditures() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))


# --- pure helper tests (TDD stage: non-DB slice) ---


def test_load_result_is_constructible() -> None:
    result = LoadResult(
        inserted=8,
        skipped=2,
        quarantined=1,
        superseded=0,
        errors=0,
        elapsed_seconds=0.35,
    )

    assert result.inserted == 8
    assert result.skipped == 2
    assert result.quarantined == 1
    assert result.superseded == 0
    assert result.elapsed_seconds == 0.35


def test_parse_in_date_supports_stage2_timestamp_shape() -> None:
    assert _parse_in_date("2025-08-28 16:24:45") == date(2025, 8, 28)
    assert _parse_in_date("2025-03-03 00:00:00") == date(2025, 3, 3)


def test_parse_in_date_returns_none_for_blank_values() -> None:
    assert _parse_in_date(None) is None
    assert _parse_in_date("") is None
    assert _parse_in_date("   ") is None


def test_in_amendment_indicator_maps_stage2_0_1_flags() -> None:
    contribution_row = _parsed_contributions()[0]
    amended_contribution_row = _parsed_contributions()[4]
    expenditure_row = _parsed_expenditures()[0]
    amended_expenditure_row = _parsed_expenditures()[7]

    assert _in_amendment_indicator(contribution_row, data_type="contributions") == "N"
    assert _in_amendment_indicator(amended_contribution_row, data_type="contributions") == "A"
    assert _in_amendment_indicator(expenditure_row, data_type="expenditures") == "N"
    assert _in_amendment_indicator(amended_expenditure_row, data_type="expenditures") == "A"


def test_in_source_record_key_uses_row_hash_without_native_row_id() -> None:
    row = _parsed_contributions()[0]

    key = _in_source_record_key(row, data_type="contributions")

    assert key == compute_record_hash(dict(row))
    assert len(key) == 64


def test_in_filing_fec_id_uses_file_number_year_and_data_type() -> None:
    contribution_row = _parsed_contributions()[0]
    expenditure_row = _parsed_expenditures()[0]

    assert _in_filing_fec_id(contribution_row, data_type="contributions") == "IN-17-2025-contributions"
    assert _in_filing_fec_id(expenditure_row, data_type="expenditures") == "IN-17-2025-expenditures"


def test_in_filing_fec_id_uses_semantic_path_columns_not_hardcoded() -> None:
    row = dict(_parsed_contributions()[0])
    file_number_column = _column("contributions", "filing.id")
    date_column = _column("contributions", "transaction.date")

    row[file_number_column] = "9001"
    row[date_column] = "2024-12-31 23:59:59"

    assert _in_filing_fec_id(row, data_type="contributions") == "IN-9001-2024-contributions"


def test_in_native_committee_id_uses_committee_fields_not_filing_number() -> None:
    contribution_row = dict(_parsed_contributions()[0])
    expenditure_row = dict(_parsed_expenditures()[0])
    contribution_file_number_column = _column("contributions", "filing.id")

    contribution_row[contribution_file_number_column] = "999999"

    assert _in_native_committee_id(contribution_row, data_type="contributions") == (
        "indiana republican state committee, inc::regular party"
    )
    assert _in_native_committee_id(contribution_row, data_type="contributions") == _in_native_committee_id(
        expenditure_row,
        data_type="expenditures",
    )


def test_resolve_in_filing_committee_id_uses_stable_committee_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pytest.importorskip("unittest.mock").MagicMock()
    row = _parsed_contributions()[0]
    expected_committee_id = _in_native_committee_id(row, data_type="contributions")

    monkeypatch.setattr(
        in_relational_load_module,
        "_resolve_in_committee_organization_id",
        lambda *_args, **_kwargs: "org-id",
    )
    ensure_state_committee = pytest.importorskip("unittest.mock").MagicMock(return_value="committee-id")
    monkeypatch.setattr(in_relational_load_module, "ensure_state_committee", ensure_state_committee)

    committee_id = in_relational_load_module._resolve_in_filing_committee_id(conn, row, "contributions")

    assert committee_id == "committee-id"
    assert ensure_state_committee.call_args.kwargs["native_committee_id"] == expected_committee_id


def test_load_in_file_dispatches_parser_from_data_type_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    csv_path = tmp_path / "contributions.csv"
    header = list(_load_columns_for_data_type("contributions"))

    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        writer.writerow(["row" for _ in header])

    parser_rows = [{"from_spec_parser": "1"}]
    parser_mock = pytest.importorskip("unittest.mock").MagicMock(return_value=iter(parser_rows))
    original_spec = in_load_helpers._IN_DATA_TYPE_SPECS["contributions"]
    monkeypatch.setitem(
        in_load_helpers._IN_DATA_TYPE_SPECS,
        "contributions",
        replace(original_spec, parse_rows=parser_mock),
    )

    expected_result = LoadResult(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.01)
    captured_rows: list[dict[str, str | None]] = []

    def _capture_rows(_conn: psycopg.Connection, rows: object, **_kwargs: object) -> LoadResult:
        captured_rows.extend(list(rows))
        return expected_result

    monkeypatch.setattr(in_load_module, "_load_in_rows", _capture_rows)

    result = in_load_module._load_in_file(
        pytest.importorskip("unittest.mock").MagicMock(),
        csv_path,
        data_source_id=uuid4(),
        data_type="contributions",
    )

    parser_mock.assert_called_once_with(csv_path)
    assert captured_rows == parser_rows
    assert result == expected_result


def test_raw_and_relational_loaders_share_data_type_contract_from_load_helpers() -> None:
    assert in_load_module._in_data_type_spec is in_load_helpers._in_data_type_spec
    assert in_relational_load_module._in_data_type_spec is in_load_helpers._in_data_type_spec
    assert in_load_module._in_extract_row is in_load_helpers._in_extract_row
    assert in_relational_load_module._in_extract_row is in_load_helpers._in_extract_row
    assert in_load_module._resolve_in_committee_organization_id is in_load_helpers._resolve_in_committee_organization_id
    assert (
        in_relational_load_module._resolve_in_committee_organization_id
        is in_load_helpers._resolve_in_committee_organization_id
    )


def test_counterparty_name_raw_uses_data_type_spec_entity_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    original_spec = in_load_helpers._IN_DATA_TYPE_SPECS["contributions"]
    monkeypatch.setitem(
        in_load_helpers._IN_DATA_TYPE_SPECS,
        "contributions",
        replace(original_spec, person_key="custom_person", organization_key="custom_org"),
    )
    monkeypatch.setattr(
        in_relational_load_module,
        "_in_extract_row",
        lambda _row, _data_type: {
            "custom_person": None,
            "custom_org": SimpleNamespace(canonical_name="Custom Organization"),
        },
    )

    assert in_relational_load_module._counterparty_name_raw({}, "contributions") == "Custom Organization"


def test_load_in_rows_records_invalid_amendment_as_row_error(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_row = _parsed_contributions()[0]
    invalid_row = dict(valid_row)
    invalid_row[_column("contributions", "transaction.amended")] = "INVALID"
    rows = [invalid_row, valid_row]

    conn = pytest.importorskip("unittest.mock").MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    load_row_mock = pytest.importorskip("unittest.mock").MagicMock(return_value=True)
    monkeypatch.setattr(in_load_module, "_try_load_in_row", load_row_mock)
    monkeypatch.setattr(in_load_module, "commit_managed_transaction", lambda *_args, **_kwargs: None)

    result = in_load_module._load_in_rows(
        conn,
        rows,
        data_source_id=uuid4(),
        data_type="contributions",
        limit=None,
    )

    assert result.inserted == 1
    assert result.errors == 1
    assert result.skipped == 0
    assert load_row_mock.call_count == 1


# --- DB-backed tests ---


@pytest.fixture(autouse=True)
def _isolate_in_loader_state(request: pytest.FixtureRequest) -> None:
    if "db_conn" not in request.fixturenames:
        return
    db_conn = request.getfixturevalue("db_conn")
    clear_state_loader_records(db_conn, jurisdiction=_IN_JURISDICTION, state_code=_IN_STATE_CODE)


@pytest.mark.integration
def test_ingest_in_contribution_deduplicates_row_key(db_conn: psycopg.Connection) -> None:
    row = _parsed_contributions()[0]
    data_source_id = ensure_in_data_source(db_conn, data_type="contributions")

    first_insert = load_in_contribution(db_conn, row, data_source_id)
    second_insert = load_in_contribution(db_conn, row, data_source_id)

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
            (data_source_id, _in_source_record_key(row, data_type="contributions")),
        )
        result = cursor.fetchone()

    assert result is not None
    assert result["count"] == 1


@pytest.mark.integration
def test_ingest_in_contributions_is_idempotent_and_sets_relational_keys(
    db_conn: psycopg.Connection,
) -> None:
    first_result = load_in_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    assert isinstance(first_result, LoadResult)
    assert first_result.inserted == 8
    assert first_result.errors == 0

    expected_row = _parsed_contributions()[0]
    expected_filing = _in_filing_fec_id(expected_row, data_type="contributions")
    expected_identifier = _in_source_record_key(expected_row, data_type="contributions")

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
            (expected_filing, expected_identifier),
        )
        row = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE filing_fec_id LIKE 'IN-%-contributions'
            """,
        )
        first_filing_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'IN-%-contributions'
            """,
        )
        first_transaction_count = cursor.fetchone()["count"]

    contribution_data_source_id = ensure_in_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (contribution_data_source_id, expected_identifier),
        )
        source_record_snapshot = cursor.fetchone()

    assert row is not None
    assert source_record_snapshot is not None
    assert row["filing_fec_id"] == expected_filing
    # receipt_date reflects the last-processed row for this filing: upsert_filing uses
    # COALESCE(EXCLUDED.receipt_date, existing) so each non-null date overwrites the prior.
    # Row index 3 (2025-07-21) is the final row for filing IN-17-2025-contributions.
    assert row["receipt_date"] == date(2025, 7, 21)
    assert row["transaction_identifier"] == expected_identifier
    assert row["amendment_indicator"] == "N"

    second_result = load_in_contributions_with_filings(db_conn, _SAMPLE_CONTRIBUTIONS_PATH)

    assert isinstance(second_result, LoadResult)
    assert second_result.inserted == 0
    assert second_result.skipped == 8

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
            (expected_filing, expected_identifier),
        )
        rerun_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE filing_fec_id LIKE 'IN-%-contributions'
            """,
        )
        second_filing_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE 'IN-%-contributions'
            """,
        )
        second_transaction_count = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (contribution_data_source_id, expected_identifier),
        )
        rerun_source_record_snapshot = cursor.fetchone()

    assert rerun_row == row
    assert second_filing_count == first_filing_count
    assert second_transaction_count == first_transaction_count
    assert rerun_source_record_snapshot == source_record_snapshot


@pytest.mark.integration
def test_ingest_in_expenditures_maps_amended_rows_to_indicator_a(db_conn: psycopg.Connection) -> None:
    result = load_in_expenditures_with_filings(db_conn, _SAMPLE_EXPENDITURES_PATH)

    assert result.inserted == 9
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT t.amendment_indicator
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id LIKE %s
            """,
            ("IN-%-expenditures",),
        )
        amendments = {row["amendment_indicator"] for row in cursor.fetchall()}

    assert amendments == {"A", "N"}


@pytest.mark.integration
def test_ingest_in_rolls_back_managed_transaction_when_relational_phase_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pytest.importorskip("unittest.mock").MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    load_result = LoadResult(
        inserted=2,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )

    # The raw phase is stubbed and performs no writes here. Every commit the entry point owns
    # routes through commit_managed_transaction, so patching it keeps
    # conn.commit.assert_not_called() meaningful while this test isolates exception cleanup.
    commit_managed_transaction = pytest.importorskip("unittest.mock").MagicMock()
    monkeypatch.setattr(in_load_module, "commit_managed_transaction", commit_managed_transaction)
    monkeypatch.setattr(in_load_module, "ensure_in_data_source", lambda *_args, **_kwargs: "in-source-id")
    monkeypatch.setattr(in_load_module, "_load_in_file", lambda *_args, **_kwargs: load_result)
    original_spec = in_load_helpers._IN_DATA_TYPE_SPECS["contributions"]
    monkeypatch.setitem(
        in_load_helpers._IN_DATA_TYPE_SPECS,
        "contributions",
        replace(original_spec, parse_rows=lambda _path: iter(())),
    )
    monkeypatch.setattr(
        in_load_module,
        "_load_in_relational_transactions",
        pytest.importorskip("unittest.mock").MagicMock(side_effect=RuntimeError("relational failed")),
    )

    with pytest.raises(RuntimeError, match="relational failed"):
        in_load_module._load_in_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions")

    # Once, not twice: the relational stub raises before the terminal commit is reached.
    commit_managed_transaction.assert_called_once_with(conn, True)
    conn.rollback.assert_called_once_with()
    conn.commit.assert_not_called()


def test_load_in_relational_transactions_delegates_rows_to_no_savepoint_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    rows = [{"row": "0"}, {"row": "1"}, {"row": "2"}]
    linked_source_record_ids = [uuid4(), None, uuid4()]
    select_source_record_id = MagicMock(side_effect=linked_source_record_ids)
    helper_calls: list[tuple[object, object, bool, str]] = []
    helper_results = iter(((True, False), (None, False)))

    def record_without_invoking_callback(
        helper_conn: object,
        callback: object,
        *,
        manages_outer_transaction: bool,
        label: str,
    ) -> tuple[bool | None, bool]:
        helper_calls.append((helper_conn, callback, manages_outer_transaction, label))
        return next(helper_results)

    monkeypatch.setattr(in_relational_load_module, "_select_in_source_record_id", select_source_record_id)
    monkeypatch.setattr(in_relational_load_module, "try_row_without_savepoint", record_without_invoking_callback)

    errors = in_relational_load_module._load_in_relational_transactions(
        conn,
        rows,
        data_source_id=uuid4(),
        data_type="contributions",
        limit=None,
    )

    assert len(helper_calls) == 2
    assert [call[0] for call in helper_calls] == [conn, conn]
    assert all(call[2] is True for call in helper_calls)
    assert [call[3] for call in helper_calls] == ["IN contribution filing link"] * 2
    assert errors == 1
    conn.transaction.assert_not_called()
    assert select_source_record_id.call_count == 3


def _relational_transactions_over_two_rows(conn: MagicMock) -> int:
    return in_relational_load_module._load_in_relational_transactions(
        conn,
        [{"row": "0"}, {"row": "1"}],
        data_source_id=uuid4(),
        data_type="contributions",
        limit=None,
    )


@pytest.fixture
def prepared_transaction(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    transaction = MagicMock()
    monkeypatch.setattr(in_relational_load_module, "_build_in_transaction", MagicMock(return_value=transaction))
    return transaction


def test_load_in_relational_transactions_reraises_filing_lookup_drift(
    monkeypatch: pytest.MonkeyPatch,
    prepared_transaction: MagicMock,
) -> None:
    """A filing cache that disagrees with the database aborts the load, it is not a row error.

    `try_row_without_savepoint` catches every `Exception`, so without an explicit re-raise the
    drift guard would be downgraded to one counted row error and the load would keep writing
    against a cache already known to be wrong.
    """
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    drift = in_relational_load_module.INFilingLookupDrift("IN filing lookup drift for filing_fec_id='f': a != b")
    upsert_filing = MagicMock(side_effect=drift)

    monkeypatch.setattr(in_relational_load_module, "_select_in_source_record_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(in_relational_load_module, "_upsert_in_filing", upsert_filing)

    with pytest.raises(in_relational_load_module.INFilingLookupDrift) as raised:
        _relational_transactions_over_two_rows(conn)

    assert raised.value is drift
    # Aborted on the first row rather than continuing through the rest of the file.
    assert upsert_filing.call_count == 1


def test_load_in_relational_transactions_counts_ordinary_row_errors_without_aborting(
    monkeypatch: pytest.MonkeyPatch,
    prepared_transaction: MagicMock,
) -> None:
    """A plain `ValueError` stays a counted row error — only the drift subclass aborts."""
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    upsert_filing = MagicMock(side_effect=ValueError("unparseable row"))

    monkeypatch.setattr(in_relational_load_module, "_select_in_source_record_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(in_relational_load_module, "_upsert_in_filing", upsert_filing)

    assert _relational_transactions_over_two_rows(conn) == 2
    assert upsert_filing.call_count == 2


@pytest.mark.integration
def test_ingest_in_reports_quarantined_rows_from_parser_skip_count(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    # Build a fixture with one well-formed row plus one malformed row missing the last column.
    source_path = _SAMPLE_CONTRIBUTIONS_PATH
    malformed_path = tmp_path / "malformed_contributions.csv"

    with source_path.open("r", encoding="utf-8", newline="") as source_file:
        rows = list(csv.reader(source_file))

    header = rows[0]
    good_row = rows[1]
    malformed_row = good_row[:-1]

    with malformed_path.open("w", encoding="utf-8", newline="") as malformed_file:
        writer = csv.writer(malformed_file)
        writer.writerow(header)
        writer.writerow(good_row)
        writer.writerow(malformed_row)

    result = load_in_contributions_with_filings(db_conn, malformed_path)

    assert result.inserted == 1
    assert result.skipped == 0
    assert result.errors == 0
    assert result.quarantined == 1


# --- IE classification tests (load_helpers) ---


def test_in_is_independent_expenditure_true_for_ie_code() -> None:
    row = {"ExpenditureCode": "Independent Expenditure"}
    assert in_load_helpers._in_is_independent_expenditure(row, data_type="expenditures") is True


def test_in_is_independent_expenditure_case_insensitive() -> None:
    row = {"ExpenditureCode": "INDEPENDENT EXPENDITURE"}
    assert in_load_helpers._in_is_independent_expenditure(row, data_type="expenditures") is True


def test_in_is_independent_expenditure_false_for_non_ie_code() -> None:
    row = {"ExpenditureCode": "Advertising"}
    assert in_load_helpers._in_is_independent_expenditure(row, data_type="expenditures") is False


@pytest.mark.parametrize("raw_value", ["", None])
def test_in_is_independent_expenditure_false_for_blank_or_null(raw_value: str | None) -> None:
    row = {"ExpenditureCode": raw_value}
    assert in_load_helpers._in_is_independent_expenditure(row, data_type="expenditures") is False


def test_in_is_independent_expenditure_false_for_non_expenditure_data_type() -> None:
    row = {"ExpenditureCode": "Independent Expenditure"}
    assert in_load_helpers._in_is_independent_expenditure(row, data_type="contributions") is False


def test_in_transaction_type_returns_ie_when_expenditure_code_is_ie() -> None:
    row = {"ExpenditureCode": "Independent Expenditure", "ExpenditureType": "Direct"}
    assert in_load_helpers._in_transaction_type(row, data_type="expenditures") == "Independent Expenditure"


def test_in_transaction_type_returns_normal_type_for_non_ie() -> None:
    row = {"ExpenditureCode": "Advertising", "ExpenditureType": "Direct"}
    assert in_load_helpers._in_transaction_type(row, data_type="expenditures") == "direct"


# ---------------------------------------------------------------------------
# Stage 3: the entry point owns its outer transaction and commits each batch
# ---------------------------------------------------------------------------
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from a live
# loader constant: the boundary these specimens prove is exactly 1,000 rows, and an
# expectation derived from the loader could never go red against a broken loader.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_IN_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# The caller-owned invariant does not depend on crossing the batch boundary, so it uses a
# small fixture to keep the full phase 1 + phase 2 load off the suite's critical path.
_IN_CALLER_ARM_ROW_COUNT = 5
# One full batch plus two rows, so a failure on the last row has exactly one uncommitted
# sibling behind it and 1,000 committed rows that must NOT be charged as losses.
_IN_POST_BOUNDARY_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 2


def _install_relational_write_db_error(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_on_write: int,
) -> dict[str, int]:
    real_upsert_transaction = in_relational_load_module._upsert_in_transaction_with_filing
    write_counts = {"writes": 0}

    def fail_nth_relational_write(*args: object, **kwargs: object) -> None:
        write_counts["writes"] += 1
        if write_counts["writes"] == fail_on_write:
            # Enter PostgreSQL's real INERROR state; a constructed psycopg exception
            # would leave the connection healthy and would not prove rollback recovery.
            db_conn.execute("SELECT 1 / 0")
        real_upsert_transaction(*args, **kwargs)

    monkeypatch.setattr(
        in_relational_load_module,
        "_upsert_in_transaction_with_filing",
        fail_nth_relational_write,
    )
    return write_counts


def test_write_in_contribution_fixture_produces_unique_keys_and_one_committee(tmp_path: Path) -> None:
    """The bulk writer gives every row a distinct source-record key but one shared committee."""
    fixture = write_in_contribution_fixture(tmp_path, row_count=_IN_BULK_ROW_COUNT)

    assert len(fixture.source_record_keys) == _IN_BULK_ROW_COUNT
    assert len(set(fixture.source_record_keys)) == _IN_BULK_ROW_COUNT

    with fixture.input_path.open(encoding="utf-8", newline="") as csv_file:
        written_rows = list(csv.DictReader(csv_file))
    assert len(written_rows) == _IN_BULK_ROW_COUNT
    assert {row["Committee"] for row in written_rows} == {f"IN Bounded Commit Test Committee {fixture.run_suffix}"}
    assert len({row["CommitteeType"] for row in written_rows}) == 1
    assert len({row["FileNumber"] for row in written_rows}) == 1
    assert len({_parse_in_date(row["ContributionDate"]).year for row in written_rows}) == 1
    # Pinned to the non-amended value so no row can take `_load_in_rows`' amendment-error
    # branch, which owns its own 1,000-row commit boundary.
    assert {row["Amended"] for row in written_rows} == {"0"}

    parsed_first_row = next(iter(parse_contributions(fixture.input_path)))
    assert fixture.committee_native_id == _in_native_committee_id(parsed_first_row, data_type="contributions")


@pytest.mark.integration
def test_load_in_contributions_with_filings_commits_source_record_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 source records leaves exactly those 1,000 durable.

    With the pre-Stage-3 ordering `_load_in_with_filings` resolved the data source before
    sampling the transaction status, so it read INTRANS, decided it did not manage the outer
    transaction, and turned every `commit_managed_transaction` — including phase 1's
    1,000-row boundary — into a no-op. This interruption then discarded all 1,000 rows and
    an independent connection saw zero.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=_IN_BULK_ROW_COUNT),
            row_count=_IN_BULK_ROW_COUNT,
        )
        write_counts = install_write_interrupt(
            monkeypatch,
            in_load_module,
            "try_insert_source_record",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_in_contributions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        # Phase 1 flushed its first full batch at row 1,000 and was interrupted on row 1,001,
        # so exactly that batch of source records is durable. Phase 2 never started, so no
        # cf.transaction rows exist.
        assert write_counts["writes"] == _IN_BULK_ROW_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _EXPECTED_DURABLE_BATCH_ROWS
        assert transaction_count == 0


@pytest.mark.integration
def test_load_in_contributions_with_filings_commits_relational_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 relational rows leaves exactly those 1,000 durable.

    Before the relational boundary fix, an interruption on transaction 1,001 discarded
    every linked row because the pass committed only at the end of the job.
    `BulkFixtureInterruption` subclasses `BaseException` on purpose: that is what carries it
    past `try_row_without_savepoint`'s `except psycopg.Error` / `except Exception` handlers and
    past `_load_in_with_filings`' `except Exception`, so the interrupt propagates as a genuine
    interruption instead of being swallowed as a row error, and this test's own
    `db_conn.rollback()` discards the uncommitted remainder of the partial batch.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=_IN_BULK_ROW_COUNT),
            row_count=_IN_BULK_ROW_COUNT,
        )
        # `_load_in_relational_transactions` resolves `_upsert_in_transaction_with_filing` as a
        # module global at call time, so patching the module attribute takes
        # effect.
        write_counts = install_write_interrupt(
            monkeypatch,
            in_relational_load_module,
            "_upsert_in_transaction_with_filing",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_in_contributions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        # Phase 1 ran to completion so all 1,001 source records are durable; the relational
        # pass was interrupted on transaction 1,001, so exactly its first full batch survives.
        assert write_counts["writes"] == _IN_BULK_ROW_COUNT
        assert bulk_fixture_row_counts(fixture) == (_IN_BULK_ROW_COUNT, _EXPECTED_DURABLE_BATCH_ROWS)


@pytest.mark.integration
def test_load_in_contributions_with_filings_recovers_from_relational_db_error(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=3),
            row_count=3,
        )
        write_counts = _install_relational_write_db_error(db_conn, monkeypatch, fail_on_write=2)

        result = load_in_contributions_with_filings(db_conn, fixture.input_path)

        assert write_counts["writes"] == 3
        assert result.errors == 2
        assert result.inserted == 3
        assert bulk_fixture_row_counts(fixture) == (3, 1)

        db_conn.rollback()
        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT filing.id
                FROM cf.filing AS filing
                JOIN cf.committee AS committee ON committee.id = filing.committee_id
                WHERE committee.fec_committee_id = %s
                """,
                (fixture.committee_fec_id,),
            )
            fixture_filing_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT transaction.filing_id
                FROM cf.transaction AS transaction
                JOIN core.source_record AS source_record
                  ON source_record.id = transaction.source_record_id
                WHERE source_record.source_record_key = ANY(%s)
                """,
                (fixture.source_record_keys,),
            )
            surviving_transaction_rows = cursor.fetchall()

        assert len(fixture_filing_rows) == 1
        assert surviving_transaction_rows == [fixture_filing_rows[0]]


@pytest.mark.integration
def test_load_in_contributions_with_filings_rejects_invalid_amount_before_writing_filing(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=1, amount="not-a-number"),
            row_count=1,
        )

        result = load_in_contributions_with_filings(db_conn, fixture.input_path)

        assert result.inserted == 1
        assert result.errors == 1
        assert bulk_fixture_row_counts(fixture) == (1, 0)

        db_conn.rollback()
        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM cf.filing AS filing
                JOIN cf.committee AS committee ON committee.id = filing.committee_id
                WHERE committee.fec_committee_id = %s
                """,
                (fixture.committee_fec_id,),
            )
            assert cursor.fetchone()[0] == 0


@pytest.mark.integration
def test_load_in_contributions_with_filings_charges_only_the_open_batch_after_a_boundary(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DB error past the 1,000-row commit loses only the rows linked since that commit.

    The batch rollback erases the open batch, never the committed batches behind it. Without
    the `linked_rows_since_commit` reset at the boundary the loader would charge every row
    linked since the start of the file — 1,002 here instead of 2 — to `LoadResult.errors`,
    reporting durable rows as lost.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=_IN_POST_BOUNDARY_ROW_COUNT),
            row_count=_IN_POST_BOUNDARY_ROW_COUNT,
        )
        write_counts = _install_relational_write_db_error(
            db_conn,
            monkeypatch,
            fail_on_write=_IN_POST_BOUNDARY_ROW_COUNT,
        )

        result = load_in_contributions_with_filings(db_conn, fixture.input_path)

        assert write_counts["writes"] == _IN_POST_BOUNDARY_ROW_COUNT
        # Row 1,002 failed and took row 1,001 down with it; rows 1..1,000 were committed at
        # the boundary and survive, so exactly two rows are lost.
        assert result.errors == 2
        assert result.inserted == _IN_POST_BOUNDARY_ROW_COUNT
        assert bulk_fixture_row_counts(fixture) == (_IN_POST_BOUNDARY_ROW_COUNT, _EXPECTED_DURABLE_BATCH_ROWS)


@pytest.mark.integration
def test_load_in_contributions_with_filings_caller_owned_relational_db_error_is_loud(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=3),
            row_count=3,
        )
        write_counts = _install_relational_write_db_error(db_conn, monkeypatch, fail_on_write=2)

        db_conn.execute("BEGIN")
        with pytest.raises(in_load_module.INCallerTransactionRolledBack):
            load_in_contributions_with_filings(db_conn, fixture.input_path)

        assert write_counts["writes"] == 2
        assert bulk_fixture_row_counts(fixture) == (0, 0)


@pytest.mark.integration
def test_load_in_contributions_with_filings_writes_into_caller_transaction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """A caller-supplied INTRANS connection owns the commit: the loader writes but never commits.

    Holds both before and after the Stage 3 ordering fix — when the caller hands over an open
    transaction the entry point must observe it does not manage it — so it is a standing
    invariant, not part of the red evidence.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_in_contribution_fixture(tmp_path, row_count=_IN_CALLER_ARM_ROW_COUNT),
            row_count=_IN_CALLER_ARM_ROW_COUNT,
        )
        db_conn.execute("BEGIN")
        assert_loader_arm_is_caller_owned(
            fixture,
            db_conn,
            expected_source_records=_IN_CALLER_ARM_ROW_COUNT,
            run_loader=lambda: load_in_contributions_with_filings(db_conn, fixture.input_path),
        )


@pytest.mark.integration
def test_cli_load_path_hands_the_loader_an_idle_connection(db_conn: psycopg.Connection) -> None:
    """`cli._load_path` must hand the loader an IDLE connection.

    A data-source lookup left open would make the loader read INTRANS and silently drop its
    1,000-row commit boundary — the exact defect Stage 3 fixes inside the entry point.
    """
    from domains.campaign_finance.jurisdictions.states.IN.scraper import cli

    observed_transaction_status: list[object] = []

    def _recording_loader(conn: psycopg.Connection, input_path: Path, *, limit: int | None) -> LoadResult:
        observed_transaction_status.append(conn.info.transaction_status)
        return LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "load_in_contributions_with_filings", _recording_loader)
        connection = get_connection()
        try:
            cli._load_path(connection, Path("unused.csv"), data_type="contributions", limit=3)
        finally:
            connection.rollback()
            connection.close()

    assert observed_transaction_status == [psycopg.pq.TransactionStatus.IDLE]
