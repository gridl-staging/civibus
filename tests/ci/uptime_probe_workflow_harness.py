"""Shared hermetic harness for the uptime-probe workflow contracts.

Extracted 2026-08-16 from ``test_uptime_probe_workflow.py`` so the single test
owner stays under the 800-line review limit. This module holds ONLY the reusable
harness — workflow-path constants, manifest specimens, the Actions-expression
evaluator, the fake external commands, and the step executors. Every contract
assertion stays in the test owner; there is no second workflow simulator here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import NamedTuple


WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "uptime_probe.yml"


SURFACE_PROBE_STEPS: dict[str, str | None] = {
    "public_surfaces": None,
    "drift": "Check public deploy drift",
}
JOB_FAILURE_GATE_STEP_NAME = "Fail the run when any production surface probe was red"
# A missing public-surface output is red. That fail-closed arm covers manifest
# fetch/parse failures that abort before the probe can write `healthy=false`.
UNHEALTHY_CONDITION_TERMS = (
    "steps.probe.outputs.healthy == 'false'",
    "steps.public_surfaces.outcome == 'failure'",
    "steps.public_surfaces.outputs.healthy != 'true'",
    "steps.drift.outcome == 'failure'",
)
PUBLIC_SURFACE_MANIFEST_ERROR = "public_surface_manifest_error"
PUBLIC_SURFACE_MANIFEST_PATH = "infra/public_surface_probes.tsv"
PUBLIC_SURFACE_MANIFEST_FETCH = (
    f'gh api "repos/${{{{ github.repository }}}}/contents/{PUBLIC_SURFACE_MANIFEST_PATH}'
    "?ref=${{ github.sha }}\" --jq '.content' | base64 -d"
)
PUBLIC_SURFACE_MANIFEST_HEADER = "surface_id\tkind\tpath\tmarker\tparity_mode\tuptime_mode\towners"
DONOR_MANIFEST_ROW = (
    "donor_search_surface\tstatic\t/donors?q=smith&by=name\t"
    'data-testid="donor-result-row"\tfatal\tfatal\tweb donor owners'
)
PERSON_MANIFEST_ROW = (
    "person_detail_surface\tperson_sitemap\t/sitemap-person-0.xml\t"
    'aria-label="Breadcrumb"\tknown_red\tfatal\tweb person owners'
)
PARITY_ONLY_MANIFEST_ROW = "parity_only_surface\tstatic\t/parity-only\tparity marker\tfatal\tskip\tparity owner"
# An arbitrary fatal specimen whose surface id, path, and marker appear NOWHERE
# else in this harness or the workflow. If the executed step fetches this path
# and exports this id, membership is provably driven by the manifest row rather
# than by hard-coded donor/person knowledge.
ARBITRARY_SURFACE_ID = "zeta_widget_surface"
ARBITRARY_SURFACE_PATH = "/zeta-widget-probe"
ARBITRARY_SURFACE_MARKER = 'data-flag="zeta-widget-marker-7f3"'
ARBITRARY_MANIFEST_ROW = (
    f"{ARBITRARY_SURFACE_ID}\tstatic\t{ARBITRARY_SURFACE_PATH}\t"
    f"{ARBITRARY_SURFACE_MARKER}\tfatal\tfatal\tweb zeta owners"
)


PUBLIC_SURFACE_FAILURE_BODY = "fixture public surface failure"
# Real curl semantics the fake must model: `-f`/`--fail` abort with exit 22 and
# discard the HTTP error body, `--fail-with-body` aborts but keeps the body, and
# option arguments containing `f` do not enable HTTP fail mode.
FAKE_CURL_FAIL_MODE_CASES = (
    ("-f", 22, False),
    ("-fsS", 22, False),
    ("--fail", 22, False),
    ("--fail-with-body", 22, True),
    ("--fail-early", 0, True),
    ("-Afoo", 0, True),
)


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

# `a || b` is the only operator this harness evaluates. Anything richer is
# rejected loudly rather than mis-modelled: silently resolving `&&`/`==` to a
# context lookup would let a wrong incident identity pass as correct.
_ACTIONS_UNSUPPORTED_OPERATORS = ("&&", "==", "!=", "!", ">", "<")


@dataclass(frozen=True)
class ProbeRunState:
    """Inputs supplied by Actions to the incident and final-gate scripts."""

    content_red: bool
    drift_red: bool
    public_surfaces_detail: str = ""
    public_surfaces_healthy: str = "true"
    public_surfaces_outcome: str = "success"
    omit_public_surfaces_outputs: bool = False

    @classmethod
    def all_green(cls) -> "ProbeRunState":
        return cls(content_red=False, drift_red=False)

    @classmethod
    def content_failure(cls) -> "ProbeRunState":
        return cls(content_red=True, drift_red=False)

    @classmethod
    def drift_failure(cls) -> "ProbeRunState":
        return cls(content_red=False, drift_red=True)

    @classmethod
    def public_surface_failure(
        cls,
        detail: str = "",
        *,
        drift_red: bool = False,
        outcome: str = "failure",
    ) -> "ProbeRunState":
        return cls(
            content_red=False,
            drift_red=drift_red,
            public_surfaces_detail=detail,
            public_surfaces_healthy="false",
            public_surfaces_outcome=outcome,
        )

    @classmethod
    def public_surface_outcome_failure(cls) -> "ProbeRunState":
        return cls(content_red=False, drift_red=False, public_surfaces_outcome="failure")

    @classmethod
    def missing_public_surface_outputs(cls, *, outcome: str = "success") -> "ProbeRunState":
        return cls(
            content_red=False,
            drift_red=False,
            public_surfaces_outcome=outcome,
            omit_public_surfaces_outputs=True,
        )


@dataclass(frozen=True)
class PublicSurfaceFixture:
    """External responses supplied to one executed public-surface step."""

    manifest_fetch_exit: int = 0
    failure_path: str = ""
    arbitrary_path: str = ""
    arbitrary_body: str = ""


def _step_by_name(steps: list[dict], name: str | None, *, step_id: str | None = None) -> dict:
    """Find a workflow step without pinning a display name for id-owned steps."""
    for step in steps:
        if name is not None and step.get("name") == name:
            return step
        if step_id is not None and step.get("id") == step_id:
            return step
    identity = f"id {step_id!r}" if step_id is not None else f"name {name!r}"
    raise AssertionError(f"missing required step with {identity}")


def _probe_run_context(state: ProbeRunState) -> dict[str, str]:
    base_url = "https://probe.example"
    context = {
        "env.PROBE_BASE_URL": base_url,
        "github.repository": "example/civibus",
        "github.run_id": "4242",
        "github.server_url": "https://github.example",
        "github.sha": "0123456789abcdef0123456789abcdef01234567",
        "secrets.GITHUB_TOKEN": "fake-token",
        # Legacy expressions remain resolvable while this red-contract stage
        # runs against the pre-refactor workflow. Keeping them green ensures a
        # donor/person specimen can pass only through `public_surfaces` detail.
        "steps.donor.outcome": "success",
        "steps.drift.outcome": "failure" if state.drift_red else "success",
        "steps.person.outcome": "success",
        "steps.find.outputs.number": "17",
        "steps.probe.outputs.detail": CONTENT_RED_DETAIL if state.content_red else CONTENT_GREEN_DETAIL,
        "steps.probe.outputs.healthy": "false" if state.content_red else "true",
        "steps.probe.outputs.status": CONTENT_RED_STATUS if state.content_red else CONTENT_GREEN_STATUS,
        "steps.probe.outputs.target": f"{base_url}/api/health/content",
        "steps.public_surfaces.outcome": state.public_surfaces_outcome,
        "steps.public_surfaces.outputs.detail": state.public_surfaces_detail,
        "steps.public_surfaces.outputs.healthy": state.public_surfaces_healthy,
    }
    if state.omit_public_surfaces_outputs:
        # A step that aborts before writing GITHUB_OUTPUT leaves its outputs
        # absent, not empty-but-present. Model the absence so the fail-closed
        # contract is exercised against the harder of the two shapes.
        for key in ("steps.public_surfaces.outputs.detail", "steps.public_surfaces.outputs.healthy"):
            del context[key]
    return context


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


def _actions_operand_value(operand: str, context: dict[str, str]) -> str:
    operand = operand.strip()
    if len(operand) >= 2 and operand[0] == "'" and operand[-1] == "'":
        # Actions escapes a single quote inside a string literal by doubling it.
        return operand[1:-1].replace("''", "'")
    if operand.startswith("steps.public_surfaces.outputs."):
        # GitHub resolves a step output that was never written to an empty
        # string. Model that explicitly so fetch/parse aborts exercise the
        # workflow's fallback incident identity rather than the harness.
        return context.get(operand, "")
    assert operand in context, f"test harness needs a value for Actions expression {operand!r}"
    return context[operand]


def _resolve_actions_expressions(value: str, context: dict[str, str]) -> str:
    """Resolve `${{ ... }}` expressions the way Actions does for string operands.

    Only the empty string is falsy here, matching Actions' string-to-boolean
    cast: `steps.public_surfaces.outputs.healthy` of `'false'` is a non-empty
    string and therefore wins over any `||` fallback, while an output the step
    never wrote falls through to the fallback literal.
    """

    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        operands = expression.split("||")
        if len(operands) > 1:
            for operator in _ACTIONS_UNSUPPORTED_OPERATORS:
                assert operator not in expression, (
                    f"harness evaluates only `a || b` fallbacks; {expression!r} needs richer evaluation"
                )
        resolved = ""
        for operand in operands:
            resolved = _actions_operand_value(operand, context)
            if resolved != "":
                return resolved
        return resolved

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


def _write_public_surface_fetch_fake(bin_dir: Path) -> None:
    """Write the fake `gh api` manifest reader."""
    gh_path = bin_dir / "gh"
    gh_path.write_text(
        "#!/bin/sh\n"
        "{\n"
        '  for argument in "$@"; do\n'
        "    printf '%s\\000' \"$argument\"\n"
        "  done\n"
        "  printf '\\000'\n"
        '} >> "$GH_CAPTURE_PATH"\n'
        'if [ "${MANIFEST_FETCH_EXIT:-0}" -ne 0 ]; then\n'
        '  echo "fixture manifest fetch failed" >&2\n'
        '  exit "$MANIFEST_FETCH_EXIT"\n'
        "fi\n"
        'base64 < "$PUBLIC_SURFACE_MANIFEST_PATH"\n',
        encoding="utf-8",
    )
    gh_path.chmod(0o755)


_PUBLIC_SURFACE_CURL_FAKE = (
    "#!/bin/sh\n"
    "fail_mode=0\n"
    "keep_body_on_fail=0\n"
    'output_file=""\n'
    'write_out=""\n'
    'target=""\n'
    'while [ "$#" -gt 0 ]; do\n'
    '  case "$1" in\n'
    "    --fail) fail_mode=1; shift ;;\n"
    "    --fail-with-body) fail_mode=1; keep_body_on_fail=1; shift ;;\n"
    '    --output|-o) output_file="$2"; shift 2 ;;\n'
    '    --write-out|-w) write_out="$2"; shift 2 ;;\n'
    '    --) shift; target="$1"; shift ;;\n'
    '    http://*|https://*) target="$1"; shift ;;\n'
    "    --*) shift ;;\n"
    "    -?*)\n"
    '      short_options="${1#-}"\n'
    "      shift\n"
    '      while [ -n "$short_options" ]; do\n'
    '        short_option=${short_options%"${short_options#?}"}\n'
    "        short_options=${short_options#?}\n"
    '        case "$short_option" in\n'
    "          f) fail_mode=1 ;;\n"
    "          o|w)\n"
    '            if [ -n "$short_options" ]; then\n'
    '              option_value="$short_options"; short_options=""\n'
    "            else\n"
    '              option_value="$1"; shift\n'
    "            fi\n"
    '            if [ "$short_option" = o ]; then\n'
    '              output_file="$option_value"\n'
    "            else\n"
    '              write_out="$option_value"\n'
    "            fi\n"
    "            ;;\n"
    "          A|b|c|C|d|D|e|E|F|H|K|m|P|Q|r|t|T|u|U|x|X|y|Y|z)\n"
    '            if [ -z "$short_options" ]; then shift; fi\n'
    '            short_options=""\n'
    "            ;;\n"
    "        esac\n"
    "      done\n"
    "      ;;\n"
    "    *) shift ;;\n"
    "  esac\n"
    "done\n"
    "printf 'fixture_curl_target=%s\\n' \"$target\" >&2\n"
    # An arbitrary manifest row drives its own path/body purely from env the
    # test sets from the manifest specimen, so it exercises data-driven
    # membership without embedding donor/person knowledge in the fake.
    'if [ -n "${ARBITRARY_SURFACE_PATH:-}" ] && '
    'printf \'%s\' "$target" | grep -Fq -- "$ARBITRARY_SURFACE_PATH"; then\n'
    '  status=200; body="${ARBITRARY_SURFACE_BODY:-}"\n'
    'elif [ -n "${PUBLIC_SURFACE_FAILURE_PATH:-}" ] && '
    'printf \'%s\' "$target" | grep -Fq -- "$PUBLIC_SURFACE_FAILURE_PATH"; then\n'
    f'  status=503; body="{PUBLIC_SURFACE_FAILURE_BODY}"\n'
    "else\n"
    '  case "$target" in\n'
    '    *"/donors?q=smith&by=name") status=200; body=\'<tr data-testid="donor-result-row">Smith</tr>\' ;;\n'
    "    *\"/sitemap-person-0.xml\") status=200; body='<urlset><url><loc>https://probe.example/person/fixture-person</loc></url></urlset>' ;;\n"
    '    *"/person/fixture-person") status=200; body=\'<nav aria-label="Breadcrumb">Person</nav>\' ;;\n'
    '    *"/parity-only") status=503; body="parity-only row must not be fetched" ;;\n'
    '    *) status=599; body="unexpected fixture target: $target" ;;\n'
    "  esac\n"
    "fi\n"
    # Real curl discards the HTTP error body under `-f`/`--fail`; only
    # `--fail-with-body` keeps it. Modelling that stops Stage 3 from
    # consuming response text production curl would never hand it.
    'if [ "$status" -ge 400 ] && [ "$fail_mode" -eq 1 ] && [ "$keep_body_on_fail" -eq 0 ]; then\n'
    '  body=""\n'
    "fi\n"
    'if [ -n "$output_file" ]; then printf \'%s\' "$body" > "$output_file"; else printf \'%s\' "$body"; fi\n'
    'if [ -n "$write_out" ]; then printf \'%s\' "$status"; fi\n'
    'if [ "$status" -ge 400 ] && [ "$fail_mode" -eq 1 ]; then exit 22; fi\n'
)


def _write_public_surface_curl_fake(bin_dir: Path) -> None:
    """Write the fake curl used by manifest-declared surface probes."""
    curl_path = bin_dir / "curl"
    curl_path.write_text(_PUBLIC_SURFACE_CURL_FAKE, encoding="utf-8")
    curl_path.chmod(0o755)


def _write_public_surface_fake_commands(bin_dir: Path) -> None:
    """Fake manifest fetch and public HTTP reads for the extracted step."""
    bin_dir.mkdir()
    _write_public_surface_fetch_fake(bin_dir)
    _write_public_surface_curl_fake(bin_dir)
    uuidgen_path = bin_dir / "uuidgen"
    uuidgen_path.write_text("#!/bin/sh\nprintf '%s\\n' fixture-delimiter\n", encoding="utf-8")
    uuidgen_path.chmod(0o755)


def _read_captured_calls(capture_path: Path) -> list[list[str]]:
    """Split the NUL-delimited argv records the fake `gh` appended."""
    if not capture_path.exists():
        return []
    return [
        [argument.decode("utf-8") for argument in call.split(b"\0")]
        for call in capture_path.read_bytes().split(b"\0\0")
        if call
    ]


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

    calls = _read_captured_calls(capture_path)
    issue_action = "create" if step_name == OPEN_ISSUE_STEP_NAME else "comment"
    matching_calls = [args for args in calls if args[:2] == ["issue", issue_action]]
    assert len(matching_calls) == 1, f"expected one `gh issue {issue_action}` call, got {calls}"
    return matching_calls[0]


def _execute_final_gate_step(
    workflow_steps: list[dict],
    tmp_path: Path,
    context: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Execute the job-level failure gate's run script with Actions env resolved.

    The step-level `if: always()` governs only whether Actions runs the script;
    the fail-closed logic lives in the script itself, so the harness runs the
    script directly with the gate's env expressions resolved from ``context``.
    """
    step = _step_by_name(workflow_steps, JOB_FAILURE_GATE_STEP_NAME)
    run_dir = tmp_path / "final_gate"
    run_dir.mkdir()
    environment = os.environ.copy()
    for name, value in step.get("env", {}).items():
        environment[name] = _resolve_actions_expressions(str(value), context)
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _resolve_actions_expressions(step["run"], context)],
        cwd=run_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_final_gate(
    workflow_steps: list[dict],
    tmp_path: Path,
    subdir: str,
    state: ProbeRunState,
) -> subprocess.CompletedProcess[str]:
    """Execute the final gate in its own subdir with a content/drift-green context.

    Isolates the `public_surfaces` inputs in ``state`` so gate
    specimens differ only in the public-surface health/outcome under test.
    """
    run_dir = tmp_path / subdir
    run_dir.mkdir()
    return _execute_final_gate_step(workflow_steps, run_dir, _probe_run_context(state))


def _run_public_surface_fake_curl(
    tmp_path: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run the public-surface fake curl with a fixture HTTP-503 path."""
    fake_bin = tmp_path / "bin"
    tmp_path.mkdir()
    _write_public_surface_fake_commands(fake_bin)
    environment = os.environ.copy()
    environment.update(
        {
            "GH_CAPTURE_PATH": str(tmp_path / "gh_calls.nul"),
            "PUBLIC_SURFACE_FAILURE_PATH": "/red-surface",
        }
    )
    return subprocess.run(
        [str(fake_bin / "curl"), *arguments, "https://probe.example/red-surface"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_public_surface_fake_curl_channels(
    tmp_path: Path,
    *arguments: str,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the fake curl twice with identical flags: once to stdout, once to `--output`.

    Body suppression has to hold on both channels; a probe that reads the error
    text out of `-o` would otherwise still see content production curl drops.
    """
    streamed = _run_public_surface_fake_curl(tmp_path / "streamed", *arguments)
    saved_body = tmp_path / "saved_body.html"
    _run_public_surface_fake_curl(tmp_path / "saved", *arguments, "--output", str(saved_body))
    return streamed, saved_body.read_text(encoding="utf-8") if saved_body.exists() else ""


def _option_value(arguments: list[str], option: str) -> str:
    option_index = arguments.index(option)
    return arguments[option_index + 1]


def _read_actions_outputs(output_path: Path) -> dict[str, str]:
    """Parse the single-line and delimiter forms written to GITHUB_OUTPUT."""
    if not output_path.exists():
        return {}
    lines = output_path.read_text(encoding="utf-8").splitlines()
    outputs: dict[str, str] = {}
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        if "<<" in line:
            key, delimiter = line.split("<<", maxsplit=1)
            line_index += 1
            value_lines: list[str] = []
            while line_index < len(lines) and lines[line_index] != delimiter:
                value_lines.append(lines[line_index])
                line_index += 1
            assert line_index < len(lines), f"unterminated GITHUB_OUTPUT value for {key!r}"
            outputs[key] = "\n".join(value_lines)
        elif "=" in line:
            key, value = line.split("=", maxsplit=1)
            outputs[key] = value
        line_index += 1
    return outputs


class PublicSurfacesRun(NamedTuple):
    """One hermetic execution of the workflow-owned `public_surfaces` step."""

    result: subprocess.CompletedProcess[str]
    outputs: dict[str, str]
    gh_calls: list[list[str]]


class PublicSurfaceFailureCase(NamedTuple):
    """Expected identities for one red manifest surface specimen."""

    failure_path: str
    failing_surface_id: str
    green_surface_id: str


def _execute_public_surfaces_step(
    workflow_steps: list[dict],
    tmp_path: Path,
    manifest_text: str,
    *,
    fixture: PublicSurfaceFixture = PublicSurfaceFixture(),
) -> PublicSurfacesRun:
    """Execute the workflow-owned manifest step with hermetic fetch/HTTP fixtures."""
    step = _step_by_name(workflow_steps, None, step_id="public_surfaces")
    run_dir = tmp_path / "public_surfaces"
    fake_bin = run_dir / "bin"
    run_dir.mkdir()
    _write_public_surface_fake_commands(fake_bin)
    manifest_path = run_dir / "inline_public_surfaces.tsv"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    output_path = run_dir / "github_output.txt"
    capture_path = run_dir / "gh_calls.nul"

    context = _probe_run_context(ProbeRunState.all_green())
    environment = os.environ.copy()
    environment.update(
        {
            "ARBITRARY_SURFACE_BODY": fixture.arbitrary_body,
            "ARBITRARY_SURFACE_PATH": fixture.arbitrary_path,
            "GH_CAPTURE_PATH": str(capture_path),
            "GITHUB_OUTPUT": str(output_path),
            "MANIFEST_FETCH_EXIT": str(fixture.manifest_fetch_exit),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "PROBE_BASE_URL": context["env.PROBE_BASE_URL"],
            "PUBLIC_SURFACE_FAILURE_PATH": fixture.failure_path,
            "PUBLIC_SURFACE_MANIFEST_PATH": str(manifest_path),
        }
    )
    for name, value in step.get("env", {}).items():
        environment[name] = _resolve_actions_expressions(str(value), context)

    completed = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _resolve_actions_expressions(step["run"], context)],
        cwd=run_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return PublicSurfacesRun(completed, _read_actions_outputs(output_path), _read_captured_calls(capture_path))


def _incident_fields(title: str, open_body: str, comment_body: str) -> tuple[tuple[str, str], ...]:
    """Label the three rendered incident texts for uniform per-field assertions."""
    return (("title", title), ("open body", open_body), ("comment body", comment_body))


def _render_incident_texts(
    workflow_steps: list[dict],
    tmp_path: Path,
    state: ProbeRunState,
) -> tuple[str, str, str]:
    context = _probe_run_context(state)
    open_arguments = _execute_issue_step(workflow_steps, tmp_path, OPEN_ISSUE_STEP_NAME, context)
    comment_arguments = _execute_issue_step(workflow_steps, tmp_path, COMMENT_ISSUE_STEP_NAME, context)
    return (
        _option_value(open_arguments, "--title"),
        _option_value(open_arguments, "--body"),
        _option_value(comment_arguments, "--body"),
    )
