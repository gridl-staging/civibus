-- Migration: 2026-04-28 — add civic.office_roster_link bridge table
--
-- Why:
-- Stage 2 roster bootstrapping needs a canonical bridge between civic.office
-- and core.data_source so Stage 3 can discover roster harvest targets from DB
-- state instead of hardcoded per-source mappings.
--
-- Idempotent:
--   - CREATE TABLE IF NOT EXISTS for the bridge contract
--   - CREATE INDEX IF NOT EXISTS for lookup indexes
--   - guarded trigger creation using pg_trigger catalog checks

CREATE TABLE IF NOT EXISTS civic.office_roster_link (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    office_id UUID NOT NULL REFERENCES civic.office(id),
    data_source_id UUID NOT NULL REFERENCES core.data_source(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_office_roster_link_pair UNIQUE (office_id, data_source_id)
);

CREATE INDEX IF NOT EXISTS idx_office_roster_link_office_id
    ON civic.office_roster_link (office_id);

CREATE INDEX IF NOT EXISTS idx_office_roster_link_data_source_id
    ON civic.office_roster_link (data_source_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'civic'
          AND c.relname = 'office_roster_link'
          AND t.tgname = 'trg_office_roster_link_updated_at'
          AND NOT t.tgisinternal
    ) THEN
        CREATE TRIGGER trg_office_roster_link_updated_at
            BEFORE UPDATE ON civic.office_roster_link
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    END IF;
END $$;
