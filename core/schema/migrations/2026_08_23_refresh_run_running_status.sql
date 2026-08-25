-- Let core.refresh_run hold an in-flight attempt.
--
-- A run is now committed at start with pull_status='running' and no
-- completed_at, then updated in place to a terminal status when it finishes.
-- The two facts are paired: 'running' is exactly the state with no
-- completed_at, so a crashed runner that never wrote its terminal row stays
-- visibly 'running' rather than vanishing from the ledger.

ALTER TABLE core.refresh_run
ALTER COLUMN completed_at DROP NOT NULL;

ALTER TABLE core.refresh_run
DROP CONSTRAINT IF EXISTS refresh_run_pull_status_check;

ALTER TABLE core.refresh_run
ADD CONSTRAINT refresh_run_pull_status_check
CHECK (pull_status IN ('crashed', 'empty', 'degraded', 'failed', 'success', 'running'));

ALTER TABLE core.refresh_run
DROP CONSTRAINT IF EXISTS refresh_run_running_completed_at_check;

ALTER TABLE core.refresh_run
ADD CONSTRAINT refresh_run_running_completed_at_check
CHECK ((pull_status = 'running') = (completed_at IS NULL));

-- idx_refresh_run_job_key_completed_at and idx_refresh_run_completed_at stay
-- plain btrees on completed_at DESC rather than becoming partial indexes on
-- WHERE completed_at IS NOT NULL. Postgres btrees index NULLs, but in-flight
-- and interrupted attempts are expected to remain sparse relative to terminal
-- history. A partial index has no demonstrated query or size benefit here and
-- would add a second index shape to keep in sync with provenance.sql.
