-- Migration: 2026-04-30 — normalize civic.contest_result to candidate-level ENRS contract
--
-- Why:
-- Existing environments may carry an older contest_result shape
-- (candidate_name_on_ballot + election_date + uq_contest_result_natural_key).
-- Stage 2 loader requires canonical candidate_name/votes/vote_pct/certified columns and
-- uq_contest_result_canonical for deterministic idempotent upserts.

DROP TABLE IF EXISTS civic.contest_result;

CREATE TABLE civic.contest_result (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contest_id        UUID NOT NULL REFERENCES civic.contest(id),
    source_record_id  UUID NOT NULL REFERENCES core.source_record(id),
    candidate_name    TEXT NOT NULL,
    party             TEXT,
    votes             INTEGER NOT NULL CHECK (votes >= 0),
    vote_pct          NUMERIC(6,2) CHECK (vote_pct IS NULL OR (vote_pct >= 0 AND vote_pct <= 100)),
    is_certified      BOOLEAN NOT NULL DEFAULT FALSE,
    is_winner         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_contest_result_canonical UNIQUE (contest_id, source_record_id, candidate_name)
);

CREATE INDEX idx_contest_result_contest_id ON civic.contest_result (contest_id);
CREATE INDEX idx_contest_result_source_record_id ON civic.contest_result (source_record_id);

DROP TRIGGER IF EXISTS trg_contest_result_updated_at ON civic.contest_result;
CREATE TRIGGER trg_contest_result_updated_at
    BEFORE UPDATE ON civic.contest_result
    FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
