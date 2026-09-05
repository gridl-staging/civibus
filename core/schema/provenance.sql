-- Provenance: Two-Layer Source Tracking
--
-- Layer 1: data_source — a registered origin of data (FEC bulk files, NC SBE portal, etc.)
-- Layer 2: source_record — an individual record from a source, linked to canonical entities
--
-- Migration order: 2 of 3 — run AFTER entities.sql, BEFORE entity_resolution.sql
--   Defines: data_source, source_record, entity_source, field_provenance tables
--   Also applies: entity_address.source_record_id FK (cross-file, depends on source_record)
--
-- Design principle (ADR 0006, adapted from FtM Statement model):
--   Every canonical entity links back to every raw source record that contributed to it.
--   A journalist can click any data point and trace it to the original government filing.

CREATE SCHEMA IF NOT EXISTS core;

-- ============================================================================
-- Data Source Registry
-- ============================================================================
-- Each data source is a registered origin: a bulk file, an API endpoint, a web portal.
-- Domain plugins register their sources here during ingest setup.

CREATE TABLE core.data_source (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain          TEXT NOT NULL,           -- 'campaign_finance', 'property', 'corporate', etc.
    jurisdiction    TEXT,                    -- 'federal/fec', 'states/nc', 'states/nc/counties/durham'
    filing_authority_type TEXT,              -- typed reporting authority; distinct from geography
    filing_authority_code TEXT,              -- authority-owned code paired with filing_authority_type
    name            TEXT NOT NULL,           -- Human-readable: "FEC Bulk Individual Contributions"
    source_url      TEXT NOT NULL,           -- Base URL or download page
    source_format   TEXT,                    -- csv, json, api, html, pdf
    license         TEXT,                    -- public_domain, cc_by, restricted, unknown
    update_frequency TEXT,                   -- daily, weekly, quarterly, annual, continuous, one_time
    last_pull_at    TIMESTAMPTZ,            -- When we last pulled data from this source
    last_pull_status TEXT,                   -- success, partial, failed
    record_count    BIGINT,                 -- Total records ingested from this source
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_data_source_filing_authority_pair
        CHECK ((filing_authority_type IS NULL) = (filing_authority_code IS NULL)),
    CONSTRAINT ck_data_source_filing_authority_type
        CHECK (
            filing_authority_type IS NULL
            OR filing_authority_type IN (
                'federal', 'state', 'county', 'municipality',
                'school_district', 'special_district', 'named_other'
            )
        ),
    CONSTRAINT ck_data_source_filing_authority_code_nonblank
        CHECK (filing_authority_code IS NULL OR btrim(filing_authority_code) <> ''),
    CONSTRAINT ck_campaign_finance_data_source_has_filing_authority
        CHECK (
            domain <> 'campaign_finance'
            OR (filing_authority_type IS NOT NULL AND filing_authority_code IS NOT NULL)
        )
);

CREATE INDEX idx_data_source_domain ON core.data_source (domain);
CREATE INDEX idx_data_source_jurisdiction ON core.data_source (jurisdiction);
CREATE UNIQUE INDEX idx_data_source_dedup
    ON core.data_source (domain, filing_authority_type, filing_authority_code, name)
    NULLS NOT DISTINCT;

-- Materialize typed identity for the finite set of legacy jurisdiction spellings
-- still used by existing source-package writers. Unknown and partially supplied
-- scopes remain NULL/invalid and are refused by the table constraints below.
CREATE OR REPLACE FUNCTION core.populate_campaign_finance_filing_authority()
RETURNS TRIGGER AS $$
DECLARE
    scope_type TEXT;
    scope_code TEXT;
BEGIN
    IF NEW.domain <> 'campaign_finance' THEN
        RETURN NEW;
    END IF;

    IF NEW.filing_authority_type IS NULL AND NEW.filing_authority_code IS NULL THEN
        IF lower(btrim(NEW.jurisdiction)) = 'federal' THEN
            NEW.filing_authority_type := 'federal';
            NEW.filing_authority_code := 'FEC';
        ELSIF position('/' IN NEW.jurisdiction) > 0 THEN
            scope_type := lower(btrim(split_part(NEW.jurisdiction, '/', 1)));
            scope_code := upper(btrim(substr(NEW.jurisdiction, position('/' IN NEW.jurisdiction) + 1)));
            scope_type := CASE scope_type
                WHEN 'states' THEN 'state'
                WHEN 'counties' THEN 'county'
                WHEN 'city' THEN 'municipality'
                WHEN 'cities' THEN 'municipality'
                WHEN 'schools' THEN 'school_district'
                WHEN 'school' THEN 'school_district'
                WHEN 'special' THEN 'special_district'
                ELSE scope_type
            END;
            IF scope_type IN (
                'federal', 'state', 'county', 'municipality',
                'school_district', 'special_district', 'named_other'
            ) AND scope_code <> '' THEN
                NEW.filing_authority_type := scope_type;
                NEW.filing_authority_code := scope_code;
            END IF;
        END IF;
    ELSIF NEW.filing_authority_type IS NOT NULL AND NEW.filing_authority_code IS NOT NULL THEN
        NEW.filing_authority_type := lower(btrim(NEW.filing_authority_type));
        NEW.filing_authority_code := upper(btrim(NEW.filing_authority_code));
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_data_source_campaign_finance_filing_authority
    BEFORE INSERT OR UPDATE OF domain, jurisdiction, filing_authority_type, filing_authority_code
    ON core.data_source
    FOR EACH ROW EXECUTE FUNCTION core.populate_campaign_finance_filing_authority();

-- ============================================================================
-- Refresh Run Ledger
-- ============================================================================
-- Operational record of every refresh-run attempt. This is the Keel L5 owner:
-- runner truthfulness comes from committed per-run statuses rather than
-- inferring health from today's last_pull_status snapshot on core.data_source.

CREATE TABLE core.refresh_run (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_key          TEXT NOT NULL,
    domain           TEXT NOT NULL,
    jurisdiction     TEXT NOT NULL,
    data_source_names TEXT[] NOT NULL DEFAULT '{}',
    execution_origin TEXT NOT NULL DEFAULT 'legacy_unknown',
    pull_status      TEXT NOT NULL CHECK (pull_status IN ('crashed', 'empty', 'degraded', 'failed', 'success', 'running')),
    started_at       TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ,
    inserted_count   INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    quarantined_count INTEGER NOT NULL DEFAULT 0,
    superseded_count INTEGER NOT NULL DEFAULT 0,
    error_count      INTEGER NOT NULL DEFAULT 0,
    metadata_updates INTEGER NOT NULL DEFAULT 0,
    message          TEXT NOT NULL,
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- An in-flight attempt is committed as 'running' with no completed_at and
    -- updated in place when it finishes, so 'running' is exactly the state
    -- with no completion timestamp. Mirrored by
    -- migrations/2026_08_23_refresh_run_running_status.sql.
    CONSTRAINT refresh_run_running_completed_at_check
        CHECK ((pull_status = 'running') = (completed_at IS NULL)),
    CONSTRAINT refresh_run_execution_origin_check
        CHECK (execution_origin IN ('scheduled', 'operator_attended', 'legacy_unknown'))
);

-- Plain btrees, not partial indexes on WHERE completed_at IS NOT NULL: btrees
-- index NULLs, but in-flight and interrupted attempts are expected to remain
-- sparse relative to terminal history, so a second index shape would add
-- maintenance complexity without a demonstrated query or size benefit.
CREATE INDEX idx_refresh_run_job_key_completed_at ON core.refresh_run (job_key, completed_at DESC);
CREATE INDEX idx_refresh_run_completed_at ON core.refresh_run (completed_at DESC);
CREATE INDEX idx_refresh_run_pull_status ON core.refresh_run (pull_status);

-- ============================================================================
-- Source Record
-- ============================================================================
-- An individual record from a data source. This is the atomic unit of provenance.
-- Each source record maps to one or more canonical entities (Person, Organization, Address).
--
-- Example: A single FEC contribution row creates a source_record that links to
-- the canonical Person (donor), Organization (committee), and the contribution itself.

CREATE TABLE core.source_record (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id  UUID NOT NULL REFERENCES core.data_source(id),
    source_record_key TEXT,                  -- Source's own ID (FEC transaction ID, parcel number, etc.)
    source_url      TEXT,                    -- Deep link to this specific record (if available)
    raw_fields      JSONB NOT NULL,          -- Complete raw record as received from source
    pull_date       TIMESTAMPTZ NOT NULL,    -- When this record was pulled
    record_hash     TEXT,                    -- SHA-256 of raw_fields for change detection
    superseded_by   UUID,                    -- Points to newer version of same record (if updated)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_source_record_data_source ON core.source_record (data_source_id);
CREATE INDEX idx_source_record_pull_date ON core.source_record (pull_date);
CREATE INDEX idx_source_record_hash ON core.source_record (record_hash);
CREATE INDEX idx_source_record_superseded_by ON core.source_record (superseded_by)
    WHERE superseded_by IS NOT NULL;

-- Only one active (non-superseded) record per source key.
-- Prevents duplicate ingestion; nullable source_record_key rows are excluded.
CREATE UNIQUE INDEX idx_source_record_active_key
    ON core.source_record (data_source_id, source_record_key)
    WHERE superseded_by IS NULL AND source_record_key IS NOT NULL;

-- This append-heavy table commonly receives bounded six-figure bulk loads.
-- Avoid launching VACUUM/ANALYZE inside those loads, while retaining an
-- aggressive 5% scale factor once the table is established.
ALTER TABLE core.source_record SET (
    autovacuum_analyze_threshold = 250000,
    autovacuum_analyze_scale_factor = 0.05,
    autovacuum_vacuum_insert_threshold = 250000,
    autovacuum_vacuum_insert_scale_factor = 0.05
);

CREATE OR REPLACE FUNCTION core.enforce_source_record_supersession_scope()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM new_rows AS source_record
        LEFT JOIN core.source_record AS successor
          ON successor.id = source_record.superseded_by
        WHERE source_record.superseded_by IS NOT NULL
          AND (
              successor.id IS NULL
              OR successor.data_source_id IS DISTINCT FROM source_record.data_source_id
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23503',
            CONSTRAINT = 'fk_source_record_superseded_scope',
            MESSAGE = 'source-record supersession must remain within one data source';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_source_record_supersession_scope_insert
AFTER INSERT ON core.source_record
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION core.enforce_source_record_supersession_scope();

CREATE TRIGGER trg_source_record_supersession_scope_update
AFTER UPDATE ON core.source_record
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION core.enforce_source_record_supersession_scope();

-- Cross-file FK: entity_address.source_record_id (defined in entities.sql, resolved here)
ALTER TABLE core.entity_address
    ADD CONSTRAINT fk_entity_address_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

-- Cross-file FK: contact_point.source_record_id (defined in entities.sql, resolved here)
ALTER TABLE core.contact_point
    ADD CONSTRAINT fk_contact_point_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

-- Cross-file FK: person_portrait.source_record_id (defined in entities.sql, resolved here)
ALTER TABLE core.person_portrait
    ADD CONSTRAINT fk_person_portrait_source_record
    FOREIGN KEY (source_record_id) REFERENCES core.source_record(id);

-- ============================================================================
-- Entity-Source Linkage
-- ============================================================================
-- Links canonical entities (Person, Organization) to the source records that
-- contributed to them. Many-to-many: one source record may contribute to multiple
-- entities (e.g., a donation record creates both a donor Person and a committee Org),
-- and one entity may be built from many source records across domains.

CREATE TABLE core.entity_source (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     TEXT NOT NULL CHECK (entity_type IN (
                        'person', 'organization', 'donor_identity', 'address',
                        'office', 'electoral_division', 'contest',
                        'election', 'filing_deadline', 'reporting_period',
                        'candidacy', 'officeholding', 'contact_point'
                    )),
    entity_id       UUID NOT NULL,
    source_record_id UUID NOT NULL REFERENCES core.source_record(id),
    extraction_role TEXT,                    -- 'donor', 'recipient', 'owner', 'officer', 'agent', etc.
    confidence      REAL,                    -- Confidence that this source record belongs to this entity [0..1]
    extracted_fields JSONB,                  -- Which fields from raw_fields were used for this entity
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_entity_source_entity ON core.entity_source (entity_type, entity_id);
CREATE INDEX idx_entity_source_record ON core.entity_source (source_record_id);
CREATE INDEX idx_entity_source_role ON core.entity_source (extraction_role);

-- Prevent duplicate linkages
CREATE UNIQUE INDEX idx_entity_source_dedup
    ON core.entity_source (entity_type, entity_id, source_record_id, extraction_role);

-- ============================================================================
-- Field-Level Provenance (adapted from FtM Statement model)
-- ============================================================================
-- Tracks individual property values across source records for the same entity.
-- Used when the same field (e.g., "employer") has different values across sources
-- and we need to pick the best one or surface the conflict.

CREATE TABLE core.field_provenance (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     TEXT NOT NULL CHECK (entity_type IN (
                        'person', 'organization', 'donor_identity', 'address',
                        'office', 'electoral_division', 'contest',
                        'election', 'filing_deadline', 'reporting_period',
                        'candidacy', 'officeholding', 'contact_point'
                    )),
    entity_id       UUID NOT NULL,
    field_name      TEXT NOT NULL,            -- 'canonical_name', 'date_of_birth', 'org_type', etc.
    field_value     TEXT NOT NULL,            -- The value (cast to text for uniform storage)
    source_record_id UUID NOT NULL REFERENCES core.source_record(id),
    first_seen      TIMESTAMPTZ NOT NULL,     -- When this value was first observed
    last_seen       TIMESTAMPTZ NOT NULL,     -- When this value was last confirmed
    is_current      BOOLEAN NOT NULL DEFAULT TRUE, -- Whether this is the currently selected value
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_field_prov_entity ON core.field_provenance (entity_type, entity_id);
CREATE INDEX idx_field_prov_field ON core.field_provenance (entity_type, entity_id, field_name);
CREATE UNIQUE INDEX idx_field_prov_current ON core.field_provenance (entity_type, entity_id, field_name)
    WHERE is_current = TRUE;
CREATE INDEX idx_field_provenance_source_record_id ON core.field_provenance (source_record_id);
CREATE UNIQUE INDEX idx_field_prov_dedup
    ON core.field_provenance (entity_type, entity_id, field_name, field_value, source_record_id);

-- ============================================================================
-- Trigger: auto-update data_source.updated_at
-- ============================================================================

CREATE TRIGGER trg_data_source_updated_at
    BEFORE UPDATE ON core.data_source
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
