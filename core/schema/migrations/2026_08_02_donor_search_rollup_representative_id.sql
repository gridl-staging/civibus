-- Preserve donor-search's established minimum-transaction-ID pagination tie-break.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'cf'
          AND table_name = 'donor_search_rollup'
          AND column_name = 'representative_transaction_id'
    ) THEN
        ALTER TABLE cf.donor_search_rollup
            ADD COLUMN representative_transaction_id UUID;

        -- The rollup is derived and atomically rebuilt. Existing rows lack the
        -- stable representative ID, so invalidate them and their provenance
        -- rather than serve a mixed contract before the next rebuild.
        TRUNCATE TABLE cf.donor_search_rollup;
        DELETE FROM cf.donor_search_rollup_provenance;
    END IF;
END
$$;

ALTER TABLE cf.donor_search_rollup
    ALTER COLUMN representative_transaction_id SET NOT NULL;
