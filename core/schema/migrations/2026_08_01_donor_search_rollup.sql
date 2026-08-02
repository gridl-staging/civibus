-- Add the refresh-built donor-search aggregate and its one-row build provenance.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS cf.donor_search_rollup (
    donor_key                  TEXT PRIMARY KEY,
    contributor_name          TEXT NOT NULL,
    contributor_employer      TEXT,
    contributor_occupation    TEXT,
    contributor_city          TEXT,
    contributor_state         TEXT,
    normalized_zip5           TEXT,
    jurisdiction              TEXT,
    search_text               TEXT NOT NULL,
    total_amount              NUMERIC NOT NULL,
    transaction_count         INTEGER NOT NULL,
    latest_transaction_date   DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_donor_search_rollup_search_text_trgm
    ON cf.donor_search_rollup USING GIN (search_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_donor_search_rollup_normalized_zip5
    ON cf.donor_search_rollup (normalized_zip5);

CREATE TABLE IF NOT EXISTS cf.donor_search_rollup_provenance (
    singleton                     BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    donor_key_fingerprint         TEXT NOT NULL,
    row_count                     BIGINT NOT NULL CHECK (row_count >= 0),
    build_duration_milliseconds   BIGINT NOT NULL CHECK (build_duration_milliseconds >= 0),
    completed_at                  TIMESTAMPTZ NOT NULL
);
