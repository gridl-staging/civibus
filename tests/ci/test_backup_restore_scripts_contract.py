from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT_PATH = REPO_ROOT / "infra/scripts/backup.sh"
RESTORE_SCRIPT_PATH = REPO_ROOT / "infra/scripts/restore.sh"
POSTGRES_LOCAL_HELPER_PATH = REPO_ROOT / "infra/scripts/postgres_local.py"
README_PATH = REPO_ROOT / "infra/scripts/README.md"
BACKUPS_DIRECTORY_PATH = REPO_ROOT / "infra/scripts/backups"
BACKUPS_GITIGNORE_PATH = BACKUPS_DIRECTORY_PATH / ".gitignore"

# Fragments that must not appear in thin-wrapper shell scripts — they indicate
# the script is reimplementing logic that belongs in postgres_local.py.
_THIN_WRAPPER_FORBIDDEN_FRAGMENTS = (
    "docker compose",
    "POSTGRES_USER=",
    "POSTGRES_DB=",
    "POSTGRES_PORT=",
    "5432",
    "5433",
    "civibus",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_script(path: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(path), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_backup_script_is_thin_wrapper_over_shared_helper() -> None:
    assert BACKUP_SCRIPT_PATH.is_file(), "infra/scripts/backup.sh must exist"
    assert POSTGRES_LOCAL_HELPER_PATH.is_file(), "infra/scripts/postgres_local.py must exist"

    backup_script_text = _read_text(BACKUP_SCRIPT_PATH)

    assert "infra/scripts/postgres_local.py backup" in backup_script_text
    assert "POSTGRES_PASSWORD" in backup_script_text

    for fragment in (*_THIN_WRAPPER_FORBIDDEN_FRAGMENTS, "pg_dump"):
        assert fragment not in backup_script_text


def test_backup_script_requires_postgres_password() -> None:
    env = {k: v for k, v in os.environ.items() if k != "POSTGRES_PASSWORD"}
    result = _run_script(BACKUP_SCRIPT_PATH, env=env)

    assert result.returncode != 0
    assert "POSTGRES_PASSWORD must be set in the environment" in (result.stderr + result.stdout)


def test_backup_output_directory_ignores_generated_dumps() -> None:
    assert BACKUPS_GITIGNORE_PATH.is_file(), "infra/scripts/backups/.gitignore must exist"

    assert _read_text(BACKUPS_GITIGNORE_PATH).strip().splitlines() == ["*.dump"]


def test_restore_script_requires_dump_path_and_destructive_confirmation() -> None:
    assert RESTORE_SCRIPT_PATH.is_file(), "infra/scripts/restore.sh must exist"
    assert POSTGRES_LOCAL_HELPER_PATH.is_file(), "infra/scripts/postgres_local.py must exist"

    restore_script_text = _read_text(RESTORE_SCRIPT_PATH)

    assert "infra/scripts/postgres_local.py restore" in restore_script_text
    assert "POSTGRES_PASSWORD" in restore_script_text
    assert "--yes-overwrite-local-db" in restore_script_text

    for fragment in (*_THIN_WRAPPER_FORBIDDEN_FRAGMENTS, "pg_restore"):
        assert fragment not in restore_script_text

    env = os.environ.copy()
    env["POSTGRES_PASSWORD"] = "contract-password"

    missing_dump_result = _run_script(RESTORE_SCRIPT_PATH, env=env)
    assert missing_dump_result.returncode != 0
    assert "Usage:" in (missing_dump_result.stderr + missing_dump_result.stdout)

    missing_confirmation_result = _run_script(RESTORE_SCRIPT_PATH, "infra/scripts/backups/example.dump", env=env)
    assert missing_confirmation_result.returncode != 0
    assert "--yes-overwrite-local-db" in (missing_confirmation_result.stderr + missing_confirmation_result.stdout)


def test_scripts_readme_points_back_to_repo_runtime_contracts() -> None:
    assert README_PATH.is_file(), "infra/scripts/README.md must exist"

    readme_text = _read_text(README_PATH)

    for required_fragment in (
        "infra/scripts/backup.sh",
        "infra/scripts/restore.sh",
        "Makefile",
        "infra/docker-compose.yml",
        "core/db.py",
        "core/docker_compose.py",
        "POSTGRES_PASSWORD",
        "make db-up",
        "overwrites the current local database",
    ):
        assert required_fragment in readme_text
