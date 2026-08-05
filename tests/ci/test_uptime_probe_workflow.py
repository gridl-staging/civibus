"""Structural tests for the uptime-probe GitHub Actions workflow.

The workflow itself runs on staging/prod (debbie syncs it from this dev repo).
These tests assert the dev-repo file's structural contract — cron cadence,
target endpoint, content-health issue handling, and fatal donor/deploy surface
gates — so a future edit that silently loosens any of those gets caught at PR
time.

The workflow's GitHub Actions runtime cannot be exercised here. Structural
contracts inspect its parsed steps, while rendered-incident contracts execute
only the extracted filing scripts with fake external commands. Together they
catch workflow refactors that break issue identity, deduplication, or cadence.

Restructured 2026-08-03: EVERY surface probe -- content health, donor search,
and public deploy drift -- now feeds one issue-filing decision and one job
failure gate. Previously only content health could open an incident, so donor
search served zero rows for 18+ hours across ten consecutive red runs without
anything being filed. See `ROADMAP.md` `row_id: uptime-alarm-mute`.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

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
    "person": "Check person detail surface",
}
JOB_FAILURE_GATE_STEP_NAME = "Fail the run when any production surface probe was red"
# Any one of these being red means production is not serving correctly, so all
# three must be able to reach the issue-filing decision.
UNHEALTHY_CONDITION_TERMS = (
    "steps.probe.outputs.healthy == 'false'",
    "steps.donor.outcome == 'failure'",
    "steps.drift.outcome == 'failure'",
    "steps.person.outcome == 'failure'",
)


def _step_by_name(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"missing required step {name!r}")


OPEN_ISSUE_STEP_NAME = "Open new uptime-incident issue (endpoint failing, no existing issue)"
COMMENT_ISSUE_STEP_NAME = "Comment on existing issue (endpoint still failing)"
_ACTIONS_EXPRESSION = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")

# Distinctive sentinels, so "the incident text carried the green content probe's
# reading" fails loudly instead of hiding behind a value that could plausibly
# come from another surface. Only the content probe exports `detail`, so the
# green detail string can reach rendered issue text by exactly one route.
CONTENT_RED_STATUS = "503"
CONTENT_GREEN_STATUS = "200"
CONTENT_RED_DETAIL = "content probe reported red"
CONTENT_GREEN_DETAIL = "content_probe_green_detail_must_not_be_rendered"
# Every shape the workflow renders `steps.probe.outputs.status` in: the title
# (`returned ${STATUS} at`), the open body (`**Status:** ${STATUS}`), and the
# comment (`Status: ${STATUS}`). No other surface probe exports a status output,
# so any of these literals in a non-content incident is stale content-health
# text, not the red surface's own reading.
GREEN_CONTENT_STATUS_RENDERINGS = (
    f"returned {CONTENT_GREEN_STATUS}",
    f"**Status:** {CONTENT_GREEN_STATUS}",
    f"Status: {CONTENT_GREEN_STATUS}",
)
# Every way the workflow currently names the content-health surface: the probed
# path, the prose that opens the body, and the owner reference.
CONTENT_HEALTH_IDENTITY_TERMS = (
    "/api/health/content",
    "content health probe",
    "api/health_content.py",
)
DONOR_IDENTITY_TERMS = (
    "donor_search_surface",
    "web/src/routes/donors/+page.server.ts",
    "api/routes/donors.py",
    "api/queries/campaign_finance.py",
)
DRIFT_IDENTITY_TERMS = (
    "public_deploy_drift",
    ".github/workflows/deploy.yml",
)
DRIFT_TARGET_URLS = (
    "https://probe.example/api/health/version",
    "https://probe.example/version.json",
)


def _probe_run_context(
    *, content_red: bool, donor_red: bool, drift_red: bool, person_red: bool = False
) -> dict[str, str]:
    base_url = "https://probe.example"
    return {
        "env.PROBE_BASE_URL": base_url,
        "github.repository": "example/civibus",
        "github.run_id": "4242",
        "github.server_url": "https://github.example",
        "secrets.GITHUB_TOKEN": "fake-token",
        "steps.donor.outcome": "failure" if donor_red else "success",
        "steps.drift.outcome": "failure" if drift_red else "success",
        "steps.person.outcome": "failure" if person_red else "success",
        "steps.find.outputs.number": "17",
        "steps.probe.outputs.detail": CONTENT_RED_DETAIL if content_red else CONTENT_GREEN_DETAIL,
        "steps.probe.outputs.healthy": "false" if content_red else "true",
        "steps.probe.outputs.status": CONTENT_RED_STATUS if content_red else CONTENT_GREEN_STATUS,
        "steps.probe.outputs.target": f"{base_url}/api/health/content",
    }


def _assert_no_green_content_output(rendered_text: str, field: str) -> None:
    """A non-content incident may carry no content-health identity, status, or detail.

    The defect this pins is a partial fix: adding the red surface's identifiers
    while still rendering the healthy content probe's title, status line, and
    detail. That output tells an operator the content endpoint is the incident.
    """
    for term in CONTENT_HEALTH_IDENTITY_TERMS:
        assert term not in rendered_text, (
            f"{field} names the green content-health probe via {term!r}: {rendered_text!r}"
        )
    assert CONTENT_GREEN_DETAIL not in rendered_text, (
        f"{field} carries the healthy content probe's detail: {rendered_text!r}"
    )
    for rendering in GREEN_CONTENT_STATUS_RENDERINGS:
        assert rendering not in rendered_text, (
            f"{field} carries the healthy content probe's status as {rendering!r}: {rendered_text!r}"
        )


def _resolve_actions_expressions(value: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        assert expression in context, f"test harness needs a value for Actions expression {expression!r}"
        return context[expression]

    return _ACTIONS_EXPRESSION.sub(replace, value)


def _write_fake_commands(bin_dir: Path) -> None:
    bin_dir.mkdir()
    gh_path = bin_dir / "gh"
    gh_path.write_text(
        "#!/bin/sh\n"
        "{\n"
        '  for argument in "$@"; do\n'
        "    printf '%s\\000' \"$argument\"\n"
        "  done\n"
        "  printf '\\000'\n"
        '} >> "$GH_CAPTURE_PATH"\n',
        encoding="utf-8",
    )
    gh_path.chmod(0o755)

    date_path = bin_dir / "date"
    date_path.write_text("#!/bin/sh\nprintf '%s\\n' '2026-08-03T20:00:00Z'\n", encoding="utf-8")
    date_path.chmod(0o755)


def _execute_issue_step(
    workflow_steps: list[dict],
    tmp_path: Path,
    step_name: str,
    context: dict[str, str],
) -> list[str]:
    """Execute only an issue text-rendering script with all external commands faked."""
    step = _step_by_name(workflow_steps, step_name)
    run_dir = tmp_path / step_name.split()[0].lower()
    fake_bin = run_dir / "bin"
    run_dir.mkdir()
    _write_fake_commands(fake_bin)
    capture_path = run_dir / "gh_calls.nul"

    environment = os.environ.copy()
    environment.update(
        {
            "GH_CAPTURE_PATH": str(capture_path),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "PROBE_BASE_URL": context["env.PROBE_BASE_URL"],
        }
    )
    for name, value in step.get("env", {}).items():
        environment[name] = _resolve_actions_expressions(str(value), context)

    script = _resolve_actions_expressions(step["run"], context)
    completed = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=run_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (
        f"extracted script for {step_name!r} failed in the hermetic harness:\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )

    calls = [
        [argument.decode("utf-8") for argument in call.split(b"\0")]
        for call in capture_path.read_bytes().split(b"\0\0")
        if call
    ]
    issue_action = "create" if step_name == OPEN_ISSUE_STEP_NAME else "comment"
    matching_calls = [args for args in calls if args[:2] == ["issue", issue_action]]
    assert len(matching_calls) == 1, f"expected one `gh issue {issue_action}` call, got {calls}"
    return matching_calls[0]


def _option_value(arguments: list[str], option: str) -> str:
    option_index = arguments.index(option)
    return arguments[option_index + 1]


def _render_incident_texts(
    workflow_steps: list[dict],
    tmp_path: Path,
    *,
    content_red: bool,
    donor_red: bool,
    drift_red: bool,
    person_red: bool = False,
) -> tuple[str, str, str]:
    context = _probe_run_context(
        content_red=content_red, donor_red=donor_red, drift_red=drift_red, person_red=person_red
    )
    open_arguments = _execute_issue_step(workflow_steps, tmp_path, OPEN_ISSUE_STEP_NAME, context)
    comment_arguments = _execute_issue_step(workflow_steps, tmp_path, COMMENT_ISSUE_STEP_NAME, context)
    return (
        _option_value(open_arguments, "--title"),
        _option_value(open_arguments, "--body"),
        _option_value(comment_arguments, "--body"),
    )


def test_donor_only_incident_rendering_names_donor_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """A donor-only outage must not be rendered as a content-health outage."""
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        content_red=False,
        donor_red=True,
        drift_red=False,
    )

    for field, rendered_text in (
        ("title", title),
        ("open body", open_body),
        ("comment body", comment_body),
    ):
        assert "donor_search_surface" in rendered_text, f"{field} does not name the red donor surface"
        _assert_no_green_content_output(rendered_text, field)
        for term in DRIFT_IDENTITY_TERMS:
            assert term not in rendered_text, f"{field} names the green drift probe via {term!r}"
    assert "https://probe.example/donors?q=smith&by=name" in open_body
    for owner in DONOR_IDENTITY_TERMS[1:]:
        assert owner in open_body
    assert "https://github.example/example/civibus/actions/runs/4242" in comment_body


def test_drift_only_incident_rendering_names_deploy_drift_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """A drift-only outage must not be rendered as a content-health outage."""
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        content_red=False,
        donor_red=False,
        drift_red=True,
    )

    for field, rendered_text in (
        ("title", title),
        ("open body", open_body),
        ("comment body", comment_body),
    ):
        assert "public_deploy_drift" in rendered_text, f"{field} does not name the red drift surface"
        _assert_no_green_content_output(rendered_text, field)
        for term in DONOR_IDENTITY_TERMS:
            assert term not in rendered_text, f"{field} names the green donor probe via {term!r}"
    assert ".github/workflows/deploy.yml" in open_body
    for target_url in DRIFT_TARGET_URLS:
        assert target_url in open_body
        assert target_url in comment_body
    assert "https://github.example/example/civibus/actions/runs/4242" in comment_body


def test_content_only_incident_rendering_preserves_content_health_details(
    workflow_steps: list[dict], tmp_path: Path
) -> None:
    """Preserve the useful existing content-health incident details."""
    context = _probe_run_context(content_red=True, donor_red=False, drift_red=False)
    open_arguments = _execute_issue_step(workflow_steps, tmp_path, OPEN_ISSUE_STEP_NAME, context)
    title = _option_value(open_arguments, "--title")
    body = _option_value(open_arguments, "--body")

    assert "/api/health/content" in title
    assert CONTENT_RED_STATUS in title
    assert "content health probe" in body
    assert "https://probe.example/api/health/content" in body
    assert "api/health_content.py + api/main.py:186" in body
    assert f"**Status:** {CONTENT_RED_STATUS}" in body
    # The detail output does reach the rendered body, which is what makes the
    # green-detail exclusion in `_assert_no_green_content_output` a live guard
    # rather than an assertion about a string the workflow never renders.
    assert CONTENT_RED_DETAIL in body
    for green_probe in DONOR_IDENTITY_TERMS + DRIFT_IDENTITY_TERMS:
        assert green_probe not in title, f"title names the green {green_probe!r}"
        assert green_probe not in body, f"body names the green {green_probe!r}"


def test_two_red_surface_incident_rendering_names_only_current_failures(
    workflow_steps: list[dict], tmp_path: Path
) -> None:
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        content_red=False,
        donor_red=True,
        drift_red=True,
    )

    for field, rendered_text in (
        ("title", title),
        ("open body", open_body),
        ("comment body", comment_body),
    ):
        assert "donor_search_surface" in rendered_text, f"{field} does not name the red donor surface"
        assert "public_deploy_drift" in rendered_text, f"{field} does not name the red drift surface"
        _assert_no_green_content_output(rendered_text, field)
    for owner in DONOR_IDENTITY_TERMS[1:]:
        assert owner in open_body
    assert ".github/workflows/deploy.yml" in open_body
    assert "https://github.example/example/civibus/actions/runs/4242" in comment_body


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
    assert "steps.person.outcome == 'success'" in close_step["if"]


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


def test_workflow_declares_best_effort_four_hour_cadence(workflow_parsed: dict, workflow_text: str) -> None:
    # PyYAML parses bare `on:` as Python True. Use both forms to be safe.
    on_block = workflow_parsed.get("on") or workflow_parsed.get(True)
    assert on_block is not None, "workflow has no `on:` trigger block"
    assert on_block["schedule"] == [{"cron": "0 */4 * * *"}]

    header = " ".join(line.removeprefix("#").strip() for line in workflow_text.split("on:", maxsplit=1)[0].splitlines())
    assert "requests a four-hour GitHub scheduled uptime probe" in header
    assert "GitHub scheduled workflows are best-effort" in header
    assert "n=11" in header
    assert "64-216 minutes" in header
    assert "not a guaranteed delivery interval" in header
    assert "no five-minute SLA or detection guarantee" in header


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
        "|| steps.drift.outcome == 'failure' || steps.person.outcome == 'failure')"
    )
    healthy = (
        "steps.probe.outputs.healthy == 'true' && steps.donor.outcome == 'success' "
        "&& steps.drift.outcome == 'success' && steps.person.outcome == 'success'"
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


def test_workflow_probes_a_person_detail_page_from_the_live_sitemap(workflow_steps: list[dict]) -> None:
    """Person detail is the flagship surface and nothing watched it.

    `/person/<id>` returned HTTP 500 route-wide from 2026-08-03T14:34:16Z for
    over 48 hours. Three checkers existed and none opened a person page: this
    probe's 3 checks, the deploy-time parity list's 14 surfaces, and
    /api/health/content -- which counts rows and cannot observe a render. The
    generalisation is the useful part: every LIST page was probed and no DETAIL
    page reached from a list was ever followed, so a /congress that renders 539
    links to broken pages passed every check.

    The specimen is resolved from the published sitemap rather than hardcoded,
    because a pinned UUID rots on the next reload and would then fail for a
    reason that has nothing to do with the surface being down.
    """
    person_step = _step_by_name(workflow_steps, "Check person detail surface")
    script = person_step["run"]

    # Non-fatal like its siblings so it reaches issue filing; the final job gate
    # re-imposes the failure (test_red_surface_probe_still_fails_the_job).
    assert person_step["continue-on-error"] is True

    # Specimen resolution: read the person sitemap shard, take a real path.
    assert "sitemap-person-0.xml" in script
    assert "/person/" in script
    # An unresolvable specimen must fail closed -- an empty person sitemap is
    # itself a defect and must never read as "nothing to check, so healthy".
    assert "person surface probe no_specimen" in script

    assert "--max-time 30" in script
    assert "set +e" in script
    assert "CURL_EXIT=$?" in script
    assert "set -e" in script
    assert 'if [ "$CURL_EXIT" -ne 0 ]; then' in script
    assert "person surface probe curl_error" in script
    assert 'if [ "$STATUS" != "200" ]; then' in script
    assert "person surface probe http_status" in script

    # Marker validated against live production on 2026-08-05 in BOTH directions:
    # count=0 on the HTTP 500 person page, count=1 on /committee/... which
    # renders the same Breadcrumb component. A status-only check would pass on a
    # 200 that rendered an error body.
    assert 'aria-label="Breadcrumb"' in script
    assert "person surface probe missing_marker" in script

    # Probes never file issues themselves; that is the issue-flow steps' job.
    assert "gh issue" not in script
    assert "GH_TOKEN" not in script


def test_person_only_incident_rendering_names_person_detail_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """A person-only outage must file an incident that names the person surface.

    This is the rendering half of the 2026-08-03 lesson recorded on
    `row_id: uptime-alarm-mute`: issue #3 was titled
    "[uptime] /api/health/content returned 200" while the content probe was
    green and neither red probe was named anywhere. An operator sent to
    api/health_content.py finds {"healthy":true} and learns to distrust the
    alarm. So the incident must name person_detail_surface and must carry no
    content-health identity when content health is green.
    """
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        content_red=False,
        donor_red=False,
        drift_red=False,
        person_red=True,
    )

    assert "person_detail_surface" in title
    for body in (open_body, comment_body):
        assert "person_detail_surface" in body
        assert "sitemap-person-0.xml" in body
        assert "web/src/lib/entity-detail/contract.ts" in body
        # Surfaces that are green must not appear as failures.
        assert "donor_search_surface" not in body
        assert "public_deploy_drift" not in body
        _assert_no_green_content_output(body, "person-only incident body")
