
from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import subprocess
from pathlib import Path

from core.docker_compose import DB_SERVICE_NAME, resolve_compose_service_container
from core.schema_sql_fallback import run_sql_file_via_psycopg, run_sql_via_psycopg


_DOCKER_EXEC_OPTIONS_WITH_VALUE = {
    "-e",
    "--env",
    "--env-file",
    "-u",
    "--user",
    "-w",
    "--workdir",
    "--detach-keys",
}
_PSQL_DISALLOWED_OVERRIDE_FLAGS = {
    "-c",
    "--command",
    "-f",
    "--file",
}
_PSQL_COMMAND_TAG_PATTERN = re.compile(
    r"^(?:INSERT \d+ \d+|UPDATE \d+|DELETE \d+|MERGE \d+|COPY \d+|SELECT \d+|MOVE \d+|FETCH \d+)$"
)


def _command_binary_name(token: str) -> str:
    return Path(token).name


def _docker_exec_psql_command(container_name: str, database: str) -> list[str]:
    return ["docker", "exec", container_name, "psql", "-U", "civibus", "-d", database]


def _is_docker_exec_option_with_value(token: str) -> bool:
    return any(token == option or token.startswith(f"{option}=") for option in _DOCKER_EXEC_OPTIONS_WITH_VALUE)


def _docker_exec_container_and_inner_command(base_command: list[str]) -> tuple[str | None, int | None]:
    if len(base_command) < 4 or _command_binary_name(base_command[0]) != "docker" or base_command[1] != "exec":
        return None, None

    option_index = 2
    while option_index < len(base_command):
        token = base_command[option_index]
        if not token.startswith("-"):
            inner_command_index = option_index + 1
            if inner_command_index >= len(base_command):
                return token, None
            return token, inner_command_index
        option_index += 1 if "=" in token or not _is_docker_exec_option_with_value(token) else 2

    return None, None


def _docker_exec_container_name(base_command: list[str]) -> str | None:
    container_name, _ = _docker_exec_container_and_inner_command(base_command)
    return container_name


def _docker_exec_inner_command_index(base_command: list[str]) -> int | None:
    _, inner_command_index = _docker_exec_container_and_inner_command(base_command)
    return inner_command_index


def _docker_exec_with_replaced_inner_command(base_command: list[str], inner_command: list[str]) -> list[str]:
    inner_command_index = _docker_exec_inner_command_index(base_command)
    if inner_command_index is None:
        raise RuntimeError("Docker SQL execution requires a docker exec command with an explicit inner command.")
    return base_command[:inner_command_index] + inner_command


def _container_sql_path(sql_file: Path) -> str:
    random_suffix = secrets.token_hex(16)
    return f"/tmp/{random_suffix}-{sql_file.name}"


def _ensure_safe_psql_override_tokens(command_tokens: list[str], *, command_env_var: str, psql_index: int) -> list[str]:
    for token in command_tokens[psql_index + 1 :]:
        if any(token == flag or token.startswith(f"{flag}=") for flag in _PSQL_DISALLOWED_OVERRIDE_FLAGS):
            raise RuntimeError(
                f"{command_env_var} may not include psql SQL execution flags like -c/--command or -f/--file"
            )
    return command_tokens


def _skip_env_prefix(command_tokens: list[str]) -> int:
    if _command_binary_name(command_tokens[0]) != "env":
        return 0

    token_index = 1
    while token_index < len(command_tokens):
        token = command_tokens[token_index]
        if token == "--":
            return token_index + 1
        if "=" in token and not token.startswith("-"):
            token_index += 1
            continue
        break
    return token_index


def _psql_command_index(command_tokens: list[str]) -> int | None:
    """Return the index of the psql binary after optional env/docker exec wrappers."""
    command_index = _skip_env_prefix(command_tokens)
    if command_index >= len(command_tokens):
        return None

    command_name = _command_binary_name(command_tokens[command_index])
    if command_name == "psql":
        return command_index

    if (
        command_name != "docker"
        or len(command_tokens[command_index:]) < 4
        or command_tokens[command_index + 1] != "exec"
    ):
        return None

    inner_command_index = _docker_exec_inner_command_index(command_tokens[command_index:])
    if inner_command_index is None:
        return None

    psql_index = command_index + inner_command_index
    if _command_binary_name(command_tokens[psql_index]) != "psql":
        return None
    return psql_index


def _validated_env_psql_command(command_text: str, *, command_env_var: str) -> list[str]:
    command_tokens = shlex.split(command_text)
    if not command_tokens:
        raise RuntimeError(f"{command_env_var} must not be empty")

    psql_index = _psql_command_index(command_tokens)
    if psql_index is None:
        raise RuntimeError(f"{command_env_var} must invoke psql directly or via docker exec")
    return _ensure_safe_psql_override_tokens(command_tokens, command_env_var=command_env_var, psql_index=psql_index)


def build_base_psql_command(database: str, *, command_env_var: str, repo_root: Path) -> list[str]:
    env_command = os.getenv(command_env_var)
    if env_command:
        return _validated_env_psql_command(env_command, command_env_var=command_env_var) + ["-d", database]

    if shutil.which("docker") is not None:
        container_name = resolve_compose_service_container(DB_SERVICE_NAME, repo_root=repo_root)
        if container_name is not None:
            return _docker_exec_psql_command(container_name, database)

    if shutil.which("psql") is not None:
        return ["psql", "-d", database]

    return []


def _run_command(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _is_psql_command_tag(output_line: str) -> bool:
    return bool(_PSQL_COMMAND_TAG_PATTERN.match(output_line))


def run_psql_command(
    database: str,
    sql: str,
    *,
    command_env_var: str,
    repo_root: Path,
    expect_tuples: bool = True,
) -> list[str] | str:
    base_command = build_base_psql_command(database, command_env_var=command_env_var, repo_root=repo_root)
    if not base_command:
        return run_sql_via_psycopg(database, sql, expect_tuples=expect_tuples)

    command = base_command + ["-v", "ON_ERROR_STOP=1", "-A", "-t"]
    if sql.strip():
        command += ["-c", sql]

    output = _run_command(command)
    if not expect_tuples:
        return output
    if not output:
        return []
    return [line for line in (line.strip() for line in output.splitlines()) if line and not _is_psql_command_tag(line)]


def run_psql_file(database: str, sql_file: Path, *, command_env_var: str, repo_root: Path) -> None:
    base_command = build_base_psql_command(database, command_env_var=command_env_var, repo_root=repo_root)
    if not base_command:
        run_sql_file_via_psycopg(database, sql_file)
        return

    if _command_binary_name(base_command[0]) == "docker":
        container = _docker_exec_container_name(base_command)
        if container is None:
            raise RuntimeError("Docker SQL execution requires a docker exec command with an explicit container name.")
        container_sql_path = _container_sql_path(sql_file)
        _run_command(["docker", "cp", str(sql_file), f"{container}:{container_sql_path}"])
        command = base_command + ["-v", "ON_ERROR_STOP=1", "-f", container_sql_path]
        cleanup_command = _docker_exec_with_replaced_inner_command(base_command, ["rm", "-f", container_sql_path])
        command_failed = False
        try:
            _run_command(command)
        except RuntimeError:
            command_failed = True
            raise
        finally:
            try:
                _run_command(cleanup_command)
            except RuntimeError:
                if not command_failed:
                    raise
    else:
        command = base_command + ["-v", "ON_ERROR_STOP=1", "-f", str(sql_file)]
        _run_command(command)
