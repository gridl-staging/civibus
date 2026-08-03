"""Structural tests for the uptime-probe GitHub Actions workflow.

The workflow itself runs on staging/prod (debbie syncs it from this dev repo).
These tests assert the dev-repo file's structural contract — cron cadence,
target endpoint, content-health issue handling, and fatal donor/deploy surface
gates — so a future edit that silently loosens any of those gets caught at PR
time.

The workflow's *runtime* behavior cannot be exercised here (would require
GitHub Actions infra), so these tests are deliberately limited to file-shape
assertions. The failure mode they catch is "someone refactored the workflow
and broke its dedup/cadence contract".

Restructured 2026-08-03: EVERY surface probe -- content health, donor search,
and public deploy drift -- now feeds one issue-filing decision and one job
failure gate. Previously only content health could open an incident, so donor
search served zero rows for 18+ hours across ten consecutive red runs without
anything being filed. See `ROADMAP.md` `row_id: uptime-alarm-mute`.
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


SURFACE_PROBE_STEPS = {
    "donor": "Check donor search surface",
    "drift": "Check public deploy drift",
}
JOB_FAILURE_GATE_STEP_NAME = "Fail the run when any production surface probe was red"
# Any one of these being red means production is not serving correctly, so all
# three must be able to reach the issue-filing decision.
UNHEALTHY_CONDITION_TERMS = (
    "steps.probe.outputs.healthy == 'false'",
    "steps.donor.outcome == 'failure'",
    "steps.drift.outcome == 'failure'",
)


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"missing required step {name!r}")


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.exists(), f"missing workflow at {WORKFLOW_PATH}"


def test_every_surface_probe_can_open_an_incident_issue(workflow_steps: list[dict]) -> None:
    """A probe that cannot file an issue is not an alarm.

    2026-08-03: the donor-surface check failed ten consecutive scheduled runs
    (`30764126828` through `30820555844`) reporting HTTP 200 with zero
    `data-testid="donor-result-row"` markers, and no incident issue was ever
    opened -- because issue filing consulted only the content-health probe.
    Donor search was dead for 18+ hours and the alarm stayed silent.
    """
    open_step = _step_by_name(workflow_steps, "Open new uptime-incident issue (endpoint failing, no existing issue)")
    comment_step = _step_by_name(workflow_steps, "Comment on existing issue (endpoint still failing)")
    close_step = _step_by_name(workflow_steps, "Close existing issue (endpoint recovered)")

    for step in (open_step, comment_step):
        for term in UNHEALTHY_CONDITION_TERMS:
            assert term in step["if"], f"{step['name']!r} must file an incident when {term}"

    # Recovery is the conjunction: an issue may only close when every surface is
    # green, otherwise a content-health recovery would close an issue that donor
    # search is still failing.
    assert "steps.probe.outputs.healthy == 'true'" in close_step["if"]
    assert "steps.donor.outcome == 'success'" in close_step["if"]
    assert "steps.drift.outcome == 'success'" in close_step["if"]


def test_surface_probes_run_before_issue_filing(workflow_steps: list[dict]) -> None:
    """Outcomes can only be read by later steps, so every probe must precede the issue flow."""
    step_names = [step.get("name") for step in workflow_steps]
    find_position = step_names.index("Find existing open uptime-incident issue")

    for step_id, step_name in SURFACE_PROBE_STEPS.items():
        step = _step_by_name(workflow_steps, step_name)
        assert step.get("id") == step_id, f"{step_name!r} must expose id {step_id!r} for its outcome to be readable"
        assert step_names.index(step_name) < find_position, (
            f"{step_name!r} runs after issue filing, so its result cannot open an incident"
        )


def test_red_surface_probe_still_fails_the_job(workflow_steps: list[dict]) -> None:
    """`continue-on-error` is only acceptable because a job-level gate re-imposes the failure.

    Without this step the probes would become advisory: the run would go green
    while production was broken, which is strictly worse than the silent-alarm
    state it replaced.
    """
    gate_step = _step_by_name(workflow_steps, JOB_FAILURE_GATE_STEP_NAME)
    script = gate_step["run"]
    step_names = [step.get("name") for step in workflow_steps]

    assert gate_step["if"] == "${{ always() }}", "the gate must evaluate even when an earlier step already failed"
    assert step_names.index(JOB_FAILURE_GATE_STEP_NAME) == len(step_names) - 1, "the gate must be the final step"
    for step_id in SURFACE_PROBE_STEPS:
        assert f"steps.{step_id}.outcome" in gate_step.get("env", {}).get(f"{step_id.upper()}_OUTCOME", ""), (
            f"gate must read steps.{step_id}.outcome"
        )
    assert "exit 1" in script


def test_surface_probes_are_non_fatal_only_where_the_gate_covers_them(workflow_steps: list[dict]) -> None:
    """Every `continue-on-error` step must be one the final gate re-checks."""
    gate_step = _step_by_name(workflow_steps, JOB_FAILURE_GATE_STEP_NAME)
    covered_ids = {step_id for step_id in SURFACE_PROBE_STEPS if f"{step_id.upper()}_OUTCOME" in gate_step["env"]}

    for step in workflow_steps:
        if step.get("continue-on-error") is not True:
            continue
        assert step.get("id") in covered_ids, (
            f"step {step.get('name')!r} suppresses its own failure but the job gate does not re-check it"
        )


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


def test_workflow_fails_on_public_deploy_drift(workflow_text: str, workflow_steps: list[dict]) -> None:
    drift_step = next(step for step in workflow_steps if step.get("name") == "Check public deploy drift")
    script = drift_step["run"]

    # Changed 2026-08-03: the step now suppresses its own abort so the issue
    # flow downstream can read its outcome and file an incident. It is still
    # fatal to the job -- `Fail the run when any production surface probe was
    # red` re-imposes that, and test_surface_probes_are_non_fatal_only_where_
    # the_gate_covers_them proves no suppressed step escapes the gate.
    assert drift_step["continue-on-error"] is True
    assert "gh api repos/${{ github.repository }}/contents/.debbie/sync_manifest.json" in script
    assert "base64 -d" in script
    assert "jq -r '.dev_sha // empty'" in script
    assert '[[ ! "$expected_sha" =~ ^[0-9a-f]{40}$ ]]' in script
    assert 'curl -fsS "${PROBE_BASE_URL%/}/api/health/version"' in script
    assert 'curl -fsS "${PROBE_BASE_URL%/}/version.json"' in script
    assert '[[ "$api_sha" == "$expected_sha" && "$web_sha" == "$expected_sha" ]]' in script
    assert 'echo "deploy_drift_ok expected=$expected_sha api=$api_sha web=$web_sha"' in script
    assert (
        'echo "::error::deploy lag check could not read a valid dev_sha from the mirror sync manifest"\n  exit 1'
    ) in script
    assert (
        'echo "::error::deploy lag detected for ${PROBE_BASE_URL}: expected=$expected_sha '
        "api=$api_sha web=$web_sha. This mirror-side warning cannot detect sync lag; "
        'the dev-repo parity probe owns that."\n'
        "exit 1"
    ) in script
    assert "cannot detect sync lag" in workflow_text


def test_workflow_fails_on_donor_search_surface(workflow_steps: list[dict]) -> None:
    donor_step = next(step for step in workflow_steps if step.get("name") == "Check donor search surface")
    script = donor_step["run"]

    # Reordered 2026-08-03: all three surface probes now run BEFORE the issue
    # flow. Under the old order the donor and drift checks came last and could
    # only redden a workflow nobody reads.
    ordered_step_names = (
        "Probe content health endpoint",
        "Check donor search surface",
        "Check public deploy drift",
        "Find existing open uptime-incident issue",
        "Close existing issue (endpoint recovered)",
        "Comment on existing issue (endpoint still failing)",
        "Open new uptime-incident issue (endpoint failing, no existing issue)",
    )
    ordered_step_indexes = [
        next(index for index, step in enumerate(workflow_steps) if step.get("name") == name)
        for name in ordered_step_names
    ]

    assert ordered_step_indexes == sorted(ordered_step_indexes)
    # Changed 2026-08-03 for the same reason as the drift step above: a probe
    # that aborts the job before issue filing can never open an incident.
    assert donor_step["continue-on-error"] is True
    assert 'TARGET="${PROBE_BASE_URL%/}/donors?q=smith&by=name"' in script
    assert "--max-time 30" in script
    assert "set +e" in script
    assert "CURL_EXIT=$?" in script
    assert "set -e" in script
    assert 'if [ "$CURL_EXIT" -ne 0 ]; then' in script
    assert ('echo "::error::donor surface probe curl_error target=${TARGET} exit=${CURL_EXIT}"\n  exit 1') in script
    assert 'if [ "$STATUS" != "200" ]; then' in script
    assert (
        'echo "::error::donor surface probe http_status target=${TARGET} status=${STATUS} '
        'body=${BODY_EXCERPT}"\n'
        "  exit 1"
    ) in script
    assert 'if grep -q \'data-testid="donor-result-row"\' "$BODY_FILE"; then' in script
    assert 'donor_surface_ok target=${TARGET} status=200 marker=data-testid=\\"donor-result-row\\"' in script
    assert (
        'echo "::error::donor surface probe missing_marker target=${TARGET} status=${STATUS} '
        'marker=data-testid=\\"donor-result-row\\" body=${BODY_EXCERPT}"\n'
        "exit 1"
    ) in script
    assert "$GITHUB_OUTPUT" not in script
    assert 'echo "healthy=' not in script
    assert 'echo "status=' not in script
    assert 'echo "target=' not in script
    assert "gh issue" not in script
    assert "gh label" not in script
    assert "GH_TOKEN" not in script


def test_workflow_preserves_content_health_issue_flow_before_fatal_gates(
    workflow_text: str, workflow_steps: list[dict]
) -> None:
    find_step = next(step for step in workflow_steps if step.get("name") == "Find existing open uptime-incident issue")
    close_step = next(
        step for step in workflow_steps if step.get("name") == "Close existing issue (endpoint recovered)"
    )
    comment_step = next(
        step for step in workflow_steps if step.get("name") == "Comment on existing issue (endpoint still failing)"
    )
    open_step = next(
        step
        for step in workflow_steps
        if step.get("name") == "Open new uptime-incident issue (endpoint failing, no existing issue)"
    )

    assert find_step["id"] == "find"
    assert "if" not in find_step
    assert find_step["run"].strip().startswith("NUMBER=$(gh issue list")
    # Widened 2026-08-03 from content-health-only to every production surface.
    # Recovery is the conjunction (close only when all three are green) and
    # failure is the disjunction (any one red files an incident);
    # test_every_surface_probe_can_open_an_incident_issue owns that rule.
    unhealthy = (
        "(steps.probe.outputs.healthy == 'false' || steps.donor.outcome == 'failure' "
        "|| steps.drift.outcome == 'failure')"
    )
    healthy = (
        "steps.probe.outputs.healthy == 'true' && steps.donor.outcome == 'success' && steps.drift.outcome == 'success'"
    )
    assert close_step["if"] == f"{healthy} && steps.find.outputs.number != ''"
    assert comment_step["if"] == f"{unhealthy} && steps.find.outputs.number != ''"
    assert open_step["if"] == f"{unhealthy} && steps.find.outputs.number == ''"
    assert "actions/checkout@" not in workflow_text
    assert "uv sync" not in workflow_text
    assert "gh issue create" in workflow_text
    assert "gh issue close" in workflow_text
    assert "WARN-only shadow mode" not in workflow_text
    assert "Promote this check to fail-closed only after" not in workflow_text
    assert "The job ALWAYS exits 0" not in workflow_text
