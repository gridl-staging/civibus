from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.campaign_finance.coverage import validate_registry
from domains.campaign_finance.coverage.registry import CoverageRegistry


def _write_registry(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")
    return path


def _base_row_payload(code: str = "CA") -> dict[str, object]:
    return {
        "jurisdiction_code": code,
        "name": "California" if code == "CA" else code,
        "jurisdiction_type": "state",
        "best_update_frequency": "daily",
        "best_last_verified_working": "2026-03-21",
        "covers_sub_jurisdictions": True,
        "source_count": 2,
        "source_names": ["source_a", "source_b"],
        "runner_wired": True,
        "tier": None,
        "evidence_summary": None,
        "operational_reason": None,
        "next_action": None,
        "evidence_date": None,
    }


def test_main_valid_registry_reports_pass_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = CoverageRegistry.model_validate({"rows": [_base_row_payload("CA"), _base_row_payload("MN")]})
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(f"{registry.model_dump_json(indent=2)}\n", encoding="utf-8")

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS: row[0] jurisdiction_code=CA" in output
    assert "PASS: row[1] jurisdiction_code=MN" in output
    assert "Validation summary: checked=2 passed=2 failed=0 warnings=0" in output


def test_main_duplicate_jurisdiction_code_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    row = _base_row_payload("CA")
    registry_path = _write_registry(tmp_path / "registry_dup.json", {"rows": [row, row]})

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "FAIL: Duplicate jurisdiction code 'CA'" in output


def test_main_invalid_row_reports_validation_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_row = _base_row_payload("CA")
    bad_row["source_count"] = False
    registry_path = _write_registry(tmp_path / "registry_invalid.json", {"rows": [bad_row]})

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "FAIL: row[0]" in output
    assert "source_count" in output


# --- Municipality cross-layer validation tests (Stage 5) ---


def _municipality_row_payload(
    code: str = "CA_LOS_ANGELES",
    parent: str = "CA",
    decision: str = "covered_by_parent",
) -> dict[str, object]:
    return {
        "jurisdiction_code": code,
        "name": "Los Angeles",
        "jurisdiction_type": "municipality",
        "best_update_frequency": "daily",
        "best_last_verified_working": "2026-03-25",
        "covers_sub_jurisdictions": False,
        "source_count": 1,
        "source_names": ["Inherited from CA"],
        "runner_wired": False,
        "tier": "launch-support candidate",
        "evidence_summary": "Covered by parent state CA",
        "operational_reason": None,
        "next_action": "Inherits parent pipeline",
        "evidence_date": "2026-03-25",
        "parent_jurisdiction_code": parent,
        "municipal_audit_decision": decision,
    }


def test_main_validates_mixed_state_and_municipality_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_row = _base_row_payload("CA")
    muni_row = _municipality_row_payload()
    registry_path = _write_registry(tmp_path / "registry.json", {"rows": [state_row, muni_row]})

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS: row[0] jurisdiction_code=CA" in output
    assert "PASS: row[1] jurisdiction_code=CA_LOS_ANGELES" in output


def test_main_fails_municipality_with_orphan_parent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Municipality references a parent code that doesn't exist in the registry."""
    muni_row = _municipality_row_payload(parent="ZZ")
    registry_path = _write_registry(tmp_path / "registry.json", {"rows": [muni_row]})

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "orphan" in output.lower() or "parent" in output.lower()


def test_main_fails_covered_by_parent_when_parent_does_not_cover_subs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """covered_by_parent decision contradicts parent's covers_sub_jurisdictions=false."""
    state_row = _base_row_payload("MN")
    state_row["covers_sub_jurisdictions"] = False
    muni_row = _municipality_row_payload(code="MN_MINNEAPOLIS", parent="MN", decision="covered_by_parent")
    registry_path = _write_registry(tmp_path / "registry.json", {"rows": [state_row, muni_row]})

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "covers_sub_jurisdictions" in output.lower() or "covered_by_parent" in output.lower()


def test_main_fails_browser_verified_independent_target_without_portal_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_row = _base_row_payload("CA")
    muni_row = _municipality_row_payload(code="CA_LOS_ANGELES", parent="CA", decision="independent_target")
    muni_row["evidence_summary"] = "Browser-verified city portal research (2026-03-31): LA open data portal"
    registry_path = _write_registry(tmp_path / "registry.json", {"rows": [state_row, muni_row]})

    exit_code = validate_registry.main(["--path", str(registry_path)])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "municipal_portal_url" in output
