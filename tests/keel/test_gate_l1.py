from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

import core.keel_gate_l1 as keel_gate_l1
from core.graph.loader_test_support import (
    seed_committee,
    seed_data_source,
    seed_filing,
    seed_source_record,
    seed_transaction,
)


def _write_anchor(path: Path) -> None:
    path.write_text(
        """---
scope: NC
domain: campaign_finance
review_cadence_days: 180
created: 2026-04-24
updated: 2026-04-24
schema_version: 1
---

## Coverage boundary

Committee-scoped NC proof slice for retained 2024 ADAMS FOR NC HOUSE transaction export
plus the statewide 2026 NC IE document-index filing lane. Excludes statewide NC
fundraising totals and any committee whose transaction export has not been loaded
with a matching committee-document export.

## Aggregate expectations

- metric: registered_candidate_committees
  value_expected: [100, 200]
  unit: count
  cycle: 2024
  source: https://example.test/committees
  tier: 2
  accessed: 2026-04-24
- metric: total_contributions_raised
  value_expected: [1000, 2000]
  unit: usd
  cycle: 2024
  source: https://example.test/contributions
  tier: 1
  accessed: 2026-04-24
- metric: total_independent_expenditures
  value_expected: [250, 500]
  unit: usd
  cycle: 2024
  source: https://example.test/ie
  tier: 1
  accessed: 2026-04-24

## Named-entity expectations

- name: Example Candidate One
  entity_type: candidate
  role_or_office: Governor
  cycle: 2024
  source: https://example.test/candidate-1
  tier: 1
  accessed: 2026-04-24
- name: Example Candidate Two
  entity_type: candidate
  role_or_office: Senate
  cycle: 2024
  source: https://example.test/candidate-2
  tier: 1
  accessed: 2026-04-24
- name: Example PAC One
  entity_type: pac
  role_or_office: State PAC
  cycle: 2024
  source: https://example.test/pac-1
  tier: 2
  accessed: 2026-04-24
- name: Example PAC Two
  entity_type: pac
  role_or_office: Federal PAC
  cycle: 2024
  source: https://example.test/pac-2
  tier: 2
  accessed: 2026-04-24
- name: Example IE Spender
  entity_type: ie_spender
  role_or_office: IE spender
  cycle: 2024
  source: https://example.test/ie-spender
  tier: 2
  accessed: 2026-04-24

## Negative expectations

- pattern: TEST COMMITTEE
  reason: placeholder committee names indicate fixture leakage
  source: internal_convention
  tier: internal
  accessed: 2026-04-24
- pattern: UNKNOWN CANDIDATE
  reason: unresolved recipient placeholder should not render as a real candidate
  source: internal_convention
  tier: internal
  accessed: 2026-04-24

## Source bibliography

- url: https://example.test/contributions
  description: Official contribution total summary
- url: https://example.test/ie
  description: Official IE total summary
""",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_anchor_file_reads_frontmatter_and_primary_contribution_metric(tmp_path: Path) -> None:
    anchor_path = tmp_path / "NC.md"
    _write_anchor(anchor_path)

    anchor = keel_gate_l1.load_anchor_file(anchor_path)
    metric = keel_gate_l1.select_primary_metric(anchor)

    assert anchor.frontmatter.scope == "NC"
    assert "Committee-scoped NC proof slice" in anchor.coverage_boundary
    assert len(anchor.aggregate_expectations) == 3
    assert len(anchor.named_entity_expectations) == 5
    assert len(anchor.negative_expectations) == 2
    assert metric.metric == "total_contributions_raised"
    assert metric.expected_minimum == Decimal("1000")
    assert metric.expected_maximum == Decimal("2000")


def test_select_primary_metric_prefers_contribution_total_over_ie_filing_index_rows() -> None:
    anchor = keel_gate_l1.AnchorFile(
        frontmatter=keel_gate_l1.AnchorFrontmatter(
            scope="NC",
            domain="campaign_finance",
            review_cadence_days=180,
            created=date(2026, 4, 24),
            updated=date(2026, 4, 24),
            schema_version=1,
        ),
        coverage_boundary="NC campaign-finance anchor scope",
        aggregate_expectations=[
            keel_gate_l1.AggregateExpectation(
                metric="ie_document_index_filings",
                value_expected=[45, 80],
                unit="count",
                cycle=2026,
                source="https://example.test/ie-index",
                tier=1,
                accessed=date(2026, 4, 24),
                notes="IE filing-index expectation remains non-primary for L1.",
            ),
            keel_gate_l1.AggregateExpectation(
                metric="total_contributions_raised",
                value_expected=[70000, 71000],
                unit="usd",
                cycle=2024,
                source="https://example.test/contributions",
                tier=1,
                accessed=date(2026, 4, 24),
            ),
            keel_gate_l1.AggregateExpectation(
                metric="registered_candidate_committees",
                value_expected=[1, 5],
                unit="count",
                cycle=2024,
                source="https://example.test/committees",
                tier=1,
                accessed=date(2026, 4, 24),
            ),
        ],
        named_entity_expectations=[
            keel_gate_l1.NamedEntityExpectation(
                name="Entity One",
                entity_type="committee",
                role_or_office="Role",
                cycle=2024,
                source="https://example.test/entity-1",
                tier=1,
                accessed=date(2026, 4, 24),
            )
        ]
        * 5,
        negative_expectations=[
            keel_gate_l1.NegativeExpectation(
                pattern="TEST",
                reason="fixture leakage",
                source="internal_convention",
                tier="internal",
                accessed=date(2026, 4, 24),
            ),
            keel_gate_l1.NegativeExpectation(
                pattern="UNKNOWN",
                reason="unresolved candidate",
                source="internal_convention",
                tier="internal",
                accessed=date(2026, 4, 24),
            ),
        ],
        source_bibliography=[
            keel_gate_l1.SourceBibliographyEntry(
                url="https://example.test/contributions",
                description="Contribution source",
            )
        ],
    )

    metric = keel_gate_l1.select_primary_metric(anchor)

    assert metric.metric == "total_contributions_raised"


def test_nc_anchor_keeps_ie_filing_index_non_primary_and_contribution_total_primary() -> None:
    nc_anchor_path = Path(__file__).resolve().parents[2] / "docs" / "reference" / "anchors" / "NC.md"

    anchor = keel_gate_l1.load_anchor_file(nc_anchor_path)
    ie_metric_rows = [row for row in anchor.aggregate_expectations if row.metric == "ie_document_index_filings"]
    primary_metric = keel_gate_l1.select_primary_metric(anchor)

    assert len(ie_metric_rows) == 1
    assert ie_metric_rows[0].unit != "usd"
    assert "contribution" not in ie_metric_rows[0].metric.lower()
    assert primary_metric.metric == "total_contributions_raised"


def test_query_scope_total_sql_stays_receipt_only_and_excludes_ie_spend() -> None:
    statements: list[str] = []
    parameters: list[tuple[object, ...]] = []

    class _FakeCursor:
        def execute(self, statement: str, params: tuple[object, ...]) -> None:
            statements.append(statement)
            parameters.append(params)

        def fetchone(self) -> tuple[Decimal]:
            return (Decimal("0"),)

        def __enter__(self) -> "_FakeCursor":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    class _FakeConnection:
        def cursor(self) -> _FakeCursor:
            return _FakeCursor()

    total = keel_gate_l1.query_scope_total(_FakeConnection(), jurisdiction="NC", cycle=2024)

    assert total == Decimal("0")
    assert len(statements) == 1
    assert "t.support_oppose IS NULL" in statements[0]
    assert "SUM(t.amount)" in statements[0]
    assert "independent" not in statements[0].lower()
    assert parameters[0][0] == "NC"
    assert parameters[0][2] == date(2024, 1, 1)
    assert parameters[0][3] == date(2025, 1, 1)
    assert "Independent Expenditure" not in parameters[0][1]


@pytest.mark.integration
def test_query_scope_total_counts_only_target_jurisdiction_cycle_and_contributions(
    db_conn: psycopg.Connection,
) -> None:
    data_source_id = seed_data_source(db_conn, label="keel-l1")
    source_record_id = seed_source_record(db_conn, data_source_id=data_source_id, key="keel-l1-source-record")
    nc_committee_id = seed_committee(db_conn, name="NC Test Committee")
    nc_filing_id = seed_filing(db_conn, committee_id=nc_committee_id, source_record_id=source_record_id)

    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("125.00"),
        transaction_date=date(2024, 2, 1),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Expenditure (Itemized)",
        amount=Decimal("50.00"),
        transaction_date=date(2024, 2, 2),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("75.00"),
        transaction_date=date(2025, 1, 3),
    )

    other_committee_id = seed_committee(db_conn, name="SC Test Committee")
    db_conn.execute("UPDATE cf.committee SET state = 'SC' WHERE id = %s", (other_committee_id,))
    other_filing_id = seed_filing(db_conn, committee_id=other_committee_id, source_record_id=source_record_id)
    seed_transaction(
        db_conn,
        filing_id=other_filing_id,
        committee_id=other_committee_id,
        source_record_id=source_record_id,
        transaction_type="Monetary (Itemized)",
        amount=Decimal("999.00"),
        transaction_date=date(2024, 3, 1),
    )

    assert keel_gate_l1.query_scope_total(db_conn, jurisdiction="NC", cycle=2024) == Decimal("125.00")


@pytest.mark.integration
def test_query_scope_total_counts_nc_receipt_labels_but_excludes_ie_and_spending(
    db_conn: psycopg.Connection,
) -> None:
    data_source_id = seed_data_source(db_conn, label="keel-l1-nc-types")
    source_record_id = seed_source_record(db_conn, data_source_id=data_source_id, key="keel-l1-nc-types-record")
    nc_committee_id = seed_committee(db_conn, name="NC Typed Committee")
    nc_filing_id = seed_filing(db_conn, committee_id=nc_committee_id, source_record_id=source_record_id)

    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Individual",
        amount=Decimal("25.00"),
        transaction_date=date(2024, 4, 1),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Non-Party Comm",
        amount=Decimal("50.00"),
        transaction_date=date(2024, 4, 2),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Business/Group/Org",
        amount=Decimal("75.00"),
        transaction_date=date(2024, 4, 3),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Operating Exp",
        amount=Decimal("1000.00"),
        transaction_date=date(2024, 4, 4),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Cont to Other Comm",
        amount=Decimal("2000.00"),
        transaction_date=date(2024, 4, 5),
    )
    seed_transaction(
        db_conn,
        filing_id=nc_filing_id,
        committee_id=nc_committee_id,
        source_record_id=source_record_id,
        transaction_type="Independent Expenditure",
        amount=Decimal("3000.00"),
        transaction_date=date(2024, 4, 6),
        support_oppose="S",
    )

    assert keel_gate_l1.query_scope_total(db_conn, jurisdiction="NC", cycle=2024) == Decimal("150.00")


def test_write_l1_evidence_marks_fail_when_current_total_is_below_anchor_minimum(tmp_path: Path) -> None:
    anchor_path = tmp_path / "anchors" / "NC.md"
    anchor_path.parent.mkdir(parents=True)
    _write_anchor(anchor_path)

    anchor = keel_gate_l1.load_anchor_file(anchor_path)
    metric = keel_gate_l1.select_primary_metric(anchor)

    evidence_path = keel_gate_l1.write_l1_evidence(
        jurisdiction="NC",
        metric=metric,
        current_total=Decimal("400"),
        repo_sha="d54355d6",
        produced_at=datetime(2026, 4, 24, 22, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path / "evidence",
        anchor_path=anchor_path,
        anchor_schema_version=anchor.frontmatter.schema_version,
        data_store_environment="production",
    )

    payload = _read_json(evidence_path)

    assert payload["status"] == "fail"
    assert payload["scope"] == "NC"
    assert payload["current_total"] == 400
    assert payload["expected_range"] == {"minimum": 1000, "maximum": 2000}
    assert payload["ratio"] == 0.4
    assert payload["data_store_environment"] == "production"


def test_main_writes_pass_evidence_when_anchor_and_db_total_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    anchors_root = tmp_path / "anchors"
    anchor_path = anchors_root / "NC.md"
    anchors_root.mkdir(parents=True)
    _write_anchor(anchor_path)
    monkeypatch.setenv("CIVIBUS_ENV", "production")

    class _FakeConnection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(keel_gate_l1, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(
        keel_gate_l1,
        "query_scope_total",
        lambda connection, *, jurisdiction, cycle: Decimal("1500"),
    )
    monkeypatch.setattr(keel_gate_l1, "_repo_sha", lambda: "d54355d6")

    exit_code = keel_gate_l1.main(
        [
            "--jurisdiction",
            "NC",
            "--anchors-root",
            str(anchors_root),
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    evidence_path = tmp_path / "evidence" / "NC" / f"{keel_gate_l1._utc_now().date().isoformat()}.json"
    payload = _read_json(evidence_path)

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["current_total"] == 1500
    assert payload["data_store_environment"] == "production"


def test_main_writes_error_evidence_when_total_query_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    anchors_root = tmp_path / "anchors"
    anchor_path = anchors_root / "NC.md"
    anchors_root.mkdir(parents=True)
    _write_anchor(anchor_path)
    monkeypatch.setenv("CIVIBUS_ENV", "production")

    class _FakeConnection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(keel_gate_l1, "get_connection", lambda: _FakeConnection())

    def _raise_query_error(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(keel_gate_l1, "query_scope_total", _raise_query_error)
    monkeypatch.setattr(keel_gate_l1, "_repo_sha", lambda: "d54355d6")

    exit_code = keel_gate_l1.main(
        [
            "--jurisdiction",
            "NC",
            "--anchors-root",
            str(anchors_root),
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    evidence_path = tmp_path / "evidence" / "NC" / f"{keel_gate_l1._utc_now().date().isoformat()}.json"
    payload = _read_json(evidence_path)

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["current_total"] == 0
    assert payload["expected_range"] == {"minimum": 1000, "maximum": 2000}
    assert payload["ratio"] == 0
    assert str(payload["anchor_path"]).endswith("anchors/NC.md")
    assert payload["data_store_environment"] == "production"


def test_main_writes_error_evidence_when_not_running_against_production_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    anchors_root = tmp_path / "anchors"
    anchor_path = anchors_root / "NC.md"
    anchors_root.mkdir(parents=True)
    _write_anchor(anchor_path)
    monkeypatch.setenv("CIVIBUS_ENV", "development")
    monkeypatch.setattr(keel_gate_l1, "_repo_sha", lambda: "d54355d6")

    exit_code = keel_gate_l1.main(
        [
            "--jurisdiction",
            "NC",
            "--anchors-root",
            str(anchors_root),
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    evidence_path = tmp_path / "evidence" / "NC" / f"{keel_gate_l1._utc_now().date().isoformat()}.json"
    payload = _read_json(evidence_path)

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["current_total"] == 0
    assert payload["data_store_environment"] == "development"


def test_main_returns_error_when_anchor_file_is_missing(tmp_path: Path) -> None:
    exit_code = keel_gate_l1.main(
        [
            "--jurisdiction",
            "NC",
            "--anchors-root",
            str(tmp_path / "anchors"),
            "--evidence-root",
            str(tmp_path / "evidence"),
        ]
    )

    assert exit_code == 1
    assert not (tmp_path / "evidence").exists()


def test_repo_audited_anchor_files_are_schema_valid() -> None:
    anchors_root = Path(__file__).resolve().parents[2] / "docs" / "reference" / "anchors"
    jurisdictions = ("NC", "IN", "NE", "LA", "AL", "GA", "PA", "TX", "CA")

    for jurisdiction in jurisdictions:
        anchor_path = anchors_root / f"{jurisdiction}.md"
        assert anchor_path.exists(), f"missing anchor file: {anchor_path}"

        anchor = keel_gate_l1.load_anchor_file(anchor_path)
        metric = keel_gate_l1.select_primary_metric(anchor)

        assert anchor.frontmatter.scope == jurisdiction
        assert anchor.frontmatter.domain == "campaign_finance"
        assert anchor.coverage_boundary
        assert len(anchor.aggregate_expectations) >= 3
        assert len(anchor.named_entity_expectations) >= 5
        assert len(anchor.negative_expectations) >= 2
        assert metric.unit == "usd"
        assert "contribution" in metric.metric.lower()
