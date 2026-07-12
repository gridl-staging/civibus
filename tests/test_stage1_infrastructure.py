from __future__ import annotations

from pathlib import Path
import re

from test_support.makefile_contract_helpers import parse_makefile_db_sql_files

REPO_ROOT = Path(__file__).resolve().parents[1]
_AGE_BOOTSTRAP_SQL_PATH = "infra/db/09-age-graph-bootstrap.sql"


def read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _compose_init_mounts(compose_text: str) -> list[str]:
    return re.findall(r"^\s*-\s+(\.\./[^\s]+:/docker-entrypoint-initdb\.d/[^\s]+)$", compose_text, re.M)


def _normalized_compose_init_repo_paths(compose_text: str) -> list[str]:
    return [mount.split(":", 1)[0].removeprefix("../") for mount in _compose_init_mounts(compose_text)]


def test_entities_sql_enables_age_extension_after_btree_gist():
    entities_sql = read_repo_text("core/schema/entities.sql")

    assert "CREATE EXTENSION IF NOT EXISTS age;" in entities_sql
    btree_index = entities_sql.index('CREATE EXTENSION IF NOT EXISTS "btree_gist"')
    age_index = entities_sql.index("CREATE EXTENSION IF NOT EXISTS age;")
    assert age_index > btree_index


def test_entities_sql_enables_pg_trgm_extension_for_search_similarity():
    entities_sql = read_repo_text("core/schema/entities.sql")

    assert 'CREATE EXTENSION IF NOT EXISTS "pg_trgm";' in entities_sql


def test_entities_sql_fts_indexes_avoid_non_immutable_helpers():
    entities_sql = read_repo_text("core/schema/entities.sql")

    assert "CREATE INDEX idx_person_name_fts ON core.person" in entities_sql
    assert "CREATE INDEX idx_org_name_fts ON core.organization" in entities_sql
    assert "array_to_string(name_variants, ' ')" not in entities_sql


def test_docker_compose_targets_image_and_mounted_schema_files():
    compose = read_repo_text("infra/docker-compose.yml")

    assert "services:\n  db:" in compose
    assert "build:" in compose
    assert "context: .." in compose
    assert "dockerfile: infra/db/Dockerfile" in compose
    assert "POSTGRES_USER: ${POSTGRES_USER:-civibus}" in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}" in compose
    assert "POSTGRES_DB: ${POSTGRES_DB:-civibus}" in compose
    assert "POSTGRES_PORT: ${POSTGRES_PORT:-5433}" in compose
    assert "PGDATA: /var/lib/postgresql/data" in compose
    assert "127.0.0.1:${POSTGRES_PORT:-5433}:5432" in compose
    assert "pg_isready -U" in compose
    assert "$${POSTGRES_USER}" in compose
    assert "$${POSTGRES_DB}" in compose
    assert "interval: 5s" in compose
    assert "timeout: 5s" in compose
    assert "retries: 5" in compose
    assert "container_name:" not in compose
    compose_init_mounts = _compose_init_mounts(compose)
    assert (
        "../domains/campaign_finance/schema/nc_orchestrator_tables.sql:"
        "/docker-entrypoint-initdb.d/08-nc-orchestrator.sql"
    ) in compose_init_mounts


def test_docker_compose_init_mounts_stay_in_sync_with_makefile_db_sql_files() -> None:
    compose = read_repo_text("infra/docker-compose.yml")
    makefile = read_repo_text("Makefile")

    compose_schema_paths = _normalized_compose_init_repo_paths(compose)
    makefile_schema_paths = parse_makefile_db_sql_files(makefile)

    # Stage 2 allows one explicit exception: AGE graph bootstrap can remain reset-time-only.
    assert compose_schema_paths in (
        makefile_schema_paths,
        [*makefile_schema_paths, _AGE_BOOTSTRAP_SQL_PATH],
    )
    if compose_schema_paths != makefile_schema_paths:
        assert compose_schema_paths[-1] == _AGE_BOOTSTRAP_SQL_PATH


def test_bio_migration_bootstrap_manifest_sync() -> None:
    compose = read_repo_text("infra/docker-compose.yml")
    makefile = read_repo_text("Makefile")
    bio_migration = "core/schema/migrations/2026_04_30_person_bio_fields.sql"

    makefile_files = parse_makefile_db_sql_files(makefile)
    compose_paths = _normalized_compose_init_repo_paths(compose)

    in_makefile = bio_migration in makefile_files
    in_compose = bio_migration in compose_paths

    assert in_makefile == in_compose, (
        f"Bio migration presence must agree: Makefile={in_makefile}, docker-compose={in_compose}"
    )

    if in_makefile:
        entities_idx = makefile_files.index("core/schema/entities.sql")
        bio_idx = makefile_files.index(bio_migration)
        assert bio_idx == entities_idx + 1, (
            f"Bio migration must immediately follow entities.sql in DB_SQL_FILES; "
            f"entities at index {entities_idx}, bio at index {bio_idx}"
        )


def test_db_dockerfile_installs_postgis_and_age_for_postgres_18():
    dockerfile = read_repo_text("infra/db/Dockerfile")

    assert "FROM postgres:18-bookworm" in dockerfile
    assert "postgresql-18-postgis-3" in dockerfile
    assert "postgresql-18-postgis-3-scripts" in dockerfile
    assert "postgresql-18-age" in dockerfile
    assert "FROM postgres:17-bookworm" not in dockerfile
    assert "postgresql-17-postgis-3" not in dockerfile
    assert "postgresql-17-postgis-3-scripts" not in dockerfile
    assert "postgresql-17-age" not in dockerfile
    assert "postgresql-contrib" not in dockerfile


def test_graph_eval_script_targets_current_database_container():
    eval_script = read_repo_text("eval/03-graph-db/load_data.py")

    assert (
        "from core.docker_compose import DB_SERVICE_NAME, compose_project_name, resolve_compose_service_container"
        in eval_script
    )
    assert "resolve_compose_service_container(DB_SERVICE_NAME, repo_root=REPO_ROOT)" in eval_script
    assert "No running Compose container found for project" in eval_script
    assert 'AGE_CONTAINER_NAME = "civibus_db"' not in eval_script
    assert '"civibus_age"' not in eval_script


def test_schema_sql_helper_uses_shared_compose_db_resolver():
    schema_test = read_repo_text("domains/campaign_finance/tests/test_tables_schema.py")

    assert "from core.schema_sql_runner import (" in schema_test
    assert 'build_base_psql_command(database, command_env_var="CF_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)' in schema_test
    assert 'for container_name in ("civibus_db", "civibus_age")' not in schema_test
    assert '"civibus_db"' not in schema_test


def test_makefile_exports_and_targets_database_reset_command():
    makefile = read_repo_text("Makefile")

    assert "POSTGRES_USER ?= civibus" in makefile
    assert "POSTGRES_PASSWORD ?=" not in makefile
    assert "POSTGRES_DB ?= civibus" in makefile
    assert "POSTGRES_PORT ?= 5433" in makefile
    assert "WORKSPACE_SLUG :=" in makefile
    assert "COMPOSE_PROJECT_NAME ?= civibus_$(WORKSPACE_SLUG)" in makefile
    assert re.search(r"^export POSTGRES_USER$", makefile, re.M)
    assert re.search(r"^export POSTGRES_PASSWORD$", makefile, re.M)
    assert re.search(r"^export POSTGRES_DB$", makefile, re.M)
    assert re.search(r"^export POSTGRES_PORT$", makefile, re.M)
    assert re.search(r"^export COMPOSE_PROJECT_NAME$", makefile, re.M)
    assert "POSTGRES_PASSWORD must be set in the environment" in makefile
    assert re.search(
        r"^db-up: require-postgres-password\n^\tdocker compose -f infra/docker-compose.yml up -d", makefile, re.M
    )
    assert re.search(
        r"^db-down: require-postgres-password\n^\tdocker compose -f infra/docker-compose.yml down", makefile, re.M
    )
    db_sql_files_lines = re.findall(r"^override DB_SQL_FILES := .+$", makefile, re.M)
    assert len(db_sql_files_lines) == 1
    assert "domains/campaign_finance/schema/tables.sql" in db_sql_files_lines[0]
    assert "# shell and Python recipe bodies, so command-line overrides would become code execution." in makefile
    assert "db-reset: require-postgres-password" in makefile
    assert "db-reset: require-postgres-password\n\t@set -e; if command -v psql >/dev/null 2>&1; then \\" in makefile
    assert "DROP SCHEMA IF EXISTS core CASCADE;" in makefile
    assert 'test:\n\tuv run --extra dev --extra entity-resolution pytest -m "not integration and not e2e"' in makefile
    assert "test-api:\n\tuv run --extra dev --extra api pytest api/" in makefile
    assert 'test-e2e:\n\tuv run --extra dev pytest -m "e2e" -v' in makefile
    assert (
        "api-dev: require-postgres-password\n"
        "\tuv run --extra dev --extra api uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload"
    ) in makefile
    assert "lint:\n\t$(MAKE) check-retired-symbols\n\tuv run --extra dev ruff check ." in makefile
    assert "ruff format --check ." in makefile
    assert "quality-check:" in makefile
    assert "python -m domains.campaign_finance.quality.cli" in makefile


def test_makefile_retired_symbols_lint_guard_wiring():
    makefile = read_repo_text("Makefile")

    retired_symbols = re.search(r"^RETIRED_SYMBOLS := (.+)$", makefile, re.M)
    assert retired_symbols is not None
    # fmt: off
    # Split literals keep the retired-symbol git-grep guard from matching this
    # test file itself; fmt guards stop ruff format from re-joining them.
    assert retired_symbols.group(1).split() == [
        "INDIANA_" "FRESHNESS_NOTE",
        "_CASE_" "FIXTURE_SOURCES",
        "_PILOT_" "SUPPORTED_STATES",
        "is_autopublish_" "enabled",
    ]
    # fmt: on
    assert re.search(
        r"^RETIRED_ALLOWLIST := \\\n"
        r"^\tcore/keel_gate_l11\.py \\\n"
        r"^\ttests/keel/test_gate_l15\.py \\\n"
        r"^\tdocs/reference/keel/\*\* \\\n"
        r"^\tchats/\*\* \\\n"
        r"^\t\.matt/projects/\*\* \\\n"
        r"^\tMakefile$",
        makefile,
        re.M,
    )
    assert re.search(
        r"^lint:\n"
        r"^\t\$\(MAKE\) check-retired-symbols\n"
        r"^\tuv run --extra dev ruff check \.\n"
        r"^\tuv run --extra dev ruff format --check \.$",
        makefile,
        re.M,
    )


def test_makefile_stage6_state_sample_ingest_targets_wiring():
    makefile = read_repo_text("Makefile")

    assert re.search(
        r"^ingest-co-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.states\.CO\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/states/CO/scraper/test_fixtures/sample_contributions\.csv "
        r"--year 2024 --data-type contributions$",
        makefile,
        re.M,
    )
    assert re.search(
        r"^ingest-ga-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.states\.GA\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/states/GA/tests/fixtures/contribution_export_sample\.xls "
        r"--data-type contributions$",
        makefile,
        re.M,
    )
    assert re.search(
        r"^ingest-nc-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.states\.NC\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/states/NC/tests/fixtures/transaction_export_sample\.csv "
        r"--data-type transactions$",
        makefile,
        re.M,
    )
    # Stage 6 contract: NC sample target stays on provenance-only fallback.
    assert "--committee-docs-path" not in makefile.split("ingest-nc-sample:")[1].splitlines()[1]


def test_makefile_sf_city_sample_ingest_target():
    makefile = read_repo_text("Makefile")

    assert re.search(
        r"^ingest-sf-sample:\n"
        r"^\tuv run python -m domains\.campaign_finance\.jurisdictions\.cities\.SF\.scraper\.cli "
        r"--path domains/campaign_finance/jurisdictions/cities/SF/tests/test_fixtures/sample_transactions\.csv "
        r"--data-type transactions$",
        makefile,
        re.M,
    )


def test_makefile_stage2_bulk_targets_wiring():
    makefile = read_repo_text("Makefile")

    assert "FEC_BULK_CYCLE ?= 2024" in makefile
    assert "FEC_BULK_DIR ?= data/fec/bulk/$(FEC_BULK_CYCLE)" in makefile
    assert re.search(r"^download-fec-bulk:\n^\t@mkdir -p \"\$\(FEC_BULK_DIR\)\"", makefile, re.M)
    assert "uv run python -c 'from domains.campaign_finance.ingest.bulk_cli import fec_baseline_urls;" in makefile
    assert 'FEC_BULK_CYCLE="$(FEC_BULK_CYCLE)"' in makefile
    assert 'urls="$$(FEC_BULK_CYCLE="$(FEC_BULK_CYCLE)" uv run python -c' in makefile
    assert "|| exit $$?; \\" in makefile
    assert "for url in $$urls; do \\" in makefile
    assert 'curl -fLsS -z "$(FEC_BULK_DIR)/$$archive" -o "$(FEC_BULK_DIR)/$$archive" "$$url"' in makefile
    assert (
        "ingest-fec-bulk:\n"
        "\tuv run python -m domains.campaign_finance.ingest.bulk_cli "
        "--cycle $(FEC_BULK_CYCLE) --all --directory $(FEC_BULK_DIR) --batch-size 1000"
    ) in makefile
    assert "download-fec-weball:" in makefile
    assert "from domains.campaign_finance.ingest.bulk_cli import fec_weball_url;" in makefile
    assert (
        "ingest-fec-federal:\n"
        "\tuv run python -m domains.campaign_finance.ingest.bulk_cli "
        "--cycle $(FEC_BULK_CYCLE) --federal --directory $(FEC_BULK_DIR) --batch-size 1000"
    ) in makefile
    assert "download-fec-bulk:" in makefile
    assert "fec_baseline_urls" in makefile


def test_makefile_refresh_targets_route_through_runner_with_dry_run_default():
    makefile = read_repo_text("Makefile")

    assert "REFRESH_CF_ARGS ?= --dry-run" in makefile
    assert re.search(
        r"^refresh-cf-data:\n^\tuv run python -m core\.refresh\.runner --scope all \$\(REFRESH_CF_ARGS\)$",
        makefile,
        re.M,
    )
    assert re.search(
        r"^refresh-cf-priority:\n^\tuv run python -m core\.refresh\.runner --scope priority \$\(REFRESH_CF_ARGS\)$",
        makefile,
        re.M,
    )


def test_pyproject_dependencies_and_tooling_config():
    pyproject_text = read_repo_text("pyproject.toml")
    assert 'name = "civibus"' in pyproject_text
    assert 'requires-python = ">=3.12"' in pyproject_text
    assert "pydantic" in pyproject_text
    assert "psycopg[binary]" in pyproject_text
    assert "httpx" in pyproject_text
    dev_section = re.search(
        r"\[project.optional-dependencies\]\n^dev = \[\n([\s\S]*?)^\]",
        pyproject_text,
        re.M,
    )
    assert dev_section is not None
    dev_block = dev_section.group(0)
    assert "fastapi" in dev_block
    assert "pytest" in dev_block
    assert "pytest-asyncio" in dev_block
    assert "ruff" in dev_block
    assert ('[project.optional-dependencies]\ndev = [\n  "fastapi",\n') in pyproject_text
    assert ('api = [\n  "fastapi",\n  "uvicorn[standard]",\n]') in pyproject_text
    assert 'testpaths = ["api", "core", "domains", "tests"]' in pyproject_text
    assert 'addopts = ["--import-mode=importlib"]' in pyproject_text
    assert "unit:" in pyproject_text
    assert "integration:" in pyproject_text
    assert "line-length = 120" in pyproject_text
    assert 'target-version = "py312"' in pyproject_text
    assert "[tool.hatch.build.targets.wheel]" in pyproject_text
    assert 'packages = ["api", "core", "domains"]' in pyproject_text


def test_expected_directories_and_package_inits():
    for rel_path in [
        "infra/",
        "core/types/python/",
        "core/graph/",
        "domains/campaign_finance/schema/",
        "domains/campaign_finance/ingest/",
        "domains/campaign_finance/entity_extractors/",
        "domains/campaign_finance/normalize/",
        "domains/campaign_finance/quality/",
        "tests/fixtures/",
    ]:
        assert (REPO_ROOT / rel_path).is_dir()

    for rel_path in [
        "core/types/__init__.py",
        "core/types/python/__init__.py",
        "core/graph/__init__.py",
        "domains/__init__.py",
        "domains/campaign_finance/__init__.py",
        "domains/campaign_finance/ingest/__init__.py",
        "domains/campaign_finance/entity_extractors/__init__.py",
        "domains/campaign_finance/normalize/__init__.py",
        "domains/campaign_finance/quality/__init__.py",
    ]:
        assert (REPO_ROOT / rel_path).is_file()

    assert not (REPO_ROOT / "domains/campaign_finance/schema/__init__.py").exists()
    assert (REPO_ROOT / "domains/campaign_finance/schema/.gitkeep").is_file()
    assert (REPO_ROOT / "tests/fixtures/.gitkeep").is_file()


def test_schema_sql_defines_stage1_indexes_used_by_later_stages():
    expected_indexes_by_file = {
        "core/schema/entities.sql": [
            "idx_person_name_fts",
            "idx_org_name_fts",
            "idx_person_canonical_name_trgm",
            "idx_org_canonical_name_trgm",
            "idx_address_dedup",
            "idx_entity_address_current",
        ],
        "core/schema/jurisdiction.sql": [
            "idx_jurisdiction_fips_unique",
            "idx_jurisdiction_type",
            "idx_jurisdiction_parent",
        ],
        "core/schema/provenance.sql": [
            "idx_source_record_active_key",
            "idx_entity_source_dedup",
            "idx_field_prov_current",
        ],
        "core/schema/entity_resolution.sql": [
            "idx_match_active_pair",
            "idx_cluster_member_active",
            "idx_override_active_pair",
        ],
    }

    for relative_path, index_names in expected_indexes_by_file.items():
        schema_text = read_repo_text(relative_path)
        for index_name in index_names:
            assert index_name in schema_text


def test_stage1_person_and_portrait_schema_contract() -> None:
    entities_sql = read_repo_text("core/schema/entities.sql")
    provenance_sql = read_repo_text("core/schema/provenance.sql")

    assert "occupation" in entities_sql
    assert "education" in entities_sql
    assert "bio_text" in entities_sql
    assert "bio_source_url" in entities_sql
    assert "bio_license" in entities_sql
    assert "bio_pulled_at" in entities_sql
    assert "CREATE TABLE core.person_portrait (" in entities_sql

    required_portrait_fields = [
        "person_id",
        "status",
        "rights_status",
        "image_hash",
        "width_px",
        "height_px",
        "source_record_id",
        "source_image_url",
        "storage_uri",
        "dedup_key",
    ]
    for field_name in required_portrait_fields:
        assert field_name in entities_sql

    assert "idx_person_portrait_active_per_person" in entities_sql
    assert "idx_person_portrait_dedup" in entities_sql
    assert "idx_person_portrait_source_record" in entities_sql
    for status_value in ("active", "not_found", "too_small", "face_too_small", "takedown_requested", "superseded"):
        assert status_value in entities_sql
    assert "bio_provenance" not in entities_sql
    assert "bio_provenance" not in provenance_sql
    assert "fk_person_portrait_source_record" in provenance_sql


def test_jurisdiction_schema_relies_on_entities_sql_for_shared_definitions():
    jurisdiction_sql = read_repo_text("core/schema/jurisdiction.sql")

    assert "CREATE EXTENSION" not in jurisdiction_sql
    assert "CREATE TYPE core.date_precision" not in jurisdiction_sql
    assert "CREATE OR REPLACE FUNCTION core.set_updated_at()" not in jurisdiction_sql
    assert "EXECUTE FUNCTION core.set_updated_at();" in jurisdiction_sql


def test_gitignore_includes_data_cache_and_egg_info():
    gitignore_lines = {line.strip() for line in read_repo_text(".gitignore").splitlines()}
    assert "data/" in gitignore_lines
    assert ".env" in gitignore_lines
    assert "*.egg-info/" in gitignore_lines
