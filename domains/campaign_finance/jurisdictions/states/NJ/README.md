# New Jersey (NJ) campaign-finance jurisdiction package

## Jurisdiction overview
New Jersey is a state-level jurisdiction (`fips: 34`) using the NJ Election Law Enforcement Commission (ELEC) e-filing system at `https://www.elec.nj.gov/`.

This package treats `config.yaml` as the single machine-readable source of truth for endpoint URLs, cadence, and field mappings.

## Freshness routing status (2026-04-28)
- Stage 1 baseline and the 2026-04-17 NJ IE investigation keep NJ on a `RESOLVED_NEGATIVE` freshness route.
- Stage 4 closes this route in existing owners (`sources.yaml`) with `nj_elec_contribution_exports` deferred.
- Reopen scraper-surface freshness work only if newer official evidence dated after 2026-04-17 overturns that closeout.

## Verified export contract (2026-03-26)
Two official source surfaces are recorded in `config.yaml`:

1. **ELEC Reports and Data Search Export API** (primary contributions source)
   - `POST https://www.njelecefilesearch.com/api/VWContributionDetail/DownlodDataCSV`
   - Returns a JSON string containing a temporary Azure Blob Storage URL
   - Blob CSV has 23 columns with structured contributor name fields

2. **ELEC Pay-to-Play Quick Download** (pay-to-play subset only)
   - Direct CSV at `https://www.elec.nj.gov/download/ptp/data/P2P_{YEAR}_Contributions.csv`
   - 22 columns focused on vendor/contractor contributions

## Package scope for Stage 6
- Implement config-driven download/parse/extract/load/cli seams for the ELEC API contributions source.
- Keep endpoint and field mapping constants in `config.yaml` and load through scraper config helpers.
- Only the ELEC API source owns the `contributions` transaction_type; the P2P source uses `pay_to_play`.
- Preserve `runner_wired` as code-derived truth from `core/refresh/runner.py`.

## Update instructions
1. Re-verify the ELEC API POST response contract and CSV header order.
2. Update `config.yaml` `last_verified_working` values when the contract is confirmed.
3. Run NJ scraper tests and config validation before any runner wiring changes.
