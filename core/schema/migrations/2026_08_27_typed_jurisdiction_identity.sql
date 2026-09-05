-- Expand core.jurisdiction with unambiguous typed geographic identifiers.
-- The migration runner applies this file and its ledger row in one transaction.

ALTER TABLE core.jurisdiction
    ADD COLUMN IF NOT EXISTS state_fips TEXT,
    ADD COLUMN IF NOT EXISTS county_geoid TEXT,
    ADD COLUMN IF NOT EXISTS place_geoid TEXT;

UPDATE core.jurisdiction
SET state_fips = fips
WHERE state_fips IS NULL
  AND jurisdiction_type = 'state'
  AND fips ~ '^[0-9]{2}$';

UPDATE core.jurisdiction
SET county_geoid = fips
WHERE county_geoid IS NULL
  AND jurisdiction_type = 'county'
  AND fips ~ '^[0-9]{5}$';

UPDATE core.jurisdiction
SET place_geoid = fips
WHERE place_geoid IS NULL
  AND jurisdiction_type = 'municipality'
  AND fips ~ '^[0-9]{7}$';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'core.jurisdiction'::regclass
          AND conname = 'ck_jurisdiction_state_fips'
    ) THEN
        ALTER TABLE core.jurisdiction
            ADD CONSTRAINT ck_jurisdiction_state_fips CHECK (
                state_fips IS NULL OR (
                    jurisdiction_type = 'state'
                    AND state_fips ~ '^[0-9]{2}$'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'core.jurisdiction'::regclass
          AND conname = 'ck_jurisdiction_county_geoid'
    ) THEN
        ALTER TABLE core.jurisdiction
            ADD CONSTRAINT ck_jurisdiction_county_geoid CHECK (
                county_geoid IS NULL OR (
                    jurisdiction_type IN ('county', 'municipality')
                    AND county_geoid ~ '^[0-9]{5}$'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'core.jurisdiction'::regclass
          AND conname = 'ck_jurisdiction_place_geoid'
    ) THEN
        ALTER TABLE core.jurisdiction
            ADD CONSTRAINT ck_jurisdiction_place_geoid CHECK (
                place_geoid IS NULL OR (
                    jurisdiction_type = 'municipality'
                    AND place_geoid ~ '^[0-9]{7}$'
                )
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jurisdiction_state_fips_unique
    ON core.jurisdiction (state_fips)
    WHERE state_fips IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_jurisdiction_county_geoid_unique
    ON core.jurisdiction (county_geoid)
    WHERE county_geoid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_jurisdiction_place_geoid_unique
    ON core.jurisdiction (place_geoid)
    WHERE place_geoid IS NOT NULL;
