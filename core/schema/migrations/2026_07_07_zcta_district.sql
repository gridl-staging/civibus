-- Add the civic.zcta_district reference table used by federal fundraising geography.
-- Canonical reset-time schema: domains/civics/schema/tables.sql.

CREATE SCHEMA IF NOT EXISTS civic;

CREATE TABLE IF NOT EXISTS civic.zcta_district (
    zcta5           TEXT PRIMARY KEY CHECK (zcta5 ~ '^[0-9]{5}$'),
    state_fips      TEXT NOT NULL CHECK (state_fips ~ '^[0-9]{2}$'),
    cd_geoid        TEXT NOT NULL CHECK (cd_geoid ~ '^[0-9A-Z]{4}$'),
    district_number TEXT NOT NULL CHECK (char_length(district_number) = 2),
    land_share      NUMERIC(7,5) NOT NULL CHECK (land_share >= 0 AND land_share <= 1),
    source_url      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_zcta_district_cd_geoid ON civic.zcta_district (cd_geoid);
CREATE INDEX IF NOT EXISTS idx_zcta_district_state_fips ON civic.zcta_district (state_fips);

COMMENT ON TABLE civic.zcta_district IS
    'Approximate ZCTA5-to-119th-congressional-district mapping derived from the Census 2020-ZCTA relationship file for fundraising geography summaries; not a parcel- or geometry-level district assignment.';
