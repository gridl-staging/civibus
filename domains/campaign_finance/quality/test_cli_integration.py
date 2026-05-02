"""Integration tests for quality CLI jurisdiction discovery behavior."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import insert_data_source, insert_source_record
from core.types.python.models import DataSource, SourceRecord, utc_now
from domains.campaign_finance.quality.cli import _discover_and_run, main
from domains.campaign_finance.quality.conftest import EXPECTED_EDGE_FAMILIES


pytestmark = pytest.mark.integration


class _ConnectionNoClose:
    """Proxy wrapper that prevents CLI main() from closing the shared db_conn fixture."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> object:
        return getattr(self._conn, name)

    def close(self) -> None:
        return None


def _test_jurisdiction(prefix: str) -> str:
    """Return a per-test synthetic jurisdiction to avoid ambient DB collisions."""
    return f"state/{prefix}-{uuid4().hex[:8]}"


def _insert_data_source_fixture(
    conn: psycopg.Connection,
    *,
    domain: str,
    jurisdiction: str | None,
    name: str,
    record_count: int | None,
    source_url: str | None = None,
) -> DataSource:
    data_source = DataSource(
        domain=domain,
        jurisdiction=jurisdiction,
        name=f"{name} {uuid4()}",
        source_url=source_url or f"https://example.com/{domain}/{uuid4()}",
        record_count=record_count,
    )
    insert_data_source(conn, data_source)
    return data_source


def _insert_source_record_fixture(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    superseded_by: UUID | None = None,
) -> SourceRecord:
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url="https://example.com/record",
        raw_fields={"transaction_amt": "25.00"},
        pull_date=utc_now(),
        record_hash=f"hash-{source_record_key}",
        superseded_by=superseded_by,
    )
    insert_source_record(conn, source_record)
    return source_record


def test_main_discovers_campaign_finance_jurisdictions_from_live_data_source(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    jurisdiction = _test_jurisdiction("CO")
    included_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="CO Campaign Source",
        record_count=1,
    )
    _insert_source_record_fixture(db_conn, data_source_id=included_source.id, source_record_key="co-1")
    _insert_data_source_fixture(
        db_conn,
        domain="corporate_filings",
        jurisdiction=jurisdiction,
        name="CO Corporate Source",
        record_count=1,
    )

    monkeypatch.setattr(
        "domains.campaign_finance.quality.cli.get_connection",
        lambda: _ConnectionNoClose(db_conn),
    )

    exit_code = main(["--check", "record_count"])
    captured = capsys.readouterr()

    assert exit_code in (0, 1), f"unexpected exit code {exit_code}: {captured.err}"
    payload = json.loads(captured.out)
    jurisdictions = [summary["jurisdiction"] for summary in payload["summaries"]]
    assert jurisdiction in jurisdictions
    co_summary = next(s for s in payload["summaries"] if s["jurisdiction"] == jurisdiction)
    assert co_summary["record_count"] == 1
    check_names = [result["name"] for result in co_summary["check_results"]]
    assert check_names == ["record_count_reconciliation"]


def test_main_unknown_jurisdiction_filter_returns_empty_live_db_report(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    present_jurisdiction = _test_jurisdiction("NC")
    missing_jurisdiction = _test_jurisdiction("ZZ")
    _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=present_jurisdiction,
        name="NC Campaign Source",
        record_count=0,
    )

    monkeypatch.setattr(
        "domains.campaign_finance.quality.cli.get_connection",
        lambda: _ConnectionNoClose(db_conn),
    )

    exit_code = main(["--jurisdiction", missing_jurisdiction, "--check", "record_count"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["jurisdiction_filter"] == missing_jurisdiction
    assert payload["summaries"] == []
    assert payload["total_checks"] == 0


def test_discover_and_run_returns_sorted_jurisdictions_from_live_data_source(
    db_conn: psycopg.Connection,
) -> None:
    co_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction="state/CO",
        name="CO Campaign Source",
        record_count=1,
    )
    nc_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction="state/NC",
        name="NC Campaign Source",
        record_count=1,
    )
    _insert_source_record_fixture(db_conn, data_source_id=co_source.id, source_record_key="co-1")
    _insert_source_record_fixture(db_conn, data_source_id=nc_source.id, source_record_key="nc-1")

    report = _discover_and_run(db_conn, jurisdiction_filter=None, check_filter="record_count")

    jurisdictions = [summary.jurisdiction for summary in report.summaries]
    assert "state/CO" in jurisdictions
    assert "state/NC" in jurisdictions
    co_idx = jurisdictions.index("state/CO")
    nc_idx = jurisdictions.index("state/NC")
    assert co_idx < nc_idx, "jurisdictions should be sorted alphabetically"


def test_discover_and_run_additively_includes_ca_mn_wa_jurisdictions(
    db_conn: psycopg.Connection,
) -> None:
    ca_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction="state/CA",
        name="CA Campaign Source",
        record_count=1,
    )
    mn_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction="state/MN",
        name="MN Campaign Source",
        record_count=1,
    )
    wa_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction="state/WA",
        name="WA Campaign Source",
        record_count=1,
    )
    _insert_source_record_fixture(db_conn, data_source_id=ca_source.id, source_record_key="ca-1")
    _insert_source_record_fixture(db_conn, data_source_id=mn_source.id, source_record_key="mn-1")
    _insert_source_record_fixture(db_conn, data_source_id=wa_source.id, source_record_key="wa-1")

    report = _discover_and_run(db_conn, jurisdiction_filter=None, check_filter="record_count")

    jurisdictions = [summary.jurisdiction for summary in report.summaries]
    assert "state/CA" in jurisdictions
    assert "state/MN" in jurisdictions
    assert "state/WA" in jurisdictions
    assert jurisdictions.index("state/CA") < jurisdictions.index("state/MN") < jurisdictions.index("state/WA")


def test_discover_and_run_deduplicates_baseline_urls_for_multiple_data_sources(
    db_conn: psycopg.Connection,
) -> None:
    jurisdiction = _test_jurisdiction("GA")
    shared_url = "https://example.com/shared/ga"
    ga_source_a = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="GA Campaign Source A",
        record_count=1,
        source_url=shared_url,
    )
    ga_source_b = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="GA Campaign Source B",
        record_count=1,
        source_url=shared_url,
    )
    _insert_source_record_fixture(db_conn, data_source_id=ga_source_a.id, source_record_key="ga-1")
    _insert_source_record_fixture(db_conn, data_source_id=ga_source_b.id, source_record_key="ga-2")

    report = _discover_and_run(db_conn, jurisdiction_filter=jurisdiction, check_filter="record_count")

    assert len(report.summaries) == 1
    summary = report.summaries[0]
    assert summary.jurisdiction == jurisdiction
    assert summary.baseline_urls == [shared_url]
    assert summary.record_count == 2
    assert len(summary.data_source_ids) == 2
    assert [result.name for result in summary.check_results] == [
        "record_count_reconciliation",
        "record_count_reconciliation",
    ]


def test_discover_and_run_orders_multi_source_output_by_name(
    db_conn: psycopg.Connection,
) -> None:
    jurisdiction = _test_jurisdiction("TX")
    zulu_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="Zulu Campaign Source",
        record_count=1,
        source_url="https://example.com/zulu",
    )
    alpha_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="Alpha Campaign Source",
        record_count=1,
        source_url="https://example.com/alpha",
    )
    _insert_source_record_fixture(db_conn, data_source_id=zulu_source.id, source_record_key="tx-zulu")
    _insert_source_record_fixture(db_conn, data_source_id=alpha_source.id, source_record_key="tx-alpha")

    report = _discover_and_run(db_conn, jurisdiction_filter=jurisdiction, check_filter="record_count")

    assert len(report.summaries) == 1
    summary = report.summaries[0]
    assert summary.data_source_ids == [str(alpha_source.id), str(zulu_source.id)]
    assert summary.baseline_urls == [
        "https://example.com/alpha",
        "https://example.com/zulu",
    ]
    assert [result.details["data_source_id"] for result in summary.check_results] == [
        str(alpha_source.id),
        str(zulu_source.id),
    ]


def test_discover_and_run_ignores_data_sources_with_null_jurisdiction(
    db_conn: psycopg.Connection,
) -> None:
    _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=None,
        name="Jurisdictionless Campaign Source",
        record_count=1,
    )
    co_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction="state/CO",
        name="CO Campaign Source",
        record_count=1,
    )
    _insert_source_record_fixture(db_conn, data_source_id=co_source.id, source_record_key="co-active")

    report = _discover_and_run(db_conn, jurisdiction_filter=None, check_filter="record_count")

    jurisdictions = [summary.jurisdiction for summary in report.summaries]
    assert "state/CO" in jurisdictions
    assert all(j is not None for j in jurisdictions), "null-jurisdiction data sources should be filtered out"


def test_discover_and_run_record_count_uses_active_records_only(
    db_conn: psycopg.Connection,
) -> None:
    jurisdiction = _test_jurisdiction("NC")
    data_source = _insert_data_source_fixture(
        db_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="NC Campaign Source",
        record_count=1,
    )
    active_record = _insert_source_record_fixture(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="nc-active",
    )
    _insert_source_record_fixture(
        db_conn,
        data_source_id=data_source.id,
        source_record_key="nc-superseded",
        superseded_by=active_record.id,
    )

    report = _discover_and_run(db_conn, jurisdiction_filter=jurisdiction, check_filter="record_count")

    assert len(report.summaries) == 1
    summary = report.summaries[0]
    assert summary.record_count == 1
    assert len(summary.check_results) == 1
    assert summary.check_results[0].name == "record_count_reconciliation"
    assert summary.check_results[0].status == "pass"


def test_main_graph_edges_filter_emits_graph_edge_presence_only(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    jurisdiction = _test_jurisdiction("GE")
    _insert_data_source_fixture(
        graph_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="Graph Edges Source",
        record_count=0,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.quality.cli.get_connection",
        lambda: _ConnectionNoClose(graph_conn),
    )

    exit_code = main(["--jurisdiction", jurisdiction, "--check", "graph_edges"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["check_filter"] == "graph_edges"
    assert len(payload["summaries"]) == 1
    summary = payload["summaries"][0]
    assert summary["jurisdiction"] == jurisdiction
    assert [result["name"] for result in summary["check_results"]] == ["graph_edge_presence"]
    graph_edge_result = summary["check_results"][0]
    assert graph_edge_result["metric_name"] == "edge_population_ratio"
    assert set(graph_edge_result["details"]["edge_families"]) == set(EXPECTED_EDGE_FAMILIES)


def test_main_default_run_includes_graph_edge_presence_with_db_checks(
    graph_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    jurisdiction = _test_jurisdiction("DG")
    _insert_data_source_fixture(
        graph_conn,
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name="Default Graph Source",
        record_count=0,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.quality.cli.get_connection",
        lambda: _ConnectionNoClose(graph_conn),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.quality.cli.run_freshness_checks",
        lambda _jurisdiction: [],
    )

    exit_code = main(["--jurisdiction", jurisdiction])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["check_filter"] is None
    assert len(payload["summaries"]) == 1
    summary = payload["summaries"][0]
    assert summary["jurisdiction"] == jurisdiction
    check_names = {result["name"] for result in summary["check_results"]}
    assert "graph_edge_presence" in check_names
    assert "record_count_reconciliation" in check_names
    assert "duplicate_records" in check_names
    assert "amount_sanity" in check_names
    assert "date_range" in check_names
    assert "completeness_source_record_key" in check_names
    assert "completeness_source_url" in check_names
    assert "completeness_raw_fields" in check_names
    assert "null_rate_source_record_key" in check_names
    assert "null_rate_source_url" in check_names
