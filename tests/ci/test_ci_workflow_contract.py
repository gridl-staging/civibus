"""CI workflow contract tests for Makefile-owned Python quality gates."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parents[2]
_repo_root_path = str(REPO_ROOT)
if _repo_root_path in sys.path:
    sys.path.remove(_repo_root_path)
sys.path.insert(0, _repo_root_path)

from test_support.browser_smoke_seed import SMOKE_COMMITTEE_SLUG, SMOKE_PERSON_ID  # noqa: E402
from tests.ci.public_mirror_contract import (  # noqa: E402
    DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID,
    MINIMUM_PUBLIC_CLASSIFICATION_TOTAL,
    PROJECTED_PUBLIC_CONTRACT_NODE_ID,
    PublicMirrorCategory,
    PublicMirrorTestClassification,
    validate_public_mirror_classifications,
)  # noqa: E402


CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
INTEGRATION_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/integration.yml"
WORKFLOW_DIRECTORY = REPO_ROOT / ".github/workflows"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
WEB_PACKAGE_PATH = REPO_ROOT / "web/package.json"
BATMAN_CONFIG_PATH = REPO_ROOT / ".batman.toml"
STAGE2_DISPOSITIONS_TEST_PATH = Path("domains/civics/loaders/official_rosters/test_stage2_dispositions.py")
BROWSER_SMOKE_SEED_MODULE = "test_support.browser_smoke_seed"
BROWSER_SMOKE_SEED_MODULE_PATH = REPO_ROOT / "test_support/browser_smoke_seed.py"
BROWSER_SMOKE_SEED_COMMAND = f"uv run --extra dev --extra entity-resolution python -m {BROWSER_SMOKE_SEED_MODULE}"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_NODE_SHA = "820762786026740c76f36085b0efc47a31fe5020"
SETUP_UV_SHA = "0c5e2b8115b80b4c7c5ddf6ffdd634974642d182"


def _read_ci_workflow() -> str:
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_workflow_uses_python_312_with_expected_triggers_and_jobs() -> None:
    """One required fast job answers every push/PR; heavy proof lives elsewhere.

    The pre-2026-08-15 shape ran three jobs (lint, full public unit suite,
    full web gates) on every change, so ordinary feedback waited on the
    slowest. The fast job runs the measured qa-fast composition through its
    Makefile owner; the build job keeps the production web build as parallel,
    non-blocking signal; exhaustive proof moved to the nightly workflow.
    """
    workflow_text = _read_ci_workflow()
    fast_job = _job_block(workflow_text, "fast")
    build_job = _job_block(workflow_text, "build")

    assert "pull_request:\n    branches: [main]" in workflow_text
    assert "push:\n    branches: [main]" in workflow_text
    assert "permissions:\n  contents: read" in workflow_text
    assert "    name: fast" in fast_job.splitlines()
    assert "    name: build" in build_job.splitlines()
    # Exactly these two jobs: a third job re-introduces the every-push wait
    # this restructure exists to remove.
    jobs_section = workflow_text.split("\njobs:\n", 1)[1]
    job_names = [
        line
        for line in jobs_section.splitlines()
        if line.startswith("  ") and line.endswith(":") and not line.startswith("    ")
    ]
    assert job_names == ["  fast:", "  build:"]

    for job_block in (fast_job, build_job):
        assert f"uses: actions/checkout@{CHECKOUT_SHA}" in job_block
        assert "          fetch-depth: 2" in job_block.splitlines()
        assert "          persist-credentials: false" in job_block.splitlines()

    assert f"uses: astral-sh/setup-uv@{SETUP_UV_SHA}" in fast_job
    assert '          python-version: "3.12"' in fast_job.splitlines()


def _job_block(workflow_text: str, job_name: str) -> str:
    workflow_lines = workflow_text.splitlines()
    start_index = workflow_lines.index(f"  {job_name}:")
    end_index = len(workflow_lines)
    for index, line in enumerate(workflow_lines[start_index + 1 :], start_index + 1):
        if line.startswith("  ") and not line.startswith("    "):
            end_index = index
            break
    return "\n".join(workflow_lines[start_index:end_index])


def _make_target_block(makefile_text: str, target_name: str) -> str:
    lines = makefile_text.splitlines()
    start_index = lines.index(f"{target_name}:")
    end_index = len(lines)
    for index, line in enumerate(lines[start_index + 1 :], start_index + 1):
        if line and not line.startswith(("\t", " ")):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index])


def _make_variable_value(makefile_text: str, variable_name: str) -> str:
    prefix = f"{variable_name} :="
    lines = makefile_text.splitlines()
    start_index = next(index for index, line in enumerate(lines) if line.startswith(prefix))
    value_lines = [lines[start_index][len(prefix) :].strip()]
    for line in lines[start_index + 1 :]:
        if not line.startswith("\t"):
            break
        value_lines.append(line.strip())
    return " ".join(value_lines).replace("\\", "").strip()


def test_ci_workflow_commands_use_make_owned_python_gates() -> None:
    workflow_text = _read_ci_workflow()
    fast_job = _job_block(workflow_text, "fast")

    assert "        run: uv sync --locked --extra dev --extra entity-resolution" in fast_job.splitlines()
    # qa-fast-public is the locality view of the fast tier: identical recipe,
    # with dev_repo_only nodes deselected because their private assets are
    # intentionally absent from the public mirror this workflow runs on.
    assert "        run: make qa-fast-public" in fast_job.splitlines()
    assert "        run: make test" not in workflow_text.splitlines()
    # The full public unit suite left this workflow deliberately: it is the
    # nightly workflow's job now, so nobody waits ~4 minutes per push for it.
    assert "run: make test-public" not in workflow_text
    # make lint is not a separate job: qa-fast runs it as its first gate.
    assert "run: make lint" not in workflow_text


def test_ci_workflow_runs_package_owned_web_gates_before_deploy() -> None:
    """Web unit gates live inside qa-fast; CI only bootstraps deps and builds.

    The fast job installs web dependencies (qa-fast fails closed without
    them), and the build job keeps the production build as parallel signal.
    npm test / npm run check must NOT reappear as workflow steps — the
    Makefile owns that composition and duplicating it here is drift.
    """
    workflow_text = _read_ci_workflow()
    fast_job = _job_block(workflow_text, "fast")
    build_job = _job_block(workflow_text, "build")
    web_package = json.loads(WEB_PACKAGE_PATH.read_text(encoding="utf-8"))

    assert web_package["engines"]["node"] == "24.18.0"
    for job_block in (fast_job, build_job):
        assert f"uses: actions/setup-node@{SETUP_NODE_SHA}" in job_block
        assert "          node-version-file: web/package.json" in job_block.splitlines()
        assert "          cache: npm" in job_block.splitlines()
        assert "          cache-dependency-path: web/package-lock.json" in job_block.splitlines()
        assert job_block.index("uses: actions/setup-node@") < job_block.index("run: npm ci")
        assert "        run: npm ci" in job_block.splitlines()
        assert "continue-on-error" not in job_block
        assert "tests/smoke/run-playwright.sh" not in job_block

    assert "        run: npm run build" in build_job.splitlines()
    assert "run: npm test" not in workflow_text
    assert "run: npm run check" not in workflow_text


def test_ci_workflow_does_not_copy_make_owned_python_gate_commands() -> None:
    workflow_text = _read_ci_workflow()
    forbidden_commands = (
        "ruff check tests/ci/",
        "ruff format --check tests/ci/",
        "ruff check .",
        "ruff format --check .",
        'pytest tests/ci/ -m "not dev_repo_only"',
        'pytest -m "not integration and not e2e"',
        'pytest -m "not integration and not e2e and not dev_repo_only"',
        "--cov=api --cov=core --cov=domains",
        "--cov-fail-under=70",
        "continue-on-error",
    )

    for command in forbidden_commands:
        assert command not in workflow_text


def test_makefile_owns_public_python_gate_selector() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert (
        ".PHONY: db-up db-wait db-down db-teardown db-reset test qa-fast qa-fast-public coverage-public test-public test-e2e-smoke test-projected-public-contract"
    ) in makefile_text
    assert (
        "MERGE_DB_BACKED_TEST_NODES := "
        "\\\n\tcore/test_refresh_runner.py::test_masters_with_spine_skipped_preserves_officeholder_money_coverage "
        "\\\n\ttests/integration/test_donor_search_query_contract.py::test_search_donors_full_scope_bound_preserves_high_volume_donor_values"
        in makefile_text
    )
    assert (
        'test-public:\n\tuv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e and not dev_repo_only"'
        in makefile_text
    )
    assert (
        'test:\n\tuv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e and not projected_public_contract"\n'
        '\t@merge_db_target="$$(uv run --extra dev --extra entity-resolution python -c '
        "'import conftest; conftest.merge_db_slice_probe()')\"; "
        "\\\n\tmerge_db_probe_status=$$?; "
        '\\\n\tif [ "$$merge_db_probe_status" -eq 0 ]; then '
        "\\\n\t\tCIVIBUS_REQUIRE_DB=1 uv run --extra dev --extra entity-resolution pytest $(MERGE_DB_BACKED_TEST_NODES); "
        '\\\n\telif [ "$$merge_db_probe_status" -eq 1 ]; then '
        "\\\n\t\tprintf '%s\\n' \"CIVIBUS_MERGE_DB_SLICE_SHADOW_WARN $$merge_db_target nodes=$(MERGE_DB_BACKED_TEST_NODES)\"; "
        "\\\n\telse "
        '\\\n\t\texit "$$merge_db_probe_status"; '
        "\\\n\tfi" in makefile_text
    )


def test_makefile_owns_db_free_qa_fast_gate() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    qa_fast_block = _make_target_block(makefile_text, "qa-fast")
    qa_fast_commands = [line for line in qa_fast_block.splitlines()[1:] if line.startswith("\t")]

    assert _make_variable_value(makefile_text, "QA_FAST_STRUCTURAL_TEST_PATHS").split() == [
        "tests/ci",
        "tests/test_beads_adoption_contract.py",
    ]
    assert _make_variable_value(makefile_text, "QA_FAST_STRUCTURAL_MARKER_EXPRESSION") == (
        "not integration and not e2e and not projected_public_contract"
    )
    assert _make_variable_value(makefile_text, "QA_FAST_PRODUCT_TEST_PATHS").split() == [
        "api/",
        "core/people/enrichment",
        "core/entity_resolution",
        "domains/campaign_finance/entity_extractors",
        "domains/campaign_finance/normalize",
        "domains/campaign_finance/tests",
        "domains/campaign_finance/ingest/test_federal_contest_name.py",
        "domains/civics/loaders/test_federal_fec_races.py",
        "domains/civics/tests/test_constants.py",
        "tests/test_stage1_fec_committee_summary_format_outputs.py",
        "tests/test_stage1_fec_schedule_b_source_contract.py",
        "tests/test_stage1_fec_schedule_e_format_outputs.py",
        "tests/test_schedule_e_test_support.py",
    ]
    assert _make_variable_value(makefile_text, "QA_FAST_PRODUCT_MARKER_EXPRESSION") == (
        "not integration and not e2e and not projected_public_contract and not dev_repo_only"
    )
    assert qa_fast_commands == [
        "\t@test -d web/node_modules || { "
        "printf '%s\\n' 'qa-fast requires web/node_modules; run npm --prefix web ci' >&2; exit 1; }",
        "\t$(MAKE) lint",
        "\tnpm --prefix web test",
        "\tnpm --prefix web run check",
        "\tuv run --extra dev --extra entity-resolution pytest $(QA_FAST_STRUCTURAL_TEST_PATHS) "
        '-m "$(QA_FAST_STRUCTURAL_MARKER_EXPRESSION)"',
        "\tuv run --extra dev --extra entity-resolution pytest $(QA_FAST_PRODUCT_TEST_PATHS) "
        '-m "$(QA_FAST_PRODUCT_MARKER_EXPRESSION)"',
    ]

    forbidden_dependencies = (
        "db-up",
        "db-reset",
        "docker",
        "POSTGRES_PASSWORD",
        "require-postgres-password",
        "merge_db_slice_probe",
        "psql",
        "curl",
        "api_key",
        "token",
        "secret",
        "credential",
    )
    assert not any(dependency.casefold() in qa_fast_block.casefold() for dependency in forbidden_dependencies)


def test_qa_fast_missing_node_modules_preflight_message(tmp_path: Path) -> None:
    result = subprocess.run(
        ["make", "-f", str(MAKEFILE_PATH), "qa-fast"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "web/node_modules" in result.stderr
    assert "npm --prefix web ci" in result.stderr
    assert "npm --prefix web test" not in result.stdout


def test_batman_config_declares_qa_fast_merge_gate() -> None:
    batman_config_text = BATMAN_CONFIG_PATH.read_text(encoding="utf-8")
    batman_config = tomllib.loads(batman_config_text)
    merge_validation = batman_config["merge_validation"]
    gates = merge_validation["gates"]
    budget_seconds = merge_validation["budget_seconds"]

    assert len(gates) == 1
    assert len({gate["name"] for gate in gates}) == len(gates)
    assert type(budget_seconds) in (int, float)
    assert budget_seconds > 0

    gate = gates[0]
    assert gate["name"] == "qa-fast"
    # The gate runs in Batman merge worktrees, which materialize tracked files
    # only: web/node_modules never exists there, so bare `make qa-fast` fails
    # closed on environment rather than on code (proven at this change's first
    # landing attempt). The repo-owned wrapper bootstraps the lockfile-pinned
    # web dependencies and then execs the canonical target unchanged.
    assert gate["command"] == ["bash", "scripts/qa_fast_gate.sh"]

    # No-drift principle: neither the declared command nor the wrapper may
    # inline a copy of the qa-fast composition. The wrapper must exec the
    # canonical make target so Makefile stays the single owner.
    copied_command_fragments = (
        "pytest",
        "ruff",
        "QA_FAST_STRUCTURAL_TEST_PATHS",
        "QA_FAST_PRODUCT_TEST_PATHS",
    )
    declared_command = " ".join(gate["command"])
    assert not any(fragment in declared_command for fragment in copied_command_fragments)
    assert "/parallel_development/" not in batman_config_text

    wrapper_path = REPO_ROOT / "scripts" / "qa_fast_gate.sh"
    wrapper_text = wrapper_path.read_text(encoding="utf-8")
    assert wrapper_path.stat().st_mode & 0o111, "gate wrapper must be executable"
    assert 'exec make -C "$repo_root" qa-fast' in wrapper_text
    assert not any(fragment in wrapper_text for fragment in copied_command_fragments)
    # The one permitted bootstrap: web dependencies from the pinned lockfile.
    assert "npm --prefix" in wrapper_text and " ci " in wrapper_text


def test_qa_fast_has_no_other_command_surface() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    non_owner_surfaces = {
        ".github/workflows/integration.yml": INTEGRATION_WORKFLOW_PATH.read_text(encoding="utf-8"),
        "web/package.json": WEB_PACKAGE_PATH.read_text(encoding="utf-8"),
        # test-integration-local survives only as a one-line alias delegating to
        # qa-integration, so scanning the qa-integration block covers both.
        # .batman.toml is deliberately NOT in this list anymore: since the
        # merge-validation gate landed it legitimately references qa-fast, and
        # its exact command shape is pinned by
        # test_batman_config_declares_qa_fast_merge_gate instead.
        # ci.yml is likewise a sanctioned INVOKER now (its fast job runs
        # `make qa-fast-public`); the ci contract tests above pin that the
        # workflow never inlines the composition itself.
        "Makefile:qa-integration": _make_target_block(makefile_text, "qa-integration"),
    }

    assert {surface for surface, contents in non_owner_surfaces.items() if "qa-fast" in contents} == set()

    # ci.yml may name the make target (in comments, step names, and the one
    # invocation) but every executable reference must be the make target — a
    # run line carrying any other qa-fast text would be composition drift.
    ci_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    qa_fast_run_lines = [line.strip() for line in ci_text.splitlines() if "run:" in line and "qa-fast" in line]
    assert qa_fast_run_lines == ["run: make qa-fast-public"]


def test_makefile_owns_public_qa_fast_locality_variant() -> None:
    """qa-fast-public = the same fast tier, viewed from the public mirror.

    dev_repo_only nodes anchor on private assets (.beads/, frozen ROADMAP.md,
    dev-host CLIs) that the public mirror intentionally lacks, so the public
    invocation must deselect them. Everything else — recipe, paths, product
    marker — must stay byte-identical to qa-fast so there is exactly one
    composition owner. Target-specific variable appends give that for free.
    """
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    lines = makefile_text.splitlines()

    assert "qa-fast-public: QA_FAST_STRUCTURAL_MARKER_EXPRESSION += and not dev_repo_only" in lines
    # The product expression already carries "and not dev_repo_only" for both
    # localities, so only the structural expression needs the append.
    assert "qa-fast-public: qa-fast" in lines
    # Exactly the delegation and the append: any recipe line under
    # qa-fast-public would fork the composition.
    delegation_index = lines.index("qa-fast-public: qa-fast")
    assert not lines[delegation_index + 1].startswith("\t")
    assert any("qa-fast-public" in line for line in lines if line.startswith(".PHONY:"))


def test_makefile_owns_public_coverage_gate() -> None:
    """Nightly owns coverage; the Makefile owns the command it runs."""
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    coverage_block = _make_target_block(makefile_text, "coverage-public")
    coverage_commands = [line for line in coverage_block.splitlines()[1:] if line.startswith("\t")]

    assert coverage_commands == [
        "\tuv run --extra dev --extra entity-resolution pytest "
        '-m "not integration and not e2e and not dev_repo_only" '
        "--cov=api --cov=core --cov=domains --cov-fail-under=70",
    ]


NIGHTLY_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/nightly.yml"


def test_nightly_workflow_owns_exhaustive_scheduled_proof() -> None:
    """The heavy tiers run on a timer, not in anyone's edit or merge loop.

    backend-full owns the full public unit suite with the coverage floor (one
    run — coverage-public fails on any test failure, so a separate plain run
    would only double runtime), web-full owns the complete web gate set, and
    browser-smoke owns the Playwright journeys in LIVE mode against a seeded
    database: without SMOKE_USE_LIVE_API the runner boots its fixture backend
    and skips every DB-touching journey, which would make the seeded database
    dead weight. The integration suite itself is NOT duplicated here:
    integration.yml carries its own schedule trigger.
    """
    workflow_text = NIGHTLY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "schedule:" in workflow_text
    assert re.search(r"- cron: ['\"]\d+ \d+ \* \* \*['\"]", workflow_text)
    assert "workflow_dispatch:" in workflow_text
    assert "permissions:\n  contents: read" in workflow_text
    # Scheduled proof must not silently run stale pins.
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in workflow_text
    assert f"uses: astral-sh/setup-uv@{SETUP_UV_SHA}" in workflow_text
    assert f"uses: actions/setup-node@{SETUP_NODE_SHA}" in workflow_text

    backend_job = _job_block(workflow_text, "backend-full")
    assert "        run: make coverage-public" in backend_job.splitlines()
    # A plain test-public step would re-run the identical selection.
    assert "run: make test-public" not in workflow_text

    web_job = _job_block(workflow_text, "web-full")
    for command in ("npm ci", "npm test", "npm run check", "npm run build"):
        assert f"        run: {command}" in web_job.splitlines()

    # The e2e smoke modules are marked e2e-only, so no merge-time or
    # coverage selection ever executes them; this job is their scheduled
    # home. It owns a disposable DB lifecycle of its own because the state
    # sample module resets and re-seeds the database, which would destroy
    # the federal seed browser-smoke depends on if the two shared one.
    e2e_job = _job_block(workflow_text, "e2e")
    for command in (
        "make db-up",
        "make db-wait",
        "make db-reset",
        "make test-e2e-smoke",
    ):
        assert f"        run: {command}" in e2e_job.splitlines()
    # The full dev-side sweep would drag registry-quarantined nodes and
    # live-key requirements into scheduled proof; the scoped target may not
    # silently widen back.
    assert "run: make test-e2e\n" not in e2e_job + "\n"
    # DEMO_KEY keeps the live-ingest fixture off its missing-key hard-fail
    # path; rate limiting engages the fixture-fallback the test documents.
    assert "      FEC_API_KEY: DEMO_KEY" in e2e_job.splitlines()
    assert "- name: Stop DB\n        if: always()\n        run: make db-down" in e2e_job

    browser_job = _job_block(workflow_text, "browser-smoke")
    browser_job_lines = browser_job.splitlines()
    for command in (
        "make db-up",
        "make db-wait",
        "make db-reset",
        "make ingest-fec-bulk-sample",
        "make graph-load",
        BROWSER_SMOKE_SEED_COMMAND,
        "npm run test:smoke",
    ):
        assert f"        run: {command}" in browser_job_lines
    # The seed replaces the bulk sample's entities with the deterministic
    # specimens the journeys assert on, so it must land after the graph is
    # loaded from that sample and before any journey reads a page.
    seed_step_index = browser_job_lines.index(f"        run: {BROWSER_SMOKE_SEED_COMMAND}")
    assert browser_job_lines.index("        run: make graph-load") < seed_step_index
    assert seed_step_index < browser_job_lines.index("        run: npm run test:smoke")
    # The specimen pins are the Playwright fixtures' env overrides. They are
    # imported from the seed module, so a literal that drifts from the rows
    # the seed actually writes fails here instead of in a browser journey.
    assert f'      SMOKE_PERSON_ID: "{SMOKE_PERSON_ID}"' in browser_job_lines
    assert f'      SMOKE_COMMITTEE_SLUG: "{SMOKE_COMMITTEE_SLUG}"' in browser_job_lines
    # Live mode is what binds the journeys to the seeded database.
    assert '      SMOKE_USE_LIVE_API: "1"' in browser_job_lines
    # Teardown must be unconditional AND attached to the db-down step itself.
    assert "- name: Stop DB\n        if: always()\n        run: make db-down" in browser_job
    # The shadow-warn escape hatch may never appear in scheduled proof.
    assert "CIVIBUS_MERGE_DB_SLICE_SHADOW_WARN" not in workflow_text
    assert "run: make test\n" not in workflow_text


def test_browser_smoke_seed_module_runs_its_seed_when_executed_as_a_module() -> None:
    """`python -m` on a module with no entrypoint guard exits 0 having done nothing.

    The nightly job's only signal that the seed ran is the exit status, so a
    module that merely defines `main()` would let browser-smoke proceed
    against unseeded rows and fail in a journey assertion instead of here.
    """
    module_body = ast.parse(BROWSER_SMOKE_SEED_MODULE_PATH.read_text(encoding="utf-8")).body
    entrypoint_guards = [node for node in module_body if _is_exact_main_entrypoint_guard(node)]

    assert len(entrypoint_guards) == 1, f"expected exactly one __main__ guard in {BROWSER_SMOKE_SEED_MODULE}"


@pytest.mark.parametrize(
    "invalid_entrypoint",
    [
        'if __name__ != "__main__":\n    main()\n',
        'if __name__ == "__main__":\n    main("unexpected")\n',
        'if __name__ == "__main__":\n    main(unexpected=True)\n',
        'if __name__ == "__main__":\n    main()\n    print("extra")\n',
        'if __name__ == "__main__":\n    main()\nelse:\n    pass\n',
    ],
    ids=["not-equal", "positional-argument", "keyword-argument", "extra-body-statement", "else-branch"],
)
def test_browser_smoke_seed_entrypoint_contract_rejects_invalid_shapes(invalid_entrypoint: str) -> None:
    [entrypoint] = ast.parse(invalid_entrypoint).body

    assert not _is_exact_main_entrypoint_guard(entrypoint)


def _is_exact_main_entrypoint_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not _guards_on_main_module_name(node.test):
        return False
    if len(node.body) != 1 or node.orelse:
        return False

    statement = node.body[0]
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False

    call = statement.value
    return isinstance(call.func, ast.Name) and call.func.id == "main" and not call.args and not call.keywords


def _guards_on_main_module_name(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def test_makefile_merge_slice_preflight_delegates_to_conftest_connection_owner() -> None:
    """The preflight must not re-implement the DB-backed connect policy.

    A direct `core.db.get_connection()` one-shot here skipped the root
    conftest's password default and startup retries, so `make test` shadow-
    skipped an answerable database instead of evaluating the merge slice.
    """
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    test_block = _make_target_block(makefile_text, "test")

    assert "import conftest; conftest.merge_db_slice_probe()" in test_block
    assert "from core.db import get_connection" not in test_block
    assert "merge_db_probe_status=$$?" in test_block
    assert '[ "$$merge_db_probe_status" -eq 1 ]' in test_block
    assert 'exit "$$merge_db_probe_status"' in test_block


def test_makefile_shadow_warning_reuses_merge_db_slice_nodes() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    selected_nodes = _make_variable_value(makefile_text, "MERGE_DB_BACKED_TEST_NODES")
    test_block = _make_target_block(makefile_text, "test")

    assert selected_nodes.split() == [
        "core/test_refresh_runner.py::test_masters_with_spine_skipped_preserves_officeholder_money_coverage",
        "tests/integration/test_donor_search_query_contract.py::test_search_donors_full_scope_bound_preserves_high_volume_donor_values",
    ]
    assert "CIVIBUS_MERGE_DB_SLICE_SHADOW_WARN" in test_block
    # The warning reports the target the probe actually resolved through
    # core.db, not the Makefile's own DB_HOST, which can disagree with
    # POSTGRES_HOST and name a host that was never attempted.
    assert "CIVIBUS_MERGE_DB_SLICE_SHADOW_WARN $$merge_db_target" in test_block
    assert "DB_HOST=$(DB_HOST)" not in test_block
    assert test_block.count("$(MERGE_DB_BACKED_TEST_NODES)") == 2


def test_shadow_warning_is_executable_only_in_optional_make_test() -> None:
    marker = "CIVIBUS_MERGE_DB_SLICE_SHADOW_WARN"
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    test_block = _make_target_block(makefile_text, "test")
    qa_integration_block = _make_target_block(makefile_text, "qa-integration")
    compatibility_declarations = "\n".join(
        line for line in makefile_text.splitlines() if line.startswith("test-integration-local:")
    )

    assert makefile_text.count(marker) == 1
    assert marker in test_block
    assert marker not in qa_integration_block
    assert marker not in compatibility_declarations
    assert marker not in BATMAN_CONFIG_PATH.read_text(encoding="utf-8")
    for workflow_path in WORKFLOW_DIRECTORY.glob("*.yml"):
        assert marker not in workflow_path.read_text(encoding="utf-8"), workflow_path


def test_makefile_lint_runs_lane_authoring_hazard_ratchet() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    lint_block = _make_target_block(makefile_text, "lint")

    assert (
        "\t@if [ -f scripts/lane_authoring_hazard_checker.py ]; "
        "then uv run python scripts/lane_authoring_hazard_checker.py; fi"
    ) in lint_block


def test_public_mirror_classification_contract_is_valid_and_exact() -> None:
    entries = validate_public_mirror_classifications()

    assert len(entries) == len({entry.node_id for entry in entries})
    assert len(entries) >= MINIMUM_PUBLIC_CLASSIFICATION_TOTAL
    assert {entry.category for entry in entries} == {PublicMirrorCategory.DEV_REPO_ONLY}
    assert "tests/ci/test_api_dockerfile_contract.py::test_debbie_sync_includes_api_dockerfile_root_inputs" in (
        DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID
    )


def test_dev_repo_only_marker_selection_matches_public_mirror_contract() -> None:
    collected_node_ids = _collect_node_ids("-m", "dev_repo_only")
    # The projected-public contract is collection-gated to explicit naming
    # (conftest deselects it from every unnamed selection so Batman's
    # directory-level merge validation can never run it implicitly), so the
    # repo-wide marker sweep must see every classified node except that one.
    expected_node_ids = set(DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID)
    expected_node_ids.discard(PROJECTED_PUBLIC_CONTRACT_NODE_ID)

    assert collected_node_ids == expected_node_ids, _node_delta_message(
        expected_node_ids=expected_node_ids,
        actual_node_ids=collected_node_ids,
    )
    # The gated node stays reachable — and marker-classified — when named.
    named_node_ids = _collect_node_ids("-m", "dev_repo_only", PROJECTED_PUBLIC_CONTRACT_NODE_ID.split("::", 1)[0])
    assert named_node_ids == {PROJECTED_PUBLIC_CONTRACT_NODE_ID}


def test_stage2_disposition_nodes_are_all_classified_dev_repo_only() -> None:
    collected_node_ids = _collect_node_ids(STAGE2_DISPOSITIONS_TEST_PATH.as_posix())
    classified_node_ids = set(DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID)

    assert collected_node_ids <= classified_node_ids, _node_delta_message(
        expected_node_ids=collected_node_ids,
        actual_node_ids=classified_node_ids,
    )


def test_static_dev_repo_only_markers_carry_matching_contract_metadata() -> None:
    marker_uses = _static_dev_repo_only_markers()

    assert marker_uses, "expected at least one explicit dev_repo_only marker use"
    for marker_use in marker_uses:
        entry = DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID[marker_use.node_id]
        assert marker_use.private_asset == entry.private_asset
        assert marker_use.owner == entry.owner


def test_marker_metadata_audit_rejects_bare_marker() -> None:
    with pytest.raises(AssertionError, match="private_asset"):
        _validate_marker_metadata(
            node_id="tests/example.py::test_private",
            private_asset=None,
            owner="owner",
            classifications={
                "tests/example.py::test_private": PublicMirrorTestClassification(
                    node_id="tests/example.py::test_private",
                    category=PublicMirrorCategory.DEV_REPO_ONLY,
                    private_asset="private-doc.md",
                    owner="owner",
                )
            },
        )


def test_marker_metadata_audit_rejects_unknown_marker_use() -> None:
    with pytest.raises(AssertionError, match="not classified"):
        _validate_marker_metadata(
            node_id="tests/example.py::test_private",
            private_asset="private-doc.md",
            owner="owner",
            classifications={},
        )


def test_public_mirror_classification_rejects_stale_duplicate_entry() -> None:
    duplicate = PublicMirrorTestClassification(
        node_id="tests/example.py::test_private",
        category=PublicMirrorCategory.DEV_REPO_ONLY,
        private_asset="private-doc.md",
        owner="owner",
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_public_mirror_classifications((duplicate, duplicate))


def test_marker_metadata_audit_rejects_product_runtime_quarantine() -> None:
    with pytest.raises(AssertionError, match="product_runtime"):
        _validate_marker_metadata(
            node_id="tests/example.py::test_public",
            private_asset="private-doc.md",
            owner="owner",
            classifications={
                "tests/example.py::test_public": PublicMirrorTestClassification(
                    node_id="tests/example.py::test_public",
                    category=PublicMirrorCategory.PRODUCT_RUNTIME,
                )
            },
        )


class _StaticMarkerUse(BaseModel):
    node_id: str
    private_asset: str | None
    owner: str | None


def _collect_node_ids(*pytest_args: str) -> set[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=110,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    return {line for line in completed.stdout.splitlines() if "::" in line and not line.startswith("<")}


def _node_delta_message(*, expected_node_ids: set[str], actual_node_ids: set[str]) -> str:
    missing = sorted(expected_node_ids - actual_node_ids)
    extra = sorted(actual_node_ids - expected_node_ids)
    return f"missing={missing}\nextra={extra}"


def _static_dev_repo_only_markers() -> list[_StaticMarkerUse]:
    marker_uses: list[_StaticMarkerUse] = []
    for path in sorted(
        (
            *REPO_ROOT.glob("tests/**/*.py"),
            *REPO_ROOT.glob("api/**/*.py"),
            *REPO_ROOT.glob("core/**/*.py"),
            *REPO_ROOT.glob("domains/**/*.py"),
        )
    ):
        module = ast.parse(path.read_text(encoding="utf-8"))
        module_marker = _module_dev_repo_only_marker(module)
        test_functions = [
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        if module_marker is not None:
            for function in test_functions:
                marker_uses.extend(
                    _marker_uses_for_function(path=path, function_name=function.name, marker=module_marker)
                )
        for function in test_functions:
            for decorator in function.decorator_list:
                marker = _dev_repo_only_marker_kwargs(decorator)
                if marker is not None:
                    marker_uses.extend(_marker_uses_for_function(path=path, function_name=function.name, marker=marker))
    return marker_uses


def _module_dev_repo_only_marker(module: ast.Module) -> dict[str, str | None] | None:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            continue
        marker = _dev_repo_only_marker_kwargs(node.value)
        if marker is not None:
            return marker
    return None


def _dev_repo_only_marker_kwargs(node: ast.AST) -> dict[str, str | None] | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "dev_repo_only":
        return None
    if not isinstance(node.func.value, ast.Attribute) or node.func.value.attr != "mark":
        return None
    kwargs = {keyword.arg: _constant_string(keyword.value) for keyword in node.keywords}
    return {"private_asset": kwargs.get("private_asset"), "owner": kwargs.get("owner")}


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _marker_uses_for_function(
    *, path: Path, function_name: str, marker: dict[str, str | None]
) -> list[_StaticMarkerUse]:
    base_node_id = f"{path.relative_to(REPO_ROOT).as_posix()}::{function_name}"
    classified_node_ids = sorted(
        node_id
        for node_id in DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID
        if node_id == base_node_id or node_id.startswith(f"{base_node_id}[")
    )
    return [_marker_use(node_id=node_id, marker=marker) for node_id in (classified_node_ids or [base_node_id])]


def _marker_use(*, node_id: str, marker: dict[str, str | None]) -> _StaticMarkerUse:
    _validate_marker_metadata(
        node_id=node_id,
        private_asset=marker["private_asset"],
        owner=marker["owner"],
        classifications=DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID,
    )
    return _StaticMarkerUse(node_id=node_id, private_asset=marker["private_asset"], owner=marker["owner"])


def _validate_marker_metadata(
    *,
    node_id: str,
    private_asset: str | None,
    owner: str | None,
    classifications: dict[str, PublicMirrorTestClassification],
) -> None:
    assert private_asset, f"{node_id} dev_repo_only marker must include private_asset"
    assert owner, f"{node_id} dev_repo_only marker must include owner"
    entry = classifications.get(node_id)
    assert entry is not None, f"{node_id} is marked dev_repo_only but not classified"
    assert entry.category == PublicMirrorCategory.DEV_REPO_ONLY, f"{node_id} classified as product_runtime"
