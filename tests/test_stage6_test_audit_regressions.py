from __future__ import annotations

from pathlib import Path
import re

import pytest

from infra.scripts import postgres_local
from test_support.makefile_contract_helpers import parse_makefile_db_sql_files


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_pyproject_dev_extra_includes_pandas_for_make_test_baseline() -> None:
    pyproject_text = read_repo_text("pyproject.toml")

    dev_section = re.search(
        r"\[project.optional-dependencies\]\n^dev = \[\n([\s\S]*?)^\]",
        pyproject_text,
        re.M,
    )
    assert dev_section is not None
    assert '  "pandas",' in dev_section.group(0)


def test_pyproject_entity_resolution_extra_includes_pandas_for_direct_runtime_imports() -> None:
    pyproject_text = read_repo_text("pyproject.toml")

    entity_resolution_section = re.search(
        r"^entity-resolution = \[\n([\s\S]*?)^\]",
        pyproject_text,
        re.M,
    )
    assert entity_resolution_section is not None
    assert '  "pandas",' in entity_resolution_section.group(0)


def test_conftest_reexecs_pytest_under_project_python_for_pre312_interpreters() -> None:
    conftest_text = read_repo_text("conftest.py")

    assert "_REEXEC_SENTINEL_ENV_VAR" in conftest_text
    assert "sys.version_info >= (3, 12)" in conftest_text
    assert 'os.execvp("uv", reexec_command)' in conftest_text
    assert '"--extra"' in conftest_text
    assert '"dev"' in conftest_text
    assert '"entity-resolution"' in conftest_text


def test_makefile_db_reset_sql_files_include_property_schema() -> None:
    makefile = read_repo_text("Makefile")
    compose_dev = read_repo_text("infra/docker-compose.yml")
    compose_prod = read_repo_text("infra/docker-compose.prod.yml")

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
    assert (
        "../domains/campaign_finance/schema/dark_money_tables.sql:/docker-entrypoint-initdb.d/09-dark-money.sql"
        in compose_dev
    )
    assert (
        "../domains/campaign_finance/schema/dark_money_tables.sql:/docker-entrypoint-initdb.d/08-dark-money.sql"
        in compose_prod
    )


def test_makefile_exposes_ingest_tx_sample_target_with_expected_fixture_command() -> None:
    makefile = read_repo_text("Makefile")

    phony_lines = re.findall(r"^\.PHONY:\s+(.+)$", makefile, re.M)

    assert phony_lines, "Expected a .PHONY declaration in Makefile"
    assert "ingest-tx-sample" in phony_lines[0].split()

    expected_target = (
        "ingest-tx-sample:\n"
        "\tuv run python -m domains.campaign_finance.jurisdictions.states.TX.scraper.cli "
        "--path domains/campaign_finance/jurisdictions/states/TX/scraper/test_fixtures/sample_contributions.csv "
        "--data-type contributions"
    )

    assert expected_target in makefile


def test_makefile_exposes_ingest_pa_sample_target_with_expected_fixture_command() -> None:
    makefile = read_repo_text("Makefile")

    phony_lines = re.findall(r"^\.PHONY:\s+(.+)$", makefile, re.M)

    assert phony_lines, "Expected a .PHONY declaration in Makefile"
    assert "ingest-pa-sample" in phony_lines[0].split()

    expected_target = (
        "ingest-pa-sample:\n"
        "\tuv run python -m domains.campaign_finance.jurisdictions.states.PA.scraper.cli "
        "--year 2025 "
        "--path domains/campaign_finance/jurisdictions/states/PA/scraper/test_fixtures/sample_contributions.csv "
        "--data-type contributions"
    )

    assert expected_target in makefile


def test_makefile_exposes_ingest_in_sample_target_with_expected_fixture_command() -> None:
    makefile = read_repo_text("Makefile")

    phony_lines = re.findall(r"^\.PHONY:\s+(.+)$", makefile, re.M)

    assert phony_lines, "Expected a .PHONY declaration in Makefile"
    assert "ingest-in-sample" in phony_lines[0].split()

    expected_target = (
        "ingest-in-sample:\n"
        "\tuv run python -m domains.campaign_finance.jurisdictions.states.IN.scraper.cli "
        "--path domains/campaign_finance/jurisdictions/states/IN/scraper/test_fixtures/sample_contributions.csv "
        "--data-type contributions"
    )

    assert expected_target in makefile


def test_makefile_exposes_ingest_nc_past_results_2022_2024_target() -> None:
    makefile = read_repo_text("Makefile")
    phony_lines = re.findall(r"^\.PHONY:\s+(.+)$", makefile, re.M)

    assert phony_lines, "Expected a .PHONY declaration in Makefile"
    assert "ingest-nc-past-results-2022-2024" in phony_lines[0].split()
    assert (
        "ingest-nc-past-results-2022-2024:\n"
        "\tuv run python -m core.refresh.runner --scope all --job-key-prefix civics-nc-past-results-2022-2024 $(REFRESH_CF_ARGS)"
    ) in makefile


def test_load_structure_test_skips_cleanly_without_locust_extra() -> None:
    load_test_text = read_repo_text("tests/load/test_locustfile_structure.py")

    assert 'ModuleType("locust")' in load_test_text
    assert 'monkeypatch.setitem(sys.modules, "locust", fake_locust)' in load_test_text
    assert "from locust import HttpUser" not in load_test_text


@pytest.mark.parametrize(
    ("raw_database_name", "expected_prefix"),
    [
        ("../../outside-target", "outside-target"),
        ("folder/with/slashes", "folder-with-slashes"),
        (" spaced db ", "spaced-db"),
    ],
)
def test_postgres_local_backup_sanitizes_database_name_for_output_filename(
    raw_database_name: str,
    expected_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = postgres_local.LocalPostgresRuntime(
        compose_project_name="civibus",
        compose_service_name="db",
        container_name="civibus-db-1",
        connection_parameters={"user": "civibus", "dbname": raw_database_name, "host": "localhost", "port": 5433},
        database_name=raw_database_name,
    )

    monkeypatch.setattr(
        postgres_local, "resolve_local_postgres_runtime", lambda repo_root=postgres_local.REPO_ROOT: runtime
    )
    monkeypatch.setattr(postgres_local, "_required_postgres_password", lambda: "test-password")

    def fake_run_command(
        command: list[str],
        *,
        cwd: Path | None = None,
        stdin=None,
        input: bytes | None = None,
        stdout=None,
        env: dict[str, str] | None = None,
    ) -> None:
        if stdout is not None:
            stdout.write(b"fixture-backup")

    monkeypatch.setattr(postgres_local, "_run_command", fake_run_command)

    backup_path = postgres_local.create_backup(output_dir=tmp_path)

    assert backup_path.resolve().parent == tmp_path.resolve()
    assert backup_path.name.startswith(f"{expected_prefix}-")
    assert "/" not in backup_path.name
