ALTER TABLE cf.candidate
    ADD COLUMN IF NOT EXISTS total_receipts NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS total_disbursements NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS cash_on_hand NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS summary_coverage_end_date DATE;
