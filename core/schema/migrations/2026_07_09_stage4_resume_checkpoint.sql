-- Add cf.stage4_resume_checkpoint for Stage 4 itcont resume state.
-- Canonical base-schema copy: domains/campaign_finance/schema/tables.sql

CREATE TABLE IF NOT EXISTS cf.stage4_resume_checkpoint (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id         UUID NOT NULL REFERENCES core.data_source(id),
    cycle                  INTEGER NOT NULL,
    file_type              TEXT NOT NULL,
    archive_fingerprint    TEXT NOT NULL,
    archive_member_name    TEXT,
    next_source_row_number BIGINT NOT NULL DEFAULT 0,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_stage4_resume_checkpoint_file_type
        CHECK (file_type IN ('itcont')),
    CONSTRAINT ck_stage4_resume_checkpoint_cycle
        CHECK (cycle >= 1900),
    CONSTRAINT ck_stage4_resume_checkpoint_next_source_row_number
        CHECK (next_source_row_number >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_stage4_resume_checkpoint_identity
    ON cf.stage4_resume_checkpoint (data_source_id, cycle, file_type);
CREATE INDEX IF NOT EXISTS idx_stage4_resume_checkpoint_data_source_id
    ON cf.stage4_resume_checkpoint (data_source_id);
CREATE INDEX IF NOT EXISTS idx_stage4_resume_checkpoint_updated_at
    ON cf.stage4_resume_checkpoint (updated_at);

DROP TRIGGER IF EXISTS trg_stage4_resume_checkpoint_updated_at ON cf.stage4_resume_checkpoint;
CREATE TRIGGER trg_stage4_resume_checkpoint_updated_at
    BEFORE UPDATE ON cf.stage4_resume_checkpoint
    FOR EACH ROW
    EXECUTE FUNCTION core.set_updated_at();
