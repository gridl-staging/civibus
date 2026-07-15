-- Add raw FEC weball self-funding amounts to cf.candidate.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

ALTER TABLE cf.candidate
    ADD COLUMN IF NOT EXISTS candidate_contrib NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS candidate_loans NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS candidate_loan_repay NUMERIC(14,2);
