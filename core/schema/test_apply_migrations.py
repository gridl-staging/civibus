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
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
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
_SAFE_PORTS = {5475, 5477, 5531, 5545, 5567}


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

_OLD_JURISDICTION_SQL = textwrap.dedent("""\
    CREATE TABLE core.jurisdiction (
        id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name              TEXT NOT NULL,
        jurisdiction_type TEXT NOT NULL,
        fips              TEXT,
        state             TEXT
    );

    CREATE UNIQUE INDEX idx_jurisdiction_fips_unique
        ON core.jurisdiction (fips) WHERE fips IS NOT NULL;

    INSERT INTO core.jurisdiction (name, jurisdiction_type, fips, state)
    VALUES
        ('North Carolina', 'state', '37', 'NC'),
        ('Durham County', 'county', '37063', 'NC'),
        ('Legacy seven digit municipality', 'municipality', '0644000', 'CA'),
        ('Legacy five digit municipality', 'municipality', '36510', 'NY'),
        ('Legacy Unicode state', 'state', '٣٧', 'ZZ'),
        ('Legacy short county', 'county', '3706', 'NC');
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

_AUTHORITY_SCOPED_IDENTITY_LEGACY_SQL = textwrap.dedent("""\
    CREATE SCHEMA core;
    CREATE SCHEMA cf;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    CREATE TABLE core.schema_migrations (
        filename TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE core.data_source (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        domain TEXT NOT NULL,
        jurisdiction TEXT,
        name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_format TEXT,
        license TEXT,
        update_frequency TEXT,
        last_pull_at TIMESTAMPTZ,
        last_pull_status TEXT,
        record_count BIGINT,
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX idx_data_source_dedup ON core.data_source (domain, jurisdiction, name);

    CREATE TABLE core.source_record (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        data_source_id UUID NOT NULL REFERENCES core.data_source(id),
        source_record_key TEXT,
        source_url TEXT,
        raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
        pull_date TIMESTAMPTZ NOT NULL DEFAULT now(),
        record_hash TEXT,
        superseded_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT fk_source_record_superseded FOREIGN KEY (superseded_by) REFERENCES core.source_record(id)
    );

    CREATE TABLE core.person (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        canonical_name TEXT NOT NULL,
        first_name TEXT,
        last_name TEXT,
        date_of_birth DATE,
        identifiers JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    CREATE TABLE core.organization (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        canonical_name TEXT NOT NULL,
        registered_state TEXT,
        org_type TEXT,
        identifiers JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    CREATE TABLE core.address (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        normalized_address TEXT,
        street_number TEXT,
        zip5 TEXT,
        state TEXT
    );
    CREATE TABLE core.entity_address (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type TEXT NOT NULL,
        entity_id UUID NOT NULL,
        address_id UUID NOT NULL REFERENCES core.address(id),
        valid_period DATERANGE NOT NULL DEFAULT daterange(NULL, NULL, '[]'::text),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE core.entity_source (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        entity_type TEXT NOT NULL,
        entity_id UUID NOT NULL,
        source_record_id UUID NOT NULL REFERENCES core.source_record(id)
    );

    CREATE TABLE cf.committee (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        fec_committee_id TEXT NOT NULL UNIQUE,
        source_record_id UUID REFERENCES core.source_record(id)
    );
    CREATE TABLE cf.candidate (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        fec_candidate_id TEXT NOT NULL UNIQUE,
        source_record_id UUID REFERENCES core.source_record(id)
    );
    CREATE TABLE cf.filing (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        filing_fec_id TEXT NOT NULL UNIQUE,
        amended_from_filing_id UUID REFERENCES cf.filing(id),
        source_record_id UUID REFERENCES core.source_record(id)
    );
    CREATE TABLE cf.transaction (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        sub_id NUMERIC(19,0),
        transaction_identifier TEXT,
        amended_by_transaction_id UUID REFERENCES cf.transaction(id),
        source_record_id UUID REFERENCES core.source_record(id)
    );
    CREATE UNIQUE INDEX uq_transaction_sub_id ON cf.transaction (sub_id) WHERE sub_id IS NOT NULL;
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
    "2026_08_27_typed_jurisdiction_identity.sql",
    "2026_08_27_refresh_run_execution_origin.sql",
]

_DONOR_IDENTITY_MIGRATION = "2026_07_28_donor_identity_er_contract.sql"
_DONOR_CLUSTER_PERSON_MIGRATION = "2026_07_28_donor_identity_person_mapping.sql"
_CONTRIBUTION_LIMIT_RULES_MIGRATION = "2026_08_23_contribution_limit_rules.sql"
_PERSON_ABSORPTION_MIGRATION = "2026_08_24_person_absorption.sql"
_TYPED_JURISDICTION_IDENTITY_MIGRATION = "2026_08_27_typed_jurisdiction_identity.sql"
_REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION = "2026_08_27_refresh_run_execution_origin.sql"
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
        conn.execute(_OLD_JURISDICTION_SQL)
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
def fresh_jurisdiction_db() -> str:
    db_name = _create_database()
    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        conn.execute('CREATE EXTENSION IF NOT EXISTS "postgis"')
        conn.execute("CREATE SCHEMA core")
        conn.execute(
            """
            CREATE FUNCTION core.set_updated_at()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN NEW.updated_at := NOW(); RETURN NEW; END; $$
            """
        )
        conn.execute((REPO_ROOT / "core" / "schema" / "jurisdiction.sql").read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT INTO core.jurisdiction (
                id,
                name,
                jurisdiction_type,
                fips,
                state_fips,
                county_geoid,
                place_geoid,
                parent_id,
                state
            )
            VALUES
                ('98000000-0000-4000-8000-000000000000',
                    'Fixture State', 'state', '98', '98', NULL, NULL, NULL, 'FS'),
                ('98000000-0000-4000-8000-000000000001',
                    'Fixture County', 'county', '98123', NULL, '98123', NULL,
                    '98000000-0000-4000-8000-000000000000', 'FS'),
                ('98000000-0000-4000-8000-000000000002',
                    'Fixture City', 'municipality', '9812345', NULL, NULL, '9812345',
                    '98000000-0000-4000-8000-000000000001', 'FS'),
                ('98000000-0000-4000-8000-000000000003',
                    'Fixture Consolidated City', 'municipality', '98124', NULL, '98124', '9812346',
                    '98000000-0000-4000-8000-000000000000', 'FS')
            """
        )
    finally:
        conn.close()

    yield db_name

    _drop_database(db_name)


@pytest.fixture
def legacy_refresh_run_db() -> str:
    """A fresh pre-execution-origin database for the focused backfill contract."""
    db_name = _create_database()
    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute(_MINIMAL_CORE_SQL)
        conn.execute(_MINIMAL_CF_SQL)
        conn.execute(_OLD_JURISDICTION_SQL)
        conn.execute(_OLD_ZCTA_DISTRICT_SQL)
    finally:
        conn.close()

    yield db_name

    _drop_database(db_name)


@pytest.fixture
def production_execution_origin_db() -> str:
    """A local database whose only unreceipted delta is execution_origin."""
    db_name = _create_database()
    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute(_MINIMAL_CORE_SQL)
        conn.execute("DROP TABLE core.refresh_run")
        conn.execute(_refresh_run_pre_execution_origin_ddl())
        conn.execute(
            "CREATE TABLE core.schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        filenames = sorted(
            path.name
            for path in (REPO_ROOT / "core/schema/migrations").glob("*.sql")
            if path.name != _REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
                [(filename,) for filename in filenames],
            )
        conn.execute(
            "INSERT INTO core.refresh_run ("
            "job_key, domain, jurisdiction, pull_status, started_at, completed_at, message"
            ") VALUES ('fixture', 'fixture', 'fixture', 'success', now(), now(), 'fixture')"
        )
    finally:
        conn.close()

    yield db_name

    _drop_database(db_name)


@pytest.fixture
def production_authority_scoped_identity_db() -> str:
    """A local production-shaped database with only the exact domain migration pending."""
    db_name = _create_database()
    conn = _connect_to(db_name)
    try:
        conn.autocommit = True
        conn.execute(_AUTHORITY_SCOPED_IDENTITY_LEGACY_SQL)
        conn.execute(_refresh_run_ddl_from_provenance_sql())
        migration_names = sorted(path.name for path in (REPO_ROOT / "core/schema/migrations").glob("*.sql"))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
                [(filename,) for filename in migration_names],
            )
        conn.execute(
            """
            INSERT INTO core.refresh_run (
                job_key, domain, jurisdiction, pull_status, started_at, completed_at, message
            ) VALUES ('fixture', 'campaign_finance', 'federal/fec', 'success', now(), now(), 'fixture')
            """
        )
        conn.execute(
            """
            INSERT INTO core.data_source (
                id, domain, jurisdiction, name, source_url, source_format
            ) VALUES (
                '10000000-0000-4000-8000-000000000001',
                'campaign_finance', 'federal/FEC', 'Fixture FEC source',
                'https://example.test/fec', 'api'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO core.source_record (
                id, data_source_id, source_record_key, raw_fields, pull_date
            ) VALUES (
                '20000000-0000-4000-8000-000000000001',
                '10000000-0000-4000-8000-000000000001',
                'fixture-native-record', '{}'::jsonb, now()
            )
            """
        )
        conn.execute(
            """
            INSERT INTO cf.committee (id, fec_committee_id, source_record_id) VALUES (
                '30000000-0000-4000-8000-000000000001', 'C001',
                '20000000-0000-4000-8000-000000000001'
            );
            INSERT INTO cf.candidate (id, fec_candidate_id, source_record_id) VALUES (
                '40000000-0000-4000-8000-000000000001', 'H0AA00001',
                '20000000-0000-4000-8000-000000000001'
            );
            INSERT INTO cf.filing (id, filing_fec_id, source_record_id) VALUES (
                '50000000-0000-4000-8000-000000000001', 'F001',
                '20000000-0000-4000-8000-000000000001'
            );
            INSERT INTO cf.transaction (
                id, sub_id, transaction_identifier, source_record_id
            ) VALUES (
                '60000000-0000-4000-8000-000000000001', 1, 'T001',
                '20000000-0000-4000-8000-000000000001'
            );
            """
        )
    finally:
        conn.close()

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


def _production_connection(db_name: str, *, read_only: bool) -> psycopg.Connection:
    conn = _connect_to(db_name)
    conn.autocommit = True
    conn.execute(f"SET default_transaction_read_only = {'on' if read_only else 'off'}")
    conn.autocommit = False
    return conn


def _production_operation(
    conn: psycopg.Connection,
    db_name: str,
    operation: str,
) -> dict[str, object]:
    import core.schema.apply_migrations as mod

    return mod._run_production_execution_origin_operation(
        conn,
        operation=operation,
        expected_host=conn.info.host,
        expected_port=int(conn.info.port),
        expected_database=db_name,
    )


def _authority_scoped_identity_operation(
    conn: psycopg.Connection,
    db_name: str,
    operation: str,
) -> dict[str, object]:
    import core.schema.apply_migrations as mod

    return mod._run_production_authority_scoped_identity_operation(
        conn,
        operation=operation,
        expected_host=conn.info.host,
        expected_port=int(conn.info.port),
        expected_database=db_name,
    )


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


def _refresh_run_pre_execution_origin_ddl() -> str:
    ddl = _refresh_run_ddl_from_provenance_sql()
    ddl = ddl.replace("    execution_origin TEXT NOT NULL DEFAULT 'legacy_unknown',\n", "")
    ddl = ddl.replace(
        ",\n    CONSTRAINT refresh_run_execution_origin_check\n"
        "        CHECK (execution_origin IN ('scheduled', 'operator_attended', 'legacy_unknown'))",
        "",
    )
    assert "execution_origin" not in ddl
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


def _refresh_run_execution_origin_shape(conn: psycopg.Connection) -> tuple[str, str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'refresh_run'
              AND column_name = 'execution_origin'
            """
        )
        return cur.fetchone()


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


def _typed_jurisdiction_snapshot(conn: psycopg.Connection) -> tuple[object, ...]:
    rows = conn.execute(
        """
        SELECT name, jurisdiction_type, fips, state_fips, county_geoid, place_geoid, state
        FROM core.jurisdiction
        ORDER BY name
        """
    ).fetchall()
    columns = conn.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'core'
          AND table_name = 'jurisdiction'
        ORDER BY ordinal_position
        """
    ).fetchall()
    constraints = conn.execute(
        """
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'core.jurisdiction'::regclass
        ORDER BY conname
        """
    ).fetchall()
    indexes = conn.execute(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'core'
          AND tablename = 'jurisdiction'
        ORDER BY indexname
        """
    ).fetchall()
    return rows, columns, constraints, indexes


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


class TestProductionExecutionOriginOwner:
    @pytest.mark.parametrize("catalog_form", ["legacy", "postgres18"])
    def test_constraint_catalog_accepts_only_the_two_supported_not_null_forms(
        self,
        catalog_form: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        ordinary = [
            (name, contype, validated, True, definition, (), True, 0, contype == "p")
            for name, contype, validated, definition in mod._REFRESH_RUN_BASE_CONSTRAINTS
        ]
        not_null_columns = frozenset(column[0] for column in mod._REFRESH_RUN_BASE_COLUMNS if column[2])
        postgres18_not_null = [
            (
                f"{column}_not_null",
                "n",
                True,
                True,
                f"NOT NULL {column}",
                (column,),
                True,
                0,
                False,
            )
            for column in sorted(not_null_columns)
        ]

        mod._require_supported_constraint_catalog(
            ordinary + (postgres18_not_null if catalog_form == "postgres18" else []),
            expected_constraints=mod._REFRESH_RUN_BASE_CONSTRAINTS,
            expected_not_null_columns=not_null_columns,
            relation="core.refresh_run",
        )

    @pytest.mark.parametrize(
        "drift",
        [
            "partial",
            "extra",
            "duplicate",
            "unvalidated",
            "unenforced",
            "wrong_definition",
            "multi_column",
            "nonlocal",
            "inherited",
            "no_inherit",
        ],
    )
    def test_postgres18_not_null_catalog_fails_closed_for_every_wrong_shape(
        self,
        drift: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        ordinary = [
            (name, contype, validated, True, definition, (), True, 0, contype == "p")
            for name, contype, validated, definition in mod._MIGRATION_LEDGER_CONSTRAINTS
        ]
        expected_not_null = frozenset({"filename", "applied_at"})
        not_null = [
            (f"{column}_not_null", "n", True, True, f"NOT NULL {column}", (column,), True, 0, False)
            for column in sorted(expected_not_null)
        ]
        if drift == "partial":
            not_null.pop()
        elif drift == "extra":
            not_null.append(("extra_not_null", "n", True, True, "NOT NULL extra", ("extra",), True, 0, False))
        elif drift == "duplicate":
            not_null.append(not_null[0])
        elif drift == "unvalidated":
            not_null[0] = (*not_null[0][:2], False, *not_null[0][3:])
        elif drift == "unenforced":
            not_null[0] = (*not_null[0][:3], False, *not_null[0][4:])
        elif drift == "wrong_definition":
            not_null[0] = (*not_null[0][:4], "NOT NULL wrong", *not_null[0][5:])
        elif drift == "multi_column":
            not_null[0] = (*not_null[0][:5], ("filename", "applied_at"), *not_null[0][6:])
        elif drift == "nonlocal":
            not_null[0] = (*not_null[0][:6], False, *not_null[0][7:])
        elif drift == "inherited":
            not_null[0] = (*not_null[0][:7], 1, *not_null[0][8:])
        elif drift == "no_inherit":
            not_null[0] = (*not_null[0][:8], True)

        with pytest.raises(ValueError, match="constraint shape"):
            mod._require_supported_constraint_catalog(
                ordinary + not_null,
                expected_constraints=mod._MIGRATION_LEDGER_CONSTRAINTS,
                expected_not_null_columns=expected_not_null,
                relation="core.schema_migrations",
            )

    @pytest.mark.parametrize(
        ("constraint_type", "field_index", "value"),
        [
            ("c", 3, False),
            ("c", 6, False),
            ("c", 7, 1),
            ("c", 8, True),
            ("p", 8, False),
        ],
        ids=("unenforced", "nonlocal", "inherited", "check-noinherit", "primary-inheritable"),
    )
    def test_ordinary_constraint_catalog_fails_closed_for_inheritance_or_enforcement_drift(
        self,
        constraint_type: str,
        field_index: int,
        value: object,
    ) -> None:
        import core.schema.apply_migrations as mod

        rows = [
            list((name, contype, validated, True, definition, (), True, 0, contype == "p"))
            for name, contype, validated, definition in sorted(mod._REFRESH_RUN_BASE_CONSTRAINTS)
        ]
        row_index = next(index for index, row in enumerate(rows) if row[1] == constraint_type)
        rows[row_index][field_index] = value

        with pytest.raises(ValueError, match="constraint shape"):
            mod._require_supported_constraint_catalog(
                [tuple(row) for row in rows],
                expected_constraints=mod._REFRESH_RUN_BASE_CONSTRAINTS,
                expected_not_null_columns=frozenset(),
                relation="core.refresh_run",
            )

    def test_argument_identity_is_required_only_for_explicit_production_mode(self) -> None:
        import core.schema.apply_migrations as mod

        parser = mod.build_argument_parser()
        with pytest.raises(SystemExit):
            mod._require_production_arguments(
                parser,
                parser.parse_args(["--production-execution-origin", "preflight"]),
            )
        with pytest.raises(SystemExit):
            mod._require_production_arguments(
                parser,
                parser.parse_args(["--expected-host", "localhost"]),
            )
        mod._require_production_arguments(parser, parser.parse_args([]))
        for mode in ("preflight", "apply", "verify"):
            args = parser.parse_args(
                [
                    "--production-execution-origin",
                    mode,
                    "--expected-host",
                    "127.0.0.1",
                    "--expected-port",
                    "5475",
                    "--expected-database",
                    "civibus",
                ]
            )
            mod._require_production_arguments(parser, args)
            assert args.production_execution_origin == mode

    @pytest.mark.parametrize("unsafe", ["missing", "symlink", "digest", "concurrently"])
    def test_pinned_artifact_refuses_absence_symlink_or_digest_drift(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        unsafe: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        migrations = tmp_path / "migrations"
        migrations.mkdir()
        target = migrations / mod._PRODUCTION_EXECUTION_ORIGIN_MIGRATION
        source = REPO_ROOT / "core/schema/migrations" / target.name
        if unsafe == "symlink":
            target.symlink_to(source)
        elif unsafe == "digest":
            target.write_text("SELECT 1;\n", encoding="utf-8")
        elif unsafe == "concurrently":
            target.write_text("CREATE INDEX CONCURRENTLY unsafe ON example (id);\n", encoding="utf-8")
            monkeypatch.setattr(
                mod, "_PRODUCTION_EXECUTION_ORIGIN_SHA256", hashlib.sha256(target.read_bytes()).hexdigest()
            )
        monkeypatch.setattr(mod, "MIGRATIONS_DIR", migrations)

        with pytest.raises(ValueError):
            mod._load_pinned_execution_origin_sql()

    def test_pinned_artifact_executes_the_exact_bytes_that_were_hashed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        migrations = tmp_path / "migrations"
        migrations.mkdir()
        target = migrations / mod._PRODUCTION_EXECUTION_ORIGIN_MIGRATION
        payload = b"ALTER TABLE core.refresh_run ADD COLUMN execution_origin TEXT;\n"
        target.write_bytes(payload)
        real_read_bytes = Path.read_bytes
        read_count = 0

        def one_safe_read(path: Path) -> bytes:
            nonlocal read_count
            if path == target:
                read_count += 1
                if read_count > 1:
                    raise AssertionError("pinned migration was re-read after digest verification")
            return real_read_bytes(path)

        monkeypatch.setattr(mod, "MIGRATIONS_DIR", migrations)
        monkeypatch.setattr(mod, "_PRODUCTION_EXECUTION_ORIGIN_SHA256", hashlib.sha256(payload).hexdigest())
        monkeypatch.setattr(Path, "read_bytes", one_safe_read)
        monkeypatch.setattr(
            Path,
            "read_text",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("pinned migration must decode the verified byte payload")
            ),
        )

        assert mod._load_pinned_execution_origin_sql() == payload.decode("utf-8")
        assert read_count == 1

    def test_production_cli_dispatches_exact_identity_and_prints_receipt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = MagicMock()
        calls: list[dict[str, object]] = []

        def fake_operation(_conn: MagicMock, **kwargs: object) -> dict[str, str]:
            assert _conn is conn
            calls.append(kwargs)
            return {
                "migration": mod._PRODUCTION_EXECUTION_ORIGIN_MIGRATION,
                "migration_sha256": mod._PRODUCTION_EXECUTION_ORIGIN_SHA256,
                "state": "applied_verified",
            }

        monkeypatch.setattr(mod, "get_connection", lambda: conn)
        monkeypatch.setattr(mod, "_run_production_execution_origin_operation", fake_operation)

        result = mod.main(
            [
                "--production-execution-origin",
                "verify",
                "--expected-host",
                "127.0.0.1",
                "--expected-port",
                "16548",
                "--expected-database",
                "civibus",
            ]
        )

        assert result == 0
        assert calls == [
            {
                "operation": "verify",
                "expected_host": "127.0.0.1",
                "expected_port": 16548,
                "expected_database": "civibus",
            }
        ]
        assert capsys.readouterr().out == (
            f'{{"migration": "{mod._PRODUCTION_EXECUTION_ORIGIN_MIGRATION}", '
            f'"migration_sha256": "{mod._PRODUCTION_EXECUTION_ORIGIN_SHA256}", '
            '"mode": "verify", "state": "applied_verified"}\n'
        )
        conn.close.assert_called_once_with()

    def test_read_only_preflight_is_exact_and_has_no_database_mutation(
        self,
        production_execution_origin_db: str,
    ) -> None:
        conn = _production_connection(production_execution_origin_db, read_only=True)
        try:
            before = conn.execute(
                "SELECT COUNT(*), to_regclass('core.refresh_run')::text FROM core.schema_migrations"
            ).fetchone()
            result = _production_operation(conn, production_execution_origin_db, "preflight")
            after = conn.execute(
                "SELECT COUNT(*), to_regclass('core.refresh_run')::text FROM core.schema_migrations"
            ).fetchone()
            assert before == after
            assert result["state"] == "pending_absent"
            assert result["database_identity"]["transaction_read_only"] == "on"
            assert _refresh_run_execution_origin_shape(conn) is None
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "drift",
        [
            "refresh_run_shape",
            "refresh_run_default",
            "refresh_run_owner",
            "migration_ledger_shape",
            "migration_ledger_default",
        ],
    )
    def test_preflight_refuses_noncanonical_owner_shape(
        self,
        production_execution_origin_db: str,
        drift: str,
    ) -> None:
        writer = _production_connection(production_execution_origin_db, read_only=False)
        try:
            if drift == "refresh_run_shape":
                writer.execute("ALTER TABLE core.refresh_run DROP COLUMN message")
            elif drift == "refresh_run_default":
                writer.execute("ALTER TABLE core.refresh_run ALTER COLUMN inserted_count SET DEFAULT 1")
            elif drift == "refresh_run_owner":
                writer.execute("ALTER TABLE core.refresh_run OWNER TO pg_read_all_data")
            elif drift == "migration_ledger_shape":
                writer.execute("ALTER TABLE core.schema_migrations DROP CONSTRAINT schema_migrations_pkey")
            else:
                writer.execute("ALTER TABLE core.schema_migrations ALTER COLUMN applied_at DROP DEFAULT")
            writer.commit()
        finally:
            writer.close()

        reader = _production_connection(production_execution_origin_db, read_only=True)
        try:
            with pytest.raises(ValueError, match="canonical .* shape"):
                _production_operation(reader, production_execution_origin_db, "preflight")
        finally:
            reader.close()

    def test_apply_backfills_and_atomically_records_then_read_only_verify_accepts(
        self,
        production_execution_origin_db: str,
    ) -> None:
        writer = _production_connection(production_execution_origin_db, read_only=False)
        try:
            result = _production_operation(writer, production_execution_origin_db, "apply")
            assert result["state"] == "applied_verified"
        finally:
            writer.close()

        verifier = _production_connection(production_execution_origin_db, read_only=True)
        try:
            verified = _production_operation(verifier, production_execution_origin_db, "verify")
            assert verified["state"] == "applied_verified"
            assert verifier.execute("SELECT execution_origin FROM core.refresh_run").fetchall() == [("legacy_unknown",)]
            assert verifier.execute(
                "SELECT COUNT(*) FROM core.schema_migrations WHERE filename = %s",
                (_REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION,),
            ).fetchone() == (1,)
        finally:
            verifier.close()

    @pytest.mark.parametrize(
        ("operation", "read_only", "identity_drift"),
        [
            ("apply", True, None),
            ("preflight", False, None),
            ("verify", True, "database"),
            ("preflight", True, "host"),
            ("preflight", True, "port"),
        ],
    )
    def test_identity_and_read_mode_mismatch_refuse_before_schema_change(
        self,
        production_execution_origin_db: str,
        operation: str,
        read_only: bool,
        identity_drift: str | None,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_execution_origin_db, read_only=read_only)
        try:
            with pytest.raises(ValueError):
                mod._run_production_execution_origin_operation(
                    conn,
                    operation=operation,
                    expected_host="wrong" if identity_drift == "host" else conn.info.host,
                    expected_port=1 if identity_drift == "port" else int(conn.info.port),
                    expected_database=("wrong" if identity_drift == "database" else production_execution_origin_db),
                )
            assert _refresh_run_execution_origin_shape(conn) is None
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "drift",
        ["schema_present", "extra_pending", "running", "missing_ledger", "missing_refresh"],
    )
    def test_preflight_refuses_schema_pending_or_active_run_drift(
        self,
        production_execution_origin_db: str,
        drift: str,
    ) -> None:
        writer = _production_connection(production_execution_origin_db, read_only=False)
        try:
            if drift == "schema_present":
                writer.execute("ALTER TABLE core.refresh_run ADD COLUMN execution_origin TEXT")
            elif drift == "extra_pending":
                filename = writer.execute(
                    "SELECT filename FROM core.schema_migrations ORDER BY filename LIMIT 1"
                ).fetchone()[0]
                writer.execute("DELETE FROM core.schema_migrations WHERE filename = %s", (filename,))
            elif drift == "running":
                writer.execute("ALTER TABLE core.refresh_run DROP CONSTRAINT refresh_run_pull_status_check")
                writer.execute(
                    "INSERT INTO core.refresh_run ("
                    "job_key, domain, jurisdiction, pull_status, started_at, completed_at, message"
                    ") VALUES ('running', 'fixture', 'fixture', 'running', now(), NULL, 'fixture')"
                )
            elif drift == "missing_ledger":
                writer.execute("DROP TABLE core.schema_migrations")
            else:
                writer.execute("DROP TABLE core.refresh_run")
            writer.commit()
        finally:
            writer.close()

        reader = _production_connection(production_execution_origin_db, read_only=True)
        try:
            with pytest.raises(ValueError):
                _production_operation(reader, production_execution_origin_db, "preflight")
        finally:
            reader.close()

    def test_lock_contention_refuses_without_schema_or_ledger_change(
        self,
        production_execution_origin_db: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        holder = _production_connection(production_execution_origin_db, read_only=False)
        worker = _production_connection(production_execution_origin_db, read_only=False)
        try:
            assert holder.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                (mod._PRODUCTION_MIGRATION_LOCK_NAME,),
            ).fetchone() == (True,)
            with pytest.raises(ValueError, match="holds the lock"):
                _production_operation(worker, production_execution_origin_db, "apply")
            assert _refresh_run_execution_origin_shape(worker) is None
        finally:
            worker.close()
            holder.close()

    def test_injected_apply_failure_rolls_back_schema_and_ledger_together(
        self,
        production_execution_origin_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        real_verify = mod._require_execution_origin_applied_shape

        def fail_after_verify(conn: psycopg.Connection) -> None:
            real_verify(conn)
            raise RuntimeError("injected failure after ledger and exact verification")

        monkeypatch.setattr(mod, "_require_execution_origin_applied_shape", fail_after_verify)
        conn = _production_connection(production_execution_origin_db, read_only=False)
        try:
            with pytest.raises(RuntimeError, match="after ledger"):
                _production_operation(conn, production_execution_origin_db, "apply")
            conn.rollback()
            assert _refresh_run_execution_origin_shape(conn) is None
            assert conn.execute(
                "SELECT COUNT(*) FROM core.schema_migrations WHERE filename = %s",
                (_REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION,),
            ).fetchone() == (0,)
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "drift",
        ["constraint", "widened_constraint", "unvalidated_constraint", "default", "nullability"],
    )
    def test_verify_refuses_both_constraint_and_column_drift(
        self,
        production_execution_origin_db: str,
        drift: str,
    ) -> None:
        writer = _production_connection(production_execution_origin_db, read_only=False)
        try:
            _production_operation(writer, production_execution_origin_db, "apply")
            if drift == "constraint":
                writer.execute("ALTER TABLE core.refresh_run DROP CONSTRAINT refresh_run_execution_origin_check")
            elif drift in {"widened_constraint", "unvalidated_constraint"}:
                writer.execute("ALTER TABLE core.refresh_run DROP CONSTRAINT refresh_run_execution_origin_check")
                allowed = (
                    "'scheduled', 'operator_attended', 'legacy_unknown', 'cron'"
                    if drift == "widened_constraint"
                    else "'scheduled', 'operator_attended', 'legacy_unknown'"
                )
                not_valid = " NOT VALID" if drift == "unvalidated_constraint" else ""
                writer.execute(
                    "ALTER TABLE core.refresh_run ADD CONSTRAINT "
                    "refresh_run_execution_origin_check "
                    f"CHECK (execution_origin IN ({allowed})){not_valid}"
                )
            elif drift == "default":
                writer.execute("ALTER TABLE core.refresh_run ALTER COLUMN execution_origin DROP DEFAULT")
            else:
                writer.execute("ALTER TABLE core.refresh_run ALTER COLUMN execution_origin DROP NOT NULL")
            writer.commit()
        finally:
            writer.close()

        verifier = _production_connection(production_execution_origin_db, read_only=True)
        try:
            with pytest.raises(ValueError):
                _production_operation(verifier, production_execution_origin_db, "verify")
        finally:
            verifier.close()

    def test_verify_refuses_ledger_receipt_without_schema(self, production_execution_origin_db: str) -> None:
        writer = _production_connection(production_execution_origin_db, read_only=False)
        try:
            writer.execute(
                "INSERT INTO core.schema_migrations (filename) VALUES (%s)",
                (_REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION,),
            )
            writer.commit()
        finally:
            writer.close()

        verifier = _production_connection(production_execution_origin_db, read_only=True)
        try:
            with pytest.raises(ValueError):
                _production_operation(verifier, production_execution_origin_db, "verify")
        finally:
            verifier.close()

    @pytest.mark.parametrize(
        ("database_user", "server_port", "error"),
        [
            ("wrong", 5432, "server identity"),
            ("civibus", 5433, "server identity"),
            ("civibus", None, "server port is indeterminate"),
        ],
    )
    def test_fixed_server_identity_refuses_wrong_user_or_server_port(
        self,
        database_user: str,
        server_port: int | None,
        error: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = MagicMock()
        conn.info.host = "127.0.0.1"
        conn.info.port = 16548
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            ("civibus", database_user, server_port),
            ("on",),
        ]

        with pytest.raises(ValueError, match=error):
            mod._require_production_identity(
                conn,
                expected_host="127.0.0.1",
                expected_port=16548,
                expected_database="civibus",
                expected_read_only="on",
            )

    def test_preflight_refuses_a_long_idle_transaction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import core.schema.apply_migrations as mod

        monkeypatch.setattr(mod, "_require_production_owner_shapes", lambda *_args, **_kwargs: None)
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            ("core.schema_migrations", "core.refresh_run"),
            (0,),
            (0,),
            (0,),
            (1,),
        ]
        cursor.fetchall.return_value = [
            (path.name,)
            for path in mod.MIGRATIONS_DIR.glob("*.sql")
            if path.name != mod._PRODUCTION_EXECUTION_ORIGIN_MIGRATION
        ]

        with pytest.raises(ValueError, match="long-idle"):
            mod._require_execution_origin_pending_absent(conn)

    @pytest.mark.parametrize("drift", ["missing_relation", "missing_receipt"])
    def test_verify_refuses_missing_relations_or_target_receipt(
        self, drift: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import core.schema.apply_migrations as mod

        monkeypatch.setattr(mod, "_require_production_owner_shapes", lambda *_args, **_kwargs: None)
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = (
            [(None, "core.refresh_run")]
            if drift == "missing_relation"
            else [("core.schema_migrations", "core.refresh_run"), (0,)]
        )

        with pytest.raises(ValueError, match="requires|receipt is absent"):
            mod._require_execution_origin_applied_shape(conn)

    def test_apply_rechecks_pending_state_after_lock_before_schema_or_ledger_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (True,)
        sentinel_sql = "ALTER TABLE core.refresh_run ADD COLUMN should_not_run TEXT"
        checks = 0

        def fail_second_check(_conn: MagicMock) -> None:
            nonlocal checks
            checks += 1
            if checks == 2:
                raise ValueError("in-lock state changed")

        monkeypatch.setattr(mod, "_require_production_identity", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(mod, "_load_pinned_execution_origin_sql", lambda: sentinel_sql)
        monkeypatch.setattr(mod, "_require_execution_origin_pending_absent", fail_second_check)

        with pytest.raises(ValueError, match="in-lock state changed"):
            mod._run_production_execution_origin_operation(
                conn,
                operation="apply",
                expected_host="127.0.0.1",
                expected_port=5475,
                expected_database="civibus",
            )

        assert checks == 2
        statements = [call.args[0] for call in conn.execute.call_args_list]
        assert sentinel_sql not in statements
        assert not any(statement.startswith("INSERT INTO core.schema_migrations") for statement in statements)


class TestProductionAuthorityScopedIdentityOwner:
    def test_cli_is_pinned_to_the_lane_local_civibus_identity(self) -> None:
        import core.schema.apply_migrations as mod

        parser = mod.build_argument_parser()
        args = parser.parse_args(
            [
                "--production-authority-scoped-identity",
                "preflight",
                "--expected-host",
                "127.0.0.1",
                "--expected-port",
                "16548",
                "--expected-database",
                "civibus",
            ]
        )

        mod._require_production_arguments(parser, args)
        assert args.production_authority_scoped_identity == "preflight"
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION == "2026_08_28_authority_scoped_identity.sql"
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SUPERSEDED_SHA256 == (
            "310cfcd3106c70039d947bdd20ba1cc001072d8bf96969390ad162edab9416ed"
        )
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256 != (
            mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SUPERSEDED_SHA256
        )

    @pytest.mark.parametrize(
        ("host", "port", "database"),
        [
            ("localhost", "16548", "civibus"),
            ("127.0.0.1", "0", "civibus"),
            ("127.0.0.1", "65536", "civibus"),
            ("127.0.0.1", "16548", "wrong"),
        ],
    )
    def test_cli_refuses_wrong_locality_or_database(self, host: str, port: str, database: str) -> None:
        import core.schema.apply_migrations as mod

        parser = mod.build_argument_parser()
        args = parser.parse_args(
            [
                "--production-authority-scoped-identity",
                "preflight",
                "--expected-host",
                host,
                "--expected-port",
                port,
                "--expected-database",
                database,
            ]
        )
        with pytest.raises(SystemExit):
            mod._require_production_arguments(parser, args)

    def test_cli_refuses_two_production_targets(self) -> None:
        import core.schema.apply_migrations as mod

        with pytest.raises(SystemExit):
            mod.build_argument_parser().parse_args(
                [
                    "--production-execution-origin",
                    "preflight",
                    "--production-authority-scoped-identity",
                    "preflight",
                ]
            )

    def test_internal_owner_refuses_an_unknown_operation_before_connectivity_checks(self) -> None:
        import core.schema.apply_migrations as mod

        with pytest.raises(ValueError, match="unsupported authority-scoped identity operation"):
            mod._run_production_authority_scoped_identity_operation(
                MagicMock(),
                operation="unknown",
                expected_host="127.0.0.1",
                expected_port=16548,
                expected_database="civibus",
            )

    def test_apply_contract_uses_bounded_batches_and_never_reuses_the_terminal_timeout(self) -> None:
        import core.schema.apply_migrations as mod

        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE == 10_000
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_DEPTH_LIMIT == 32
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_CLOSURE_LIMIT == 20_000
        assert mod._AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_COLUMNS == {
            "backfill.filing": "amended_from_filing_id",
            "backfill.transaction": "amended_by_transaction_id",
        }
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT == "5min"
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT == "15min"
        assert mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_CUTOVER_STATEMENT_TIMEOUT == "5min"
        assert "60min" not in {
            mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT,
            mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT,
            mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_CUTOVER_STATEMENT_TIMEOUT,
        }

    @pytest.mark.parametrize(
        ("operation", "classified_state", "expected_state", "initial_read_only"),
        [
            ("preflight", "pending_absent", "pending_absent", "on"),
            ("verify", "already_applied_verified", "applied_verified", "on"),
            ("apply", "already_applied_verified", "already_applied_verified", "off"),
        ],
    )
    def test_outer_classifier_is_once_bounded_and_read_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        operation: str,
        classified_state: str,
        expected_state: str,
        initial_read_only: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = MagicMock()
        statements: list[str] = []

        def execute(statement: str, *_args: object, **_kwargs: object) -> MagicMock:
            normalized = " ".join(statement.split())
            statements.append(normalized)
            result = MagicMock()
            if normalized == "SHOW transaction_read_only":
                value = "on" if "SET TRANSACTION READ ONLY" in statements else initial_read_only
                result.fetchone.return_value = (value,)
            elif normalized == "SHOW statement_timeout":
                value = (
                    mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT
                    if "SET LOCAL statement_timeout = '15min'" in statements
                    else "42s"
                )
                result.fetchone.return_value = (value,)
            elif normalized == "SHOW lock_timeout":
                value = "5s" if "SET LOCAL lock_timeout = '5s'" in statements else "0"
                result.fetchone.return_value = (value,)
            return result

        conn.execute.side_effect = execute
        classifier_calls: list[object] = []

        def classify(actual_conn: object) -> str:
            classifier_calls.append(actual_conn)
            assert actual_conn is conn
            assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
            assert conn.execute("SHOW statement_timeout").fetchone() == ("15min",)
            assert conn.execute("SHOW lock_timeout").fetchone() == ("5s",)
            return classified_state

        monkeypatch.setattr(mod, "_require_production_identity", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(mod, "_load_pinned_authority_scoped_identity_sql", lambda: "pinned")
        monkeypatch.setattr(mod, "_parse_authority_scoped_identity_phases", lambda _sql: {})
        monkeypatch.setattr(mod, "_classify_authority_scoped_identity_state", classify)
        monkeypatch.setattr(mod, "_acquire_authority_scoped_identity_session_lock", lambda _conn: None)
        monkeypatch.setattr(mod, "_release_authority_scoped_identity_session_lock", lambda _conn: None)

        result = mod._run_production_authority_scoped_identity_operation(
            conn,
            operation=operation,
            expected_host="127.0.0.1",
            expected_port=16548,
            expected_database="civibus",
        )

        assert result["state"] == expected_state
        assert classifier_calls == [conn]
        conn.transaction.assert_called_once_with()
        assert statements.count("SET TRANSACTION READ ONLY") == 1
        assert statements.count("SET LOCAL statement_timeout = '15min'") == 1
        assert statements.count("SET LOCAL lock_timeout = '5s'") == 1

    @pytest.mark.parametrize("classified_state", ["pending_absent", "partial_resumable"])
    def test_verify_maps_only_exact_applied_classification(
        self,
        monkeypatch: pytest.MonkeyPatch,
        classified_state: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = MagicMock()
        monkeypatch.setattr(mod, "_require_production_identity", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(mod, "_load_pinned_authority_scoped_identity_sql", lambda: "pinned")
        monkeypatch.setattr(mod, "_parse_authority_scoped_identity_phases", lambda _sql: {})
        monkeypatch.setattr(
            mod,
            "_classify_authority_scoped_identity_state",
            lambda _conn: classified_state,
        )

        with pytest.raises(ValueError, match="is not applied"):
            mod._run_production_authority_scoped_identity_operation(
                conn,
                operation="verify",
                expected_host="127.0.0.1",
                expected_port=16548,
                expected_database="civibus",
            )

    def test_atomic_cutover_verifier_is_catalog_ledger_and_transient_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        calls: list[str] = []

        def record(name: str):
            def recorder(_conn, *_args, **_kwargs) -> None:
                calls.append(name)

            return recorder

        monkeypatch.setattr(
            mod,
            "_authority_scoped_identity_ledger_count",
            lambda _conn: calls.append("ledger") or 1,
        )
        for helper_name, label in (
            ("_require_authority_scoped_identity_columns", "columns"),
            ("_require_authority_scoped_identity_constraints", "constraints"),
            ("_require_authority_scoped_identity_indexes", "indexes"),
            ("_require_authority_scoped_identity_triggers", "triggers"),
            ("_require_authority_scoped_identity_views", "views"),
            ("_require_authority_scoped_identity_transients_absent", "transients"),
        ):
            monkeypatch.setattr(mod, helper_name, record(label))

        def refuse_table_scan(_conn) -> None:
            raise AssertionError("atomic cutover verification must not scan data tables")

        monkeypatch.setattr(mod, "_require_authority_scoped_identity_semantics", refuse_table_scan)
        monkeypatch.setattr(mod, "_require_authority_scoped_identity_backfills_complete", refuse_table_scan)

        mod._require_authority_scoped_identity_atomic_shape(object())

        assert calls == [
            "ledger",
            "columns",
            "constraints",
            "indexes",
            "triggers",
            "views",
            "transients",
        ]

    def test_backfill_plan_materializes_a_target_pk_batch_before_domain_joins(
        self,
        production_authority_scoped_identity_db: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        expected_targets = {
            "backfill.committee": "cf.committee",
            "backfill.candidate": "cf.candidate",
            "backfill.filing": "cf.filing",
            "backfill.transaction": "cf.transaction",
        }
        assert {
            phase_name: spec[0] for phase_name, spec in mod._AUTHORITY_SCOPED_IDENTITY_BACKFILL_SPECS.items()
        } == expected_targets
        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            source_prefix = "21000000-0000-4000-9000-"
            target_prefix = "51000000-0000-4000-9000-"
            conn.execute(
                f"""
                WITH generated AS (
                    SELECT value,
                           ('{source_prefix}' || lpad(to_hex(value), 12, '0'))::uuid AS source_id,
                           ('{target_prefix}' || lpad(to_hex(value), 12, '0'))::uuid AS target_id
                    FROM generate_series(1, 50050) AS values(value)
                ), inserted_sources AS (
                    INSERT INTO core.source_record (
                        id, data_source_id, source_record_key, raw_fields, pull_date
                    )
                    SELECT source_id,
                           '10000000-0000-4000-8000-000000000001'::uuid,
                           'r24-source-' || value,
                           '{{}}'::jsonb,
                           now()
                    FROM generated
                    RETURNING id
                )
                INSERT INTO cf.filing (id, filing_fec_id, source_record_id)
                SELECT target_id, 'R24F' || value, source_id
                FROM generated
                """
            )
            conn.commit()
            conn.execute("ANALYZE cf.filing")
            conn.execute("ANALYZE core.source_record")
            target_rows = conn.execute("SELECT COUNT(*) FROM cf.filing").fetchone()[0]
            target_estimate = conn.execute(
                "SELECT reltuples::bigint FROM pg_class WHERE oid = 'cf.filing'::regclass"
            ).fetchone()[0]
            assert target_rows > mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE * 5
            assert target_estimate > mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE * 5

            sql = mod._load_pinned_authority_scoped_identity_sql()
            phases = mod._parse_authority_scoped_identity_phases(sql)
            mod._prepare_authority_scoped_identity_migration(conn, phases["prepare"])
            for phase_name, target_relation in expected_targets.items():
                batch_sql = mod._authority_scoped_identity_backfill_sql(phase_name)
                assert "target_batch AS MATERIALIZED" in batch_sql
                assert f"FROM {target_relation} AS selected_row" in batch_sql
                assert batch_sql.index("LIMIT %s") < batch_sql.index("JOIN core.source_record")
                assert "SKIP LOCKED" not in batch_sql.upper()
            for phase_name, dependency_column in mod._AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_COLUMNS.items():
                dependency_sql = mod._authority_scoped_identity_backfill_sql(phase_name)
                assert "WITH RECURSIVE target_batch AS MATERIALIZED" in dependency_sql
                assert "dependency_closure AS MATERIALIZED" in dependency_sql
                assert dependency_column in dependency_sql
                assert "closure_status.failure IS NULL" in dependency_sql

            def walk(node: dict[str, object]) -> list[dict[str, object]]:
                return [node, *(child for plan_child in node.get("Plans", []) for child in walk(plan_child))]

            batch_sql = mod._authority_scoped_identity_backfill_sql("backfill.filing")
            plan = conn.execute(
                f"EXPLAIN (FORMAT JSON) {batch_sql}",
                (
                    "50000000-0000-4000-8000-000000000000",
                    mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE,
                ),
            ).fetchone()[0][0]["Plan"]
            all_nodes = walk(plan)
            target_ctes = [node for node in all_nodes if node.get("Subplan Name") == "CTE target_batch"]
            assert len(target_ctes) == 1, plan
            target_cte_nodes = walk(target_ctes[0])
            assert target_ctes[0]["Node Type"] == "Limit"
            assert {
                node.get("Relation Name") for node in target_cte_nodes if node.get("Relation Name") is not None
            } == {"filing"}
            assert any(node.get("Node Type") == "LockRows" for node in target_cte_nodes)
            assert any(
                node.get("Node Type") in {"Index Scan", "Index Only Scan"}
                and node.get("Index Name") == "filing_pkey"
                and "id" in str(node.get("Index Cond"))
                and ">" in str(node.get("Index Cond"))
                for node in target_cte_nodes
            ), target_ctes[0]
            assert any(
                node.get("Node Type") == "CTE Scan" and node.get("CTE Name") == "target_batch" for node in all_nodes
            )
            assert any(node.get("Relation Name") == "source_record" for node in all_nodes)
        finally:
            conn.close()

    def test_filing_batch_atomically_includes_an_ancestor_beyond_the_ten_thousand_target_boundary(
        self,
        production_authority_scoped_identity_db: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        cursor_id = "50000000-0000-4000-8000-000000000001"
        child_id = "51000000-0000-4000-9000-000000002710"
        original_id = "51000000-0000-4000-9000-000000002711"
        ancestor_id = "51000000-0000-4000-9000-000000002712"
        try:
            sql = mod._load_pinned_authority_scoped_identity_sql()
            phases = mod._parse_authority_scoped_identity_phases(sql)
            mod._prepare_authority_scoped_identity_migration(conn, phases["prepare"])
            conn.execute(
                """
                WITH generated AS (
                    SELECT value,
                           ('21000000-0000-4000-9000-' || lpad(to_hex(value), 12, '0'))::uuid AS source_id
                    FROM generate_series(1, 10002) AS values(value)
                )
                INSERT INTO core.source_record (
                    id, data_source_id, source_record_key, raw_fields, pull_date
                )
                SELECT source_id,
                       '10000000-0000-4000-8000-000000000001'::uuid,
                       'r27-filing-source-' || value,
                       '{}'::jsonb,
                       now()
                FROM generated
                """
            )
            conn.execute(
                """
                WITH generated AS (
                    SELECT value,
                           ('21000000-0000-4000-9000-' || lpad(to_hex(value), 12, '0'))::uuid AS source_id,
                           ('51000000-0000-4000-9000-' || lpad(to_hex(value), 12, '0'))::uuid AS target_id
                    FROM generate_series(1, 10002) AS values(value)
                )
                INSERT INTO cf.filing (id, filing_fec_id, source_record_id)
                SELECT target_id, 'R27F' || value, source_id
                FROM generated
                """
            )
            conn.execute(
                "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                (original_id, child_id),
            )
            conn.execute(
                "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                (ancestor_id, original_id),
            )
            conn.execute(
                """
                UPDATE core.authority_scoped_identity_migration_progress
                SET last_id = %s
                WHERE target_relation = 'cf.filing'
                """,
                (cursor_id,),
            )
            conn.commit()

            batch_sql = mod._authority_scoped_identity_backfill_sql("backfill.filing")
            with conn.transaction():
                result = conn.execute(
                    batch_sql,
                    (cursor_id, mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE),
                ).fetchone()
            assert result == (10_000, None)
            assert conn.execute(
                """
                SELECT id::text, data_source_id::text, native_filing_id
                FROM cf.filing
                WHERE id = ANY(%s::uuid[])
                ORDER BY id
                """,
                ([child_id, original_id, ancestor_id],),
            ).fetchall() == [
                (child_id, "10000000-0000-4000-8000-000000000001", "R27F10000"),
                (original_id, "10000000-0000-4000-8000-000000000001", "R27F10001"),
                (ancestor_id, "10000000-0000-4000-8000-000000000001", "R27F10002"),
            ]
            assert conn.execute(
                """
                SELECT last_id::text
                FROM core.authority_scoped_identity_migration_progress
                WHERE target_relation = 'cf.filing'
                """
            ).fetchone() == (child_id,)

            with conn.transaction():
                revisit = conn.execute(
                    batch_sql,
                    (child_id, mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE),
                ).fetchone()
            assert revisit == (2, None)
            assert conn.execute(
                """
                SELECT last_id::text
                FROM core.authority_scoped_identity_migration_progress
                WHERE target_relation = 'cf.filing'
                """
            ).fetchone() == (ancestor_id,)
        finally:
            conn.close()

    def test_transaction_batch_atomically_includes_a_successor_beyond_the_ten_thousand_target_boundary(
        self,
        production_authority_scoped_identity_db: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        cursor_id = "60000000-0000-4000-8000-000000000001"
        original_id = "61000000-0000-4000-9000-000000002710"
        successor_id = "61000000-0000-4000-9000-000000002711"
        second_successor_id = "61000000-0000-4000-9000-000000002712"
        try:
            sql = mod._load_pinned_authority_scoped_identity_sql()
            phases = mod._parse_authority_scoped_identity_phases(sql)
            mod._prepare_authority_scoped_identity_migration(conn, phases["prepare"])
            conn.execute(
                """
                WITH generated AS (
                    SELECT value,
                           ('22000000-0000-4000-9000-' || lpad(to_hex(value), 12, '0'))::uuid AS source_id
                    FROM generate_series(1, 10002) AS values(value)
                )
                INSERT INTO core.source_record (
                    id, data_source_id, source_record_key, raw_fields, pull_date
                )
                SELECT source_id,
                       '10000000-0000-4000-8000-000000000001'::uuid,
                       'r27-transaction-source-' || value,
                       '{}'::jsonb,
                       now()
                FROM generated
                """
            )
            conn.execute(
                """
                WITH generated AS (
                    SELECT value,
                           ('22000000-0000-4000-9000-' || lpad(to_hex(value), 12, '0'))::uuid AS source_id,
                           ('61000000-0000-4000-9000-' || lpad(to_hex(value), 12, '0'))::uuid AS target_id
                    FROM generate_series(1, 10002) AS values(value)
                )
                INSERT INTO cf.transaction (
                    id, sub_id, transaction_identifier, source_record_id
                )
                SELECT target_id, 100000 + value, 'R27T' || value, source_id
                FROM generated
                """
            )
            conn.execute(
                "UPDATE cf.transaction SET amended_by_transaction_id = %s WHERE id = %s",
                (successor_id, original_id),
            )
            conn.execute(
                "UPDATE cf.transaction SET amended_by_transaction_id = %s WHERE id = %s",
                (second_successor_id, successor_id),
            )
            conn.execute(
                """
                UPDATE core.authority_scoped_identity_migration_progress
                SET last_id = %s
                WHERE target_relation = 'cf.transaction'
                """,
                (cursor_id,),
            )
            conn.commit()

            batch_sql = mod._authority_scoped_identity_backfill_sql("backfill.transaction")
            with conn.transaction():
                result = conn.execute(
                    batch_sql,
                    (cursor_id, mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE),
                ).fetchone()
            assert result == (10_000, None)
            assert conn.execute(
                """
                SELECT id::text, data_source_id::text, native_transaction_id
                FROM cf.transaction
                WHERE id = ANY(%s::uuid[])
                ORDER BY id
                """,
                ([original_id, successor_id, second_successor_id],),
            ).fetchall() == [
                (
                    original_id,
                    "10000000-0000-4000-8000-000000000001",
                    "r27-transaction-source-10000",
                ),
                (
                    successor_id,
                    "10000000-0000-4000-8000-000000000001",
                    "r27-transaction-source-10001",
                ),
                (
                    second_successor_id,
                    "10000000-0000-4000-8000-000000000001",
                    "r27-transaction-source-10002",
                ),
            ]
            assert conn.execute(
                """
                SELECT last_id::text
                FROM core.authority_scoped_identity_migration_progress
                WHERE target_relation = 'cf.transaction'
                """
            ).fetchone() == (original_id,)

            with conn.transaction():
                revisit = conn.execute(
                    batch_sql,
                    (original_id, mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE),
                ).fetchone()
            assert revisit == (2, None)
            assert conn.execute(
                """
                SELECT last_id::text
                FROM core.authority_scoped_identity_migration_progress
                WHERE target_relation = 'cf.transaction'
                """
            ).fetchone() == (second_successor_id,)
        finally:
            conn.close()

    @pytest.mark.parametrize(
        ("failure_kind", "expected_error"),
        [
            ("cycle", "dependency cycle"),
            ("overflow", "dependency closure overflow"),
            ("missing_source", "dependency source is missing"),
            ("scope_mismatch", "dependency scope mismatch"),
        ],
    )
    def test_filing_dependency_closure_refuses_unsafe_graphs_before_batch_or_cursor_change(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
        failure_kind: str,
        expected_error: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        filing_ids = [
            "52000000-0000-4000-9000-000000000001",
            "52000000-0000-4000-9000-000000000002",
            "52000000-0000-4000-9000-000000000003",
        ]
        source_ids = [
            "23000000-0000-4000-9000-000000000001",
            "23000000-0000-4000-9000-000000000002",
            "23000000-0000-4000-9000-000000000003",
        ]
        try:
            conn.execute(
                """
                INSERT INTO core.data_source (
                    id, domain, jurisdiction, name, source_url, source_format
                ) VALUES (
                    '11000000-0000-4000-8000-000000000002',
                    'fixture', 'fixture', 'Second fixture source',
                    'https://example.test/second', 'api'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO core.source_record (
                    id, data_source_id, source_record_key, raw_fields, pull_date
                ) VALUES
                    (%s, '10000000-0000-4000-8000-000000000001', 'r27-refusal-1', '{}'::jsonb, now()),
                    (%s, %s, 'r27-refusal-2', '{}'::jsonb, now()),
                    (%s, '10000000-0000-4000-8000-000000000001', 'r27-refusal-3', '{}'::jsonb, now())
                """,
                (
                    source_ids[0],
                    source_ids[1],
                    (
                        "11000000-0000-4000-8000-000000000002"
                        if failure_kind == "scope_mismatch"
                        else "10000000-0000-4000-8000-000000000001"
                    ),
                    source_ids[2],
                ),
            )
            conn.execute(
                """
                INSERT INTO cf.filing (id, filing_fec_id, source_record_id) VALUES
                    (%s, 'R27-REFUSAL-1', %s),
                    (%s, 'R27-REFUSAL-2', %s),
                    (%s, 'R27-REFUSAL-3', %s)
                """,
                (
                    filing_ids[0],
                    source_ids[0],
                    filing_ids[1],
                    None if failure_kind == "missing_source" else source_ids[1],
                    filing_ids[2],
                    source_ids[2],
                ),
            )
            if failure_kind == "cycle":
                conn.execute(
                    "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                    (filing_ids[1], filing_ids[0]),
                )
                conn.execute(
                    "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                    (filing_ids[0], filing_ids[1]),
                )
                batch_size = 3
            elif failure_kind == "overflow":
                conn.execute(
                    "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                    (filing_ids[1], filing_ids[0]),
                )
                conn.execute(
                    "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                    (filing_ids[2], filing_ids[1]),
                )
                batch_size = 2
                monkeypatch.setattr(
                    mod,
                    "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_DEPENDENCY_CLOSURE_LIMIT",
                    3,
                    raising=False,
                )
            else:
                conn.execute(
                    "UPDATE cf.filing SET amended_from_filing_id = %s WHERE id = %s",
                    (filing_ids[1], filing_ids[0]),
                )
                batch_size = 3
            conn.commit()
            monkeypatch.setattr(mod, "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE", batch_size)

            with pytest.raises(ValueError, match=expected_error):
                _authority_scoped_identity_operation(conn, production_authority_scoped_identity_db, "apply")
            conn.rollback()

            assert mod._authority_scoped_identity_ledger_count(conn) == 0
            assert conn.execute(
                """
                SELECT last_id
                FROM core.authority_scoped_identity_migration_progress
                WHERE target_relation = 'cf.filing'
                """
            ).fetchone() == (None,)
            assert conn.execute(
                """
                SELECT data_source_id, native_filing_id
                FROM cf.filing
                WHERE id = ANY(%s::uuid[])
                ORDER BY id
                """,
                (filing_ids,),
            ).fetchall() == [(None, None), (None, None), (None, None)]
        finally:
            conn.close()

    def test_backfill_progress_counts_selected_target_ids_including_populated_and_sourceless_rows(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            sql = mod._load_pinned_authority_scoped_identity_sql()
            phases = mod._parse_authority_scoped_identity_phases(sql)
            mod._prepare_authority_scoped_identity_migration(conn, phases["prepare"])
            conn.execute(
                """
                INSERT INTO cf.committee (
                    id, fec_committee_id, source_record_id, data_source_id, native_committee_id
                ) VALUES
                    ('30000000-0000-4000-8000-000000000002', 'C002', NULL,
                     '10000000-0000-4000-8000-000000000001', 'already-C002'),
                    ('30000000-0000-4000-8000-000000000003', 'C003', NULL, NULL, NULL);
                INSERT INTO cf.candidate (
                    id, fec_candidate_id, source_record_id, data_source_id, native_candidate_id
                ) VALUES
                    ('40000000-0000-4000-8000-000000000002', 'H0AA00002', NULL,
                     '10000000-0000-4000-8000-000000000001', 'already-H0AA00002'),
                    ('40000000-0000-4000-8000-000000000003', 'H0AA00003', NULL, NULL, NULL);
                INSERT INTO cf.filing (
                    id, filing_fec_id, source_record_id, data_source_id, native_filing_id
                ) VALUES
                    ('50000000-0000-4000-8000-000000000002', 'F002', NULL,
                     '10000000-0000-4000-8000-000000000001', 'already-F002'),
                    ('50000000-0000-4000-8000-000000000003', 'F003', NULL, NULL, NULL);
                INSERT INTO cf.transaction (
                    id, sub_id, transaction_identifier, source_record_id,
                    data_source_id, native_transaction_id
                ) VALUES
                    ('60000000-0000-4000-8000-000000000002', 2, 'T002', NULL,
                     '10000000-0000-4000-8000-000000000001', 'already-T002'),
                    ('60000000-0000-4000-8000-000000000003', 3, 'T003', NULL, NULL, NULL);
                """
            )
            conn.commit()
            monkeypatch.setattr(mod, "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE", 1)

            mod._run_authority_scoped_identity_backfills(conn, phases)

            assert conn.execute(
                """
                SELECT target_relation, last_id::text
                FROM core.authority_scoped_identity_migration_progress
                ORDER BY target_relation
                """
            ).fetchall() == [
                ("cf.candidate", "40000000-0000-4000-8000-000000000003"),
                ("cf.committee", "30000000-0000-4000-8000-000000000003"),
                ("cf.filing", "50000000-0000-4000-8000-000000000003"),
                ("cf.transaction", "60000000-0000-4000-8000-000000000003"),
            ]
            assert conn.execute(
                """
                SELECT native_committee_id FROM cf.committee
                WHERE id = '30000000-0000-4000-8000-000000000002'
                """
            ).fetchone() == ("already-C002",)
            assert conn.execute(
                """
                SELECT data_source_id, native_transaction_id FROM cf.transaction
                WHERE id = '60000000-0000-4000-8000-000000000003'
                """
            ).fetchone() == (None, None)
        finally:
            conn.close()

    def test_each_backfill_commits_its_first_batch_and_resumes_after_the_second_rolls_back(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        cases = (
            (
                "committee",
                "30000000-0000-4000-8000-",
                "native_committee_id",
                ["C001", "C002", "C003"],
            ),
            (
                "candidate",
                "40000000-0000-4000-8000-",
                "native_candidate_id",
                ["H0AA00001", "H0AA00002", "H0AA00003"],
            ),
            (
                "filing",
                "50000000-0000-4000-8000-",
                "native_filing_id",
                ["F001", "F002", "F003"],
            ),
            (
                "transaction",
                "60000000-0000-4000-8000-",
                "native_transaction_id",
                ["fixture-native-record", "fixture-native-record-2", "fixture-native-record-3"],
            ),
        )
        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            conn.execute(
                """
                INSERT INTO core.source_record (
                    id, data_source_id, source_record_key, raw_fields, pull_date
                ) VALUES
                    (%s, '10000000-0000-4000-8000-000000000001',
                     'fixture-native-record-2', '{}'::jsonb, now()),
                    (%s, '10000000-0000-4000-8000-000000000001',
                     'fixture-native-record-3', '{}'::jsonb, now())
                """,
                (
                    "20000000-0000-4000-8000-000000000002",
                    "20000000-0000-4000-8000-000000000003",
                ),
            )
            conn.execute(
                """
                INSERT INTO cf.committee (id, fec_committee_id, source_record_id) VALUES
                    ('30000000-0000-4000-8000-000000000002', 'C002',
                     '20000000-0000-4000-8000-000000000002'),
                    ('30000000-0000-4000-8000-000000000003', 'C003',
                     '20000000-0000-4000-8000-000000000003');
                INSERT INTO cf.candidate (id, fec_candidate_id, source_record_id) VALUES
                    ('40000000-0000-4000-8000-000000000002', 'H0AA00002',
                     '20000000-0000-4000-8000-000000000002'),
                    ('40000000-0000-4000-8000-000000000003', 'H0AA00003',
                     '20000000-0000-4000-8000-000000000003');
                INSERT INTO cf.filing (id, filing_fec_id, source_record_id) VALUES
                    ('50000000-0000-4000-8000-000000000002', 'F002',
                     '20000000-0000-4000-8000-000000000002'),
                    ('50000000-0000-4000-8000-000000000003', 'F003',
                     '20000000-0000-4000-8000-000000000003');
                INSERT INTO cf.transaction (
                    id, sub_id, transaction_identifier, source_record_id
                ) VALUES
                    ('60000000-0000-4000-8000-000000000002', 2, 'T002',
                     '20000000-0000-4000-8000-000000000002'),
                    ('60000000-0000-4000-8000-000000000003', 3, 'T003',
                     '20000000-0000-4000-8000-000000000003');
                """
            )
            for table, target_prefix, _native_column, _expected_native_ids in cases:
                trigger_name = f"r24_sleep_on_second_{table}"
                second_id = f"{target_prefix}000000000002"
                conn.execute(
                    f"""
                    CREATE FUNCTION cf.{trigger_name}()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        IF NEW.id = '{second_id}'::uuid THEN
                            PERFORM pg_sleep(1);
                        END IF;
                        RETURN NEW;
                    END;
                    $$;
                    CREATE TRIGGER {trigger_name}
                    BEFORE UPDATE ON cf.{table}
                    FOR EACH ROW EXECUTE FUNCTION cf.{trigger_name}();
                    """
                )
            conn.commit()
            monkeypatch.setattr(mod, "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE", 1)
            monkeypatch.setattr(
                mod,
                "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT",
                "100ms",
            )

            for table, target_prefix, native_column, expected_native_ids in cases:
                first_id = f"{target_prefix}000000000001"
                second_id = f"{target_prefix}000000000002"
                trigger_name = f"r24_sleep_on_second_{table}"
                with pytest.raises(psycopg.errors.QueryCanceled, match="statement timeout"):
                    _authority_scoped_identity_operation(conn, production_authority_scoped_identity_db, "apply")
                conn.rollback()

                assert mod._authority_scoped_identity_ledger_count(conn) == 0
                assert conn.execute(
                    """
                    SELECT last_id::text
                    FROM core.authority_scoped_identity_migration_progress
                    WHERE target_relation = %s
                    """,
                    (f"cf.{table}",),
                ).fetchone() == (first_id,)
                assert conn.execute(
                    f"SELECT {native_column} FROM cf.{table} WHERE id = %s",
                    (first_id,),
                ).fetchone() == (expected_native_ids[0],)
                assert conn.execute(
                    f"SELECT {native_column} FROM cf.{table} WHERE id = %s",
                    (second_id,),
                ).fetchone() == (None,)
                conn.execute(f"DROP TRIGGER {trigger_name} ON cf.{table}")
                conn.execute(f"DROP FUNCTION cf.{trigger_name}()")
                conn.commit()

            monkeypatch.setattr(
                mod,
                "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT",
                "5min",
            )
        finally:
            conn.close()

        reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            assert (
                _authority_scoped_identity_operation(
                    reader,
                    production_authority_scoped_identity_db,
                    "preflight",
                )["state"]
                == "partial_resumable"
            )
        finally:
            reader.close()

        resumed = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            assert (
                _authority_scoped_identity_operation(
                    resumed,
                    production_authority_scoped_identity_db,
                    "apply",
                )["state"]
                == "applied_verified"
            )
            assert mod._authority_scoped_identity_ledger_count(resumed) == 1
            assert resumed.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == (None,)
            for table, _target_prefix, native_column, expected_native_ids in cases:
                assert resumed.execute(f"SELECT {native_column} FROM cf.{table} ORDER BY id").fetchall() == [
                    (value,) for value in expected_native_ids
                ]
        finally:
            resumed.close()

    @pytest.mark.parametrize(
        "unsafe",
        ["missing", "symlink", "digest", "transaction_control"],
    )
    def test_pinned_domain_artifact_refuses_every_unsafe_shape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        unsafe: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        target = tmp_path / mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION
        if unsafe == "symlink":
            target.symlink_to(mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH)
        elif unsafe != "missing":
            payload = {
                "digest": b"SELECT 1;\n",
                "transaction_control": b"BEGIN;\nSELECT 1;\nCOMMIT;\n",
            }[unsafe]
            target.write_bytes(payload)
            if unsafe != "digest":
                monkeypatch.setattr(
                    mod,
                    "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                )
        monkeypatch.setattr(mod, "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH", target)

        with pytest.raises(ValueError):
            mod._load_pinned_authority_scoped_identity_sql()

    def test_pinned_domain_artifact_digest_matches_the_frozen_migration(self) -> None:
        import core.schema.apply_migrations as mod

        assert hashlib.sha256(mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH.read_bytes()).hexdigest() == (
            mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256
        )
        sql = mod._load_pinned_authority_scoped_identity_sql()
        assert sql == mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH.read_text(encoding="utf-8")
        assert "CREATE UNIQUE INDEX CONCURRENTLY" in sql
        assert "civibus-phase:" in sql

    def test_read_only_pending_preflight_then_apply_verify_and_idempotent_reapply(
        self,
        production_authority_scoped_identity_db: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            before = reader.execute("SELECT COUNT(*) FROM core.schema_migrations").fetchone()
            preflight = _authority_scoped_identity_operation(
                reader,
                production_authority_scoped_identity_db,
                "preflight",
            )
            after = reader.execute("SELECT COUNT(*) FROM core.schema_migrations").fetchone()
            assert preflight["state"] == "pending_absent"
            assert preflight["database_identity"]["transaction_read_only"] == "on"
            assert before == after
        finally:
            reader.close()

        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            applied = _authority_scoped_identity_operation(
                writer,
                production_authority_scoped_identity_db,
                "apply",
            )
            assert applied == {
                "database_identity": applied["database_identity"],
                "migration": mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,
                "migration_sha256": mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_SHA256,
                "state": "applied_verified",
            }
            first_receipt = writer.execute(
                "SELECT applied_at FROM core.schema_migrations WHERE filename = %s",
                (mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,),
            ).fetchone()
        finally:
            writer.close()

        verifier = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            verified = _authority_scoped_identity_operation(
                verifier,
                production_authority_scoped_identity_db,
                "verify",
            )
            assert verified["state"] == "applied_verified"
            assert verified["database_identity"]["transaction_read_only"] == "on"
            assert verifier.execute(
                "SELECT filing_authority_type, filing_authority_code FROM core.data_source"
            ).fetchall() == [("federal", "FEC")]
            assert verifier.execute(
                """
                SELECT committee.native_committee_id,
                       candidate.native_candidate_id,
                       filing.native_filing_id,
                       transaction.native_transaction_id
                FROM cf.committee committee
                CROSS JOIN cf.candidate candidate
                CROSS JOIN cf.filing filing
                CROSS JOIN cf.transaction transaction
                """
            ).fetchone() == ("C001", "H0AA00001", "F001", "fixture-native-record")
        finally:
            verifier.close()

        idempotent_writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            repeated = _authority_scoped_identity_operation(
                idempotent_writer,
                production_authority_scoped_identity_db,
                "apply",
            )
            second_receipt = idempotent_writer.execute(
                "SELECT applied_at FROM core.schema_migrations WHERE filename = %s",
                (mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,),
            ).fetchone()
            assert repeated["state"] == "already_applied_verified"
            assert second_receipt == first_receipt
        finally:
            idempotent_writer.close()

    def test_post_commit_verify_uses_local_limits_and_restores_session_timeout(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            assert (
                _authority_scoped_identity_operation(
                    writer,
                    production_authority_scoped_identity_db,
                    "apply",
                )["state"]
                == "applied_verified"
            )
        finally:
            writer.close()

        verifier = _production_connection(production_authority_scoped_identity_db, read_only=True)
        real_terminal_backfill_proof = mod._require_authority_scoped_identity_backfills_complete
        terminal_calls = 0

        def assert_local_limits_then_prove(actual_conn: psycopg.Connection) -> None:
            nonlocal terminal_calls
            terminal_calls += 1
            assert actual_conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
            assert actual_conn.execute("SHOW statement_timeout").fetchone() == ("15min",)
            assert actual_conn.execute("SHOW lock_timeout").fetchone() == ("5s",)
            real_terminal_backfill_proof(actual_conn)

        try:
            verifier.execute("SET statement_timeout = '42s'")
            verifier.commit()
            monkeypatch.setattr(
                mod,
                "_require_authority_scoped_identity_backfills_complete",
                assert_local_limits_then_prove,
            )

            result = _authority_scoped_identity_operation(
                verifier,
                production_authority_scoped_identity_db,
                "verify",
            )

            assert result["state"] == "applied_verified"
            assert terminal_calls == 1
            assert verifier.execute("SHOW statement_timeout").fetchone() == ("42s",)
        finally:
            verifier.close()

    def test_post_commit_verify_timeout_fails_closed_and_restores_session_state(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            _authority_scoped_identity_operation(writer, production_authority_scoped_identity_db, "apply")
        finally:
            writer.close()

        verifier = _production_connection(production_authority_scoped_identity_db, read_only=True)
        real_terminal_backfill_proof = mod._require_authority_scoped_identity_backfills_complete

        def applied_snapshot(conn: psycopg.Connection) -> tuple[object, ...]:
            ledger = conn.execute(
                "SELECT filename, applied_at FROM core.schema_migrations WHERE filename = %s ORDER BY filename",
                (mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,),
            ).fetchall()
            catalog = conn.execute(
                """
                SELECT namespace.nspname, relation.relname, relation.relkind,
                       pg_get_userbyid(relation.relowner)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname IN ('core', 'cf')
                ORDER BY namespace.nspname, relation.relname, relation.relkind
                """
            ).fetchall()
            constraints = conn.execute(
                """
                SELECT constraint_row.conrelid::regclass::text,
                       constraint_row.conname,
                       constraint_row.contype,
                       constraint_row.convalidated,
                       constraint_row.conenforced,
                       pg_get_constraintdef(constraint_row.oid, true)
                FROM pg_constraint AS constraint_row
                JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname IN ('core', 'cf')
                ORDER BY constraint_row.conrelid::regclass::text, constraint_row.conname
                """
            ).fetchall()
            data = conn.execute(
                """
                SELECT 'committee', id::text, data_source_id::text, native_committee_id
                FROM cf.committee
                UNION ALL
                SELECT 'candidate', id::text, data_source_id::text, native_candidate_id
                FROM cf.candidate
                UNION ALL
                SELECT 'filing', id::text, data_source_id::text, native_filing_id
                FROM cf.filing
                UNION ALL
                SELECT 'transaction', id::text, data_source_id::text, native_transaction_id
                FROM cf.transaction
                ORDER BY 1, 2
                """
            ).fetchall()
            return ledger, catalog, constraints, data

        def delay_before_terminal_proof(actual_conn: psycopg.Connection) -> None:
            actual_conn.execute("SELECT pg_sleep(1)")
            real_terminal_backfill_proof(actual_conn)

        try:
            verifier.execute("SET statement_timeout = '42s'")
            verifier.commit()
            before = applied_snapshot(verifier)
            verifier.rollback()
            monkeypatch.setattr(
                mod,
                "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT",
                "100ms",
            )
            monkeypatch.setattr(
                mod,
                "_require_authority_scoped_identity_backfills_complete",
                delay_before_terminal_proof,
            )

            with pytest.raises(psycopg.errors.QueryCanceled, match="statement timeout"):
                _authority_scoped_identity_operation(
                    verifier,
                    production_authority_scoped_identity_db,
                    "verify",
                )

            assert verifier.execute("SHOW statement_timeout").fetchone() == ("42s",)
            assert verifier.execute("SELECT 1").fetchone() == (1,)
            after = applied_snapshot(verifier)
            assert after == before
            assert len(after[0]) == 1
            assert verifier.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == (None,)
            monkeypatch.setattr(
                mod,
                "_require_authority_scoped_identity_backfills_complete",
                real_terminal_backfill_proof,
            )
            mod._require_authority_scoped_identity_applied_shape(verifier)
        finally:
            verifier.close()

    def test_main_reports_verify_timeout_without_success_json(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import core.schema.apply_migrations as mod

        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            _authority_scoped_identity_operation(writer, production_authority_scoped_identity_db, "apply")
        finally:
            writer.close()

        verifier = _production_connection(production_authority_scoped_identity_db, read_only=True)
        real_terminal_backfill_proof = mod._require_authority_scoped_identity_backfills_complete

        def delay_before_terminal_proof(actual_conn: psycopg.Connection) -> None:
            actual_conn.execute("SELECT pg_sleep(1)")
            real_terminal_backfill_proof(actual_conn)

        verifier.execute("SET statement_timeout = '42s'")
        verifier.commit()
        monkeypatch.setattr(mod, "get_connection", lambda: verifier)
        monkeypatch.setattr(mod, "_require_production_identity", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(
            mod,
            "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_INDEX_STATEMENT_TIMEOUT",
            "100ms",
        )
        monkeypatch.setattr(
            mod,
            "_require_authority_scoped_identity_backfills_complete",
            delay_before_terminal_proof,
        )

        result = mod.main(
            [
                "--production-authority-scoped-identity",
                "verify",
                "--expected-host",
                "127.0.0.1",
                "--expected-port",
                "16548",
                "--expected-database",
                "civibus",
            ]
        )
        captured = capsys.readouterr()

        assert result == 1
        assert captured.out == ""
        assert "statement timeout" in captured.err
        assert '"state"' not in captured.out

    def test_owner_never_scans_the_domain_migration_directory(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        domain_migrations = mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_PATH.parent
        real_iterdir = Path.iterdir

        def refuse_domain_scan(path: Path):
            if path == domain_migrations:
                raise AssertionError("the exact domain owner must not scan sibling migrations")
            return real_iterdir(path)

        monkeypatch.setattr(Path, "iterdir", refuse_domain_scan)
        reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            assert (
                _authority_scoped_identity_operation(
                    reader,
                    production_authority_scoped_identity_db,
                    "preflight",
                )["state"]
                == "pending_absent"
            )
        finally:
            reader.close()

    @pytest.mark.parametrize(
        ("operation", "read_only", "identity_drift"),
        [
            ("preflight", False, None),
            ("apply", True, None),
            ("verify", True, "host"),
            ("verify", True, "port"),
            ("verify", True, "database"),
        ],
    )
    def test_operation_refuses_wrong_read_mode_or_connection_identity_before_change(
        self,
        production_authority_scoped_identity_db: str,
        operation: str,
        read_only: bool,
        identity_drift: str | None,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_authority_scoped_identity_db, read_only=read_only)
        try:
            with pytest.raises(ValueError):
                mod._run_production_authority_scoped_identity_operation(
                    conn,
                    operation=operation,
                    expected_host="wrong" if identity_drift == "host" else conn.info.host,
                    expected_port=1 if identity_drift == "port" else int(conn.info.port),
                    expected_database=(
                        "wrong" if identity_drift == "database" else production_authority_scoped_identity_db
                    ),
                )
            assert mod._authority_scoped_identity_ledger_count(conn) == 0
        finally:
            conn.close()

    @pytest.mark.parametrize("blocker", ["unrelated_pending", "running_refresh"])
    def test_preflight_refuses_unrelated_pending_or_active_refresh_writer(
        self,
        production_authority_scoped_identity_db: str,
        blocker: str,
    ) -> None:
        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            if blocker == "unrelated_pending":
                filename = writer.execute(
                    "SELECT filename FROM core.schema_migrations ORDER BY filename LIMIT 1"
                ).fetchone()[0]
                writer.execute("DELETE FROM core.schema_migrations WHERE filename = %s", (filename,))
            else:
                writer.execute(
                    """
                    INSERT INTO core.refresh_run (
                        job_key, domain, jurisdiction, pull_status, started_at, completed_at, message
                    ) VALUES ('running', 'campaign_finance', 'state/WA', 'running', now(), NULL, 'fixture')
                    """
                )
            writer.commit()
        finally:
            writer.close()

        reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            with pytest.raises(ValueError, match="unrelated pending|running refresh"):
                _authority_scoped_identity_operation(
                    reader,
                    production_authority_scoped_identity_db,
                    "preflight",
                )
        finally:
            reader.close()

    def test_apply_refuses_advisory_lock_contention_without_change(
        self,
        production_authority_scoped_identity_db: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        holder = _production_connection(production_authority_scoped_identity_db, read_only=False)
        worker = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            assert holder.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                (mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_LOCK_NAME,),
            ).fetchone() == (True,)
            with pytest.raises(ValueError, match="holds the lock"):
                _authority_scoped_identity_operation(worker, production_authority_scoped_identity_db, "apply")
            assert mod._authority_scoped_identity_ledger_count(worker) == 0
            assert worker.execute(
                """
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = 'core' AND table_name = 'data_source'
                  AND column_name LIKE 'filing_authority_%'
                """
            ).fetchone() == (0,)
        finally:
            worker.close()
            holder.close()

    @pytest.mark.parametrize(
        "verifier_name",
        [
            "_require_authority_scoped_identity_semantics",
            "_require_authority_scoped_identity_backfills_complete",
        ],
    )
    def test_exhaustive_pre_cutover_failure_blocks_every_cutover_ddl(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
        verifier_name: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        def fail_after_pre_cutover_proof(conn: psycopg.Connection) -> None:
            assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
            catalog = mod._authority_scoped_identity_index_catalog(conn)
            assert len(catalog) == 9
            assert all(bool(shape[2]) and bool(shape[3]) for shape in catalog.values())
            assert conn.execute(
                """
                SELECT COUNT(*)
                FROM pg_constraint
                WHERE conname = ANY(%s) AND convalidated
                """,
                ([name for _relation, name in mod._AUTHORITY_SCOPED_CONSTRAINT_DEFINITION_SHA256],),
            ).fetchone() == (12,)
            assert mod._authority_scoped_identity_ledger_count(conn) == 0
            assert conn.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == ("core.authority_scoped_identity_migration_progress",)
            raise RuntimeError("injected pre-cutover exhaustive mismatch")

        monkeypatch.setattr(mod, verifier_name, fail_after_pre_cutover_proof)
        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            with pytest.raises(RuntimeError, match="pre-cutover exhaustive mismatch"):
                _authority_scoped_identity_operation(conn, production_authority_scoped_identity_db, "apply")
            conn.rollback()
            assert mod._authority_scoped_identity_ledger_count(conn) == 0
            assert conn.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == ("core.authority_scoped_identity_migration_progress",)
            assert conn.execute("SELECT to_regclass('core.idx_data_source_dedup_pre_authority')").fetchone() == (
                "core.idx_data_source_dedup_pre_authority",
            )
            assert conn.execute("SELECT to_regclass('cf.uq_transaction_sub_id_pre_authority')").fetchone() == (
                "cf.uq_transaction_sub_id_pre_authority",
            )
        finally:
            conn.close()

    def test_injected_atomic_catalog_mismatch_rolls_back_and_terminal_cursors_resume(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        real_verify = mod._require_authority_scoped_identity_atomic_shape

        def fail_after_exact_verification(conn: psycopg.Connection) -> None:
            real_verify(conn)
            assert conn.execute("SHOW transaction_read_only").fetchone() == ("off",)
            assert mod._authority_scoped_identity_ledger_count(conn) == 1
            assert conn.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == (None,)
            raise RuntimeError("injected mismatch after exact catalog verification")

        monkeypatch.setattr(
            mod,
            "_require_authority_scoped_identity_atomic_shape",
            fail_after_exact_verification,
        )
        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            with pytest.raises(RuntimeError, match="injected mismatch"):
                _authority_scoped_identity_operation(conn, production_authority_scoped_identity_db, "apply")
            conn.rollback()
            assert mod._authority_scoped_identity_ledger_count(conn) == 0
            assert conn.execute(
                """
                SELECT COUNT(*) FROM information_schema.columns
                WHERE (table_schema, table_name, column_name) IN (
                    ('core', 'data_source', 'filing_authority_type'),
                    ('core', 'data_source', 'filing_authority_code'),
                    ('cf', 'committee', 'data_source_id'),
                    ('cf', 'committee', 'native_committee_id'),
                    ('cf', 'candidate', 'data_source_id'),
                    ('cf', 'candidate', 'native_candidate_id'),
                    ('cf', 'filing', 'data_source_id'),
                    ('cf', 'filing', 'native_filing_id'),
                    ('cf', 'transaction', 'data_source_id'),
                    ('cf', 'transaction', 'native_transaction_id')
                )
                """
            ).fetchone() == (10,)
            assert conn.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == ("core.authority_scoped_identity_migration_progress",)
            catalog = mod._authority_scoped_identity_index_catalog(conn)
            assert len(catalog) == 9
            assert all(bool(shape[2]) and bool(shape[3]) for shape in catalog.values())
            assert conn.execute(
                """
                SELECT COUNT(*), COUNT(last_id)
                FROM core.authority_scoped_identity_migration_progress
                """
            ).fetchone() == (4, 4)
            assert conn.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT 1 FROM cf.committee
                    WHERE id > (SELECT last_id FROM core.authority_scoped_identity_migration_progress
                                WHERE target_relation = 'cf.committee')
                    UNION ALL
                    SELECT 1 FROM cf.candidate
                    WHERE id > (SELECT last_id FROM core.authority_scoped_identity_migration_progress
                                WHERE target_relation = 'cf.candidate')
                    UNION ALL
                    SELECT 1 FROM cf.filing
                    WHERE id > (SELECT last_id FROM core.authority_scoped_identity_migration_progress
                                WHERE target_relation = 'cf.filing')
                    UNION ALL
                    SELECT 1 FROM cf.transaction
                    WHERE id > (SELECT last_id FROM core.authority_scoped_identity_migration_progress
                                WHERE target_relation = 'cf.transaction')
                ) AS remaining_after_terminal_cursor
                """
            ).fetchone() == (0,)
            assert conn.execute(
                """
                SELECT COUNT(*)
                FROM pg_constraint
                WHERE conname = ANY(%s) AND convalidated
                """,
                ([name for _relation, name in mod._AUTHORITY_SCOPED_CONSTRAINT_DEFINITION_SHA256],),
            ).fetchone() == (12,)
        finally:
            conn.close()

        reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            assert (
                _authority_scoped_identity_operation(
                    reader,
                    production_authority_scoped_identity_db,
                    "preflight",
                )["state"]
                == "partial_resumable"
            )
        finally:
            reader.close()

        monkeypatch.setattr(mod, "_require_authority_scoped_identity_atomic_shape", real_verify)
        resumed = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            assert (
                _authority_scoped_identity_operation(
                    resumed,
                    production_authority_scoped_identity_db,
                    "apply",
                )["state"]
                == "applied_verified"
            )
            assert mod._authority_scoped_identity_ledger_count(resumed) == 1
            assert resumed.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == (None,)
        finally:
            resumed.close()

    def test_concurrent_access_share_reader_finishes_while_exhaustive_scan_is_paused(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        real_semantics = mod._require_authority_scoped_identity_semantics
        scan_started = threading.Event()
        release_scan = threading.Event()
        worker_results: list[dict[str, object]] = []
        worker_errors: list[BaseException] = []

        def paused_semantics(conn: psycopg.Connection) -> None:
            assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
            conn.execute("LOCK TABLE cf.transaction IN ACCESS SHARE MODE")
            scan_started.set()
            if not release_scan.wait(timeout=10):
                raise AssertionError("test did not release the exhaustive verifier")
            real_semantics(conn)

        def run_apply() -> None:
            worker = _production_connection(production_authority_scoped_identity_db, read_only=False)
            try:
                worker_results.append(
                    _authority_scoped_identity_operation(
                        worker,
                        production_authority_scoped_identity_db,
                        "apply",
                    )
                )
            except BaseException as exc:  # surfaced on the test thread below
                worker_errors.append(exc)
            finally:
                worker.close()

        monkeypatch.setattr(mod, "_require_authority_scoped_identity_semantics", paused_semantics)
        apply_thread = threading.Thread(target=run_apply, name="r29-authority-apply")
        apply_thread.start()
        reader_error: BaseException | None = None
        try:
            assert scan_started.wait(timeout=10), worker_errors
            reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
            try:
                reader.execute("SET LOCAL statement_timeout = '500ms'")
                assert reader.execute("SELECT COUNT(*) FROM cf.transaction").fetchone() == (1,)
            except BaseException as exc:  # release the paused owner before asserting
                reader_error = exc
            finally:
                reader.close()
        finally:
            release_scan.set()
            apply_thread.join(timeout=10)

        assert not apply_thread.is_alive()
        assert reader_error is None
        assert worker_errors == []
        assert worker_results[0]["state"] == "applied_verified"

    def test_batch_timeout_preserves_a_safe_checkpoint_and_reapply_resumes_to_exact_completion(
        self,
        production_authority_scoped_identity_db: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import core.schema.apply_migrations as mod

        conn = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            conn.execute(
                """
                INSERT INTO core.source_record (
                    id, data_source_id, source_record_key, raw_fields, pull_date
                ) VALUES
                    ('20000000-0000-4000-8000-000000000002',
                     '10000000-0000-4000-8000-000000000001',
                     'fixture-native-record-2', '{}'::jsonb, now()),
                    ('20000000-0000-4000-8000-000000000003',
                     '10000000-0000-4000-8000-000000000001',
                     'fixture-native-record-3', '{}'::jsonb, now());
                INSERT INTO cf.transaction (
                    id, sub_id, transaction_identifier, source_record_id
                ) VALUES
                    ('60000000-0000-4000-8000-000000000002', 2, 'T002',
                     '20000000-0000-4000-8000-000000000002'),
                    ('60000000-0000-4000-8000-000000000003', 3, 'T003',
                     '20000000-0000-4000-8000-000000000003');
                CREATE FUNCTION cf.r20_sleep_on_second_transaction()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.id = '60000000-0000-4000-8000-000000000002'::uuid THEN
                        PERFORM pg_sleep(2);
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER r20_sleep_on_second_transaction
                BEFORE UPDATE ON cf.transaction
                FOR EACH ROW EXECUTE FUNCTION cf.r20_sleep_on_second_transaction();
                """
            )
            conn.commit()
            monkeypatch.setattr(
                mod,
                "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_SIZE",
                1,
                raising=False,
            )
            monkeypatch.setattr(
                mod,
                "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT",
                "250ms",
                raising=False,
            )

            with pytest.raises(psycopg.errors.QueryCanceled, match="statement timeout"):
                _authority_scoped_identity_operation(conn, production_authority_scoped_identity_db, "apply")
            conn.rollback()

            assert mod._authority_scoped_identity_ledger_count(conn) == 0
            assert conn.execute(
                """
                SELECT COUNT(*) FROM information_schema.columns
                WHERE (table_schema, table_name, column_name) IN (
                    ('core', 'data_source', 'filing_authority_type'),
                    ('core', 'data_source', 'filing_authority_code'),
                    ('cf', 'committee', 'data_source_id'),
                    ('cf', 'committee', 'native_committee_id'),
                    ('cf', 'candidate', 'data_source_id'),
                    ('cf', 'candidate', 'native_candidate_id'),
                    ('cf', 'filing', 'data_source_id'),
                    ('cf', 'filing', 'native_filing_id'),
                    ('cf', 'transaction', 'data_source_id'),
                    ('cf', 'transaction', 'native_transaction_id')
                )
                """
            ).fetchone() == (10,)
            assert conn.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == ("core.authority_scoped_identity_migration_progress",)
            assert conn.execute(
                """
                SELECT native_transaction_id
                FROM cf.transaction
                WHERE id = '60000000-0000-4000-8000-000000000001'
                """
            ).fetchone() == ("fixture-native-record",)
            assert conn.execute(
                """
                SELECT native_transaction_id
                FROM cf.transaction
                WHERE id = '60000000-0000-4000-8000-000000000002'
                """
            ).fetchone() == (None,)

            conn.execute("DROP TRIGGER r20_sleep_on_second_transaction ON cf.transaction")
            conn.execute("DROP FUNCTION cf.r20_sleep_on_second_transaction()")
            conn.commit()
            monkeypatch.setattr(
                mod,
                "_PRODUCTION_AUTHORITY_SCOPED_IDENTITY_BATCH_STATEMENT_TIMEOUT",
                "5min",
                raising=False,
            )
        finally:
            conn.close()

        reader = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            assert (
                _authority_scoped_identity_operation(
                    reader,
                    production_authority_scoped_identity_db,
                    "preflight",
                )["state"]
                == "partial_resumable"
            )
        finally:
            reader.close()

        resumed = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            assert (
                _authority_scoped_identity_operation(
                    resumed,
                    production_authority_scoped_identity_db,
                    "apply",
                )["state"]
                == "applied_verified"
            )
            assert mod._authority_scoped_identity_ledger_count(resumed) == 1
            assert resumed.execute(
                "SELECT to_regclass('core.authority_scoped_identity_migration_progress')"
            ).fetchone() == (None,)
            assert resumed.execute("SELECT native_transaction_id FROM cf.transaction ORDER BY id").fetchall() == [
                ("fixture-native-record",),
                ("fixture-native-record-2",),
                ("fixture-native-record-3",),
            ]
        finally:
            resumed.close()

    @pytest.mark.parametrize(
        "drift",
        ["ledger", "column", "constraint", "index", "trigger", "trigger_function", "view"],
    )
    def test_read_only_verify_refuses_every_catalog_or_ledger_mismatch(
        self,
        production_authority_scoped_identity_db: str,
        drift: str,
    ) -> None:
        import core.schema.apply_migrations as mod

        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            _authority_scoped_identity_operation(writer, production_authority_scoped_identity_db, "apply")
            if drift == "ledger":
                writer.execute(
                    "DELETE FROM core.schema_migrations WHERE filename = %s",
                    (mod._PRODUCTION_AUTHORITY_SCOPED_IDENTITY_MIGRATION,),
                )
            elif drift == "column":
                writer.execute("ALTER TABLE core.data_source ALTER COLUMN filing_authority_code SET DEFAULT ''")
            elif drift == "constraint":
                writer.execute("ALTER TABLE core.data_source DROP CONSTRAINT ck_data_source_filing_authority_code")
            elif drift == "index":
                writer.execute("DROP INDEX cf.uq_transaction_authority_native_id")
            elif drift == "trigger":
                writer.execute(
                    "ALTER TABLE core.data_source DISABLE TRIGGER trg_data_source_campaign_finance_filing_authority"
                )
            elif drift == "trigger_function":
                writer.execute(
                    """
                    CREATE OR REPLACE FUNCTION cf.enforce_source_record_scope()
                    RETURNS TRIGGER AS $$ BEGIN RETURN NULL; END; $$ LANGUAGE plpgsql
                    """
                )
            else:
                writer.execute("DROP VIEW core.person_er_view")
            writer.commit()
        finally:
            writer.close()

        verifier = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            with pytest.raises(ValueError):
                _authority_scoped_identity_operation(
                    verifier,
                    production_authority_scoped_identity_db,
                    "verify",
                )
        finally:
            verifier.close()

    def test_post_commit_read_only_verify_remains_exhaustive_for_bad_data(
        self,
        production_authority_scoped_identity_db: str,
    ) -> None:
        writer = _production_connection(production_authority_scoped_identity_db, read_only=False)
        try:
            _authority_scoped_identity_operation(writer, production_authority_scoped_identity_db, "apply")
            writer.execute(
                "ALTER TABLE core.data_source DISABLE TRIGGER trg_data_source_campaign_finance_filing_authority"
            )
            writer.execute("UPDATE core.data_source SET filing_authority_code = 'fec'")
            writer.execute(
                "ALTER TABLE core.data_source ENABLE TRIGGER trg_data_source_campaign_finance_filing_authority"
            )
            writer.commit()
        finally:
            writer.close()

        verifier = _production_connection(production_authority_scoped_identity_db, read_only=True)
        try:
            with pytest.raises(ValueError, match="semantic verification"):
                _authority_scoped_identity_operation(
                    verifier,
                    production_authority_scoped_identity_db,
                    "verify",
                )
        finally:
            verifier.close()


class TestApplyMigrations:
    """KAT: baseline adoption + selective delta application on the old prod shape."""

    def test_authority_runbook_separates_exhaustive_proof_from_atomic_cutover(self) -> None:
        runbook = (REPO_ROOT / "docs/howto/operations/campaign-finance-refresh.md").read_text(encoding="utf-8")
        procedure = runbook.split("## Production authority-scoped identity migration owner", 1)[1].split(
            "## Authority-scoped regional scheduled-Machine profile", 1
        )[0]
        normalized = " ".join(procedure.split())

        assert "separate `READ ONLY` pre-cutover transaction" in normalized
        assert "all nine expected indexes are valid and ready" in normalized
        assert "all twelve checks are validated" in normalized
        assert "It performs no domain table scan while holding cutover locks" in normalized
        assert "post-commit `verify` invocation stays read-only and exhaustive" in normalized

    def test_production_runbook_mechanically_chains_preflight_apply_and_verify(self) -> None:
        runbook = (REPO_ROOT / "docs/howto/operations/campaign-finance-refresh.md").read_text(encoding="utf-8")
        procedure = runbook.split("## Production execution-origin migration owner", 1)[1].split(
            "## Frozen regional scheduled-Machine profile", 1
        )[0]
        shell = procedure.split("```bash", 1)[1].split("```", 1)[0]
        assert shell.count("--production-execution-origin") == 3
        assert shell.count("--expected-host 127.0.0.1") == 3
        assert shell.count('--expected-port "$CIVIBUS_PROBE_PORT"') == 3
        assert shell.count("--expected-database civibus") == 3
        assert shell.count("&&") == 5
        assert (
            shell.index("--production-execution-origin preflight")
            < shell.index("--production-execution-origin apply")
            < shell.index("--production-execution-origin verify")
        )

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

    def test_typed_jurisdiction_identity_migration_is_pending_delta(
        self,
        fixture_paths: dict[str, Path],
    ) -> None:
        assert _TYPED_JURISDICTION_IDENTITY_MIGRATION in _PENDING_FILENAMES
        assert _TYPED_JURISDICTION_IDENTITY_MIGRATION not in _BASELINE_ENTRIES
        assert (fixture_paths["migrations_dir"] / _TYPED_JURISDICTION_IDENTITY_MIGRATION).is_file()

    def test_typed_jurisdiction_identity_upgrades_only_unambiguous_legacy_rows(
        self,
        disposable_db: str,
        fixture_paths: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert _run_main(disposable_db, fixture_paths, monkeypatch) == 0
        conn = _connect_to(disposable_db)
        try:
            rows = conn.execute(
                """
                SELECT name, fips, state_fips, county_geoid, place_geoid
                FROM core.jurisdiction
                """
            ).fetchall()
            # Row order follows the database collation; the migration owns the
            # exact legacy-name-to-typed-identity mapping, not presentation order.
            rows_by_name = {
                name: (fips, state_fips, county_geoid, place_geoid)
                for name, fips, state_fips, county_geoid, place_geoid in rows
            }
            assert len(rows_by_name) == len(rows)
            assert rows_by_name == {
                "Durham County": ("37063", None, "37063", None),
                "Legacy Unicode state": ("٣٧", None, None, None),
                "Legacy five digit municipality": ("36510", None, None, None),
                "Legacy seven digit municipality": ("0644000", None, None, "0644000"),
                "Legacy short county": ("3706", None, None, None),
                "North Carolina": ("37", "37", None, None),
            }

            columns = conn.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'core'
                  AND table_name = 'jurisdiction'
                  AND column_name IN ('state_fips', 'county_geoid', 'place_geoid')
                ORDER BY column_name
                """
            ).fetchall()
            assert columns == [
                ("county_geoid", "text", "YES"),
                ("place_geoid", "text", "YES"),
                ("state_fips", "text", "YES"),
            ]
            constraint_names = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'core.jurisdiction'::regclass
                    """
                ).fetchall()
            }
            assert {
                "ck_jurisdiction_state_fips",
                "ck_jurisdiction_county_geoid",
                "ck_jurisdiction_place_geoid",
            } <= constraint_names
            index_names = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'core'
                      AND tablename = 'jurisdiction'
                    """
                ).fetchall()
            }
            assert {
                "idx_jurisdiction_state_fips_unique",
                "idx_jurisdiction_county_geoid_unique",
                "idx_jurisdiction_place_geoid_unique",
            } <= index_names
        finally:
            conn.close()

    def test_typed_jurisdiction_identity_migration_replays_on_fresh_schema_without_drift(
        self,
        fresh_jurisdiction_db: str,
    ) -> None:
        migration_sql = (
            REPO_ROOT / "core" / "schema" / "migrations" / _TYPED_JURISDICTION_IDENTITY_MIGRATION
        ).read_text(encoding="utf-8")
        conn = _connect_to(fresh_jurisdiction_db)
        try:
            before = _typed_jurisdiction_snapshot(conn)
            conn.execute(migration_sql)
            after_first_replay = _typed_jurisdiction_snapshot(conn)
            conn.execute(migration_sql)
            after_second_replay = _typed_jurisdiction_snapshot(conn)
            assert after_first_replay == before
            assert after_second_replay == before
        finally:
            conn.rollback()
            conn.close()

    def test_refresh_run_execution_origin_migration_is_pending_delta(
        self,
        fixture_paths: dict[str, Path],
    ) -> None:
        assert _REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION in _PENDING_FILENAMES
        assert _REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION not in _BASELINE_ENTRIES
        assert (fixture_paths["migrations_dir"] / _REFRESH_RUN_EXECUTION_ORIGIN_MIGRATION).is_file()

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

    def test_refresh_run_execution_origin_migration_backfills_and_preserves_old_writers(
        self, legacy_refresh_run_db: str, fixture_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = _connect_to(legacy_refresh_run_db)
        try:
            with before.cursor() as cur:
                _insert_refresh_run(cur, pull_status="success", completed_at=_COMPLETED_AT)
            before.commit()
        finally:
            before.close()

        assert _run_main(legacy_refresh_run_db, fixture_paths, monkeypatch) == 0
        conn = _connect_to(legacy_refresh_run_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT execution_origin FROM core.refresh_run")
                assert cur.fetchall() == [("legacy_unknown",)]

                cur.execute(
                    "INSERT INTO core.refresh_run (pull_status, completed_at) "
                    "VALUES ('success', %s) RETURNING execution_origin",
                    (_COMPLETED_AT,),
                )
                assert cur.fetchone() == ("legacy_unknown",)
                conn.rollback()

                for execution_origin in ("scheduled", "operator_attended", "legacy_unknown"):
                    cur.execute(
                        "INSERT INTO core.refresh_run (pull_status, completed_at, execution_origin) "
                        "VALUES ('success', %s, %s)",
                        (_COMPLETED_AT, execution_origin),
                    )
                    conn.rollback()

                with pytest.raises(psycopg.errors.NotNullViolation):
                    cur.execute(
                        "INSERT INTO core.refresh_run (pull_status, completed_at, execution_origin) "
                        "VALUES ('success', %s, NULL)",
                        (_COMPLETED_AT,),
                    )
                conn.rollback()

                with pytest.raises(psycopg.errors.CheckViolation) as exc_info:
                    cur.execute(
                        "INSERT INTO core.refresh_run (pull_status, completed_at, execution_origin) "
                        "VALUES ('success', %s, 'cron')",
                        (_COMPLETED_AT,),
                    )
                assert exc_info.value.diag.constraint_name == "refresh_run_execution_origin_check"
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
        assert _run_main(disposable_db, fixture_paths, monkeypatch) == 0
        migrated = _connect_to(disposable_db)
        fresh = _connect_to(provenance_shape_db)
        try:
            assert _refresh_run_check_constraints(migrated) == _refresh_run_check_constraints(fresh)
            assert _refresh_run_completed_at_is_nullable(migrated)
            assert _refresh_run_completed_at_is_nullable(fresh)
            assert _refresh_run_execution_origin_shape(migrated) == _refresh_run_execution_origin_shape(fresh)
            assert _refresh_run_execution_origin_shape(fresh) == (
                "text",
                "NO",
                "'legacy_unknown'::text",
            )
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

    def test_typed_jurisdiction_migration_rolls_back_on_dirty_preexisting_typed_data(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_name = _create_database()
        try:
            conn = _connect_to(db_name)
            try:
                conn.autocommit = True
                conn.execute(_MINIMAL_CORE_SQL)
                conn.execute(_MINIMAL_CF_SQL)
                conn.execute(
                    """
                    CREATE TABLE core.jurisdiction (
                        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                        name TEXT NOT NULL,
                        jurisdiction_type TEXT NOT NULL,
                        fips TEXT,
                        state_fips TEXT
                    );
                    INSERT INTO core.jurisdiction (name, jurisdiction_type, fips, state_fips)
                    VALUES
                        ('Valid legacy state', 'state', '37', NULL),
                        ('Dirty county', 'county', '37063', '37');
                    """
                )
            finally:
                conn.close()

            baseline_path = tmp_path / "migrations_baseline.txt"
            baseline_path.write_text("", encoding="utf-8")
            migrations_dir = tmp_path / "migrations"
            migrations_dir.mkdir()
            source_migration = REPO_ROOT / "core" / "schema" / "migrations" / _TYPED_JURISDICTION_IDENTITY_MIGRATION
            shutil.copy2(source_migration, migrations_dir / source_migration.name)

            result = _run_main(
                db_name,
                {"baseline": baseline_path, "migrations_dir": migrations_dir},
                monkeypatch,
            )
            assert result != 0

            conn = _connect_to(db_name)
            try:
                rows = conn.execute(
                    """
                    SELECT name, fips, state_fips
                    FROM core.jurisdiction
                    ORDER BY name
                    """
                ).fetchall()
                assert rows == [
                    ("Dirty county", "37063", "37"),
                    ("Valid legacy state", "37", None),
                ]
                added_columns = conn.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'core'
                      AND table_name = 'jurisdiction'
                      AND column_name IN ('county_geoid', 'place_geoid')
                    """
                ).fetchall()
                assert added_columns == []
                new_constraints = conn.execute(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'core.jurisdiction'::regclass
                      AND conname LIKE 'ck_jurisdiction_%'
                    """
                ).fetchall()
                assert new_constraints == []
                new_indexes = conn.execute(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'core'
                      AND tablename = 'jurisdiction'
                      AND indexname LIKE 'idx_jurisdiction_%_unique'
                    """
                ).fetchall()
                assert new_indexes == []
                ledger_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM core.schema_migrations
                    WHERE filename = %s
                    """,
                    (_TYPED_JURISDICTION_IDENTITY_MIGRATION,),
                ).fetchone()[0]
                assert ledger_count == 0
            finally:
                conn.close()
        finally:
            _drop_database(db_name)


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
