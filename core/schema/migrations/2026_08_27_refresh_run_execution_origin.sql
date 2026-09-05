-- Add immutable invocation-lineage evidence without breaking deployed writers
-- whose explicit column lists predate execution_origin.

ALTER TABLE core.refresh_run
ADD COLUMN execution_origin TEXT;

ALTER TABLE core.refresh_run
ALTER COLUMN execution_origin SET DEFAULT 'legacy_unknown';

UPDATE core.refresh_run
SET execution_origin = 'legacy_unknown'
WHERE execution_origin IS NULL;

ALTER TABLE core.refresh_run
ALTER COLUMN execution_origin SET NOT NULL;

ALTER TABLE core.refresh_run
ADD CONSTRAINT refresh_run_execution_origin_check
CHECK (execution_origin IN ('scheduled', 'operator_attended', 'legacy_unknown'));
