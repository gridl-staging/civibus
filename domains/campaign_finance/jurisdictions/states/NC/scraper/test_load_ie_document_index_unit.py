from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

from domains.campaign_finance.jurisdictions.states.NC.scraper import load
from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index


def test_load_exposes_public_shared_helpers_for_ie_loader() -> None:
    assert load.build_load_result is load._build_load_result
    assert load.iter_nc_rows is load._iter_nc_rows
    assert load.parse_optional_date is load._parse_optional_date
    assert load.require_text is load._require_text
    assert load.resolve_committee_doc_source_record is load._resolve_committee_doc_source_record
    assert load.resolve_nc_committee_bridge is load._resolve_nc_committee_bridge
    assert load.to_amendment_indicator is load._to_amendment_indicator


def test_ie_loader_uses_public_load_counts_symbol() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_types

    assert hasattr(load_types, "NCLoadCounts")
    counts = load_types.NCLoadCounts(inserted=1, skipped=2, errors=3)
    assert counts.inserted == 1
    assert counts.skipped == 2
    assert counts.errors == 3


def test_load_nc_ie_document_index_row_keeps_filing_upsert_when_source_record_exists(
    monkeypatch,
) -> None:
    conn = MagicMock()
    source_record_id = UUID("f0791933-636f-468d-bf0a-3edc54268414")
    data_source_id = UUID("2fc5ad2a-d4c4-4e7a-b9ce-c14b6d6ca8d4")
    committee_id = UUID("0b8f3dca-f2c7-4e6d-9f8a-4cc3d1d62f8e")
    filing = object()
    row = {
        "Committee Name": "Example IE Committee",
        "SBoE ID": "No Id",
        "Year": "2026",
        "Doc Type": "Disclosure Report",
        "Doc Name": "Independent Expenditure Report",
        "Amend": "N",
        "Received Image": "02/24/2026",
        "Received Data": "02/24/2026",
        "Start Date": "02/01/2026",
        "End Date": "02/14/2026",
        "Image": "IMAGE",
        "Data": "DATA",
    }
    report_section_url = "https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=123&SID=No+Id"

    resolve_source_record = MagicMock(return_value=(source_record_id, False))
    normalize_committee_id = MagicMock(return_value="NC-IE-committee")
    resolve_committee_bridge = MagicMock(return_value=committee_id)
    build_filing = MagicMock(return_value=filing)
    persist_report_section_url = MagicMock()
    upsert_filing = MagicMock()

    monkeypatch.setattr(load_ie_document_index, "resolve_committee_doc_source_record", resolve_source_record)
    monkeypatch.setattr(load_ie_document_index, "_normalize_nc_ie_committee_sboe_id", normalize_committee_id)
    monkeypatch.setattr(load_ie_document_index, "resolve_nc_committee_bridge", resolve_committee_bridge)
    monkeypatch.setattr(load_ie_document_index, "_build_nc_ie_filing", build_filing)
    monkeypatch.setattr(load_ie_document_index, "set_nc_source_record_report_section_url", persist_report_section_url)
    monkeypatch.setattr(load_ie_document_index, "upsert_filing", upsert_filing)

    inserted = load_ie_document_index._load_nc_ie_document_index_row(
        conn,
        row=row,
        data_source_id=data_source_id,
        report_section_url=report_section_url,
    )

    assert inserted is False
    resolve_source_record.assert_called_once_with(
        conn,
        row=row,
        data_source_id=data_source_id,
    )
    normalize_committee_id.assert_called_once_with(row)
    resolve_committee_bridge.assert_called_once_with(
        conn,
        "NC-IE-committee",
        committee_name="Example IE Committee",
    )
    build_filing.assert_called_once_with(
        row,
        committee_id=committee_id,
        source_record_id=source_record_id,
    )
    upsert_filing.assert_called_once_with(conn, filing)
    persist_report_section_url.assert_called_once_with(
        conn,
        source_record_id=source_record_id,
        report_section_url=report_section_url,
    )


def test_load_nc_ie_document_index_row_omits_report_section_persistence_when_url_missing(
    monkeypatch,
) -> None:
    conn = MagicMock()
    source_record_id = UUID("09396788-b13b-49d5-af95-5f8de3fa54f4")
    data_source_id = UUID("069fa905-e3f8-4958-812b-f8b04ed18f06")
    committee_id = UUID("ec3f9085-2006-4c43-867a-09d8ade6fa4c")
    filing = object()
    row = {"Committee Name": "Example IE Committee"}

    monkeypatch.setattr(
        load_ie_document_index,
        "resolve_committee_doc_source_record",
        MagicMock(return_value=(source_record_id, True)),
    )
    monkeypatch.setattr(load_ie_document_index, "_normalize_nc_ie_committee_sboe_id", MagicMock(return_value="NC-IE"))
    monkeypatch.setattr(load_ie_document_index, "resolve_nc_committee_bridge", MagicMock(return_value=committee_id))
    monkeypatch.setattr(load_ie_document_index, "_build_nc_ie_filing", MagicMock(return_value=filing))
    persist_report_section_url = MagicMock()
    monkeypatch.setattr(load_ie_document_index, "set_nc_source_record_report_section_url", persist_report_section_url)
    upsert_filing = MagicMock()
    monkeypatch.setattr(load_ie_document_index, "upsert_filing", upsert_filing)

    inserted = load_ie_document_index._load_nc_ie_document_index_row(
        conn,
        row=row,
        data_source_id=data_source_id,
        report_section_url=None,
    )

    assert inserted is True
    upsert_filing.assert_called_once_with(conn, filing)
    persist_report_section_url.assert_not_called()
