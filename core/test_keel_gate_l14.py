"""Tests for the federal aggregate row in L14 coverage projection."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from core.keel_gate_l14 import (
    FederalCoverageGate,
    L14CoverageCollection,
    L14CoverageRow,
    _EXPECTED_FEDERAL_RACES,
    _EXPECTED_FEDERAL_SEATS,
    _collect_federal_gate,
    _evidence_status,
)


class TestFederalCoverageGateModel:
    def test_round_trip_valid(self) -> None:
        gate = FederalCoverageGate(
            active_officeholders=540,
            total_seats=543,
            portrait_coverage_pct=92.5,
            bio_coverage_pct=85.0,
            candidate_link_coverage_pct=96.0,
            ie_coverage_pct=45.0,
        )
        assert gate.active_officeholders == 540
        assert gate.total_seats == 543
        assert gate.portrait_coverage_pct == 92.5
        assert gate.bio_coverage_pct == 85.0

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            FederalCoverageGate(
                active_officeholders=540,
                total_seats=543,
                portrait_coverage_pct=92.5,
                bio_coverage_pct=85.0,
                candidate_link_coverage_pct=96.0,
                ie_coverage_pct=45.0,
                bogus=True,
            )


class TestFederalAggregateRow:
    def test_federal_row_accepts_expected_shape(self) -> None:
        row = L14CoverageRow(
            jurisdiction_code="FEDERAL",
            name="Federal Aggregate",
            jurisdiction_type="federal_aggregate",
            best_update_frequency="weekly",
            runner_wired=True,
            tier="launch-support candidate",
            operational_reason=None,
            next_action=None,
            evidence_date=None,
            acquisition_pattern=None,
            discovery_maturity=None,
            source_contract_maturity=None,
            legal_filing_semantics_maturity=None,
            implementation_maturity="live_proven",
            operational_maturity="runner_wired",
            public_claim_status="launch-support candidate",
            completeness_intelligence_maturity=None,
            civics_candidacy_status=None,
            main_blocker=None,
            loaded_count=540,
            expected_count=_EXPECTED_FEDERAL_SEATS,
            nc_geometry_total_count=None,
            nc_geometry_srid_4326_count=None,
            nc_geometry_expected_count=None,
            nc_geometry_counts_match_expected=None,
        )
        assert row.jurisdiction_code == "FEDERAL"
        assert row.jurisdiction_type == "federal_aggregate"
        assert row.expected_count == 543


class TestCollectFederalGateFixture:
    """Deterministic test using a mock cursor that returns seeded values."""

    def test_returns_expected_gate_from_seeded_queries(self) -> None:
        captured_sql: list[str] = []
        query_results = iter(
            [
                (540,),  # active officeholders
                (543,),  # total seats
                (500, 540),  # portrait coverage
                (460, 540),  # bio coverage
                (520, 540),  # candidate link coverage
                (200,),  # ie candidates
            ]
        )

        class FakeCursor:
            def execute(self, sql, *_a, **_kw):  # noqa: ANN002, ANN001
                captured_sql.append(str(sql))

            def fetchone(self):  # noqa: ANN201
                return next(query_results)

            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *_a):  # noqa: ANN002
                pass

        class FakeConn:
            def cursor(self):  # noqa: ANN201
                return FakeCursor()

        gate = _collect_federal_gate(FakeConn())
        assert gate.active_officeholders == 540
        assert gate.total_seats == 543
        assert gate.portrait_coverage_pct == pytest.approx(92.59, abs=0.01)
        assert gate.bio_coverage_pct == pytest.approx(85.19, abs=0.01)
        assert gate.candidate_link_coverage_pct == pytest.approx(96.30, abs=0.01)
        assert gate.ie_coverage_pct == pytest.approx(38.46, abs=0.01)
        assert "core.person_portrait" in captured_sql[2]
        assert "p.portrait_url" not in captured_sql[2]


class TestFederalFirstStatus:
    def test_federal_gate_passes_even_when_parked_nc_geometry_is_unloaded(self) -> None:
        nc_row = L14CoverageRow(
            jurisdiction_code="NC",
            name="North Carolina",
            jurisdiction_type="state",
            best_update_frequency="weekly",
            runner_wired=True,
            tier="launch-support candidate",
            operational_reason=None,
            next_action=None,
            evidence_date=None,
            acquisition_pattern=None,
            discovery_maturity=None,
            source_contract_maturity=None,
            legal_filing_semantics_maturity=None,
            implementation_maturity=None,
            operational_maturity=None,
            public_claim_status=None,
            completeness_intelligence_maturity=None,
            civics_candidacy_status=None,
            main_blocker=None,
            loaded_count=None,
            expected_count=None,
            nc_geometry_total_count=0,
            nc_geometry_srid_4326_count=0,
            nc_geometry_expected_count=100,
            nc_geometry_counts_match_expected=False,
        )
        federal_row = L14CoverageRow(
            jurisdiction_code="FEDERAL",
            name="Federal Aggregate",
            jurisdiction_type="federal_aggregate",
            best_update_frequency="weekly",
            runner_wired=True,
            tier="launch-support candidate",
            operational_reason=None,
            next_action=None,
            evidence_date=None,
            acquisition_pattern=None,
            discovery_maturity=None,
            source_contract_maturity=None,
            legal_filing_semantics_maturity=None,
            implementation_maturity="live_proven",
            operational_maturity="runner_wired",
            public_claim_status="launch-support candidate",
            completeness_intelligence_maturity=None,
            civics_candidacy_status=None,
            main_blocker=None,
            # FEDERAL row denominator is now countable federal races (in [1, _EXPECTED_FEDERAL_RACES]),
            # not active officeholder seats; the officeholder-quality gate stays in federal_gate.
            loaded_count=474,
            expected_count=_EXPECTED_FEDERAL_RACES,
            nc_geometry_total_count=None,
            nc_geometry_srid_4326_count=None,
            nc_geometry_expected_count=None,
            nc_geometry_counts_match_expected=None,
        )
        collection = L14CoverageCollection(
            scope="coverage_registry_projection",
            registry_path="docs/reference/coverage-boundary-registry.json",
            lifecycle_path="docs/reference/coverage-lifecycle.json",
            lifecycle_updated_at=date(2026, 6, 6),
            rows=[nc_row, federal_row],
            federal_gate=FederalCoverageGate(
                active_officeholders=538,
                total_seats=_EXPECTED_FEDERAL_SEATS,
                portrait_coverage_pct=97.7,
                bio_coverage_pct=92.9,
                candidate_link_coverage_pct=100.0,
                ie_coverage_pct=1.0,
            ),
        )

        assert _evidence_status(collection) == "pass"
