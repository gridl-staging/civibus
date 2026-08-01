ALTER TABLE core.refresh_run
DROP CONSTRAINT IF EXISTS refresh_run_pull_status_check;

ALTER TABLE core.refresh_run
ADD CONSTRAINT refresh_run_pull_status_check
CHECK (pull_status IN ('crashed', 'empty', 'degraded', 'failed', 'success'));
