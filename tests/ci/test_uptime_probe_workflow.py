"""Structural and hermetic contracts for the uptime-probe Actions workflow.

The tests inspect parsed steps and execute extracted scripts with fake external
commands to catch breaks in issue identity, dedup, cadence, and fatal gates.

Restructured 2026-08-03 (`ROADMAP.md` `row_id: uptime-alarm-mute`): every
surface probe now feeds one issue-filing decision and one job failure gate,
after donor search served zero rows for 18+ hours with no incident filed.

Reusable helpers live in `tests.ci.uptime_probe_workflow_harness`; contracts
stay in this owner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.ci.uptime_probe_workflow_harness import (
    ARBITRARY_MANIFEST_ROW,
    ARBITRARY_SURFACE_ID,
    ARBITRARY_SURFACE_MARKER,
    ARBITRARY_SURFACE_PATH,
    CONTENT_RED_DETAIL,
    CONTENT_RED_STATUS,
    DONOR_IDENTITY_TERMS,
    DONOR_MANIFEST_ROW,
    DRIFT_IDENTITY_TERMS,
    DRIFT_TARGET_URLS,
    FAKE_CURL_FAIL_MODE_CASES,
    JOB_FAILURE_GATE_STEP_NAME,
    OPEN_ISSUE_STEP_NAME,
    PARITY_ONLY_MANIFEST_ROW,
    PERSON_MANIFEST_ROW,
    PUBLIC_SURFACE_FAILURE_BODY,
    PUBLIC_SURFACE_MANIFEST_ERROR,
    PUBLIC_SURFACE_MANIFEST_FETCH,
    PUBLIC_SURFACE_MANIFEST_HEADER,
    PUBLIC_SURFACE_MANIFEST_PATH,
    ProbeRunState,
    PublicSurfaceFailureCase,
    PublicSurfaceFixture,
    SURFACE_PROBE_STEPS,
    UNHEALTHY_CONDITION_TERMS,
    WORKFLOW_PATH,
    _assert_no_green_content_output,
    _execute_issue_step,
    _execute_public_surfaces_step,
    _incident_fields,
    _option_value,
    _probe_run_context,
    _render_incident_texts,
    _resolve_actions_expressions,
    _run_final_gate,
    _run_public_surface_fake_curl_channels,
    _step_by_name,
)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_parsed() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow_steps(workflow_parsed: dict) -> list[dict]:
    return workflow_parsed["jobs"]["probe"]["steps"]


def test_donor_only_incident_rendering_names_donor_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """A donor-only outage must not be rendered as a content-health outage."""
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        ProbeRunState.public_surface_failure("donor_search_surface"),
    )

    for field, rendered_text in _incident_fields(title, open_body, comment_body):
        assert "donor_search_surface" in rendered_text, f"{field} does not name the red donor surface"
        _assert_no_green_content_output(rendered_text, field)
        for term in DRIFT_IDENTITY_TERMS:
            assert term not in rendered_text, f"{field} names the green drift probe via {term!r}"
    assert "https://github.example/example/civibus/actions/runs/4242" in comment_body


def test_drift_only_incident_rendering_names_deploy_drift_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """A drift-only outage must not be rendered as a content-health outage."""
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        ProbeRunState.drift_failure(),
    )

    for field, rendered_text in _incident_fields(title, open_body, comment_body):
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
    context = _probe_run_context(ProbeRunState.content_failure())
    open_arguments = _execute_issue_step(workflow_steps, tmp_path, OPEN_ISSUE_STEP_NAME, context)
    title = _option_value(open_arguments, "--title")
    body = _option_value(open_arguments, "--body")

    assert "/api/health/content" in title
    assert CONTENT_RED_STATUS in title
    assert "content health probe" in body
    assert "https://probe.example/api/health/content" in body
    assert "api/health_content.py + api/main.py:186" in body
    assert f"**Status:** {CONTENT_RED_STATUS}" in body
    assert CONTENT_RED_DETAIL in body  # keeps the green-detail exclusion a live guard
    for green_probe in DONOR_IDENTITY_TERMS + DRIFT_IDENTITY_TERMS:
        assert green_probe not in title, f"title names the green {green_probe!r}"
        assert green_probe not in body, f"body names the green {green_probe!r}"


def test_two_red_surface_incident_rendering_names_only_current_failures(
    workflow_steps: list[dict], tmp_path: Path
) -> None:
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        ProbeRunState.public_surface_failure("donor_search_surface", drift_red=True),
    )

    for field, rendered_text in _incident_fields(title, open_body, comment_body):
        assert "donor_search_surface" in rendered_text, f"{field} does not name the red donor surface"
        assert "public_deploy_drift" in rendered_text, f"{field} does not name the red drift surface"
        _assert_no_green_content_output(rendered_text, field)
    assert ".github/workflows/deploy.yml" in open_body
    assert "https://github.example/example/civibus/actions/runs/4242" in comment_body


@pytest.mark.parametrize(
    ("manifest_text", "manifest_fetch_exit"),
    (
        pytest.param(
            f"{PUBLIC_SURFACE_MANIFEST_HEADER}\n{PERSON_MANIFEST_ROW}\nmalformed\trow\n",
            0,
            id="malformed-manifest",
        ),
        pytest.param(
            f"{PUBLIC_SURFACE_MANIFEST_HEADER}\n{DONOR_MANIFEST_ROW}\n",
            19,
            id="manifest-fetch-failure",
        ),
        pytest.param(
            f"{PUBLIC_SURFACE_MANIFEST_HEADER}\n"
            f"{DONOR_MANIFEST_ROW.replace('/donors?q=smith&by=name', '@attacker.example/person/specimen')}\n",
            0,
            id="authority-switching-path",
        ),
        pytest.param(
            f"{PUBLIC_SURFACE_MANIFEST_HEADER}\n"
            f"{DONOR_MANIFEST_ROW.replace('/donors?q=smith&by=name', '/public/%252e%252e/api/private')}\n",
            0,
            id="encoded-traversal-path",
        ),
    ),
)
def test_public_surface_manifest_errors_fail_closed_and_name_manifest_error(
    workflow_steps: list[dict],
    tmp_path: Path,
    manifest_text: str,
    manifest_fetch_exit: int,
) -> None:
    """Manifest acquisition/parse failures must page with a stable identity."""
    probe_result, outputs, _ = _execute_public_surfaces_step(
        workflow_steps,
        tmp_path,
        manifest_text,
        fixture=PublicSurfaceFixture(manifest_fetch_exit=manifest_fetch_exit),
    )
    assert probe_result.returncode != 0 or outputs.get("healthy") != "true", (
        "manifest failure was reported healthy:\n"
        f"stdout={probe_result.stdout}\nstderr={probe_result.stderr}\noutputs={outputs}"
    )
    assert "fixture_curl_target=" not in probe_result.stderr, (
        "a rejected manifest performed an HTTP request before failing closed:\n"
        f"stdout={probe_result.stdout}\nstderr={probe_result.stderr}"
    )

    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        ProbeRunState(
            content_red=False,
            drift_red=False,
            public_surfaces_detail=outputs.get("detail", ""),
            public_surfaces_healthy=outputs.get("healthy", ""),
            public_surfaces_outcome="failure" if probe_result.returncode else "success",
        ),
    )
    for field, rendered_text in _incident_fields(title, open_body, comment_body):
        assert PUBLIC_SURFACE_MANIFEST_ERROR in rendered_text, (
            f"{field} lacks the stable manifest-error identity after fetch/parse failure: {rendered_text!r}"
        )
        _assert_no_green_content_output(rendered_text, field)

    # Harder shape: the step died before writing GITHUB_OUTPUT at all, so both
    # outputs are absent rather than empty. The incident must still name the
    # manifest error instead of rendering a blank surface identity.
    absent_outputs_dir = tmp_path / "absent_public_surface_outputs"
    absent_outputs_dir.mkdir()
    for field, rendered_text in zip(
        ("title", "open body", "comment body"),
        _render_incident_texts(
            workflow_steps,
            absent_outputs_dir,
            ProbeRunState.missing_public_surface_outputs(outcome="failure"),
        ),
        strict=True,
    ):
        assert PUBLIC_SURFACE_MANIFEST_ERROR in rendered_text, (
            f"{field} lacks the manifest-error identity when the step wrote no outputs: {rendered_text!r}"
        )
        _assert_no_green_content_output(rendered_text, field)


def test_actions_expression_harness_evaluates_output_fallbacks() -> None:
    """The harness must evaluate `||` the way Actions does, or it rejects correct workflows.

    A fail-closed step names a manifest abort via
    `${{ steps.public_surfaces.outputs.detail || 'public_surface_manifest_error' }}`;
    resolving that as one literal lookup key would render an empty identity, so
    the rendering specimens above are only trustworthy if this holds.
    """
    template = "${{ steps.public_surfaces.outputs.detail || 'public_surface_manifest_error' }}"
    context = _probe_run_context(ProbeRunState.public_surface_failure("donor_search_surface"))
    assert _resolve_actions_expressions(template, context) == "donor_search_surface"
    assert context["steps.public_surfaces.outcome"] == "failure"

    # Absent and empty are both falsy for a string operand, so both fall through.
    del context["steps.public_surfaces.outputs.detail"]
    assert _resolve_actions_expressions(template, context) == PUBLIC_SURFACE_MANIFEST_ERROR
    context["steps.public_surfaces.outputs.detail"] = ""
    assert _resolve_actions_expressions(template, context) == PUBLIC_SURFACE_MANIFEST_ERROR

    # Actions casts any non-empty string to true, so `healthy=false` is truthy
    # and must win over its fallback -- resolving it to 'true' would silently
    # convert a red surface into a green one.
    context["steps.public_surfaces.outputs.healthy"] = "false"
    assert _resolve_actions_expressions("${{ steps.public_surfaces.outputs.healthy || 'true' }}", context) == "false"

    # Operators this harness does not model must fail loudly, not resolve to
    # something plausible.
    with pytest.raises(AssertionError):
        _resolve_actions_expressions("${{ steps.probe.outputs.healthy == 'true' || 'x' }}", context)


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.exists(), f"missing workflow at {WORKFLOW_PATH}"


def test_every_surface_probe_can_open_an_incident_issue(workflow_steps: list[dict]) -> None:
    """A probe that cannot file an issue is not an alarm.

    2026-08-03: the donor-surface check failed ten consecutive runs reporting
    HTTP 200 with zero donor markers, yet no incident issue opened -- filing
    consulted only the content-health probe. See `row_id: uptime-alarm-mute`.
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
    assert "steps.public_surfaces.outcome == 'success'" in close_step["if"]
    assert "steps.public_surfaces.outputs.healthy == 'true'" in close_step["if"]
    assert "steps.drift.outcome == 'success'" in close_step["if"]


def test_surface_probes_run_before_issue_filing(workflow_steps: list[dict]) -> None:
    """Outcomes can only be read by later steps, so every probe must precede the issue flow."""
    step_names = [step.get("name") for step in workflow_steps]
    find_position = step_names.index("Find existing open uptime-incident issue")

    for step_id, step_name in SURFACE_PROBE_STEPS.items():
        step = _step_by_name(workflow_steps, step_name, step_id=step_id)
        assert step.get("id") == step_id, (
            f"{step.get('name')!r} must expose id {step_id!r} for its outcome to be readable"
        )
        assert step.get("continue-on-error") is True, (
            f"{step.get('name')!r} must preserve issue filing after a red probe"
        )
        assert step_names.index(step.get("name")) < find_position, (
            f"{step.get('name')!r} runs after issue filing, so its result cannot open an incident"
        )


def test_red_surface_probe_still_fails_the_job(workflow_steps: list[dict]) -> None:
    """`continue-on-error` is only acceptable because a job-level gate re-imposes the failure.

    Without this gate the probes are advisory: the run goes green while
    production is broken -- strictly worse than the silent-alarm state it replaced.
    """
    gate_step = _step_by_name(workflow_steps, JOB_FAILURE_GATE_STEP_NAME)
    script = gate_step["run"]
    step_names = [step.get("name") for step in workflow_steps]

    assert gate_step["if"] == "${{ always() }}", "the gate must evaluate even when an earlier step already failed"
    assert step_names.index(JOB_FAILURE_GATE_STEP_NAME) == len(step_names) - 1, "the gate must be the final step"
    gate_env = gate_step.get("env", {})
    assert "steps.public_surfaces.outcome" in gate_env.get("PUBLIC_SURFACES_OUTCOME", "")
    assert "steps.public_surfaces.outputs.healthy" in gate_env.get("PUBLIC_SURFACES_HEALTHY", "")
    assert "steps.drift.outcome" in gate_env.get("DRIFT_OUTCOME", "")
    assert "PUBLIC_SURFACES_OUTCOME" in script
    assert "PUBLIC_SURFACES_HEALTHY" in script
    assert "DRIFT_OUTCOME" in script
    assert "exit 1" in script


def test_final_gate_fails_closed_on_unhealthy_public_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """Execute the gate script: a structural mention of the var is not fail-closed behavior.

    `test_red_surface_probe_still_fails_the_job` only proves the gate *names*
    `PUBLIC_SURFACES_HEALTHY` and contains an `exit 1`; a gate that logs the var
    next to an unreachable `exit 1` would satisfy it while a red surface stayed
    green. This runs the extracted gate under four inputs and asserts the exit
    code the job would take; the green control (exit 0) keeps the reds honest.
    """
    # Green control: a live specimen that must exit 0.
    green = _run_final_gate(
        workflow_steps,
        tmp_path,
        "green",
        ProbeRunState.all_green(),
    )
    assert green.returncode == 0, f"all-green gate should pass:\nstdout={green.stdout}\nstderr={green.stderr}"

    red_cases = (
        (
            "healthy_false",
            ProbeRunState.public_surface_failure(outcome="success"),
        ),
        (
            "healthy_missing",
            ProbeRunState.missing_public_surface_outputs(),
        ),
        (
            "outcome_failure",
            ProbeRunState.public_surface_outcome_failure(),
        ),
    )
    for case_name, state in red_cases:
        red = _run_final_gate(workflow_steps, tmp_path, case_name, state)
        assert red.returncode != 0, f"gate treated {case_name!r} as green:\n{red.stdout}\n{red.stderr}"


@pytest.mark.parametrize(("fail_flag", "expected_returncode", "keeps_body"), FAKE_CURL_FAIL_MODE_CASES)
def test_fake_curl_models_only_http_fail_mode_flags(
    tmp_path: Path, fail_flag: str, expected_returncode: int, keeps_body: bool
) -> None:
    # Real curl discards the HTTP error body under `-f`/`--fail`; only `--fail-with-body` hands it back.
    streamed, saved_body = _run_public_surface_fake_curl_channels(tmp_path, fail_flag, "-sS")
    assert streamed.returncode == expected_returncode, f"{fail_flag}: {streamed.stdout}\n{streamed.stderr}"
    for channel, text in (("stdout", streamed.stdout), ("--output", saved_body)):
        assert (PUBLIC_SURFACE_FAILURE_BODY in text) is keeps_body, f"{fail_flag} {channel} body={text!r}"


def test_surface_probes_are_non_fatal_only_where_the_gate_covers_them(workflow_steps: list[dict]) -> None:
    """Every `continue-on-error` step must be one the final gate re-checks."""
    gate_step = _step_by_name(workflow_steps, JOB_FAILURE_GATE_STEP_NAME)
    covered_ids = {
        "public_surfaces" if "PUBLIC_SURFACES_OUTCOME" in gate_step["env"] else "",
        "drift" if "DRIFT_OUTCOME" in gate_step["env"] else "",
    }

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
    """`--write-out '%{http_code}'` is the status check; dropping it always-passes."""
    assert "%{http_code}" in workflow_text


def test_workflow_uses_jq_for_body_healthy_check(workflow_text: str) -> None:
    """Body parse must check `.healthy == true` (Apr 30: 200 the whole time, empty DB)."""
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


def test_public_surface_manifest_fetches_exact_revision_without_checkout(
    workflow_text: str, workflow_steps: list[dict], tmp_path: Path
) -> None:
    """The executed step reads the manifest at the run's exact revision, with no checkout.

    The structural literal can survive in a comment or dead branch, so this
    closes on the argv the step actually hands `gh`: exactly one read, of this
    path, at `github.sha`, whose decoded body is what the step then parsed.
    """
    public_surfaces_step = _step_by_name(workflow_steps, None, step_id="public_surfaces")
    assert PUBLIC_SURFACE_MANIFEST_FETCH in public_surfaces_step["run"]
    assert "actions/checkout@" not in workflow_text
    assert "uv sync" not in workflow_text

    manifest_run = _execute_public_surfaces_step(
        workflow_steps,
        tmp_path,
        "\n".join((PUBLIC_SURFACE_MANIFEST_HEADER, DONOR_MANIFEST_ROW, PERSON_MANIFEST_ROW, "")),
    )
    context = _probe_run_context(ProbeRunState.all_green())
    expected_endpoint = (
        f"repos/{context['github.repository']}/contents/{PUBLIC_SURFACE_MANIFEST_PATH}?ref={context['github.sha']}"
    )
    api_calls = [call for call in manifest_run.gh_calls if call[:1] == ["api"]]
    assert len(api_calls) == 1, f"expected exactly one manifest `gh api` read, got {manifest_run.gh_calls}"
    arguments = api_calls[0]
    expected_arguments = ["api", expected_endpoint, "--jq", ".content"]
    assert arguments == expected_arguments, (
        "the executed manifest fetch did not use the required exact argv: "
        f"expected={expected_arguments!r} actual={arguments!r}"
    )
    # Proves the fetched bytes are the manifest the step parsed, so a step that
    # read the right URL and then ignored the response still fails here.
    assert manifest_run.outputs.get("healthy") == "true", (
        f"stdout={manifest_run.result.stdout}\nstderr={manifest_run.result.stderr}\noutputs={manifest_run.outputs}"
    )
    assert "donor_search_surface" in manifest_run.result.stdout


def test_public_surface_membership_is_manifest_driven_not_hardcoded(workflow_steps: list[dict], tmp_path: Path) -> None:
    """An arbitrary fatal row -- id/path/marker embedded nowhere else -- must drive execution.

    A workflow that fetches then ignores the manifest could fool fixed donor
    and person specimens. This arbitrary row proves its id, path, and marker
    determine the target, verdict, and exported failure identity.
    """
    manifest_text = "\n".join((PUBLIC_SURFACE_MANIFEST_HEADER, ARBITRARY_MANIFEST_ROW, PERSON_MANIFEST_ROW, ""))
    expected_target = f"fixture_curl_target=https://probe.example{ARBITRARY_SURFACE_PATH}"

    # Marker present in the body -> the manifest-declared marker check passes.
    healthy_dir = tmp_path / "arbitrary_healthy"
    healthy_dir.mkdir()
    healthy_run = _execute_public_surfaces_step(
        workflow_steps,
        healthy_dir,
        manifest_text,
        fixture=PublicSurfaceFixture(
            arbitrary_path=ARBITRARY_SURFACE_PATH,
            arbitrary_body=f"<html><body>{ARBITRARY_SURFACE_MARKER}</body></html>",
        ),
    )
    assert expected_target in healthy_run.result.stderr, (
        f"the step never fetched the manifest-declared path:\nstderr={healthy_run.result.stderr}"
    )
    assert healthy_run.outputs.get("healthy") == "true", (
        f"arbitrary row with a matching marker was not green:\n"
        f"stdout={healthy_run.result.stdout}\nstderr={healthy_run.result.stderr}\noutputs={healthy_run.outputs}"
    )
    assert ARBITRARY_SURFACE_ID in healthy_run.result.stdout, (
        f"the step did not act on the manifest surface id:\nstdout={healthy_run.result.stdout}"
    )

    # Same path, but the marker the manifest declared is absent from the body ->
    # the verdict flips and the exported identity is the manifest's surface id.
    red_dir = tmp_path / "arbitrary_red"
    red_dir.mkdir()
    red_run = _execute_public_surfaces_step(
        workflow_steps,
        red_dir,
        manifest_text,
        fixture=PublicSurfaceFixture(
            arbitrary_path=ARBITRARY_SURFACE_PATH,
            arbitrary_body="<html><body>marker absent from this body</body></html>",
        ),
    )
    assert expected_target in red_run.result.stderr, (
        f"the red arm never fetched the manifest-declared path:\nstderr={red_run.result.stderr}"
    )
    assert red_run.outputs.get("healthy") == "false", (
        f"a missing manifest marker did not turn the surface red:\n"
        f"stdout={red_run.result.stdout}\nstderr={red_run.result.stderr}\noutputs={red_run.outputs}"
    )
    assert ARBITRARY_SURFACE_ID in red_run.outputs.get("detail", ""), (
        f"the exported failure identity was not the manifest surface id: {red_run.outputs!r}"
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


def test_manifest_public_surface_scope_runs_only_fatal_uptime_rows(workflow_steps: list[dict], tmp_path: Path) -> None:
    """Donor/person are fatal uptime rows; parity-only rows do not affect outputs."""
    manifest_text = "\n".join(
        (
            PUBLIC_SURFACE_MANIFEST_HEADER,
            DONOR_MANIFEST_ROW,
            PERSON_MANIFEST_ROW,
            PARITY_ONLY_MANIFEST_ROW,
            "",
        )
    )
    result, outputs, _ = _execute_public_surfaces_step(workflow_steps, tmp_path, manifest_text)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert outputs.get("healthy") == "true", outputs
    assert "donor_search_surface" in result.stdout
    assert "person_detail_surface" in result.stdout
    fetched_targets = result.stderr.splitlines()
    for expected_target in (
        "fixture_curl_target=https://probe.example/donors?q=smith&by=name",
        "fixture_curl_target=https://probe.example/sitemap-person-0.xml",
        "fixture_curl_target=https://probe.example/person/fixture-person",
    ):
        assert fetched_targets.count(expected_target) == 1, (
            f"fatal manifest target was not fetched exactly once: {expected_target!r}\nstderr={result.stderr}"
        )
    combined_evidence = "\n".join((result.stdout, result.stderr, outputs.get("detail", "")))
    assert "parity_only_surface" not in combined_evidence
    assert "/parity-only" not in combined_evidence


@pytest.mark.parametrize(
    "failure_case",
    (
        pytest.param(
            PublicSurfaceFailureCase(
                "/donors?q=smith&by=name",
                "donor_search_surface",
                "person_detail_surface",
            ),
            id="donor-page-failure",
        ),
        pytest.param(
            PublicSurfaceFailureCase(
                "/person/fixture-person",
                "person_detail_surface",
                "donor_search_surface",
            ),
            id="person-detail-failure",
        ),
    ),
)
def test_public_surface_red_rows_emit_unhealthy_output_and_incident_identity(
    workflow_steps: list[dict],
    tmp_path: Path,
    failure_case: PublicSurfaceFailureCase,
) -> None:
    """A real donor/person probe failure must drive the exported alarm identity."""
    failure_path, failing_surface_id, green_surface_id = failure_case
    manifest_text = "\n".join(
        (
            PUBLIC_SURFACE_MANIFEST_HEADER,
            DONOR_MANIFEST_ROW,
            PERSON_MANIFEST_ROW,
            "",
        )
    )
    probe_result, outputs, _ = _execute_public_surfaces_step(
        workflow_steps,
        tmp_path,
        manifest_text,
        fixture=PublicSurfaceFixture(failure_path=failure_path),
    )

    assert outputs.get("healthy") == "false", (
        f"red {failing_surface_id} specimen did not export healthy=false:\n"
        f"stdout={probe_result.stdout}\nstderr={probe_result.stderr}\noutputs={outputs}"
    )
    assert failing_surface_id in outputs.get("detail", ""), outputs
    assert green_surface_id not in outputs.get("detail", ""), outputs

    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        ProbeRunState.public_surface_failure(
            outputs["detail"],
            outcome="failure" if probe_result.returncode else "success",
        ),
    )
    for field, rendered_text in _incident_fields(title, open_body, comment_body):
        assert failing_surface_id in rendered_text, (
            f"{field} lost the step-exported red surface identity: {rendered_text!r}"
        )
        assert green_surface_id not in rendered_text, (
            f"{field} incorrectly names green surface {green_surface_id!r}: {rendered_text!r}"
        )
        _assert_no_green_content_output(rendered_text, field)


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
    # Recovery is the conjunction (close only when all owners are green) and
    # failure is the disjunction (any one red files an incident);
    # test_every_surface_probe_can_open_an_incident_issue owns that rule.
    unhealthy = (
        "(steps.probe.outputs.healthy == 'false' || steps.public_surfaces.outcome == 'failure' "
        "|| steps.public_surfaces.outputs.healthy != 'true' || steps.drift.outcome == 'failure')"
    )
    healthy = (
        "steps.probe.outputs.healthy == 'true' && steps.public_surfaces.outcome == 'success' "
        "&& steps.public_surfaces.outputs.healthy == 'true' && steps.drift.outcome == 'success'"
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


def test_person_only_incident_rendering_names_person_detail_surface(workflow_steps: list[dict], tmp_path: Path) -> None:
    """A person-only outage must file an incident that names the person surface.

    Rendering half of the 2026-08-03 lesson (`row_id: uptime-alarm-mute`): an
    incident titled for green `/api/health/content` while neither red probe was
    named teaches operators to distrust the alarm. So the incident must name
    person_detail_surface and carry no content-health identity when content is
    green.
    """
    title, open_body, comment_body = _render_incident_texts(
        workflow_steps,
        tmp_path,
        ProbeRunState.public_surface_failure("person_detail_surface"),
    )

    assert "person_detail_surface" in title
    for body in (open_body, comment_body):
        assert "person_detail_surface" in body
        # Surfaces that are green must not appear as failures.
        assert "donor_search_surface" not in body
        assert "public_deploy_drift" not in body
        _assert_no_green_content_output(body, "person-only incident body")
