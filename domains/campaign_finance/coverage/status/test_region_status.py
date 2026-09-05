"""Red-first tests for the read-only ``region-status`` projection."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from inspect import signature
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest
from pydantic import ValidationError

from core.keel_gate_l3 import JurisdictionEntry, SourceEntry, SourceTransition, SourcesRegistry
from core.refresh import runner
from core.refresh.job_builders import build_refresh_plan
from core.refresh.runner import RefreshJob
from domains.campaign_finance.coverage.lifecycle import (
    AuthorityPromotionReceipt,
    ImplementedRegionLifecycleRegistry,
)
from domains.campaign_finance.coverage.registry import CoverageRegistry, load_registry, write_registry
from domains.campaign_finance.coverage.lifecycle import write_lifecycle
from domains.campaign_finance.coverage.status.models import UNKNOWN, ProjectionReport, Refusal, UnknownFact
from domains.campaign_finance.coverage.status import region_status
from domains.campaign_finance.coverage.status.region_status import (
    RegionStatusProjectionInputs,
    RegionStatusReport,
    build_region_status_report,
    main,
    match_refresh_jobs_for_region,
)
from domains.campaign_finance.coverage.status.test_municipality import _lifecycle_row, _registry_row
from test_support.refresh_run_fixtures import (
    assert_single_in_flight_row,
    delete_refresh_runs_for_job,
    record_terminal_refresh_run,
    refresh_job_for_tests,
)

_REPORT_TIME = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _job(key: str, jurisdiction: str, *, refresh_history_key: str | None = None) -> RefreshJob:
    return refresh_job_for_tests(
        key,
        jurisdiction=jurisdiction,
        data_source_names=(f"{key} source",),
        refresh_history_key=refresh_history_key,
    )


def _sources_registry() -> SourcesRegistry:
    return SourcesRegistry(
        schema_version=1,
        jurisdictions=[
            _sources_entry("CA", [("ca_transactions", "validated", date(2026, 5, 4))]),
            _sources_entry("NC", [("nc_transactions", "validated", date(2026, 4, 24))]),
            _sources_entry(
                "PHL",
                [
                    ("phl_contributions", "validated", date(2026, 5, 1)),
                    ("phl_expenditures", "prototyped", date(2026, 5, 3)),
                ],
            ),
            _sources_entry("FEDERAL", [("fec_bulk", "prototyped", date(2026, 4, 29))]),
        ],
    )


def _sources_entry(scope: str, source_specs: list[tuple[str, str, date]]) -> JurisdictionEntry:
    return JurisdictionEntry(
        scope=scope,
        phase="test",
        ownership="test",
        sources=[
            SourceEntry(
                source_id=source_id,
                current_state=current_state,
                coverage_boundary="test boundary",
                transitions=[
                    SourceTransition(
                        to_state=current_state,
                        recorded_on=recorded_on,
                        rationale="test",
                        evidence_refs=[],
                    )
                ],
            )
            for source_id, current_state, recorded_on in source_specs
        ],
    )


def _registry(*rows: object) -> CoverageRegistry:
    return CoverageRegistry(rows=list(rows))


def _lifecycle(*rows: object) -> ImplementedRegionLifecycleRegistry:
    return ImplementedRegionLifecycleRegistry(updated_at=date(2026, 8, 20), rows=list(rows))


def _payload(report: object) -> dict[str, object]:
    return json.loads(report.model_dump_json())


def _authority_promotion_receipt(
    *,
    source_identities: list[str],
    source_observed_at: datetime,
    recurrence_completed_at: datetime,
) -> AuthorityPromotionReceipt:
    return AuthorityPromotionReceipt.model_validate(
        {
            "schema_version": 1,
            "issued_at": _REPORT_TIME.isoformat(),
            "jurisdiction_code": "WA",
            "geographic_subject": {"kind": "state", "code": "WA"},
            "filing_authority": {"kind": "state", "code": "WA"},
            "authority_relation": "independent",
            "aggregation_disposition": "not_applicable",
            "provenance_scope": "state/WA",
            "promotion_evidence": {
                "authority_identity": "state/WA",
                "authority_relation": "independent",
                "aggregation_disposition": "not_applicable",
                "expected_source_identities": source_identities,
                "source_evidence": [
                    {
                        "source_identity": source_identity,
                        "freshness_status": "fresh",
                        "observed_at": source_observed_at.isoformat(),
                    }
                    for source_identity in source_identities
                ],
                "recurrence_evidence": [
                    {
                        "source_identity": source_identity,
                        "pull_status": "success",
                        "execution_origin": "scheduled",
                        "completed_at": recurrence_completed_at.isoformat(),
                    }
                    for source_identity in source_identities
                ],
                "provenance_source_identities": source_identities,
                "keel_source_identities": source_identities,
                "deployed_source_identities": source_identities,
                "source_revision": "a" * 40,
                "api_revision": "a" * 40,
                "web_revision": "a" * 40,
            },
            "canonical_evidence": [
                {"kind": kind, "path": f"/{kind}.json", "sha256": "a" * 64}
                for kind in (
                    "canary_ledger",
                    "scheduled_recurrence",
                    "filing_authority",
                    "provenance",
                    "keel",
                    "serving_deploy",
                    "surface_parity",
                )
            ],
        }
    )


def test_match_refresh_jobs_for_region_owns_runner_namespace_translation() -> None:
    jobs = [
        _job("state-ca", "state/CA"),
        _job("state-nc", "state/NC"),
        _job("civics-nc", "states/NC"),
        _job("city-la", "municipality/LA"),
        _job("state-la", "state/LA"),
        _job("sf-contributions", "municipality/SF"),
        _job("federal-a", "federal/fec"),
        _job("federal-b", "federal/irs-527"),
        _job("other", "municipality/PHL"),
    ]

    assert [job.key for job in match_refresh_jobs_for_region("state", "CA", jobs)] == ["state-ca"]
    assert [job.key for job in match_refresh_jobs_for_region("state", "NC", jobs)] == ["state-nc"]
    assert [job.key for job in match_refresh_jobs_for_region("state", "LA", jobs)] == ["state-la"]
    assert [job.key for job in match_refresh_jobs_for_region("municipality", "CA_LOS_ANGELES", jobs)] == ["city-la"]
    assert [job.key for job in match_refresh_jobs_for_region("municipality", "CA_SAN_FRANCISCO", jobs)] == [
        "sf-contributions"
    ]
    assert [job.key for job in match_refresh_jobs_for_region("federal", "FEC", jobs)] == [
        "federal-a",
        "federal-b",
    ]
    assert match_refresh_jobs_for_region("state", "AK", jobs) == []


def test_region_status_builder_stays_within_parameter_count_standard() -> None:
    assert len(signature(build_region_status_report).parameters) <= 6


def test_region_status_cli_accepts_exact_promotion_receipt_path_from_shared_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = "/absolute/evidence/authority-promotion-receipt.json"
    monkeypatch.setenv("CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON", receipt_path)

    args = region_status._build_argument_parser().parse_args(["--region", "WA"])

    assert args.promotion_receipt_json == Path(receipt_path)
    assert os.environ["CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON"] == receipt_path


def test_region_status_report_rejects_nested_refusal_outcomes() -> None:
    report = build_region_status_report(
        jurisdiction_code="CA",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("CA", "California", runner_wired=False)),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA", "California")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )
    payload = report.model_dump()
    payload["l3_source_state"] = [
        Refusal(scope="CA", reason="invalid nested refusal", canonical_owner="test").model_dump()
    ]

    with pytest.raises(ValidationError):
        RegionStatusReport.model_validate(payload)


def test_live_refresh_plan_agrees_with_committed_registry_runner_wiring_for_key_regions() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    registry = load_registry(repo_root / "docs" / "reference" / "research" / "coverage-registry.json")
    jobs = build_refresh_plan()
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}

    for code in ("CA", "PA_PHILADELPHIA", "FEC"):
        row = rows_by_code[code]
        assert row.runner_wired is bool(match_refresh_jobs_for_region(row.jurisdiction_type, code, jobs))

    covered_child = rows_by_code["CA_ANAHEIM"]
    assert covered_child.parent_jurisdiction_code == "CA"
    assert covered_child.runner_wired is bool(
        match_refresh_jobs_for_region("state", covered_child.parent_jurisdiction_code, jobs)
    )


def test_region_status_refuses_runner_wired_plan_mismatch() -> None:
    direct_report = build_region_status_report(
        jurisdiction_code="CA",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("CA", "California", runner_wired=True)),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA", "California")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )
    inherited_report = build_region_status_report(
        jurisdiction_code="CA_SAN_FRANCISCO",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row("CA", "California", runner_wired=True),
                _registry_row(
                    "CA_SAN_FRANCISCO",
                    "San Francisco",
                    jurisdiction_type="municipality",
                    municipal_audit_decision="covered_by_parent",
                    parent_jurisdiction_code="CA",
                    runner_wired=False,
                ),
            ),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA", "California")),
            sources_registry=_sources_registry(),
            refresh_jobs=[_job("state-ca-refresh", "state/CA")],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    assert direct_report == Refusal(
        scope="CA",
        reason="coverage-registry runner_wired=True disagrees with RefreshJob plan match=False for 'CA'",
        canonical_owner="core/refresh/job_builders.py::build_refresh_plan",
    )
    assert inherited_report == Refusal(
        scope="CA_SAN_FRANCISCO",
        reason=(
            "coverage-registry runner_wired=False disagrees with RefreshJob plan match=True for 'CA_SAN_FRANCISCO'"
        ),
        canonical_owner="core/refresh/job_builders.py::build_refresh_plan",
    )


def test_region_status_projects_every_spec_field_with_per_job_clocks() -> None:
    ca_job = _job("state-ca-refresh", "state/CA", refresh_history_key="state-ca-history")
    completed_at = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    cadence_at = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

    report = build_region_status_report(
        jurisdiction_code="CA",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row(
                    "CA",
                    "California",
                    tier="launch-support candidate",
                    evidence_summary="statewide source verified",
                    next_action="keep monitoring",
                    evidence_date=date(2026, 8, 1),
                    runner_wired=True,
                )
            ),
            lifecycle_registry=_lifecycle(
                _lifecycle_row(
                    "CA",
                    "California",
                    acquisition_pattern="bulk_api",
                    public_claim_status="launch-support candidate",
                    main_blocker="none",
                )
            ),
            sources_registry=_sources_registry(),
            refresh_jobs=[ca_job],
            latest_completed_run_lookup=lambda job: {
                "completed_at": completed_at,
                "pull_status": "crashed",
                "inserted_count": 0,
                "error": "boom",
            },
            cadence_last_pull_lookup=lambda job: cadence_at,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["status"] == "region"
    assert payload["jurisdiction_code"]["value"] == "CA"
    assert payload["name"]["value"] == "California"
    assert payload["municipality_disposition"]["value"] == "not_applicable"
    assert payload["acquisition_pattern"]["value"] == "bulk_api"
    assert payload["source_maturity"]["value"] == {
        "discovery_maturity": "researched",
        "source_contract_maturity": "encoded",
        "legal_filing_semantics_maturity": "partial",
        "implementation_maturity": "fixture_tested",
        "operational_maturity": "manual_only",
        "completeness_intelligence_maturity": "not_started",
        "civics_candidacy_status": "not_started",
    }
    assert payload["l3_source_state"][0]["value"] == {
        "source_id": "ca_transactions",
        "current_state": "validated",
    }
    assert payload["public_claim"]["value"] == {
        "tier": "launch-support candidate",
        "evidence_summary": "statewide source verified",
    }
    assert payload["authority_relation"]["value"]["relation"] == "unresolved"
    authority_health = payload["authority_health"][0]["value"]
    assert authority_health["authority_identity"] == "state/CA"
    assert authority_health["expected_source_identities"] == ["state/CA:state-ca-refresh source"]
    assert authority_health["freshness_status"] == "degraded"
    assert authority_health["degraded_source_identities"] == ["state/CA:state-ca-refresh source"]
    assert authority_health["recurrence_status"] == "degraded"
    assert authority_health["recurrence_observed_at"] == "2026-08-21T12:00:00Z"
    assert authority_health["revision_parity"] == "unknown"
    assert authority_health["promotion_eligible"] is False
    assert "The filing authority relation is unresolved." in authority_health["refusal_reasons"]
    assert "Serving source/API/web revision parity is unknown." in authority_health["refusal_reasons"]
    assert payload["municipality_audit_claim"]["value"] is None
    assert payload["runner_wired"]["value"] is True
    assert payload["latest_operational_proof"][0]["value"] == {
        "job_key": "state-ca-refresh",
        "completed_at": "2026-08-21T12:00:00Z",
        "pull_status": "crashed",
        "inserted_count": 0,
        "error": "boom",
    }
    assert payload["cadence_clock_owner"][0]["value"] == {
        "job_key": "state-ca-refresh",
        "cadence_clock_owner": "refresh_history",
    }
    assert payload["cadence_clock_owner"][0]["owner"] == "core/refresh/runner.py::cadence_last_pull_owner"
    assert payload["cadence_last_pull_at"][0]["value"] == {
        "job_key": "state-ca-refresh",
        "cadence_last_pull_at": "2026-08-20T12:00:00Z",
    }
    assert payload["cadence_last_pull_at"][0]["owner"] == "core.refresh_run"
    assert payload["proof_age"][0]["value"] == {"job_key": "state-ca-refresh", "proof_age": "P1D"}
    assert payload["execution_origin"] == {"status": "unknown", "reason": "no canonical owner records execution origin"}
    assert payload["main_blocker"]["value"] == "none"
    assert payload["next_action"]["value"] == "keep monitoring"


def test_region_status_uses_exact_promotion_receipt_without_changing_geographic_aggregation() -> None:
    job = _job("state-wa-refresh", "state/WA")
    completed_at = _REPORT_TIME - timedelta(hours=1)
    source_identity = "state/WA:state-wa-refresh source"
    receipt = _authority_promotion_receipt(
        source_identities=[source_identity],
        source_observed_at=completed_at,
        recurrence_completed_at=completed_at,
    )
    report = build_region_status_report(
        jurisdiction_code="WA",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("WA", "Washington", runner_wired=True)),
            lifecycle_registry=_lifecycle(_lifecycle_row("WA", "Washington")),
            sources_registry=_sources_registry(),
            refresh_jobs=[job],
            latest_completed_run_lookup=lambda _job: {
                "completed_at": completed_at,
                "pull_status": "success",
                "inserted_count": 1,
                "error": None,
                "execution_origin": "scheduled",
            },
            cadence_last_pull_lookup=lambda _job: completed_at,
            promotion_receipt=receipt,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["jurisdiction_code"]["value"] == "WA"
    assert payload["authority_relation"]["value"]["relation"] == "independent"
    assert payload["authority_relation"]["value"]["authority"]["code"] == "WA"
    assert payload["authority_relation"]["owner"] == "authority-promotion-receipt"
    authority_health = payload["authority_health"][0]["value"]
    assert authority_health["authority_identity"] == "state/WA"
    assert authority_health["expected_source_identities"] == [source_identity]
    assert authority_health["source_revision"] == "a" * 40
    assert authority_health["revision_parity"] == "match"
    assert authority_health["promotion_eligible"] is True
    assert authority_health["refusal_reasons"] == []
    assert payload["municipality_disposition"]["value"] == "not_applicable"


def test_region_status_exposes_each_overlap_authority_and_refuses_unproved_sources() -> None:
    relation = {
        "relation": "partitioned_overlapping",
        "authorities": [
            {"kind": "state", "code": "CA"},
            {"kind": "municipality", "code": "CA_EXAMPLE"},
        ],
        "precedence": [
            {"authority": {"kind": "state", "code": "CA"}, "scope": "state scope"},
            {
                "authority": {"kind": "municipality", "code": "CA_EXAMPLE"},
                "scope": "city scope",
            },
        ],
        "partitions": [
            {"authority": {"kind": "state", "code": "CA"}, "scope": "state scope"},
            {
                "authority": {"kind": "municipality", "code": "CA_EXAMPLE"},
                "scope": "city scope",
            },
        ],
        "provenance": [
            {"authority": {"kind": "state", "code": "CA"}, "source_scope": "state source"},
            {
                "authority": {"kind": "municipality", "code": "CA_EXAMPLE"},
                "source_scope": "city source",
            },
        ],
        "deduplication": {"disposition": "refuse_combination", "identity_keys": []},
        "refusals": ["No combined total."],
        "evidence": {
            "owner": "test",
            "receipt": "test receipt",
            "receipt_sha256": "a" * 64,
        },
    }
    report = build_region_status_report(
        jurisdiction_code="CA_EXAMPLE",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row("CA", "California", runner_wired=False),
                _registry_row(
                    "CA_EXAMPLE",
                    "Example City",
                    jurisdiction_type="municipality",
                    municipal_audit_decision="independent_target",
                    parent_jurisdiction_code="CA",
                    runner_wired=False,
                    authority_relation=relation,
                ),
            ),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA_EXAMPLE", "Example City")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["authority_relation"]["value"]["relation"] == "partitioned_overlapping"
    health = [entry["value"] for entry in payload["authority_health"]]
    assert [entry["authority_identity"] for entry in health] == [
        "state/CA",
        "municipality/CA_EXAMPLE",
    ]
    assert {entry["freshness_status"] for entry in health} == {"unknown"}
    assert {entry["recurrence_status"] for entry in health} == {"unknown"}
    assert all(entry["revision_parity"] == "unknown" for entry in health)
    assert all(entry["promotion_eligible"] is False for entry in health)
    assert all(
        "No exact source identities are assigned to this filing authority." in entry["refusal_reasons"]
        for entry in health
    )
    assert all(
        "The authority overlap disposition refuses combined promotion." in entry["refusal_reasons"] for entry in health
    )


def test_region_status_l3_scope_join_uses_sources_namespace() -> None:
    phl_job = _job("phl-contributions", "municipality/PHL")

    report = build_region_status_report(
        jurisdiction_code="PA_PHILADELPHIA",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row(
                    "PA",
                    "Pennsylvania",
                    runner_wired=False,
                ),
                _registry_row(
                    "PA_PHILADELPHIA",
                    "Philadelphia",
                    jurisdiction_type="municipality",
                    municipal_audit_decision="independent_target",
                    parent_jurisdiction_code="PA",
                    runner_wired=True,
                ),
            ),
            lifecycle_registry=_lifecycle(_lifecycle_row("PA_PHILADELPHIA", "Philadelphia")),
            sources_registry=_sources_registry(),
            refresh_jobs=[phl_job],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert [entry["value"]["source_id"] for entry in payload["l3_source_state"]] == [
        "phl_contributions",
        "phl_expenditures",
    ]
    assert [entry["source_observed_at"] for entry in payload["l3_source_state"]] == ["2026-05-01", "2026-05-03"]


def test_region_status_cadence_provenance_follows_data_source_branch() -> None:
    job = _job("state-ca-refresh", "state/CA")
    cadence_at = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    report = build_region_status_report(
        jurisdiction_code="CA",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("CA", "California", runner_wired=True)),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA", "California")),
            sources_registry=_sources_registry(),
            refresh_jobs=[job],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: cadence_at,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["cadence_clock_owner"][0]["value"]["cadence_clock_owner"] == "data_source"
    assert payload["cadence_last_pull_at"][0]["owner"] == "core.data_source"


def test_region_status_marks_parent_lifecycle_fields_as_inherited() -> None:
    parent_job = _job("state-ca-refresh", "state/CA")
    report = build_region_status_report(
        jurisdiction_code="CA_SAN_FRANCISCO",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row("CA", "California", runner_wired=True),
                _registry_row(
                    "CA_SAN_FRANCISCO",
                    "San Francisco",
                    jurisdiction_type="municipality",
                    municipal_audit_decision="covered_by_parent",
                    parent_jurisdiction_code="CA",
                    runner_wired=True,
                ),
            ),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA", "California", main_blocker="parent blocker")),
            sources_registry=_sources_registry(),
            refresh_jobs=[parent_job],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["acquisition_pattern"]["origin"] == "inherited"
    assert payload["source_maturity"]["origin"] == "inherited"
    assert payload["main_blocker"]["origin"] == "inherited"
    assert payload["public_claim"]["origin"] == "inherited"
    assert payload["name"]["origin"] == "direct"
    assert payload["runner_wired"]["value"] is True
    assert payload["cadence_clock_owner"][0]["value"] == {
        "job_key": "state-ca-refresh",
        "cadence_clock_owner": "data_source",
    }


def test_region_status_surfaces_inherited_owner_refusals_unchanged() -> None:
    result = build_region_status_report(
        jurisdiction_code="AZ_PHOENIX",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("AZ_PHOENIX", "Phoenix", runner_wired=False)),
            lifecycle_registry=_lifecycle(),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    assert result == Refusal(
        scope="AZ_PHOENIX",
        reason="no implemented-region-lifecycle row for 'AZ_PHOENIX'",
        canonical_owner="implemented-region-lifecycle",
    )


def test_region_status_refuses_unknown_jurisdiction_and_unresolvable_parent() -> None:
    unknown = build_region_status_report(
        jurisdiction_code="ZZ",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("CA", "California")),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA", "California")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )
    parent_missing = build_region_status_report(
        jurisdiction_code="CA_SAN_FRANCISCO",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row(
                    "CA_SAN_FRANCISCO",
                    "San Francisco",
                    jurisdiction_type="municipality",
                    municipal_audit_decision="covered_by_parent",
                    parent_jurisdiction_code="CA",
                    runner_wired=False,
                )
            ),
            lifecycle_registry=_lifecycle(_lifecycle_row("CA_SAN_FRANCISCO", "San Francisco")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    assert unknown == Refusal(
        scope="ZZ",
        reason="no coverage-registry row for 'ZZ'",
        canonical_owner="coverage-registry",
    )
    assert parent_missing == Refusal(
        scope="CA_SAN_FRANCISCO",
        reason="municipality 'CA_SAN_FRANCISCO' has no coverage-registry parent 'CA'",
        canonical_owner="coverage-registry",
    )


def test_region_status_optional_inputs_become_unknown_not_refusals() -> None:
    job = _job("state-ak-refresh", "state/AK")

    report = build_region_status_report(
        jurisdiction_code="AK",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("AK", "Alaska", runner_wired=True)),
            lifecycle_registry=_lifecycle(_lifecycle_row("AK", "Alaska")),
            sources_registry=_sources_registry(),
            refresh_jobs=[job],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["l3_source_state"] == [{"status": "unknown", "reason": "sources.yaml has no scope for AK"}]
    assert payload["latest_operational_proof"] == [
        {"status": "unknown", "reason": "core.refresh_run has no completed attempt for state-ak-refresh"}
    ]
    assert payload["cadence_last_pull_at"] == [
        {"status": "unknown", "reason": "cadence clock returned no row for state-ak-refresh"}
    ]
    assert payload["execution_origin"]["status"] == UNKNOWN.lower()


def test_region_status_zero_matched_jobs_projects_runner_wired_false() -> None:
    report = build_region_status_report(
        jurisdiction_code="AK",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("AK", "Alaska", runner_wired=False)),
            lifecycle_registry=_lifecycle(_lifecycle_row("AK", "Alaska")),
            sources_registry=_sources_registry(),
            refresh_jobs=[_job("state-ca", "state/CA")],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert payload["runner_wired"]["value"] is False
    assert payload["latest_operational_proof"] == []
    assert payload["cadence_clock_owner"] == []
    assert payload["cadence_last_pull_at"] == []
    assert payload["proof_age"] == []


def test_region_status_multi_job_unavailable_clocks_keep_job_identity() -> None:
    jobs = [_job("nc-current", "state/NC"), _job("nc-past-results", "state/NC")]
    unavailable = UnknownFact(reason="refresh clock database unavailable")

    report = build_region_status_report(
        jurisdiction_code="NC",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("NC", "North Carolina", runner_wired=True)),
            lifecycle_registry=_lifecycle(_lifecycle_row("NC", "North Carolina")),
            sources_registry=_sources_registry(),
            refresh_jobs=jobs,
            latest_completed_run_lookup=lambda job: unavailable,
            cadence_last_pull_lookup=lambda job: unavailable,
        ),
        calculated_at=_REPORT_TIME,
    )

    payload = _payload(report)
    assert [entry["reason"] for entry in payload["latest_operational_proof"]] == [
        "nc-current: refresh clock database unavailable",
        "nc-past-results: refresh clock database unavailable",
    ]
    assert [entry["reason"] for entry in payload["cadence_last_pull_at"]] == [
        "nc-current: refresh clock database unavailable",
        "nc-past-results: refresh clock database unavailable",
    ]
    assert [entry["reason"] for entry in payload["proof_age"]] == [
        "nc-current: refresh clock database unavailable",
        "nc-past-results: refresh clock database unavailable",
    ]


def test_region_status_l3_scope_join_resolves_direct_and_federal_scopes() -> None:
    nc = build_region_status_report(
        jurisdiction_code="NC",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("NC", "North Carolina", runner_wired=False)),
            lifecycle_registry=_lifecycle(_lifecycle_row("NC", "North Carolina")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )
    fec = build_region_status_report(
        jurisdiction_code="FEC",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(
                _registry_row("FEC", "Federal", jurisdiction_type="federal", runner_wired=True)
            ),
            lifecycle_registry=_lifecycle(_lifecycle_row("FEC", "Federal")),
            sources_registry=_sources_registry(),
            refresh_jobs=[_job("federal-a", "federal/fec")],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )
    absent = build_region_status_report(
        jurisdiction_code="AK",
        inputs=RegionStatusProjectionInputs(
            coverage_registry=_registry(_registry_row("AK", "Alaska", runner_wired=False)),
            lifecycle_registry=_lifecycle(_lifecycle_row("AK", "Alaska")),
            sources_registry=_sources_registry(),
            refresh_jobs=[],
            latest_completed_run_lookup=lambda job: None,
            cadence_last_pull_lookup=lambda job: None,
        ),
        calculated_at=_REPORT_TIME,
    )

    assert [entry["value"]["source_id"] for entry in _payload(nc)["l3_source_state"]] == ["nc_transactions"]
    assert [entry["value"]["source_id"] for entry in _payload(fec)["l3_source_state"]] == ["fec_bulk"]
    assert _payload(absent)["l3_source_state"] == [{"status": "unknown", "reason": "sources.yaml has no scope for AK"}]


def test_region_status_cli_prints_report_and_refusal_with_fixture_paths(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    registry_path = write_registry(
        tmp_path / "registry.json", _registry(_registry_row("CA", "California", runner_wired=False))
    )
    lifecycle_path = write_lifecycle(tmp_path / "lifecycle.json", _lifecycle(_lifecycle_row("CA", "California")))
    sources_path = _write_sources_yaml(tmp_path)
    monkeypatch.setattr(region_status, "build_refresh_plan", lambda: [])
    monkeypatch.setattr(region_status, "get_connection", MagicMock())

    assert (
        main(
            [
                "--region",
                "CA",
                "--registry-path",
                str(registry_path),
                "--lifecycle-path",
                str(lifecycle_path),
                "--sources-path",
                str(sources_path),
            ]
        )
        == 0
    )
    stdout = capsys.readouterr().out
    assert stdout.count('"status": "region"') == 1
    assert json.loads(stdout)["jurisdiction_code"]["value"] == "CA"

    assert (
        main(
            [
                "--region",
                "ZZ",
                "--registry-path",
                str(registry_path),
                "--lifecycle-path",
                str(lifecycle_path),
                "--sources-path",
                str(sources_path),
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "refuse"


def test_region_status_cli_unreadable_owner_fails_and_unreachable_db_is_unknown(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    registry_path = write_registry(
        tmp_path / "registry.json", _registry(_registry_row("CA", "California", runner_wired=True))
    )
    lifecycle_path = write_lifecycle(tmp_path / "lifecycle.json", _lifecycle(_lifecycle_row("CA", "California")))
    sources_path = _write_sources_yaml(tmp_path)
    job = _job("state-ca-refresh", "state/CA")
    monkeypatch.setattr(region_status, "build_refresh_plan", lambda: [job])
    monkeypatch.setattr(region_status, "get_connection", MagicMock(side_effect=RuntimeError("unreachable db")))

    assert (
        main(
            [
                "--region",
                "CA",
                "--registry-path",
                str(tmp_path / "missing.json"),
                "--lifecycle-path",
                str(lifecycle_path),
                "--sources-path",
                str(sources_path),
            ]
        )
        == 1
    )
    assert capsys.readouterr().err.startswith("FAIL:")

    assert (
        main(
            [
                "--region",
                "CA",
                "--registry-path",
                str(registry_path),
                "--lifecycle-path",
                str(lifecycle_path),
                "--sources-path",
                str(sources_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["latest_operational_proof"][0]["status"] == "unknown"
    assert payload["latest_operational_proof"][0]["reason"] == "state-ca-refresh: refresh clock database unavailable"
    assert payload["cadence_last_pull_at"][0]["status"] == "unknown"
    assert payload["cadence_last_pull_at"][0]["reason"] == "state-ca-refresh: refresh clock database unavailable"


def test_region_status_cli_unreadable_lifecycle_path_fails(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    registry_path = write_registry(
        tmp_path / "registry.json", _registry(_registry_row("CA", "California", runner_wired=False))
    )
    sources_path = _write_sources_yaml(tmp_path)
    monkeypatch.setattr(region_status, "build_refresh_plan", lambda: [])
    monkeypatch.setattr(region_status, "get_connection", MagicMock())

    assert (
        main(
            [
                "--region",
                "CA",
                "--registry-path",
                str(registry_path),
                "--lifecycle-path",
                str(tmp_path / "missing_lifecycle.json"),
                "--sources-path",
                str(sources_path),
            ]
        )
        == 1
    )
    assert capsys.readouterr().err.startswith("FAIL:")


def test_region_status_cli_unreadable_optional_sources_registry_is_unknown(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    registry_path = write_registry(
        tmp_path / "registry.json", _registry(_registry_row("CA", "California", runner_wired=False))
    )
    lifecycle_path = write_lifecycle(tmp_path / "lifecycle.json", _lifecycle(_lifecycle_row("CA", "California")))
    monkeypatch.setattr(region_status, "build_refresh_plan", lambda: [])
    monkeypatch.setattr(region_status, "get_connection", MagicMock(side_effect=RuntimeError("unreachable db")))

    assert (
        main(
            [
                "--region",
                "CA",
                "--registry-path",
                str(registry_path),
                "--lifecycle-path",
                str(lifecycle_path),
                "--sources-path",
                str(tmp_path / "missing.yaml"),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["l3_source_state"] == [{"status": "unknown", "reason": "sources.yaml unavailable"}]

    malformed_sources_path = tmp_path / "malformed.yaml"
    malformed_sources_path.write_text("jurisdictions: [", encoding="utf-8")
    assert (
        main(
            [
                "--region",
                "CA",
                "--registry-path",
                str(registry_path),
                "--lifecycle-path",
                str(lifecycle_path),
                "--sources-path",
                str(malformed_sources_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["l3_source_state"] == [
        {"status": "unknown", "reason": "sources.yaml unavailable"}
    ]


def _write_sources_yaml(tmp_path: Path) -> Path:
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(
        """
schema_version: 1
jurisdictions:
- scope: CA
  phase: test
  ownership: test
  sources:
  - source_id: ca_transactions
    current_state: validated
    coverage_boundary: test
    transitions:
    - to_state: validated
      recorded_on: 2026-05-04
      rationale: test
      evidence_refs: []
""".lstrip(),
        encoding="utf-8",
    )
    return sources_path


@pytest.mark.integration
def test_projection_clock_selectors_ignore_an_in_flight_running_row(
    db_conn: psycopg.Connection,
) -> None:
    # _safe_latest_completed_run / _safe_cadence_last_pull_at are the projection layer's
    # only path to core.refresh_run. A committed running row for the same job_key must not
    # move the terminal attempt they return, nor the source_observed_at / proof_age the
    # projection helpers derive from it.
    job_key = "region-status-in-flight-job"
    job = _job(job_key, "state/CO", refresh_history_key=job_key)
    terminal_at = datetime(2099, 5, 1, 12, 0, tzinfo=timezone.utc)
    report = ProjectionReport(calculated_at=_REPORT_TIME)

    try:
        # Pre-clear as well as clean up: a killed run's leaked rows would otherwise wedge
        # the vacuity guard below permanently red.
        delete_refresh_runs_for_job(db_conn, job_key)
        record_terminal_refresh_run(
            db_conn,
            job,
            pull_status="success",
            completed_at=terminal_at,
            counts={"inserted": 42, "skipped": 0, "quarantined": 0, "superseded": 0, "errors": 0},
        )
        db_conn.commit()

        latest_before = region_status._safe_latest_completed_run(db_conn, job)
        cadence_before = region_status._safe_cadence_last_pull_at(db_conn, job)
        proof_before = region_status._project_latest_operational_proof(report, job, latest_before)
        age_before = region_status._project_proof_age(report, job, latest_before)

        runner._start_refresh_run(db_conn, job, started_at=terminal_at + timedelta(days=1))
        # Vacuity guard: the running row is committed before the second read.
        assert_single_in_flight_row(db_conn, job_key)

        latest_after = region_status._safe_latest_completed_run(db_conn, job)
        cadence_after = region_status._safe_cadence_last_pull_at(db_conn, job)
        proof_after = region_status._project_latest_operational_proof(report, job, latest_after)
        age_after = region_status._project_proof_age(report, job, latest_after)

        assert latest_before == {
            "completed_at": terminal_at,
            "pull_status": "success",
            "execution_origin": "legacy_unknown",
            "inserted_count": 42,
            "skipped_count": 0,
            "quarantined_count": 0,
            "superseded_count": 0,
            "error_count": 0,
            "error": None,
        }
        assert cadence_before == terminal_at
        # The running row leaves both clock selectors — and every projection derived from
        # them — byte-identical.
        assert latest_after == latest_before
        assert cadence_after == cadence_before
        assert proof_after.source_observed_at == proof_before.source_observed_at == terminal_at
        assert age_after.model_dump(mode="json") == age_before.model_dump(mode="json")
    finally:
        delete_refresh_runs_for_job(db_conn, job_key)
