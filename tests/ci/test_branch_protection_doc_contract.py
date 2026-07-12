"""Stage 4 contract tests for the branch-protection runbook."""

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
INTEGRATION_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/integration.yml"
RUNBOOK_PATH = REPO_ROOT / "docs/reference/dev/branch-protection.md"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_job_names(workflow_text: str) -> list[str]:
    """Extract job display names from the jobs section without YAML dependencies."""
    _, separator, jobs_text = workflow_text.partition("\njobs:\n")
    assert separator, "workflow is missing a jobs section"
    return re.findall(r"^\s{4}name:\s*([a-z0-9-]+)\s*$", jobs_text, flags=re.MULTILINE)


def test_branch_protection_runbook_exists_and_references_workflow_sources() -> None:
    assert RUNBOOK_PATH.exists(), "docs/reference/dev/branch-protection.md must exist"
    runbook_text = _read_text(RUNBOOK_PATH)

    assert ".github/workflows/ci.yml" in runbook_text
    assert ".github/workflows/integration.yml" in runbook_text
    assert "tests/ci/test_ci_workflow_contract.py" in runbook_text
    assert "tests/ci/test_integration_workflow_contract.py" in runbook_text


def test_branch_protection_runbook_reflects_pr_vs_push_check_split() -> None:
    ci_workflow_text = _read_text(CI_WORKFLOW_PATH)
    integration_workflow_text = _read_text(INTEGRATION_WORKFLOW_PATH)
    runbook_text = _read_text(RUNBOOK_PATH)

    ci_checks = _extract_job_names(ci_workflow_text)
    integration_checks = _extract_job_names(integration_workflow_text)

    assert ci_checks == ["lint", "unit-tests"]
    assert integration_checks == ["integration-tests"]

    required_pr_line = "Current PR-required checks from `.github/workflows/ci.yml`: " + ", ".join(
        f"`{check}`" for check in ci_checks
    )
    push_only_line = "Push-only checks from `.github/workflows/integration.yml`: " + ", ".join(
        f"`{check}`" for check in integration_checks
    )

    assert required_pr_line in runbook_text
    assert push_only_line in runbook_text
    assert "Do not select `integration-tests` as a required status check for pull requests." in runbook_text
