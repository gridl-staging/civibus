"""Shell contract tests for the B2 database-backup scripts.

One owner for all backup shell coverage: the shared object-contract library
(`infra/scripts/b2_backup_lib.sh`), the parked Hetzner cron entrypoint
(`infra/scripts/backup_to_b2.sh`), and the live Fly wrapper
(`infra/scripts/backup_fly_db_to_b2.sh`).

The wrapper tests drive the real scripts against stub `docker`, `pg_dump`,
`psql`, and `rclone` binaries on `PATH`. Each stub records its argv and its
inherited environment, so the assertions below are about what the scripts
actually asked those tools to do — not merely that they exited 0.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
LIB_PATH = SCRIPTS_DIR / "b2_backup_lib.sh"
HETZNER_WRAPPER_PATH = SCRIPTS_DIR / "backup_to_b2.sh"
FLY_WRAPPER_PATH = SCRIPTS_DIR / "backup_fly_db_to_b2.sh"
CHECKER_PATH = SCRIPTS_DIR / "check_fly_db_backup_freshness.sh"
INSTALLER_PATH = SCRIPTS_DIR / "install_refresh_cron.sh"
BACKUP_RUNBOOK_PATH = REPO_ROOT / "docs/howto/operations/db-backup-runbook.md"

TEST_BUCKET = "civibus-test-bucket"
TEST_DB_PASSWORD = "postgres-password-sentinel"
TEST_B2_APPLICATION_KEY = "b2-application-key-sentinel"

FLY_PREFIX = "fly/civibus-db/"
FLY_PREFIX_PATH = f"b2:{TEST_BUCKET}/{FLY_PREFIX}"
BUCKET_ROOT_PATH = f"b2:{TEST_BUCKET}/"
DUMP_OBJECT_NAME_REGEX = re.compile(r"^db-\d{8}T\d{6}Z\.dump$")
CUSTOM_FORMAT_DUMP_FLAGS = ("--format=custom", "--compress=6", "--no-owner", "--no-privileges")

SCRIPT_RUN_TIMEOUT_SECONDS = 30

# Stub binaries record every invocation into an ordered per-call directory so
# the tests can assert argv and inherited environment, including the absence of
# password material. `compgen -e` enumerates exported names under bash 3.2.
STUB_BINARY_TEMPLATE = """#!/usr/bin/env bash
set -uo pipefail

tool_name="$(basename "$0")"
call_sequence=0
while ! mkdir "${STUB_CALL_DIR}/$(printf '%04d' "${call_sequence}")_${tool_name}" 2>/dev/null; do
  call_sequence=$((call_sequence + 1))
done
call_dir="${STUB_CALL_DIR}/$(printf '%04d' "${call_sequence}")_${tool_name}"

: >"${call_dir}/argv"
if (( $# > 0 )); then
  printf '%s\\0' "$@" >"${call_dir}/argv"
fi

for exported_name in $(compgen -e); do
  printf '%s=%s\\0' "${exported_name}" "${!exported_name}"
done >"${call_dir}/env"

if [[ -n "${PGPASSFILE:-}" && -f "${PGPASSFILE}" ]]; then
  { stat -f '%Lp' -- "${PGPASSFILE}" 2>/dev/null \\
    || stat -c '%a' -- "${PGPASSFILE}" 2>/dev/null; } >"${call_dir}/pgpassfile_mode"
  cp -- "${PGPASSFILE}" "${call_dir}/pgpassfile_content"
fi

cat >/dev/null

case "${tool_name}" in
  pg_dump)
    for argument in "$@"; do
      if [[ "${argument}" == "--version" ]]; then
        printf 'pg_dump (PostgreSQL) %s\\n' "${STUB_PG_DUMP_VERSION}"
        exit 0
      fi
    done
    printf 'PGDMP stub dump payload\\n'
    exit "${STUB_PG_DUMP_EXIT}"
    ;;
  psql)
    printf '%s\\n' "${STUB_SERVER_VERSION_OUTPUT}"
    ;;
  docker)
    printf 'PGDMP stub dump payload\\n'
    ;;
  rclone)
    # The freshness checker lists the Fly prefix with `rclone lsf`; emit the
    # fixture-controlled rows so the test drives which objects the checker sees.
    if [[ "${1:-}" == "lsf" ]]; then
      printf '%s' "${STUB_RCLONE_LSF_OUTPUT}"
    fi
    exit "${STUB_RCLONE_EXIT}"
    ;;
esac
exit 0
"""

# Test double for env_lib.sh. It mirrors the real library's exported surface —
# crucially including PGPASSWORD, which the Fly wrapper must remove before any
# libpq client runs — without reading a real .env or sanitizing PATH (the real
# sanitizer would drop the stub bin directory staged under a shared tmpdir).
ENV_LIB_STUB = """#!/usr/bin/env bash
load_civibus_env() {
  export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
  export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  export PGHOST="${POSTGRES_HOST}"
  export PGPORT="${POSTGRES_PORT}"
  export PGUSER="${POSTGRES_USER:-civibus}"
  export PGPASSWORD="${POSTGRES_PASSWORD}"
  export PGDATABASE="${POSTGRES_DB:-civibus}"
}
"""

STUBBED_TOOLS = ("docker", "pg_dump", "psql", "rclone")
STAGED_SCRIPTS = (LIB_PATH, HETZNER_WRAPPER_PATH, FLY_WRAPPER_PATH, CHECKER_PATH)


@dataclass(frozen=True)
class StubCall:
    """One recorded invocation of a stubbed external binary."""

    tool: str
    argv: list[str]
    env: dict[str, str]
    pgpassfile_mode: str | None
    pgpassfile_content: str | None

    @property
    def argv_text(self) -> str:
        return " ".join(self.argv)

    def flag_value(self, flag: str) -> str | None:
        for index, argument in enumerate(self.argv[:-1]):
            if argument == flag:
                return self.argv[index + 1]
        return None


@dataclass(frozen=True)
class ScriptRun:
    """Result of running one backup script against the stubbed toolchain."""

    completed: subprocess.CompletedProcess[str]
    calls: list[StubCall]

    def calls_for(self, tool: str) -> list[StubCall]:
        return [call for call in self.calls if call.tool == tool]

    def rclone_calls(self, subcommand: str) -> list[StubCall]:
        return [call for call in self.calls_for("rclone") if call.argv[:1] == [subcommand]]

    @property
    def output(self) -> str:
        return self.completed.stdout + self.completed.stderr


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _read_null_separated(path: Path) -> list[str]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8")
    return [entry for entry in raw.split("\0") if entry != ""]


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _collect_stub_calls(call_dir: Path) -> list[StubCall]:
    calls: list[StubCall] = []
    for entry in sorted(call_dir.iterdir()):
        sequence, _, tool = entry.name.partition("_")
        assert sequence.isdigit(), f"unexpected stub call directory: {entry.name}"
        env_pairs = (pair.split("=", 1) for pair in _read_null_separated(entry / "env"))
        calls.append(
            StubCall(
                tool=tool,
                argv=_read_null_separated(entry / "argv"),
                env={key: value for key, value in env_pairs},
                pgpassfile_mode=(_read_optional_text(entry / "pgpassfile_mode") or "").strip() or None,
                pgpassfile_content=_read_optional_text(entry / "pgpassfile_content"),
            )
        )
    return calls


def _stage_backup_harness(tmp_path: Path, *, write_env_file: bool) -> tuple[Path, Path, dict[str, str]]:
    """Stage a fake repo, stub binaries, and the environment the scripts see."""
    fake_scripts_dir = tmp_path / "fake_repo" / "infra" / "scripts"
    fake_scripts_dir.mkdir(parents=True)
    _write_executable(fake_scripts_dir / "env_lib.sh", ENV_LIB_STUB)
    for script_path in STAGED_SCRIPTS:
        assert script_path.is_file(), f"{script_path} must exist"
        _write_executable(fake_scripts_dir / script_path.name, script_path.read_text(encoding="utf-8"))

    if write_env_file:
        # Presence of .env is what makes the wrapper call load_civibus_env, and
        # therefore what makes the PGPASSWORD-removal assertions meaningful.
        (tmp_path / "fake_repo" / ".env").write_text("POSTGRES_PASSWORD=unused-by-stub\n", encoding="utf-8")

    stub_bin_dir = tmp_path / "stub_bin"
    stub_bin_dir.mkdir()
    for tool in STUBBED_TOOLS:
        _write_executable(stub_bin_dir / tool, STUB_BINARY_TEMPLATE)

    call_dir = tmp_path / "stub_calls"
    call_dir.mkdir()

    env = {
        "PATH": f"{stub_bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path / "tmp"),
        "STUB_CALL_DIR": str(call_dir),
        "STUB_PG_DUMP_VERSION": "18.2",
        "STUB_PG_DUMP_EXIT": "0",
        "STUB_SERVER_VERSION_OUTPUT": "180002",
        "STUB_RCLONE_EXIT": "0",
        "STUB_RCLONE_LSF_OUTPUT": "",
        "B2_BUCKET": TEST_BUCKET,
        "B2_ACCOUNT_ID": "b2-account-id",
        "B2_APPLICATION_KEY": TEST_B2_APPLICATION_KEY,
        "FLY_BACKUP_DB_PASSWORD": TEST_DB_PASSWORD,
        "POSTGRES_PASSWORD": TEST_DB_PASSWORD,
    }
    Path(env["HOME"]).mkdir()
    Path(env["TMPDIR"]).mkdir()
    return fake_scripts_dir, call_dir, env


def _run_backup_script(
    tmp_path: Path,
    script_path: Path,
    *,
    write_env_file: bool = True,
    script_args: tuple[str, ...] = (),
    **env_overrides: str,
) -> ScriptRun:
    fake_scripts_dir, call_dir, env = _stage_backup_harness(tmp_path, write_env_file=write_env_file)
    env.update(env_overrides)
    completed = subprocess.run(
        ["bash", str(fake_scripts_dir / script_path.name), *script_args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=SCRIPT_RUN_TIMEOUT_SECONDS,
    )
    return ScriptRun(completed=completed, calls=_collect_stub_calls(call_dir))


def _run_lib_shell(body: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Source the real library and evaluate `body` against it."""
    script = f"set -euo pipefail\nsource {shlex.quote(str(LIB_PATH))}\n{body}\n"
    env = {"PATH": "/usr/bin:/bin", "B2_BUCKET": TEST_BUCKET}
    env.update(env_overrides)
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=SCRIPT_RUN_TIMEOUT_SECONDS,
    )


def _assert_sensitive_value_not_exposed(run: ScriptRun, sensitive_value: str) -> None:
    assert sensitive_value not in run.output, "backup script output exposed secret material"
    for call in run.calls:
        assert sensitive_value not in call.argv_text, f"secret leaked into {call.tool} argv: {call.argv}"


def _assert_no_password_exposure(run: ScriptRun) -> None:
    """No backup command or script output may expose secret material."""
    for sensitive_value in (TEST_DB_PASSWORD, TEST_B2_APPLICATION_KEY):
        _assert_sensitive_value_not_exposed(run, sensitive_value)

    for call in run.calls:
        assert TEST_DB_PASSWORD not in call.env.values(), f"{call.tool} inherited raw database password material"
        if call.tool != "rclone":
            assert TEST_B2_APPLICATION_KEY not in call.env.values(), f"{call.tool} inherited the B2 application key"
        paired = list(zip(call.argv, call.argv[1:]))
        assert not any(first == "-e" and second == "PGPASSWORD" for first, second in paired), (
            f"PGPASSWORD must not be injected via -e: {call.argv}"
        )
        assert "PGPASSWORD=" not in call.argv_text, f"PGPASSWORD must not appear in argv: {call.argv}"


# ---------- shared library contract ----------


def test_lib_builds_canonical_dump_object_names_from_utc_timestamps() -> None:
    result = _run_lib_shell('b2_backup_dump_object_name "20260816T023001Z"')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "db-20260816T023001Z.dump"
    assert DUMP_OBJECT_NAME_REGEX.match(result.stdout.strip())


@pytest.mark.parametrize(
    "malformed_timestamp",
    ["", "20260816", "2026-08-16T02:30:01Z", "20260816T023001", "20260816T023001z", "20260816T0230011Z"],
)
def test_lib_refuses_to_build_dump_names_from_non_canonical_timestamps(malformed_timestamp: str) -> None:
    result = _run_lib_shell(f"b2_backup_dump_object_name {shlex.quote(malformed_timestamp)}")

    assert result.returncode != 0, f"{malformed_timestamp!r} must be rejected, got stdout={result.stdout!r}"
    assert "non-canonical UTC timestamp" in result.stderr


def test_lib_parses_the_timestamp_back_out_of_a_dump_object_name() -> None:
    result = _run_lib_shell('b2_backup_dump_object_timestamp "db-20260816T023001Z.dump"')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "20260816T023001Z"


@pytest.mark.parametrize(
    "malformed_object_name",
    ["db-20260816T023001Z.dumpx", "db-20260816T023001Z", "backup-20260816T023001Z.dump", "db-.dump", "db-2026Z.dump"],
)
def test_lib_rejects_malformed_dump_object_names(malformed_object_name: str) -> None:
    result = _run_lib_shell(f"b2_backup_dump_object_timestamp {shlex.quote(malformed_object_name)}")

    assert result.returncode != 0, f"{malformed_object_name!r} must be rejected, got stdout={result.stdout!r}"
    assert "not a canonical backup dump object name" in result.stderr


def test_lib_resolves_bucket_from_env_with_documented_default() -> None:
    configured = _run_lib_shell("b2_backup_bucket")
    defaulted = _run_lib_shell("b2_backup_bucket", B2_BUCKET="")

    assert configured.returncode == 0, configured.stderr
    assert configured.stdout.strip() == TEST_BUCKET
    assert defaulted.stdout.strip() == "civibus-db-backups"


def test_lib_resolves_retention_window_from_env_with_documented_default() -> None:
    configured = _run_lib_shell("b2_backup_retention_days", BACKUP_RETENTION_DAYS="30")
    defaulted = _run_lib_shell("b2_backup_retention_days")
    zero_days = _run_lib_shell("b2_backup_retention_days", BACKUP_RETENTION_DAYS="0")
    non_numeric = _run_lib_shell("b2_backup_retention_days", BACKUP_RETENTION_DAYS="seven")
    zero_day_prune = _run_lib_shell(
        'rclone() { echo "unexpected rclone call"; }\nb2_backup_prune_fly_dumps',
        BACKUP_RETENTION_DAYS="0",
    )

    assert configured.returncode == 0, configured.stderr
    assert configured.stdout.strip() == "30"
    assert defaulted.returncode == 0, defaulted.stderr
    assert defaulted.stdout.strip() == "7"
    assert zero_days.returncode != 0
    assert "positive integer" in zero_days.stderr
    assert non_numeric.returncode != 0
    assert "positive integer" in non_numeric.stderr
    assert zero_day_prune.returncode != 0
    assert "unexpected rclone call" not in zero_day_prune.stdout


def test_lib_owns_the_fly_prefix_and_full_object_paths() -> None:
    prefix_result = _run_lib_shell("b2_backup_fly_prefix_path")
    object_result = _run_lib_shell('b2_backup_fly_dump_path "20260816T023001Z"')

    assert prefix_result.stdout.strip() == FLY_PREFIX_PATH
    assert object_result.stdout.strip() == f"{FLY_PREFIX_PATH}db-20260816T023001Z.dump"


def test_lib_configures_rclone_from_env_and_requires_b2_credentials() -> None:
    configured = _run_lib_shell(
        "b2_backup_configure_rclone_env\n"
        'printf "%s|%s|%s\\n" "${RCLONE_CONFIG_B2_TYPE}" "${RCLONE_CONFIG_B2_ACCOUNT}" "${RCLONE_CONFIG_B2_KEY}"',
        B2_ACCOUNT_ID="account-id",
        B2_APPLICATION_KEY="application-key",
    )
    missing_key = _run_lib_shell("b2_backup_configure_rclone_env", B2_ACCOUNT_ID="account-id")

    assert configured.returncode == 0, configured.stderr
    assert configured.stdout.strip() == "b2|account-id|application-key"
    assert missing_key.returncode != 0
    assert "B2_APPLICATION_KEY" in missing_key.stderr


def test_object_contract_literals_are_defined_only_in_the_shared_lib() -> None:
    """Bucket, prefix, filename shape, and prune verb live in exactly one file."""
    lib_text = LIB_PATH.read_text(encoding="utf-8")
    assert FLY_PREFIX in lib_text
    assert "civibus-db-backups" in lib_text
    assert "rclone delete" in lib_text

    for consumer_path in (HETZNER_WRAPPER_PATH, FLY_WRAPPER_PATH, CHECKER_PATH):
        consumer_text = consumer_path.read_text(encoding="utf-8")
        assert 'source "${script_dir}/b2_backup_lib.sh"' in consumer_text, f"{consumer_path} must source the shared lib"
        for owned_literal in ("fly/civibus-db", "civibus-db-backups", ".dump", "%Y%m%dT%H%M%SZ", "rclone delete"):
            assert owned_literal not in consumer_text, (
                f"{consumer_path.name} must read {owned_literal!r} from b2_backup_lib.sh instead of hardcoding it"
            )


# ---------- parked Hetzner wrapper contract ----------


def test_installer_still_invokes_the_hetzner_wrapper_at_its_published_path() -> None:
    installer_text = INSTALLER_PATH.read_text(encoding="utf-8")

    assert HETZNER_WRAPPER_PATH.is_file()
    assert 'backup_wrapper="${repo_root}/infra/scripts/backup_to_b2.sh"' in installer_text
    assert "30 2 * * * bash ${backup_wrapper} >> /var/log/civibus/backup.log 2>&1" in installer_text

    # The 02:30 UTC backup entry is retained executable, but must be labeled as
    # the parked historical Hetzner path, superseded by the civibus-db-backup
    # Fly backup Machine, so no reader mistakes it for the current backup path.
    lines = installer_text.splitlines()
    backup_line_idx = next(i for i, line in enumerate(lines) if "30 2 * * * bash ${backup_wrapper}" in line)
    marker_block = "\n".join(lines[max(0, backup_line_idx - 3) : backup_line_idx])
    assert "Parked historical Hetzner backup path" in marker_block, (
        "the parked-path marker must sit immediately beside the backup cron entry"
    )
    assert "civibus-db-backup" in marker_block, "the marker must name the Fly backup Machine that supersedes this entry"
    assert "superseded" in marker_block


def test_current_backup_runbook_does_not_redeclare_dump_filename_grammar() -> None:
    runbook_text = BACKUP_RUNBOOK_PATH.read_text(encoding="utf-8")
    current_guidance, parked_heading, _ = runbook_text.partition("## Parked historical Hetzner path")

    assert parked_heading, "the legacy procedure must remain isolated behind the parked-history heading"
    assert re.search(r"db-<[^>]+>[.]dump", current_guidance) is None, (
        "current Fly guidance must resolve selected dump names through b2_backup_lib.sh"
    )


def test_hetzner_wrapper_keeps_container_dump_flags_and_root_prefix_object(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, HETZNER_WRAPPER_PATH, DB_CONTAINER="infra-db-1")

    assert run.completed.returncode == 0, run.output
    dump_calls = [call for call in run.calls_for("docker") if "pg_dump" in call.argv]
    assert len(dump_calls) == 1, f"expected exactly one containerised pg_dump, got {run.calls}"
    dump_argv = dump_calls[0].argv
    assert dump_argv[:2] == ["exec", "-e"]
    assert dump_argv[2].startswith("PGPASSFILE=")
    assert "infra-db-1" in dump_argv
    for flag in CUSTOM_FORMAT_DUMP_FLAGS:
        assert flag in dump_argv, f"{flag} must survive the lib refactor: {dump_argv}"

    upload_calls = run.rclone_calls("rcat")
    assert len(upload_calls) == 1, f"expected exactly one streamed upload, got {run.calls}"
    remote_path = upload_calls[0].argv[1]
    bucket_root, _, object_name = remote_path.rpartition("/")
    assert f"{bucket_root}/" == BUCKET_ROOT_PATH, f"Hetzner dumps stay at the bucket root: {remote_path}"
    assert DUMP_OBJECT_NAME_REGEX.match(object_name), remote_path


def test_hetzner_wrapper_prunes_only_root_level_dump_objects(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, HETZNER_WRAPPER_PATH, BACKUP_RETENTION_DAYS="9")

    assert run.completed.returncode == 0, run.output
    prune_calls = run.rclone_calls("delete")
    assert len(prune_calls) == 1, f"expected exactly one prune, got {run.calls}"
    assert prune_calls[0].argv == [
        "delete",
        "--min-age",
        "9d",
        "--include",
        "/db-*.dump",
        BUCKET_ROOT_PATH,
    ]


def test_hetzner_wrapper_never_exposes_password_material_in_argv(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, HETZNER_WRAPPER_PATH)

    assert run.completed.returncode == 0, run.output
    _assert_no_password_exposure(run)


# ---------- live Fly wrapper contract ----------


def test_fly_wrapper_streams_dump_to_the_canonical_prefixed_object(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH)

    assert run.completed.returncode == 0, run.output
    upload_calls = run.rclone_calls("rcat")
    assert len(upload_calls) == 1, f"expected exactly one streamed upload, got {run.calls}"
    remote_path = upload_calls[0].argv[1]
    assert remote_path.startswith(FLY_PREFIX_PATH), remote_path
    assert DUMP_OBJECT_NAME_REGEX.match(remote_path[len(FLY_PREFIX_PATH) :]), remote_path


def test_fly_wrapper_prune_is_scoped_to_the_fly_prefix_not_the_bucket_root(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH, BACKUP_RETENTION_DAYS="7")

    assert run.completed.returncode == 0, run.output
    prune_calls = run.rclone_calls("delete")
    assert len(prune_calls) == 1, f"expected exactly one prune, got {run.calls}"
    prune_target = prune_calls[0].argv[-1]
    assert prune_target == FLY_PREFIX_PATH, prune_target
    assert prune_target != BUCKET_ROOT_PATH, "Fly prune must never resolve to the bucket root"
    assert prune_calls[0].argv == ["delete", "--min-age", "7d", FLY_PREFIX_PATH]


def test_fly_wrapper_dumps_the_live_fly_database_coordinates(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH)

    assert run.completed.returncode == 0, run.output
    dump_calls = [call for call in run.calls_for("pg_dump") if "--version" not in call.argv]
    assert len(dump_calls) == 1, f"expected exactly one dump, got {run.calls}"
    dump_call = dump_calls[0]
    assert dump_call.flag_value("--host") == "civibus-db.internal"
    assert dump_call.flag_value("--port") == "5432"
    assert dump_call.flag_value("--username") == "civibus_backup"
    assert dump_call.flag_value("--dbname") == "civibus"
    for flag in CUSTOM_FORMAT_DUMP_FLAGS:
        assert flag in dump_call.argv, f"{flag} missing from Fly dump argv: {dump_call.argv}"


def test_fly_wrapper_never_spools_the_dump_to_a_local_file(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH)

    assert run.completed.returncode == 0, run.output
    dump_calls = [call for call in run.calls_for("pg_dump") if "--version" not in call.argv]
    assert not any(argument in {"-f", "--file"} or argument.startswith("--file=") for argument in dump_calls[0].argv)
    assert not run.rclone_calls("copy")
    assert not run.rclone_calls("copyto")
    assert not run.rclone_calls("moveto")


def test_fly_wrapper_authenticates_via_private_pgpassfile_without_password_env(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH)
    backup_dockerfile = (REPO_ROOT / "infra/db/backup.Dockerfile").read_text(encoding="utf-8")

    assert run.completed.returncode == 0, run.output
    assert "\nUSER postgres:postgres\n" in backup_dockerfile, (
        "the credential-bearing Fly backup process must not run as container root"
    )
    _assert_no_password_exposure(run)

    libpq_calls = run.calls_for("pg_dump") + run.calls_for("psql")
    assert libpq_calls, "expected the Fly wrapper to invoke libpq clients"
    for call in libpq_calls:
        assert "RCLONE_CONFIG_B2_ACCOUNT" not in call.env, f"{call.tool} inherited the B2 account id"
        assert "RCLONE_CONFIG_B2_KEY" not in call.env, f"{call.tool} inherited the B2 application key"
        assert "PGPASSWORD" not in call.env, f"{call.tool} must not inherit PGPASSWORD: {sorted(call.env)}"
        assert "POSTGRES_PASSWORD" not in call.env, f"{call.tool} must not inherit POSTGRES_PASSWORD"
        assert TEST_DB_PASSWORD not in call.env.values(), f"{call.tool} inherited password material"
        assert call.env.get("PGPASSFILE"), f"{call.tool} must authenticate through PGPASSFILE"
        assert call.pgpassfile_mode == "600", f"PGPASSFILE must be mode 0600, got {call.pgpassfile_mode}"
        assert call.pgpassfile_content == (f"civibus-db.internal:5432:civibus:civibus_backup:{TEST_DB_PASSWORD}\n"), (
            call.pgpassfile_content
        )


def test_fly_wrapper_escapes_pgpass_separator_characters(tmp_path: Path) -> None:
    special_password = r"colon:and\backslash"
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH, FLY_BACKUP_DB_PASSWORD=special_password)

    assert run.completed.returncode == 0, run.output
    _assert_sensitive_value_not_exposed(run, special_password)
    libpq_calls = run.calls_for("pg_dump") + run.calls_for("psql")
    assert libpq_calls, "expected the Fly wrapper to invoke libpq clients"
    for call in libpq_calls:
        assert special_password not in call.env.values(), f"{call.tool} inherited password material"
        assert call.pgpassfile_content == ("civibus-db.internal:5432:civibus:civibus_backup:colon\\:and\\\\backslash\n")


def test_fly_wrapper_removes_its_temporary_pgpass_file_on_exit(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH)

    assert run.completed.returncode == 0, run.output
    pgpass_paths = {call.env["PGPASSFILE"] for call in run.calls if "PGPASSFILE" in call.env}
    assert len(pgpass_paths) == 1, f"expected one temporary pgpass file, got {pgpass_paths}"
    assert not Path(next(iter(pgpass_paths))).exists(), "temporary pgpass file must be removed on exit"


def test_fly_wrapper_accepts_a_packaged_client_version_string(tmp_path: Path) -> None:
    run = _run_backup_script(
        tmp_path,
        FLY_WRAPPER_PATH,
        STUB_PG_DUMP_VERSION="18.2 (Debian 18.2-1.pgdg120+1)",
    )

    assert run.completed.returncode == 0, run.output
    assert len(run.rclone_calls("rcat")) == 1


def test_fly_wrapper_refuses_to_upload_a_version_mismatched_dump(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH, STUB_PG_DUMP_VERSION="17.5")

    assert run.completed.returncode != 0, run.output
    assert "major version 17" in run.output and "18" in run.output
    assert not run.rclone_calls("rcat"), "a version-mismatched dump must never be uploaded"
    assert not run.rclone_calls("delete"), "a failed backup must never prune existing dumps"


@pytest.mark.parametrize("server_version_output", ["", "not-a-version", "SHOW"])
def test_fly_wrapper_refuses_an_indeterminate_server_version(tmp_path: Path, server_version_output: str) -> None:
    """Indeterminate evidence must fail closed rather than read as a match."""
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH, STUB_SERVER_VERSION_OUTPUT=server_version_output)

    assert run.completed.returncode != 0, run.output
    assert not run.rclone_calls("rcat")


def test_fly_wrapper_requires_a_database_password(tmp_path: Path) -> None:
    run = _run_backup_script(
        tmp_path,
        FLY_WRAPPER_PATH,
        write_env_file=False,
        FLY_BACKUP_DB_PASSWORD="",
        POSTGRES_PASSWORD="owner-password-is-not-a-backup-credential",
    )

    assert run.completed.returncode != 0, run.output
    assert "FLY_BACKUP_DB_PASSWORD" in run.output
    assert not run.rclone_calls("rcat")


def test_fly_wrapper_propagates_upload_failure(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH, STUB_RCLONE_EXIT="7")

    assert run.completed.returncode != 0, run.output
    assert not run.rclone_calls("delete"), "a failed upload must never prune existing dumps"


def test_fly_wrapper_removes_partial_remote_object_when_pg_dump_fails(tmp_path: Path) -> None:
    run = _run_backup_script(tmp_path, FLY_WRAPPER_PATH, STUB_PG_DUMP_EXIT="23")

    assert run.completed.returncode != 0, run.output
    upload_calls = run.rclone_calls("rcat")
    assert len(upload_calls) == 1, f"the partial payload must reach the upload stream: {run.calls}"
    remote_path = upload_calls[0].argv[1]
    cleanup_calls = run.rclone_calls("deletefile")
    assert len(cleanup_calls) == 1, f"expected exact-object cleanup after the failed dump: {run.calls}"
    assert cleanup_calls[0].argv == ["deletefile", remote_path]
    assert not run.rclone_calls("delete"), "a failed dump must never prune existing backups"


# ---------- Fly backup freshness checker contract ----------

# A fixed, injected reference clock makes every age assertion hand-calculable.
FRESHNESS_CLOCK = datetime(2026, 8, 16, 2, 0, 0, tzinfo=timezone.utc)
FRESHNESS_CLOCK_EPOCH = int(FRESHNESS_CLOCK.timestamp())
CANONICAL_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# A B2 modification time recent enough to mask a stale filename if the checker
# ever (wrongly) trusted mtime over the canonical filename timestamp.
RECENT_B2_MTIME = FRESHNESS_CLOCK.strftime("%Y-%m-%d %H:%M:%S")


def _dump_name_aged_hours(hours: float) -> str:
    """Canonical dump object name for a dump taken `hours` before the clock."""
    stamp = (FRESHNESS_CLOCK - timedelta(hours=hours)).strftime(CANONICAL_TIMESTAMP_FORMAT)
    return f"db-{stamp}.dump"


def _lsf_row(name: str, *, mtime: str = RECENT_B2_MTIME) -> str:
    """One `rclone lsf --format tp` row: modtime and path joined by ';'."""
    return f"{mtime};{name}"


def _run_freshness_checker(
    tmp_path: Path,
    *,
    max_age_hours: object,
    rows: tuple[str, ...],
    clock_epoch: object = FRESHNESS_CLOCK_EPOCH,
    **env_overrides: str,
) -> ScriptRun:
    return _run_backup_script(
        tmp_path,
        CHECKER_PATH,
        script_args=("--max-age-hours", str(max_age_hours)),
        STUB_RCLONE_LSF_OUTPUT="".join(f"{row}\n" for row in rows),
        CIVIBUS_BACKUP_CLOCK_EPOCH=str(clock_epoch),
        **env_overrides,
    )


def _lsf_calls(run: ScriptRun) -> list[StubCall]:
    return run.rclone_calls("lsf")


def test_checker_passes_when_the_newest_dump_is_within_max_age(tmp_path: Path) -> None:
    newest = _dump_name_aged_hours(6)
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(_dump_name_aged_hours(30)), _lsf_row(newest)),
    )

    assert run.completed.returncode == 0, run.output
    assert newest in run.output, run.output
    assert "6h old" in run.output, "success evidence must name the age from the filename timestamp"


def test_checker_selects_the_newest_object_by_filename_timestamp(tmp_path: Path) -> None:
    """Freshness is decided by the newest dump, regardless of listing order."""
    newest = _dump_name_aged_hours(6)
    stale = _dump_name_aged_hours(200)
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(newest), _lsf_row(stale)),
    )

    assert run.completed.returncode == 0, run.output
    assert newest in run.output and "6h old" in run.output, run.output


def test_checker_fails_when_the_newest_dump_is_older_than_max_age(tmp_path: Path) -> None:
    stale = _dump_name_aged_hours(96)
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(_lsf_row(stale),))

    assert run.completed.returncode != 0, run.output
    assert "STALE" in run.output, run.output
    assert stale in run.output and "96h old" in run.output, "stale evidence must name the object and its age"


def test_checker_fails_closed_when_the_newest_dump_is_future_dated(tmp_path: Path) -> None:
    future = "db-20260816T030000Z.dump"
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(_lsf_row(future),))

    assert run.completed.returncode != 0, run.output
    assert future in run.output and "future" in run.output, "future-dated evidence must fail closed explicitly"


def test_checker_rejects_a_calendar_invalid_dump_timestamp(tmp_path: Path) -> None:
    invalid = "db-20260815T250000Z.dump"
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(_lsf_row(invalid),))

    assert run.completed.returncode != 0, run.output
    assert invalid in run.output and "not a canonical" in run.output, "invalid calendar fields must not be normalized"


def test_checker_ignores_a_newer_b2_mtime_on_a_stale_filename(tmp_path: Path) -> None:
    """A refreshed object mtime must never make an older dump read as fresh."""
    stale = _dump_name_aged_hours(96)
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(stale, mtime=RECENT_B2_MTIME),),
    )

    assert run.completed.returncode != 0, run.output
    assert "STALE" in run.output and "96h old" in run.output, "age must come from the filename, not the B2 mtime"


def test_checker_lists_only_the_fly_prefix_never_the_bucket_root(tmp_path: Path) -> None:
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(_dump_name_aged_hours(1)),),
    )

    assert run.completed.returncode == 0, run.output
    lsf_calls = _lsf_calls(run)
    assert len(lsf_calls) == 1, f"expected exactly one prefix listing, got {run.calls}"
    argv = lsf_calls[0].argv
    assert argv[-1] == FLY_PREFIX_PATH, f"checker must list the Fly prefix, got {argv}"
    assert argv[-1] != BUCKET_ROOT_PATH, "checker must never list the bucket root"


def test_checker_fails_closed_on_an_empty_prefix(tmp_path: Path) -> None:
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=())

    assert run.completed.returncode != 0, run.output
    assert "no backup objects" in run.output, "an empty prefix must fail closed, not read as fresh"


def test_checker_fails_closed_on_a_non_dump_object_under_the_prefix(tmp_path: Path) -> None:
    stray = "manifest.json"
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(_lsf_row(stray),))

    assert run.completed.returncode != 0, run.output
    assert stray in run.output and "not a canonical" in run.output, "a non-dump object must fail closed"


def test_checker_fails_closed_on_a_malformed_dump_name(tmp_path: Path) -> None:
    malformed = "db-not-a-timestamp.dump"
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(_lsf_row(malformed),))

    assert run.completed.returncode != 0, run.output
    assert malformed in run.output and "not a canonical" in run.output, "a malformed name must fail closed"


def test_checker_preserves_unescaped_separators_inside_object_names(tmp_path: Path) -> None:
    separator_name = "unexpected;db-20260816T010000Z.dump"
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(_lsf_row(separator_name),))

    assert run.completed.returncode != 0, run.output
    assert separator_name in run.output and "not a canonical" in run.output, (
        "the complete path field must be validated instead of its canonical-looking suffix"
    )


def test_checker_fails_closed_when_a_listing_row_has_no_separator(tmp_path: Path) -> None:
    delimiterless_row = "db-20260816T010000Z.dump"
    run = _run_freshness_checker(tmp_path, max_age_hours=48, rows=(delimiterless_row,))

    assert run.completed.returncode != 0, run.output
    assert delimiterless_row in run.output and "separator" in run.output, (
        "a delimiterless listing row must fail closed before its filename can be treated as canonical"
    )


def test_checker_fails_closed_when_rclone_errors(tmp_path: Path) -> None:
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(_dump_name_aged_hours(1)),),
        STUB_RCLONE_EXIT="7",
    )

    assert run.completed.returncode != 0, run.output
    assert "could not list" in run.output, "an rclone failure must fail closed"


def test_checker_parses_leading_zero_max_age_hours_as_decimal(tmp_path: Path) -> None:
    newest = _dump_name_aged_hours(6)
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours="08",
        rows=(_lsf_row(newest),),
    )

    assert run.completed.returncode == 0, run.output
    assert newest in run.output and "threshold 8h" in run.output, run.output
    assert _lsf_calls(run), "a valid positive integer spelling must reach the B2 prefix listing"


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        ((), "required"),
        (("--max-age-hours",), "requires a value"),
        (("--max-age-hours", "abc"), "positive integer"),
        (("--max-age-hours", "0"), "positive integer"),
        (("--max-age-hours", "-5"), "positive integer"),
        (("--max-age-hours", "3.5"), "positive integer"),
    ],
)
def test_checker_rejects_bad_max_age_hours(tmp_path: Path, args: tuple[str, ...], expected_message: str) -> None:
    run = _run_backup_script(
        tmp_path,
        CHECKER_PATH,
        script_args=args,
        STUB_RCLONE_LSF_OUTPUT=f"{_lsf_row(_dump_name_aged_hours(1))}\n",
        CIVIBUS_BACKUP_CLOCK_EPOCH=str(FRESHNESS_CLOCK_EPOCH),
    )

    assert run.completed.returncode != 0, run.output
    assert expected_message in run.output, run.output
    assert not _lsf_calls(run), "a bad --max-age-hours must fail before any B2 listing"


def test_checker_never_exposes_the_b2_application_key(tmp_path: Path) -> None:
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(_dump_name_aged_hours(1)),),
    )

    assert run.completed.returncode == 0, run.output
    _assert_sensitive_value_not_exposed(run, TEST_B2_APPLICATION_KEY)


def test_checker_only_reads_from_b2_and_never_mutates_it(tmp_path: Path) -> None:
    """The freshness gate must not upload, prune, or delete any B2 object."""
    run = _run_freshness_checker(
        tmp_path,
        max_age_hours=48,
        rows=(_lsf_row(_dump_name_aged_hours(6)), _lsf_row(_dump_name_aged_hours(96))),
    )

    assert run.completed.returncode == 0, run.output
    assert _lsf_calls(run), "checker must list the prefix"
    for mutating_subcommand in ("rcat", "delete", "deletefile", "copy", "copyto", "moveto"):
        assert not run.rclone_calls(mutating_subcommand), f"checker must never call rclone {mutating_subcommand}"
