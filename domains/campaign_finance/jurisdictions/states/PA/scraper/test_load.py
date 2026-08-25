from __future__ import annotations

import threading
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

from core.db import get_connection
from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.PA.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.PA.scraper import load as pa_load_module
from domains.campaign_finance.jurisdictions.states.PA.scraper.load import (
    LoadResult,
    _build_filer_amendment_lookup,
    _pa_filing_fec_id,
    _pa_source_record_key,
    _parse_pa_compact_date,
    _parse_pa_submitted_date,
    _resolve_pa_amendment_indicator,
    load_pa_contributions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper.parse import parse_contributions, parse_filings
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    bulk_fixture_contributor_person_ids,
    bulk_fixture_row_counts,
    cleanup_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper import pa_load_test_support as pa_support

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv", year=2025))


def _filer_rows() -> list[dict[str, str | None]]:
    return list(parse_filings(_FIXTURE_DIR / "sample_filings.csv", year=2025))


def test_sample_contributions_resolve_to_hand_checked_filer_identity() -> None:
    filer_lookup = pa_load_module._build_filer_row_lookup(_filer_rows())
    resolved_pairs = set()

    for contribution_row in _contribution_rows():
        filer_row = pa_load_module._require_pa_filer_row(
            contribution_row,
            data_type="contributions",
            filer_row_lookup=filer_lookup,
        )
        assert filer_row["CampaignfinanceID"] == "433213"
        assert filer_row["FILERID"] == "2004206"
        assert filer_row["FILERNAME"] == "Amgen Inc. Political Action Committee"
        resolved_pairs.add((contribution_row["CampaignFinanceID"], filer_row["FILERID"]))

    assert resolved_pairs == {("433213", "2004206")}


def test_load_pa_rows_commits_every_thousand_rows_and_leaves_connection_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()
    monkeypatch.setattr(pa_load_module, "_load_pa_row", lambda *_args, **_kwargs: True)

    rows = [{"CampaignFinanceID": str(index)} for index in range(pa_load_module._COMMIT_BATCH_ROWS * 2 + 500)]
    counts = pa_load_module._load_pa_rows(
        conn,
        rows,
        data_source_id=uuid4(),
        data_type="contributions",
        limit=None,
    )

    assert counts.inserted == len(rows)
    # Two commits at the batch boundaries plus the final commit.
    assert conn.commit_count == 3
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_load_pa_relational_transactions_commits_every_thousand_rows_and_leaves_connection_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()
    monkeypatch.setattr(pa_load_module, "_resolve_pa_amendment_indicator", lambda *_a, **_k: "N")
    monkeypatch.setattr(pa_load_module, "_pa_source_record_key", lambda *_a, **_k: "key")
    monkeypatch.setattr(pa_load_module, "_select_pa_source_record_id", lambda *_a, **_k: uuid4())
    monkeypatch.setattr(pa_load_module, "_upsert_pa_filing", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(pa_load_module, "_upsert_pa_transaction_with_filing", lambda *_a, **_k: None)

    filer_context = pa_load_module._PAFilerContext(amendment_lookup={}, row_lookup={})
    rows = [{"CampaignFinanceID": str(index)} for index in range(pa_load_module._COMMIT_BATCH_ROWS * 2 + 500)]

    superseded = pa_load_module._load_pa_relational_transactions(
        conn,
        rows,
        data_source_id=uuid4(),
        data_type="contributions",
        filer_context=filer_context,
        limit=None,
    )

    assert superseded == 0
    assert conn.commit_count == 3
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_load_pa_relational_transactions_bounds_rows_without_source_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()
    monkeypatch.setattr(pa_load_module, "_resolve_pa_amendment_indicator", lambda *_a, **_k: "N")
    monkeypatch.setattr(pa_load_module, "_pa_source_record_key", lambda *_a, **_k: "key")

    def _missing_source_record(connection: object, **_kwargs: object) -> None:
        # The real `_select_pa_source_record_id` runs a SELECT through
        # `conn.cursor().execute`, which opens a transaction on the non-autocommit
        # connection even when the row is missing. A pure lambda would leave the
        # double IDLE and could not catch an unbounded skip path.
        connection.execute("SELECT source record")
        return None

    monkeypatch.setattr(pa_load_module, "_select_pa_source_record_id", _missing_source_record)

    filer_context = pa_load_module._PAFilerContext(amendment_lookup={}, row_lookup={})
    rows = [{"CampaignFinanceID": str(index)} for index in range(pa_load_module._COMMIT_BATCH_ROWS * 2 + 500)]

    pa_load_module._load_pa_relational_transactions(
        conn,
        rows,
        data_source_id=uuid4(),
        data_type="contributions",
        filer_context=filer_context,
        limit=None,
    )

    # Every iterated row advances the commit boundary, so the read transaction the
    # lookup opens is bounded: two commits at the batch boundaries plus the final one.
    assert conn.commit_count == 3
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_load_pa_with_filings_commits_data_source_before_loading_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = pa_support.FakeTransactionConnection()

    def _ensure_data_source(connection: object, **_kwargs: object) -> str:
        connection.execute("SELECT ensure data source")
        return "pa-source-id"

    def _load_file(connection: object, *_args: object, **_kwargs: object) -> LoadResult:
        connection.calls.append("load_pa_file")
        return LoadResult(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.1)

    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", _ensure_data_source)
    monkeypatch.setattr(pa_load_module, "_load_pa_file", _load_file)
    monkeypatch.setattr(pa_load_module, "parse_filings", lambda _path, _year: iter(()))
    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda _path, _year: iter(()))
    monkeypatch.setattr(pa_load_module, "_load_pa_relational_transactions", lambda *_a, **_k: 0)

    pa_load_module._load_pa_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025)

    assert "commit" in conn.calls
    assert "load_pa_file" in conn.calls
    assert conn.calls.index("commit") < conn.calls.index("load_pa_file")


def test_source_record_key_uses_campaign_finance_id_data_type_and_row_hash() -> None:
    row = _contribution_rows()[0]

    expected_hash = compute_record_hash(dict(row))
    expected_key = f"PA-{row['CampaignFinanceID']}-contributions-{expected_hash}"

    assert _pa_source_record_key(row, data_type="contributions") == expected_key


def test_filing_fec_id_uses_filer_id_and_submitted_year() -> None:
    row = _contribution_rows()[0]

    assert _pa_filing_fec_id(row, data_type="contributions") == "PA-2004206-2026-contributions"


def test_date_parsers_handle_pa_formats() -> None:
    assert _parse_pa_compact_date("20250703") == date(2025, 7, 3)
    assert _parse_pa_submitted_date("2026-01-28") == date(2026, 1, 28)


def test_amendment_indicator_resolution_uses_filer_lookup_and_allows_unresolved() -> None:
    campaignfinance_id_column = _load_column_for_semantic_path("filings", "pa.campaignfinance_id")
    amend_column = _load_column_for_semantic_path("filings", "pa.amend_flag")
    terminate_column = _load_column_for_semantic_path("filings", "pa.terminate_flag")

    filer_rows = [
        {campaignfinance_id_column: "1001", amend_column: "Y", terminate_column: "N"},
        {campaignfinance_id_column: "1002", amend_column: "N", terminate_column: "Y"},
        {campaignfinance_id_column: "1003", amend_column: "N", terminate_column: "N"},
    ]
    lookup = _build_filer_amendment_lookup(filer_rows)

    detail_column = _load_column_for_semantic_path("contributions", "pa.campaign_finance_id")
    assert (
        _resolve_pa_amendment_indicator({detail_column: "1001"}, data_type="contributions", filer_lookup=lookup) == "A"
    )
    assert (
        _resolve_pa_amendment_indicator({detail_column: "1002"}, data_type="contributions", filer_lookup=lookup) == "T"
    )
    assert (
        _resolve_pa_amendment_indicator({detail_column: "1003"}, data_type="contributions", filer_lookup=lookup) == "N"
    )
    assert (
        _resolve_pa_amendment_indicator({detail_column: "9999"}, data_type="contributions", filer_lookup=lookup) is None
    )


def test_try_load_pa_row_returns_none_when_row_loader_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    conn.transaction.return_value.__enter__.return_value = None
    conn.transaction.return_value.__exit__.return_value = False
    row = _contribution_rows()[0]
    data_source_id = uuid4()

    ensure_transaction_open = MagicMock()
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_transaction_open",
        ensure_transaction_open,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._load_pa_row",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    assert (
        pa_load_module._try_load_pa_row(
            conn,
            row,
            data_source_id=data_source_id,
            data_type="contributions",
            manages_outer_transaction=True,
        )
        is None
    )
    ensure_transaction_open.assert_called_once_with(conn)


def test_load_pa_contributions_with_filings_uses_loader_helpers(monkeypatch) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    conn.transaction.return_value.__enter__.return_value = None
    conn.transaction.return_value.__exit__.return_value = False

    detail_row = dict(_contribution_rows()[0])
    filer_row = dict(_filer_rows()[1])
    detail_row["CampaignFinanceID"] = filer_row["CampaignfinanceID"]

    data_source_id = uuid4()
    source_record_id = uuid4()
    committee_id = uuid4()
    filing_id = uuid4()

    try_insert_source_record = MagicMock(return_value=source_record_id)
    ensure_state_committee = MagicMock(return_value=committee_id)
    upsert_filing = MagicMock(return_value=filing_id)
    upsert_transaction = MagicMock(return_value=uuid4())

    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda _path, year: iter([detail_row]))
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.parse_filings",
        lambda _path, year: iter([filer_row]),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_pa_data_source",
        lambda *_args, **_kwargs: data_source_id,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.try_insert_source_record",
        try_insert_source_record,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_state_committee", ensure_state_committee
    )
    monkeypatch.setattr("domains.campaign_finance.jurisdictions.states.PA.scraper.load.upsert_filing", upsert_filing)
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.upsert_transaction", upsert_transaction
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.resolve_transaction_counterparty_ids",
        MagicMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._resolve_pa_transaction_address_id",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._select_pa_source_record_id",
        lambda *_args, **_kwargs: source_record_id,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._resolve_pa_committee_organization_id",
        lambda *_args, **_kwargs: uuid4(),
    )

    result = load_pa_contributions_with_filings(conn, Path("/tmp/pa-2025.zip"), year=2025)

    assert result.inserted == 1
    assert try_insert_source_record.call_count == 1
    assert ensure_state_committee.call_count == 1
    assert upsert_filing.call_count == 1
    assert upsert_transaction.call_count == 1


def test_load_pa_contributions_with_filings_uses_filer_row_for_committee_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    conn.transaction.return_value.__enter__.return_value = None
    conn.transaction.return_value.__exit__.return_value = False

    detail_row = dict(_contribution_rows()[0])
    filer_row = dict(_filer_rows()[1])
    detail_row["CampaignFinanceID"] = filer_row["CampaignfinanceID"]

    data_source_id = uuid4()
    source_record_id = uuid4()
    filing_id = uuid4()
    committee_id = uuid4()
    upsert_filing = MagicMock(return_value=filing_id)

    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda _path, year: iter([detail_row]))
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.parse_filings",
        lambda _path, year: iter([filer_row]),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_pa_data_source",
        lambda *_args, **_kwargs: data_source_id,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.try_insert_source_record",
        MagicMock(return_value=source_record_id),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._select_pa_source_record_id",
        lambda *_args, **_kwargs: source_record_id,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_state_committee",
        MagicMock(return_value=committee_id),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.upsert_filing",
        upsert_filing,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.upsert_transaction",
        MagicMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.resolve_transaction_counterparty_ids",
        MagicMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._resolve_pa_transaction_address_id",
        MagicMock(return_value=None),
    )

    def _resolve_committee(_conn: object, committee: object) -> object:
        assert committee.canonical_name.strip() == filer_row["FILERNAME"].strip()
        return uuid4()

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._resolve_pa_committee_organization_id",
        _resolve_committee,
    )

    result = load_pa_contributions_with_filings(conn, Path("/tmp/pa-2025.zip"), year=2025)

    assert result.inserted == 1
    filing = upsert_filing.call_args.args[1]
    assert filing.filing_fec_id == "PA-2004174-2025-contributions"
    assert filing.receipt_date == date(2025, 5, 6)


def test_load_pa_contributions_with_filings_threads_resolved_counterparty_ids_into_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    conn.transaction.return_value.__enter__.return_value = None
    conn.transaction.return_value.__exit__.return_value = False

    detail_row = dict(_contribution_rows()[0])
    filer_row = dict(_filer_rows()[1])
    detail_row["CampaignFinanceID"] = filer_row["CampaignfinanceID"]

    data_source_id = uuid4()
    source_record_id = uuid4()
    committee_id = uuid4()
    filing_id = uuid4()
    person_id = uuid4()
    address_id = uuid4()

    captured_transaction: dict[str, object] = {}

    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda _path, year: iter([detail_row]))
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.parse_filings",
        lambda _path, year: iter([filer_row]),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_pa_data_source",
        lambda *_args, **_kwargs: data_source_id,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.try_insert_source_record",
        MagicMock(return_value=source_record_id),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._select_pa_source_record_id",
        lambda *_args, **_kwargs: source_record_id,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._resolve_pa_committee_organization_id",
        lambda *_args, **_kwargs: uuid4(),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.ensure_state_committee",
        MagicMock(return_value=committee_id),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.upsert_filing",
        MagicMock(return_value=filing_id),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.resolve_transaction_counterparty_ids",
        MagicMock(return_value=(person_id, None)),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load._resolve_pa_transaction_address_id",
        MagicMock(return_value=address_id),
    )

    def _capture_transaction(_conn: object, transaction: object) -> object:
        captured_transaction["value"] = transaction
        return uuid4()

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.states.PA.scraper.load.upsert_transaction",
        _capture_transaction,
    )

    load_pa_contributions_with_filings(conn, Path("/tmp/pa-2025.zip"), year=2025)

    transaction = captured_transaction["value"]
    assert transaction.contributor_person_id == person_id
    assert transaction.contributor_organization_id is None
    assert transaction.contributor_address_id == address_id
    assert transaction.contributor_city == "Thousand Oaks"
    assert transaction.contributor_state == "CA"
    assert transaction.contributor_zip == "91320"


def test_load_module_stays_at_or_below_warning_threshold() -> None:
    line_count = sum(1 for _ in Path(pa_load_module.__file__).open(encoding="utf-8"))
    assert line_count <= 525


# --- Stage 1: shared bulk/observer seam smoke specimen -------------------------
#
# One DB-backed specimen that exercises the whole Stage 1 seam Stages 2 and 3
# reuse: a bulk contributions fixture crossing load._COMMIT_BATCH_ROWS, exact
# inserted/source-record/transaction counts and the entity-leak guard through the
# pa_support helpers, two independent fixture identities that share one extracted
# address resolving to a single core.address row, and the backend-activity
# observer that later blocking stages poll.

_BULK_ROW_COUNT = pa_load_module._COMMIT_BATCH_ROWS + 1


def test_pa_bulk_and_shared_address_seam_smoke(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    bulk = pa_support.write_pa_fixture_pair(tmp_path, row_count=_BULK_ROW_COUNT)
    ident_a = pa_support.write_pa_fixture_pair(tmp_path, shared_address="4200 Shared Common Ave")
    ident_b = pa_support.write_pa_fixture_pair(tmp_path, shared_address="4200 Shared Common Ave")

    # db_conn yields with BEGIN already executed; the loader must observe IDLE to
    # own its commits, otherwise nothing commits and the test proves nothing.
    db_conn.rollback()
    cleanup_bulk_fixture(bulk)
    cleanup_bulk_fixture(ident_a)
    cleanup_bulk_fixture(ident_b)

    try:
        # Backend-activity observer contract (the seam Stage 2's blocking test
        # polls): a real, live backend PID yields a BackendActivity naming that
        # exact PID, and a terminated backend's PID reads as an honest None rather
        # than a synthesised healthy row.
        live_pid = db_conn.info.backend_pid
        live_activity = pa_support.observe_backend_activity(live_pid)
        assert live_activity is not None
        assert live_activity.pid == live_pid
        assert isinstance(live_activity.blocking_pids, list)

        gone_conn = get_connection()
        gone_pid = gone_conn.info.backend_pid
        gone_conn.close()
        # Closing the client connection does not synchronously tear down the server
        # backend, so an independent observer connection can still see the row for a
        # moment. Poll the shared bounded guard instead of assuming synchronous
        # external state; wait_until raises on timeout, so a backend that never goes
        # away fails the test rather than reading as healthy.
        pa_support.wait_until(
            lambda: pa_support.observe_backend_activity(gone_pid) is None,
            timeout_seconds=5.0,
            poll_interval_seconds=0.05,
            description=f"backend pid {gone_pid} to leave pg_stat_activity",
        )
        assert pa_support.observe_backend_activity(gone_pid) is None

        assert len(bulk.source_record_keys) > pa_load_module._COMMIT_BATCH_ROWS
        assert len(bulk.source_record_keys) == _BULK_ROW_COUNT
        assert len(set(bulk.source_record_keys)) == _BULK_ROW_COUNT

        baseline = pa_support.fixture_entity_row_counts(bulk)

        result = load_pa_contributions_with_filings(db_conn, bulk.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        assert result.inserted == _BULK_ROW_COUNT
        assert result.errors == 0

        # Exact inserted/source-record/transaction counts through the helpers, not
        # ad hoc SQL: one source record and one transaction per bulk row.
        source_record_count, transaction_count = bulk_fixture_row_counts(bulk)
        assert source_record_count == _BULK_ROW_COUNT
        assert transaction_count == _BULK_ROW_COUNT

        # Leak guard: the load created entity rows (distinct donor person per row,
        # one shared committee org, one shared street address, one committee).
        after = pa_support.fixture_entity_row_counts(bulk)
        assert after != baseline
        assert after["person"] == baseline["person"] + _BULK_ROW_COUNT
        assert after["organization"] == baseline["organization"] + 1
        assert after["address"] == baseline["address"] + 1
        assert after["committee"] == baseline["committee"] + 1

        cleanup_bulk_fixture(bulk)
        assert pa_support.fixture_entity_row_counts(bulk) == baseline

        # Two independent identities sharing one address resolve to one core.address
        # row while staying separate committee/provenance fixtures.
        result_a = load_pa_contributions_with_filings(db_conn, ident_a.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert result_a.inserted == 1
        assert result_a.errors == 0
        assert bulk_fixture_row_counts(ident_a) == (1, 1)
        assert bulk_fixture_row_counts(ident_b) == (0, 0)
        assert pa_support.fixture_address_ids(ident_b) == []

        result_b = load_pa_contributions_with_filings(db_conn, ident_b.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert result_b.inserted == 1
        assert result_b.errors == 0
        assert bulk_fixture_row_counts(ident_b) == (1, 1)

        address_ids_a = pa_support.fixture_address_ids(ident_a)
        address_ids_b = pa_support.fixture_address_ids(ident_b)
        assert len(address_ids_a) == 1
        assert address_ids_a == address_ids_b
        # Separate identities: distinct committees and distinct source records.
        assert ident_a.committee_fec_id != ident_b.committee_fec_id
        assert set(ident_a.source_record_keys).isdisjoint(ident_b.source_record_keys)
    finally:
        cleanup_bulk_fixture(bulk)
        cleanup_bulk_fixture(ident_a)
        cleanup_bulk_fixture(ident_b)


def test_pa_bulk_fixture_person_identities_are_run_scoped(db_conn: psycopg.Connection, tmp_path: Path) -> None:
    with ExitStack() as resources:
        shared_address = f"4250 Run Scoped Donor Ave {uuid4().hex[:12]}"
        fixture_a = pa_support.write_pa_fixture_pair(tmp_path, shared_address=shared_address)
        resources.callback(cleanup_bulk_fixture, fixture_a)
        fixture_b = pa_support.write_pa_fixture_pair(tmp_path, shared_address=shared_address)
        resources.callback(cleanup_bulk_fixture, fixture_b)
        db_conn.rollback()
        cleanup_bulk_fixture(fixture_a)
        cleanup_bulk_fixture(fixture_b)

        result_a = load_pa_contributions_with_filings(db_conn, fixture_a.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        result_b = load_pa_contributions_with_filings(db_conn, fixture_b.detail_path, year=pa_support.PA_FIXTURE_YEAR)
        assert (result_a.inserted, result_a.errors) == (1, 0)
        assert (result_b.inserted, result_b.errors) == (1, 0)
        assert bulk_fixture_row_counts(fixture_a) == (1, 1)
        assert bulk_fixture_row_counts(fixture_b) == (1, 1)
        person_zip_keys_a = pa_support.fixture_person_zip_keys(fixture_a)
        person_zip_keys_b = pa_support.fixture_person_zip_keys(fixture_b)
        contributor_person_ids_a = bulk_fixture_contributor_person_ids(fixture_a)
        contributor_person_ids_b = bulk_fixture_contributor_person_ids(fixture_b)
        assert len(contributor_person_ids_a) == len(contributor_person_ids_b) == 1
        assert None not in contributor_person_ids_a + contributor_person_ids_b
        assert contributor_person_ids_a[0] != contributor_person_ids_b[0]
        assert person_zip_keys_a != person_zip_keys_b
        address_ids_a = pa_support.fixture_address_ids(fixture_a)
        address_ids_b = pa_support.fixture_address_ids(fixture_b)
        assert len(address_ids_a) == 1
        assert address_ids_a == address_ids_b


# --- Stage 2: shared-dimension lock-release specimen ---------------------------
#
# One DB-backed acceptance specimen proving the PA loader releases a shared
# core.address lock at its FIRST batch commit (load._COMMIT_BATCH_ROWS rows in),
# before the whole load finishes — not only at job end. Two real loader calls run
# on independent connections in worker threads; Job A holds the uncommitted
# shared-address lock, Job B contends, and every claim is asserted from durable
# committed state (never from wall-clock ordering).

_GATE_TIMEOUT_SECONDS = 60.0
_BULK_TIMEOUT_SECONDS = 90.0


def _stage2_gated_row_loader(
    job_a: pa_support.PAFixture,
    gates: tuple[threading.Event, threading.Event, threading.Event, threading.Event],
):
    gate1_reached, gate1_release, gate2_reached, gate2_release = gates
    real_load_pa_row = pa_load_module._load_pa_row
    a_invocations = 0

    def _gated_load_pa_row(conn, row, data_source_id, *, data_type):
        nonlocal a_invocations
        is_job_a = pa_load_module._pa_campaign_finance_id(row, data_type=data_type) == job_a.campaign_finance_id
        if not is_job_a:
            return real_load_pa_row(conn, row, data_source_id, data_type=data_type)

        a_invocations += 1
        if a_invocations == pa_load_module._COMMIT_BATCH_ROWS + 1:
            gate2_reached.set()
            if not gate2_release.wait(timeout=_GATE_TIMEOUT_SECONDS):
                raise TimeoutError("GATE 2 was never released")
            return real_load_pa_row(conn, row, data_source_id, data_type=data_type)

        result = real_load_pa_row(conn, row, data_source_id, data_type=data_type)
        if a_invocations == 1:
            gate1_reached.set()
            if not gate1_release.wait(timeout=_GATE_TIMEOUT_SECONDS):
                raise TimeoutError("GATE 1 was never released")
        return result

    return _gated_load_pa_row


def test_load_pa_with_filings_releases_shared_dimension_lock_at_batch_commit(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with ExitStack() as resources:
        shared_address = f"5100 Batch Commit Lock Ave {uuid4().hex[:12]}"
        job_a = pa_support.write_pa_fixture_pair(tmp_path, row_count=_BULK_ROW_COUNT, shared_address=shared_address)
        resources.callback(cleanup_bulk_fixture, job_a)
        job_b = pa_support.write_pa_fixture_pair(tmp_path, shared_address=shared_address)
        resources.callback(cleanup_bulk_fixture, job_b)
        db_conn.rollback()
        cleanup_bulk_fixture(job_a)
        cleanup_bulk_fixture(job_b)
        assert bulk_fixture_row_counts(job_a) == (0, 0)
        assert bulk_fixture_row_counts(job_b) == (0, 0)

        gates = tuple(threading.Event() for _ in range(4))
        gate1_reached, gate1_release, gate2_reached, gate2_release = gates
        conn_a = get_connection()
        resources.callback(conn_a.close)
        conn_b = get_connection()
        resources.callback(conn_b.close)
        job_a_pid, job_b_pid = conn_a.info.backend_pid, conn_b.info.backend_pid
        worker_errors: dict[str, BaseException] = {}

        def _run_job(conn: psycopg.Connection, fixture: pa_support.PAFixture, key: str) -> None:
            try:
                load_pa_contributions_with_filings(conn, fixture.detail_path, year=pa_support.PA_FIXTURE_YEAR)
            except BaseException as exc:  # noqa: BLE001 - surfaced to main thread
                worker_errors[key] = exc

        thread_a = threading.Thread(target=_run_job, args=(conn_a, job_a, "a"), name="pa-job-a")
        thread_b = threading.Thread(target=_run_job, args=(conn_b, job_b, "b"), name="pa-job-b")
        monkeypatch.setattr(pa_load_module, "_load_pa_row", _stage2_gated_row_loader(job_a, gates))

        try:
            thread_a.start()
            if not gate1_reached.wait(timeout=_GATE_TIMEOUT_SECONDS):
                if "a" in worker_errors:
                    raise worker_errors["a"]
                raise AssertionError("Job A never reached GATE 1 (first-row hold)")
            thread_b.start()

            def _b_blocked_by_a() -> bool:
                if "b" in worker_errors:
                    raise worker_errors["b"]
                activity = pa_support.observe_backend_activity(job_b_pid)
                return bool(
                    activity
                    and job_a_pid in activity.blocking_pids
                    and activity.wait_event_type == "Lock"
                    and "insert into core.address" in (activity.query or "").lower()
                )

            pa_support.wait_until(
                _b_blocked_by_a,
                timeout_seconds=_GATE_TIMEOUT_SECONDS,
                description="job B blocked by job A on the shared core.address lock",
            )
            gate1_release.set()

            def _a_reached_gate2() -> bool:
                if "a" in worker_errors:
                    raise worker_errors["a"]
                return gate2_reached.is_set()

            pa_support.wait_until(
                _a_reached_gate2,
                timeout_seconds=_BULK_TIMEOUT_SECONDS,
                description="job A to pause after its first batch commit (GATE 2)",
            )

            thread_b.join(timeout=_GATE_TIMEOUT_SECONDS)
            assert not thread_b.is_alive(), "Job B did not unblock after A's batch commit"
            if "b" in worker_errors:
                raise worker_errors["b"]
            assert bulk_fixture_row_counts(job_b) == (1, 1)
            source_records_a, _ = bulk_fixture_row_counts(job_a)
            assert source_records_a == pa_load_module._COMMIT_BATCH_ROWS == _BULK_ROW_COUNT - 1

            gate2_release.set()
            thread_a.join(timeout=_BULK_TIMEOUT_SECONDS)
            assert not thread_a.is_alive(), "Job A did not finish after GATE 2 release"
            if "a" in worker_errors:
                raise worker_errors["a"]
            assert bulk_fixture_row_counts(job_a) == (_BULK_ROW_COUNT, _BULK_ROW_COUNT)
        finally:
            gate1_release.set()
            gate2_release.set()
            for thread, timeout in ((thread_a, _BULK_TIMEOUT_SECONDS), (thread_b, _GATE_TIMEOUT_SECONDS)):
                if thread.ident is not None:
                    thread.join(timeout=timeout)


# --- Stage 3: interruption preserves committed batch --------------------------


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
