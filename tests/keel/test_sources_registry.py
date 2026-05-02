from __future__ import annotations

import json
from pathlib import Path

import yaml

_ALLOWED_SOURCE_STATES = {
    "discovered",
    "prototyped",
    "validated",
    "operationalized",
    "degraded",
    "deferred",
}

_EXPECTED_PHASE2_JURISDICTIONS = {
    "NC": {
        "phase": "Phase 2",
        "ownership_contains": "project-local",
        "sources": {
            "nc_transactions": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("L6", "NC_transactions"),
                },
            },
            "nc_committee_documents": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("L6", "NC_committee_documents"),
                },
            },
            "nc_ie_document_index": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("L6", "NC_ie_document_index"),
                },
            },
            "nc_tiger_county_shapefile": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_geometry_source_contract_2026_04_29"),
                },
            },
            "nc_ncsbe_congressional_district_shapefile": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_geometry_source_contract_2026_04_29"),
                },
            },
            "nc_ncsbe_state_senate_district_shapefile": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_geometry_source_contract_2026_04_29"),
                },
            },
            "nc_ncsbe_state_house_district_shapefile": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_geometry_source_contract_2026_04_29"),
                },
            },
            "nc_nconemap_municipal_shapefile": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_geometry_source_contract_2026_04_29"),
                },
            },
            "nc_nconemap_school_district_shapefile": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_geometry_source_contract_2026_04_29"),
                },
            },
            "nc_durham_city_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_general_assembly_house_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_sheriffs_association_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_registers_of_deeds_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_durham_county_commissioners_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_wake_county_commissioners_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_orange_county_commissioners_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_soil_water_supervisors_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_raleigh_city_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_cary_town_council_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_apex_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_holly_springs_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_fuquay_varina_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_wake_forest_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_garner_town_council_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_morrisville_town_council_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_knightdale_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_wendell_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_zebulon_town_council_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_rolesville_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_chapel_hill_town_council_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_carrboro_town_council_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_hillsborough_town_council_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_dps_school_board_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_wcpss_school_board_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_ocs_school_board_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "nc_chccs_school_board_roster": {
                "current_state": "validated",
                "required_evidence": {
                    ("L1", "NC"),
                    ("docs", "NC_roster_maintenance_closeout_2026_04_30"),
                },
            },
            "ncsbe_candidate_listing_2026": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_candidate_listing_2026"),
                },
            },
            "nc_superior_court_judge_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_judicial_contract_stage1_2026_04_29"),
                },
            },
            "nc_district_court_judge_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_judicial_contract_stage1_2026_04_29"),
                },
            },
            "nc_clerk_of_superior_court_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_judicial_contract_stage1_2026_04_29"),
                },
            },
            "nc_district_attorney_roster": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NC_judicial_contract_stage1_2026_04_29"),
                },
            },
            "nc_ncsbe_enrs_2020_11_03_general": {
                "current_state": "deferred",
                "required_evidence": {
                    ("docs", "NC_NCSBE_ENRS_contract_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage1_prerequisite_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage5_dispatch_state_s148_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage6_hetzner_dispatch_2026_04_30"),
                },
            },
            "nc_ncsbe_enrs_2022_11_08_general": {
                "current_state": "deferred",
                "required_evidence": {
                    ("docs", "NC_NCSBE_ENRS_contract_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage1_prerequisite_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage5_dispatch_state_s148_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage6_hetzner_dispatch_2026_04_30"),
                },
            },
            "nc_ncsbe_enrs_2024_03_05_primary": {
                "current_state": "deferred",
                "required_evidence": {
                    ("docs", "NC_NCSBE_ENRS_contract_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage1_prerequisite_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage5_dispatch_state_s148_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage6_hetzner_dispatch_2026_04_30"),
                },
            },
            "nc_ncsbe_enrs_2024_11_05_general": {
                "current_state": "deferred",
                "required_evidence": {
                    ("docs", "NC_NCSBE_ENRS_contract_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage1_prerequisite_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage5_dispatch_state_s148_2026_04_30"),
                    ("docs", "NC_NCSBE_ENRS_stage6_hetzner_dispatch_2026_04_30"),
                },
            },
        },
    },
    "PHL": {
        "phase": "Phase 2",
        "ownership_contains": "city pipeline",
        "sources": {
            "phl_contributions": {
                "current_state": "deferred",
                "required_evidence": {
                    ("docs", "PHL"),
                },
            },
            "phl_expenditures": {
                "current_state": "deferred",
                "required_evidence": {
                    ("docs", "PHL"),
                },
            },
        },
    },
    "NY": {
        "phase": "Phase 2",
        "ownership_contains": "project-local",
        "sources": {
            "ny_contributions": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NY_stage5_maintenance_closeout_2026_04_29"),
                },
            },
            "ny_expenditures": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NY_stage5_maintenance_closeout_2026_04_29"),
                    ("docs", "NY_stage2_closeout_2026_04_28"),
                },
            },
            "ny_independent_expenditures": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "NY_stage5_maintenance_closeout_2026_04_29"),
                    ("docs", "NY_stage2_closeout_2026_04_28"),
                },
            },
        },
    },
    "MA": {
        "phase": "Phase 2",
        "ownership_contains": "project-local",
        "sources": {
            "ma_contributions": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "MA_deadlock_fix_closeout_2026_04_29"),
                },
            },
            "ma_expenditures": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("docs", "MA_deadlock_fix_closeout_2026_04_29"),
                },
            },
        },
    },
    "CA": {
        "phase": "Phase 2",
        "ownership_contains": "project-local",
        "sources": {
            "ca_cal_access_raw_export": {
                "current_state": "prototyped",
                "required_evidence": {
                    ("L1", "CA"),
                },
            },
        },
    },
}

_EXPECTED_SCOPE_ORDER = ["NC", "PHL", "NY", "MA", "IN", "MN", "NJ", "CA"]

_EXPECTED_IN_MN_NJ_MINIMAL_SOURCES = {
    "IN": {
        "source_id": "in_ied_bulk_exports",
        "current_state": "prototyped",
        "phase": "Stage 2 freshness closeout",
        "required_docs_scopes": {
            "IN_freshness_recheck_2026_04_26",
            "IN_MN_NJ_freshness_stage1_baseline_2026_04_28",
        },
    },
    "MN": {
        "source_id": "mn_cfb_bulk_exports",
        "current_state": "deferred",
        "phase": "Stage 3 freshness closeout",
        "required_docs_scopes": {
            "MN_freshness_negative_closeout",
            "MN_freshness_probe_2026_04_09",
            "IN_MN_NJ_freshness_stage1_baseline_2026_04_28",
        },
    },
    "NJ": {
        "source_id": "nj_elec_contribution_exports",
        "current_state": "deferred",
        "phase": "Stage 4 freshness closeout",
        "required_docs_scopes": {
            "NJ_ie_investigation_2026_04_17",
            "NJ_freshness_probe_2026_04_09",
            "IN_MN_NJ_freshness_stage1_baseline_2026_04_28",
        },
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_registry() -> dict:
    registry_path = _repo_root() / "sources.yaml"
    assert registry_path.is_file(), "sources.yaml must exist once Phase 2 starts"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_sources_registry_lands_phase2_jurisdiction_contracts() -> None:
    payload = _load_registry()

    assert payload["schema_version"] == 1
    jurisdictions = payload["jurisdictions"]
    assert isinstance(jurisdictions, list)
    assert [entry["scope"] for entry in jurisdictions] == _EXPECTED_SCOPE_ORDER

    jurisdictions_by_scope = {entry["scope"]: entry for entry in jurisdictions}
    for scope, expectation in _EXPECTED_PHASE2_JURISDICTIONS.items():
        jurisdiction = jurisdictions_by_scope[scope]
        assert jurisdiction["phase"] == expectation["phase"]
        assert expectation["ownership_contains"] in jurisdiction["ownership"]

        sources = {source["source_id"]: source for source in jurisdiction["sources"]}
        expected_sources = expectation["sources"]
        assert sources.keys() == expected_sources.keys()

        for source_id, source_expectation in expected_sources.items():
            source = sources[source_id]
            assert source["current_state"] in _ALLOWED_SOURCE_STATES
            assert source["current_state"] == source_expectation["current_state"]
            transitions = source["transitions"]
            assert isinstance(transitions, list)
            assert len(transitions) >= 1
            assert transitions[-1]["to_state"] == source["current_state"]


def test_nc_roster_sources_registry_contract() -> None:
    payload = _load_registry()
    jurisdictions = payload["jurisdictions"]
    jurisdictions_by_scope = {entry["scope"]: entry for entry in jurisdictions}
    nc_sources = {source["source_id"]: source for source in jurisdictions_by_scope["NC"]["sources"]}

    roster_sources = {
        "nc_durham_city_council_roster": "durham_city_council",
        "nc_raleigh_city_council_roster": "nc_municipal_council",
        "nc_cary_town_council_roster": "nc_municipal_council",
        "nc_apex_town_council_roster": "nc_municipal_council",
        "nc_holly_springs_town_council_roster": "nc_municipal_council",
        "nc_fuquay_varina_town_council_roster": "nc_municipal_council",
        "nc_wake_forest_town_council_roster": "nc_municipal_council",
        "nc_garner_town_council_roster": "nc_municipal_council",
        "nc_morrisville_town_council_roster": "nc_municipal_council",
        "nc_knightdale_town_council_roster": "nc_municipal_council",
        "nc_wendell_town_council_roster": "nc_municipal_council",
        "nc_zebulon_town_council_roster": "nc_municipal_council",
        "nc_rolesville_town_council_roster": "nc_municipal_council",
        "nc_chapel_hill_town_council_roster": "nc_municipal_council",
        "nc_carrboro_town_council_roster": "nc_municipal_council",
        "nc_hillsborough_town_council_roster": "nc_municipal_council",
        "nc_dps_school_board_roster": "nc_school_board",
        "nc_wcpss_school_board_roster": "nc_school_board",
        "nc_ocs_school_board_roster": "nc_school_board",
        "nc_chccs_school_board_roster": "nc_school_board",
    }
    for source_id, body_key in roster_sources.items():
        assert source_id in nc_sources
        roster_bootstrap = nc_sources[source_id].get("roster_bootstrap")
        assert isinstance(roster_bootstrap, dict)
        assert roster_bootstrap.get("body_key") == body_key


def test_sources_registry_includes_minimal_in_mn_nj_entries() -> None:
    payload = _load_registry()
    jurisdictions = payload["jurisdictions"]
    jurisdictions_by_scope = {entry["scope"]: entry for entry in jurisdictions}

    for scope, expected in _EXPECTED_IN_MN_NJ_MINIMAL_SOURCES.items():
        assert scope in jurisdictions_by_scope
        entry = jurisdictions_by_scope[scope]
        assert entry["phase"] == expected["phase"]
        assert "project-local" in entry["ownership"]
        assert len(entry["sources"]) == 1
        source = entry["sources"][0]
        assert source["source_id"] == expected["source_id"]
        assert source["current_state"] == expected["current_state"]
        assert source["current_state"] in _ALLOWED_SOURCE_STATES
        assert source["transitions"][-1]["to_state"] == expected["current_state"]

        docs_refs = [
            evidence_ref
            for evidence_ref in source["transitions"][-1]["evidence_refs"]
            if evidence_ref["layer"] == "docs"
        ]
        if expected["current_state"] == "deferred":
            assert docs_refs, f"{scope} deferred state must include at least one docs evidence ref"
        if "required_docs_scopes" in expected:
            docs_scopes = {evidence_ref["scope"] for evidence_ref in docs_refs}
            assert docs_scopes >= expected["required_docs_scopes"]


def test_sources_registry_evidence_refs_point_to_real_matching_artifacts() -> None:
    payload = _load_registry()
    repo_root = _repo_root()

    for jurisdiction in payload["jurisdictions"]:
        jurisdiction_expectation = _EXPECTED_PHASE2_JURISDICTIONS.get(jurisdiction["scope"])
        for source in jurisdiction["sources"]:
            evidence_refs = set()
            for transition in source["transitions"]:
                for evidence_ref in transition["evidence_refs"]:
                    evidence_refs.add((evidence_ref["layer"], evidence_ref["scope"]))
                    evidence_path = repo_root / evidence_ref["path"]
                    assert evidence_path.is_file(), f"missing evidence file: {evidence_ref['path']}"
                    if evidence_ref["layer"] == "docs":
                        assert evidence_ref["path"].startswith("docs/")
                        continue
                    evidence_payload = _load_json(evidence_path)
                    assert evidence_payload["layer"] == evidence_ref["layer"]
                    assert evidence_payload["scope"] == evidence_ref["scope"]
                    assert evidence_payload["status"] == "pass"

            if jurisdiction_expectation is not None:
                expected_evidence = jurisdiction_expectation["sources"][source["source_id"]]["required_evidence"]
                assert evidence_refs == expected_evidence


def test_indiana_closeout_package_metadata_matches_stage2_evidence() -> None:
    repo_root = _repo_root()
    registry = _load_registry()
    jurisdictions = {entry["scope"]: entry for entry in registry["jurisdictions"]}
    in_entry = jurisdictions["IN"]
    in_source = in_entry["sources"][0]
    last_transition = in_source["transitions"][-1]
    docs_scopes = {
        evidence_ref["scope"]
        for evidence_ref in last_transition["evidence_refs"]
        if evidence_ref["layer"] == "docs"
    }

    assert docs_scopes >= {
        "IN_freshness_recheck_2026_04_26",
        "IN_MN_NJ_freshness_stage1_baseline_2026_04_28",
    }

    in_config = _load_yaml(repo_root / "domains/campaign_finance/jurisdictions/states/IN/config.yaml")
    source_dates = {source["last_verified_working"] for source in in_config["data_sources"]}
    source_frequencies = {source["update_frequency"] for source in in_config["data_sources"]}
    assert source_dates == {"2026-04-26"}
    assert source_frequencies == {"weekly"}

    readme_text = (repo_root / "domains/campaign_finance/jurisdictions/states/IN/README.md").read_text(
        encoding="utf-8"
    )
    assert "docs/research/in_freshness_recheck_2026_04_26.md" in readme_text
    assert "docs/research/in_mn_nj_freshness_stage1_baseline_2026_04_28.md" in readme_text
