-- Widen provenance entity_type check constraints to cover the civic ingest owner.
-- domains/civics/ingest.py upserts election / filing_deadline / reporting_period
-- rows and records their provenance via core.entity_source, but the original
-- check constraints omitted these three types, so election provenance (populated
-- by the federal FEC races loader) violated the constraint.
-- Canonical reset-time schema: core/schema/provenance.sql.

ALTER TABLE core.entity_source
    DROP CONSTRAINT IF EXISTS entity_source_entity_type_check;
ALTER TABLE core.entity_source
    ADD CONSTRAINT entity_source_entity_type_check CHECK (entity_type IN (
        'person', 'organization', 'address',
        'office', 'electoral_division', 'contest',
        'election', 'filing_deadline', 'reporting_period',
        'candidacy', 'officeholding', 'contact_point'
    ));

ALTER TABLE core.field_provenance
    DROP CONSTRAINT IF EXISTS field_provenance_entity_type_check;
ALTER TABLE core.field_provenance
    ADD CONSTRAINT field_provenance_entity_type_check CHECK (entity_type IN (
        'person', 'organization', 'address',
        'office', 'electoral_division', 'contest',
        'election', 'filing_deadline', 'reporting_period',
        'candidacy', 'officeholding', 'contact_point'
    ));
