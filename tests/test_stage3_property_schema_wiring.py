from __future__ import annotations

from pathlib import Path

from test_support.makefile_contract_helpers import parse_makefile_db_sql_files


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_stage3_property_schema_file_exists() -> None:
    assert (REPO_ROOT / "domains/property/schema/tables.sql").is_file()


def test_stage3_makefile_appends_property_schema_to_db_sql_files_in_order() -> None:
    makefile = read_repo_text("Makefile")
    db_sql_files = parse_makefile_db_sql_files(makefile)

    assert db_sql_files[:6] == [
        "core/schema/entities.sql",
        "core/schema/migrations/2026_04_30_person_bio_fields.sql",
        "core/schema/jurisdiction.sql",
        "core/schema/provenance.sql",
        "core/schema/entity_resolution.sql",
        "core/schema/er_views.sql",
    ]
    assert db_sql_files.index("domains/property/schema/tables.sql") < db_sql_files.index(
        "domains/civics/schema/tables.sql"
    )


def test_stage3_db_reset_drops_prop_schema_in_psql_and_psycopg_paths() -> None:
    makefile = read_repo_text("Makefile")

    assert "DROP SCHEMA IF EXISTS cf CASCADE; DROP SCHEMA IF EXISTS prop CASCADE;" in makefile
    assert "DROP SCHEMA IF EXISTS civic CASCADE;" in makefile
    assert "DROP SCHEMA IF EXISTS core CASCADE;" in makefile
    assert "conn.execute('DROP SCHEMA IF EXISTS cf CASCADE')" in makefile
    assert "conn.execute('DROP SCHEMA IF EXISTS prop CASCADE')" in makefile
    assert "conn.execute('DROP SCHEMA IF EXISTS civic CASCADE')" in makefile
    assert "conn.execute('DROP SCHEMA IF EXISTS core CASCADE')" in makefile


def test_stage3_no_property_ingest_target_in_makefile() -> None:
    makefile = read_repo_text("Makefile")

    assert "ingest-property-" not in makefile
