"""KAT for the ledger-based migration runner.

Recreates the old production zcta_district shape (single-column PK, no
boundary_year) plus minimal dependency tables, then proves apply_migrations
adopts the frozen baseline, skips the retro-edited 2026_07_07_zcta_district.sql,
and applies only the explicitly enumerated pending deltas.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
import psycopg
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]

_POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
_POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5475"))
_POSTGRES_USER = os.environ.get("POSTGRES_USER", "civibus")
_POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "civibus_dev")
_DB_NAME_PREFIX = "test_migrations_"
_SAFE_HOSTS = {None, "", "localhost", "127.0.0.1"}
_SAFE_PORTS = {5475, 5477, 5531, 5545}


def _skip_or_fail(message: str) -> None:
    if os.environ.get("CIVIBUS_REQUIRE_DB") == "1":
        pytest.fail(message)
    pytest.skip(message)


def _admin_connect() -> psycopg.Connection:
    raw_host = os.environ.get("POSTGRES_HOST")
    if raw_host not in _SAFE_HOSTS:
        _skip_or_fail(f"POSTGRES_HOST={raw_host} is not a safe local host for destructive tests")
    if _POSTGRES_PORT not in _SAFE_PORTS:
        _skip_or_fail(f"POSTGRES_PORT={_POSTGRES_PORT} is not an approved safe-local test port")

    try:
        conn = psycopg.connect(
            user=_POSTGRES_USER,
            password=_POSTGRES_PASSWORD,
            dbname="postgres",
            host=_POSTGRES_HOST or "localhost",
            port=_POSTGRES_PORT,
            autocommit=True,
        )
        return conn
    except psycopg.Error as exc:
        _skip_or_fail(f"Cannot connect to Postgres at {_POSTGRES_HOST}:{_POSTGRES_PORT}: {exc}")
        raise  # unreachable, keeps type-checker happy


def _connect_to(dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        user=_POSTGRES_USER,
        password=_POSTGRES_PASSWORD,
        dbname=dbname,
        host=_POSTGRES_HOST or "localhost",
        port=_POSTGRES_PORT,
    )


# ---------------------------------------------------------------------------
# SQL for recreating the old production schema shape
# ---------------------------------------------------------------------------

_OLD_ZCTA_DISTRICT_SQL = textwrap.dedent("""\
    CREATE SCHEMA IF NOT EXISTS civic;

    CREATE TABLE civic.zcta_district (
        zcta5           TEXT NOT NULL CHECK (zcta5 ~ '^[0-9]{5}$'),
        state_fips      TEXT NOT NULL CHECK (state_fips ~ '^[0-9]{2}$'),
        cd_geoid        TEXT NOT NULL CHECK (cd_geoid ~ '^[0-9A-Z]{4}$'),
        district_number TEXT NOT NULL CHECK (char_length(district_number) = 2),
        land_share      NUMERIC(7,5) NOT NULL CHECK (land_share >= 0 AND land_share <= 1),
        source_url      TEXT NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (zcta5)
    );

    CREATE INDEX idx_zcta_district_cd_geoid
        ON civic.zcta_district (cd_geoid);
    CREATE INDEX idx_zcta_district_state_fips
        ON civic.zcta_district (state_fips);

    INSERT INTO civic.zcta_district (zcta5, state_fips, cd_geoid, district_number, land_share, source_url)
    VALUES ('27514', '37', '3704', '04', 0.95000, 'https://example.com/cd119');
""")

_MINIMAL_CORE_SQL = textwrap.dedent("""\
    CREATE SCHEMA IF NOT EXISTS core;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    CREATE OR REPLACE FUNCTION core.set_updated_at()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN NEW.updated_at := NOW(); RETURN NEW; END; $$;

    CREATE TABLE IF NOT EXISTS core.source_record (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4()
    );

    CREATE TABLE IF NOT EXISTS core.refresh_run (
        pull_status  TEXT NOT NULL
            CHECK (pull_status IN ('crashed', 'empty', 'degraded', 'success')),
        completed_at TIMESTAMPTZ NOT NULL
    );

    CREATE TABLE IF NOT EXISTS core.entity_source (
        id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type     TEXT NOT NULL CHECK (entity_type IN (
                            'person', 'organization', 'address',
                            'office', 'electoral_division', 'contest',
                            'candidacy', 'officeholding', 'contact_point'
                        )),
        entity_id       UUID NOT NULL,
        source_record_id UUID NOT NULL REFERENCES core.source_record(id),
        extraction_role TEXT,
        confidence      REAL,
        extracted_fields JSONB,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS core.field_provenance (
        id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type     TEXT NOT NULL CHECK (entity_type IN (
                            'person', 'organization', 'address',
                            'office', 'electoral_division', 'contest',
                            'candidacy', 'officeholding', 'contact_point'
                        )),
        entity_id       UUID NOT NULL,
        field_name      TEXT NOT NULL,
        field_value     TEXT NOT NULL,
        source_record_id UUID NOT NULL REFERENCES core.source_record(id),
        first_seen      TIMESTAMPTZ NOT NULL,
        last_seen       TIMESTAMPTZ NOT NULL,
        is_current      BOOLEAN NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS core.match_decision (
        id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
        entity_id_a     UUID NOT NULL,
        entity_id_b     UUID NOT NULL,
        decision        TEXT NOT NULL CHECK (decision IN ('match', 'probable_match', 'possible_match', 'no_match')),
        confidence      REAL NOT NULL,
        decided_by      TEXT NOT NULL,
        decision_method TEXT NOT NULL,
        match_evidence  JSONB,
        decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        superseded_by   UUID,
        superseded_at   TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_ordered_pair CHECK (entity_id_a < entity_id_b)
    );

    CREATE TABLE IF NOT EXISTS core.entity_cluster (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type         TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
        canonical_entity_id UUID NOT NULL,
        cluster_confidence  REAL,
        member_count        INTEGER NOT NULL DEFAULT 1,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_cluster_id_type UNIQUE (id, entity_type)
    );

    CREATE TABLE IF NOT EXISTS core.cluster_member (
        id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        cluster_id      UUID NOT NULL,
        entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
        entity_id       UUID NOT NULL,
        is_canonical    BOOLEAN NOT NULL DEFAULT FALSE,
        merged_at       TIMESTAMPTZ,
        merged_by       TEXT,
        split_at        TIMESTAMPTZ,
        split_by        TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT fk_cluster_member_cluster
            FOREIGN KEY (cluster_id, entity_type)
            REFERENCES core.entity_cluster(id, entity_type)
    );

    CREATE TABLE IF NOT EXISTS core.manual_override (
        id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        match_decision_id   UUID REFERENCES core.match_decision(id),
        entity_type         TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
        entity_id_a         UUID NOT NULL,
        entity_id_b         UUID NOT NULL,
        override_decision   TEXT NOT NULL CHECK (override_decision IN ('confirmed_match', 'confirmed_non_match')),
        reason              TEXT,
        decided_by          TEXT NOT NULL,
        decided_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        superseded_by       UUID,
        superseded_at       TIMESTAMPTZ,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT chk_override_ordered CHECK (entity_id_a < entity_id_b)
    );

    CREATE TABLE IF NOT EXISTS core.splink_run (
        id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
        splink_version  TEXT NOT NULL,
        model_config    JSONB NOT NULL,
        input_record_count BIGINT,
        pairs_compared  BIGINT,
        matches_found   BIGINT,
        auto_merged     BIGINT,
        probable_matches BIGINT,
        possible_matches BIGINT,
        duration_seconds REAL,
        started_at      TIMESTAMPTZ NOT NULL,
        completed_at    TIMESTAMPTZ,
        status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
        error_message   TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
""")

_MINIMAL_CF_SQL = textwrap.dedent("""\
    CREATE SCHEMA IF NOT EXISTS cf;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;

    CREATE TABLE IF NOT EXISTS core.person (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        canonical_name TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS core.organization (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        canonical_name TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cf.committee (
        id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        fec_committee_id TEXT NOT NULL UNIQUE,
        name             TEXT NOT NULL,
        organization_id  UUID REFERENCES core.organization(id),
        source_record_id UUID REFERENCES core.source_record(id),
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cf.committee_summary (
        id                                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        committee_id                        UUID NOT NULL REFERENCES cf.committee(id),
        cycle                               INTEGER NOT NULL,
        coverage_start_date                 DATE,
        coverage_end_date                   DATE,
        derived_total_raised                NUMERIC(14,2),
        derived_total_spent                 NUMERIC(14,2),
        derived_net                         NUMERIC(14,2),
        derived_transaction_count           INTEGER,
        derived_cash_receipts_total         NUMERIC(14,2),
        derived_in_kind_receipts_total      NUMERIC(14,2),
        derived_loan_receipts_total         NUMERIC(14,2),
        derived_contribution_receipts_total NUMERIC(14,2),
        derived_jurisdiction                TEXT,
        derived_data_through                TIMESTAMPTZ,
        source_record_id                    UUID REFERENCES core.source_record(id),
        created_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cf.candidate (
        id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        fec_candidate_id         TEXT NOT NULL UNIQUE,
        name                     TEXT NOT NULL,
        person_id                UUID REFERENCES core.person(id),
        party                    TEXT,
        office                   TEXT NOT NULL CHECK (office IN ('H', 'S', 'P')),
        state                    TEXT,
        district                 TEXT,
        incumbent_challenge      TEXT,
        principal_committee_id   UUID REFERENCES cf.committee(id),
        total_receipts           NUMERIC(14,2),
        total_disbursements      NUMERIC(14,2),
        cash_on_hand             NUMERIC(14,2),
        summary_coverage_end_date DATE,
        source_record_id         UUID REFERENCES core.source_record(id),
        created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cf.transaction (
        id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        committee_id            UUID REFERENCES cf.committee(id),
        contributor_name_raw    TEXT,
        transaction_type        TEXT,
        contributor_entity_type TEXT,
        is_memo                 BOOLEAN,
        amendment_indicator     TEXT
    );
""")


# ---------------------------------------------------------------------------
# Baseline entries (frozen Stage 1 manifest, minus the ZCTA 07_14 line)
# ---------------------------------------------------------------------------

_BASELINE_ENTRIES = [
    "2026_04_30_person_bio_fields.sql",
    "2026_07_07_committee_summary.sql",
    "2026_07_07_transaction_entity_type.sql",
    "2026_07_07_zcta_district.sql",
    "2026_07_09_donor_search_index.sql",
    "2026_07_09_stage4_resume_checkpoint.sql",
    "2026_07_12_committee_summary_derived_aggregates.sql",
    "2026_07_12_person_money_query_indexes.sql",
    # 2026_07_14_zcta_district_boundary_year.sql intentionally ABSENT from
    # fixture baseline — it is the pending migration that should be applied.
]

_PENDING_FILENAMES = [
    "2026_07_13_entity_source_civic_types.sql",
    "2026_07_14_candidate_self_funding.sql",
    "2026_07_14_zcta_district_boundary_year.sql",
    "2026_07_18_committee_summary_top_lists.sql",
    "2026_07_19_committee_summary_filing_breakdown.sql",
    "2026_07_24_donor_search_committee_scope_index.sql",
    "2026_07_28_donor_identity_er_contract.sql",
    "2026_07_28_donor_identity_person_mapping.sql",
    "2026_07_31_refresh_run_failed_status.sql",
    "2026_08_01_donor_search_rollup.sql",
    "2026_08_02_donor_search_rollup_representative_id.sql",
    "2026_08_03_donor_search_rollup_identity_variants.sql",
    "2026_08_23_contribution_limit_rules.sql",
    "2026_08_23_refresh_run_running_status.sql",
    "2026_08_24_person_absorption.sql",
]

_DONOR_IDENTITY_MIGRATION = "2026_07_28_donor_identity_er_contract.sql"
_DONOR_CLUSTER_PERSON_MIGRATION = "2026_07_28_donor_identity_person_mapping.sql"
_CONTRIBUTION_LIMIT_RULES_MIGRATION = "2026_08_23_contribution_limit_rules.sql"
_PERSON_ABSORPTION_MIGRATION = "2026_08_24_person_absorption.sql"
_PERSON_ABSORPTION_COLUMNS = [
    ("absorbed_person_id", "uuid", "NO"),
    ("canonical_person_id", "uuid", "NO"),
    ("cluster_id", "uuid", "NO"),
    ("merged_by", "text", "NO"),
    ("absorbed_at", "timestamp with time zone", "NO"),
    ("absorbed_payload", "jsonb", "NO"),
]
_PERSON_ABSORPTION_INDEXES = [
    "idx_person_absorption_absorbed_at",
    "idx_person_absorption_canonical_person",
    "idx_person_absorption_cluster",
    "person_absorption_pkey",
]
_CONTRIBUTION_LIMIT_RULE_COLUMNS = [
    ("id", "uuid", "NO", "uuid_generate_v4()"),
    ("jurisdiction_fips", "text", "NO", None),
    ("donor_type", "text", "YES", None),
    ("recipient_type", "text", "YES", None),
    ("office_level", "text", "YES", None),
    ("election_type", "text", "YES", None),
    ("limit_status", "text", "NO", None),
    ("limit_amount", "integer", "YES", None),
    ("limit_basis", "text", "YES", None),
    ("source_citation", "text", "NO", None),
    ("effective_date", "date", "YES", None),
    ("sunset_date", "date", "YES", None),
    ("research_observed_date", "date", "YES", None),
    ("local_override_allowed", "boolean", "NO", "false"),
    ("note", "text", "YES", None),
    ("metadata", "jsonb", "NO", "'[]'::jsonb"),
    ("created_at", "timestamp with time zone", "NO", "now()"),
    ("updated_at", "timestamp with time zone", "NO", "now()"),
]
_CONTRIBUTION_LIMIT_RULE_IDENTITY_INDEX_TERMS = (
    "jurisdiction_fips",
    "(donor_type IS NULL)",
    "COALESCE(donor_type, '')",
    "(recipient_type IS NULL)",
    "COALESCE(recipient_type, '')",
    "(office_level IS NULL)",
    "COALESCE(office_level, '')",
    "(election_type IS NULL)",
    "COALESCE(election_type, '')",
    "(effective_date IS NULL)",
    "COALESCE(effective_date, DATE '0001-01-01')",
    "(sunset_date IS NULL)",
    "COALESCE(sunset_date, DATE '0001-01-01')",
)
# Pinned non-overlap EXCLUDE key: the four dimensions keyed by equality plus the
# effectivity period keyed by overlap. Pinning (not just cross-file equality) fails red
# even if a dimension were dropped from both owners in lockstep.
_CONTRIBUTION_LIMIT_RULE_EXCLUDE_TERMS = (
    "jurisdiction_fips WITH =",
    "(donor_type IS NULL) WITH =",
    "COALESCE(donor_type, '') WITH =",
    "(recipient_type IS NULL) WITH =",
    "COALESCE(recipient_type, '') WITH =",
    "(office_level IS NULL) WITH =",
    "COALESCE(office_level, '') WITH =",
    "(election_type IS NULL) WITH =",
    "COALESCE(election_type, '') WITH =",
    "daterange(effective_date, sunset_date, '[)') WITH &&",
)
_CONTRIBUTION_LIMIT_NON_OVERLAP_CONSTRAINT = "contribution_limit_rules_non_overlapping_periods"
_DONOR_IDENTITY_COLUMNS = [
    "id",
    "canonical_name",
    "contributor_name_raw",
    "contributor_employer",
    "contributor_occupation",
    "contributor_city",
    "contributor_state",
    "contributor_zip",
    "zip5",
    "transaction_count",
    "er_cluster_id",
    "er_confidence",
    "created_at",
    "updated_at",
]
_DONOR_ER_VIEW_COLUMNS = [
    "id",
    "canonical_name",
    "contributor_name_raw",
    "contributor_employer",
    "contributor_occupation",
    "contributor_city",
    "contributor_state",
    "contributor_zip",
    "zip5",
    "transaction_count",
]
_DONOR_IDENTITY_ENTITY_TYPE_TABLES = [
    "entity_source",
    "field_provenance",
    "match_decision",
    "entity_cluster",
    "cluster_member",
    "manual_override",
    "splink_run",
]


def _write_fixture_baseline(path: Path) -> None:
    lines = ["# FROZEN baseline — test fixture copy"]
    lines.extend(_BASELINE_ENTRIES)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_fixture_migrations_dir(target: Path, source_dir: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in _BASELINE_ENTRIES + _PENDING_FILENAMES:
        src = source_dir / name
        if src.exists():
            shutil.copy2(src, target / name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def disposable_db() -> str:
    db_name = _create_database()

    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute(_MINIMAL_CORE_SQL)
        conn.execute(_MINIMAL_CF_SQL)
        conn.execute(_OLD_ZCTA_DISTRICT_SQL)
    finally:
        conn.close()

    yield db_name

    _drop_database(db_name)


@pytest.fixture(scope="module")
def empty_disposable_db() -> str:
    db_name = _create_database()

    yield db_name

    _drop_database(db_name)


@pytest.fixture
def provenance_shape_db() -> str:
    """A database holding only the fresh-install shape of core.refresh_run.

    Kept separate from empty_disposable_db, whose tests depend on that database
    staying uninitialized.
    """
    db_name = _create_database()
    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute("CREATE SCHEMA core")
        conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        conn.execute(_refresh_run_ddl_from_provenance_sql())
    finally:
        conn.close()

    yield db_name

    _drop_database(db_name)


@pytest.fixture(scope="module")
def fixture_paths(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("migrations")
    baseline_path = base / "migrations_baseline.txt"
    migrations_dir = base / "migrations"
    _write_fixture_baseline(baseline_path)
    _build_fixture_migrations_dir(migrations_dir, REPO_ROOT / "core" / "schema" / "migrations")
    return {"baseline": baseline_path, "migrations_dir": migrations_dir}


def _run_main(
    db_name: str,
    fixture_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> int:
    import core.schema.apply_migrations as mod

    if monkeypatch is not None:
        monkeypatch.setattr(mod, "BASELINE_PATH", fixture_paths["baseline"])
        monkeypatch.setattr(mod, "MIGRATIONS_DIR", fixture_paths["migrations_dir"])

    env_patch = {
        "POSTGRES_HOST": _POSTGRES_HOST or "localhost",
        "POSTGRES_PORT": str(_POSTGRES_PORT),
        "POSTGRES_DB": db_name,
        "POSTGRES_USER": _POSTGRES_USER,
        "POSTGRES_PASSWORD": _POSTGRES_PASSWORD,
    }
    saved = {}
    for k, v in env_patch.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return mod.main()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _create_database() -> str:
    db_name = f"{_DB_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
    admin = _admin_connect()
    try:
        admin.execute(f"CREATE DATABASE {db_name}")
    finally:
        admin.close()
    return db_name


def _drop_database(db_name: str) -> None:
    admin = _admin_connect()
    try:
        admin.execute(
            f"""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
            """
        )
        admin.execute(f"DROP DATABASE IF EXISTS {db_name}")
    finally:
        admin.close()


# ---------------------------------------------------------------------------
# core.refresh_run insert helper
# ---------------------------------------------------------------------------
# The fixture core.refresh_run carries only the columns these tests exercise,
# but production (core/schema/provenance.sql) makes job_key, domain,
# jurisdiction, started_at and message NOT NULL with no default. Route every
# insert through one helper that names pull_status and completed_at explicitly
# so a rejection is provably the CHECK under test and never a NotNullViolation.

_TERMINAL_PULL_STATUSES = ("crashed", "empty", "degraded", "success", "failed")
_COMPLETED_AT = datetime(2026, 8, 23, 12, 5, tzinfo=timezone.utc)


def _insert_refresh_run(cur: psycopg.Cursor, *, pull_status: str, completed_at: datetime | None) -> None:
    cur.execute(
        "INSERT INTO core.refresh_run (pull_status, completed_at) VALUES (%s, %s)",
        (pull_status, completed_at),
    )


def _refresh_run_ddl_from_provenance_sql() -> str:
    """Extract the core.refresh_run CREATE TABLE block from provenance.sql.

    Lets a test stand up the fresh-database shape of one table without running
    the whole provenance schema and its dependencies.
    """
    sql = (REPO_ROOT / "core" / "schema" / "provenance.sql").read_text()
    start = sql.index("CREATE TABLE core.refresh_run")
    end = sql.index(");", start) + len(");")
    ddl = sql[start:end]
    assert "pull_status" in ddl and "completed_at" in ddl, ddl
    return ddl


def _refresh_run_check_constraints(conn: psycopg.Connection) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'core.refresh_run'::regclass
              AND contype = 'c'
            ORDER BY conname
            """
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def _refresh_run_completed_at_is_nullable(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'refresh_run'
              AND column_name = 'completed_at'
            """
        )
        return cur.fetchone()[0] == "YES"


def _column_names(conn: psycopg.Connection, *, table_schema: str, table_name: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_schema, table_name),
        )
        return [row[0] for row in cur.fetchall()]


def _entity_type_check_definitions(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rel.relname, pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = 'core'
              AND rel.relname = ANY(%s)
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) LIKE '%%entity_type%%'
            ORDER BY rel.relname
            """,
            (_DONOR_IDENTITY_ENTITY_TYPE_TABLES,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _assert_donor_identity_upgrade_contract(conn: psycopg.Connection) -> None:
    assert _column_names(conn, table_schema="core", table_name="donor_identity") == _DONOR_IDENTITY_COLUMNS
    assert _column_names(conn, table_schema="core", table_name="donor_er_view") == _DONOR_ER_VIEW_COLUMNS
    assert _column_names(conn, table_schema="core", table_name="donor_cluster_person") == [
        "cluster_id",
        "entity_type",
        "person_id",
        "created_at",
    ]

    definitions = _entity_type_check_definitions(conn)
    assert sorted(definitions) == sorted(_DONOR_IDENTITY_ENTITY_TYPE_TABLES)
    for table_name, definition in definitions.items():
        assert "'donor_identity'" in definition, f"{table_name} does not accept donor_identity: {definition}"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'core'
              AND tablename = 'donor_identity'
              AND indexname IN (
                  'idx_donor_identity_cluster',
                  'idx_donor_identity_name',
                  'idx_donor_identity_zip5'
              )
            ORDER BY indexname
            """
        )
        assert [row[0] for row in cur.fetchall()] == [
            "idx_donor_identity_cluster",
            "idx_donor_identity_name",
            "idx_donor_identity_zip5",
        ]

        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_proc p ON p.oid = t.tgfoid
                WHERE c.relnamespace = 'core'::regnamespace
                  AND c.relname = 'donor_identity'
                  AND p.proname = 'set_updated_at'
                  AND NOT t.tgisinternal
                  AND lower(pg_get_triggerdef(t.oid)) LIKE '%before update%'
                  AND pg_get_triggerdef(t.oid) LIKE '%core.set_updated_at%'
            )
            """
        )
        assert cur.fetchone()[0] is True


def _contribution_limit_rule_columns(conn: psycopg.Connection) -> list[tuple[str, str, str, str | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'cf'
              AND table_name = 'contribution_limit_rules'
            ORDER BY ordinal_position
            """
        )
        return cur.fetchall()


def _person_absorption_columns(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'person_absorption'
            ORDER BY ordinal_position
            """
        )
        return cur.fetchall()


def _person_absorption_constraints(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'core.person_absorption'::regclass
            ORDER BY conname
            """
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _person_absorption_index_names(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'core'
              AND tablename = 'person_absorption'
            ORDER BY indexname
            """
        )
        return [row[0] for row in cur.fetchall()]


def _assert_contribution_rule_insert_rejected(
    conn: psycopg.Connection,
    statement: str,
    constraint_name: str,
    params: tuple[object, ...] | None = None,
) -> None:
    conn.execute("SAVEPOINT contribution_rule_rejection")
    try:
        with pytest.raises(psycopg.errors.IntegrityError) as exc_info:
            conn.execute(statement, params)
        assert exc_info.value.diag.constraint_name == constraint_name
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT contribution_rule_rejection")
        conn.execute("RELEASE SAVEPOINT contribution_rule_rejection")


def _contribution_limit_rule_ddl_names(path: Path) -> set[str]:
    ddl = path.read_text(encoding="utf-8")
    return set(
        re.findall(
            r"\b(?:CONSTRAINT|CREATE UNIQUE INDEX(?: IF NOT EXISTS)?)\s+"
            r"((?:ck_|uq_)?contribution_limit_rules_[a-z_]+)",
            ddl,
        )
    )


def _contribution_limit_rule_table_body(path: Path) -> str:
    """Normalized CREATE TABLE body shared by the fresh and migration owners."""

    ddl = path.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TABLE(?: IF NOT EXISTS)? cf\.contribution_limit_rules \((.*?)\n\);",
        ddl,
        re.DOTALL,
    )
    assert match is not None, f"No contribution_limit_rules table found in {path}"
    return "\n".join(line.rstrip() for line in match.group(1).strip().splitlines())


def _contribution_limit_rule_identity_index_terms(path: Path) -> tuple[str, ...]:
    ddl = path.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE UNIQUE INDEX(?: IF NOT EXISTS)? uq_contribution_limit_rules_identity\s+"
        r"ON cf\.contribution_limit_rules \((.*?)\);",
        ddl,
        re.DOTALL,
    )
    assert match is not None
    return tuple(" ".join(line.strip().rstrip(",").split()) for line in match.group(1).splitlines() if line.strip())


def _contribution_limit_rule_exclude_terms(path: Path) -> tuple[str, ...]:
    """Normalized term list from the non-overlap EXCLUDE key in a schema-owner file.

    Compared across the two owners so dropping a dimension from one EXCLUDE key — which
    leaves the constraint name unchanged and so is invisible to the name-set drift check —
    fails red. The closing ``)`` of the EXCLUDE sits on its own line, while daterange's own
    parens stay inline, so a non-greedy match up to a standalone paren line captures the
    whole key without tripping on the inner parens.
    """

    ddl = path.read_text(encoding="utf-8")
    match = re.search(
        r"EXCLUDE USING gist \((.*?)\n\s*\)\s*;",
        ddl,
        re.DOTALL,
    )
    assert match is not None, f"No EXCLUDE key found in {path}"
    return tuple(" ".join(line.strip().rstrip(",").split()) for line in match.group(1).splitlines() if line.strip())


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestApplyMigrations:
    """KAT: baseline adoption + selective delta application on the old prod shape."""

    def test_main_returns_zero(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _run_main(disposable_db, fixture_paths, monkeypatch)
        assert result == 0

    def test_contribution_limit_rules_migration_is_pending_delta(
        self,
        fixture_paths: dict[str, Path],
    ) -> None:
        assert _CONTRIBUTION_LIMIT_RULES_MIGRATION in _PENDING_FILENAMES
        assert _CONTRIBUTION_LIMIT_RULES_MIGRATION not in _BASELINE_ENTRIES
        assert (fixture_paths["migrations_dir"] / _CONTRIBUTION_LIMIT_RULES_MIGRATION).is_file()

    def test_person_absorption_migration_is_pending_delta(
        self,
        fixture_paths: dict[str, Path],
    ) -> None:
        assert _PERSON_ABSORPTION_MIGRATION in _PENDING_FILENAMES
        assert _PERSON_ABSORPTION_MIGRATION not in _BASELINE_ENTRIES
        assert (fixture_paths["migrations_dir"] / _PERSON_ABSORPTION_MIGRATION).is_file()

    def test_person_absorption_pending_delta_schema_contract(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            assert _person_absorption_columns(conn) == _PERSON_ABSORPTION_COLUMNS
            constraints = _person_absorption_constraints(conn)
            assert constraints["person_absorption_pkey"] == "PRIMARY KEY (absorbed_person_id)"
            assert constraints["person_absorption_canonical_person_id_fkey"] == (
                "FOREIGN KEY (canonical_person_id) REFERENCES core.person(id)"
            )
            assert constraints["person_absorption_cluster_id_fkey"] == (
                "FOREIGN KEY (cluster_id) REFERENCES core.entity_cluster(id)"
            )
            assert not any(
                "absorbed_person_id" in definition and "core.person" in definition
                for definition in constraints.values()
            )
            assert _person_absorption_index_names(conn) == _PERSON_ABSORPTION_INDEXES
        finally:
            conn.close()

    def test_contribution_limit_rules_migrated_schema_contract(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            assert _contribution_limit_rule_columns(conn) == _CONTRIBUTION_LIMIT_RULE_COLUMNS
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'cf.contribution_limit_rules'::regclass
                      AND contype = 'c'
                    """
                )
                migration_path = REPO_ROOT / "core" / "schema" / "migrations" / _CONTRIBUTION_LIMIT_RULES_MIGRATION
                expected_checks = {
                    name for name in _contribution_limit_rule_ddl_names(migration_path) if name.startswith("ck_")
                }
                assert {row[0] for row in cur.fetchall()} == expected_checks
                cur.execute(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'cf' AND indexname = 'uq_contribution_limit_rules_identity'"
                )
                index_definition = cur.fetchone()[0].lower()
                for dimension in ("donor_type", "recipient_type", "office_level", "election_type"):
                    assert f"({dimension} is null)" in index_definition
                    assert f"coalesce({dimension}, ''::text)" in index_definition
                for date_column in ("effective_date", "sunset_date"):
                    assert f"({date_column} is null)" in index_definition
                    assert f"coalesce({date_column}, '0001-01-01'::date)" in index_definition
                cur.execute(
                    """
                    SELECT COUNT(*) FROM pg_trigger
                    WHERE tgrelid = 'cf.contribution_limit_rules'::regclass
                      AND tgname = 'trg_contribution_limit_rules_updated_at'
                      AND NOT tgisinternal
                    """
                )
                assert cur.fetchone()[0] == 1
                cur.execute(
                    """
                    SELECT COUNT(*) FROM pg_constraint
                    WHERE conrelid = 'cf.contribution_limit_rules'::regclass
                      AND contype = 'x'
                      AND conname = %s
                    """,
                    (_CONTRIBUTION_LIMIT_NON_OVERLAP_CONSTRAINT,),
                )
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT COUNT(*) FROM cf.contribution_limit_rules")
                assert cur.fetchone()[0] == 0
        finally:
            conn.close()

    def test_contribution_limit_rules_migrated_status_and_date_behavior(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            rejected = [
                (
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, limit_basis, source_citation, effective_date) "
                    "VALUES ('missing-amount', 'numeric', 'per_election', 'Authority', '2025-01-01')",
                    "ck_contribution_limit_rules_numeric_fields",
                ),
                (
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, limit_amount, source_citation, effective_date) "
                    "VALUES ('prohibited-amount', 'prohibited', 1, 'Authority', '2025-01-01')",
                    "ck_contribution_limit_rules_non_numeric_fields",
                ),
                (
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, "
                    "effective_date, research_observed_date) VALUES "
                    "('known-research-date', 'numeric', 1, 'per_cycle', 'Authority', "
                    "'2025-01-01', '2026-08-22')",
                    "ck_contribution_limit_rules_numeric_fields",
                ),
                (
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, source_citation, research_observed_date, note, effective_date) "
                    "VALUES ('unknown-effective', 'unknown', 'Authority', '2026-08-22', 'Open', '2025-01-01')",
                    "ck_contribution_limit_rules_unknown_fields",
                ),
                (
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, source_citation, research_observed_date) "
                    "VALUES ('unknown-note', 'unknown', 'Authority', '2026-08-22')",
                    "ck_contribution_limit_rules_unknown_fields",
                ),
                (
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, "
                    "effective_date, sunset_date) VALUES "
                    "('reversed-dates', 'numeric', 1, 'per_cycle', 'Authority', '2025-02-01', '2025-01-01')",
                    "ck_contribution_limit_rules_date_order",
                ),
            ]
            for statement, constraint_name in rejected:
                _assert_contribution_rule_insert_rejected(conn, statement, constraint_name)

            row = conn.execute(
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, source_citation, research_observed_date, note)
                VALUES ('valid-unknown', 'unknown', 'Authority', '2026-08-22', 'Research remains open')
                RETURNING effective_date, sunset_date, limit_amount, limit_basis
                """
            ).fetchone()
            assert row == (None, None, None, None)
            conn.rollback()
        finally:
            conn.close()

    def test_contribution_limit_rules_migrated_metadata_and_identity_behavior(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            for metadata in (
                '[{"description":"Cap","source_citation":"Law","extra":true}]',
                '[{"description":"Cap"}]',
                # Nested array item: rejected by the strict-mode scan (lax mode would unwrap it).
                '[[{"description":"Cap","source_citation":"Law"}]]',
                # U+00A0-only strings are blank to config_schema.NonBlankText (str.strip).
                '[{"description":"\\u00a0","source_citation":"Law"}]',
                '[{"description":"Cap","source_citation":"\\u00a0"}]',
            ):
                _assert_contribution_rule_insert_rejected(
                    conn,
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, "
                    "effective_date, metadata) VALUES "
                    f"('invalid-metadata', 'numeric', 1, 'per_cycle', 'Authority', '2025-01-01', '{metadata}')",
                    "ck_contribution_limit_rules_metadata_shape",
                )

            _assert_contribution_rule_insert_rejected(
                conn,
                "INSERT INTO cf.contribution_limit_rules "
                "(jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, effective_date) "
                "VALUES ('blank-citation', 'numeric', 1, 'per_cycle', E'\\u00a0', '2025-01-01')",
                "ck_contribution_limit_rules_citation_nonblank",
            )

            row = conn.execute(
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation,
                     effective_date, metadata)
                VALUES ('valid-rule', 'numeric', 100, 'per_election', 'Authority', '2025-01-01',
                        '[{"description":"Cap","source_citation":"Law"}]')
                RETURNING local_override_allowed, metadata
                """
            ).fetchone()
            assert row == (False, [{"description": "Cap", "source_citation": "Law"}])
            conn.rollback()

            conn.execute(
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, effective_date)
                VALUES ('duplicate-rule', 'numeric', 100, 'per_election', 'Authority', '2025-01-01')
                """
            )
            _assert_contribution_rule_insert_rejected(
                conn,
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, effective_date)
                VALUES ('duplicate-rule', 'numeric', 200, 'per_election', 'Other authority', '2025-01-01')
                """,
                "uq_contribution_limit_rules_identity",
            )
        finally:
            conn.close()

    def test_contribution_limit_rules_migrated_identity_preserves_successive_effective_periods(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            conn.execute(
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation,
                     effective_date, sunset_date)
                VALUES ('temporal-rule', 'numeric', 100, 'per_election', 'Authority',
                        '2023-01-01', '2025-01-01')
                """
            )
            conn.execute(
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation,
                     effective_date)
                VALUES ('temporal-rule', 'numeric', 200, 'per_election', 'Authority',
                        '2025-01-01')
                """
            )
            count = conn.execute(
                """
                SELECT COUNT(*) FROM cf.contribution_limit_rules
                WHERE jurisdiction_fips = 'temporal-rule'
                """
            ).fetchone()[0]
            assert count == 2

            _assert_contribution_rule_insert_rejected(
                conn,
                """
                INSERT INTO cf.contribution_limit_rules
                    (jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation,
                     effective_date, sunset_date)
                VALUES ('temporal-rule', 'numeric', 300, 'per_election', 'Different authority',
                        '2023-01-01', '2025-01-01')
                """,
                "uq_contribution_limit_rules_identity",
            )
            conn.rollback()
        finally:
            conn.close()

    def test_contribution_limit_rules_migrated_rejects_overlapping_periods(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            base = (
                "INSERT INTO cf.contribution_limit_rules "
                "(jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, "
                "effective_date, sunset_date) VALUES "
            )
            # Two open-ended (sunset NULL) rules for one tuple.
            conn.execute(base + "('open', 'numeric', 1, 'per_election', 'A', '2023-01-01', NULL)")
            _assert_contribution_rule_insert_rejected(
                conn,
                base + "('open', 'numeric', 2, 'per_election', 'A', '2024-01-01', NULL)",
                _CONTRIBUTION_LIMIT_NON_OVERLAP_CONSTRAINT,
            )
            conn.rollback()

            # Two overlapping bounded periods.
            conn.execute(base + "('bounded', 'numeric', 1, 'per_election', 'A', '2023-01-01', '2025-12-31')")
            _assert_contribution_rule_insert_rejected(
                conn,
                base + "('bounded', 'numeric', 2, 'per_election', 'A', '2024-01-01', '2026-12-31')",
                _CONTRIBUTION_LIMIT_NON_OVERLAP_CONSTRAINT,
            )
            conn.rollback()

            # An unknown row (NULL dates -> unbounded) coexisting with a known rule.
            conn.execute(base + "('unk', 'numeric', 1, 'per_election', 'A', '2023-01-01', NULL)")
            _assert_contribution_rule_insert_rejected(
                conn,
                "INSERT INTO cf.contribution_limit_rules "
                "(jurisdiction_fips, limit_status, source_citation, research_observed_date, note) "
                "VALUES ('unk', 'unknown', 'A', '2026-08-22', 'open')",
                _CONTRIBUTION_LIMIT_NON_OVERLAP_CONSTRAINT,
            )
            conn.rollback()

            # Two rows sharing a period but differing in exactly one non-NULL dimension are
            # distinct tuples the EXCLUDE must admit. A dimension dropped from the key would
            # collide these instead — the all-NULL-dimension cases above cannot detect that.
            for dimension, value in (
                ("donor_type", "pac"),
                ("recipient_type", "candidate_committee"),
                ("office_level", "governor"),
                ("election_type", "primary"),
            ):
                conn.execute(
                    "INSERT INTO cf.contribution_limit_rules "
                    "(jurisdiction_fips, limit_status, limit_amount, limit_basis, source_citation, "
                    "effective_date, sunset_date) VALUES "
                    "('accept-dim', 'numeric', 1, 'per_election', 'A', '2023-01-01', '2025-12-31')"
                )
                conn.execute(
                    "INSERT INTO cf.contribution_limit_rules "
                    f"(jurisdiction_fips, limit_status, limit_amount, limit_basis, {dimension}, "
                    "source_citation, effective_date, sunset_date) VALUES "
                    f"('accept-dim', 'numeric', 1, 'per_election', '{value}', 'A', "
                    "'2023-01-01', '2025-12-31')"
                )
                count = conn.execute(
                    "SELECT COUNT(*) FROM cf.contribution_limit_rules WHERE jurisdiction_fips = 'accept-dim'"
                ).fetchone()[0]
                assert count == 2, dimension
                conn.rollback()
        finally:
            conn.close()

    def test_contribution_limit_rule_schema_owners_do_not_drift(self) -> None:
        migration_path = REPO_ROOT / "core" / "schema" / "migrations" / _CONTRIBUTION_LIMIT_RULES_MIGRATION
        fresh_schema_path = REPO_ROOT / "domains" / "campaign_finance" / "schema" / "tables.sql"
        migration_names = _contribution_limit_rule_ddl_names(migration_path)
        fresh_schema_names = _contribution_limit_rule_ddl_names(fresh_schema_path)
        assert migration_names == fresh_schema_names
        # The table body owns the ordered columns, defaults, and every CHECK body.
        # Compare it whole so matching names cannot conceal divergent enforcement.
        assert _contribution_limit_rule_table_body(migration_path) == _contribution_limit_rule_table_body(
            fresh_schema_path
        )
        assert _contribution_limit_rule_identity_index_terms(
            migration_path
        ) == _contribution_limit_rule_identity_index_terms(fresh_schema_path)
        assert (
            _contribution_limit_rule_identity_index_terms(migration_path)
            == _CONTRIBUTION_LIMIT_RULE_IDENTITY_INDEX_TERMS
        )
        # Constraint names alone cannot catch a dimension dropped from one EXCLUDE key
        # (the name is unchanged), so compare the key body between the two owners too.
        migration_exclude = _contribution_limit_rule_exclude_terms(migration_path)
        assert migration_exclude == _contribution_limit_rule_exclude_terms(fresh_schema_path)
        assert migration_exclude == _CONTRIBUTION_LIMIT_RULE_EXCLUDE_TERMS

    def test_adopted_baseline_not_executed(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT filename FROM core.schema_migrations ORDER BY filename")
                ledger_rows = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

        for entry in _BASELINE_ENTRIES:
            assert entry in ledger_rows, f"Adopted baseline entry missing: {entry}"
        for pending in _PENDING_FILENAMES:
            assert pending in ledger_rows, f"Applied pending entry missing: {pending}"

        expected = sorted(_BASELINE_ENTRIES + _PENDING_FILENAMES)
        assert ledger_rows == expected

    def test_refresh_run_failed_status_migration_preserves_closed_status_set(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                for status in _TERMINAL_PULL_STATUSES:
                    _insert_refresh_run(cur, pull_status=status, completed_at=_COMPLETED_AT)
                    conn.rollback()

                with pytest.raises(psycopg.errors.CheckViolation):
                    _insert_refresh_run(cur, pull_status="unknown", completed_at=_COMPLETED_AT)
                conn.rollback()
        finally:
            conn.close()

    def test_refresh_run_running_status_migration_accepts_in_flight_attempt(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 'running' attempt with no completed_at must be storable."""
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                _insert_refresh_run(cur, pull_status="running", completed_at=None)
                cur.execute("SELECT pull_status, completed_at FROM core.refresh_run WHERE pull_status = 'running'")
                assert cur.fetchall() == [("running", None)]
                conn.rollback()
        finally:
            conn.close()

    def test_refresh_run_running_status_migration_enforces_paired_invariant(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """running <=> completed_at IS NULL, for every status in the closed set."""
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                with pytest.raises(psycopg.errors.CheckViolation):
                    _insert_refresh_run(cur, pull_status="running", completed_at=_COMPLETED_AT)
                conn.rollback()

                for status in _TERMINAL_PULL_STATUSES:
                    with pytest.raises(psycopg.errors.CheckViolation):
                        _insert_refresh_run(cur, pull_status=status, completed_at=None)
                    conn.rollback()
        finally:
            conn.close()

    def test_refresh_run_migrated_shape_matches_provenance_sql(
        self,
        disposable_db: str,
        provenance_shape_db: str,
        fixture_paths: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A migrated core.refresh_run must constrain exactly what a fresh one does.

        provenance.sql builds new databases and the migrations rebuild existing
        ones; if the two drift, a check that holds in dev silently does not hold
        in production.
        """
        _run_main(disposable_db, fixture_paths, monkeypatch)
        migrated = _connect_to(disposable_db)
        fresh = _connect_to(provenance_shape_db)
        try:
            assert _refresh_run_check_constraints(migrated) == _refresh_run_check_constraints(fresh)
            assert _refresh_run_completed_at_is_nullable(migrated)
            assert _refresh_run_completed_at_is_nullable(fresh)
        finally:
            fresh.close()
            migrated.close()

    def test_zcta_07_07_not_reexecuted(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The retro-edited 2026_07_07_zcta_district.sql must be adopted, not re-run.

        If it were re-executed it would try to create a table that already exists
        but with a different PK shape, or the old single-column indexes would
        still be present. The old zcta_district row must survive.
        """
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM civic.zcta_district WHERE zcta5 = '27514'")
                assert cur.fetchone()[0] == 1, "Pre-existing ZCTA row must survive adoption"
        finally:
            conn.close()

    def test_entity_source_civic_types_applied(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO core.source_record (id) VALUES (uuid_generate_v4()) RETURNING id")
                sr_id = cur.fetchone()[0]
                conn.commit()

                for new_type in ("election", "filing_deadline", "reporting_period"):
                    cur.execute(
                        """
                        INSERT INTO core.entity_source (entity_type, entity_id, source_record_id)
                        VALUES (%s, uuid_generate_v4(), %s)
                        """,
                        (new_type, sr_id),
                    )
                    conn.rollback()

                    cur.execute(
                        """
                        INSERT INTO core.field_provenance
                            (entity_type, entity_id, field_name, field_value,
                             source_record_id, first_seen, last_seen)
                        VALUES (%s, uuid_generate_v4(), 'test', 'val', %s, NOW(), NOW())
                        """,
                        (new_type, sr_id),
                    )
                    conn.rollback()
        finally:
            conn.close()

    def test_candidate_self_funding_columns_exist(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'cf' AND table_name = 'candidate'
                      AND column_name IN ('candidate_contrib', 'candidate_loans', 'candidate_loan_repay')
                    ORDER BY column_name
                    """
                )
                cols = [r[0] for r in cur.fetchall()]
                assert cols == ["candidate_contrib", "candidate_loan_repay", "candidate_loans"]
        finally:
            conn.close()

    def test_zcta_boundary_year_schema(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, is_nullable, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'civic' AND table_name = 'zcta_district'
                      AND column_name = 'boundary_year'
                    """
                )
                row = cur.fetchone()
                assert row is not None, "boundary_year column must exist"
                assert row[1] == "NO", "boundary_year must be NOT NULL"

                cur.execute(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = 'civic.zcta_district'::regclass AND i.indisprimary
                    ORDER BY a.attnum
                    """
                )
                pk_cols = [r[0] for r in cur.fetchall()]
                assert pk_cols == ["zcta5", "boundary_year"]

                cur.execute(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'civic' AND tablename = 'zcta_district'
                      AND indexname IN (
                          'idx_zcta_district_cd_geoid_boundary_year',
                          'idx_zcta_district_state_fips_boundary_year'
                      )
                    ORDER BY indexname
                    """
                )
                composite_indexes = [r[0] for r in cur.fetchall()]
                assert composite_indexes == [
                    "idx_zcta_district_cd_geoid_boundary_year",
                    "idx_zcta_district_state_fips_boundary_year",
                ]

                cur.execute(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'civic' AND tablename = 'zcta_district'
                      AND indexname IN ('idx_zcta_district_cd_geoid', 'idx_zcta_district_state_fips')
                    """
                )
                old_indexes = cur.fetchall()
                assert old_indexes == [], "Old single-column indexes must be dropped"

                cur.execute("SELECT boundary_year FROM civic.zcta_district WHERE zcta5 = '27514'")
                row = cur.fetchone()
                assert row is not None and row[0] == 2022, "Existing row must get boundary_year=2022"
        finally:
            conn.close()

    def test_committee_summary_top_list_columns_exist(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'cf'
                      AND table_name = 'committee_summary'
                      AND column_name IN (
                          'derived_top_donors',
                          'derived_top_vendors',
                          'derived_spend_categories',
                          'derived_filing_breakdown'
                      )
                    ORDER BY column_name
                    """
                )
                cols = cur.fetchall()

        finally:
            conn.close()

        assert cols == [
            ("derived_filing_breakdown", "jsonb", "YES"),
            ("derived_spend_categories", "jsonb", "YES"),
            ("derived_top_donors", "jsonb", "YES"),
            ("derived_top_vendors", "jsonb", "YES"),
        ]

    def test_donor_identity_migration_is_pending_delta(self, fixture_paths: dict[str, Path]) -> None:
        assert _DONOR_IDENTITY_MIGRATION in _PENDING_FILENAMES
        assert _DONOR_IDENTITY_MIGRATION not in _BASELINE_ENTRIES
        assert (fixture_paths["migrations_dir"] / _DONOR_IDENTITY_MIGRATION).is_file()

    def test_donor_cluster_person_mapping_migration_is_pending_delta(
        self,
        fixture_paths: dict[str, Path],
    ) -> None:
        assert _DONOR_CLUSTER_PERSON_MIGRATION in _PENDING_FILENAMES
        assert _DONOR_CLUSTER_PERSON_MIGRATION not in _BASELINE_ENTRIES
        assert (fixture_paths["migrations_dir"] / _DONOR_CLUSTER_PERSON_MIGRATION).is_file()

    def test_donor_identity_upgrade_schema_contract(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            _assert_donor_identity_upgrade_contract(conn)
        finally:
            conn.close()

    def test_donor_identity_entity_type_is_accepted_by_upgraded_constraints(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        donor_id_a = "00000000-0000-0000-0000-000000000001"
        donor_id_b = "00000000-0000-0000-0000-000000000002"
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO core.source_record DEFAULT VALUES RETURNING id")
                source_record_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO core.donor_identity
                        (id, canonical_name, contributor_name_raw, transaction_count)
                    VALUES
                        (%s, 'DOE, JANE', 'Doe, Jane', 1),
                        (%s, 'DOE, JANE', 'DOE JANE', 1)
                    """,
                    (donor_id_a, donor_id_b),
                )
                cur.execute(
                    """
                    INSERT INTO core.entity_source (entity_type, entity_id, source_record_id)
                    VALUES ('donor_identity', %s, %s)
                    """,
                    (donor_id_a, source_record_id),
                )
                cur.execute(
                    """
                    INSERT INTO core.field_provenance
                        (entity_type, entity_id, field_name, field_value,
                         source_record_id, first_seen, last_seen)
                    VALUES
                        ('donor_identity', %s, 'canonical_name', 'DOE, JANE',
                         %s, NOW(), NOW())
                    """,
                    (donor_id_a, source_record_id),
                )
                cur.execute(
                    """
                    INSERT INTO core.match_decision
                        (entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by, decision_method)
                    VALUES ('donor_identity', %s, %s, 'match', 0.99, 'test', 'deterministic')
                    """,
                    (donor_id_a, donor_id_b),
                )
                cur.execute(
                    """
                    INSERT INTO core.entity_cluster
                        (entity_type, canonical_entity_id, cluster_confidence, member_count)
                    VALUES ('donor_identity', %s, 0.99, 1)
                    RETURNING id
                    """,
                    (donor_id_a,),
                )
                cluster_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO core.cluster_member (cluster_id, entity_type, entity_id, is_canonical)
                    VALUES (%s, 'donor_identity', %s, TRUE)
                    """,
                    (cluster_id, donor_id_a),
                )
                cur.execute(
                    """
                    INSERT INTO core.manual_override
                        (entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by)
                    VALUES (%s, %s, %s, 'confirmed_match', 'same donor tuple', 'test')
                    """,
                    ("donor_identity", donor_id_a, donor_id_b),
                )
                cur.execute(
                    """
                    INSERT INTO core.splink_run
                        (entity_type, splink_version, model_config, started_at, status)
                    VALUES ('donor_identity', 'test', '{}'::jsonb, NOW(), 'completed')
                    """
                )
                conn.commit()
        finally:
            conn.close()

    def test_second_run_is_noop(
        self, disposable_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _run_main(disposable_db, fixture_paths, monkeypatch)
        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT filename, applied_at FROM core.schema_migrations ORDER BY filename")
                before = cur.fetchall()
        finally:
            conn.close()

        result = _run_main(disposable_db, fixture_paths, monkeypatch)
        assert result == 0

        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT filename, applied_at FROM core.schema_migrations ORDER BY filename")
                after = cur.fetchall()
        finally:
            conn.close()

        assert before == after


# ---------------------------------------------------------------------------
# Fail-closed tests
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Failure-mode tests: empty DB, bad baseline, CONCURRENTLY, rollback."""

    def test_admin_connect_fails_non_migration_port_when_db_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.modules[__name__], "_POSTGRES_PORT", 5485)
        monkeypatch.setenv("CIVIBUS_REQUIRE_DB", "1")

        # The approved set is `_SAFE_PORTS`, not the single Stage 1 port, so the
        # refusal names the port that was rejected rather than the one allowed.
        with pytest.raises(pytest.fail.Exception, match="POSTGRES_PORT=5485 is not an approved safe-local test port"):
            _admin_connect()

    def test_empty_db_no_sentinel_returns_nonzero(
        self,
        empty_disposable_db: str,
        fixture_paths: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        result = _run_main(empty_disposable_db, fixture_paths, monkeypatch)
        assert result != 0

    def test_duplicate_baseline_entry_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_name = f"{_DB_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        admin = _admin_connect()
        try:
            admin.execute(f"CREATE DATABASE {db_name}")
        finally:
            admin.close()

        try:
            conn = _connect_to(db_name)
            try:
                conn.autocommit = True
                conn.execute(_MINIMAL_CORE_SQL)
                conn.execute(_MINIMAL_CF_SQL)
            finally:
                conn.close()

            import core.schema.apply_migrations as mod

            bad_baseline = tmp_path / "bad_baseline.txt"
            bad_baseline.write_text(
                "2026_07_07_zcta_district.sql\n2026_07_07_zcta_district.sql\n",
                encoding="utf-8",
            )
            migrations_dir = tmp_path / "migrations"
            migrations_dir.mkdir()
            src = REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_07_zcta_district.sql"
            shutil.copy2(src, migrations_dir / "2026_07_07_zcta_district.sql")

            monkeypatch.setattr(mod, "BASELINE_PATH", bad_baseline)
            monkeypatch.setattr(mod, "MIGRATIONS_DIR", migrations_dir)

            env_patch = {
                "POSTGRES_HOST": _POSTGRES_HOST or "localhost",
                "POSTGRES_PORT": str(_POSTGRES_PORT),
                "POSTGRES_DB": db_name,
                "POSTGRES_USER": _POSTGRES_USER,
                "POSTGRES_PASSWORD": _POSTGRES_PASSWORD,
            }
            saved = {}
            for k, v in env_patch.items():
                saved[k] = os.environ.get(k)
                os.environ[k] = v
            try:
                result = mod.main()
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            assert result != 0
        finally:
            admin = _admin_connect()
            try:
                admin.execute(
                    f"""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
                    """
                )
                admin.execute(f"DROP DATABASE IF EXISTS {db_name}")
            finally:
                admin.close()

    def test_concurrently_refused(self, disposable_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import core.schema.apply_migrations as mod

        baseline = tmp_path / "baseline.txt"
        baseline.write_text("", encoding="utf-8")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        bad_migration = migrations_dir / "9999_bad.sql"
        bad_migration.write_text(
            "CREATE INDEX CONCURRENTLY idx_foo ON core.source_record (id);",
            encoding="utf-8",
        )

        monkeypatch.setattr(mod, "BASELINE_PATH", baseline)
        monkeypatch.setattr(mod, "MIGRATIONS_DIR", migrations_dir)

        env_patch = {
            "POSTGRES_HOST": _POSTGRES_HOST or "localhost",
            "POSTGRES_PORT": str(_POSTGRES_PORT),
            "POSTGRES_DB": disposable_db,
            "POSTGRES_USER": _POSTGRES_USER,
            "POSTGRES_PASSWORD": _POSTGRES_PASSWORD,
        }
        saved = {}
        for k, v in env_patch.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        try:
            result = mod.main()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        assert result != 0

        conn = _connect_to(disposable_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM core.schema_migrations WHERE filename = '9999_bad.sql'")
                assert cur.fetchone()[0] == 0, "CONCURRENTLY migration must not be recorded"
        finally:
            conn.close()

    def test_failed_migration_rolls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_name = f"{_DB_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        admin = _admin_connect()
        try:
            admin.execute(f"CREATE DATABASE {db_name}")
        finally:
            admin.close()

        try:
            conn = _connect_to(db_name)
            try:
                conn.autocommit = True
                conn.execute(_MINIMAL_CORE_SQL)
                conn.execute(_MINIMAL_CF_SQL)
            finally:
                conn.close()

            import core.schema.apply_migrations as mod

            baseline = tmp_path / "baseline.txt"
            baseline.write_text("", encoding="utf-8")
            migrations_dir = tmp_path / "migrations"
            migrations_dir.mkdir()
            failing_migration = migrations_dir / "9999_failing.sql"
            failing_migration.write_text(
                textwrap.dedent("""\
                    CREATE TABLE core.test_rollback_proof (id SERIAL PRIMARY KEY);
                    SELECT 1/0;
                """),
                encoding="utf-8",
            )

            monkeypatch.setattr(mod, "BASELINE_PATH", baseline)
            monkeypatch.setattr(mod, "MIGRATIONS_DIR", migrations_dir)

            env_patch = {
                "POSTGRES_HOST": _POSTGRES_HOST or "localhost",
                "POSTGRES_PORT": str(_POSTGRES_PORT),
                "POSTGRES_DB": db_name,
                "POSTGRES_USER": _POSTGRES_USER,
                "POSTGRES_PASSWORD": _POSTGRES_PASSWORD,
            }
            saved = {}
            for k, v in env_patch.items():
                saved[k] = os.environ.get(k)
                os.environ[k] = v
            try:
                result = mod.main()
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            assert result != 0

            conn = _connect_to(db_name)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('core.test_rollback_proof') IS NOT NULL")
                    assert cur.fetchone()[0] is False, "DDL from failed migration must roll back"
                    cur.execute("SELECT to_regclass('core.schema_migrations') IS NOT NULL")
                    has_ledger = cur.fetchone()[0]
                    if has_ledger:
                        cur.execute("SELECT COUNT(*) FROM core.schema_migrations WHERE filename = '9999_failing.sql'")
                        assert cur.fetchone()[0] == 0
            finally:
                conn.close()
        finally:
            admin = _admin_connect()
            try:
                admin.execute(
                    f"""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
                    """
                )
                admin.execute(f"DROP DATABASE IF EXISTS {db_name}")
            finally:
                admin.close()


class TestEntrypoint:
    """Verify python -m core.schema.apply_migrations propagates exit status."""

    def test_module_entrypoint_exit_code(self, empty_disposable_db: str, fixture_paths: dict[str, Path]) -> None:
        env = os.environ.copy()
        env.update(
            {
                "POSTGRES_HOST": _POSTGRES_HOST or "localhost",
                "POSTGRES_PORT": str(_POSTGRES_PORT),
                "POSTGRES_DB": empty_disposable_db,
                "POSTGRES_USER": _POSTGRES_USER,
                "POSTGRES_PASSWORD": _POSTGRES_PASSWORD,
            }
        )
        result = subprocess.run(
            [sys.executable, "-m", "core.schema.apply_migrations"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=30,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for empty DB, got {result.returncode}. stderr: {result.stderr}"
        )
