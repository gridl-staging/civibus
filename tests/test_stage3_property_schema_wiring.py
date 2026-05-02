from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_stage3_property_schema_file_exists() -> None:
    assert (REPO_ROOT / "domains/property/schema/tables.sql").is_file()


def test_stage3_makefile_appends_property_schema_to_db_sql_files_in_order() -> None:
    makefile = read_repo_text("Makefile")

    assert re.search(
        r"^DB_SQL_FILES := core/schema/entities\.sql "
        r"core/schema/jurisdiction\.sql "
        r"core/schema/provenance\.sql "
        r"core/schema/entity_resolution\.sql "
        r"core/schema/er_views\.sql "
        r"domains/campaign_finance/schema/tables\.sql "
        r"domains/campaign_finance/schema/nc_orchestrator_tables\.sql "
        r"domains/campaign_finance/schema/dark_money_tables\.sql "
        r"domains/property/schema/tables\.sql "
        r"domains/civics/schema/tables\.sql "
        r"infra/db/09-age-graph-bootstrap\.sql$",
        makefile,
        re.M,
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
