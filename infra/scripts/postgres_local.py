"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar26_am_3_new_state_pipeline_builds/civibus_dev/infra/scripts/postgres_local.py.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.db import build_connection_parameters
from core.docker_compose import DB_SERVICE_NAME, compose_project_name, resolve_compose_service_container


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BACKUP_DIRECTORY = Path("infra/scripts/backups")
RESTORE_CONFIRMATION_FLAG = "--yes-overwrite-local-db"


@dataclass(frozen=True)
class LocalPostgresRuntime:
    compose_project_name: str
    compose_service_name: str
    container_name: str
    connection_parameters: dict[str, str | int]
    database_name: str


def resolve_local_postgres_runtime(*, repo_root: Path = REPO_ROOT) -> LocalPostgresRuntime:
    connection_parameters = build_connection_parameters()
    database_name = str(connection_parameters["dbname"])
    project_name = compose_project_name(repo_root)
    container_name = resolve_compose_service_container(DB_SERVICE_NAME, repo_root=repo_root)
    if container_name is None:
        raise RuntimeError(
            "Unable to locate a running Compose container for service "
            f"'{DB_SERVICE_NAME}' in project '{project_name}'. Start the local DB via `make db-up`."
        )

    return LocalPostgresRuntime(
        compose_project_name=project_name,
        compose_service_name=DB_SERVICE_NAME,
        container_name=container_name,
        connection_parameters=connection_parameters,
        database_name=database_name,
    )


def _required_postgres_password() -> str:
    postgres_password = os.getenv("POSTGRES_PASSWORD")
    if not postgres_password:
        raise RuntimeError("POSTGRES_PASSWORD must be set in the environment")
    return postgres_password


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    stdin=None,
    stdout=None,
    env: dict[str, str] | None = None,
) -> None:
    child_env = None if env is None else {**os.environ, **env}
    subprocess.run(command, cwd=cwd, check=True, stdin=stdin, stdout=stdout, env=child_env)


def create_backup(*, output_dir: Path, repo_root: Path = REPO_ROOT) -> Path:
    runtime = resolve_local_postgres_runtime(repo_root=repo_root)
    postgres_password = _required_postgres_password()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_database_name = (
        "-".join(
            part for part in runtime.database_name.strip().replace("\\", "/").split("/") if part not in {"", ".", ".."}
        ).replace(" ", "-")
        or "postgres"
    )
    backup_path = output_dir / f"{safe_database_name}-{timestamp}.dump"
    pg_dump_command = [
        "docker",
        "exec",
        "-e",
        "PGPASSWORD",
        runtime.container_name,
        "pg_dump",
        "-U",
        str(runtime.connection_parameters["user"]),
        "-d",
        runtime.database_name,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
    ]
    with backup_path.open("wb") as dump_file:
        _run_command(pg_dump_command, stdout=dump_file, env={"PGPASSWORD": postgres_password})

    return backup_path


def restore_backup(*, dump_path: Path, repo_root: Path = REPO_ROOT) -> None:
    if not dump_path.is_file():
        raise RuntimeError(f"Backup dump file does not exist: {dump_path}")

    runtime = resolve_local_postgres_runtime(repo_root=repo_root)
    postgres_password = _required_postgres_password()

    _run_command(["make", "db-reset"], cwd=repo_root)

    pg_restore_command = [
        "docker",
        "exec",
        "-i",
        "-e",
        "PGPASSWORD",
        runtime.container_name,
        "pg_restore",
        "-U",
        str(runtime.connection_parameters["user"]),
        "-d",
        runtime.database_name,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
    ]
    with dump_path.open("rb") as dump_file:
        _run_command(pg_restore_command, cwd=repo_root, stdin=dump_file, env={"PGPASSWORD": postgres_password})


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local PostgreSQL backup and restore tooling for the Compose db service."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a local PostgreSQL backup dump.")
    backup_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIRECTORY,
        help="Directory where backup dumps are written.",
    )

    restore_parser = subparsers.add_parser("restore", help="Restore a local PostgreSQL dump into the active local DB.")
    restore_parser.add_argument("dump_path", type=Path, help="Path to the backup dump generated by backup.")
    restore_parser.add_argument(
        RESTORE_CONFIRMATION_FLAG,
        action="store_true",
        help="Acknowledge that restore overwrites the current local database.",
    )

    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    if args.command == "backup":
        backup_path = create_backup(output_dir=args.output_dir.resolve())
        print(f"Backup created: {backup_path}")
        return 0

    if not args.yes_overwrite_local_db:
        parser.error(
            f"Refusing to restore without explicit overwrite acknowledgement. Pass {RESTORE_CONFIRMATION_FLAG}."
        )

    restore_backup(dump_path=args.dump_path.resolve())
    print(f"Restore completed from: {args.dump_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
