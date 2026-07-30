-- Persist the explicit donor-cluster-to-person promotion used by local donor
-- transaction writeback. The composite FK guarantees only donor clusters map.

CREATE TABLE IF NOT EXISTS core.donor_cluster_person (
    cluster_id     UUID PRIMARY KEY,
    entity_type    TEXT NOT NULL DEFAULT 'donor_identity'
                   CHECK (entity_type = 'donor_identity'),
    person_id      UUID NOT NULL REFERENCES core.person(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_donor_cluster_person_cluster
        FOREIGN KEY (cluster_id, entity_type)
        REFERENCES core.entity_cluster(id, entity_type)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_donor_cluster_person_person
    ON core.donor_cluster_person (person_id);
