-- Jurisdiction reference table
-- Migration order: 2 of 4 - run AFTER entities.sql and BEFORE provenance.sql
--   Requires: core schema and core.set_updated_at() function from entities.sql

CREATE TABLE core.jurisdiction (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                TEXT NOT NULL,
    jurisdiction_type   TEXT NOT NULL CHECK (
        jurisdiction_type IN (
            'federal',
            'state',
            'county',
            'municipality',
            'school_district',
            'special_district'
        )
    ),
    fips                TEXT,
    parent_id           UUID REFERENCES core.jurisdiction(id),
    state               TEXT,
    geometry            GEOMETRY(MultiPolygon, 4326),
    population          BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE core.jurisdiction
    ADD CONSTRAINT ck_jurisdiction_non_federal_requires_fips
    CHECK (jurisdiction_type = 'federal' OR fips IS NOT NULL);

CREATE UNIQUE INDEX idx_jurisdiction_fips_unique ON core.jurisdiction (fips)
    WHERE fips IS NOT NULL;

CREATE INDEX idx_jurisdiction_type ON core.jurisdiction (jurisdiction_type);
CREATE INDEX idx_jurisdiction_parent ON core.jurisdiction (parent_id) WHERE parent_id IS NOT NULL;

CREATE TRIGGER trg_jurisdiction_updated_at
    BEFORE UPDATE ON core.jurisdiction
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
