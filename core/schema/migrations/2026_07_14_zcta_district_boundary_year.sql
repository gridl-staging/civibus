-- Make civic.zcta_district vintage-aware without dropping existing rows.
-- Existing CD119 rows come from the 2022 congressional boundary cycle.

CREATE SCHEMA IF NOT EXISTS civic;

ALTER TABLE civic.zcta_district
    ADD COLUMN IF NOT EXISTS boundary_year SMALLINT;

UPDATE civic.zcta_district
SET boundary_year = 2022
WHERE boundary_year IS NULL;

ALTER TABLE civic.zcta_district
    ALTER COLUMN boundary_year SET NOT NULL;

DO $$
DECLARE
    primary_key_name TEXT;
BEGIN
    SELECT conname
    INTO primary_key_name
    FROM pg_constraint
    WHERE conrelid = 'civic.zcta_district'::regclass
      AND contype = 'p';

    IF primary_key_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE civic.zcta_district DROP CONSTRAINT %I', primary_key_name);
    END IF;
END $$;

ALTER TABLE civic.zcta_district
    ADD CONSTRAINT zcta_district_pkey PRIMARY KEY (zcta5, boundary_year);

ALTER TABLE civic.zcta_district
    DROP CONSTRAINT IF EXISTS zcta_district_boundary_year_check;

ALTER TABLE civic.zcta_district
    ADD CONSTRAINT zcta_district_boundary_year_check CHECK (boundary_year >= 0);

DROP INDEX IF EXISTS civic.idx_zcta_district_cd_geoid;
DROP INDEX IF EXISTS civic.idx_zcta_district_state_fips;

CREATE INDEX IF NOT EXISTS idx_zcta_district_cd_geoid_boundary_year
    ON civic.zcta_district (cd_geoid, boundary_year);
CREATE INDEX IF NOT EXISTS idx_zcta_district_state_fips_boundary_year
    ON civic.zcta_district (state_fips, boundary_year);
