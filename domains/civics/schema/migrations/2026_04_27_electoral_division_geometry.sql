-- Migration: 2026-04-27 — add civic.electoral_division geometry contract columns/indexes
--
-- Why:
-- Stage 2 geometry readers/loaders depend on civic.electoral_division.geometry.
-- Existing databases provisioned before Stage 2 need an in-place, idempotent
-- schema upgrade path that does not require destructive db-reset.
--
-- Idempotent:
--   - ADD COLUMN IF NOT EXISTS for geometry
--   - CREATE INDEX IF NOT EXISTS for the partial GIST index

ALTER TABLE civic.electoral_division
    ADD COLUMN IF NOT EXISTS geometry GEOMETRY(MultiPolygon, 4326);

CREATE INDEX IF NOT EXISTS idx_electoral_division_geometry
    ON civic.electoral_division USING GIST (geometry)
    WHERE geometry IS NOT NULL;
