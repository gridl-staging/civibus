-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- search_donors(by=name|employer|zip) needs fuzzy text lookup on names/employers
-- and exact normalized 5-digit ZIP-prefix filtering without replacing donor ER indexes.
CREATE INDEX IF NOT EXISTS idx_transaction_contributor_name_lower_trgm
    ON cf.transaction USING GIN (LOWER(contributor_name_raw) gin_trgm_ops)
    WHERE contributor_name_raw IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_transaction_contributor_employer_lower_trgm
    ON cf.transaction USING GIN (LOWER(contributor_employer) gin_trgm_ops)
    WHERE contributor_employer IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_transaction_contributor_zip5
    ON cf.transaction (LEFT(contributor_zip, 5))
    WHERE contributor_zip IS NOT NULL;

-- High-frequency donor searches must intersect the mode predicate with the
-- immutable Schedule A receipt filters before row materialization. These partial
-- indexes are intentionally narrower than the general donor ER indexes above.
CREATE INDEX IF NOT EXISTS idx_transaction_donor_search_name_receipt_trgm
    ON cf.transaction USING GIN (LOWER(contributor_name_raw) gin_trgm_ops)
    WHERE contributor_name_raw IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';
CREATE INDEX IF NOT EXISTS idx_transaction_donor_search_employer_receipt_trgm
    ON cf.transaction USING GIN (LOWER(contributor_employer) gin_trgm_ops)
    WHERE contributor_employer IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';
CREATE INDEX IF NOT EXISTS idx_transaction_donor_search_zip5_receipt
    ON cf.transaction (LEFT(contributor_zip, 5))
    WHERE contributor_zip IS NOT NULL
      AND transaction_type LIKE '1%'
      AND contributor_entity_type = 'IND'
      AND is_memo = FALSE
      AND amendment_indicator != 'T';

-- Donor search validates source freshness before aggregation but should not
-- probe the full source-record primary key for every matched transaction.
CREATE INDEX IF NOT EXISTS idx_source_record_superseded_id
    ON core.source_record (id)
    WHERE superseded_by IS NOT NULL;
