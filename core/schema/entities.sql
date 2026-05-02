-- Core Entity Tables: Person, Organization, Address
-- These are the core shared types. Every data domain contributes
-- source records that resolve to these entities via entity resolution (Splink).
--
-- Migration order: 1 of 3 — run BEFORE provenance.sql and entity_resolution.sql
--   Defines: core schema, set_updated_at() function, Person/Organization/Address tables
--   Requires: uuid-ossp, postgis, fuzzystrmatch, and btree_gist extensions
--   Note: entity_address.source_record_id FK is applied in provenance.sql (cross-file dependency)
--
-- Design decisions:
--   - ADR 0006: Adapt FtM concepts, own schema (typed columns, PostGIS, Pydantic-first)
--   - ADR 0004: Splink for entity resolution
--   - ADR 0002: PostGIS from day one
--   - ADR 0003: Apache AGE (accepted) — core shared types as graph nodes in same PostgreSQL instance

CREATE SCHEMA IF NOT EXISTS core;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "fuzzystrmatch";  -- SOUNDEX() used by org ER blocking rules
CREATE EXTENSION IF NOT EXISTS "pg_trgm";        -- Trigram similarity for hybrid name search
CREATE EXTENSION IF NOT EXISTS "btree_gist";     -- Required for daterange WITHOUT OVERLAPS constraints
CREATE EXTENSION IF NOT EXISTS age;

-- ============================================================================
-- Person
-- ============================================================================
-- A canonical person entity, resolved from one or more source records across
-- data domains (campaign finance donors, property owners, corporate officers, etc.)

CREATE TABLE core.person (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name  TEXT NOT NULL,                -- Best-known name form
    name_variants   TEXT[] NOT NULL DEFAULT '{}',  -- All observed name forms
    first_name      TEXT,
    middle_name     TEXT,
    last_name       TEXT,
    suffix          TEXT,                          -- Jr, Sr, III, etc.
    occupation      TEXT,                          -- Best-known occupation (source-traceable via core.field_provenance)
    education       TEXT,                          -- Best-known education text (source-traceable via core.field_provenance)
    bio_text        TEXT,                          -- Best-known official biography text (source-traceable via core.field_provenance)
    bio_source_url  TEXT,                          -- Canonical source URL from which bio_text was acquired
    bio_license     TEXT CHECK (bio_license IS NULL OR bio_license IN ('public_domain', 'licensed', 'restricted', 'unknown')),
    bio_pulled_at   TIMESTAMPTZ,                   -- UTC timestamp when biography text was last fetched
    date_of_birth   DATE,
    year_of_birth   SMALLINT,                     -- When full DOB unavailable
    identifiers     JSONB NOT NULL DEFAULT '{}',   -- {"fec_id": "...", "nc_voter_id": "..."}
    primary_address_id UUID,                      -- FK to core.address
    er_cluster_id   UUID,                         -- Entity resolution cluster identifier
    er_confidence   REAL,                         -- Overall entity resolution confidence [0..1]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_person_canonical_name ON core.person (canonical_name);
CREATE INDEX idx_person_canonical_name_trgm ON core.person USING GIN (canonical_name gin_trgm_ops);
CREATE INDEX idx_person_last_name ON core.person (last_name);
CREATE INDEX idx_person_last_first ON core.person (last_name, first_name);
CREATE INDEX idx_person_identifiers ON core.person USING GIN (identifiers);
CREATE INDEX idx_person_er_cluster ON core.person (er_cluster_id) WHERE er_cluster_id IS NOT NULL;
CREATE INDEX idx_person_primary_address ON core.person (primary_address_id) WHERE primary_address_id IS NOT NULL;

-- Full-text search on canonical name
CREATE INDEX idx_person_name_fts ON core.person
    USING GIN (to_tsvector('simple', canonical_name));

-- ============================================================================
-- Person Portrait
-- ============================================================================
-- Candidate portrait metadata linked to an entity person.
-- Provenance remains centralized in core.source_record/core.field_provenance:
-- source_record_id is declared here and resolved as a cross-file FK in provenance.sql.

CREATE TABLE core.person_portrait (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id       UUID NOT NULL REFERENCES core.person(id),
    source_record_id UUID NOT NULL,                -- FK applied in provenance.sql
    status          TEXT NOT NULL CHECK (status IN (
                        'active',
                        'not_found',
                        'too_small',
                        'face_too_small',
                        'takedown_requested',
                        'superseded',
                        'rejected'
                    )),
    rights_status   TEXT NOT NULL CHECK (rights_status IN ('public_domain', 'licensed', 'restricted', 'unknown')),
    image_hash      TEXT NOT NULL,                 -- SHA-256 of canonical image bytes
    dedup_key       TEXT NOT NULL,                 -- Deterministic hash of source identity + image hash
    mime_type       TEXT,                          -- image/jpeg, image/png, etc.
    width_px        INTEGER CHECK (width_px IS NULL OR width_px > 0),
    height_px       INTEGER CHECK (height_px IS NULL OR height_px > 0),
    source_image_url TEXT,                         -- Original fetch URL
    storage_uri     TEXT,                          -- Internal storage locator (object key/URI)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_person_portrait_person_id ON core.person_portrait (person_id);
CREATE INDEX idx_person_portrait_source_record ON core.person_portrait (source_record_id);
CREATE UNIQUE INDEX idx_person_portrait_dedup ON core.person_portrait (person_id, dedup_key);
CREATE UNIQUE INDEX idx_person_portrait_active_per_person ON core.person_portrait (person_id)
    WHERE status = 'active';

-- ============================================================================
-- Organization
-- ============================================================================
-- A canonical organization entity: LLC, corporation, nonprofit, PAC, government
-- agency, etc. Resolved from source records across domains.

CREATE TABLE core.organization (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name  TEXT NOT NULL,
    name_variants   TEXT[] NOT NULL DEFAULT '{}',
    org_type        TEXT,                          -- llc, corporation, nonprofit, pac, government, etc.
    identifiers     JSONB NOT NULL DEFAULT '{}',   -- {"ein": "...", "nc_sos_id": "...", "fec_committee_id": "..."}
    registered_state TEXT,                         -- Two-letter state code
    formation_date  DATE,
    dissolution_date DATE,
    primary_address_id UUID,
    er_cluster_id   UUID,
    er_confidence   REAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_org_canonical_name ON core.organization (canonical_name);
CREATE INDEX idx_org_canonical_name_trgm ON core.organization USING GIN (canonical_name gin_trgm_ops);
CREATE INDEX idx_org_type ON core.organization (org_type);
CREATE INDEX idx_org_identifiers ON core.organization USING GIN (identifiers);
CREATE INDEX idx_org_registered_state ON core.organization (registered_state) WHERE registered_state IS NOT NULL;
CREATE INDEX idx_org_er_cluster ON core.organization (er_cluster_id) WHERE er_cluster_id IS NOT NULL;
CREATE INDEX idx_org_primary_address ON core.organization (primary_address_id) WHERE primary_address_id IS NOT NULL;

CREATE INDEX idx_org_name_fts ON core.organization
    USING GIN (to_tsvector('simple', canonical_name));

-- ============================================================================
-- Address
-- ============================================================================
-- Normalized, geocoded addresses. Shared across all domains.
-- A Person or Organization may have multiple addresses over time;
-- primary_address_id on the entity points to the current best one.

CREATE TABLE core.address (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_address         TEXT NOT NULL,                -- As received from source
    normalized_address  TEXT,                         -- Standardized format (USPS-style)
    street_number       TEXT,
    street_name         TEXT,
    unit                TEXT,                         -- Apt, Suite, etc.
    city                TEXT,
    state               TEXT,                         -- Two-letter code
    zip5                TEXT,
    zip4                TEXT,
    county_fips         TEXT,                         -- 5-digit FIPS code
    geometry            GEOMETRY(Point, 4326),        -- PostGIS geocoded point (WGS84)
    geocode_confidence  REAL,                         -- Geocoder confidence [0..1]
    geocode_source      TEXT,                         -- census, nominatim, google, etc.
    geocoded_at         TIMESTAMPTZ,                  -- When geocoding was performed
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_address_zip5 ON core.address (zip5);
CREATE INDEX idx_address_state ON core.address (state);
CREATE INDEX idx_address_city_state ON core.address (city, state);
CREATE INDEX idx_address_geometry ON core.address USING GIST (geometry);
CREATE INDEX idx_address_normalized ON core.address (normalized_address);

-- Deduplicate addresses: USPS-normalized form (number+street+city+state+zip) is
-- unique per physical location. NULLs excluded so un-normalized records coexist.
CREATE UNIQUE INDEX idx_address_dedup ON core.address (normalized_address)
    WHERE normalized_address IS NOT NULL;

-- Deduplicate pre-normalized addresses during Stage 5 ingest.
CREATE UNIQUE INDEX idx_address_raw_address_dedup ON core.address (raw_address)
    WHERE raw_address IS NOT NULL;

-- ============================================================================
-- Temporal date precision
-- ============================================================================
-- Public records data has inconsistent date precision. This enum lets the UI
-- display dates at the appropriate granularity (show "2020" not "January 1, 2020").

CREATE TYPE core.date_precision AS ENUM ('day', 'month', 'quarter', 'year', 'approximate');

-- ============================================================================
-- Entity-Address junction (temporal)
-- ============================================================================
-- Tracks all addresses associated with an entity over time.
-- The entity's primary_address_id points to the current best address.
-- Temporal semantics:
--   - valid_period captures the relationship timeline and disallows overlaps
--     per (entity_type, entity_id, address_id, address_role) using PG18
--     WITHOUT OVERLAPS constraints.
--   - date_precision records source precision for display and interpretation.


CREATE TABLE core.entity_address (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    entity_id   UUID NOT NULL,
    address_id  UUID NOT NULL REFERENCES core.address(id),
    address_role TEXT NOT NULL DEFAULT 'mailing', -- mailing, registered, physical, billing
    valid_period daterange NOT NULL DEFAULT daterange(NULL, NULL, '[)'),
    date_precision core.date_precision NOT NULL DEFAULT 'day',
    source_record_id UUID,              -- FK to core.source_record
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_type, entity_id, address_id, address_role, valid_period WITHOUT OVERLAPS)
);

CREATE INDEX idx_entity_address_entity ON core.entity_address (entity_type, entity_id);
CREATE INDEX idx_entity_address_address ON core.entity_address (address_id);
CREATE INDEX idx_entity_address_current ON core.entity_address (entity_type, entity_id)
    WHERE upper_inf(valid_period);

-- ============================================================================
-- Contact Point
-- ============================================================================
-- Domain-agnostic communication primitive: email, phone, web URL, or physical
-- contact address. Reusable across civic, corporate, nonprofit, and future
-- domains. Analogous to core.address as a shared linkable primitive.
--
-- ADR 0008: contact_point is a core shared type, not civic-domain-specific.

CREATE TABLE core.contact_point (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type              TEXT NOT NULL,                -- email, phone, fax, web, social
    value_raw         TEXT NOT NULL,                -- As received from source
    value_normalized  TEXT,                         -- Standardized format (e.g., E.164 phone)
    role              TEXT,                         -- campaign, office, personal, press
    owner_type        TEXT NOT NULL CHECK (owner_type IN (
                          'person', 'organization', 'office', 'officeholding', 'candidacy'
                      )),
    owner_id          UUID NOT NULL,
    source_record_id  UUID,                        -- FK to core.source_record (applied in provenance.sql)
    last_verified_at  TIMESTAMPTZ,
    is_preferred      BOOLEAN NOT NULL DEFAULT FALSE,
    valid_period      daterange NOT NULL DEFAULT daterange(NULL, NULL, '[)'),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_contact_point_natural_key
    ON core.contact_point (owner_type, owner_id, type, value_raw, role)
    WHERE role IS NOT NULL;

-- Separate partial index for NULL role to avoid NULL != NULL exclusion
CREATE UNIQUE INDEX uq_contact_point_natural_key_null_role
    ON core.contact_point (owner_type, owner_id, type, value_raw)
    WHERE role IS NULL;

CREATE INDEX idx_contact_point_owner ON core.contact_point (owner_type, owner_id);
CREATE INDEX idx_contact_point_type ON core.contact_point (type);

-- ============================================================================
-- Foreign keys (deferred to allow table creation in any order)
-- ============================================================================

ALTER TABLE core.person
    ADD CONSTRAINT fk_person_primary_address
    FOREIGN KEY (primary_address_id) REFERENCES core.address(id);

ALTER TABLE core.organization
    ADD CONSTRAINT fk_org_primary_address
    FOREIGN KEY (primary_address_id) REFERENCES core.address(id);

-- ============================================================================
-- Trigger: auto-update updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_person_updated_at
    BEFORE UPDATE ON core.person
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_person_portrait_updated_at
    BEFORE UPDATE ON core.person_portrait
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_org_updated_at
    BEFORE UPDATE ON core.organization
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_address_updated_at
    BEFORE UPDATE ON core.address
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_contact_point_updated_at
    BEFORE UPDATE ON core.contact_point
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
