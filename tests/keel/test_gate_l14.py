from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import core.keel_gate_l14 as keel_gate_l14
import yaml
from domains.campaign_finance.coverage import lifecycle as coverage_lifecycle
from domains.campaign_finance.coverage import registry as coverage_registry
from domains.campaign_finance.coverage import render_summary as coverage_render_summary


def test_l14_coverage_row_allows_optional_counts_and_forbids_extra() -> None:
    row = keel_gate_l14.L14CoverageRow(
        jurisdiction_code="NC",
        name="North Carolina",
        jurisdiction_type="state",
        best_update_frequency="daily",
        runner_wired=True,
        tier="launch-support candidate",
        operational_reason="NC reason",
        next_action="NC next",
        evidence_date=date(2026, 4, 24),
        loaded_count=8,
        expected_count=11,
        acquisition_pattern=None,
        discovery_maturity=None,
        source_contract_maturity=None,
        legal_filing_semantics_maturity=None,
        implementation_maturity=None,
        operational_maturity=None,
        public_claim_status=None,
        completeness_intelligence_maturity=None,
        main_blocker=None,
    )
    dumped = row.model_dump(mode="json")
    assert dumped["loaded_count"] == 8
    assert dumped["expected_count"] == 11

    with pytest.raises(ValueError):
        keel_gate_l14.L14CoverageRow(
            **{
                **row.model_dump(mode="python"),
                "not_a_real_field": "forbidden",
            }
        )


def test_collect_coverage_matrix_reuses_registry_and_lifecycle_owners(monkeypatch) -> None:
    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="B",
                name="Beta",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 1),
                covers_sub_jurisdictions=True,
                source_count=2,
                source_names=["Beta API", "Beta IE"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="Beta evidence",
                operational_reason="Beta reason",
                next_action="Beta next",
                evidence_date=date(2026, 4, 2),
                loaded_count=12,
                expected_count=12,
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            ),
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="A",
                name="Alpha",
                jurisdiction_type="state",
                best_update_frequency="weekly",
                best_last_verified_working=None,
                covers_sub_jurisdictions=False,
                source_count=1,
                source_names=["Alpha API"],
                runner_wired=False,
                tier="freshness-limited",
                evidence_summary="Alpha evidence",
                operational_reason="Alpha reason",
                next_action="Alpha next",
                evidence_date=None,
                loaded_count=None,
                expected_count=None,
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            ),
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(
        updated_at=date(2026, 4, 24),
        rows=[
            coverage_lifecycle.ImplementedRegionLifecycleRow(
                jurisdiction_code="A",
                name="Alpha lifecycle alias",
                acquisition_pattern="bulk_api",
                discovery_maturity="researched",
                source_contract_maturity="verified",
                legal_filing_semantics_maturity="substantial",
                implementation_maturity="live_proven",
                operational_maturity="operational",
                public_claim_status="freshness-limited",
                completeness_intelligence_maturity="gap_detection_ready",
                civics_candidacy_status="loaded",
                main_blocker="Needs broader municipal audit.",
            )
        ],
    )

    load_calls: list[tuple[str, Path]] = []

    def _fake_load_registry(path: str | Path) -> coverage_registry.CoverageRegistry:
        load_calls.append(("registry", Path(path)))
        return registry

    def _fake_load_lifecycle(path: str | Path) -> coverage_lifecycle.ImplementedRegionLifecycleRegistry:
        load_calls.append(("lifecycle", Path(path)))
        return lifecycle

    def _raise_if_called(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise AssertionError("derived markdown rendering must not be used as L14 input")

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", _fake_load_registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", _fake_load_lifecycle)
    monkeypatch.setattr(coverage_render_summary, "render_summary_markdown", _raise_if_called)
    monkeypatch.setattr(coverage_render_summary, "render_publication_markdown", _raise_if_called)
    monkeypatch.setattr(keel_gate_l14, "_load_civics_roster_sources", lambda sources_path: [])
    monkeypatch.setattr(keel_gate_l14, "_manifest_member_counts_by_source_id", lambda: {})
    monkeypatch.setattr(keel_gate_l14, "_load_roster_loaded_counts", lambda conn, source_ids: {})

    class _FakeConn:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(keel_gate_l14, "get_connection", lambda: _FakeConn())

    collection = keel_gate_l14.collect_coverage_matrix(
        registry_path=Path("docs/research/coverage-registry.json"),
        lifecycle_path=Path("docs/research/implemented-region-lifecycle.json"),
    )

    assert load_calls == [
        ("registry", Path("docs/research/coverage-registry.json")),
        ("lifecycle", Path("docs/research/implemented-region-lifecycle.json")),
    ]
    assert collection.scope == keel_gate_l14.L14_SCOPE
    assert [row.jurisdiction_code for row in collection.rows] == ["B", "A"]

    expected_registry_fields = (
        "jurisdiction_code",
        "name",
        "jurisdiction_type",
        "best_update_frequency",
        "runner_wired",
        "tier",
        "operational_reason",
        "next_action",
        "evidence_date",
        "loaded_count",
        "expected_count",
    )
    expected_lifecycle_fields = (
        "acquisition_pattern",
        "discovery_maturity",
        "source_contract_maturity",
        "legal_filing_semantics_maturity",
        "implementation_maturity",
        "operational_maturity",
        "public_claim_status",
        "completeness_intelligence_maturity",
        "civics_candidacy_status",
        "main_blocker",
    )
    expected_geometry_fields = (
        "nc_geometry_total_count",
        "nc_geometry_srid_4326_count",
        "nc_geometry_expected_count",
        "nc_geometry_counts_match_expected",
    )
    expected_keys = {
        *expected_registry_fields,
        *expected_lifecycle_fields,
        "loaded_count",
        "expected_count",
        *expected_geometry_fields,
    }

    beta = collection.rows[0].model_dump(mode="json")
    alpha = collection.rows[1].model_dump(mode="json")
    assert set(beta) == expected_keys
    assert set(alpha) == expected_keys

    assert {field: beta[field] for field in expected_registry_fields} == {
        "jurisdiction_code": "B",
        "name": "Beta",
        "jurisdiction_type": "state",
        "best_update_frequency": "daily",
        "runner_wired": True,
        "tier": "launch-support candidate",
        "operational_reason": "Beta reason",
        "next_action": "Beta next",
        "evidence_date": "2026-04-02",
        "loaded_count": 12,
        "expected_count": 12,
    }
    assert {field: beta[field] for field in expected_lifecycle_fields} == {
        "acquisition_pattern": None,
        "discovery_maturity": None,
        "source_contract_maturity": None,
        "legal_filing_semantics_maturity": None,
        "implementation_maturity": None,
        "operational_maturity": None,
        "public_claim_status": None,
        "completeness_intelligence_maturity": None,
        "civics_candidacy_status": None,
        "main_blocker": None,
    }
    assert {field: beta[field] for field in expected_geometry_fields} == {
        "nc_geometry_total_count": None,
        "nc_geometry_srid_4326_count": None,
        "nc_geometry_expected_count": None,
        "nc_geometry_counts_match_expected": None,
    }

    assert {field: alpha[field] for field in expected_registry_fields} == {
        "jurisdiction_code": "A",
        "name": "Alpha",
        "jurisdiction_type": "state",
        "best_update_frequency": "weekly",
        "runner_wired": False,
        "tier": "freshness-limited",
        "operational_reason": "Alpha reason",
        "next_action": "Alpha next",
        "evidence_date": None,
        "loaded_count": None,
        "expected_count": None,
    }
    assert {field: alpha[field] for field in expected_lifecycle_fields} == {
        "acquisition_pattern": "bulk_api",
        "discovery_maturity": "researched",
        "source_contract_maturity": "verified",
        "legal_filing_semantics_maturity": "substantial",
        "implementation_maturity": "live_proven",
        "operational_maturity": "operational",
        "public_claim_status": "freshness-limited",
        "completeness_intelligence_maturity": "gap_detection_ready",
        "civics_candidacy_status": "loaded",
        "main_blocker": "Needs broader municipal audit.",
    }
    assert {field: alpha[field] for field in expected_geometry_fields} == {
        "nc_geometry_total_count": None,
        "nc_geometry_srid_4326_count": None,
        "nc_geometry_expected_count": None,
        "nc_geometry_counts_match_expected": None,
    }


def test_collect_coverage_matrix_includes_roster_source_rows_with_loaded_expected_counts(monkeypatch) -> None:
    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="NC",
                name="North Carolina",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 1),
                covers_sub_jurisdictions=True,
                source_count=1,
                source_names=["NC API"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="evidence",
                operational_reason="reason",
                next_action="next",
                evidence_date=date(2026, 4, 2),
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            )
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(
        updated_at=date(2026, 4, 24),
        rows=[],
    )

    class _FakeConn:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", lambda path: registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", lambda path: lifecycle)
    monkeypatch.setattr(
        keel_gate_l14,
        "_load_civics_roster_sources",
        lambda sources_path: [
            {"source_id": "nc_durham_county_commissioners_roster", "jurisdiction_code": "NC"},
            {"source_id": "nc_wcpss_school_board_roster", "jurisdiction_code": "NC"},
        ],
    )
    monkeypatch.setattr(
        keel_gate_l14,
        "_manifest_member_counts_by_source_id",
        lambda: {
            "nc_durham_county_commissioners_roster": 5,
            "nc_wcpss_school_board_roster": 9,
        },
    )
    monkeypatch.setattr(
        keel_gate_l14,
        "_load_roster_loaded_counts",
        lambda conn, source_ids: {
            "nc_durham_county_commissioners_roster": 5,
            "nc_wcpss_school_board_roster": 8,
        },
    )
    monkeypatch.setattr(keel_gate_l14, "get_connection", lambda: _FakeConn())

    collection = keel_gate_l14.collect_coverage_matrix(
        registry_path=Path("docs/research/coverage-registry.json"),
        lifecycle_path=Path("docs/research/implemented-region-lifecycle.json"),
    )

    roster_rows = [row for row in collection.rows if row.jurisdiction_type == "civics_roster_source"]
    assert [row.jurisdiction_code for row in roster_rows] == [
        "nc_durham_county_commissioners_roster",
        "nc_wcpss_school_board_roster",
    ]
    assert roster_rows[0].loaded_count == 5
    assert roster_rows[0].expected_count == 5
    assert roster_rows[1].loaded_count == 8
    assert roster_rows[1].expected_count == 9


def test_collect_coverage_matrix_nc_geometry_summary_detects_off_by_one(monkeypatch) -> None:
    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="NC",
                name="North Carolina",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 20),
                covers_sub_jurisdictions=True,
                source_count=3,
                source_names=["NC Transactions", "NC Committee Documents", "NC IE Index"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="NC evidence",
                operational_reason="NC reason",
                next_action="NC next",
                evidence_date=date(2026, 4, 21),
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            ),
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="IN",
                name="Indiana",
                jurisdiction_type="state",
                best_update_frequency="annual",
                best_last_verified_working=None,
                covers_sub_jurisdictions=True,
                source_count=1,
                source_names=["IN ZIP"],
                runner_wired=True,
                tier="freshness-limited",
                evidence_summary="IN evidence",
                operational_reason="IN reason",
                next_action="IN next",
                evidence_date=None,
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            ),
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(updated_at=date(2026, 4, 24), rows=[])

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", lambda _path: registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", lambda _path: lifecycle)
    monkeypatch.setattr(keel_gate_l14, "_load_civics_roster_sources", lambda sources_path: [])
    monkeypatch.setattr(keel_gate_l14, "_manifest_member_counts_by_source_id", lambda: {})
    monkeypatch.setattr(keel_gate_l14, "_load_roster_loaded_counts", lambda conn, source_ids: {})

    class _FakeConn:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(keel_gate_l14, "get_connection", lambda: _FakeConn())

    collection = keel_gate_l14.collect_coverage_matrix(
        registry_path=Path("docs/research/coverage-registry.json"),
        lifecycle_path=Path("docs/research/implemented-region-lifecycle.json"),
        nc_geometry_summary=keel_gate_l14.NcGeometrySummary(total_count=209, srid_4326_count=209),
    )

    assert [row.jurisdiction_code for row in collection.rows] == ["NC", "IN"]
    nc_row = collection.rows[0].model_dump(mode="json")
    in_row = collection.rows[1].model_dump(mode="json")

    assert nc_row["nc_geometry_total_count"] == 209
    assert nc_row["nc_geometry_srid_4326_count"] == 209
    assert nc_row["nc_geometry_expected_count"] == 210
    assert nc_row["nc_geometry_counts_match_expected"] is False
    assert keel_gate_l14._evidence_status(collection) == "fail"

    assert in_row["nc_geometry_total_count"] is None
    assert in_row["nc_geometry_srid_4326_count"] is None
    assert in_row["nc_geometry_expected_count"] is None
    assert in_row["nc_geometry_counts_match_expected"] is None


def test_main_returns_non_zero_when_nc_geometry_summary_mismatches(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source_repo_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    (schema_root / "L14.json").write_text(
        (source_repo_root / "evidence_schemas" / "L14.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="NC",
                name="North Carolina",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 20),
                covers_sub_jurisdictions=True,
                source_count=3,
                source_names=["NC Transactions", "NC Committee Documents", "NC IE Index"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="NC evidence",
                operational_reason="NC reason",
                next_action="NC next",
                evidence_date=date(2026, 4, 21),
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            )
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(
        updated_at=date(2026, 4, 24),
        rows=[
            coverage_lifecycle.ImplementedRegionLifecycleRow(
                jurisdiction_code="NC",
                name="North Carolina",
                acquisition_pattern="browser_session_portal",
                discovery_maturity="interactively_proven",
                source_contract_maturity="verified",
                legal_filing_semantics_maturity="substantial",
                implementation_maturity="live_proven",
                operational_maturity="operational",
                public_claim_status="launch-support candidate",
                completeness_intelligence_maturity="observed_only",
                civics_candidacy_status="loaded",
                main_blocker="Statewide contest-universe proof is still narrow.",
            )
        ],
    )

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", lambda path: registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", lambda path: lifecycle)
    monkeypatch.setattr(keel_gate_l14, "_load_civics_roster_sources", lambda sources_path: [])
    monkeypatch.setattr(keel_gate_l14, "_manifest_member_counts_by_source_id", lambda: {})
    monkeypatch.setattr(keel_gate_l14, "_load_roster_loaded_counts", lambda conn, source_ids: {})
    monkeypatch.setattr(
        keel_gate_l14,
        "_collect_nc_geometry_summary",
        lambda: keel_gate_l14.NcGeometrySummary(total_count=209, srid_4326_count=209),
    )
    monkeypatch.setattr(keel_gate_l14, "_repo_sha", lambda repo_root: "6a78078d")
    monkeypatch.setattr(keel_gate_l14, "_utc_now", lambda: datetime(2026, 4, 24, 13, 30, tzinfo=UTC))

    exit_code = keel_gate_l14.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )
    payload = json.loads(
        (repo_root / "evidence" / "L14" / keel_gate_l14.L14_SCOPE / "2026-04-24.json").read_text(encoding="utf-8")
    )
    stdout = capsys.readouterr().out

    assert payload["status"] == "fail"
    assert exit_code == 1
    assert stdout.startswith("FAIL:")


def test_main_writes_l14_evidence_from_registry_lifecycle_projection(tmp_path: Path, monkeypatch) -> None:
    source_repo_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    (schema_root / "L14.json").write_text(
        (source_repo_root / "evidence_schemas" / "L14.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="NC",
                name="North Carolina",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 20),
                covers_sub_jurisdictions=True,
                source_count=3,
                source_names=["NC Transactions", "NC Committee Documents", "NC IE Index"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="NC evidence",
                operational_reason="NC reason",
                next_action="NC next",
                evidence_date=date(2026, 4, 21),
                loaded_count=20,
                expected_count=23,
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            ),
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="IN",
                name="Indiana",
                jurisdiction_type="state",
                best_update_frequency="annual",
                best_last_verified_working=None,
                covers_sub_jurisdictions=True,
                source_count=1,
                source_names=["IN ZIP"],
                runner_wired=True,
                tier="freshness-limited",
                evidence_summary="IN evidence",
                operational_reason="IN reason",
                next_action="IN next",
                evidence_date=None,
                loaded_count=None,
                expected_count=None,
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            ),
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(
        updated_at=date(2026, 4, 24),
        rows=[
            coverage_lifecycle.ImplementedRegionLifecycleRow(
                jurisdiction_code="NC",
                name="North Carolina",
                acquisition_pattern="browser_session_portal",
                discovery_maturity="interactively_proven",
                source_contract_maturity="verified",
                legal_filing_semantics_maturity="substantial",
                implementation_maturity="live_proven",
                operational_maturity="operational",
                public_claim_status="launch-support candidate",
                completeness_intelligence_maturity="observed_only",
                civics_candidacy_status="loaded",
                main_blocker="Statewide contest-universe proof is still narrow.",
            )
        ],
    )

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", lambda path: registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", lambda path: lifecycle)
    monkeypatch.setattr(keel_gate_l14, "_repo_sha", lambda repo_root: "6a78078d")
    monkeypatch.setattr(keel_gate_l14, "_utc_now", lambda: datetime(2026, 4, 24, 13, 30, tzinfo=UTC))
    monkeypatch.setattr(keel_gate_l14, "_load_civics_roster_sources", lambda sources_path: [])
    monkeypatch.setattr(keel_gate_l14, "_manifest_member_counts_by_source_id", lambda: {})
    monkeypatch.setattr(keel_gate_l14, "_load_roster_loaded_counts", lambda conn, source_ids: {})
    monkeypatch.setattr(
        keel_gate_l14,
        "_collect_nc_geometry_summary",
        lambda: keel_gate_l14.NcGeometrySummary(total_count=210, srid_4326_count=210),
    )

    class _FakeConn:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(keel_gate_l14, "get_connection", lambda: _FakeConn())

    exit_code = keel_gate_l14.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )

    evidence_path = repo_root / "evidence" / "L14" / keel_gate_l14.L14_SCOPE / "2026-04-24.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["layer"] == "L14"
    assert payload["scope"] == keel_gate_l14.L14_SCOPE
    assert payload["status"] == "pass"
    assert payload["registry_path"] == "docs/research/coverage-registry.json"
    assert payload["lifecycle_path"] == "docs/research/implemented-region-lifecycle.json"
    assert payload["lifecycle_updated_at"] == "2026-04-24"
    assert [row["jurisdiction_code"] for row in payload["rows"]] == ["NC", "IN"]
    assert "loaded_count" in payload["rows"][0]
    assert "expected_count" in payload["rows"][0]
    assert "loaded_count" in payload["rows"][1]
    assert "expected_count" in payload["rows"][1]
    assert payload["rows"][0]["loaded_count"] == 20
    assert payload["rows"][0]["expected_count"] == 23
    assert payload["rows"][1]["loaded_count"] is None
    assert payload["rows"][1]["expected_count"] is None
    assert payload["rows"][0]["implementation_maturity"] == "live_proven"
    assert payload["rows"][0]["main_blocker"] == "Statewide contest-universe proof is still narrow."
    assert payload["rows"][0]["civics_candidacy_status"] == "loaded"
    assert payload["rows"][0]["nc_geometry_total_count"] == 210
    assert payload["rows"][0]["nc_geometry_srid_4326_count"] == 210
    assert payload["rows"][0]["nc_geometry_expected_count"] == 210
    assert payload["rows"][0]["nc_geometry_counts_match_expected"] is True
    assert payload["rows"][1]["implementation_maturity"] is None
    assert payload["rows"][1]["main_blocker"] is None
    assert payload["rows"][1]["civics_candidacy_status"] is None
    assert payload["rows"][1]["loaded_count"] is None
    assert payload["rows"][1]["expected_count"] is None
    assert payload["rows"][1]["nc_geometry_total_count"] is None
    assert payload["rows"][1]["nc_geometry_srid_4326_count"] is None
    assert payload["rows"][1]["nc_geometry_expected_count"] is None
    assert payload["rows"][1]["nc_geometry_counts_match_expected"] is None

    legacy_payload = json.loads(json.dumps(payload))
    for row in legacy_payload["rows"]:
        row.pop("loaded_count", None)
        row.pop("expected_count", None)
    keel_gate_l14._validate_payload(payload=legacy_payload, schema_path=schema_root / "L14.json")


def test_lifecycle_updated_at_tracks_civics_loaded_status() -> None:
    lifecycle = coverage_lifecycle.load_lifecycle(Path("docs/research/implemented-region-lifecycle.json"))
    has_loaded_civics = any(
        row.civics_candidacy_status in {"loaded", "full_csv_proven"}
        for row in lifecycle.rows
    )
    assert has_loaded_civics
    # Stage 7 set NC civics coverage to loaded on April 30, 2026.
    assert lifecycle.updated_at >= date(2026, 4, 30)


def test_l14_schema_civics_status_nullable_enum_uses_anyof() -> None:
    schema = json.loads(Path("evidence_schemas/L14.json").read_text(encoding="utf-8"))
    civics_status_schema = schema["$defs"]["coverage_row"]["properties"]["civics_candidacy_status"]
    assert civics_status_schema == {
        "anyOf": [
            {
                "type": "string",
                "enum": ["not_started", "loaded", "full_csv_proven"],
            },
            {"type": "null"},
        ]
    }
    assert schema["$defs"]["coverage_row"]["properties"]["nc_geometry_total_count"] == {"type": ["integer", "null"]}
    assert schema["$defs"]["coverage_row"]["properties"]["nc_geometry_counts_match_expected"] == {
        "type": ["boolean", "null"]
    }


def test_main_reads_roster_sources_from_selected_repo_root(tmp_path: Path, monkeypatch) -> None:
    source_repo_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    (schema_root / "L14.json").write_text(
        (source_repo_root / "evidence_schemas" / "L14.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo_root / "sources.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "jurisdictions": [
                    {
                        "scope": "NC",
                        "phase": "Phase 2",
                        "ownership": "project-local pilot registry until matt-side absorption exists",
                        "sources": [
                            {
                                "source_id": "tmp_repo_roster_source",
                                "current_state": "prototyped",
                                "coverage_boundary": "Temp roster source for L14 CLI regression coverage.",
                                "roster_bootstrap": {
                                    "name": "Temp Repo Roster Source",
                                    "source_url": "https://example.org/roster",
                                    "body_key": "nc_municipal_council",
                                },
                                "transitions": [],
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="NC",
                name="North Carolina",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 20),
                covers_sub_jurisdictions=True,
                source_count=1,
                source_names=["NC API"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="NC evidence",
                operational_reason="NC reason",
                next_action="NC next",
                evidence_date=date(2026, 4, 21),
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            )
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(
        updated_at=date(2026, 4, 24),
        rows=[],
    )

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", lambda path: registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", lambda path: lifecycle)
    monkeypatch.setattr(keel_gate_l14, "_repo_sha", lambda repo_root: "6a78078d")
    monkeypatch.setattr(keel_gate_l14, "_utc_now", lambda: datetime(2026, 4, 24, 13, 30, tzinfo=UTC))
    monkeypatch.setattr(
        keel_gate_l14,
        "_manifest_member_counts_by_source_id",
        lambda: {"tmp_repo_roster_source": 6},
    )
    monkeypatch.setattr(
        keel_gate_l14,
        "_collect_nc_geometry_summary",
        lambda: keel_gate_l14.NcGeometrySummary(total_count=210, srid_4326_count=210),
    )

    def _assert_temp_repo_source_ids(conn, source_ids):  # type: ignore[no-untyped-def]
        assert source_ids == ["tmp_repo_roster_source"]
        return {"tmp_repo_roster_source": 4}

    monkeypatch.setattr(keel_gate_l14, "_load_roster_loaded_counts", _assert_temp_repo_source_ids)

    class _FakeConn:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(keel_gate_l14, "get_connection", lambda: _FakeConn())

    exit_code = keel_gate_l14.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )

    evidence_path = repo_root / "evidence" / "L14" / keel_gate_l14.L14_SCOPE / "2026-04-24.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    roster_rows = [row for row in payload["rows"] if row["jurisdiction_type"] == "civics_roster_source"]

    assert exit_code == 0
    assert [row["jurisdiction_code"] for row in roster_rows] == ["tmp_repo_roster_source"]
    assert roster_rows[0]["loaded_count"] == 4
    assert roster_rows[0]["expected_count"] == 6


def test_collect_coverage_matrix_defaults_missing_loaded_count_to_zero(monkeypatch) -> None:
    registry = coverage_registry.CoverageRegistry(
        rows=[
            coverage_registry.CoverageRegistryRow(
                jurisdiction_code="NC",
                name="North Carolina",
                jurisdiction_type="state",
                best_update_frequency="daily",
                best_last_verified_working=date(2026, 4, 1),
                covers_sub_jurisdictions=True,
                source_count=1,
                source_names=["NC API"],
                runner_wired=True,
                tier="launch-support candidate",
                evidence_summary="evidence",
                operational_reason="reason",
                next_action="next",
                evidence_date=date(2026, 4, 2),
                parent_jurisdiction_code=None,
                municipal_audit_decision=None,
                municipal_portal_url=None,
            )
        ]
    )
    lifecycle = coverage_lifecycle.ImplementedRegionLifecycleRegistry(
        updated_at=date(2026, 4, 24),
        rows=[],
    )

    class _FakeConn:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(keel_gate_l14.coverage_registry, "load_registry", lambda path: registry)
    monkeypatch.setattr(keel_gate_l14.coverage_lifecycle, "load_lifecycle", lambda path: lifecycle)
    monkeypatch.setattr(
        keel_gate_l14,
        "_load_civics_roster_sources",
        lambda sources_path: [
            {"source_id": "nc_cary_town_council_roster", "jurisdiction_code": "NC"},
        ],
    )
    monkeypatch.setattr(
        keel_gate_l14,
        "_manifest_member_counts_by_source_id",
        lambda: {
            "nc_cary_town_council_roster": 7,
        },
    )
    monkeypatch.setattr(keel_gate_l14, "_load_roster_loaded_counts", lambda conn, source_ids: {})
    monkeypatch.setattr(keel_gate_l14, "get_connection", lambda: _FakeConn())

    collection = keel_gate_l14.collect_coverage_matrix(
        registry_path=Path("docs/research/coverage-registry.json"),
        lifecycle_path=Path("docs/research/implemented-region-lifecycle.json"),
    )

    roster_rows = [row for row in collection.rows if row.jurisdiction_type == "civics_roster_source"]
    assert len(roster_rows) == 1
    assert roster_rows[0].jurisdiction_code == "nc_cary_town_council_roster"
    assert roster_rows[0].loaded_count == 0
    assert roster_rows[0].expected_count == 7


def test_load_civics_roster_sources_uses_roster_bootstrap_contract(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "jurisdictions": [
                    {
                        "scope": "NC",
                        "phase": "Phase 2",
                        "ownership": "project-local pilot registry until matt-side absorption exists",
                        "sources": [
                            {
                                "source_id": "nc_durham_county_commissioners_roster",
                                "current_state": "prototyped",
                                "coverage_boundary": "Durham County Board of Commissioners roster page.",
                                "roster_bootstrap": {
                                    "name": "Durham County Commissioners Official Roster",
                                    "source_url": "https://www.dconc.gov/Board-of-Commissioners/Commissioners",
                                    "body_key": "nc_county_commissioners",
                                },
                                "transitions": [],
                            },
                            {
                                "source_id": "nc_transactions",
                                "current_state": "validated",
                                "coverage_boundary": "civics/official_roster",
                                "transitions": [],
                            },
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert keel_gate_l14._load_civics_roster_sources(sources_path) == [
        {
            "source_id": "nc_durham_county_commissioners_roster",
            "jurisdiction_code": "NC",
        }
    ]


def test_l14_coverage_row_accepts_legacy_payload_without_count_fields() -> None:
    modern_row = keel_gate_l14.L14CoverageRow(
        jurisdiction_code="NC",
        name="North Carolina",
        jurisdiction_type="state",
        best_update_frequency="daily",
        runner_wired=True,
        tier="launch-support candidate",
        loaded_count=None,
        expected_count=None,
        operational_reason="reason",
        next_action="next",
        evidence_date=date(2026, 4, 24),
        acquisition_pattern="browser_session_portal",
        discovery_maturity="interactively_proven",
        source_contract_maturity="verified",
        legal_filing_semantics_maturity="substantial",
        implementation_maturity="live_proven",
        operational_maturity="operational",
        public_claim_status="launch-support candidate",
        completeness_intelligence_maturity="observed_only",
        civics_candidacy_status=None,
        main_blocker=None,
        nc_geometry_total_count=None,
        nc_geometry_srid_4326_count=None,
        nc_geometry_expected_count=None,
        nc_geometry_counts_match_expected=None,
    )
    legacy_row = modern_row.model_dump(mode="python")
    legacy_row.pop("loaded_count")
    legacy_row.pop("expected_count")

    validated_row = keel_gate_l14.L14CoverageRow.model_validate(legacy_row)
    assert validated_row.loaded_count is None
    assert validated_row.expected_count is None
