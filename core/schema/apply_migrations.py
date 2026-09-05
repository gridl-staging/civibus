"""Ledger-based delta migration runner for initialized databases.

Fresh database initialization stays with Makefile DB_SQL_FILES and domain
tables.sql files. This module owns only delta application: adopting the
frozen baseline for already-initialized databases and then applying any
checked-in migrations not yet in the ledger.

The frozen baseline contains 2026_07_07_zcta_district.sql, which was
retro-edited after its original production execution to include the
boundary_year column that 2026_07_14_zcta_district_boundary_year.sql
later added via ALTER. Adoption seeds baseline entries into the ledger
without re-executing their SQL, so the retro-edited file is safely
recorded as "already applied" and only the 07_14 reconciliation runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from core.db import get_connection

BASELINE_PATH = Path(__file__).resolve().parent / "migrations_baseline.txt"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_REPO_ROOT = Path(__file__).resolve().parents[2]

_FILENAME_RE = re.compile(r"^[A-Za-z0-9_]+\.sql$")
_CONCURRENTLY_RE = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)
_AUTHORITY_PHASE_RE = re.compile(r"(?m)^-- civibus-phase: ([a-z0-9_.]+)\s*$")
_PRODUCTION_EXECUTION_ORIGIN_MIGRATION = "2026_08_27_refresh_run_execution_origin.sql"
_PRODUCTION_EXECUTION_ORIGIN_SHA256 = "aba8d3c17cd3c1f8d0e85ebdcf8d3b1a7e171b50c5415ad4589b962a0cf9d99f"
_PRODUCTION_MIGRATION_LOCK_NAME = "civibus:production-migration:refresh-run-execution-origin"
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION = "2026_08_28_authority_scoped_identity.sql"
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH = (
    _REPO_ROOT
    / "domains"
    / "campaign_finance"
    / "schema"
    / "migrations"
    / _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION
)
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SUPERSEDED_SHA256 = (
    "310cfcd3106c70039d947bdd20ba1cc001072d8bf96969390ad162edab9416ed"
)
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256 = "0f463ecd2877c35c2754867c3994aa135c89e006554baa58697e6ff20d4badc8"
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_LOCK_NAME = (
    "civibus:production-migration:authority-scoped-campaign-finance-identity"
)
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE = 10_000
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_DEPTH_LIMIT = 32
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_CLOSURE_LIMIT = 20_000
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT = "5min"
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT = "15min"
_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_CUTOVER_STATEMENT_TIMEOUT = "5min"
_AUTHORITY_SCOPED_IDENTITY_PROGRESS_RELATION = "core.authority_scoped_identity_migration_progress"
_AUTHORITY_SCOPED_IDENTITY_BACKFILL_PHASES = (
    "backfill.committee",
    "backfill.candidate",
    "backfill.filing",
    "backfill.transaction",
)
_AUTHORITY_SCOPED_IDENTITY_BACKFILL_SPECS = {
    "backfill.committee": (
        "cf.committee",
        "native_committee_id",
        "selected_row.fec_committee_id",
    ),
    "backfill.candidate": (
        "cf.candidate",
        "native_candidate_id",
        "selected_row.fec_candidate_id",
    ),
    "backfill.filing": (
        "cf.filing",
        "native_filing_id",
        "selected_row.filing_fec_id",
    ),
    "backfill.transaction": (
        "cf.transaction",
        "native_transaction_id",
        "COALESCE(NULLIF(btrim(source_record.source_record_key), ''), "
        "selected_row.sub_id::text, NULLIF(btrim(selected_row.transaction_identifier), ''), "
        "selected_row.id::text)",
    ),
}
_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_COLUMNS = {
    "backfill.filing": "amended_from_filing_id",
    "backfill.transaction": "amended_by_transaction_id",
}
_PRODUCTION_DATABASE_USER = "civibus"
_PRODUCTION_SERVER_PORT = 5432
_EXECUTION_ORIGIN_CONSTRAINT = (
    "CHECK ((execution_origin = ANY (ARRAY['scheduled'::text, 'operator_attended'::text, 'legacy_unknown'::text])))"
)
_REFRESH_RUN_BASE_COLUMNS = frozenset(
    {
        ("id", "uuid", True, "uuid_generate_v4()"),
        ("job_key", "text", True, None),
        ("domain", "text", True, None),
        ("jurisdiction", "text", True, None),
        ("data_source_names", "text[]", True, "'{}'::text[]"),
        ("pull_status", "text", True, None),
        ("started_at", "timestamp with time zone", True, None),
        ("completed_at", "timestamp with time zone", False, None),
        ("inserted_count", "integer", True, "0"),
        ("skipped_count", "integer", True, "0"),
        ("quarantined_count", "integer", True, "0"),
        ("superseded_count", "integer", True, "0"),
        ("error_count", "integer", True, "0"),
        ("metadata_updates", "integer", True, "0"),
        ("message", "text", True, None),
        ("error", "text", False, None),
        ("created_at", "timestamp with time zone", True, "now()"),
    }
)
_REFRESH_RUN_BASE_CONSTRAINTS = frozenset(
    {
        ("refresh_run_pkey", "p", True, "PRIMARY KEY (id)"),
        (
            "refresh_run_pull_status_check",
            "c",
            True,
            "CHECK ((pull_status = ANY (ARRAY['crashed'::text, 'empty'::text, 'degraded'::text, "
            "'failed'::text, 'success'::text, 'running'::text])))",
        ),
        (
            "refresh_run_running_completed_at_check",
            "c",
            True,
            "CHECK (((pull_status = 'running'::text) = (completed_at IS NULL)))",
        ),
    }
)
_MIGRATION_LEDGER_COLUMNS = frozenset(
    {
        ("filename", "text", True, None),
        ("applied_at", "timestamp with time zone", True, "now()"),
    }
)
_MIGRATION_LEDGER_CONSTRAINTS = frozenset({("schema_migrations_pkey", "p", True, "PRIMARY KEY (filename)")})


def _require_supported_constraint_catalog(
    rows: list[tuple[object, ...]],
    *,
    expected_constraints: frozenset[tuple[str, str, bool, str]],
    expected_not_null_columns: frozenset[str],
    relation: str,
) -> None:
    """Accept only the exact legacy or PostgreSQL 18 NOT NULL catalog form."""
    ordinary: list[tuple[str, str, bool, str]] = []
    not_null: list[tuple[bool, bool, str, tuple[str, ...], bool, int, bool]] = []
    for row in rows:
        (
            name,
            constraint_type,
            validated,
            enforced,
            definition,
            columns,
            is_local,
            inherited_count,
            no_inherit,
        ) = row
        normalized_columns = tuple(columns or ())
        if constraint_type == "n":
            not_null.append(
                (
                    bool(validated),
                    bool(enforced),
                    str(definition),
                    normalized_columns,
                    bool(is_local),
                    int(inherited_count),
                    bool(no_inherit),
                )
            )
        else:
            expected_no_inherit = constraint_type == "p"
            if not enforced or not is_local or inherited_count != 0 or bool(no_inherit) != expected_no_inherit:
                raise ValueError(f"canonical {relation} constraint shape mismatch")
            ordinary.append((str(name), str(constraint_type), bool(validated), str(definition)))

    if len(ordinary) != len(expected_constraints) or frozenset(ordinary) != expected_constraints:
        raise ValueError(f"canonical {relation} constraint shape mismatch")
    if not not_null:
        return

    expected_not_null = frozenset(
        (True, True, f"NOT NULL {column}", (column,), True, 0, False) for column in expected_not_null_columns
    )
    if len(not_null) != len(expected_not_null) or frozenset(not_null) != expected_not_null:
        raise ValueError(f"canonical {relation} constraint shape mismatch")


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the explicit production-target CLI without changing the zero-argument release command."""
    parser = argparse.ArgumentParser(description=__doc__)
    production_target = parser.add_mutually_exclusive_group()
    production_target.add_argument(
        "--production-execution-origin",
        choices=("preflight", "apply", "verify"),
        help="Operate only the production execution_origin migration contract",
    )
    production_target.add_argument(
        "--production-authority-scoped-identity",
        choices=("preflight", "apply", "verify"),
        help="Operate only the production authority-scoped campaign-finance identity migration contract",
    )
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-port", type=int)
    parser.add_argument("--expected-database")
    return parser


def _require_production_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    supplied_identity = (args.expected_host, args.expected_port, args.expected_database)
    production_mode = args.production_execution_origin or args.production_authority_scoped_identity
    if production_mode is None:
        if any(value is not None for value in supplied_identity):
            parser.error("expected database identity options require an explicit production migration mode")
        return
    if any(value in (None, "") for value in supplied_identity):
        parser.error("production migration mode requires --expected-host, --expected-port, and --expected-database")
    if args.production_authority_scoped_identity is not None:
        if args.expected_host != "127.0.0.1" or args.expected_database != "civibus":
            parser.error("authority-scoped identity production mode requires 127.0.0.1:<lane port>/civibus")
        if not 1024 <= args.expected_port <= 65535:
            parser.error("authority-scoped identity production mode requires a valid unprivileged lane port")


def _require_production_identity(
    conn,
    *,
    expected_host: str,
    expected_port: int,
    expected_database: str,
    expected_read_only: str,
) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, inet_server_port()")
        row = cur.fetchone()
        cur.execute("SHOW transaction_read_only")
        read_only = cur.fetchone()[0]
    actual_host = conn.info.host
    actual_port = int(conn.info.port)
    actual_database = row[0]
    if (actual_host, actual_port, actual_database) != (
        expected_host,
        expected_port,
        expected_database,
    ):
        raise ValueError(
            "database identity mismatch: "
            f"expected {expected_host}:{expected_port}/{expected_database}, "
            f"found {actual_host}:{actual_port}/{actual_database}"
        )
    if row[2] is None:
        raise ValueError("database server port is indeterminate")
    if row[1] != _PRODUCTION_DATABASE_USER or int(row[2]) != _PRODUCTION_SERVER_PORT:
        raise ValueError(
            "production database server identity mismatch: "
            f"expected user {_PRODUCTION_DATABASE_USER} on server port {_PRODUCTION_SERVER_PORT}, "
            f"found user {row[1]} on server port {row[2]}"
        )
    if read_only != expected_read_only:
        raise ValueError(f"production migration requires transaction_read_only={expected_read_only}")
    return {
        "database": actual_database,
        "host": actual_host,
        "port": actual_port,
        "server_port": int(row[2]),
        "transaction_read_only": read_only,
        "user": row[1],
    }


def _load_pinned_sql(
    *,
    target: Path,
    filename: str,
    expected_sha256: str,
    label: str,
    allow_concurrently: bool = False,
) -> str:
    if not target.is_file() or target.is_symlink():
        raise ValueError(f"required migration file is absent or unsafe: {filename}")
    payload = target.read_bytes()
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != expected_sha256:
        raise ValueError(f"{label} migration digest mismatch")
    sql = payload.decode("utf-8")
    if not allow_concurrently and _CONCURRENTLY_RE.search(sql):
        raise ValueError(f"{label} migration contains unsupported CONCURRENTLY")
    if re.search(
        r"(?im)^\s*(?:BEGIN\s*(?:;|TRANSACTION\b|WORK\b)|COMMIT\b|ROLLBACK\b)",
        sql,
    ):
        raise ValueError(f"{label} migration contains transaction control")
    return sql


def _load_pinned_execution_origin_sql() -> str:
    return _load_pinned_sql(
        target=MIGRATIONS_DIR / _PRODUCTION_EXECUTION_ORIGIN_MIGRATION,
        filename=_PRODUCTION_EXECUTION_ORIGIN_MIGRATION,
        expected_sha256=_PRODUCTION_EXECUTION_ORIGIN_SHA256,
        label="execution_origin",
    )


def _load_pinned_authority_scoped_identity_sql() -> str:
    return _load_pinned_sql(
        target=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH,
        filename=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,
        expected_sha256=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256,
        label="authority_scoped_identity",
        allow_concurrently=True,
    )


def _parse_authority_scoped_identity_phases(sql: str) -> dict[str, str]:
    matches = list(_AUTHORITY_PHASE_RE.finditer(sql))
    prefix = sql[: matches[0].start()] if matches else sql
    if not matches or any(line.strip() and not line.lstrip().startswith("--") for line in prefix.splitlines()):
        raise ValueError("authority-scoped identity migration phase preamble is invalid")
    phases: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        if name in phases:
            raise ValueError(f"duplicate authority-scoped identity phase: {name}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(sql)
        body = sql[match.end() : end].strip()
        if not body:
            raise ValueError(f"empty authority-scoped identity phase: {name}")
        phases[name] = body
    expected = {
        "prepare",
        "cutover",
        *_AUTHORITY_SCOPED_IDENTITY_BACKFILL_PHASES,
        *(f"index.{name}" for name in _AUTHORITY_SCOPED_INDEXES),
        *(f"validate.{name}" for _relation, name in _AUTHORITY_SCOPED_CONSTRAINT_DEFINITION_SHA256),
    }
    if set(phases) != expected:
        raise ValueError("authority-scoped identity phase manifest mismatch")
    return phases


def _require_production_migration_quiescence(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM core.refresh_run WHERE pull_status = 'running'")
        if cur.fetchone()[0] != 0:
            raise ValueError("running refresh attempts block the production migration")
        cur.execute(
            """
            SELECT COUNT(*)
            FROM pg_stat_activity
            WHERE pid <> pg_backend_pid()
              AND datname = current_database()
              AND state LIKE 'idle in transaction%'
              AND xact_start < now() - interval '30 minutes'
            """
        )
        if cur.fetchone()[0] != 0:
            raise ValueError("long-idle production transactions block the migration")


def _require_production_owner_shapes(conn, *, execution_origin_present: bool) -> None:
    expected_refresh_columns = _REFRESH_RUN_BASE_COLUMNS
    expected_refresh_constraints = _REFRESH_RUN_BASE_CONSTRAINTS
    if execution_origin_present:
        expected_refresh_columns |= {("execution_origin", "text", True, "'legacy_unknown'::text")}
        expected_refresh_constraints |= {
            ("refresh_run_execution_origin_check", "c", True, _EXECUTION_ORIGIN_CONSTRAINT)
        }

    with conn.cursor() as cur:
        for relation, expected_columns, expected_constraints in (
            ("core.refresh_run", expected_refresh_columns, expected_refresh_constraints),
            ("core.schema_migrations", _MIGRATION_LEDGER_COLUMNS, _MIGRATION_LEDGER_CONSTRAINTS),
        ):
            cur.execute(
                "SELECT relkind, pg_get_userbyid(relowner) FROM pg_class WHERE oid = %s::regclass",
                (relation,),
            )
            if cur.fetchone() != ("r", _PRODUCTION_DATABASE_USER):
                raise ValueError(f"canonical {relation} relation shape mismatch")
            cur.execute(
                """
                SELECT attributes.attname,
                       format_type(attributes.atttypid, attributes.atttypmod),
                       attributes.attnotnull,
                       pg_get_expr(defaults.adbin, defaults.adrelid)
                FROM pg_attribute attributes
                LEFT JOIN pg_attrdef defaults
                  ON defaults.adrelid = attributes.attrelid
                 AND defaults.adnum = attributes.attnum
                WHERE attributes.attrelid = %s::regclass
                  AND attributes.attnum > 0
                  AND NOT attributes.attisdropped
                """,
                (relation,),
            )
            if frozenset(cur.fetchall()) != expected_columns:
                raise ValueError(f"canonical {relation} column shape mismatch")
            cur.execute(
                """
                SELECT constraints.conname,
                       constraints.contype::text,
                       constraints.convalidated,
                       COALESCE((to_jsonb(constraints) ->> 'conenforced')::boolean, TRUE),
                       pg_get_constraintdef(constraints.oid),
                       ARRAY(
                           SELECT attributes.attname::text
                           FROM unnest(constraints.conkey) WITH ORDINALITY AS keys(attnum, position)
                           JOIN pg_attribute attributes
                             ON attributes.attrelid = constraints.conrelid
                            AND attributes.attnum = keys.attnum
                           ORDER BY keys.position
                       ),
                       constraints.conislocal,
                       constraints.coninhcount,
                       constraints.connoinherit
                FROM pg_constraint constraints
                WHERE constraints.conrelid = %s::regclass
                """,
                (relation,),
            )
            _require_supported_constraint_catalog(
                cur.fetchall(),
                expected_constraints=expected_constraints,
                expected_not_null_columns=frozenset(
                    column_name for column_name, _type, not_null, _default in expected_columns if not_null
                ),
                relation=relation,
            )


def _require_execution_origin_pending_absent(conn) -> None:
    migration_names = sorted(path.name for path in MIGRATIONS_DIR.iterdir() if path.suffix == ".sql")
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('core.schema_migrations'), to_regclass('core.refresh_run')")
        ledger_relation, refresh_relation = cur.fetchone()
        if ledger_relation is None:
            raise ValueError("core.schema_migrations is absent; production preflight will not create it")
        if refresh_relation is None:
            raise ValueError("core.refresh_run is absent")
        _require_production_owner_shapes(conn, execution_origin_present=False)

        cur.execute("SELECT filename FROM core.schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        pending = tuple(name for name in migration_names if name not in applied)
        if pending != (_PRODUCTION_EXECUTION_ORIGIN_MIGRATION,):
            raise ValueError(
                f"production execution_origin apply requires the exact singleton pending migration; found {pending!r}"
            )

        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'refresh_run'
              AND column_name = 'execution_origin'
            """
        )
        column_count = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*)
            FROM pg_constraint
            WHERE conrelid = 'core.refresh_run'::regclass
              AND conname = 'refresh_run_execution_origin_check'
            """
        )
        constraint_count = cur.fetchone()[0]
        if column_count != 0 or constraint_count != 0:
            raise ValueError("execution_origin schema exists without its migration ledger receipt")

        _require_production_migration_quiescence(conn)


def _require_execution_origin_applied_shape(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('core.schema_migrations'), to_regclass('core.refresh_run')")
        ledger_relation, refresh_relation = cur.fetchone()
        if ledger_relation is None or refresh_relation is None:
            raise ValueError("migration verification requires core.schema_migrations and core.refresh_run")
        _require_production_owner_shapes(conn, execution_origin_present=True)
        cur.execute(
            "SELECT COUNT(*) FROM core.schema_migrations WHERE filename = %s",
            (_PRODUCTION_EXECUTION_ORIGIN_MIGRATION,),
        )
        if cur.fetchone()[0] != 1:
            raise ValueError("execution_origin migration ledger receipt is absent")
        cur.execute(
            """
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'refresh_run'
              AND column_name = 'execution_origin'
            """
        )
        shape = cur.fetchone()
        if shape != ("text", "NO", "'legacy_unknown'::text"):
            raise ValueError(f"execution_origin column shape mismatch: {shape!r}")
        cur.execute(
            """
            SELECT pg_get_constraintdef(oid), convalidated
            FROM pg_constraint
            WHERE conrelid = 'core.refresh_run'::regclass
              AND conname = 'refresh_run_execution_origin_check'
              AND contype = 'c'
            """
        )
        constraint = cur.fetchall()
        if len(constraint) != 1 or constraint[0][1] is not True:
            raise ValueError("execution_origin check constraint is absent, duplicate, or unvalidated")
        definition = re.sub(r"\s+", " ", constraint[0][0]).strip()
        if definition != _EXECUTION_ORIGIN_CONSTRAINT:
            raise ValueError("execution_origin check constraint has the wrong closed value set")


def _run_production_execution_origin_operation(
    conn,
    *,
    operation: str,
    expected_host: str,
    expected_port: int,
    expected_database: str,
) -> dict[str, object]:
    identity = _require_production_identity(
        conn,
        expected_host=expected_host,
        expected_port=expected_port,
        expected_database=expected_database,
        expected_read_only="off" if operation == "apply" else "on",
    )
    sql = _load_pinned_execution_origin_sql()
    state = "pending_absent"
    if operation == "preflight":
        _require_execution_origin_pending_absent(conn)
    elif operation == "verify":
        _require_execution_origin_applied_shape(conn)
        state = "applied_verified"
    else:
        _require_execution_origin_pending_absent(conn)
        conn.rollback()
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute("SET LOCAL statement_timeout = '60s'")
            locked = conn.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                (_PRODUCTION_MIGRATION_LOCK_NAME,),
            ).fetchone()
            if not locked or not bool(locked[0]):
                raise ValueError("another production execution_origin migration owner holds the lock")
            _require_execution_origin_pending_absent(conn)
            conn.execute(sql)
            conn.execute(
                "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
                (_PRODUCTION_EXECUTION_ORIGIN_MIGRATION,),
            )
            _require_execution_origin_applied_shape(conn)
        state = "applied_verified"
    return {
        "database_identity": identity,
        "migration": _PRODUCTION_EXECUTION_ORIGIN_MIGRATION,
        "migration_sha256": _PRODUCTION_EXECUTION_ORIGIN_SHA256,
        "state": state,
    }


_AUTHORITY_SCOPED_COLUMNS = {
    "core.data_source": (
        ("filing_authority_type", "text", "YES", None),
        ("filing_authority_code", "text", "YES", None),
    ),
    "cf.committee": (
        ("data_source_id", "uuid", "YES", None),
        ("native_committee_id", "text", "YES", None),
    ),
    "cf.candidate": (
        ("data_source_id", "uuid", "YES", None),
        ("native_candidate_id", "text", "YES", None),
    ),
    "cf.filing": (
        ("data_source_id", "uuid", "YES", None),
        ("native_filing_id", "text", "YES", None),
    ),
    "cf.transaction": (
        ("data_source_id", "uuid", "YES", None),
        ("native_transaction_id", "text", "YES", None),
    ),
}
_AUTHORITY_SCOPED_INDEXES = {
    "idx_data_source_dedup": (
        "core.data_source",
        True,
        True,
        ("domain", "filing_authority_type", "filing_authority_code", "name"),
        None,
    ),
    "uq_committee_legacy_fec_id": (
        "cf.committee",
        True,
        False,
        ("fec_committee_id",),
        "(data_source_id IS NULL)",
    ),
    "uq_committee_authority_native_id": (
        "cf.committee",
        True,
        False,
        ("data_source_id", "native_committee_id"),
        "(data_source_id IS NOT NULL)",
    ),
    "uq_candidate_legacy_fec_id": (
        "cf.candidate",
        True,
        False,
        ("fec_candidate_id",),
        "(data_source_id IS NULL)",
    ),
    "uq_candidate_authority_native_id": (
        "cf.candidate",
        True,
        False,
        ("data_source_id", "native_candidate_id"),
        "(data_source_id IS NOT NULL)",
    ),
    "uq_filing_legacy_fec_id": (
        "cf.filing",
        True,
        False,
        ("filing_fec_id",),
        "(data_source_id IS NULL)",
    ),
    "uq_filing_authority_native_id": (
        "cf.filing",
        True,
        False,
        ("data_source_id", "native_filing_id"),
        "(data_source_id IS NOT NULL)",
    ),
    "uq_transaction_sub_id": (
        "cf.transaction",
        True,
        False,
        ("sub_id",),
        "((data_source_id IS NULL) AND (sub_id IS NOT NULL))",
    ),
    "uq_transaction_authority_native_id": (
        "cf.transaction",
        True,
        False,
        ("data_source_id", "native_transaction_id"),
        "(data_source_id IS NOT NULL)",
    ),
}
_AUTHORITY_SCOPED_TRIGGERS = {
    ("core.data_source", "trg_data_source_campaign_finance_filing_authority"): (
        23,
        "core.populate_campaign_finance_filing_authority",
        None,
    ),
    ("core.source_record", "trg_source_record_supersession_scope_insert"): (
        4,
        "core.enforce_source_record_supersession_scope",
        "new_rows",
    ),
    ("core.source_record", "trg_source_record_supersession_scope_update"): (
        16,
        "core.enforce_source_record_supersession_scope",
        "new_rows",
    ),
    **{
        (f"cf.{table}", f"trg_{table}_source_scope_{event}"): (
            4 if event == "insert" else 16,
            "cf.enforce_source_record_scope",
            "new_rows",
        )
        for table in ("committee", "candidate", "filing", "transaction")
        for event in ("insert", "update")
    },
    ("cf.filing", "trg_filing_amendment_scope_insert"): (
        4,
        "cf.enforce_filing_amendment_scope",
        "new_rows",
    ),
    ("cf.filing", "trg_filing_amendment_scope_update"): (
        16,
        "cf.enforce_filing_amendment_scope",
        "new_rows",
    ),
    ("cf.transaction", "trg_transaction_amendment_scope_insert"): (
        4,
        "cf.enforce_transaction_amendment_scope",
        "new_rows",
    ),
    ("cf.transaction", "trg_transaction_amendment_scope_update"): (
        16,
        "cf.enforce_transaction_amendment_scope",
        "new_rows",
    ),
}
_AUTHORITY_SCOPED_CONSTRAINT_DEFINITION_SHA256 = {
    ("cf.candidate", "ck_candidate_authority_native_pair"): (
        "abb64c5ecd3bce1fc9cb64e6fc46b10312392cd32b1238bcf68e0836ac0b58b9"
    ),
    ("cf.candidate", "ck_candidate_native_id_nonblank"): (
        "b52ab78caaf3ddfba8810a295a96a463d5badc1f0be5f881a3540eeae3ac3c62"
    ),
    ("cf.committee", "ck_committee_authority_native_pair"): (
        "93693b12a4bfb03279e72f46cca0bf1917aa93c23e74efa47c3f61c29840dbaa"
    ),
    ("cf.committee", "ck_committee_native_id_nonblank"): (
        "7eea9319fe88ddfa48d51a2f742b1282d4f046bc12e0e270ffe8caf167172134"
    ),
    ("cf.filing", "ck_filing_authority_native_pair"): (
        "9509aa8759b84531889ea5a693a18985b9c2d8bf2b68487a2d2320bdfa79af7e"
    ),
    ("cf.filing", "ck_filing_native_id_nonblank"): ("20b79664d658293b220c98ff2d03185f9537b3d593e315ada08ae71b0e8a777c"),
    ("cf.transaction", "ck_transaction_authority_native_pair"): (
        "12513ddfeadf2de875f07669942a0652a71f5bfcd3c23918b6a9fa189c41d2ad"
    ),
    ("cf.transaction", "ck_transaction_native_id_nonblank"): (
        "d84a50556e7e15c5e5ffe1682bfd93e843c53d29bad691de64d74831ae45cc25"
    ),
    ("core.data_source", "ck_data_source_campaign_finance_authority"): (
        "f9e173679f5617d3fd6e6eccded1459e3b339a37a0c61d4d83bb9706848a362b"
    ),
    ("core.data_source", "ck_data_source_filing_authority_code"): (
        "8342d341997a195d65f02ae9c62bab2b17781fdcc35bd7eeb224d10b7a0af88d"
    ),
    ("core.data_source", "ck_data_source_filing_authority_pair"): (
        "7a173fe65bc28b4759308a71871b4cee6a05262f2465d404e638d1b65e240527"
    ),
    ("core.data_source", "ck_data_source_filing_authority_type"): (
        "64adb1411296515045a8e78f7d2ce364f4734806762dab30f7c1f8a3eb4fa672"
    ),
}
_AUTHORITY_SCOPED_VIEW_COLUMNS = {
    "core.person_er_view": (
        "id",
        "canonical_name",
        "first_name",
        "last_name",
        "date_of_birth",
        "normalized_address",
        "street_number",
        "zip5",
        "state",
        "employer",
        "occupation",
        "identifier_key",
        "filing_authority_scopes",
    ),
    "core.organization_er_view": (
        "id",
        "canonical_name",
        "registered_state",
        "normalized_address",
        "zip5",
        "org_type",
        "identifiers",
        "registered_agent_name",
        "filing_authority_scopes",
    ),
}
_AUTHORITY_SCOPED_VIEW_DEFINITION_SHA256 = {
    "core.organization_er_view": "8e56cef42bc5da8a6e5fd5895645f6d77acff7c85ddf048c33a9f6959ad536ce",
    "core.person_er_view": "1231df628ffc9437fd91f546fdc8248f8764c0589918309090e94626216d18c6",
}
_AUTHORITY_SCOPED_TRIGGER_DEFINITION_SHA256 = {
    ("cf.candidate", "trg_candidate_source_scope_insert"): (
        "72dde602355f1a6e8f7bf89019255472aa8c93acdf8fc5f098dff76538c4f5d2"
    ),
    ("cf.candidate", "trg_candidate_source_scope_update"): (
        "854901e30d8b05f9de438e0451072e3e77d84021bae8bb1254908b338f6417cc"
    ),
    ("cf.committee", "trg_committee_source_scope_insert"): (
        "6fd72fecaf1ad89dac9f88472acc9ce17650b8d51d004ea41d35f49e0cdd121f"
    ),
    ("cf.committee", "trg_committee_source_scope_update"): (
        "91e454a51f787e60d93d3e79d8056a0e74dbec6313d023241fd4a7ae86f198a4"
    ),
    ("cf.filing", "trg_filing_amendment_scope_insert"): (
        "89790d14279de1f1f6a8ffec63fba7bf4ca2cd0fb8133421e2166509a389a8e3"
    ),
    ("cf.filing", "trg_filing_amendment_scope_update"): (
        "105e6f48db2fae4a48bd2b5f5550b68275acfcd315dae45d6daf5830ec0368c6"
    ),
    ("cf.filing", "trg_filing_source_scope_insert"): (
        "6ade742bd1b142b7d8c784cd9a52eb6c36345df5a87125f1e61116f374d6c1bd"
    ),
    ("cf.filing", "trg_filing_source_scope_update"): (
        "667ae104eb9bba50399b35db80f686be71101054d292210926b80cba572799c0"
    ),
    ("cf.transaction", "trg_transaction_amendment_scope_insert"): (
        "2e4ff7d27ac7fd673fe4633aa233d0ef04ccff33b843e06571431cb83f97df8a"
    ),
    ("cf.transaction", "trg_transaction_amendment_scope_update"): (
        "cefabebfed46ff853b0dc290ee67c4e024ced77ce2f901a8b97553e64174b40c"
    ),
    ("cf.transaction", "trg_transaction_source_scope_insert"): (
        "f6a3fee5dea6130af2ae4cf301d605fd2fb6fe90e6f51f641c04abbb9969c3e3"
    ),
    ("cf.transaction", "trg_transaction_source_scope_update"): (
        "30bd5d1b791b343c6d9afffa2d9cad613ad83c4ebfb9c8b5b5fe8a85dddb87e1"
    ),
    ("core.data_source", "trg_data_source_campaign_finance_filing_authority"): (
        "cc95069bf7963043488051a409b5abdab9efa4b022a15e22728f223198a8963f"
    ),
    ("core.source_record", "trg_source_record_supersession_scope_insert"): (
        "1cd6ff38b15b3e911d1b1701efc52d3c30078b0d3440eb697cfb553680318557"
    ),
    ("core.source_record", "trg_source_record_supersession_scope_update"): (
        "9a27a723eb9de842e4155c1fab2a1b847cfd072ecfdb2ccfb8d11762d852471a"
    ),
}
_AUTHORITY_SCOPED_TRIGGER_FUNCTION_DEFINITION_SHA256 = {
    "cf.enforce_filing_amendment_scope": "253d1b17ab59279753dfeae27306c8b9b03dd4456ad71e0e3dee278fcf2a28a4",
    "cf.enforce_source_record_scope": "0d8e6898ea575eba9709b9f2857ae670f9917434fab0aae01c17f1299b8e0408",
    "cf.enforce_transaction_amendment_scope": ("5420f8a622e6d4b28e4e789d90e6048ae7bdbf342f213ac1bdf1ae619ff0c37a"),
    "core.enforce_source_record_supersession_scope": (
        "b8d9df52b61b60f8bae05e9395119ffd4392af08a9d478922ebc84c1ada48b13"
    ),
    "core.populate_campaign_finance_filing_authority": (
        "3d18690a1862ff6b723f825bbceed57a835bb44afa76bcaf47a0cd7cc02abe9f"
    ),
}


def _normalize_catalog_sql(value: str | None) -> str | None:
    return None if value is None else re.sub(r"\s+", " ", value).strip().lower()


def _catalog_sql_sha256(value: str) -> str:
    normalized = _normalize_catalog_sql(value)
    if normalized is None:
        raise ValueError("required catalog definition is absent")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_no_unrelated_core_pending_migrations(conn) -> None:
    migration_names: list[str] = []
    for path in MIGRATIONS_DIR.iterdir():
        if path.suffix != ".sql":
            continue
        if not path.is_file() or path.is_symlink() or not _FILENAME_RE.match(path.name):
            raise ValueError(f"unsafe core migration artifact: {path.name}")
        migration_names.append(path.name)
    if _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION in migration_names:
        raise ValueError("authority-scoped identity migration must remain outside the generic core migration scan")
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM core.schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
    pending = tuple(name for name in sorted(migration_names) if name not in applied)
    if pending:
        raise ValueError(f"unrelated pending core migrations block authority-scoped identity apply: {pending!r}")


def _authority_scoped_identity_ledger_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM core.schema_migrations WHERE filename = %s",
            (_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,),
        )
        return int(cur.fetchone()[0])


def _require_authority_scoped_identity_preimage(conn) -> None:
    if _authority_scoped_identity_ledger_count(conn) != 0:
        raise ValueError("authority-scoped identity migration ledger receipt is already present")
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (_AUTHORITY_SCOPED_IDENTITY_PROGRESS_RELATION,))
        if cur.fetchone()[0] is not None:
            raise ValueError("authority-scoped identity progress exists without prepared schema")
        for relation, expected_columns in _AUTHORITY_SCOPED_COLUMNS.items():
            schema_name, table_name = relation.split(".", 1)
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = ANY(%s)
                ORDER BY column_name
                """,
                (schema_name, table_name, [column[0] for column in expected_columns]),
            )
            present = tuple(row[0] for row in cur.fetchall())
            if present:
                raise ValueError(
                    f"authority-scoped identity target columns exist without ledger receipt: {relation} {present!r}"
                )


def _require_authority_scoped_identity_columns(conn) -> None:
    with conn.cursor() as cur:
        for relation, expected_columns in _AUTHORITY_SCOPED_COLUMNS.items():
            schema_name, table_name = relation.split(".", 1)
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = ANY(%s)
                ORDER BY ordinal_position
                """,
                (schema_name, table_name, [column[0] for column in expected_columns]),
            )
            if tuple(cur.fetchall()) != expected_columns:
                raise ValueError(f"authority-scoped identity column shape mismatch: {relation}")


def _authority_scoped_identity_index_catalog(conn) -> dict[str, tuple[object, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT index_relation.relname,
                   table_namespace.nspname || '.' || table_relation.relname,
                   indexes.indisunique,
                   indexes.indisvalid,
                   indexes.indisready,
                   COALESCE((to_jsonb(indexes) ->> 'indnullsnotdistinct')::boolean, FALSE),
                   ARRAY(
                       SELECT attributes.attname::text
                       FROM unnest(indexes.indkey) WITH ORDINALITY AS keys(attnum, position)
                       JOIN pg_attribute attributes
                         ON attributes.attrelid = indexes.indrelid
                        AND attributes.attnum = keys.attnum
                       ORDER BY keys.position
                   ),
                   pg_get_expr(indexes.indpred, indexes.indrelid)
            FROM pg_index indexes
            JOIN pg_class index_relation ON index_relation.oid = indexes.indexrelid
            JOIN pg_class table_relation ON table_relation.oid = indexes.indrelid
            JOIN pg_namespace table_namespace ON table_namespace.oid = table_relation.relnamespace
            WHERE index_relation.relname = ANY(%s)
            """,
            (list(_AUTHORITY_SCOPED_INDEXES),),
        )
        rows = cur.fetchall()
    if len({row[0] for row in rows}) != len(rows):
        raise ValueError("authority-scoped identity index catalog mismatch")
    return {
        name: (
            relation,
            bool(unique),
            bool(valid),
            bool(ready),
            bool(nulls_not_distinct),
            tuple(columns),
            _normalize_catalog_sql(predicate),
        )
        for name, relation, unique, valid, ready, nulls_not_distinct, columns, predicate in rows
    }


def _require_authority_scoped_identity_indexes(conn) -> None:
    actual_catalog = _authority_scoped_identity_index_catalog(conn)
    if len(actual_catalog) != len(_AUTHORITY_SCOPED_INDEXES):
        raise ValueError("authority-scoped identity index catalog mismatch")
    actual = {
        name: (relation, unique, nulls_not_distinct, columns, predicate)
        for name, (relation, unique, valid, ready, nulls_not_distinct, columns, predicate) in actual_catalog.items()
        if valid and ready
    }
    expected = {
        name: (*shape[:-1], _normalize_catalog_sql(shape[-1])) for name, shape in _AUTHORITY_SCOPED_INDEXES.items()
    }
    if actual != expected:
        raise ValueError("authority-scoped identity index catalog mismatch")


def _require_authority_scoped_identity_partial_indexes(conn) -> None:
    for name, shape in _authority_scoped_identity_index_catalog(conn).items():
        relation, unique, _valid, _ready, nulls_not_distinct, columns, predicate = shape
        expected = _AUTHORITY_SCOPED_INDEXES[name]
        normalized_expected = (*expected[:-1], _normalize_catalog_sql(expected[-1]))
        if (relation, unique, nulls_not_distinct, columns, predicate) != normalized_expected:
            raise ValueError("authority-scoped identity partial index catalog mismatch")


def _require_authority_scoped_identity_constraints(conn, *, require_validated: bool = True) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT relation_namespace.nspname || '.' || relation.relname,
                   constraints.conname,
                   constraints.contype::text,
                   constraints.convalidated,
                   COALESCE((to_jsonb(constraints) ->> 'conenforced')::boolean, TRUE),
                   pg_get_constraintdef(constraints.oid, true)
            FROM pg_constraint constraints
            JOIN pg_class relation ON relation.oid = constraints.conrelid
            JOIN pg_namespace relation_namespace ON relation_namespace.oid = relation.relnamespace
            WHERE constraints.conname = ANY(%s)
            """,
            ([name for _relation, name in _AUTHORITY_SCOPED_CONSTRAINT_DEFINITION_SHA256],),
        )
        rows = cur.fetchall()
    actual = {
        (relation, name): (
            str(kind),
            bool(enforced),
            _catalog_sql_sha256(definition.removesuffix(" NOT VALID")),
            bool(validated),
        )
        for relation, name, kind, validated, enforced, definition in rows
    }
    expected = {
        key: ("c", True, definition_sha256)
        for key, definition_sha256 in _AUTHORITY_SCOPED_CONSTRAINT_DEFINITION_SHA256.items()
    }
    if set(actual) != set(expected) or any(actual[key][:3] != expected[key] for key in expected):
        raise ValueError("authority-scoped identity constraint catalog mismatch")
    if require_validated and any(not actual[key][3] for key in expected):
        raise ValueError("authority-scoped identity constraint catalog mismatch")


def _require_authority_scoped_identity_triggers(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT relation_namespace.nspname || '.' || relation.relname,
                   triggers.tgname,
                   triggers.tgtype::integer,
                   triggers.tgenabled,
                   function_namespace.nspname || '.' || functions.proname,
                   triggers.tgnewtable,
                   pg_get_triggerdef(triggers.oid, true)
            FROM pg_trigger triggers
            JOIN pg_class relation ON relation.oid = triggers.tgrelid
            JOIN pg_namespace relation_namespace ON relation_namespace.oid = relation.relnamespace
            JOIN pg_proc functions ON functions.oid = triggers.tgfoid
            JOIN pg_namespace function_namespace ON function_namespace.oid = functions.pronamespace
            WHERE NOT triggers.tgisinternal
              AND triggers.tgname = ANY(%s)
            """,
            ([name for _relation, name in _AUTHORITY_SCOPED_TRIGGERS],),
        )
        rows = cur.fetchall()
    actual = {
        (relation, name): (
            int(trigger_type),
            function_name,
            new_table,
            _catalog_sql_sha256(definition),
        )
        for relation, name, trigger_type, enabled, function_name, new_table, definition in rows
        if enabled == "O"
    }
    expected = {
        key: (*shape, _AUTHORITY_SCOPED_TRIGGER_DEFINITION_SHA256[key])
        for key, shape in _AUTHORITY_SCOPED_TRIGGERS.items()
    }
    if actual != expected:
        raise ValueError("authority-scoped identity trigger catalog mismatch")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT function_namespace.nspname || '.' || functions.proname,
                   pg_get_functiondef(functions.oid)
            FROM pg_proc functions
            JOIN pg_namespace function_namespace ON function_namespace.oid = functions.pronamespace
            WHERE function_namespace.nspname || '.' || functions.proname = ANY(%s)
            """,
            (list(_AUTHORITY_SCOPED_TRIGGER_FUNCTION_DEFINITION_SHA256),),
        )
        function_rows = cur.fetchall()
    actual_functions = {name: _catalog_sql_sha256(definition) for name, definition in function_rows}
    if actual_functions != _AUTHORITY_SCOPED_TRIGGER_FUNCTION_DEFINITION_SHA256:
        raise ValueError("authority-scoped identity trigger function catalog mismatch")


def _require_authority_scoped_identity_views(conn) -> None:
    with conn.cursor() as cur:
        for relation, expected_columns in _AUTHORITY_SCOPED_VIEW_COLUMNS.items():
            schema_name, view_name = relation.split(".", 1)
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema_name, view_name),
            )
            if tuple(row[0] for row in cur.fetchall()) != expected_columns:
                raise ValueError(f"authority-scoped identity view columns mismatch: {relation}")
            cur.execute("SELECT pg_get_viewdef(%s::regclass, true)", (relation,))
            definition_sha256 = _catalog_sql_sha256(cur.fetchone()[0])
            if definition_sha256 != _AUTHORITY_SCOPED_VIEW_DEFINITION_SHA256[relation]:
                raise ValueError(f"authority-scoped identity view definition mismatch: {relation}")


def _require_authority_scoped_identity_semantics(conn) -> None:
    violation_queries = {
        "data_source_authority": """
            SELECT COUNT(*) FROM core.data_source
            WHERE (filing_authority_type IS NULL) <> (filing_authority_code IS NULL)
               OR (domain = 'campaign_finance' AND filing_authority_type IS NULL)
               OR filing_authority_type IS DISTINCT FROM lower(btrim(filing_authority_type))
               OR filing_authority_code IS DISTINCT FROM upper(btrim(filing_authority_code))
               OR (domain = 'campaign_finance' AND lower(btrim(jurisdiction)) = 'federal'
                   AND (filing_authority_type, filing_authority_code) IS DISTINCT FROM ('federal', 'FEC'))
        """,
        "source_record_supersession": """
            SELECT COUNT(*)
            FROM core.source_record source_record
            LEFT JOIN core.source_record successor ON successor.id = source_record.superseded_by
            WHERE source_record.superseded_by IS NOT NULL
              AND (successor.id IS NULL OR successor.data_source_id IS DISTINCT FROM source_record.data_source_id)
        """,
        "filing_amendment": """
            SELECT COUNT(*) FROM cf.filing filing
            JOIN cf.filing original ON original.id = filing.amended_from_filing_id
            WHERE filing.data_source_id IS NOT NULL
              AND original.data_source_id IS DISTINCT FROM filing.data_source_id
        """,
        "transaction_amendment": """
            SELECT COUNT(*) FROM cf.transaction transaction
            JOIN cf.transaction amendment ON amendment.id = transaction.amended_by_transaction_id
            WHERE transaction.data_source_id IS NOT NULL
              AND amendment.data_source_id IS DISTINCT FROM transaction.data_source_id
        """,
    }
    for table, native_column in (
        ("committee", "native_committee_id"),
        ("candidate", "native_candidate_id"),
        ("filing", "native_filing_id"),
        ("transaction", "native_transaction_id"),
    ):
        violation_queries[f"{table}_native_identity"] = f"""
            SELECT COUNT(*) FROM cf.{table}
            WHERE (data_source_id IS NULL) <> ({native_column} IS NULL)
               OR ({native_column} IS NOT NULL AND btrim({native_column}) = '')
        """
        violation_queries[f"{table}_source_scope"] = f"""
            SELECT COUNT(*) FROM cf.{table} owned_row
            JOIN core.source_record source_record ON source_record.id = owned_row.source_record_id
            WHERE owned_row.data_source_id IS NOT NULL
              AND source_record.data_source_id IS DISTINCT FROM owned_row.data_source_id
        """
    with conn.cursor() as cur:
        for label, query in violation_queries.items():
            cur.execute(query)
            if cur.fetchone()[0] != 0:
                raise ValueError(f"authority-scoped identity semantic verification failed: {label}")


def _require_authority_scoped_identity_progress(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT relkind, pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass(%s)",
            (_AUTHORITY_SCOPED_IDENTITY_PROGRESS_RELATION,),
        )
        if cur.fetchone() != ("r", _PRODUCTION_DATABASE_USER):
            raise ValueError("authority-scoped identity progress relation shape mismatch")
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'authority_scoped_identity_migration_progress'
            ORDER BY ordinal_position
            """
        )
        if tuple(cur.fetchall()) != (
            ("target_relation", "text", "NO"),
            ("migration_filename", "text", "NO"),
            ("migration_sha256", "text", "NO"),
            ("last_id", "uuid", "YES"),
        ):
            raise ValueError("authority-scoped identity progress column shape mismatch")
        cur.execute(
            """
            SELECT target_relation, migration_filename, migration_sha256, last_id
            FROM core.authority_scoped_identity_migration_progress
            ORDER BY target_relation
            """
        )
        rows = cur.fetchall()
    expected_targets = tuple(
        sorted(phase.replace("backfill.", "cf.") for phase in _AUTHORITY_SCOPED_IDENTITY_BACKFILL_PHASES)
    )
    if tuple(row[0] for row in rows) != expected_targets:
        raise ValueError("authority-scoped identity progress targets mismatch")
    for _target, filename, digest, _last_id in rows:
        if filename != _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION:
            raise ValueError("authority-scoped identity progress filename mismatch")
        if digest != _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256:
            raise ValueError("authority-scoped identity progress digest mismatch")


def _require_authority_scoped_identity_partial_shape(conn) -> None:
    _require_authority_scoped_identity_columns(conn)
    _require_authority_scoped_identity_constraints(conn, require_validated=False)
    _require_authority_scoped_identity_partial_indexes(conn)
    _require_authority_scoped_identity_triggers(conn)
    _require_authority_scoped_identity_views(conn)
    _require_authority_scoped_identity_progress(conn)


def _require_authority_scoped_identity_backfills_complete(conn) -> None:
    with conn.cursor() as cur:
        for table, native_column in (
            ("committee", "native_committee_id"),
            ("candidate", "native_candidate_id"),
            ("filing", "native_filing_id"),
            ("transaction", "native_transaction_id"),
        ):
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM cf.{table} AS owned_row
                JOIN core.source_record AS source_record ON source_record.id = owned_row.source_record_id
                WHERE owned_row.data_source_id IS NULL OR owned_row.{native_column} IS NULL
                """
            )
            if cur.fetchone()[0] != 0:
                raise ValueError(f"authority-scoped identity backfill is incomplete: cf.{table}")


def _require_authority_scoped_identity_transients_absent(conn) -> None:
    retired_constraints = (
        "committee_fec_committee_id_key",
        "candidate_fec_candidate_id_key",
        "filing_filing_fec_id_key",
        "fk_committee_source_scope",
        "fk_candidate_source_scope",
        "fk_filing_source_scope",
        "fk_filing_amended_from_scope",
        "uq_filing_id_data_source",
        "fk_transaction_source_scope",
        "fk_transaction_amended_by_scope",
        "uq_transaction_id_data_source",
        "fk_source_record_superseded",
        "fk_source_record_superseded_scope",
        "uq_source_record_id_data_source",
    )
    retired_indexes = (
        "core.idx_data_source_dedup_pre_authority",
        "core.uq_source_record_id_data_source",
        "cf.uq_transaction_sub_id_pre_authority",
        "cf.uq_filing_id_data_source",
        "cf.uq_transaction_id_data_source",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (_AUTHORITY_SCOPED_IDENTITY_PROGRESS_RELATION,))
        if cur.fetchone()[0] is not None:
            raise ValueError("authority-scoped identity progress remains after cutover")
        cur.execute("SELECT COUNT(*) FROM pg_constraint WHERE conname = ANY(%s)", (list(retired_constraints),))
        if cur.fetchone()[0] != 0:
            raise ValueError("authority-scoped identity retired constraint remains")
        for relation in retired_indexes:
            cur.execute("SELECT to_regclass(%s)", (relation,))
            if cur.fetchone()[0] is not None:
                raise ValueError("authority-scoped identity retired index remains")


def _require_authority_scoped_identity_atomic_shape(conn) -> None:
    if _authority_scoped_identity_ledger_count(conn) != 1:
        raise ValueError("authority-scoped identity migration ledger receipt is absent")
    _require_authority_scoped_identity_columns(conn)
    _require_authority_scoped_identity_constraints(conn)
    _require_authority_scoped_identity_indexes(conn)
    _require_authority_scoped_identity_triggers(conn)
    _require_authority_scoped_identity_views(conn)
    _require_authority_scoped_identity_transients_absent(conn)


def _require_authority_scoped_identity_applied_shape(conn) -> None:
    _require_authority_scoped_identity_atomic_shape(conn)
    _require_authority_scoped_identity_semantics(conn)
    _require_authority_scoped_identity_backfills_complete(conn)


def _classify_authority_scoped_identity_state(conn) -> str:
    _require_production_owner_shapes(conn, execution_origin_present=True)
    _require_no_unrelated_core_pending_migrations(conn)
    _require_production_migration_quiescence(conn)
    ledger_count = _authority_scoped_identity_ledger_count(conn)
    if ledger_count == 0:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (_AUTHORITY_SCOPED_IDENTITY_PROGRESS_RELATION,))
            progress_exists = cur.fetchone()[0] is not None
        if progress_exists:
            _require_authority_scoped_identity_partial_shape(conn)
            return "partial_resumable"
        _require_authority_scoped_identity_preimage(conn)
        return "pending_absent"
    if ledger_count == 1:
        _require_authority_scoped_identity_applied_shape(conn)
        return "already_applied_verified"
    raise ValueError("authority-scoped identity migration ledger receipt count mismatch")


def _set_authority_scoped_identity_transaction_limits(conn, *, statement_timeout: str) -> None:
    conn.execute("SET LOCAL lock_timeout = '5s'")
    conn.execute(f"SET LOCAL statement_timeout = '{statement_timeout}'")


def _classify_authority_scoped_identity_state_bounded_read_only(conn) -> str:
    conn.rollback()
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        _set_authority_scoped_identity_transaction_limits(
            conn,
            statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT,
        )
        return _classify_authority_scoped_identity_state(conn)


def _acquire_authority_scoped_identity_session_lock(conn) -> None:
    conn.rollback()
    locked = conn.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
        (_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_LOCK_NAME,),
    ).fetchone()
    conn.commit()
    if not locked or not bool(locked[0]):
        raise ValueError("another production authority-scoped identity migration owner holds the lock")


def _release_authority_scoped_identity_session_lock(conn) -> None:
    conn.rollback()
    unlocked = conn.execute(
        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
        (_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_LOCK_NAME,),
    ).fetchone()
    conn.commit()
    if not unlocked or not bool(unlocked[0]):
        raise RuntimeError("authority-scoped identity migration session lock was lost")


def _prepare_authority_scoped_identity_migration(conn, sql: str) -> None:
    conn.rollback()
    with conn.transaction():
        _set_authority_scoped_identity_transaction_limits(
            conn,
            statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_CUTOVER_STATEMENT_TIMEOUT,
        )
        _require_production_migration_quiescence(conn)
        if _classify_authority_scoped_identity_state(conn) != "pending_absent":
            raise ValueError("authority-scoped identity prepare requires exact pending state")
        conn.execute(sql)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO core.authority_scoped_identity_migration_progress (
                    target_relation, migration_filename, migration_sha256
                ) VALUES (%s, %s, %s)
                """,
                [
                    (
                        phase.replace("backfill.", "cf."),
                        _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,
                        _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256,
                    )
                    for phase in _AUTHORITY_SCOPED_IDENTITY_BACKFILL_PHASES
                ],
            )
        _require_authority_scoped_identity_partial_shape(conn)


def _authority_scoped_identity_backfill_sql(phase_name: str) -> str:
    try:
        target_relation, native_column, native_expression = _AUTHORITY_SCOPED_IDENTITY_BACKFILL_SPECS[phase_name]
    except KeyError as exc:
        raise ValueError(f"unsupported authority-scoped identity backfill phase: {phase_name}") from exc
    dependency_column = _AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_COLUMNS.get(phase_name)
    if dependency_column is not None:
        return f"""
            WITH RECURSIVE target_batch AS MATERIALIZED (
                SELECT selected_row.id
                FROM {target_relation} AS selected_row
                CROSS JOIN (VALUES (%s::uuid)) AS target_cursor(last_id)
                WHERE target_cursor.last_id IS NULL OR selected_row.id > target_cursor.last_id
                ORDER BY selected_row.id
                LIMIT %s
                FOR UPDATE OF selected_row
            ), dependency_walk(id, path, is_cycle, depth) AS (
                SELECT target_batch.id, ARRAY[target_batch.id], false, 0
                FROM target_batch
                UNION ALL
                SELECT dependency.id,
                       dependency_walk.path || dependency.id,
                       dependency.id = ANY(dependency_walk.path),
                       dependency_walk.depth + 1
                FROM dependency_walk
                JOIN {target_relation} AS current_row ON current_row.id = dependency_walk.id
                JOIN {target_relation} AS dependency
                  ON dependency.id = current_row.{dependency_column}
                WHERE NOT dependency_walk.is_cycle
                  AND dependency_walk.depth
                      < {_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_DEPTH_LIMIT}
            ), dependency_closure AS MATERIALIZED (
                SELECT dependency_walk.id
                FROM dependency_walk
                GROUP BY dependency_walk.id
            ), dependency_edges AS MATERIALIZED (
                SELECT current_row.id AS current_id,
                       dependency.id AS dependency_id,
                       current_source.id AS current_source_id,
                       dependency_source.id AS dependency_source_id,
                       current_source.data_source_id AS current_source_data_source_id,
                       dependency_source.data_source_id AS dependency_source_data_source_id,
                       current_row.data_source_id AS current_data_source_id,
                       dependency.data_source_id AS dependency_data_source_id
                FROM dependency_closure
                JOIN {target_relation} AS current_row
                  ON current_row.id = dependency_closure.id
                LEFT JOIN {target_relation} AS dependency
                  ON dependency.id = current_row.{dependency_column}
                LEFT JOIN core.source_record AS current_source
                  ON current_source.id = current_row.source_record_id
                LEFT JOIN core.source_record AS dependency_source
                  ON dependency_source.id = dependency.source_record_id
                WHERE current_row.{dependency_column} IS NOT NULL
            ), closure_status AS MATERIALIZED (
                SELECT CASE
                    WHEN EXISTS (
                        SELECT 1 FROM dependency_walk WHERE dependency_walk.is_cycle
                    ) THEN 'dependency cycle'
                    WHEN EXISTS (
                        SELECT 1
                        FROM dependency_walk
                        JOIN {target_relation} AS depth_row ON depth_row.id = dependency_walk.id
                        WHERE NOT dependency_walk.is_cycle
                          AND dependency_walk.depth
                              = {_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_DEPTH_LIMIT}
                          AND depth_row.{dependency_column} IS NOT NULL
                    ) THEN 'dependency depth overflow'
                    WHEN (
                        SELECT count(*) FROM dependency_closure
                    ) > {_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_CLOSURE_LIMIT}
                    THEN 'dependency closure overflow'
                    WHEN EXISTS (
                        SELECT 1
                        FROM dependency_edges
                        WHERE dependency_edges.dependency_id IS NULL
                           OR dependency_edges.current_source_id IS NULL
                           OR dependency_edges.dependency_source_id IS NULL
                    ) THEN 'dependency source is missing'
                    WHEN EXISTS (
                        SELECT 1
                        FROM dependency_edges
                        WHERE dependency_edges.current_source_data_source_id
                                  IS DISTINCT FROM dependency_edges.dependency_source_data_source_id
                           OR (
                               dependency_edges.current_data_source_id IS NOT NULL
                               AND dependency_edges.current_data_source_id
                                   IS DISTINCT FROM dependency_edges.current_source_data_source_id
                           )
                           OR (
                               dependency_edges.dependency_data_source_id IS NOT NULL
                               AND dependency_edges.dependency_data_source_id
                                   IS DISTINCT FROM dependency_edges.dependency_source_data_source_id
                           )
                    ) THEN 'dependency scope mismatch'
                    ELSE NULL
                END AS failure
            ), eligible AS (
                SELECT selected_row.id,
                       source_record.data_source_id,
                       {native_expression} AS native_id
                FROM dependency_closure
                JOIN {target_relation} AS selected_row
                  ON selected_row.id = dependency_closure.id
                JOIN core.source_record AS source_record
                  ON source_record.id = selected_row.source_record_id
                CROSS JOIN closure_status
                WHERE closure_status.failure IS NULL
                  AND (
                      selected_row.data_source_id IS NULL
                      OR selected_row.{native_column} IS NULL
                  )
            ), updated AS (
                UPDATE {target_relation} AS owned_row
                SET data_source_id = eligible.data_source_id,
                    {native_column} = eligible.native_id
                FROM eligible
                WHERE owned_row.id = eligible.id
                RETURNING owned_row.id
            ), advanced AS (
                UPDATE core.authority_scoped_identity_migration_progress AS progress
                SET last_id = selected.last_id
                FROM (
                    SELECT target_batch.id AS last_id,
                           count(*) OVER () AS row_count
                    FROM target_batch
                    CROSS JOIN closure_status
                    WHERE closure_status.failure IS NULL
                    ORDER BY target_batch.id DESC
                    LIMIT 1
                ) AS selected
                WHERE progress.target_relation = '{target_relation}'
                  AND selected.row_count > 0
                RETURNING selected.row_count
            )
            SELECT COALESCE((SELECT row_count FROM advanced), 0),
                   (SELECT failure FROM closure_status)
        """
    return f"""
        WITH target_batch AS MATERIALIZED (
            SELECT selected_row.id
            FROM {target_relation} AS selected_row
            CROSS JOIN (VALUES (%s::uuid)) AS target_cursor(last_id)
            WHERE target_cursor.last_id IS NULL OR selected_row.id > target_cursor.last_id
            ORDER BY selected_row.id
            LIMIT %s
            FOR UPDATE OF selected_row
        ), eligible AS (
            SELECT selected_row.id,
                   source_record.data_source_id,
                   {native_expression} AS native_id
            FROM target_batch
            JOIN {target_relation} AS selected_row ON selected_row.id = target_batch.id
            JOIN core.source_record AS source_record ON source_record.id = selected_row.source_record_id
            WHERE selected_row.data_source_id IS NULL OR selected_row.{native_column} IS NULL
        ), updated AS (
            UPDATE {target_relation} AS owned_row
            SET data_source_id = eligible.data_source_id,
                {native_column} = eligible.native_id
            FROM eligible
            WHERE owned_row.id = eligible.id
            RETURNING owned_row.id
        ), advanced AS (
            UPDATE core.authority_scoped_identity_migration_progress AS progress
            SET last_id = selected.last_id
            FROM (
                SELECT id AS last_id, count(*) OVER () AS row_count
                FROM target_batch
                ORDER BY id DESC
                LIMIT 1
            ) AS selected
            WHERE progress.target_relation = '{target_relation}'
              AND selected.row_count > 0
            RETURNING selected.row_count
        )
        SELECT COALESCE((SELECT row_count FROM advanced), 0), NULL::text
    """


def _read_authority_scoped_identity_backfill_cursor(conn, phase_name: str):
    target_relation = phase_name.replace("backfill.", "cf.")
    row = conn.execute(
        """
        SELECT last_id, migration_filename, migration_sha256
        FROM core.authority_scoped_identity_migration_progress
        WHERE target_relation = %s
        FOR UPDATE
        """,
        (target_relation,),
    ).fetchone()
    if row is None:
        raise ValueError(f"authority-scoped identity progress row is absent: {target_relation}")
    last_id, filename, digest = row
    if filename != _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION:
        raise ValueError("authority-scoped identity progress filename mismatch")
    if digest != _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256:
        raise ValueError("authority-scoped identity progress digest mismatch")
    return last_id


def _run_authority_scoped_identity_backfills(conn, phases: dict[str, str]) -> None:
    for phase_name in _AUTHORITY_SCOPED_IDENTITY_BACKFILL_PHASES:
        if phase_name not in phases:
            raise ValueError(f"authority-scoped identity backfill phase is absent: {phase_name}")
        batch_sql = _authority_scoped_identity_backfill_sql(phase_name)
        while True:
            conn.rollback()
            with conn.transaction():
                _set_authority_scoped_identity_transaction_limits(
                    conn,
                    statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT,
                )
                _require_production_migration_quiescence(conn)
                last_id = _read_authority_scoped_identity_backfill_cursor(conn, phase_name)
                result = conn.execute(
                    batch_sql,
                    (last_id, _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE),
                ).fetchone()
                row_count = int(result[0]) if result else 0
                failure = str(result[1]) if result and result[1] is not None else None
                if failure is not None:
                    raise ValueError(f"authority-scoped identity {failure}: {phase_name}")
            if row_count == 0:
                break


def _authority_scoped_identity_index_matches_expected(
    name: str,
    shape: tuple[object, ...],
) -> bool:
    relation, unique, _valid, _ready, nulls_not_distinct, columns, predicate = shape
    expected = _AUTHORITY_SCOPED_INDEXES[name]
    normalized_expected = (*expected[:-1], _normalize_catalog_sql(expected[-1]))
    return (relation, unique, nulls_not_distinct, columns, predicate) == normalized_expected


def _run_authority_scoped_identity_index_phase(conn, *, phase_name: str, sql: str) -> None:
    index_name = phase_name.removeprefix("index.")
    conn.rollback()
    with conn.transaction():
        _set_authority_scoped_identity_transaction_limits(
            conn,
            statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_CUTOVER_STATEMENT_TIMEOUT,
        )
        _require_production_migration_quiescence(conn)
        _require_authority_scoped_identity_progress(conn)

    conn.autocommit = True
    try:
        conn.execute("SET lock_timeout = '5s'")
        conn.execute(f"SET statement_timeout = '{_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT}'")
        catalog = _authority_scoped_identity_index_catalog(conn)
        existing = catalog.get(index_name)
        if existing is not None:
            if not _authority_scoped_identity_index_matches_expected(index_name, existing):
                raise ValueError("authority-scoped identity index drift blocks resume")
            if bool(existing[2]) and bool(existing[3]):
                return
            schema_name = str(existing[0]).split(".", 1)[0]
            conn.execute(f"DROP INDEX CONCURRENTLY {schema_name}.{index_name}")
        conn.execute(sql)
    finally:
        try:
            conn.execute("RESET statement_timeout")
            conn.execute("RESET lock_timeout")
        finally:
            conn.autocommit = False


def _run_authority_scoped_identity_validation_phase(conn, sql: str) -> None:
    conn.rollback()
    with conn.transaction():
        _set_authority_scoped_identity_transaction_limits(
            conn,
            statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT,
        )
        _require_production_migration_quiescence(conn)
        conn.execute(sql)


def _verify_authority_scoped_identity_pre_cutover(conn) -> None:
    conn.rollback()
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        _set_authority_scoped_identity_transaction_limits(
            conn,
            statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT,
        )
        _require_production_migration_quiescence(conn)
        if _authority_scoped_identity_ledger_count(conn) != 0:
            raise ValueError("authority-scoped identity pre-cutover ledger is not empty")
        _require_authority_scoped_identity_columns(conn)
        _require_authority_scoped_identity_constraints(conn)
        _require_authority_scoped_identity_indexes(conn)
        _require_authority_scoped_identity_triggers(conn)
        _require_authority_scoped_identity_views(conn)
        _require_authority_scoped_identity_progress(conn)
        _require_authority_scoped_identity_semantics(conn)
        _require_authority_scoped_identity_backfills_complete(conn)


def _cut_over_authority_scoped_identity_migration(conn, sql: str) -> None:
    conn.rollback()
    with conn.transaction():
        _set_authority_scoped_identity_transaction_limits(
            conn,
            statement_timeout=_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_CUTOVER_STATEMENT_TIMEOUT,
        )
        _require_production_migration_quiescence(conn)
        conn.execute(sql)
        conn.execute(
            "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
            (_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,),
        )
        _require_authority_scoped_identity_atomic_shape(conn)


def _run_production_authority_scoped_identity_operation(
    conn,
    *,
    operation: str,
    expected_host: str,
    expected_port: int,
    expected_database: str,
) -> dict[str, object]:
    if operation not in {"preflight", "apply", "verify"}:
        raise ValueError(f"unsupported authority-scoped identity operation: {operation}")
    identity = _require_production_identity(
        conn,
        expected_host=expected_host,
        expected_port=expected_port,
        expected_database=expected_database,
        expected_read_only="off" if operation == "apply" else "on",
    )
    sql = _load_pinned_authority_scoped_identity_sql()
    phases = _parse_authority_scoped_identity_phases(sql)
    if operation == "preflight":
        state = _classify_authority_scoped_identity_state_bounded_read_only(conn)
    elif operation == "verify":
        state = _classify_authority_scoped_identity_state_bounded_read_only(conn)
        if state != "already_applied_verified":
            raise ValueError("authority-scoped identity migration is not applied")
        state = "applied_verified"
    else:
        _acquire_authority_scoped_identity_session_lock(conn)
        try:
            state = _classify_authority_scoped_identity_state_bounded_read_only(conn)
            if state == "pending_absent":
                _prepare_authority_scoped_identity_migration(conn, phases["prepare"])
                state = "partial_resumable"
            if state == "partial_resumable":
                _run_authority_scoped_identity_backfills(conn, phases)
                for phase_name, phase_sql in phases.items():
                    if not phase_name.startswith("index."):
                        continue
                    _run_authority_scoped_identity_index_phase(
                        conn,
                        phase_name=phase_name,
                        sql=phase_sql,
                    )
                for phase_name, phase_sql in phases.items():
                    if phase_name.startswith("validate."):
                        _run_authority_scoped_identity_validation_phase(conn, phase_sql)
                _verify_authority_scoped_identity_pre_cutover(conn)
                _cut_over_authority_scoped_identity_migration(conn, phases["cutover"])
                state = "applied_verified"
        finally:
            _release_authority_scoped_identity_session_lock(conn)
    return {
        "database_identity": identity,
        "migration": _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,
        "migration_sha256": _PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256,
        "state": state,
    }


def _ensure_ledger(conn):
    conn.execute("CREATE SCHEMA IF NOT EXISTS core")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.schema_migrations (
            filename    TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()


def _parse_baseline(baseline_path):
    entries = []
    seen = set()
    for line in baseline_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _FILENAME_RE.match(stripped):
            raise ValueError(f"Unsafe baseline entry: {stripped}")
        if stripped in seen:
            raise ValueError(f"Duplicate baseline entry: {stripped}")
        seen.add(stripped)
        entries.append(stripped)
    return entries


def _adopt_baseline(conn, baseline_entries, migrations_dir):
    for entry in baseline_entries:
        if not (migrations_dir / entry).is_file():
            raise ValueError(f"Baseline entry has no matching migration file: {entry}")
    with conn.cursor() as cur:
        for entry in baseline_entries:
            cur.execute(
                "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
                (entry,),
            )
    conn.commit()


def _apply_pending(conn, migrations_dir):
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM core.schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    pending = sorted(f.name for f in migrations_dir.iterdir() if f.suffix == ".sql" and f.name not in applied)

    for filename in pending:
        sql = (migrations_dir / filename).read_text(encoding="utf-8")
        if _CONCURRENTLY_RE.search(sql):
            raise ValueError(f"Migration {filename} contains CONCURRENTLY, which cannot run inside a transaction")
        conn.execute(sql)
        conn.execute(
            "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
            (filename,),
        )
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args([] if argv is None else argv)
    _require_production_arguments(parser, args)
    try:
        conn = get_connection()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        if args.production_execution_origin is not None:
            operation = args.production_execution_origin
            result = _run_production_execution_origin_operation(
                conn,
                operation=operation,
                expected_host=args.expected_host,
                expected_port=args.expected_port,
                expected_database=args.expected_database,
            )
            print(json.dumps({"mode": operation, **result}, sort_keys=True))
            return 0
        if args.production_authority_scoped_identity is not None:
            operation = args.production_authority_scoped_identity
            result = _run_production_authority_scoped_identity_operation(
                conn,
                operation=operation,
                expected_host=args.expected_host,
                expected_port=args.expected_port,
                expected_database=args.expected_database,
            )
            print(json.dumps({"mode": operation, **result}, sort_keys=True))
            return 0

        _ensure_ledger(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM core.schema_migrations")
            ledger_count = cur.fetchone()[0]

        if ledger_count == 0:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('cf.candidate') IS NOT NULL")
                has_sentinel = cur.fetchone()[0]

            if not has_sentinel:
                print(
                    "error: ledger is empty and base schema is not initialized "
                    "(cf.candidate not found). Run the full schema init first.",
                    file=sys.stderr,
                )
                return 1

            baseline_entries = _parse_baseline(BASELINE_PATH)
            _adopt_baseline(conn, baseline_entries, MIGRATIONS_DIR)

        _apply_pending(conn, MIGRATIONS_DIR)
        return 0

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
