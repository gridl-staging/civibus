# Wisconsin (WI) campaign-finance jurisdiction package

## Jurisdiction overview
Wisconsin is a state-level jurisdiction (`fips: 55`) using the Wisconsin Elections Commission Sunshine export surface at `https://campaignfinance.wi.gov`.

This package treats `config.yaml` as the single machine-readable source of truth for endpoint URLs, cadence, and field mappings.

## Verified export contract (2026-03-26)
The official Sunshine CSV exports are:
- `https://campaignfinance.wi.gov/api/data-download/transactions`
- `https://campaignfinance.wi.gov/api/data-download/reports`
- `https://campaignfinance.wi.gov/api/data-download/committees`

Observed response contract:
- `HTTP 200`
- `content-type: text/csv`
- `content-disposition: attachment; filename=<endpoint>.csv`

## Package scope for Stage 5
- Implement config-driven download/parse/extract/load/cli seams for Wisconsin.
- Keep endpoint and field mapping constants in `config.yaml` and load through scraper config helpers.
- Preserve `runner_wired` as code-derived truth from `core/refresh/runner.py`.

## Last verified date
- Direct live ingest proof for the transaction path verified: 2026-03-27
- Additive production proof for the transaction path verified: 2026-03-28
  - Production DB/API evidence: 500 source records, 500 transactions, 32 filings

## Update instructions
1. Re-verify the three Sunshine endpoint responses and header order.
2. Update `config.yaml` `last_verified_working` values when the contract is confirmed.
3. Run Wisconsin scraper tests and config validation before any runner wiring changes.
4. Keep production proof language scoped to the transactions path until reports/committees are intentionally operationalized too.
