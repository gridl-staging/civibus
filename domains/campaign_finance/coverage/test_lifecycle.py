from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.campaign_finance.coverage.lifecycle import (
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH,
    load_lifecycle,
    main,
    render_lifecycle_summary_markdown,
)
from domains.campaign_finance.coverage.registry import DEFAULT_REGISTRY_PATH, load_registry
from domains.campaign_finance.coverage.render_summary import derive_implemented_jurisdiction_codes
from domains.campaign_finance.coverage.seed_registry import derive_state_registry_rows


def _valid_payload(*, jurisdiction_code: str = "EX") -> dict[str, object]:
    return {
        "updated_at": "2026-03-27",
        "rows": [
            {
                "jurisdiction_code": jurisdiction_code,
                "name": "Example",
                "acquisition_pattern": "bulk_file",
                "discovery_maturity": "researched",
                "source_contract_maturity": "encoded",
                "legal_filing_semantics_maturity": "partial",
                "implementation_maturity": "fixture_tested",
                "operational_maturity": "manual_only",
                "public_claim_status": "implemented but unproven",
                "completeness_intelligence_maturity": "not_started",
                "civics_candidacy_status": "not_started",
                "main_blocker": "Example blocker",
            }
        ],
    }


def test_load_lifecycle_rejects_invalid_status_literal(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"][0]["acquisition_pattern"] = "portal_magic"
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="acquisition_pattern"):
        load_lifecycle(path)


def test_render_lifecycle_summary_markdown_contains_expected_columns(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    lifecycle = load_lifecycle(path)
    markdown = render_lifecycle_summary_markdown(lifecycle)

    assert "# Implemented Region Lifecycle Summary (Derived)" in markdown
    assert "| Jurisdiction | Acquisition Pattern | Discovery | Source Contract |" in markdown
    assert "| EX | bulk_file | researched | encoded |" in markdown


def test_render_lifecycle_summary_markdown_escapes_table_breaking_text(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["rows"][0]["main_blocker"] = "Needs committee | enrichment\nand proof"
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    lifecycle = load_lifecycle(path)
    markdown = render_lifecycle_summary_markdown(lifecycle)

    assert "Needs committee \\| enrichment and proof" in markdown


def test_lifecycle_main_writes_summary_markdown(tmp_path: Path) -> None:
    lifecycle_path = tmp_path / "lifecycle.json"
    output_path = tmp_path / "summary.md"
    lifecycle_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    exit_code = main(["--path", str(lifecycle_path), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    assert "# Implemented Region Lifecycle Summary (Derived)" in output_path.read_text(encoding="utf-8")


def test_current_lifecycle_rows_match_implemented_jurisdiction_codes() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)

    assert {row.jurisdiction_code for row in lifecycle.rows} == derive_implemented_jurisdiction_codes()


def test_current_lifecycle_summary_snapshot_matches_rendered_output() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)

    assert DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_SUMMARY_PATH.read_text(encoding="utf-8") == (
        render_lifecycle_summary_markdown(lifecycle)
    )


def test_lifecycle_public_claim_status_and_names_match_registry_authority() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    registry_rows_by_code = {row.jurisdiction_code: row for row in load_registry(DEFAULT_REGISTRY_PATH).rows}

    for row in lifecycle.rows:
        registry_row = registry_rows_by_code[row.jurisdiction_code]
        assert row.public_claim_status == registry_row.tier, row.jurisdiction_code
        assert row.name == registry_row.name, row.jurisdiction_code


def test_lifecycle_operational_maturity_respects_registry_runner_wiring_floor() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    registry_rows_by_code = {row.jurisdiction_code: row for row in load_registry(DEFAULT_REGISTRY_PATH).rows}

    for row in lifecycle.rows:
        registry_row = registry_rows_by_code[row.jurisdiction_code]
        if registry_row.runner_wired:
            assert row.operational_maturity in {"runner_wired", "operational"}, row.jurisdiction_code
            continue
        assert row.operational_maturity in {"unknown", "manual_only"}, row.jurisdiction_code


def test_lifecycle_examples_capture_illinois_ohio_and_texas_statuses() -> None:
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    rows_by_code = {row.jurisdiction_code: row for row in lifecycle.rows}

    il_row = rows_by_code["IL"]
    assert il_row.acquisition_pattern == "browser_session_portal"
    assert il_row.discovery_maturity == "interactively_proven"
    assert il_row.source_contract_maturity == "verified"
    assert il_row.legal_filing_semantics_maturity == "substantial"
    assert il_row.implementation_maturity == "live_proven"
    assert il_row.operational_maturity == "runner_wired"
    assert il_row.public_claim_status == "implemented but unproven"
    assert il_row.completeness_intelligence_maturity == "not_started"

    oh_row = rows_by_code["OH"]
    assert oh_row.acquisition_pattern == "protected_or_blocked"
    assert oh_row.discovery_maturity == "blocked"
    assert oh_row.operational_maturity == "manual_only"
    assert oh_row.public_claim_status == "deferred/blocked"

    tx_row = rows_by_code["TX"]
    assert tx_row.operational_maturity == "runner_wired"
    assert tx_row.public_claim_status == "launch-support candidate"


def test_implemented_state_packages_have_required_lifecycle_artifacts() -> None:
    project_root = Path(__file__).resolve().parents[3]
    states_root = project_root / "domains" / "campaign_finance" / "jurisdictions" / "states"

    for row in derive_state_registry_rows():
        state_dir = states_root / row.jurisdiction_code
        assert (state_dir / "README.md").exists(), row.jurisdiction_code
        assert (state_dir / "config.yaml").exists(), row.jurisdiction_code
        assert (state_dir / "data_semantics.md").exists(), row.jurisdiction_code
        assert (state_dir / "laws.md").exists(), row.jurisdiction_code
        assert (state_dir / "scraper").is_dir(), row.jurisdiction_code

        test_files = [*state_dir.glob("scraper/test_*.py"), *state_dir.glob("tests/test_*.py")]
        assert test_files, row.jurisdiction_code
