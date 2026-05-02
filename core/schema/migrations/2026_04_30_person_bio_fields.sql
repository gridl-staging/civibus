-- Add nullable biography fields to the existing core.person owner.
ALTER TABLE core.person
    ADD COLUMN IF NOT EXISTS bio_text TEXT,
    ADD COLUMN IF NOT EXISTS bio_source_url TEXT,
    ADD COLUMN IF NOT EXISTS bio_license TEXT,
    ADD COLUMN IF NOT EXISTS bio_pulled_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'core'
          AND t.relname = 'person'
          AND c.conname = 'ck_person_bio_license'
    ) THEN
        ALTER TABLE core.person
            ADD CONSTRAINT ck_person_bio_license
            CHECK (
                bio_license IS NULL
                OR bio_license IN ('public_domain', 'licensed', 'restricted', 'unknown')
            );
    END IF;
END
$$;
