-- Preserve exact raw donor tuples used by core.donor_identity resolution.
-- Canonical reset-time schema: domains/campaign_finance/schema/tables.sql.

CREATE TABLE IF NOT EXISTS cf.donor_search_rollup_identity_variant (
    donor_key               TEXT NOT NULL,
    contributor_name_raw    TEXT NOT NULL,
    contributor_employer    TEXT NOT NULL,
    contributor_occupation  TEXT NOT NULL,
    contributor_city        TEXT NOT NULL,
    contributor_state       TEXT NOT NULL,
    contributor_zip         TEXT NOT NULL,
    CONSTRAINT donor_search_rollup_identity_variant_unique UNIQUE (
        donor_key,
        contributor_name_raw,
        contributor_employer,
        contributor_occupation,
        contributor_city,
        contributor_state,
        contributor_zip
    )
);

CREATE INDEX IF NOT EXISTS idx_donor_search_rollup_identity_variant_identity_tuple
    ON cf.donor_search_rollup_identity_variant (
        contributor_name_raw,
        contributor_employer,
        contributor_occupation,
        contributor_city,
        contributor_state,
        contributor_zip
    );

-- The existing aggregate was built before raw identity evidence was retained.
-- Fail serving closed until the canonical refresh owner rebuilds both relations.
DELETE FROM cf.donor_search_rollup_provenance;
