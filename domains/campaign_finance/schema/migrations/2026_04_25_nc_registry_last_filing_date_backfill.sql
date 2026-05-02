-- Backfill cf.nc_committee_registry.last_filing_date from cf.filing receipt_dates.
--
-- Why this is a separate migration: the column was added 2026-04-25 with
-- DEFAULT NULL because the upstream apr24_pm_2 discovery loader does not yet
-- populate it. The orchestrator's secondary filter
--   `WHERE (is_active OR last_filing_date >= window_start)`
-- only becomes meaningful once last_filing_date is populated for at least
-- the inactive-but-recently-active committees.
--
-- Idempotent: only updates rows whose current last_filing_date is NULL or older
-- than the computed max(receipt_date).
--
-- Limitations:
--   - cf.filing only has filings for committees we have ALREADY loaded
--     transactions/IE-document-index data for. NC has 13,612 registry rows but
--     only ~50-100 committees in cf.filing as of the 2026-04-25 first orchestrator
--     prod proof. After more orchestrator passes complete, this backfill becomes
--     more valuable.
--   - Run this script after every orchestrator-batch completion (via cron or as
--     part of `core/refresh/runner.py` post-processing) to keep last_filing_date
--     current for the secondary filter.

UPDATE cf.nc_committee_registry r
SET last_filing_date = sub.max_receipt_date
FROM (
    SELECT
        c.id AS committee_id,
        MAX(f.receipt_date) AS max_receipt_date
    FROM cf.filing f
    JOIN cf.committee c ON c.id = f.committee_id
    WHERE c.state = 'NC'
      AND f.receipt_date IS NOT NULL
    GROUP BY c.id
) sub
JOIN cf.committee c ON c.id = sub.committee_id
WHERE
    -- Match the registry row to the committee. The registry stores sboe_id and
    -- committee_name; cf.committee may carry one of those identifiers in its
    -- identifiers JSON. Use committee_name as the primary join (registry uses
    -- the canonical committee name from CFOrgLkup; cf.committee.name comes from
    -- the same downstream source). Fall back to no-op when no match.
    upper(r.committee_name) = upper(c.name)
    AND (r.last_filing_date IS NULL OR r.last_filing_date < sub.max_receipt_date);
