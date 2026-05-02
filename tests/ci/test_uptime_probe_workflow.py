"""Structural tests for the uptime-probe GitHub Actions workflow.

The workflow itself runs on staging/prod (debbie syncs it from this dev repo).
These tests assert the dev-repo file's structural contract — cron cadence,
target endpoint, dedup label, recovery behavior — so a future edit that
silently loosens any of those gets caught at PR time.

The workflow's *runtime* behavior cannot be exercised here (would require
GitHub Actions infra), so these tests are deliberately limited to file-shape
assertions. The failure mode they catch is "someone refactored the workflow
and broke its dedup/cadence contract"; runtime failures are caught by the
workflow itself opening an issue.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "uptime_probe.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_parsed() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.exists(), f"missing workflow at {WORKFLOW_PATH}"


def test_workflow_runs_on_5_minute_cron(workflow_parsed: dict) -> None:
    # PyYAML parses bare `on:` as Python True. Use both forms to be safe.
    on_block = workflow_parsed.get("on") or workflow_parsed.get(True)
    assert on_block is not None, "workflow has no `on:` trigger block"
    schedules = on_block["schedule"]
    assert any(s["cron"] == "*/5 * * * *" for s in schedules), (
        f"expected '*/5 * * * *' cron, found {schedules}"
    )


def test_workflow_hits_canonical_health_endpoint(workflow_text: str) -> None:
    # The endpoint URL is the contract. If a refactor splits or aliases it,
    # this test forces an explicit decision instead of silent drift.
    assert "civibus.org/api/health/content" in workflow_text


def test_workflow_uses_uptime_incident_label(workflow_text: str) -> None:
    # The label is the dedup key. If it drifts, dedup breaks and the
    # workflow could spam duplicate issues during an outage.
    assert "uptime-incident" in workflow_text


def test_workflow_dedups_via_existing_open_issue_search(workflow_text: str) -> None:
    """Before opening a new issue, the workflow must check for an open one with the label."""
    assert "gh issue list" in workflow_text
    assert "--label uptime-incident" in workflow_text
    assert "--state open" in workflow_text


def test_workflow_closes_issue_on_recovery(workflow_text: str) -> None:
    """When the endpoint returns 200 healthy, the open issue must be closed (not just commented)."""
    assert "gh issue close" in workflow_text


def test_workflow_grants_issues_write_permission(workflow_parsed: dict) -> None:
    """The default GITHUB_TOKEN can't open issues without explicit `issues: write`."""
    permissions = workflow_parsed.get("permissions", {})
    assert permissions.get("issues") == "write", (
        f"workflow needs `issues: write` to manage uptime-incident issues; got {permissions}"
    )


def test_workflow_checks_http_status_code_explicitly(workflow_text: str) -> None:
    """A workflow that opens issues without a status check is a false-positive factory."""
    # The `--write-out '%{http_code}'` is how curl reports the status code.
    # If a future edit drops it, the bash logic would silently always-pass
    # or always-fail.
    assert "%{http_code}" in workflow_text


def test_workflow_uses_jq_for_body_healthy_check(workflow_text: str) -> None:
    """Body parse must check `.healthy == true` explicitly, not just HTTP 200."""
    # Apr 30 incident: /health returned 200 the whole time; only a content-aware
    # check would have caught the empty DB. The probe's contract is that 200 is
    # necessary but not sufficient — body.healthy must also be true.
    assert ".healthy == true" in workflow_text
