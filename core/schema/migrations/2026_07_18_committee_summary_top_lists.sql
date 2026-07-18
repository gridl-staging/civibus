-- Add refresh-backed committee-detail top-list payloads to cf.committee_summary.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql

ALTER TABLE cf.committee_summary
    ADD COLUMN IF NOT EXISTS derived_top_donors JSONB,
    ADD COLUMN IF NOT EXISTS derived_top_vendors JSONB,
    ADD COLUMN IF NOT EXISTS derived_spend_categories JSONB;
