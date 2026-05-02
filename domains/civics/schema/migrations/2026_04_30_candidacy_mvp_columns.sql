-- Migration: 2026-04-30 — add civic.candidacy MVP columns for D/W/O loaders
--
-- Why:
-- Stage 1 adds additive candidacy fields needed by downstream state loaders while
-- preserving civic.candidacy as the single canonical owner for candidacy rows.
--
-- Idempotent:
--   - ALTER TABLE ... ADD COLUMN IF NOT EXISTS for additive columns
--   - CREATE INDEX IF NOT EXISTS for loader lookup paths

ALTER TABLE civic.candidacy
    ADD COLUMN IF NOT EXISTS name_on_ballot TEXT,
    ADD COLUMN IF NOT EXISTS is_unexpired_term BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS raw_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS committee_id UUID REFERENCES cf.committee(id);

CREATE INDEX IF NOT EXISTS idx_candidacy_committee_id
    ON civic.candidacy (committee_id)
    WHERE committee_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_candidacy_name_on_ballot
    ON civic.candidacy (name_on_ballot)
    WHERE name_on_ballot IS NOT NULL;
