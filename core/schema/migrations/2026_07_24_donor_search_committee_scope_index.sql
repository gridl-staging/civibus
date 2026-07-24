-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Common-name donor searches must intersect the trigram match with current
-- federal committee scope before heap materialization. The 2026-07-09 trigram
-- index is valid but still lets q=smith read every receipt-side Smith heap row
-- before committee pruning, which can breach the 10s donor statement timeout on
-- cold buffers.
CREATE INDEX IF NOT EXISTS idx_transaction_donor_search_name_receipt_committee_gin
    ON cf.transaction USING GIN (LOWER(contributor_name_raw) gin_trgm_ops, committee_id)
    WHERE contributor_name_raw IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';
