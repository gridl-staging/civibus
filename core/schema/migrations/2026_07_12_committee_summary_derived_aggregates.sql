-- Add refresh-backed committee-detail aggregates to cf.committee_summary.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql

ALTER TABLE cf.committee_summary
    ADD COLUMN IF NOT EXISTS derived_total_raised NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_total_spent NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_net NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_transaction_count INTEGER,
    ADD COLUMN IF NOT EXISTS derived_cash_receipts_total NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_in_kind_receipts_total NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_loan_receipts_total NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_contribution_receipts_total NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS derived_jurisdiction TEXT,
    ADD COLUMN IF NOT EXISTS derived_data_through TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_committee_summary_derived_data_through
    ON cf.committee_summary (derived_data_through);
