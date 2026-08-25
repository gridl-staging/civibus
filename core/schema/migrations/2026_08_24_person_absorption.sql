-- Durable tombstones for irreversible core.person absorption.
-- apply_migrations runs pending files inside a transaction.

CREATE TABLE IF NOT EXISTS core.person_absorption (
    absorbed_person_id UUID PRIMARY KEY,
    canonical_person_id UUID NOT NULL REFERENCES core.person(id),
    cluster_id UUID NOT NULL REFERENCES core.entity_cluster(id),
    merged_by TEXT NOT NULL,
    absorbed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    absorbed_payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_person_absorption_canonical_person
    ON core.person_absorption (canonical_person_id);

CREATE INDEX IF NOT EXISTS idx_person_absorption_cluster
    ON core.person_absorption (cluster_id);

CREATE INDEX IF NOT EXISTS idx_person_absorption_absorbed_at
    ON core.person_absorption (absorbed_at);
