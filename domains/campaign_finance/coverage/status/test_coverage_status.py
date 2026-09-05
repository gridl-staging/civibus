"""Red-first tests for the read-only ``coverage-status`` portfolio view.

Every expected owner, read path, origin, observation time, and age below is written as a
literal so the test pins the published contract rather than restating the implementation.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from domains.campaign_finance.coverage.lifecycle import (
    ImplementedRegionLifecycleRegistry,
    ImplementedRegionLifecycleRow,
    write_lifecycle,
)
from domains.campaign_finance.coverage.registry import CoverageRegistry, CoverageRegistryRow, write_registry
from domains.campaign_finance.coverage.status import coverage_status
from domains.campaign_finance.coverage.status.coverage_status import (
    CoverageStatusRegion,
    CoverageStatusReport,
    build_coverage_status_report,
    main,
)
from domains.campaign_finance.coverage.status.models import ProjectedField, Refusal
from domains.campaign_finance.coverage.status.test_municipality import _lifecycle_row, _registry_row

_REPORT_TIME = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
_LIFECYCLE_UPDATED_AT = date(2026, 8, 20)

_REGISTRY_OWNER = "coverage-registry"
_REGISTRY_READ_PATH = "registry.py::CoverageRegistryRow"
_LIFECYCLE_OWNER = "implemented-region-lifecycle"
_LIFECYCLE_READ_PATH = "lifecycle.py::ImplementedRegionLifecycleRegistry"
_MEMBERSHIP_OWNER = "derive_implemented_jurisdiction_codes"
_MEMBERSHIP_READ_PATH = "render_summary.py::derive_implemented_jurisdiction_codes"
_EVIDENCE_DATE_ABSENT = "coverage-registry evidence_date absent"


# --- expected-envelope builders ------------------------------------------------


def _field(
    value: object,
    *,
    owner: str,
    read_path: str,
    origin: str,
    observed: str,
    age: str,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "status": "value",
        "value": value,
        "owner": owner,
        "read_path": read_path,
        "origin": origin,
        "execution_origin": "UNKNOWN",
        "source_observed_at": observed,
        "age": age,
        "observation_unknown_reason": reason,
    }


def _registry_field(value: object, *, origin: str, observed: str, age: str, reason: str | None = None) -> dict:
    return _field(
        value,
        owner=_REGISTRY_OWNER,
        read_path=_REGISTRY_READ_PATH,
        origin=origin,
        observed=observed,
        age=age,
        reason=reason,
    )


def _structural_registry_field(value: object, *, origin: str = "direct") -> dict:
    return _registry_field(value, origin=origin, observed="not_applicable", age="not_applicable")


def _membership_field(value: object) -> dict:
    return _field(
        value,
        owner=_MEMBERSHIP_OWNER,
        read_path=_MEMBERSHIP_READ_PATH,
        origin="direct",
        observed="not_applicable",
        age="not_applicable",
    )


def _unknown(reason: str) -> dict[str, object]:
    return {"status": "unknown", "reason": reason}


# --- fixture portfolio ---------------------------------------------------------


def _california() -> CoverageRegistryRow:
    return _registry_row(
        "CA",
        "California",
        tier="launch-support candidate",
        evidence_date=date(2026, 7, 1),
    )


def _los_angeles() -> CoverageRegistryRow:
    return _registry_row(
        "CA_LOS_ANGELES",
        "Los Angeles",
        jurisdiction_type="municipality",
        municipal_audit_decision="independent_target",
        parent_jurisdiction_code="CA",
        tier="freshness-limited",
        evidence_summary="city portal verified",
        evidence_date=date(2026, 8, 1),
    )


def _san_francisco() -> CoverageRegistryRow:
    return _registry_row(
        "CA_SAN_FRANCISCO",
        "San Francisco",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="CA",
        tier="deferred/blocked",
        evidence_summary="child audit note",
        next_action="child next action",
        evidence_date=date(2026, 6, 15),
    )


def _new_york() -> CoverageRegistryRow:
    return _registry_row("NY", "New York", tier="implemented but unproven", evidence_date=None)


def _new_york_city() -> CoverageRegistryRow:
    return _registry_row(
        "NY_NEW_YORK",
        "New York City",
        jurisdiction_type="municipality",
        municipal_audit_decision="covered_by_parent",
        parent_jurisdiction_code="NY",
        tier="freshness-limited",
        evidence_summary="child audit pending",
        evidence_date=None,
    )


_PORTFOLIO_MEMBERSHIP = frozenset({"CA", "CA_LOS_ANGELES", "CA_SAN_FRANCISCO"})


def _portfolio_registry_rows() -> list[CoverageRegistryRow]:
    return [_california(), _los_angeles(), _san_francisco(), _new_york(), _new_york_city()]


def _portfolio_lifecycle_rows() -> list[ImplementedRegionLifecycleRow]:
    return [
        _lifecycle_row("CA", "California"),
        _lifecycle_row("CA_LOS_ANGELES", "Los Angeles", public_claim_status="freshness-limited"),
        # Duplicate-only child row for a covered_by_parent member: child identity, parent's
        # inherited lifecycle values.
        _lifecycle_row("CA_SAN_FRANCISCO", "San Francisco"),
    ]


def _build_report(
    *,
    registry_rows: list[CoverageRegistryRow],
    lifecycle_rows: list[ImplementedRegionLifecycleRow],
    membership: frozenset[str],
) -> CoverageStatusReport:
    return build_coverage_status_report(
        coverage_registry=CoverageRegistry(rows=registry_rows),
        lifecycle_registry=ImplementedRegionLifecycleRegistry(updated_at=_LIFECYCLE_UPDATED_AT, rows=lifecycle_rows),
        implemented_membership=set(membership),
        calculated_at=_REPORT_TIME,
    )


def _portfolio_report() -> CoverageStatusReport:
    return _build_report(
        registry_rows=_portfolio_registry_rows(),
        lifecycle_rows=_portfolio_lifecycle_rows(),
        membership=_PORTFOLIO_MEMBERSHIP,
    )


def _payload(report: CoverageStatusReport) -> dict:
    return json.loads(report.model_dump_json())


def _region_payload(report: CoverageStatusReport, jurisdiction_code: str) -> dict:
    matches = [
        region
        for region in _payload(report)["regions"]
        if region.get("jurisdiction_code", {}).get("value") == jurisdiction_code
    ]
    assert len(matches) == 1, f"expected exactly one region row for {jurisdiction_code}"
    return matches[0]


# --- report envelope -----------------------------------------------------------


def test_report_pins_membership_snapshot_and_deterministic_region_order() -> None:
    report = _portfolio_report()
    payload = _payload(report)

    assert payload["calculated_at"] == "2026-08-22T12:00:00Z"
    assert payload["implemented_membership"] == _membership_field(["CA", "CA_LOS_ANGELES", "CA_SAN_FRANCISCO"])
    assert payload["portfolio_snapshot_at"] == _field(
        "2026-08-20",
        owner=_LIFECYCLE_OWNER,
        read_path=_LIFECYCLE_READ_PATH,
        origin="direct",
        observed="2026-08-20",
        age="P2DT12H",
    )
    assert [region["jurisdiction_code"]["value"] for region in payload["regions"]] == [
        "CA",
        "CA_LOS_ANGELES",
        "CA_SAN_FRANCISCO",
        "NY",
        "NY_NEW_YORK",
    ]


def test_report_json_round_trips_through_the_typed_contract() -> None:
    report = _portfolio_report()

    assert CoverageStatusReport.model_validate_json(report.model_dump_json()) == report


# --- successful region rows ----------------------------------------------------


def test_implemented_non_municipality_row_projects_its_own_direct_public_claim() -> None:
    report = _portfolio_report()

    assert _region_payload(report, "CA") == {
        "status": "region",
        "jurisdiction_code": _structural_registry_field("CA"),
        "implemented": _membership_field(True),
        "public_tier": _registry_field(
            "launch-support candidate", origin="direct", observed="2026-07-01", age="P52DT12H"
        ),
        "tier_evidence_at": _registry_field("2026-07-01", origin="direct", observed="2026-07-01", age="P52DT12H"),
        "municipality_disposition": _structural_registry_field("not_applicable"),
        "municipality_audit_claim": _structural_registry_field(None),
    }


def test_implemented_independent_target_row_has_applicability_null_audit_claim() -> None:
    report = _portfolio_report()

    assert _region_payload(report, "CA_LOS_ANGELES") == {
        "status": "region",
        "jurisdiction_code": _structural_registry_field("CA_LOS_ANGELES"),
        "implemented": _membership_field(True),
        "public_tier": _registry_field("freshness-limited", origin="direct", observed="2026-08-01", age="P21DT12H"),
        "tier_evidence_at": _registry_field("2026-08-01", origin="direct", observed="2026-08-01", age="P21DT12H"),
        "municipality_disposition": _structural_registry_field(
            {"municipal_audit_decision": "independent_target", "parent_jurisdiction_code": "CA"}
        ),
        "municipality_audit_claim": _structural_registry_field(None),
    }


def test_implemented_covered_by_parent_row_inherits_public_claim_and_keeps_child_audit_claim() -> None:
    report = _portfolio_report()

    assert _region_payload(report, "CA_SAN_FRANCISCO") == {
        "status": "region",
        "jurisdiction_code": _structural_registry_field("CA_SAN_FRANCISCO"),
        "implemented": _membership_field(True),
        "public_tier": _registry_field(
            "launch-support candidate", origin="inherited", observed="2026-07-01", age="P52DT12H"
        ),
        "tier_evidence_at": _registry_field("2026-07-01", origin="inherited", observed="2026-07-01", age="P52DT12H"),
        "municipality_disposition": _structural_registry_field(
            {"municipal_audit_decision": "covered_by_parent", "parent_jurisdiction_code": "CA"}
        ),
        "municipality_audit_claim": _registry_field(
            {
                "source_jurisdiction_code": "CA_SAN_FRANCISCO",
                "tier": "deferred/blocked",
                "evidence_summary": "child audit note",
                "operational_reason": None,
                "next_action": "child next action",
                "evidence_date": "2026-06-15",
            },
            origin="direct",
            observed="2026-06-15",
            age="P68DT12H",
        ),
    }


def test_non_implemented_direct_row_reports_false_membership_without_lifecycle_join() -> None:
    report = _portfolio_report()

    assert _region_payload(report, "NY") == {
        "status": "region",
        "jurisdiction_code": _structural_registry_field("NY"),
        "implemented": _membership_field(False),
        "public_tier": _registry_field(
            "implemented but unproven",
            origin="direct",
            observed="UNKNOWN",
            age="UNKNOWN",
            reason=_EVIDENCE_DATE_ABSENT,
        ),
        "tier_evidence_at": _unknown(_EVIDENCE_DATE_ABSENT),
        "municipality_disposition": _structural_registry_field("not_applicable"),
        "municipality_audit_claim": _structural_registry_field(None),
    }


def test_non_implemented_covered_by_parent_row_inherits_parent_claim_without_any_lifecycle_row() -> None:
    report = _portfolio_report()

    assert _region_payload(report, "NY_NEW_YORK") == {
        "status": "region",
        "jurisdiction_code": _structural_registry_field("NY_NEW_YORK"),
        "implemented": _membership_field(False),
        "public_tier": _registry_field(
            "implemented but unproven",
            origin="inherited",
            observed="UNKNOWN",
            age="UNKNOWN",
            reason=_EVIDENCE_DATE_ABSENT,
        ),
        "tier_evidence_at": _unknown(_EVIDENCE_DATE_ABSENT),
        "municipality_disposition": _structural_registry_field(
            {"municipal_audit_decision": "covered_by_parent", "parent_jurisdiction_code": "NY"}
        ),
        "municipality_audit_claim": _registry_field(
            {
                "source_jurisdiction_code": "NY_NEW_YORK",
                "tier": "freshness-limited",
                "evidence_summary": "child audit pending",
                "operational_reason": None,
                "next_action": None,
                "evidence_date": None,
            },
            origin="direct",
            observed="UNKNOWN",
            age="UNKNOWN",
            reason=_EVIDENCE_DATE_ABSENT,
        ),
    }


# --- scoped refusals -----------------------------------------------------------


def _refusals(report: CoverageStatusReport) -> list[Refusal]:
    return [region for region in report.regions if isinstance(region, Refusal)]


def test_member_missing_its_coverage_registry_row_refuses_only_that_row() -> None:
    report = _build_report(
        registry_rows=[_california()],
        lifecycle_rows=[_lifecycle_row("CA", "California")],
        membership=frozenset({"CA", "NV"}),
    )

    assert _refusals(report) == [
        Refusal(scope="NV", reason="no coverage-registry row for 'NV'", canonical_owner="coverage-registry")
    ]
    # The defective code is one scoped entry; the healthy row and the report-level facts survive.
    assert len(report.regions) == 2
    assert isinstance(report.regions[0], CoverageStatusRegion)
    assert isinstance(report.implemented_membership, ProjectedField)
    assert isinstance(report.portfolio_snapshot_at, ProjectedField)


def test_direct_member_missing_its_lifecycle_row_refuses_that_row() -> None:
    report = _build_report(registry_rows=[_california()], lifecycle_rows=[], membership=frozenset({"CA"}))

    assert _refusals(report) == [
        Refusal(
            scope="CA",
            reason="no implemented-region-lifecycle row for 'CA'",
            canonical_owner="implemented-region-lifecycle",
        )
    ]


def test_covered_by_parent_member_missing_parent_registry_row_refuses_that_row() -> None:
    report = _build_report(
        registry_rows=[_san_francisco()],
        lifecycle_rows=[],
        membership=frozenset({"CA_SAN_FRANCISCO"}),
    )

    assert _refusals(report) == [
        Refusal(
            scope="CA_SAN_FRANCISCO",
            reason="municipality 'CA_SAN_FRANCISCO' has no coverage-registry parent 'CA'",
            canonical_owner="coverage-registry",
        )
    ]


def test_covered_by_parent_member_missing_parent_lifecycle_row_refuses_only_that_row() -> None:
    report = _build_report(
        registry_rows=[_california(), _san_francisco()],
        lifecycle_rows=[],
        membership=frozenset({"CA_SAN_FRANCISCO"}),
    )

    assert _refusals(report) == [
        Refusal(
            scope="CA_SAN_FRANCISCO",
            reason="covered_by_parent 'CA_SAN_FRANCISCO' has no parent implemented-region-lifecycle row for 'CA'",
            canonical_owner="implemented-region-lifecycle",
        )
    ]
    assert _region_payload(report, "CA")["implemented"]["value"] is False


def test_branch_selected_registry_lifecycle_mismatch_refuses_both_affected_rows() -> None:
    report = _build_report(
        registry_rows=[_california(), _san_francisco()],
        lifecycle_rows=[_lifecycle_row("CA", "California", public_claim_status="deferred/blocked")],
        membership=frozenset({"CA", "CA_SAN_FRANCISCO"}),
    )

    refusals = _refusals(report)
    assert [refusal.scope for refusal in refusals] == ["CA", "CA_SAN_FRANCISCO"]
    assert {refusal.canonical_owner for refusal in refusals} == {"coverage-registry"}
    assert all("public_claim_status" in refusal.reason for refusal in refusals)


def test_child_parent_lifecycle_mismatch_refuses_only_the_child_row() -> None:
    report = _build_report(
        registry_rows=[_california(), _san_francisco()],
        lifecycle_rows=[
            _lifecycle_row("CA", "California"),
            _lifecycle_row("CA_SAN_FRANCISCO", "San Francisco", main_blocker="different child blocker"),
        ],
        membership=frozenset({"CA", "CA_SAN_FRANCISCO"}),
    )

    refusals = _refusals(report)
    assert [refusal.scope for refusal in refusals] == ["CA_SAN_FRANCISCO"]
    assert refusals[0].canonical_owner == "implemented-region-lifecycle"
    assert "main_blocker" in refusals[0].reason
    assert _region_payload(report, "CA")["implemented"]["value"] is True


def test_lifecycle_row_outside_derived_membership_refuses_that_row() -> None:
    report = _build_report(
        registry_rows=[_california(), _new_york()],
        lifecycle_rows=[_lifecycle_row("CA", "California"), _lifecycle_row("NY", "New York")],
        membership=frozenset({"CA"}),
    )

    assert _refusals(report) == [
        Refusal(
            scope="NY",
            reason="implemented-region-lifecycle row for 'NY' is outside derived implemented membership",
            canonical_owner="derive_implemented_jurisdiction_codes",
        )
    ]


# --- CLI -----------------------------------------------------------------------


class _MembershipSpy:
    """Stand-in for the membership owner that records how often the CLI calls it."""

    def __init__(self, codes: set[str] | None = None, error: Exception | None = None) -> None:
        self.codes = codes or set()
        self.error = error
        self.calls = 0

    def __call__(self) -> set[str]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return set(self.codes)


def _write_fixture_inputs(tmp_path, *, registry_rows=None, lifecycle_rows=None) -> tuple[str, str]:
    registry_path = tmp_path / "coverage-registry.json"
    lifecycle_path = tmp_path / "implemented-region-lifecycle.json"
    write_registry(
        registry_path, CoverageRegistry(rows=registry_rows if registry_rows is not None else [_california()])
    )
    write_lifecycle(
        lifecycle_path,
        ImplementedRegionLifecycleRegistry(
            updated_at=_LIFECYCLE_UPDATED_AT,
            rows=lifecycle_rows if lifecycle_rows is not None else [_lifecycle_row("CA", "California")],
        ),
    )
    return str(registry_path), str(lifecycle_path)


def _run_cli(monkeypatch, registry_path: str, lifecycle_path: str, membership: _MembershipSpy) -> int:
    monkeypatch.setattr(coverage_status, "derive_implemented_jurisdiction_codes", membership)
    return main(["--registry-path", registry_path, "--lifecycle-path", lifecycle_path])


def test_cli_prints_one_report_and_calls_the_membership_owner_once(tmp_path, monkeypatch, capsys) -> None:
    from pathlib import Path

    makefile = (Path(__file__).resolve().parents[4] / "Makefile").read_text(encoding="utf-8")
    assert (
        "\ncoverage-status:\n\t@uv run python -m domains.campaign_finance.coverage.status.coverage_status\n" in makefile
    )

    registry_path, lifecycle_path = _write_fixture_inputs(tmp_path)
    membership = _MembershipSpy({"CA"})

    exit_code = _run_cli(monkeypatch, registry_path, lifecycle_path, membership)

    assert exit_code == 0
    assert membership.calls == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["implemented_membership"]["value"] == ["CA"]
    assert [region["jurisdiction_code"]["value"] for region in payload["regions"]] == ["CA"]


def test_cli_keeps_exit_zero_when_a_single_region_row_refuses(tmp_path, monkeypatch, capsys) -> None:
    registry_path, lifecycle_path = _write_fixture_inputs(tmp_path)
    membership = _MembershipSpy({"CA", "NV"})

    exit_code = _run_cli(monkeypatch, registry_path, lifecycle_path, membership)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [region["status"] for region in payload["regions"]] == ["region", "refuse"]


def test_cli_refuses_the_whole_invocation_when_the_registry_is_unreadable(tmp_path, monkeypatch, capsys) -> None:
    _, lifecycle_path = _write_fixture_inputs(tmp_path)
    membership = _MembershipSpy({"CA"})

    exit_code = _run_cli(monkeypatch, str(tmp_path / "absent-registry.json"), lifecycle_path, membership)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "absent-registry.json" in captured.err


def test_cli_refuses_the_whole_invocation_when_the_lifecycle_is_unreadable(tmp_path, monkeypatch, capsys) -> None:
    registry_path, _ = _write_fixture_inputs(tmp_path)
    membership = _MembershipSpy({"CA"})

    exit_code = _run_cli(monkeypatch, registry_path, str(tmp_path / "absent-lifecycle.json"), membership)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "absent-lifecycle.json" in captured.err


def test_cli_refuses_the_whole_invocation_when_membership_derivation_fails(tmp_path, monkeypatch, capsys) -> None:
    registry_path, lifecycle_path = _write_fixture_inputs(tmp_path)
    membership = _MembershipSpy(error=ValueError("membership derivation failed"))

    exit_code = _run_cli(monkeypatch, registry_path, lifecycle_path, membership)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "membership derivation failed" in captured.err


def test_cli_defaults_to_the_canonical_registry_and_lifecycle_paths() -> None:
    parser = coverage_status._build_argument_parser()
    defaults = parser.parse_args([])

    assert defaults.registry_path == coverage_status.DEFAULT_REGISTRY_PATH
    assert defaults.lifecycle_path == coverage_status.DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH
