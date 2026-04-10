-- Entity Resolution: Match Decisions, Confidence Scores, Merge History
--
-- Migration order: 3 of 3 — run AFTER entities.sql and provenance.sql
--   Requires: core.set_updated_at() function (defined in entities.sql)
--
-- Implements the SAME_AS / POSSIBLE_MATCH layer for entity resolution.
-- Splink (ADR 0004) produces pairwise match scores. This schema stores
-- those decisions and supports manual overrides.
--
-- Design (ADR 0006, adapted from FtM nomenklatura Resolver pattern):
--   - Every match decision is logged with method, confidence, and timestamp
--   - Decisions are reversible: entities can be split as well as merged
--   - Downstream consumers can filter by confidence threshold
--   - ADR 0003 (accepted): match decisions materialized as SAME_AS/POSSIBLE_MATCH
--     edges in Apache AGE graph

CREATE SCHEMA IF NOT EXISTS core;

-- ============================================================================
-- Match Decision
-- ============================================================================
-- A pairwise decision about whether two entity records refer to the same
-- real-world entity. Created by Splink or by manual human review.

CREATE TABLE core.match_decision (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    entity_id_a     UUID NOT NULL,           -- First entity in the pair
    entity_id_b     UUID NOT NULL,           -- Second entity in the pair
    decision        TEXT NOT NULL CHECK (decision IN ('match', 'probable_match', 'possible_match', 'no_match')),
    confidence      REAL NOT NULL,           -- Match probability [0..1]
    decided_by      TEXT NOT NULL,           -- 'splink_v1', 'deterministic_ein', 'manual:stuart', etc.
    decision_method TEXT NOT NULL,           -- 'deterministic', 'probabilistic', 'manual'
    match_evidence  JSONB,                   -- Comparison details: which fields matched, similarity scores
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_by   UUID,                    -- If this decision was overridden by a later one
    superseded_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Enforce canonical ordering: entity_id_a < entity_id_b to prevent duplicate pairs
    CONSTRAINT chk_ordered_pair CHECK (entity_id_a < entity_id_b)
);

CREATE INDEX idx_match_entity_a ON core.match_decision (entity_type, entity_id_a);
CREATE INDEX idx_match_entity_b ON core.match_decision (entity_type, entity_id_b);
CREATE INDEX idx_match_decision_type ON core.match_decision (decision) WHERE superseded_by IS NULL;
CREATE INDEX idx_match_confidence ON core.match_decision (confidence) WHERE superseded_by IS NULL;
CREATE INDEX idx_match_active ON core.match_decision (entity_type, decision)
    WHERE superseded_by IS NULL;

-- Only one active (non-superseded) decision per entity pair
CREATE UNIQUE INDEX idx_match_active_pair
    ON core.match_decision (entity_type, entity_id_a, entity_id_b)
    WHERE superseded_by IS NULL;

ALTER TABLE core.match_decision
    ADD CONSTRAINT fk_match_superseded
    FOREIGN KEY (superseded_by) REFERENCES core.match_decision(id);

-- ============================================================================
-- Entity Cluster
-- ============================================================================
-- Groups of entity records that have been resolved to the same real-world entity.
-- The canonical_entity_id points to the "winner" entity that represents the cluster.
-- Other members are absorbed — their data is merged into the canonical entity,
-- and their IDs become aliases.

CREATE TABLE core.entity_cluster (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type         TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    canonical_entity_id UUID NOT NULL,       -- The entity that represents this cluster
    cluster_confidence  REAL,                -- Aggregate confidence for the cluster
    member_count        INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Supports composite FK from cluster_member ensuring type consistency
    CONSTRAINT uq_cluster_id_type UNIQUE (id, entity_type)
);

CREATE INDEX idx_cluster_canonical ON core.entity_cluster (entity_type, canonical_entity_id);

-- ============================================================================
-- Cluster Membership
-- ============================================================================
-- Tracks which entity IDs belong to which cluster, including the merge history.

CREATE TABLE core.cluster_member (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_id      UUID NOT NULL,
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    entity_id       UUID NOT NULL,           -- The member entity (may be the canonical or a merged-in record)
    is_canonical    BOOLEAN NOT NULL DEFAULT FALSE,
    merged_at       TIMESTAMPTZ,             -- When this entity was merged into the cluster
    merged_by       TEXT,                    -- 'splink_v1', 'manual:stuart', etc.
    split_at        TIMESTAMPTZ,             -- When this entity was split OUT of the cluster (if reversed)
    split_by        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Composite FK: guarantees member.entity_type matches its cluster's entity_type
    CONSTRAINT fk_cluster_member_cluster
        FOREIGN KEY (cluster_id, entity_type)
        REFERENCES core.entity_cluster(id, entity_type)
);

CREATE INDEX idx_cluster_member_cluster ON core.cluster_member (cluster_id);
CREATE INDEX idx_cluster_member_entity ON core.cluster_member (entity_type, entity_id);
CREATE INDEX idx_cluster_member_canonical ON core.cluster_member (cluster_id) WHERE is_canonical = TRUE;

-- Prevent duplicate cluster membership (active)
CREATE UNIQUE INDEX idx_cluster_member_active
    ON core.cluster_member (entity_type, entity_id)
    WHERE split_at IS NULL;

-- ============================================================================
-- Manual Override
-- ============================================================================
-- Human-confirmed or human-rejected match decisions. These take precedence over
-- Splink's automated decisions.

CREATE TABLE core.manual_override (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    match_decision_id   UUID REFERENCES core.match_decision(id),  -- The decision being overridden (if any)
    entity_type         TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    entity_id_a         UUID NOT NULL,
    entity_id_b         UUID NOT NULL,
    override_decision   TEXT NOT NULL CHECK (override_decision IN ('confirmed_match', 'confirmed_non_match')),
    reason              TEXT,                -- Why the human made this decision
    decided_by          TEXT NOT NULL,       -- 'stuart', 'reviewer:jane', etc.
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_by       UUID,               -- Points to newer override if human changed their mind
    superseded_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_override_ordered CHECK (entity_id_a < entity_id_b)
);

CREATE INDEX idx_override_entity_a ON core.manual_override (entity_type, entity_id_a);
CREATE INDEX idx_override_entity_b ON core.manual_override (entity_type, entity_id_b);
CREATE INDEX idx_override_decision ON core.manual_override (match_decision_id);

ALTER TABLE core.manual_override
    ADD CONSTRAINT fk_override_superseded
    FOREIGN KEY (superseded_by) REFERENCES core.manual_override(id);

-- One active (non-superseded) override per entity pair
CREATE UNIQUE INDEX idx_override_active_pair
    ON core.manual_override (entity_type, entity_id_a, entity_id_b)
    WHERE superseded_by IS NULL;

-- ============================================================================
-- Splink Run Log
-- ============================================================================
-- Tracks each execution of the Splink pipeline for auditability.

CREATE TABLE core.splink_run (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    splink_version  TEXT NOT NULL,
    model_config    JSONB NOT NULL,          -- Full Splink settings: blocking rules, comparisons, thresholds
    input_record_count BIGINT,
    pairs_compared  BIGINT,
    matches_found   BIGINT,                 -- Total pairwise matches above THRESHOLD_POSSIBLE
    auto_merged     BIGINT,                 -- Confidence >= THRESHOLD_AUTO_MERGE
    probable_matches BIGINT,                -- THRESHOLD_PROBABLE <= confidence < THRESHOLD_AUTO_MERGE
    possible_matches BIGINT,                -- THRESHOLD_POSSIBLE <= confidence < THRESHOLD_PROBABLE
    -- ^ Threshold constants defined in core/entity_resolution/splink_config.py
    duration_seconds REAL,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_splink_run_entity_type ON core.splink_run (entity_type);
CREATE INDEX idx_splink_run_status ON core.splink_run (status);

-- ============================================================================
-- Views for common queries
-- ============================================================================

-- Active match decisions (not superseded)
CREATE VIEW core.active_matches AS
SELECT *
FROM core.match_decision
WHERE superseded_by IS NULL;

-- Matches needing human review (probable but not auto-merged, no manual override)
CREATE VIEW core.matches_pending_review AS
SELECT md.*
FROM core.match_decision md
LEFT JOIN core.manual_override mo
    ON md.entity_type = mo.entity_type
    AND md.entity_id_a = mo.entity_id_a
    AND md.entity_id_b = mo.entity_id_b
WHERE md.superseded_by IS NULL
  AND md.decision IN ('probable_match', 'possible_match')
  AND mo.id IS NULL
ORDER BY md.confidence DESC;

-- ============================================================================
-- Trigger: auto-update entity_cluster.updated_at
-- ============================================================================

CREATE TRIGGER trg_cluster_updated_at
    BEFORE UPDATE ON core.entity_cluster
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
