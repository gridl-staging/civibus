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


@pytest.fixture(scope="module")
def workflow_steps(workflow_parsed: dict) -> list[dict]:
    return workflow_parsed["jobs"]["probe"]["steps"]


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.exists(), f"missing workflow at {WORKFLOW_PATH}"


def test_workflow_runs_on_5_minute_cron(workflow_parsed: dict) -> None:
    # PyYAML parses bare `on:` as Python True. Use both forms to be safe.
    on_block = workflow_parsed.get("on") or workflow_parsed.get(True)
    assert on_block is not None, "workflow has no `on:` trigger block"
    schedules = on_block["schedule"]
    assert any(s["cron"] == "*/5 * * * *" for s in schedules), f"expected '*/5 * * * *' cron, found {schedules}"


def test_workflow_uses_probe_base_url_as_single_source_of_truth(workflow_parsed: dict, workflow_text: str) -> None:
    """Normal probes must derive from the top-level base URL, not hard-coded host literals."""
    assert workflow_parsed["env"]["PROBE_BASE_URL"] == "https://civibus.shareborough.com"
    assert "${{ env.PROBE_BASE_URL }}/api/health/content" in workflow_text
    assert "civibus.org" not in workflow_text.lower()


def test_workflow_dispatch_validates_full_probe_url_override(workflow_parsed: dict, workflow_text: str) -> None:
    """Manual drills may supply a complete one-run target URL, but only after URL validation."""
    on_block = workflow_parsed.get("on") or workflow_parsed.get(True)
    probe_override = on_block["workflow_dispatch"]["inputs"]["probe_url_override"]
    assert probe_override["type"] == "string"
    assert probe_override["required"] is False
    assert probe_override["default"] == ""
    assert "${{ github.event.inputs.probe_url_override }}" in workflow_text
    assert 'RAW_TARGET="${PROBE_URL_OVERRIDE:-${PROBE_BASE_URL}/api/health/content}"' in workflow_text
    assert 'parsed.scheme != "https"' in workflow_text
    assert "parsed.username is not None or parsed.password is not None" in workflow_text
    assert "parsed.fragment" in workflow_text
    assert "control characters" in workflow_text
    assert "curl --proto '=https' -sS" in workflow_text
    assert '-- "$TARGET"' in workflow_text
    assert 'echo "target=${TARGET}" >> "$GITHUB_OUTPUT"' in workflow_text
    assert "PROBE_TARGET: ${{ steps.probe.outputs.target }}" in workflow_text


def test_probe_detail_output_uses_random_delimiter(workflow_text: str) -> None:
    """Untrusted response excerpts must not be able to predict the multiline output terminator."""
    assert 'DETAIL_DELIMITER="DETAIL_DELIMITER_$(uuidgen)"' in workflow_text
    assert 'echo "detail<<${DETAIL_DELIMITER}"' in workflow_text
    assert "DETAIL_DELIMITER_$$" not in workflow_text


def test_probe_outputs_are_passed_to_shell_via_env(workflow_text: str) -> None:
    """Response-body JSON must not be interpolated directly into shell assignments."""
    assert "PROBE_DETAIL: ${{ steps.probe.outputs.detail }}" in workflow_text
    assert "PROBE_STATUS: ${{ steps.probe.outputs.status }}" in workflow_text
    assert "PROBE_TARGET: ${{ steps.probe.outputs.target }}" in workflow_text
    assert 'DETAIL="${PROBE_DETAIL}"' in workflow_text
    assert 'STATUS="${PROBE_STATUS}"' in workflow_text
    assert 'TARGET="${PROBE_TARGET}"' in workflow_text
    assert 'DETAIL="${{ steps.probe.outputs.detail }}"' not in workflow_text
    assert 'STATUS="${{ steps.probe.outputs.status }}"' not in workflow_text


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


def test_issue_commands_include_explicit_repository_context(workflow_text: str) -> None:
    """Issue commands must not depend on a local git checkout for repo context."""
    required_issue_commands = (
        "gh issue list",
        "gh issue comment",
        "gh issue close",
        "gh issue create",
    )
    for command in required_issue_commands:
        command_index = workflow_text.find(command)
        assert command_index >= 0, f"missing expected command `{command}`"
        repo_arg_index = workflow_text.find('--repo "${{ github.repository }}"', command_index)
        assert repo_arg_index >= 0, (
            f'`{command}` must include `--repo "${{{{ github.repository }}}}"` '
            "to avoid git-checkout-dependent repository discovery"
        )


def test_label_create_command_includes_explicit_repository_context(workflow_text: str) -> None:
    """Label management must also target the current mirror explicitly."""
    label_command_index = workflow_text.find("gh label create uptime-incident")
    assert label_command_index >= 0, "missing label-create command for uptime-incident"
    force_arg_index = workflow_text.find("--force", label_command_index)
    assert force_arg_index >= 0, "label-create command must keep idempotent --force behavior"
    label_command = workflow_text[label_command_index:force_arg_index]
    assert '--repo="${{ github.repository }}"' in label_command, "gh label create must include explicit --repo context"


def test_workflow_warns_on_public_deploy_drift_without_failing_job(
    workflow_text: str, workflow_steps: list[dict]
) -> None:
    drift_step = next(step for step in workflow_steps if step.get("name") == "Warn on public deploy drift")
    script = drift_step["run"]

    assert drift_step["continue-on-error"] is True
    assert "gh api repos/${{ github.repository }}/contents/.debbie/sync_manifest.json" in script
    assert "base64 -d" in script
    assert ".dev_sha" in script
    assert "/api/health/version" in script
    assert "/version.json" in script
    assert "::warning::" in script
    assert "deploy lag" in workflow_text
    assert "cannot detect sync lag" in workflow_text
    assert "Promote this check to fail-closed only after one batch with zero false would-be kills" in workflow_text


def test_workflow_warns_on_donor_search_surface_without_failing_job(workflow_steps: list[dict]) -> None:
    donor_step = next((step for step in workflow_steps if step.get("name") == "Warn on donor search surface"), None)
    assert donor_step is not None, "missing WARN-only donor search surface step"

    issue_step_index = next(
        index
        for index, step in enumerate(workflow_steps)
        if step.get("name") == "Find existing open uptime-incident issue"
    )
    donor_step_index = workflow_steps.index(donor_step)
    script = donor_step["run"]

    assert donor_step_index < issue_step_index
    assert donor_step["continue-on-error"] is True
    assert 'TARGET="${PROBE_BASE_URL%/}/donors?q=smith&by=name"' in script
    assert "curl" in script
    assert "--max-time 30" in script
    assert "grep -q 'data-testid=\"donor-result-row\"'" in script
    assert 'donor_surface_ok target=${TARGET} status=200 marker=data-testid=\\"donor-result-row\\"' in script
    assert "::warning::donor surface probe" in script
    assert "$GITHUB_OUTPUT" not in script
    assert 'echo "healthy=' not in script
    assert 'echo "status=' not in script
    assert 'echo "target=' not in script
    assert "gh issue" not in script
    assert "gh label" not in script
    assert "GH_TOKEN" not in script


def test_workflow_keeps_warn_probe_lightweight_and_issue_flow_unchanged(workflow_text: str) -> None:
    assert "actions/checkout@" not in workflow_text
    assert "uv sync" not in workflow_text
    assert "gh issue create" in workflow_text
    assert "gh issue close" in workflow_text
