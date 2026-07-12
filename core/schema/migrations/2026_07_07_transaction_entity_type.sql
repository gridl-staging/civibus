-- Upgrade existing cf.transaction tables for the contributor entity-type contract.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

ALTER TABLE cf.transaction
    ADD COLUMN IF NOT EXISTS contributor_entity_type TEXT;

CREATE INDEX IF NOT EXISTS idx_transaction_committee_date
    ON cf.transaction (committee_id, transaction_date);

DROP INDEX IF EXISTS cf.idx_transaction_committee_lookup;
