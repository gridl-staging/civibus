"""KAT for the ledger-based migration runner.

Recreates the old production zcta_district shape (single-column PK, no
boundary_year) plus minimal dependency tables, then proves apply_migrations
adopts the frozen baseline, skips the retro-edited 2026_07_07_zcta_district.sql,
and applies only the three pending deltas.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
_POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5475"))
_POSTGRES_USER = os.environ.get("POSTGRES_USER", "civibus")
_POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "civibus_dev")
_DB_NAME_PREFIX = "test_migrations_"
_SAFE_HOSTS = {None, "", "localhost", "127.0.0.1"}


def _skip_or_fail(message: str) -> None:
    if os.environ.get("CIVIBUS_REQUIRE_DB") == "1":
        pytest.fail(message)
    pytest.skip(message)


def _admin_connect() -> psycopg.Connection:
    raw_host = os.environ.get("POSTGRES_HOST")
    if raw_host not in _SAFE_HOSTS:
        _skip_or_fail(f"POSTGRES_HOST={raw_host} is not a safe local host for destructive tests")
    if _POSTGRES_PORT != 5475:
        _skip_or_fail(f"POSTGRES_PORT={_POSTGRES_PORT} is not the Stage 1 safe-local test port 5475")

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
        first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        is_current      BOOLEAN NOT NULL DEFAULT TRUE,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
""")

_MINIMAL_CF_SQL = textwrap.dedent("""\
    CREATE SCHEMA IF NOT EXISTS cf;

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
    db_name = f"{_DB_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
    admin = _admin_connect()
    try:
        admin.execute(f"CREATE DATABASE {db_name}")
    finally:
        admin.close()

    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute(_MINIMAL_CORE_SQL)
        conn.execute(_MINIMAL_CF_SQL)
        conn.execute(_OLD_ZCTA_DISTRICT_SQL)
    finally:
        conn.close()

    yield db_name

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


@pytest.fixture(scope="module")
def empty_disposable_db() -> str:
    db_name = f"{_DB_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
    admin = _admin_connect()
    try:
        admin.execute(f"CREATE DATABASE {db_name}")
    finally:
        admin.close()

    yield db_name

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
