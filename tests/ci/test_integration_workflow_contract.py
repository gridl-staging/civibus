"""Integration workflow contract tests for Stage 2 merge-time DB checks."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/integration.yml"
CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_UV_SHA = "0c5e2b8115b80b4c7c5ddf6ffdd634974642d182"


def _read_integration_workflow() -> str:
    return INTEGRATION_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_integration_workflow_uses_push_main_and_python_312() -> None:
    workflow_text = _read_integration_workflow()

    assert "push:\n    branches: [main]" in workflow_text
    assert "pull_request:\n    branches: [main]" in workflow_text
    assert "permissions:\n  contents: read" in workflow_text
    assert "name: integration-tests" in workflow_text
    assert f"uses: actions/checkout@{CHECKOUT_SHA}" in workflow_text
    assert workflow_text.count("persist-credentials: false") == 1
    assert f"uses: astral-sh/setup-uv@{SETUP_UV_SHA}" in workflow_text
    assert 'python-version: "3.12"' in workflow_text


def test_integration_workflow_reuses_repo_db_contract_commands() -> None:
    workflow_text = _read_integration_workflow()
    required_commands = (
        "uv sync --locked --extra dev --extra entity-resolution",
        "make db-up",
        "make db-reset",
        "make ingest-fec-bulk-sample",
        "make graph-load",
        "uv run --locked pytest tests/ci/test_integration_smoke.py --tb=short",
        "make db-down",
    )

    for command in required_commands:
        assert f"run: {command}" in workflow_text

    assert "POSTGRES_PASSWORD: ci-postgres-password" in workflow_text
    assert 'CIVIBUS_REQUIRE_DB: "1"' in workflow_text
    assert "if: always()" in workflow_text

    forbidden_fragments = (
        "docker compose -f infra/docker-compose.yml up",
        "docker compose -f infra/docker-compose.yml down",
        "docker compose build",
        "docker build",
        "entities.sql",
        "jurisdiction.sql",
        "provenance.sql",
        "entity_resolution.sql",
        "er_views.sql",
        "LOAD 'age'",
        "create_graph(",
        "python -m domains.campaign_finance.ingest.bulk_cli",
        "python -m core.graph.cli",
        'pytest -m "integration"',
    )

    for fragment in forbidden_fragments:
        assert fragment not in workflow_text


def test_integration_workflow_waits_for_repo_db_container_before_reset() -> None:
    workflow_text = _read_integration_workflow()

    assert "COMPOSE_PROJECT_NAME: civibus_${{ github.event.repository.name }}" in workflow_text
    assert 'container_id="$(docker compose -f infra/docker-compose.yml ps -q db)"' in workflow_text
    assert 'status="$(docker inspect -f \'{{.State.Health.Status}}\' "$container_id")"' in workflow_text

    start_index = workflow_text.index("name: Start DB")
    wait_index = workflow_text.index("name: Wait for DB health")
    reset_index = workflow_text.index("name: Reset DB schema")
    seed_index = workflow_text.index("name: Seed FEC bulk data")
    graph_index = workflow_text.index("name: Load graph")
    db_backed_suite_index = workflow_text.index("name: DB-backed product suite")
    test_index = workflow_text.index("name: Integration tests")
    stop_index = workflow_text.index("name: Stop DB")

    assert start_index < wait_index < reset_index < seed_index < graph_index < db_backed_suite_index < test_index
    assert db_backed_suite_index < stop_index
