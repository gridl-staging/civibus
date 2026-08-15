from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import time
import types
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

from _pytest.capture import CaptureManager


_REEXEC_SENTINEL_ENV_VAR = "CIVIBUS_PYTEST_REEXEC"


def _finish_bootstrap_parent(completed_process: subprocess.CompletedProcess[bytes]) -> None:
    # Initial conftest loading runs inside pytest's global capture. Finish that
    # capture explicitly so the child report reaches the original output FDs.
    capture_managers = [candidate for candidate in gc.get_objects() if isinstance(candidate, CaptureManager)]
    if len(capture_managers) != 1:
        raise RuntimeError(f"Expected one active pytest capture manager, found {len(capture_managers)}")

    capture_managers[0].stop_global_capturing()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(completed_process.returncode)


def _run_pytest_under_project_python_and_exit_if_needed() -> None:
    """Run under uv-managed Python 3.12+ if the current interpreter is older."""
    if sys.version_info >= (3, 12):
        return
    if os.environ.get(_REEXEC_SENTINEL_ENV_VAR) == "1":
        return

    os.environ[_REEXEC_SENTINEL_ENV_VAR] = "1"
    reexec_command = [
        "uv",
        "run",
        "--extra",
        "dev",
        "--extra",
        "entity-resolution",
        "pytest",
        *sys.argv[1:],
    ]
    completed_process = subprocess.run(reexec_command, check=False)
    _finish_bootstrap_parent(completed_process)


_run_pytest_under_project_python_and_exit_if_needed()

# These imports must remain below the dependency-free interpreter bootstrap.
# LiteralString requires Python 3.11+, and everything above the bootstrap must
# still import under the old system interpreter that triggers the re-exec.
from typing import LiteralString  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator  # noqa: E402

if TYPE_CHECKING:
    pass

_POSTGRES_UNAVAILABLE_PREFIX = "Unable to connect to PostgreSQL at "
_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS = 10
_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS = 1.0
_postgres_unavailable_error_message: str | None = None
_STAGE1_BOOTSTRAP_DRIFT_PREFIX = "Stage 1 bootstrap contract drift detected. Missing canaries: "
_CONTEST_RESULT_CANARY_PREFIX = "civic.contest_result."
_REPO_ROOT = Path(__file__).resolve().parent
_CIVICS_SCHEMA_PATH = _REPO_ROOT / "domains" / "civics" / "schema" / "tables.sql"
_CIVICS_CANDIDACY_MIGRATION_PATH = (
    _REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_30_candidacy_mvp_columns.sql"
)
_ENTITY_RESOLUTION_SCHEMA_PATH = _REPO_ROOT / "core" / "schema" / "entity_resolution.sql"
_PERSON_BIO_MIGRATION_PATH = _REPO_ROOT / "core" / "schema" / "migrations" / "2026_04_30_person_bio_fields.sql"
_COMMITTEE_SUMMARY_DERIVED_MIGRATION_PATH = (
    _REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_12_committee_summary_derived_aggregates.sql"
)
_DONOR_ROLLUP_MIGRATION_PATH = _REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_01_donor_search_rollup.sql"
# Applied after the base rollup migration: each one alters or extends the relation
# that migration creates, so the repair order here mirrors the migration filenames.
_DONOR_ROLLUP_REPRESENTATIVE_ID_MIGRATION_PATH = (
    _REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_02_donor_search_rollup_representative_id.sql"
)
_DONOR_ROLLUP_IDENTITY_VARIANT_MIGRATION_PATH = (
    _REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_03_donor_search_rollup_identity_variants.sql"
)
_ENTITY_SOURCE_CIVIC_TYPES_MIGRATION_PATH = (
    _REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_13_entity_source_civic_types.sql"
)
_ER_VIEWS_SCHEMA_PATH = _REPO_ROOT / "core" / "schema" / "er_views.sql"
_CONTEST_SECTION_START = "-- Contest"
_CONTEST_SECTION_END = "-- Contest Result"
_CONTEST_RESULT_SECTION_START = "-- Contest Result"
_CONTEST_RESULT_SECTION_END = "-- Filing Deadline"
_CONTEST_RESULT_TRIGGER_START = "CREATE TRIGGER trg_contest_result_updated_at"
_CONTEST_RESULT_TRIGGER_END = "CREATE TRIGGER trg_election_updated_at"
_MATCH_DECISION_SECTION_START = "-- Match Decision"
_MATCH_DECISION_SECTION_END = "-- Entity Cluster"
_CONTEST_RESULT_CANARY_REPAIR_SQL = {
    "civic.uq_contest_result_canonical": """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'civic'
                  AND indexname = 'uq_contest_result_canonical'
            ) AND NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_contest_result_canonical'
            ) THEN
                EXECUTE 'DROP INDEX civic.uq_contest_result_canonical';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_contest_result_canonical'
            ) THEN
                ALTER TABLE civic.contest_result
                ADD CONSTRAINT uq_contest_result_canonical
                UNIQUE (contest_id, source_record_id, candidate_name);
            END IF;
        END $$;
    """,
    "civic.contest_result.candidate_name": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS candidate_name TEXT NOT NULL DEFAULT ''
    """,
    "civic.contest_result.party": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS party TEXT
    """,
    "civic.contest_result.votes": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS votes INTEGER NOT NULL DEFAULT 0 CHECK (votes >= 0)
    """,
    "civic.contest_result.vote_pct": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS vote_pct NUMERIC(6,2) CHECK (
            vote_pct IS NULL OR (vote_pct >= 0 AND vote_pct <= 100)
        )
    """,
    "civic.contest_result.is_certified": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS is_certified BOOLEAN NOT NULL DEFAULT FALSE
    """,
    "civic.trg_contest_result_updated_at": """
        DROP TRIGGER IF EXISTS trg_contest_result_updated_at ON civic.contest_result;
        CREATE TRIGGER trg_contest_result_updated_at
            BEFORE UPDATE ON civic.contest_result
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """,
}
_CANDIDACY_CANARY_KEYS = frozenset(
    {
        "civic.candidacy.name_on_ballot",
        "civic.candidacy.is_unexpired_term",
        "civic.candidacy.raw_fields",
        "civic.candidacy.committee_id",
        "civic.idx_candidacy_committee_id",
        "civic.idx_candidacy_name_on_ballot",
    }
)
_PERSON_BIO_CANARY_KEYS = frozenset(
    {
        "core.person.bio_text",
        "core.person.bio_source_url",
        "core.person.bio_license",
        "core.person.bio_pulled_at",
    }
)
_COMMITTEE_SUMMARY_DERIVED_CANARY_PREFIX = "cf.committee_summary."
_DONOR_ROLLUP_CANARY_KEYS = frozenset({"cf.donor_search_rollup", "cf.donor_search_rollup_provenance"})
_DONOR_ROLLUP_REPRESENTATIVE_ID_CANARY_KEYS = frozenset({"cf.donor_search_rollup.representative_transaction_id"})
_DONOR_ROLLUP_IDENTITY_VARIANT_CANARY_KEYS = frozenset({"cf.donor_search_rollup_identity_variant"})
_ENTITY_SOURCE_CIVIC_TYPES_CANARY_KEYS = frozenset(
    {
        "core.entity_source.entity_type.election",
        "core.field_provenance.entity_type.election",
    }
)
_GRAPH_CANARY = "ag_catalog.ag_graph.civibus"

_repo_root_path = str(_REPO_ROOT)
if _repo_root_path in sys.path:
    sys.path.remove(_repo_root_path)
sys.path.insert(0, _repo_root_path)

from tests.ci.public_mirror_contract import DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID  # noqa: E402

# Test sessions can inherit another repo's `scripts` package on PYTHONPATH.
_scripts_module = sys.modules.get("scripts")
_scripts_module_file = getattr(_scripts_module, "__file__", None)
if _scripts_module_file is not None and not Path(_scripts_module_file).resolve().is_relative_to(_REPO_ROOT):
    del sys.modules["scripts"]
if "scripts" not in sys.modules:
    _repo_scripts_module = types.ModuleType("scripts")
    _repo_scripts_module.__path__ = [str(_REPO_ROOT / "scripts")]  # type: ignore[attr-defined]
    sys.modules["scripts"] = _repo_scripts_module

# --- Parked-jurisdiction quarantine (federal-first v1, see PRIORITIES.md) ---
# State/city campaign-finance pipelines are FROZEN until post-v1, so their
# ~2,500 tests are excluded from default collection to keep `make test` and CI
# focused on active code. Only per-state/city SUBDIRECTORIES are ignored:
# shared helpers directly under jurisdictions/states/ (load_utils.py etc.) are
# live federal-ingest dependencies and their colocated tests must keep running.
# Escape hatch: CIVIBUS_INCLUDE_PARKED=1 (used by `make test-parked`).
# Contract-tested in tests/test_parked_suite_exclusion.py.
_PARKED_JURISDICTION_PARENTS = (
    _REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states",
    _REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "cities",
)
_DB_BACKED_QUARANTINE_PATH = _REPO_ROOT / "tests" / "ci" / "db_backed_quarantine.md"


def _parked_jurisdiction_child_dirs(
    parents: tuple[Path, ...] | None = None,
) -> tuple[Path, ...]:
    if parents is None:
        parents = _PARKED_JURISDICTION_PARENTS
    return tuple(child for parent in parents for child in sorted(parent.iterdir()) if child.is_dir())


if not os.environ.get("CIVIBUS_INCLUDE_PARKED"):
    collect_ignore = [str(child) for child in _parked_jurisdiction_child_dirs()]


class _DbBackedQuarantineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    reason: str
    owner: str

    @field_validator("node_id", "reason", "owner")
    @classmethod
    def _require_non_blank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("owner")
    @classmethod
    def _reject_frozen_roadmap_owner(cls, value: str) -> str:
        if "roadmap.md" in value.casefold():
            raise ValueError("must not reference ROADMAP.md")
        return value


def _load_db_backed_quarantine(
    quarantine_path: Path = _DB_BACKED_QUARANTINE_PATH,
) -> tuple[_DbBackedQuarantineEntry, ...]:
    """Load and validate exact node IDs from the canonical DB-backed quarantine."""
    entries: list[_DbBackedQuarantineEntry] = []
    node_id_lines: dict[str, int] = {}
    try:
        quarantine_lines = quarantine_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise pytest.UsageError(f"Unable to read DB-backed quarantine {quarantine_path}: {error}") from error

    for line_number, line in enumerate(quarantine_lines, start=1):
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        try:
            entry_data = json.loads(stripped_line)
            entry = _DbBackedQuarantineEntry.model_validate(entry_data)
        except (json.JSONDecodeError, ValidationError) as error:
            raise pytest.UsageError(
                f"Invalid DB-backed quarantine entry at {quarantine_path}:{line_number}: {error}"
            ) from error

        previous_line = node_id_lines.get(entry.node_id)
        if previous_line is not None:
            raise pytest.UsageError(
                f"Invalid DB-backed quarantine entry at {quarantine_path}:{line_number}: "
                f"duplicate node_id {entry.node_id!r} first declared on line {previous_line}"
            )
        node_id_lines[entry.node_id] = line_number
        entries.append(entry)
    return tuple(entries)


# The projected-public contract builds a full Debbie projection and runs the
# entire public selection inside it (~10 minutes, mostly silent). Its home is
# the named target `make test-projected-public-contract`; any directory-level
# selection must never pick it up implicitly. The Makefile's `-m` exclusion is
# not enough: Batman merge validation runs its own `pytest tests/` with only
# integration/e2e excluded, and on 2026-08-15 the silent inner run tripped the
# merge watchdog's 300s no-output ceiling and refused a green canary merge.
_PROJECTED_PUBLIC_CONTRACT_BASENAME = "test_debbie_projected_public_contract"


def _projected_public_contract_explicitly_named(config: pytest.Config) -> bool:
    """True only when the invocation names the contract file or node itself."""
    return any(_PROJECTED_PUBLIC_CONTRACT_BASENAME in str(argument) for argument in config.invocation_params.args)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark exact canonical quarantine matches before built-in marker deselection."""
    entries_by_node_id = {entry.node_id: entry for entry in _load_db_backed_quarantine()}
    for item in items:
        entry = entries_by_node_id.get(item.nodeid)
        if entry is not None:
            item.add_marker(pytest.mark.quarantined(reason=entry.reason, owner=entry.owner))
        dev_repo_entry = DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID.get(item.nodeid)
        if dev_repo_entry is not None:
            item.add_marker(
                pytest.mark.dev_repo_only(
                    private_asset=dev_repo_entry.private_asset,
                    owner=dev_repo_entry.owner,
                )
            )

    if not _projected_public_contract_explicitly_named(config):
        selected_items: list[pytest.Item] = []
        deselected_items: list[pytest.Item] = []
        for item in items:
            if item.get_closest_marker("projected_public_contract") is None:
                selected_items.append(item)
            else:
                deselected_items.append(item)
        if deselected_items:
            config.hook.pytest_deselected(items=deselected_items)
            items[:] = selected_items


# Module-level imports for patchability in tests/test_conftest_db_fixtures.py.
from core.db import build_connection_parameters, get_connection  # noqa: E402
from core.graph import age_post_connect, ensure_graph  # noqa: E402
from test_support.bootstrap_canaries import _collect_missing_stage1_canaries  # noqa: E402


# Process-env test defaults for the fail-closed api.main import (module-level
# `app = create_app()` demands API keys + rate-limit env). These lived in
# api/conftest.py, which only loads when api/ is collected — a scoped run like
# `pytest tests` (batman merge validation) crashed at import. The root conftest
# loads for every run, so it is the single owner; api/conftest.py re-reads the
# values it needs from the environment.
_TEST_ENV_DEFAULTS = {
    "CIVIBUS_API_KEYS": "test-suite-default-key",
    "CIVIBUS_RATE_LIMIT_REQUESTS": "100",
    "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS": "60",
}

for _env_var_name, _env_var_value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_env_var_name, _env_var_value)


def _require_postgres_password() -> None:
    """Default DB-backed tests to the standard local development password."""
    if not os.environ.get("POSTGRES_PASSWORD"):
        os.environ["POSTGRES_PASSWORD"] = "civibus_dev"


def _connect_with_startup_retries(*, post_connect=None) -> psycopg.Connection:
    """Connect under the canonical DB-backed-test policy: password default plus startup retries.

    Single owner of "can this database answer a DB-backed test?". Anything that
    decides whether to run DB-backed nodes — the pytest fixtures below and the
    `Makefile::test` merge-slice preflight — must route through here. A second
    implementation drifts, and a preflight that connects differently than the
    tests do makes the wrong shadow/run decision.
    """
    _require_postgres_password()

    last_connection_error: RuntimeError | None = None
    for attempt_index in range(_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS):
        try:
            return get_connection(post_connect=post_connect)
        except RuntimeError as error:
            if not str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
                raise
            last_connection_error = error
            if attempt_index == _DB_CONNECTION_STARTUP_RETRY_ATTEMPTS - 1:
                break
            time.sleep(_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS)

    assert last_connection_error is not None
    raise last_connection_error


def merge_db_slice_probe() -> None:
    """Preflight for the `Makefile::test` DB-backed merge slice.

    Prints the canonically resolved target (`core.db` resolves the host, which
    is not necessarily the Makefile's `DB_HOST`). Exit 1 is reserved for
    canonical database unavailability so the Makefile can shadow only that
    condition; unexpected probe/configuration failures exit 2 and remain fatal.
    Called as `python -c 'import conftest; conftest.merge_db_slice_probe()'`.
    """
    try:
        _require_postgres_password()
        connection_parameters = build_connection_parameters()
        print(f"DB_HOST={connection_parameters['host']} POSTGRES_PORT={connection_parameters['port']}")
        _connect_with_startup_retries().close()
    except Exception as error:
        if isinstance(error, RuntimeError) and str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
            raise SystemExit(1) from error
        print(f"Unexpected merge DB slice probe failure: {error}", file=sys.stderr)
        raise SystemExit(2) from error


def _connection_or_skip(*, post_connect=None) -> psycopg.Connection:
    """Try to connect with retries; skip or fail if PostgreSQL is unavailable."""
    global _postgres_unavailable_error_message
    if _postgres_unavailable_error_message is not None and os.environ.get("CIVIBUS_REQUIRE_DB") != "1":
        _skip_or_fail_for_postgres_unavailable(_postgres_unavailable_error_message)

    try:
        connection = _connect_with_startup_retries(post_connect=post_connect)
    except RuntimeError as error:
        if not str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
            raise
        _postgres_unavailable_error_message = str(error)
        _skip_or_fail_for_postgres_unavailable(_postgres_unavailable_error_message, cause=error)
        raise  # unreachable: _skip_or_fail_for_postgres_unavailable always raises

    _postgres_unavailable_error_message = None
    return connection


def _skip_or_fail_for_postgres_unavailable(message: str, *, cause: BaseException | None = None) -> None:
    if os.environ.get("CIVIBUS_REQUIRE_DB") == "1":
        if cause is not None:
            raise pytest.fail.Exception(message) from cause
        pytest.fail(message)
    pytest.skip(message)


def _schema_section_sql(*, schema_text: str, start_marker: str, end_marker: str) -> str:
    start_index = schema_text.find(start_marker)
    if start_index < 0:
        raise RuntimeError(f"Missing start marker in civics schema: {start_marker}")
    end_index = schema_text.find(end_marker, start_index)
    if end_index < 0:
        raise RuntimeError(f"Missing end marker in civics schema: {end_marker}")
    return schema_text[start_index:end_index].strip()


def _contest_result_bootstrap_sql() -> str:
    schema_text = _CIVICS_SCHEMA_PATH.read_text(encoding="utf-8")
    contest_section = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_CONTEST_SECTION_START,
        end_marker=_CONTEST_SECTION_END,
    )
    contest_result_section = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_CONTEST_RESULT_SECTION_START,
        end_marker=_CONTEST_RESULT_SECTION_END,
    )
    contest_result_trigger = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_CONTEST_RESULT_TRIGGER_START,
        end_marker=_CONTEST_RESULT_TRIGGER_END,
    )
    return "\n".join(
        [
            "CREATE SCHEMA IF NOT EXISTS core;",
            "CREATE TABLE IF NOT EXISTS core.source_record (id UUID PRIMARY KEY);",
            """
            CREATE OR REPLACE FUNCTION core.set_updated_at()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                NEW.updated_at := NOW();
                RETURN NEW;
            END;
            $$;
            """.strip(),
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'core'
                      AND t.typname = 'date_precision'
                ) THEN
                    CREATE TYPE core.date_precision AS ENUM ('day', 'month', 'quarter', 'year', 'approximate');
                END IF;
            END $$;
            """.strip(),
            "CREATE SCHEMA IF NOT EXISTS civic;",
            contest_section,
            contest_result_section,
            "DROP TRIGGER IF EXISTS trg_contest_result_updated_at ON civic.contest_result;",
            contest_result_trigger,
        ]
    )


def _match_decision_bootstrap_sql() -> str:
    """Build targeted SQL to repair only core.match_decision from canonical ER schema."""
    schema_text = _ENTITY_RESOLUTION_SCHEMA_PATH.read_text(encoding="utf-8")
    match_decision_section = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_MATCH_DECISION_SECTION_START,
        end_marker=_MATCH_DECISION_SECTION_END,
    )
    return "\n".join(
        [
            "CREATE SCHEMA IF NOT EXISTS core;",
            match_decision_section,
        ]
    )


def _bootstrap_missing_contest_result_from_canonical_schema(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('civic.contest_result') IS NOT NULL")
        existence_row = cursor.fetchone()
        # A SELECT of one scalar always yields exactly one row; None here means
        # the driver contract itself broke, which should fail loudly.
        assert existence_row is not None
        relation_exists = bool(existence_row[0])
        if not relation_exists:
            # Bootstrap SQL is assembled from repo-owned schema files, not user
            # input; the cast mirrors core/schema_sql_fallback.py's precedent.
            cursor.execute(cast(LiteralString, _contest_result_bootstrap_sql()))
            return

        cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'civic'
                      AND table_name = 'contest_result'
                      AND column_name = 'party'
                ),
                EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'uq_contest_result_canonical'
                ),
                EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'civic'
                      AND table_name = 'contest_result'
                      AND column_name = 'candidate_name_on_ballot'
                )
            """
        )
        shape_row = cursor.fetchone()
        assert shape_row is not None
        has_party_column, has_canonical_constraint, has_legacy_ballot_column = shape_row
        if has_party_column and has_canonical_constraint and not has_legacy_ballot_column:
            return

        cursor.execute("DROP TABLE IF EXISTS civic.contest_result CASCADE")
        cursor.execute(cast(LiteralString, _contest_result_bootstrap_sql()))


def _relation_exists(connection: psycopg.Connection, relation_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (relation_name,))
        row = cursor.fetchone()
    return bool(row and row[0])


def _type_exists(connection: psycopg.Connection, schema_name: str, type_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = %s
                  AND t.typname = %s
            )
            """,
            (schema_name, type_name),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _can_repair_officeholding_date_precision(connection: psycopg.Connection) -> bool:
    """Repair only when both target table and enum type already exist."""
    has_officeholding_table = _relation_exists(connection, "civic.officeholding")
    has_date_precision_type = _type_exists(connection, "core", "date_precision")
    return has_officeholding_table and has_date_precision_type


def _can_repair_candidate_committee_link_date_precision(connection: psycopg.Connection) -> bool:
    """Repair only when both target table and enum type already exist."""
    has_link_table = _relation_exists(connection, "cf.candidate_committee_link")
    has_date_precision_type = _type_exists(connection, "core", "date_precision")
    return has_link_table and has_date_precision_type


def _ensure_core_date_precision_type(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        _execute_stage1_canary_repair(
            connection,
            cursor,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'core'
                      AND t.typname = 'date_precision'
                ) THEN
                    EXECUTE 'CREATE TYPE core.date_precision AS ENUM (''day'', ''month'', ''quarter'', ''year'', ''approximate'')';
                END IF;
            END $$;
            """,
        )


def _execute_stage1_canary_repair(
    connection: psycopg.Connection,
    cursor: psycopg.Cursor,
    repair_sql: str,
) -> None:
    """Execute one canary repair and clear transaction state if savepoint cleanup fails."""
    try:
        cursor.execute("SAVEPOINT stage1_canary_repair")
        try:
            # Repair SQL comes from the repo-owned canary catalog, not user
            # input; the cast mirrors core/schema_sql_fallback.py's precedent.
            cursor.execute(cast(LiteralString, repair_sql))
        except psycopg.Error:
            cursor.execute("ROLLBACK TO SAVEPOINT stage1_canary_repair")
        finally:
            cursor.execute("RELEASE SAVEPOINT stage1_canary_repair")
    except psycopg.Error:
        connection.rollback()


def _bootstrap_missing_stage1_canaries(connection: psycopg.Connection, *, missing_canaries: list[str]) -> None:
    if _CANDIDACY_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection, cursor, _CIVICS_CANDIDACY_MIGRATION_PATH.read_text(encoding="utf-8")
            )
    if _PERSON_BIO_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(connection, cursor, _PERSON_BIO_MIGRATION_PATH.read_text(encoding="utf-8"))
    if any(canary.startswith(_COMMITTEE_SUMMARY_DERIVED_CANARY_PREFIX) for canary in missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _COMMITTEE_SUMMARY_DERIVED_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if _DONOR_ROLLUP_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _DONOR_ROLLUP_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if _DONOR_ROLLUP_REPRESENTATIVE_ID_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _DONOR_ROLLUP_REPRESENTATIVE_ID_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if _DONOR_ROLLUP_IDENTITY_VARIANT_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _DONOR_ROLLUP_IDENTITY_VARIANT_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if _ENTITY_SOURCE_CIVIC_TYPES_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _ENTITY_SOURCE_CIVIC_TYPES_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if "civic.officeholding.date_precision" in missing_canaries:
        _ensure_core_date_precision_type(connection)
    if _GRAPH_CANARY in missing_canaries:
        try:
            age_post_connect(connection)
            ensure_graph(connection)
        except psycopg.Error:
            connection.rollback()
    with connection.cursor() as cursor:
        for missing_canary in missing_canaries:
            if not (
                missing_canary.startswith(_CONTEST_RESULT_CANARY_PREFIX)
                or missing_canary == "civic.trg_contest_result_updated_at"
                or missing_canary == "civic.uq_contest_result_canonical"
            ):
                continue
            repair_sql = _CONTEST_RESULT_CANARY_REPAIR_SQL.get(missing_canary)
            if repair_sql:
                _execute_stage1_canary_repair(connection, cursor, repair_sql)
        if "civic.officeholding.date_precision" in missing_canaries and _can_repair_officeholding_date_precision(
            connection
        ):
            _execute_stage1_canary_repair(
                connection,
                cursor,
                """
                ALTER TABLE civic.officeholding
                ADD COLUMN IF NOT EXISTS date_precision core.date_precision NOT NULL DEFAULT 'day'
                """,
            )
        if (
            "cf.candidate_committee_link.date_precision" in missing_canaries
            and _can_repair_candidate_committee_link_date_precision(connection)
        ):
            _execute_stage1_canary_repair(
                connection,
                cursor,
                """
                ALTER TABLE cf.candidate_committee_link
                ADD COLUMN IF NOT EXISTS date_precision core.date_precision NOT NULL DEFAULT 'year'
                """,
            )
        if {"core.person_er_view", "core.organization_er_view"} & set(missing_canaries) and _relation_exists(
            connection, "core.person"
        ):
            _execute_stage1_canary_repair(connection, cursor, _ER_VIEWS_SCHEMA_PATH.read_text(encoding="utf-8"))
        if "core.match_decision" in missing_canaries and not _relation_exists(connection, "core.match_decision"):
            _execute_stage1_canary_repair(connection, cursor, _match_decision_bootstrap_sql())


def _fail_if_stage1_bootstrap_drift_detected(connection: psycopg.Connection) -> None:
    _bootstrap_missing_contest_result_from_canonical_schema(connection)
    connection.commit()
    missing_canaries = _collect_missing_stage1_canaries(connection)
    if missing_canaries:
        # Canary probes can leave the current transaction aborted when optional schema is missing.
        connection.rollback()
        _bootstrap_missing_stage1_canaries(connection, missing_canaries=missing_canaries)
        connection.commit()
        remaining_missing_canaries = _collect_missing_stage1_canaries(connection)
        if remaining_missing_canaries:
            connection.rollback()
            pytest.fail(_STAGE1_BOOTSTRAP_DRIFT_PREFIX + ", ".join(remaining_missing_canaries))


@pytest.fixture
def db_conn() -> Iterator[psycopg.Connection]:
    _require_postgres_password()
    connection = _connection_or_skip()
    try:
        _fail_if_stage1_bootstrap_drift_detected(connection)
        # Preflight SELECTs auto-open a transaction, so reset before explicit BEGIN.
        connection.rollback()
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.rollback()
    finally:
        connection.close()


@pytest.fixture
def graph_conn() -> Iterator[psycopg.Connection]:
    """Provide a graph-enabled DB connection with AGE bootstrap and drift preflight."""
    _require_postgres_password()
    connection = _connection_or_skip(post_connect=age_post_connect)
    try:
        _fail_if_stage1_bootstrap_drift_detected(connection)
        ensure_graph(connection)
        connection.commit()
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.rollback()
    finally:
        connection.close()


@pytest.fixture
def committing_db_conn() -> Iterator[psycopg.Connection]:
    """Provide a DB connection for integration tests that commit real work."""
    _require_postgres_password()
    connection = _connection_or_skip()
    try:
        _fail_if_stage1_bootstrap_drift_detected(connection)
        connection.rollback()
        yield connection
    finally:
        connection.close()
