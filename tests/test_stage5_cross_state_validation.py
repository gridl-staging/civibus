from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
SMOKE_TEST_PATH = REPO_ROOT / "tests" / "test_state_sample_ingest_smoke.py"
CA_STAGE4_PATH = (
    REPO_ROOT
    / "domains"
    / "campaign_finance"
    / "jurisdictions"
    / "states"
    / "CA"
    / "tests"
    / "test_stage4_regressions.py"
)
MN_STAGE3_PATH = (
    REPO_ROOT
    / "domains"
    / "campaign_finance"
    / "jurisdictions"
    / "states"
    / "MN"
    / "tests"
    / "test_stage3_regressions.py"
)
WA_STAGE4_PATH = (
    REPO_ROOT
    / "domains"
    / "campaign_finance"
    / "jurisdictions"
    / "states"
    / "WA"
    / "tests"
    / "test_stage4_regressions.py"
)
_STAGE5_SAMPLE_INGEST_TARGETS = (
    "ingest-ca-sample",
    "ingest-mn-sample",
    "ingest-wa-sample",
)
_STAGE_REGRESSION_PATHS = (
    CA_STAGE4_PATH,
    MN_STAGE3_PATH,
    WA_STAGE4_PATH,
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _state_sample_ingest_names() -> list[str]:
    module = ast.parse(_read_text(SMOKE_TEST_PATH))
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "_STATE_SAMPLE_INGESTS":
                if not isinstance(node.value, ast.Tuple):
                    raise AssertionError("_STATE_SAMPLE_INGESTS must be a tuple")
                states: list[str] = []
                for ingest_tuple in node.value.elts:
                    if not isinstance(ingest_tuple, ast.Tuple) or not ingest_tuple.elts:
                        raise AssertionError("each ingest entry must be a non-empty tuple")
                    state_name = ingest_tuple.elts[0]
                    if not isinstance(state_name, ast.Constant) or not isinstance(state_name.value, str):
                        raise AssertionError("each ingest tuple must start with a string state code")
                    states.append(state_name.value)
                return states
    raise AssertionError("_STATE_SAMPLE_INGESTS assignment not found")


def _string_tuple_assignment(name: str) -> list[str]:
    module = ast.parse(_read_text(SMOKE_TEST_PATH))
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                if not isinstance(node.value, ast.Tuple):
                    raise AssertionError(f"{name} must be a tuple")
                values: list[str] = []
                for item in node.value.elts:
                    if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                        raise AssertionError(f"{name} entries must be string literals")
                    values.append(item.value)
                return values
    raise AssertionError(f"{name} assignment not found")


def test_makefile_wires_new_state_sample_targets_to_committed_fixtures() -> None:
    makefile = _read_text(MAKEFILE_PATH)

    assert re.search(
        r"^ingest-ca-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.states\.CA\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/states/CA/scraper/test_fixtures/sample_archive$",
        makefile,
        re.M,
    )
    assert re.search(
        r"^ingest-mn-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.states\.MN\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/states/MN/scraper/test_fixtures/sample_contributions\.csv "
        r"--data-type contributions$",
        makefile,
        re.M,
    )
    assert re.search(
        r"^ingest-wa-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.states\.WA\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/states/WA/scraper/test_fixtures/sample_contributions\.csv "
        r"--data-type contributions$",
        makefile,
        re.M,
    )


def test_state_sample_ingest_smoke_contract_is_intentionally_co_ga_nc_only() -> None:
    assert _state_sample_ingest_names() == ["CO", "GA", "NC"]


def test_stage5_preseed_targets_cover_new_states_without_expanding_smoke_contract() -> None:
    assert _string_tuple_assignment("_STAGE5_PRESEED_INGEST_TARGETS") == list(_STAGE5_SAMPLE_INGEST_TARGETS)


@pytest.mark.parametrize("path", _STAGE_REGRESSION_PATHS)
def test_stage_regression_paths_exist(path: Path) -> None:
    assert path.exists(), f"Expected regression test file is missing: {path}"


@pytest.mark.parametrize("path", _STAGE_REGRESSION_PATHS)
def test_stage_regression_files_do_not_reference_stage5_makefile_wiring_audit(
    path: Path,
) -> None:
    text = _read_text(path)

    assert "Makefile" not in text
    for target in _STAGE5_SAMPLE_INGEST_TARGETS:
        assert target not in text


def _coverage_registry_rows_by_code() -> dict[str, dict[str, object]]:
    registry_path = REPO_ROOT / "docs" / "reference" / "research" / "coverage-registry.json"
    payload = json.loads(_read_text(registry_path))
    rows = payload["rows"]
    return {row["jurisdiction_code"]: row for row in rows}


def _matrix_row_line(jurisdiction_code: str) -> str:
    matrix_path = REPO_ROOT / "docs" / "reference" / "research" / "2026-launch-support-matrix.md"
    for line in _read_text(matrix_path).splitlines():
        if line.startswith(f"| {jurisdiction_code} |"):
            return line
    raise AssertionError(f"Missing matrix row for {jurisdiction_code}")


def test_stage5_in_verdict_is_launch_ready_in_registry_and_matrix() -> None:
    rows_by_code = _coverage_registry_rows_by_code()
    in_row = rows_by_code["IN"]

    assert in_row["tier"] == "launch-support candidate"
    assert in_row["best_update_frequency"] == "weekly"
    assert in_row["best_last_verified_working"] == "2026-04-26"
    assert (
        in_row["next_action"]
        == "Launch-ready for cadence: keep weekly-or-better monitoring in routine refresh evidence and only "
        "reclassify if a future dated probe shows regression."
    )
    assert "Ship with freshness warning" not in in_row["next_action"]

    matrix_line = _matrix_row_line("IN")
    assert "| IN | state | launch-support candidate | weekly | yes |" in matrix_line
    assert "Ship with freshness warning" not in matrix_line

    for child_code in ("IN_FORT_WAYNE", "IN_INDIANAPOLIS_CITY_BALANCE"):
        child_row = rows_by_code[child_code]
        assert child_row["tier"] == in_row["tier"]
        assert child_row["next_action"] == f"Inherit parent-state path: IN -> {in_row['next_action']}"


def test_stage5_mn_nj_resolved_negative_wording_is_maintenance_only() -> None:
    rows_by_code = _coverage_registry_rows_by_code()

    for state_code in ("MN", "NJ"):
        row = rows_by_code[state_code]
        assert row["tier"] == "freshness-limited"
        assert "resolved negative" in row["operational_reason"].lower()
        assert "Investigate" not in row["next_action"]

    for child_code in ("MN_MINNEAPOLIS", "MN_ST_PAUL", "NJ_JERSEY_CITY", "NJ_NEWARK"):
        child_row = rows_by_code[child_code]
        assert "Investigate" not in child_row["next_action"]
        assert "Inherit parent-state path:" in child_row["next_action"]


def test_stage6_ny_registry_row_uses_apr29_maintenance_closeout_wording() -> None:
    rows_by_code = _coverage_registry_rows_by_code()
    ny_row = rows_by_code["NY"]
    buffalo_row = rows_by_code["NY_BUFFALO"]

    assert ny_row["tier"] == "implemented but unproven"
    assert ny_row["evidence_date"] == "2026-04-29"
    assert "serial rerun still failed in contributions" in str(ny_row["evidence_summary"]).lower()
    assert (
        "expenditures and independent expenditures did not execute in that pass"
        in str(ny_row["evidence_summary"]).lower()
    )
    assert "0 ny filings / transactions materialized" in str(ny_row["operational_reason"]).lower()
    assert "maintenance_closeout.md" in str(ny_row["next_action"])
    assert buffalo_row["municipal_audit_decision"] == "covered_by_parent"
    assert buffalo_row["next_action"] == f"Inherit parent-state path: NY -> {ny_row['next_action']}"
