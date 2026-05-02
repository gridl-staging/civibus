-- Migration: 2026-04-28 — expand core.entity_source.entity_type and core.field_provenance.entity_type
-- check constraints to match the schema-as-coded in core/schema/provenance.sql.
--
-- Why:
-- domains/civics/ingest.py inserts entity_source rows with entity_type values
-- 'office', 'electoral_division', 'contest', 'candidacy', 'officeholding'
-- (see ingest.py lines 154/202/253/441/505), but the production check constraint
-- still rejects everything except person/organization/address. Stage 5 roster
-- harvest cannot persist officeholding provenance until the constraint matches
-- the schema-as-coded values used by civics ingest.
--
-- Idempotent: drops and recreates the constraints under the same names so
-- re-running the migration converges to the schema-as-coded set.

ALTER TABLE core.entity_source
    DROP CONSTRAINT IF EXISTS entity_source_entity_type_check;

ALTER TABLE core.entity_source
    ADD CONSTRAINT entity_source_entity_type_check CHECK (entity_type IN (
        'person', 'organization', 'address',
        'office', 'electoral_division', 'contest',
        'candidacy', 'officeholding', 'contact_point'
    ));

ALTER TABLE core.field_provenance
    DROP CONSTRAINT IF EXISTS field_provenance_entity_type_check;

ALTER TABLE core.field_provenance
    ADD CONSTRAINT field_provenance_entity_type_check CHECK (entity_type IN (
        'person', 'organization', 'address',
        'office', 'electoral_division', 'contest',
        'candidacy', 'officeholding', 'contact_point'
    ));
