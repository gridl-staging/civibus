"""Contract tests for the destructive provenance-schema integration fixture."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_SCHEMA_TEST = REPO_ROOT / "core" / "schema" / "test_provenance_schema.py"
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"
TEST_DATABASE_INIT = REPO_ROOT / "infra" / "db" / "00_create_provenance_test_database.sql"


def test_provenance_schema_gate_owns_a_dedicated_database() -> None:
    test_source = PROVENANCE_SCHEMA_TEST.read_text(encoding="utf-8")
    compose_source = COMPOSE_FILE.read_text(encoding="utf-8")

    assert 'os.getenv("PROVENANCE_SCHEMA_TEST_DATABASE", "civibus_provenance_test")' in test_source
    assert TEST_DATABASE_INIT.read_text(encoding="utf-8").strip() == "CREATE DATABASE civibus_provenance_test;"
    assert (
        "../infra/db/00_create_provenance_test_database.sql:"
        "/docker-entrypoint-initdb.d/00_create_provenance_test_database.sql"
    ) in compose_source
