-- Add refresh-backed committee filing-breakdown payload to cf.committee_summary.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql

ALTER TABLE cf.committee_summary
    ADD COLUMN IF NOT EXISTS derived_filing_breakdown JSONB;
