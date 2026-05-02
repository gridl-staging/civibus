-- Migration: 2026-04-25 — add orchestrator filter columns to cf.nc_committee_registry
--
-- Why: domains/campaign_finance/jurisdictions/states/NC/scraper/orchestrator_progress.py
-- (apr24_pm_3) queries `WHERE (is_active OR last_filing_date >= window_start)` to seed
-- the per-committee orchestrator progress table. The base DDL in tables.sql shipped
-- without these columns, so the orchestrator failed in production with
-- `column "is_active" does not exist` on first run (2026-04-25).
--
-- Idempotent: uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS. Safe to re-run.
--
-- is_active is a generated column derived from status_desc so the loader does not
-- need to know about orchestrator semantics — the authoritative discovery state
-- (status_desc) is the single source of truth.

ALTER TABLE cf.nc_committee_registry
    ADD COLUMN IF NOT EXISTS last_filing_date DATE;

ALTER TABLE cf.nc_committee_registry
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN
    GENERATED ALWAYS AS (status_desc LIKE 'ACTIVE%') STORED;
