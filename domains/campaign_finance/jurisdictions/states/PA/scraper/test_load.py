from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

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


_LOAD_MODULE_LINE_WARNING_THRESHOLD = 525


def test_load_module_stays_at_or_below_warning_threshold() -> None:
    line_count = len(Path(pa_load_module.__file__).read_text(encoding="utf-8").splitlines())
    assert line_count <= _LOAD_MODULE_LINE_WARNING_THRESHOLD, (
        f"load.py has {line_count} lines; keep it at or below the "
        f"{_LOAD_MODULE_LINE_WARNING_THRESHOLD}-line warning threshold"
    )
