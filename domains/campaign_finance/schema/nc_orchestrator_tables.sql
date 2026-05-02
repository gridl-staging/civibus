-- NC Orchestrator Progress Schema
--
-- Prerequisites (loaded before this file):
--   - domains/campaign_finance/schema/tables.sql  (creates cf schema)
--
-- Schema ownership
-- This file owns exactly one table:
--   - cf.nc_orchestrator_progress
--
-- Tracks per-committee, per-window download progress for the NC statewide
-- committee orchestrator. Each row represents one committee's download state
-- within a specific run window (window_start, window_end).

CREATE TABLE cf.nc_orchestrator_progress (
    sboe_id         TEXT NOT NULL,
    window_start    DATE NOT NULL,
    window_end      DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CONSTRAINT nc_orch_status_check
                    CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    claimed_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,

    PRIMARY KEY (sboe_id, window_start, window_end)
);

CREATE INDEX idx_nc_orch_progress_claim
    ON cf.nc_orchestrator_progress (window_start, window_end, status, sboe_id)
    WHERE status = 'pending';

CREATE INDEX idx_nc_orch_progress_stale
    ON cf.nc_orchestrator_progress (window_start, window_end, status, claimed_at)
    WHERE status = 'in_progress';
