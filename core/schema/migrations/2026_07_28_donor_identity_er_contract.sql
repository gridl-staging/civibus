-- Add donor_identity as a first-class ER input for initialized databases.
-- Canonical reset-time schema: core/schema/entity_resolution.sql and
-- core/schema/er_views.sql. Provenance reset-time constraints live in
-- core/schema/provenance.sql.

CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.donor_identity (
    id                      UUID PRIMARY KEY,
    canonical_name          TEXT NOT NULL,
    contributor_name_raw    TEXT NOT NULL,
    contributor_employer    TEXT,
    contributor_occupation  TEXT,
    contributor_city        TEXT,
    contributor_state       TEXT,
    contributor_zip         TEXT,
    zip5                    TEXT,
    transaction_count       INTEGER NOT NULL CHECK (transaction_count > 0),
    er_cluster_id           UUID,
    er_confidence           REAL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_donor_identity_name
    ON core.donor_identity (canonical_name);
CREATE INDEX IF NOT EXISTS idx_donor_identity_zip5
    ON core.donor_identity (zip5) WHERE zip5 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_donor_identity_cluster
    ON core.donor_identity (er_cluster_id) WHERE er_cluster_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_donor_identity_updated_at ON core.donor_identity;
CREATE TRIGGER trg_donor_identity_updated_at
    BEFORE UPDATE ON core.donor_identity
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

CREATE OR REPLACE VIEW core.donor_er_view AS
SELECT
    id,
    canonical_name,
    contributor_name_raw,
    contributor_employer,
    contributor_occupation,
    contributor_city,
    contributor_state,
    contributor_zip,
    zip5,
    transaction_count
FROM core.donor_identity;

ALTER TABLE IF EXISTS core.entity_source
    DROP CONSTRAINT IF EXISTS entity_source_entity_type_check;
ALTER TABLE IF EXISTS core.entity_source
    ADD CONSTRAINT entity_source_entity_type_check CHECK (entity_type IN (
        'person', 'organization', 'donor_identity', 'address',
        'office', 'electoral_division', 'contest',
        'election', 'filing_deadline', 'reporting_period',
        'candidacy', 'officeholding', 'contact_point'
    ));

ALTER TABLE IF EXISTS core.field_provenance
    DROP CONSTRAINT IF EXISTS field_provenance_entity_type_check;
ALTER TABLE IF EXISTS core.field_provenance
    ADD CONSTRAINT field_provenance_entity_type_check CHECK (entity_type IN (
        'person', 'organization', 'donor_identity', 'address',
        'office', 'electoral_division', 'contest',
        'election', 'filing_deadline', 'reporting_period',
        'candidacy', 'officeholding', 'contact_point'
    ));

ALTER TABLE IF EXISTS core.match_decision
    DROP CONSTRAINT IF EXISTS match_decision_entity_type_check;
ALTER TABLE IF EXISTS core.match_decision
    ADD CONSTRAINT match_decision_entity_type_check CHECK (
        entity_type IN ('person', 'organization', 'donor_identity')
    );

ALTER TABLE IF EXISTS core.entity_cluster
    DROP CONSTRAINT IF EXISTS entity_cluster_entity_type_check;
ALTER TABLE IF EXISTS core.entity_cluster
    ADD CONSTRAINT entity_cluster_entity_type_check CHECK (
        entity_type IN ('person', 'organization', 'donor_identity')
    );

ALTER TABLE IF EXISTS core.cluster_member
    DROP CONSTRAINT IF EXISTS cluster_member_entity_type_check;
ALTER TABLE IF EXISTS core.cluster_member
    ADD CONSTRAINT cluster_member_entity_type_check CHECK (
        entity_type IN ('person', 'organization', 'donor_identity')
    );

ALTER TABLE IF EXISTS core.manual_override
    DROP CONSTRAINT IF EXISTS manual_override_entity_type_check;
ALTER TABLE IF EXISTS core.manual_override
    ADD CONSTRAINT manual_override_entity_type_check CHECK (
        entity_type IN ('person', 'organization', 'donor_identity')
    );

ALTER TABLE IF EXISTS core.splink_run
    DROP CONSTRAINT IF EXISTS splink_run_entity_type_check;
ALTER TABLE IF EXISTS core.splink_run
    ADD CONSTRAINT splink_run_entity_type_check CHECK (
        entity_type IN ('person', 'organization', 'donor_identity')
    );
