from __future__ import annotations

import inspect
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
    _resolve_pa_filings_path,
    load_pa_contributions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.PA.scraper.parse import parse_contributions, parse_filings

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv", year=2025))


def _filer_rows() -> list[dict[str, str | None]]:
    return list(parse_filings(_FIXTURE_DIR / "sample_filings.csv", year=2025))


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


def test_load_pa_with_filings_rolls_back_raw_ingest_if_relational_phase_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    load_result = LoadResult(
        inserted=2,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )

    ensure_transaction_open = MagicMock()
    monkeypatch.setattr(pa_load_module, "ensure_transaction_open", ensure_transaction_open)
    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", lambda *_args, **_kwargs: "pa-source-id")
    monkeypatch.setattr(pa_load_module, "_load_pa_file", lambda *_args, **_kwargs: load_result)
    monkeypatch.setattr(pa_load_module, "parse_filings", lambda _path, _year: iter(()))
    monkeypatch.setitem(pa_load_module._PA_PARSER_FN, "contributions", lambda _path, _year: iter(()))
    monkeypatch.setattr(
        pa_load_module,
        "_load_pa_relational_transactions",
        MagicMock(side_effect=RuntimeError("relational failed")),
    )

    with pytest.raises(RuntimeError, match="relational failed"):
        pa_load_module._load_pa_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025)

    ensure_transaction_open.assert_called_once_with(conn)
    conn.rollback.assert_called_once_with()
    conn.commit.assert_not_called()


def test_load_pa_with_filings_reports_superseded_rows_from_filer_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    load_result = LoadResult(
        inserted=2,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.1,
    )

    campaignfinance_id_column = _load_column_for_semantic_path("filings", "pa.campaignfinance_id")
    amend_column = _load_column_for_semantic_path("filings", "pa.amend_flag")
    terminate_column = _load_column_for_semantic_path("filings", "pa.terminate_flag")
    detail_campaign_id_column = _load_column_for_semantic_path("contributions", "pa.campaign_finance_id")

    monkeypatch.setattr(pa_load_module, "ensure_pa_data_source", lambda *_args, **_kwargs: "pa-source-id")
    monkeypatch.setattr(pa_load_module, "_load_pa_file", lambda *_args, **_kwargs: load_result)
    monkeypatch.setattr(
        pa_load_module,
        "parse_filings",
        lambda _path, _year: iter(
            [
                {
                    campaignfinance_id_column: "1001",
                    amend_column: "N",
                    terminate_column: "Y",
                }
            ]
        ),
    )
    monkeypatch.setitem(
        pa_load_module._PA_PARSER_FN,
        "contributions",
        lambda _path, _year: iter([{detail_campaign_id_column: "1001"}]),
    )
    monkeypatch.setattr(pa_load_module, "_load_pa_relational_transactions", MagicMock(return_value=1))

    result = pa_load_module._load_pa_with_filings(
        conn, _SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", year=2025
    )

    assert result.superseded == 1


def test_resolve_pa_filings_path_returns_zip_path_unchanged(tmp_path: Path) -> None:
    zip_path = tmp_path / "pa-2025.zip"
    zip_path.touch()
    assert _resolve_pa_filings_path(zip_path, data_type="contributions") == zip_path


def test_resolve_pa_filings_path_derives_sibling_filings_csv(tmp_path: Path) -> None:
    detail = tmp_path / "sample_contributions.csv"
    filings = tmp_path / "sample_filings.csv"
    detail.touch()
    filings.touch()
    assert _resolve_pa_filings_path(detail, data_type="contributions") == filings


def test_resolve_pa_filings_path_raises_when_no_sibling_found(tmp_path: Path) -> None:
    detail = tmp_path / "sample_contributions.csv"
    detail.touch()
    with pytest.raises(FileNotFoundError, match="Cannot locate PA filings CSV"):
        _resolve_pa_filings_path(detail, data_type="contributions")


def test_relational_loader_helpers_stay_within_parameter_hard_limit() -> None:
    helper_functions = (
        pa_load_module._upsert_pa_filing,
        pa_load_module._upsert_pa_transaction_with_filing,
        pa_load_module._load_pa_relational_transactions,
    )
    parameter_counts = {helper.__name__: len(inspect.signature(helper).parameters) for helper in helper_functions}
    violations = {
        helper_name: parameter_count for helper_name, parameter_count in parameter_counts.items() if parameter_count > 6
    }
    assert not violations, f"PA relational loader helpers must stay at or below six parameters: {violations}"
