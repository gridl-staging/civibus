from __future__ import annotations

import json
import re
from pathlib import Path

from domains.campaign_finance.coverage.registry import load_registry
from domains.campaign_finance.coverage.render_summary import (
    derive_implemented_jurisdiction_codes,
    render_publication_markdown,
)
from domains.campaign_finance.coverage.seed_registry import build_seed_registry


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _PROJECT_ROOT / "docs" / "research" / "coverage-registry.json"
_EXPECTED_JURISDICTION_CODES = {
    "FEC",
    "AL",
    "AK",
    "AZ",
    "AR",
    "AS",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "GU",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MP",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "PR",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "VI",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}


def test_state_equivalent_expected_codes_include_territories() -> None:
    assert {"AS", "GU", "MP", "PR", "VI"}.issubset(_EXPECTED_JURISDICTION_CODES)


_TERRITORY_UNINVESTIGATED_REASON = "Territory not yet investigated. No pipeline, no audit."
_TERRITORY_CODES = {"AS", "GU", "MP", "PR", "VI"}


def _load_coverage_registry():
    return load_registry(_REGISTRY_PATH)


def test_coverage_registry_snapshot_is_complete_and_classified() -> None:
    registry = _load_coverage_registry()

    # Filter to state-equivalent rows only — resilient to municipality rows being added
    state_equivalent_rows = [row for row in registry.rows if row.jurisdiction_type in ("federal", "state")]
    assert len(state_equivalent_rows) == len(_EXPECTED_JURISDICTION_CODES)
    assert {row.jurisdiction_code for row in state_equivalent_rows} == _EXPECTED_JURISDICTION_CODES

    for row in state_equivalent_rows:
        assert row.source_count == len(row.source_names)
        if row.jurisdiction_code in _TERRITORY_CODES:
            assert row.source_count == 0
        else:
            assert row.source_count > 0
        assert row.tier is not None
        assert row.evidence_summary
        assert row.next_action
        assert row.evidence_date is not None
        if row.tier == "deferred/blocked":
            assert row.operational_reason
        # State-equivalent rows must not have municipality linkage
        assert row.parent_jurisdiction_code is None
        assert row.municipal_audit_decision is None


def test_stage3_probe_artifact_keeps_corrected_arizona_entrypoint() -> None:
    artifact_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "research"
        / "artifacts"
        / "stage3_state_portal_probe_2026-03-25.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    az_probe = artifact["AZ"]
    assert az_probe["url"] == "https://azsos.gov/elections"
    assert az_probe["source_label"] == "Arizona Secretary of State Elections Portal"
    assert az_probe["status"] == 403
    assert az_probe["error"] == "HTTPError 403 (Cloudflare challenge)"


def test_stage4_state_layer_closure_invariants() -> None:
    registry = _load_coverage_registry()
    state_rows = [row for row in registry.rows if row.jurisdiction_type == "state"]

    assert state_rows
    assert all(row.tier is not None for row in state_rows)
    assert all(row.evidence_date is not None for row in state_rows)
    assert all(row.next_action != "Stage 4 browser-session investigation" for row in state_rows)

    date_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    for row in state_rows:
        if row.tier == "deferred/blocked":
            assert row.operational_reason is not None
            if row.jurisdiction_code in _TERRITORY_CODES:
                assert row.operational_reason == _TERRITORY_UNINVESTIGATED_REASON
            else:
                assert date_pattern.search(row.operational_reason) is not None


def test_registry_seed_owned_fields_match_fresh_seed_build() -> None:
    registry = _load_coverage_registry()
    seeded_rows = {row.jurisdiction_code: row for row in build_seed_registry().rows}
    research_owned_fields = {
        "tier",
        "evidence_summary",
        "operational_reason",
        "next_action",
        "evidence_date",
        "ie_coverage_available",
    }
    for row in registry.rows:
        seeded_row = seeded_rows.get(row.jurisdiction_code)
        if seeded_row is None:
            continue

        current_payload = row.model_dump(mode="json")
        seeded_payload = seeded_row.model_dump(mode="json")
        comparable_fields = set(seeded_payload) - research_owned_fields

        assert {field_name: current_payload[field_name] for field_name in comparable_fields} == {
            field_name: seeded_payload[field_name] for field_name in comparable_fields
        }, row.jurisdiction_code


def test_stage3_wisconsin_contract_gate_uses_live_sunshine_exports() -> None:
    registry = _load_coverage_registry()

    wi_row = next(row for row in registry.rows if row.jurisdiction_code == "WI")

    # runner_wired=True after Stage 7 reseed (WI is in _SUPPORTED_STATE_CODES)
    assert wi_row.runner_wired is True
    assert wi_row.tier == "launch-support candidate"
    assert wi_row.best_update_frequency == "daily"
    assert wi_row.best_last_verified_working is not None
    assert wi_row.best_last_verified_working.isoformat() == "2026-03-27"
    assert wi_row.evidence_summary is not None
    assert "first live WI Sunshine proof" in wi_row.evidence_summary
    assert "loaded 500 source records plus 500 transactions" in wi_row.evidence_summary
    assert "full-state-name normalization" in wi_row.evidence_summary
    assert "stale filing-cache reuse after row rollback" in wi_row.evidence_summary
    assert "gab.wi.gov" not in wi_row.evidence_summary
    assert wi_row.evidence_date is not None


def test_stage4_new_jersey_contract_gate_uses_verified_export_and_api_paths() -> None:
    registry = _load_coverage_registry()

    nj_row = next(row for row in registry.rows if row.jurisdiction_code == "NJ")

    # runner_wired=True after Stage 7 reseed (NJ is in _SUPPORTED_STATE_CODES)
    assert nj_row.runner_wired is True
    assert nj_row.tier == "freshness-limited"
    assert nj_row.best_update_frequency == "quarterly"
    assert nj_row.covers_sub_jurisdictions is True
    assert nj_row.evidence_summary is not None
    assert "portal probe" not in nj_row.evidence_summary
    assert "https://www.elec.nj.gov/" in nj_row.evidence_summary
    assert "https://www.elec.nj.gov/pay2play/quickdownload.html" in nj_row.evidence_summary
    assert "https://www.elec.nj.gov/download/ptp/data/P2P_2024_Contributions.csv" in nj_row.evidence_summary
    assert "https://www.njelecefilesearch.com/api/VWContributionDetail/DownlodDataCSV" in nj_row.evidence_summary
    assert "https://www.elec.nj.gov/publicinformation/disclose_dates.htm" in nj_row.evidence_summary
    assert "7:00 p.m. on the filing due date" in nj_row.evidence_summary
    assert "Governor and Legislature" in nj_row.evidence_summary
    assert "Mayor and City Council" in nj_row.evidence_summary
    # Stage 1 freshness recheck additions
    assert "all three DownlodDataCSV endpoints confirmed operational via POST" in nj_row.evidence_summary
    assert "144.5MB" in nj_row.evidence_summary
    assert "export-generation recency, not filing-level recency" in nj_row.evidence_summary
    assert (
        nj_row.next_action
        == "Maintain NJ freshness-limited classification; only reclassify if a fresher official export path is proven."
    )
    assert nj_row.evidence_date is not None


def test_stage5_idaho_stays_freshness_limited_until_weekly_plus_proof() -> None:
    registry = _load_coverage_registry()

    id_row = next(row for row in registry.rows if row.jurisdiction_code == "ID")

    assert id_row.tier == "freshness-limited"
    assert id_row.best_update_frequency == "monthly"
    assert id_row.best_last_verified_working is not None
    assert id_row.best_last_verified_working.isoformat() == "2026-04-29"
    assert id_row.evidence_summary is not None
    assert "monthly reporting plus timed-report exceptions" in id_row.evidence_summary
    assert id_row.operational_reason == (
        "Idaho has deterministic T2 API/CSV acquisition, but current evidence only proves monthly baseline "
        "filings plus timed-report events; that remains below the weekly launch-support threshold."
    )
    assert (
        id_row.next_action
        == "Prototype the Idaho pipeline from verified endpoints; keep freshness-limited until repeated "
        "production checks prove weekly+ effective cadence."
    )
    assert id_row.evidence_date is not None


def test_runner_wired_rows_do_not_claim_pending_runner_work() -> None:
    registry = _load_coverage_registry()
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}

    wi_row = rows_by_code["WI"]
    assert wi_row.runner_wired is True
    assert wi_row.operational_reason == (
        "Current direct live ingest proof and production-serving proof both exist for the WI transaction path; "
        "the remaining gap is bounded runner proof and broader reports/committees operational evidence, not "
        "source viability."
    )
    assert (
        wi_row.next_action
        == "Capture bounded runner-path proof for `state-wi-transactions` and decide how far reports/committees "
        "should be operationalized beyond the current transaction path."
    )

    assert rows_by_code["IN"].runner_wired is True
    in_evidence_summary = rows_by_code["IN"].evidence_summary
    assert in_evidence_summary is not None
    assert "in_freshness_recheck_2026_04_26.md" in in_evidence_summary
    assert "in_mn_nj_freshness_stage1_baseline_2026_04_28.md" in in_evidence_summary
    assert "weekly-or-better" in in_evidence_summary
    assert "three valid probes" in in_evidence_summary
    assert "Apr 16, Apr 17, Apr 26" in in_evidence_summary
    assert (
        rows_by_code["IN"].next_action
        == "Launch-ready for cadence: keep weekly-or-better monitoring in routine refresh evidence and only "
        "reclassify if a future dated probe shows regression."
    )
    assert rows_by_code["IN"].tier == "launch-support candidate"
    assert rows_by_code["IN"].best_last_verified_working is not None
    assert rows_by_code["IN"].best_last_verified_working.isoformat() == "2026-04-26"
    assert (
        rows_by_code["IN"].operational_reason
        == "Cadence is resolved positive: three valid probes across 10 days (2026-04-16, 2026-04-17, "
        "2026-04-26) show source advancement consistent with weekly-or-better launch support."
    )
    assert (
        rows_by_code["IN_FORT_WAYNE"].next_action
        == f"Inherit parent-state path: IN -> {rows_by_code['IN'].next_action}"
    )
    assert (
        rows_by_code["IN_INDIANAPOLIS_CITY_BALANCE"].next_action
        == f"Inherit parent-state path: IN -> {rows_by_code['IN'].next_action}"
    )
    assert rows_by_code["IN_FORT_WAYNE"].tier == rows_by_code["IN"].tier
    assert rows_by_code["IN_INDIANAPOLIS_CITY_BALANCE"].tier == rows_by_code["IN"].tier


def test_stage5_parent_reclassifications_propagate_to_covered_municipalities() -> None:
    registry = _load_coverage_registry()
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}

    for child_code, parent_code in (
        ("LA_NEW_ORLEANS", "LA"),
        ("NE_LINCOLN", "NE"),
        ("NE_OMAHA", "NE"),
    ):
        child_row = rows_by_code[child_code]
        parent_row = rows_by_code[parent_code]

        assert child_row.municipal_audit_decision == "covered_by_parent"
        assert child_row.tier == parent_row.tier
        assert child_row.best_update_frequency == parent_row.best_update_frequency
        assert child_row.best_last_verified_working == parent_row.best_last_verified_working
        assert child_row.next_action == f"Inherit parent-state path: {parent_code} -> {parent_row.next_action}"


# Cities with browser-verified materially separate filing systems may be
# independent_target even when parent has covers_sub_jurisdictions=True.
# See docs/research/coverage-audit-contract.md §4 and docs/research/city-portal-research.md.
_BROWSER_VERIFIED_INDEPENDENT_CITIES = frozenset(
    {
        "NY_NEW_YORK",
        "CA_LOS_ANGELES",
        "CA_SAN_FRANCISCO",
        "PA_PHILADELPHIA",
        "DC_WASHINGTON",
    }
)
_STAGE1_CITY_PORTAL_URLS = {
    "NY_NEW_YORK": "https://www.nyccfb.info/follow-the-money/data-library/",
    "CA_LOS_ANGELES": "https://data.lacity.org/",
    "CA_SAN_FRANCISCO": "https://sfethics.org/disclosures/campaign-finance-disclosure",
    "PA_PHILADELPHIA": "https://www.phila.gov/departments/board-of-ethics/campaign-finance/",
    "DC_WASHINGTON": "https://ocf.dc.gov/",
}


def test_stage5_municipality_layer_snapshot_invariants() -> None:
    registry = _load_coverage_registry()

    state_rows = [row for row in registry.rows if row.jurisdiction_type in ("federal", "state")]
    municipality_rows = [row for row in registry.rows if row.jurisdiction_type == "municipality"]
    code_to_state = {row.jurisdiction_code: row for row in state_rows}

    assert len(state_rows) == len(_EXPECTED_JURISDICTION_CODES)
    assert set(code_to_state) == _EXPECTED_JURISDICTION_CODES
    assert len(municipality_rows) == 100

    for row in municipality_rows:
        assert row.parent_jurisdiction_code is not None
        assert row.municipal_audit_decision in {"covered_by_parent", "independent_target"}
        assert row.parent_jurisdiction_code in code_to_state
        parent = code_to_state[row.parent_jurisdiction_code]

        # Municipal rows must never claim independent scope beyond their own unit.
        assert row.covers_sub_jurisdictions is False

        # Prevent false-independent classifications when parent authority already proves coverage.
        # Exception: cities with browser-verified materially separate filing systems
        # (coverage-audit-contract.md §4 exception clause).
        if row.municipal_audit_decision == "independent_target":
            if row.jurisdiction_code not in _BROWSER_VERIFIED_INDEPENDENT_CITIES:
                assert parent.covers_sub_jurisdictions is False


_IMPLEMENTED_CITY_PIPELINES = frozenset({"CA_LOS_ANGELES", "NY_NEW_YORK", "PA_PHILADELPHIA"})
_PRE_BUILD_INDEPENDENT_CITIES = _BROWSER_VERIFIED_INDEPENDENT_CITIES - _IMPLEMENTED_CITY_PIPELINES


def test_stage1_city_portal_reclassifications() -> None:
    """Five cities reclassified from covered_by_parent to independent_target."""
    registry = _load_coverage_registry()
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}

    for code in _BROWSER_VERIFIED_INDEPENDENT_CITIES:
        row = rows_by_code[code]
        assert row.municipal_audit_decision == "independent_target", f"{code} should be independent_target"
        assert row.jurisdiction_type == "municipality"
        assert row.parent_jurisdiction_code is not None
        # Browser-verified cities must have portal URL evidence
        assert row.municipal_portal_url is not None, f"{code} must have municipal_portal_url"
        assert row.municipal_portal_url != "needs_investigation"
        assert row.municipal_portal_url == _STAGE1_CITY_PORTAL_URLS[code]

    # Non-implemented cities: still pre-build, browser-verified research state
    for code in _PRE_BUILD_INDEPENDENT_CITIES:
        row = rows_by_code[code]
        assert row.runner_wired is False, f"{code} should have runner_wired=False (no city pipeline exists)"
        assert row.evidence_summary is not None
        assert "browser-verified" in row.evidence_summary.lower() or "Browser-verified" in row.evidence_summary

    # Implemented cities: LA and NYC have pipelines wired in runner.py
    for code in _IMPLEMENTED_CITY_PIPELINES:
        row = rows_by_code[code]
        assert row.runner_wired is True, f"{code} should have runner_wired=True (pipeline implemented)"
        assert row.tier == "implemented but unproven", f"{code} tier should be 'implemented but unproven'"
        assert row.evidence_summary is not None
        assert "Pipeline implemented" in row.evidence_summary, f"{code} evidence must cite pipeline implementation"


def test_stage4_phl_row_matches_shipped_pipeline_and_closeout_status() -> None:
    registry = _load_coverage_registry()
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}
    row = rows_by_code["PA_PHILADELPHIA"]

    assert row.source_count == 2
    assert row.source_names == [
        "PHL Campaign Finance Contributions",
        "PHL Campaign Finance Expenditures",
    ]
    assert row.runner_wired is True
    assert row.tier == "implemented but unproven"
    assert row.best_last_verified_working is not None
    assert row.best_last_verified_working.isoformat() == "2026-04-25"
    assert row.evidence_date is not None
    assert row.evidence_date.isoformat() == "2026-04-29"
    assert row.evidence_summary is not None
    assert "Pipeline implemented" in row.evidence_summary
    assert "phl_full_backfill_closeout_2026_04_29.md" in row.evidence_summary
    assert "phl_freshness_probe_2026_04_26.md" in row.evidence_summary
    assert row.operational_reason is not None
    assert "full-scale closeout remains incomplete" in row.operational_reason
    assert "freshness-limited" in row.operational_reason
    assert row.next_action is not None
    assert "Complete the detached full-scale closeout rerun" in row.next_action


def test_stage1_chicago_seattle_remain_covered_by_parent() -> None:
    """Chicago and Seattle remain covered_by_parent after city portal research."""
    registry = _load_coverage_registry()
    rows_by_code = {row.jurisdiction_code: row for row in registry.rows}

    for code in ("IL_CHICAGO", "WA_SEATTLE"):
        row = rows_by_code[code]
        assert row.municipal_audit_decision == "covered_by_parent", f"{code} should remain covered_by_parent"


def test_stage5_census_artifact_excludes_non_incorporated_cdps() -> None:
    artifact_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "research"
        / "artifacts"
        / "stage5_sub_ip_est2024_pop_top100_2026-03-25.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert all("CDP" not in row["place_name_raw"] for row in artifact["rows"])
    assert artifact["selection_logic"]["cutoff_row"]["jurisdiction_code"] == "WA_SPOKANE"
    assert artifact["selection_logic"]["next_excluded_row"]["geographic_area"] == "Huntsville city, Alabama"


def test_render_outputs_match_committed_markdown_artifacts() -> None:
    registry = _load_coverage_registry()

    publication = render_publication_markdown(
        registry,
        implemented_jurisdiction_codes=derive_implemented_jurisdiction_codes(),
    )

    assert publication.summary_markdown == (
        _PROJECT_ROOT / "docs" / "research" / "coverage-registry-summary.md"
    ).read_text(encoding="utf-8")
    assert publication.queue_markdown == (
        _PROJECT_ROOT / "docs" / "research" / "coverage-build-priority-queue.md"
    ).read_text(encoding="utf-8")
    assert publication.matrix_markdown == (
        _PROJECT_ROOT / "docs" / "research" / "2026-launch-support-matrix.md"
    ).read_text(encoding="utf-8")


def test_rendered_queue_and_matrix_headers_reference_registry_authority() -> None:
    registry = _load_coverage_registry()

    publication = render_publication_markdown(
        registry,
        implemented_jurisdiction_codes=derive_implemented_jurisdiction_codes(),
    )

    expected_authority_note = "Authoritative source: `docs/research/coverage-registry.json`."
    assert expected_authority_note in publication.summary_markdown
    assert expected_authority_note in publication.queue_markdown
    assert expected_authority_note in publication.matrix_markdown
