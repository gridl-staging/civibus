from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml

import core.keel_gate_l3 as keel_gate_l3


def _write_schema(path: Path, *, layer: str, extra_required: list[str], extra_properties: dict[str, object]) -> None:
    payload = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "layer",
            "scope",
            "schema_version",
            "produced_at_utc",
            "repo_sha",
            "gate_command",
            "status",
            *extra_required,
        ],
        "properties": {
            "layer": {"const": layer},
            "scope": {"type": "string"},
            "schema_version": {"const": 1},
            "produced_at_utc": {"type": "string", "format": "date-time"},
            "repo_sha": {"type": "string"},
            "gate_command": {"type": "string"},
            "status": {"type": "string", "enum": ["pass", "fail", "error", "waived", "stale"]},
            **extra_properties,
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_schema_files(repo_root: Path) -> None:
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(
        schema_root / "L1.json",
        layer="L1",
        extra_required=["current_total", "expected_range", "ratio", "anchor_path", "anchor_schema_version"],
        extra_properties={
            "current_total": {"type": "number"},
            "expected_range": {"type": "object"},
            "ratio": {"type": "number"},
            "anchor_path": {"type": "string"},
            "anchor_schema_version": {"type": "integer"},
        },
    )
    _write_schema(
        schema_root / "L6.json",
        layer="L6",
        extra_required=["load_id", "total_rows", "out_of_range_rows", "example_rows"],
        extra_properties={
            "load_id": {"type": "string"},
            "total_rows": {"type": "integer"},
            "out_of_range_rows": {"type": "integer"},
            "example_rows": {"type": "array"},
        },
    )
    _write_schema(
        schema_root / "L3.json",
        layer="L3",
        extra_required=["source_id", "current_state", "transition_date", "linked_evidence", "validation_checks"],
        extra_properties={
            "source_id": {"type": "string"},
            "current_state": {"type": "string"},
            "transition_date": {"type": "string", "format": "date"},
            "linked_evidence": {"type": "array"},
            "validation_checks": {"type": "array"},
        },
    )


def _write_evidence(
    repo_root: Path,
    *,
    layer: str,
    scope: str,
    relative_path: str,
    status: str = "pass",
    extras: dict[str, object],
) -> Path:
    evidence_path = repo_root / relative_path
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layer": layer,
        "scope": scope,
        "schema_version": 1,
        "produced_at_utc": "2026-04-24T12:00:00Z",
        "repo_sha": "abc12345",
        "gate_command": f"make gate-{layer}",
        "status": status,
        **extras,
    }
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return evidence_path


def _write_sources_yaml(repo_root: Path, *, current_state: str, evidence_refs: list[dict[str, str]]) -> Path:
    sources_path = repo_root / "sources.yaml"
    payload = {
        "schema_version": 1,
        "jurisdictions": [
            {
                "scope": "NC",
                "phase": "Phase 2",
                "ownership": "project-local pilot registry until matt-side absorption exists",
                "sources": [
                    {
                        "source_id": "nc_transactions",
                        "current_state": current_state,
                        "coverage_boundary": "Receipt-side NC pilot transaction proof slice.",
                        "transitions": [
                            {
                                "to_state": current_state,
                                "recorded_on": date(2026, 4, 24),
                                "rationale": "Pilot proof recorded in committed evidence.",
                                "evidence_refs": evidence_refs,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    sources_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return sources_path


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_repo_sources_registry_registers_federal_chartered_sources(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    registry = keel_gate_l3._load_registry(repo_root / "sources.yaml")

    federal_entry = next(entry for entry in registry.jurisdictions if entry.scope == "FEDERAL")
    assert [source.source_id for source in federal_entry.sources] == [
        "census_tiger_congressional_district_listing",
        "openfec_election_dates_api",
        "fec_bulk_cn_ccl_races",
    ]
    assert {source.current_state for source in federal_entry.sources} == {"prototyped"}

    result = keel_gate_l3.evaluate_registry(
        repo_root=repo_root,
        sources_path=repo_root / "sources.yaml",
        jurisdiction="FEDERAL",
        evidence_root=tmp_path / "evidence" / "L3",
    )

    assert result.exit_code == 0
    assert [source_result.source_id for source_result in result.source_results] == [
        "census_tiger_congressional_district_listing",
        "openfec_election_dates_api",
        "fec_bulk_cn_ccl_races",
    ]
    assert {source_result.status for source_result in result.source_results} == {"pass"}


def test_repo_sources_registry_passes_current_nc_roster_state_mix_contract(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    registry = yaml.safe_load((repo_root / "sources.yaml").read_text(encoding="utf-8"))
    assert isinstance(registry, dict)
    nc_entry = next(entry for entry in registry["jurisdictions"] if entry["scope"] == "NC")
    expected_source_ids = [source["source_id"] for source in nc_entry["sources"]]

    result = keel_gate_l3.evaluate_registry(
        repo_root=repo_root,
        sources_path=repo_root / "sources.yaml",
        jurisdiction="NC",
        evidence_root=tmp_path / "evidence" / "L3",
    )

    assert result.exit_code == 0
    assert [source_result.source_id for source_result in result.source_results] == expected_source_ids
    assert {source_result.status for source_result in result.source_results} == {"pass"}

    roster_expected_state_by_source_id = {
        "nc_durham_city_council_roster": "validated",
        "nc_general_assembly_house_roster": "validated",
        "nc_sheriffs_association_roster": "validated",
        "nc_registers_of_deeds_roster": "prototyped",
        "nc_durham_county_commissioners_roster": "validated",
        "nc_wake_county_commissioners_roster": "validated",
        "nc_orange_county_commissioners_roster": "validated",
        "nc_soil_water_supervisors_roster": "prototyped",
        "nc_raleigh_city_council_roster": "validated",
        "nc_cary_town_council_roster": "prototyped",
        "nc_apex_town_council_roster": "validated",
        "nc_holly_springs_town_council_roster": "validated",
        "nc_fuquay_varina_town_council_roster": "validated",
        "nc_wake_forest_town_council_roster": "validated",
        "nc_garner_town_council_roster": "prototyped",
        "nc_morrisville_town_council_roster": "prototyped",
        "nc_knightdale_town_council_roster": "validated",
        "nc_wendell_town_council_roster": "validated",
        "nc_zebulon_town_council_roster": "prototyped",
        "nc_rolesville_town_council_roster": "validated",
        "nc_chapel_hill_town_council_roster": "prototyped",
        "nc_carrboro_town_council_roster": "validated",
        "nc_hillsborough_town_council_roster": "prototyped",
        "nc_dps_school_board_roster": "prototyped",
        "nc_wcpss_school_board_roster": "validated",
        "nc_ocs_school_board_roster": "validated",
        "nc_chccs_school_board_roster": "validated",
    }
    results_by_source_id = {source_result.source_id: source_result for source_result in result.source_results}
    observed_states = set()
    for source_id, expected_state in roster_expected_state_by_source_id.items():
        source_result = results_by_source_id[source_id]
        assert source_result.evidence_path.name.startswith(f"{expected_state}_")
        observed_states.add(expected_state)
    assert observed_states == {"validated", "prototyped"}


def test_repo_sources_registry_includes_all_fixed_nc_ncsbe_enrs_source_ids(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = keel_gate_l3.evaluate_registry(
        repo_root=repo_root,
        sources_path=repo_root / "sources.yaml",
        jurisdiction="NC",
        evidence_root=tmp_path / "evidence" / "L3",
    )

    observed_source_ids = {source_result.source_id for source_result in result.source_results}
    assert {
        "nc_ncsbe_enrs_2020_11_03_general",
        "nc_ncsbe_enrs_2022_11_08_general",
        "nc_ncsbe_enrs_2024_03_05_primary",
        "nc_ncsbe_enrs_2024_11_05_general",
    }.issubset(observed_source_ids)


def test_evaluate_registry_phl_reports_missing_jurisdiction_for_minimal_fixture(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sources_path = repo_root / "sources.yaml"
    sources_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "jurisdictions": [
                    {
                        "scope": "NC",
                        "phase": "Phase 2",
                        "ownership": "project-local pilot registry until matt-side absorption exists",
                        "sources": [],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"jurisdiction 'PHL' is not present"):
        keel_gate_l3.evaluate_registry(
            repo_root=repo_root,
            sources_path=sources_path,
            jurisdiction="PHL",
        )


def test_repo_sources_registry_passes_current_phl_deferred_contract(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = keel_gate_l3.evaluate_registry(
        repo_root=repo_root,
        sources_path=repo_root / "sources.yaml",
        jurisdiction="PHL",
        evidence_root=tmp_path / "evidence" / "L3",
    )

    assert result.exit_code == 0
    assert [source_result.source_id for source_result in result.source_results] == [
        "phl_contributions",
        "phl_expenditures",
    ]
    assert {source_result.status for source_result in result.source_results} == {"pass"}


def test_repo_sources_registry_ca_emits_single_expected_l3_artifact(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    registry = yaml.safe_load((repo_root / "sources.yaml").read_text(encoding="utf-8"))
    assert isinstance(registry, dict)

    ca_entry = next(entry for entry in registry["jurisdictions"] if entry["scope"] == "CA")
    assert len(ca_entry["sources"]) == 1
    source = ca_entry["sources"][0]
    source_id = source["source_id"]
    current_state = source["current_state"]
    transition = source["transitions"][-1]
    assert transition["recorded_on"] == date(2026, 4, 29)

    result = keel_gate_l3.evaluate_registry(
        repo_root=repo_root,
        sources_path=repo_root / "sources.yaml",
        jurisdiction="CA",
        evidence_root=tmp_path / "evidence" / "L3",
    )

    assert result.exit_code == 0
    assert [entry.source_id for entry in result.source_results] == [source_id]
    source_result = result.source_results[0]
    assert source_result.status == "pass"

    expected_path = tmp_path / "evidence" / "L3" / "CA" / source_id / f"{current_state}_2026-04-29.json"
    assert source_result.evidence_path == expected_path

    payload = _read_json(source_result.evidence_path)
    assert payload["scope"] == "CA"
    assert payload["source_id"] == source_id
    assert payload["current_state"] == current_state
    assert payload["transition_date"] == "2026-04-29"
    assert payload["status"] == "pass"

    referenced_paths = {ref["path"] for ref in transition["evidence_refs"]}
    linked_paths = {item["path"] for item in payload["linked_evidence"]}
    assert linked_paths == referenced_paths
    assert all(item["status"] == "pass" for item in payload["linked_evidence"])


@pytest.mark.parametrize(
    ("jurisdiction", "source_id", "current_state", "required_docs_scopes"),
    [
        (
            "IN",
            "in_ied_bulk_exports",
            "prototyped",
            {"IN_freshness_recheck_2026_04_26", "IN_MN_NJ_freshness_stage1_baseline_2026_04_28"},
        ),
        (
            "MN",
            "mn_cfb_bulk_exports",
            "deferred",
            {
                "MN_freshness_negative_closeout",
                "MN_freshness_probe_2026_04_09",
                "IN_MN_NJ_freshness_stage1_baseline_2026_04_28",
            },
        ),
        (
            "NJ",
            "nj_elec_contribution_exports",
            "deferred",
            {
                "NJ_ie_investigation_2026_04_17",
                "NJ_freshness_probe_2026_04_09",
                "IN_MN_NJ_freshness_stage1_baseline_2026_04_28",
            },
        ),
    ],
)
def test_repo_sources_registry_passes_stage1_minimal_in_mn_nj_contract(
    jurisdiction: str,
    source_id: str,
    current_state: str,
    tmp_path: Path,
    required_docs_scopes: set[str],
) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = keel_gate_l3.evaluate_registry(
        repo_root=repo_root,
        sources_path=repo_root / "sources.yaml",
        jurisdiction=jurisdiction,
        evidence_root=tmp_path / "evidence" / "L3",
    )

    assert result.exit_code == 0
    assert [entry.source_id for entry in result.source_results] == [source_id]
    assert {entry.status for entry in result.source_results} == {"pass"}
    assert result.source_results[0].evidence_path.name.startswith(f"{current_state}_")
    if required_docs_scopes:
        docs_checks = {
            check.name.removeprefix("evidence_ref:docs:")
            for check in result.source_results[0].validation_checks
            if check.name.startswith("evidence_ref:docs:") and check.ok
        }
        assert docs_checks >= required_docs_scopes


def test_main_passes_ny_prototyped_postcloseout_contract_with_lane_specific_docs_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    (repo_root / "docs/reference/research/artifacts/2026_04_29_ny_unstick").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs/reference/research/artifacts/2026_04_29_ny_unstick/maintenance_closeout.md").write_text(
        "# NY maintenance closeout\n",
        encoding="utf-8",
    )
    (repo_root / "docs/reference/research").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs/reference/research/2026-04-28-ny-stage2-closeout.md").write_text(
        "# NY stage2 closeout\n",
        encoding="utf-8",
    )
    sources_path = repo_root / "sources.yaml"
    sources_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "jurisdictions": [
                    {
                        "scope": "NY",
                        "phase": "Phase 2",
                        "ownership": "project-local pilot registry until matt-side absorption exists",
                        "sources": [
                            {
                                "source_id": "ny_contributions",
                                "current_state": "prototyped",
                                "coverage_boundary": "NY contributions lane remains prototyped after Apr 29 serial rerun timed out before load completion.",
                                "transitions": [
                                    {
                                        "to_state": "prototyped",
                                        "recorded_on": date(2026, 4, 29),
                                        "rationale": "Apr 29 serial rerun failed in contributions with read timeout; NY remains prototyped with no L1/L5 promotion evidence.",
                                        "evidence_refs": [
                                            {
                                                "layer": "docs",
                                                "scope": "NY_stage5_maintenance_closeout_2026_04_29",
                                                "path": "docs/reference/research/artifacts/2026_04_29_ny_unstick/maintenance_closeout.md",
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "source_id": "ny_expenditures",
                                "current_state": "prototyped",
                                "coverage_boundary": "NY expenditures lane remains prototyped because Apr 29 serial rerun stopped after contributions timeout.",
                                "transitions": [
                                    {
                                        "to_state": "prototyped",
                                        "recorded_on": date(2026, 4, 29),
                                        "rationale": "Apr 29 serial rerun did not execute expenditures; Apr 28 closeout still owns the last completed lane runtime evidence.",
                                        "evidence_refs": [
                                            {
                                                "layer": "docs",
                                                "scope": "NY_stage5_maintenance_closeout_2026_04_29",
                                                "path": "docs/reference/research/artifacts/2026_04_29_ny_unstick/maintenance_closeout.md",
                                            },
                                            {
                                                "layer": "docs",
                                                "scope": "NY_stage2_closeout_2026_04_28",
                                                "path": "docs/reference/research/2026-04-28-ny-stage2-closeout.md",
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "source_id": "ny_independent_expenditures",
                                "current_state": "prototyped",
                                "coverage_boundary": "NY independent-expenditures lane remains prototyped because Apr 29 serial rerun stopped before this lane executed.",
                                "transitions": [
                                    {
                                        "to_state": "prototyped",
                                        "recorded_on": date(2026, 4, 29),
                                        "rationale": "Apr 29 serial rerun did not execute independent expenditures; Apr 28 closeout still provides the last completed lane evidence.",
                                        "evidence_refs": [
                                            {
                                                "layer": "docs",
                                                "scope": "NY_stage5_maintenance_closeout_2026_04_29",
                                                "path": "docs/reference/research/artifacts/2026_04_29_ny_unstick/maintenance_closeout.md",
                                            },
                                            {
                                                "layer": "docs",
                                                "scope": "NY_stage2_closeout_2026_04_28",
                                                "path": "docs/reference/research/2026-04-28-ny-stage2-closeout.md",
                                            },
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 29, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NY",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    assert exit_code == 0
    for source_id in ("ny_contributions", "ny_expenditures", "ny_independent_expenditures"):
        evidence_path = repo_root / "evidence" / "L3" / "NY" / source_id / "prototyped_2026-04-29.json"
        payload = _read_json(evidence_path)
        assert payload["status"] == "pass"
        assert payload["source_id"] == source_id
        assert payload["current_state"] == "prototyped"
        assert payload["linked_evidence"]
        assert all(item["layer"] == "docs" for item in payload["linked_evidence"])
        assert all(
            check["name"] != "validated_has_l1_anchor" and check["name"] != "validated_has_source_specific_evidence"
            for check in payload["validation_checks"]
        )


def test_main_writes_pass_evidence_for_validated_source_with_l1_and_source_specific_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_evidence(
        repo_root,
        layer="L1",
        scope="NC",
        relative_path="evidence/L1/NC/2026-04-24.json",
        extras={
            "current_total": 70280.85,
            "expected_range": {"minimum": 70000, "maximum": 71000},
            "ratio": 1.004,
            "anchor_path": "docs/reference/anchors/NC.md",
            "anchor_schema_version": 1,
        },
    )
    _write_evidence(
        repo_root,
        layer="L6",
        scope="NC_transactions",
        relative_path="evidence/L6/nc-transactions-20260424T194145Z.json",
        extras={
            "load_id": "nc-transactions-20260424T194145Z",
            "total_rows": 5,
            "out_of_range_rows": 0,
            "example_rows": [],
        },
    )
    sources_path = _write_sources_yaml(
        repo_root,
        current_state="validated",
        evidence_refs=[
            {"layer": "L1", "scope": "NC", "path": "evidence/L1/NC/2026-04-24.json"},
            {"layer": "L6", "scope": "NC_transactions", "path": "evidence/L6/nc-transactions-20260424T194145Z.json"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "validated_2026-04-24.json"
    payload = _read_json(evidence_path)

    assert exit_code == 0
    assert payload["status"] == "pass"
    assert payload["source_id"] == "nc_transactions"
    assert payload["current_state"] == "validated"
    assert [item["layer"] for item in payload["linked_evidence"]] == ["L1", "L6"]
    assert {check["name"] for check in payload["validation_checks"]} >= {
        "last_transition_matches_current_state",
        "validated_has_l1_anchor",
        "validated_has_source_specific_evidence",
    }


def test_main_fails_when_validated_source_has_only_l1_anchor_and_no_source_specific_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_evidence(
        repo_root,
        layer="L1",
        scope="NC",
        relative_path="evidence/L1/NC/2026-04-24.json",
        extras={
            "current_total": 70280.85,
            "expected_range": {"minimum": 70000, "maximum": 71000},
            "ratio": 1.004,
            "anchor_path": "docs/reference/anchors/NC.md",
            "anchor_schema_version": 1,
        },
    )
    sources_path = _write_sources_yaml(
        repo_root,
        current_state="validated",
        evidence_refs=[
            {"layer": "L1", "scope": "NC", "path": "evidence/L1/NC/2026-04-24.json"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "validated_2026-04-24.json"
    payload = _read_json(evidence_path)

    assert exit_code == 1
    assert payload["status"] == "fail"
    assert payload["validation_checks"][-1] == {
        "name": "validated_has_source_specific_evidence",
        "ok": False,
        "detail": "validated sources must cite at least one non-L1 pass evidence artifact",
    }


def _write_l5_schema(repo_root: Path) -> None:
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    _write_schema(
        schema_root / "L5.json",
        layer="L5",
        extra_required=["total_runs", "status_counts"],
        extra_properties={
            "total_runs": {"type": "integer"},
            "status_counts": {"type": "object"},
        },
    )


def _write_l5_evidence(
    repo_root: Path,
    *,
    evidence_date: date,
    status: str,
    relative_path: str | None = None,
) -> Path:
    rel = relative_path or f"evidence/L5/global/{evidence_date.isoformat()}.json"
    return _write_evidence(
        repo_root,
        layer="L5",
        scope="global",
        relative_path=rel,
        status=status,
        extras={"total_runs": 5, "status_counts": {"success": 5}},
    )


def test_main_rejects_operationalized_when_runner_history_is_too_short(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)

    # Only 3 consecutive green L5 dailies; the contract requires 7.
    l5_refs: list[dict[str, str]] = []
    for offset in range(3):
        evidence_date = date.fromordinal(date(2026, 4, 24).toordinal() - offset)
        path = f"evidence/L5/global/{evidence_date.isoformat()}.json"
        _write_l5_evidence(repo_root, evidence_date=evidence_date, status="pass", relative_path=path)
        l5_refs.append({"layer": "L5", "scope": "global", "path": path})

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="operationalized",
        evidence_refs=l5_refs,
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "operationalized_2026-04-24.json"
    payload = _read_json(evidence_path)

    assert exit_code == 1
    assert payload["status"] == "fail"
    check_names = {check["name"] for check in payload["validation_checks"]}
    assert "operationalized_runner_history_consecutive_green" in check_names


def test_main_passes_operationalized_when_seven_consecutive_green_l5_runs_cited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)

    l5_refs: list[dict[str, str]] = []
    for offset in range(7):
        evidence_date = date.fromordinal(date(2026, 4, 24).toordinal() - offset)
        path = f"evidence/L5/global/{evidence_date.isoformat()}.json"
        _write_l5_evidence(repo_root, evidence_date=evidence_date, status="pass", relative_path=path)
        l5_refs.append({"layer": "L5", "scope": "global", "path": path})

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="operationalized",
        evidence_refs=l5_refs,
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "operationalized_2026-04-24.json"
    payload = _read_json(evidence_path)

    assert exit_code == 0
    assert payload["status"] == "pass"


def test_main_rejects_degraded_without_a_failing_l5_evidence_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)
    _write_l5_evidence(repo_root, evidence_date=date(2026, 4, 24), status="pass")

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="degraded",
        evidence_refs=[
            {"layer": "L5", "scope": "global", "path": "evidence/L5/global/2026-04-24.json"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "degraded_2026-04-24.json"
    payload = _read_json(evidence_path)
    assert exit_code == 1
    assert payload["status"] == "fail"
    check_names = {check["name"] for check in payload["validation_checks"]}
    assert "degraded_has_failing_l5_evidence" in check_names


def test_main_passes_degraded_with_one_passing_and_one_failing_l5_evidence_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)
    _write_l5_evidence(
        repo_root,
        evidence_date=date(2026, 4, 24),
        status="fail",
        relative_path="evidence/L5/global/2026-04-24.json",
    )
    _write_l5_evidence(
        repo_root,
        evidence_date=date(2026, 4, 23),
        status="pass",
        relative_path="evidence/L5/global/2026-04-23.json",
    )

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="degraded",
        evidence_refs=[
            {"layer": "L5", "scope": "global", "path": "evidence/L5/global/2026-04-24.json"},
            {"layer": "L5", "scope": "global", "path": "evidence/L5/global/2026-04-23.json"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "degraded_2026-04-24.json"
    payload = _read_json(evidence_path)
    assert exit_code == 0
    assert payload["status"] == "pass"


def test_main_rejects_deferred_without_a_docs_evidence_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)
    _write_l5_evidence(repo_root, evidence_date=date(2026, 4, 24), status="pass")

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="deferred",
        evidence_refs=[
            {"layer": "L5", "scope": "global", "path": "evidence/L5/global/2026-04-24.json"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "deferred_2026-04-24.json"
    payload = _read_json(evidence_path)
    assert exit_code == 1
    assert payload["status"] == "fail"
    check_names = {check["name"] for check in payload["validation_checks"]}
    assert "deferred_has_docs_citation" in check_names


def test_main_passes_deferred_with_a_docs_path_evidence_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)
    docs_path = repo_root / "docs" / "reference" / "research" / "deferral_note.md"
    docs_path.parent.mkdir(parents=True)
    docs_path.write_text("Deferred per T4 policy.\n", encoding="utf-8")

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="deferred",
        evidence_refs=[
            {"layer": "docs", "scope": "research", "path": "docs/reference/research/deferral_note.md"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    exit_code = keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )

    evidence_path = repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "deferred_2026-04-24.json"
    payload = _read_json(evidence_path)
    assert exit_code == 0
    assert payload["status"] == "pass"


def test_emitted_deferred_l3_evidence_validates_against_real_repo_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression: emitted deferred L3 evidence must satisfy the real
    repo-owned evidence_schemas/L3.json. Stage-close re-validates emitted
    evidence against that schema, so a synthetic-test-only payload shape
    would silently break stage-close."""
    from jsonschema.validators import validator_for

    repo_root_real = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_schema_files(repo_root)
    _write_l5_schema(repo_root)
    docs_path = repo_root / "docs" / "reference" / "research" / "deferral_note.md"
    docs_path.parent.mkdir(parents=True)
    docs_path.write_text("Deferred per T4 policy.\n", encoding="utf-8")

    sources_path = _write_sources_yaml(
        repo_root,
        current_state="deferred",
        evidence_refs=[
            {"layer": "docs", "scope": "research", "path": "docs/reference/research/deferral_note.md"},
        ],
    )
    monkeypatch.setattr(keel_gate_l3, "_repo_sha", lambda: "d54355d6")
    monkeypatch.setattr(keel_gate_l3, "_utc_now", lambda: datetime(2026, 4, 24, 21, 0, tzinfo=UTC))

    keel_gate_l3.main(
        [
            "--jurisdiction",
            "NC",
            "--repo-root",
            str(repo_root),
            "--sources-path",
            str(sources_path),
        ]
    )
    payload = _read_json(repo_root / "evidence" / "L3" / "NC" / "nc_transactions" / "deferred_2026-04-24.json")

    real_schema = json.loads((repo_root_real / "evidence_schemas" / "L3.json").read_text(encoding="utf-8"))
    validator_cls = validator_for(real_schema)
    validator_cls.check_schema(real_schema)
    errors = list(validator_cls(real_schema).iter_errors(payload))
    assert errors == [], f"emitted deferred L3 evidence must satisfy the real schema: {errors}"
