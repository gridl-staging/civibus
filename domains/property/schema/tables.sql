-- Stage 3 Property Schema
--
-- Migration order
-- 1) Load core:
--    - core/schema/entities.sql
--    - core/schema/jurisdiction.sql
--    - core/schema/provenance.sql
-- 2) Load campaign finance:
--    - domains/campaign_finance/schema/tables.sql
-- 3) Load this file:
--    - domains/property/schema/tables.sql
--
-- Schema ownership
-- This file owns exactly three tables:
--   - prop.parcel
--   - prop.assessment
--   - prop.ownership
--
-- Shared conventions for this stage
--   - UUID primary keys use uuid_generate_v4().
--   - source_record_id links every domain row back to core provenance.
--   - updated_at columns are maintained via core.set_updated_at().
--   - ownership timelines use daterange + core.date_precision.

CREATE SCHEMA IF NOT EXISTS prop;

CREATE TABLE prop.parcel (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    reid               TEXT NOT NULL,
    pin                TEXT NOT NULL,
    site_address       TEXT NOT NULL,
    property_description TEXT,
    city               TEXT,
    zoning_class       TEXT,
    land_class         TEXT,
    acreage            NUMERIC(12,4),
    neighborhood       TEXT,
    fire_district      TEXT,
    is_pending         BOOLEAN NOT NULL DEFAULT FALSE,
    deed_date          DATE,
    deed_book          TEXT,
    deed_page          TEXT,
    jurisdiction_id    UUID REFERENCES core.jurisdiction(id),
    source_record_id   UUID REFERENCES core.source_record(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_parcel_reid_not_blank CHECK (char_length(btrim(reid)) > 0),
    CONSTRAINT ck_parcel_pin_not_blank CHECK (char_length(btrim(pin)) > 0),
    CONSTRAINT ck_parcel_site_address_not_blank CHECK (char_length(btrim(site_address)) > 0)
);

CREATE UNIQUE INDEX uq_parcel_reid ON prop.parcel (reid);
CREATE UNIQUE INDEX uq_parcel_pin ON prop.parcel (pin);
CREATE INDEX idx_parcel_jurisdiction ON prop.parcel (jurisdiction_id) WHERE jurisdiction_id IS NOT NULL;
CREATE INDEX idx_parcel_source_record ON prop.parcel (source_record_id) WHERE source_record_id IS NOT NULL;

CREATE TABLE prop.assessment (
    id                           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parcel_id                    UUID NOT NULL REFERENCES prop.parcel(id),
    tax_year                     INTEGER NOT NULL,
    land_assessed_value          NUMERIC(14,2),
    improvement_assessed_value   NUMERIC(14,2),
    total_assessed_value         NUMERIC(14,2),
    assessed_at                  DATE,
    heated_area                  INTEGER,
    exemption_description        TEXT,
    source_record_id             UUID REFERENCES core.source_record(id),
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_assessment_tax_year CHECK (tax_year >= 1900),
    CONSTRAINT ck_assessment_heated_area_non_negative CHECK (heated_area IS NULL OR heated_area >= 0)
);

CREATE UNIQUE INDEX uq_assessment_parcel_tax_year ON prop.assessment (parcel_id, tax_year);
CREATE INDEX idx_assessment_parcel ON prop.assessment (parcel_id);
CREATE INDEX idx_assessment_source_record_id ON prop.assessment (source_record_id);

CREATE TABLE prop.ownership (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parcel_id             UUID NOT NULL REFERENCES prop.parcel(id),
    owner_name            TEXT NOT NULL,
    owner_mail_line1      TEXT,
    owner_mail_line2      TEXT,
    owner_mail_line3      TEXT,
    owner_mail_city       TEXT,
    owner_mail_state      TEXT,
    owner_mail_zip5       TEXT,
    ownership_recorded_at DATE,
    valid_period          daterange NOT NULL DEFAULT daterange(NULL, NULL, '[)'::text),
    date_precision        core.date_precision NOT NULL DEFAULT 'day',
    owner_person_id       UUID REFERENCES core.person(id),
    owner_organization_id UUID REFERENCES core.organization(id),
    owner_address_id      UUID REFERENCES core.address(id),
    source_record_id      UUID REFERENCES core.source_record(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_ownership_owner_name_not_blank CHECK (char_length(btrim(owner_name)) > 0),
    CONSTRAINT ck_ownership_owner_state_len CHECK (owner_mail_state IS NULL OR char_length(owner_mail_state) = 2),
    CONSTRAINT ck_ownership_owner_zip5_len CHECK (owner_mail_zip5 IS NULL OR owner_mail_zip5 ~ '^[0-9]{5}$'),
    CONSTRAINT ck_ownership_owner_entity_links CHECK (num_nonnulls(owner_person_id, owner_organization_id) <= 1),
    CONSTRAINT ck_ownership_valid_period_non_empty CHECK (NOT isempty(valid_period))
);

CREATE INDEX idx_ownership_parcel ON prop.ownership (parcel_id);
CREATE INDEX idx_ownership_owner_person
    ON prop.ownership (owner_person_id)
    WHERE owner_person_id IS NOT NULL;
CREATE INDEX idx_ownership_owner_organization
    ON prop.ownership (owner_organization_id)
    WHERE owner_organization_id IS NOT NULL;
CREATE INDEX idx_ownership_owner_address
    ON prop.ownership (owner_address_id)
    WHERE owner_address_id IS NOT NULL;
CREATE INDEX idx_ownership_valid_period ON prop.ownership USING GIST (valid_period);
CREATE INDEX idx_ownership_source_record_id ON prop.ownership (source_record_id);

CREATE TRIGGER trg_parcel_updated_at
    BEFORE UPDATE ON prop.parcel
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_assessment_updated_at
    BEFORE UPDATE ON prop.assessment
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();

CREATE TRIGGER trg_ownership_updated_at
    BEFORE UPDATE ON prop.ownership
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();
