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
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_data_source_domain ON core.data_source (domain);
CREATE INDEX idx_data_source_jurisdiction ON core.data_source (jurisdiction);
CREATE UNIQUE INDEX idx_data_source_dedup ON core.data_source (domain, jurisdiction, name);

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
    pull_status      TEXT NOT NULL CHECK (pull_status IN ('crashed', 'empty', 'degraded', 'success')),
    started_at       TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ NOT NULL,
    inserted_count   INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    quarantined_count INTEGER NOT NULL DEFAULT 0,
    superseded_count INTEGER NOT NULL DEFAULT 0,
    error_count      INTEGER NOT NULL DEFAULT 0,
    metadata_updates INTEGER NOT NULL DEFAULT 0,
    message          TEXT NOT NULL,
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

ALTER TABLE core.source_record
    ADD CONSTRAINT fk_source_record_superseded
    FOREIGN KEY (superseded_by) REFERENCES core.source_record(id);

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
                        'person', 'organization', 'address',
                        'office', 'electoral_division', 'contest',
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
                        'person', 'organization', 'address',
                        'office', 'electoral_division', 'contest',
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
